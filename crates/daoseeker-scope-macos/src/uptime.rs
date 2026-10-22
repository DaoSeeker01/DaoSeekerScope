//! Checked calendar-derived uptime; no zero-boot fallback or dynamic cache.
use daoseeker_scope_core::*;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Boot {
    seconds: i64,
    microseconds: i64,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Failure {
    Errno(i32),
    Clock,
    Invalid,
    Changed,
}
impl Failure {
    fn observed(self) -> Observed<u64> {
        let (state, reason) = match self {
            Self::Errno(1 | 13) => (Availability::Restricted, ReasonCode::PermissionDenied),
            Self::Errno(2) => (Availability::Unavailable, ReasonCode::NotPresent),
            Self::Errno(45) => (Availability::Unsupported, ReasonCode::NotSupported),
            Self::Errno(22) | Self::Invalid => (Availability::Unavailable, ReasonCode::InvalidData),
            Self::Errno(4 | 12 | 16 | 35) | Self::Changed => (
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            Self::Errno(_) | Self::Clock => (Availability::Unavailable, ReasonCode::Unknown),
        };
        Observed::missing(state, Source::Sysctl, reason).expect("missing observation")
    }
}
fn boot_reply(seconds: i64, microseconds: i64, length: usize) -> Result<Boot, Failure> {
    if length != 16 || seconds < 0 || !(0..1_000_000).contains(&microseconds) {
        Err(Failure::Invalid)
    } else {
        Ok(Boot {
            seconds,
            microseconds,
        })
    }
}
fn clock_reply(seconds: i64) -> Result<i64, Failure> {
    match seconds {
        -1 => Err(Failure::Clock),
        ..0 => Err(Failure::Invalid),
        _ => Ok(seconds),
    }
}
trait Api {
    fn boot(&mut self) -> Result<Boot, Failure>;
    fn now(&mut self) -> Result<i64, Failure>;
}
fn elapsed(before: Boot, now: i64, after: Boot) -> Result<u64, Failure> {
    if before != after {
        return Err(Failure::Changed);
    }
    now.checked_sub(before.seconds)
        .and_then(|n| u64::try_from(n).ok())
        .ok_or(Failure::Invalid)
}
fn read_checked<T>(
    read: impl FnOnce() -> Result<T, Failure>,
    check: &mut impl FnMut() -> Result<(), ScopeError>,
) -> Result<Result<T, Failure>, ScopeError> {
    check()?;
    let result = read();
    check()?;
    Ok(result)
}
fn collect_with(
    api: &mut impl Api,
    mut check: impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<u64>, ScopeError> {
    let before = match read_checked(|| api.boot(), &mut check)? {
        Ok(value) => value,
        Err(error) => return Ok(error.observed()),
    };
    let now = match read_checked(|| api.now(), &mut check)? {
        Ok(value) => value,
        Err(error) => return Ok(error.observed()),
    };
    let after = match read_checked(|| api.boot(), &mut check)? {
        Ok(value) => value,
        Err(error) => return Ok(error.observed()),
    };
    match elapsed(before, now, after) {
        Ok(seconds) => Ok(Observed::available(
            seconds,
            Source::Sysctl,
            Timestamp::now()?,
        )),
        Err(error) => Ok(error.observed()),
    }
}

#[cfg(target_os = "macos")]
mod native {
    use super::*;
    use std::{io, mem, ptr};
    const _: () = {
        assert!(mem::size_of::<libc::time_t>() == 8);
        assert!(mem::size_of::<libc::timeval>() == 16);
        assert!(mem::offset_of!(libc::timeval, tv_sec) == 0);
        assert!(mem::offset_of!(libc::timeval, tv_usec) == 8);
    };
    struct NativeApi;
    impl Api for NativeApi {
        fn boot(&mut self) -> Result<Boot, Failure> {
            let mut mib = [libc::CTL_KERN, libc::KERN_BOOTTIME];
            let mut value = libc::timeval {
                tv_sec: 0,
                tv_usec: 0,
            };
            let mut length = mem::size_of::<libc::timeval>();
            // SAFETY: fixed public read-only MIB, initialized aligned timeval and exact
            // writable length. No pointer is retained; never consume failed output.
            if unsafe {
                libc::sysctl(
                    mib.as_mut_ptr(),
                    2,
                    (&mut value as *mut libc::timeval).cast(),
                    &mut length,
                    ptr::null_mut(),
                    0,
                )
            } != 0
            {
                return Err(Failure::Errno(
                    io::Error::last_os_error().raw_os_error().unwrap_or(0),
                ));
            }
            boot_reply(value.tv_sec, i64::from(value.tv_usec), length)
        }
        fn now(&mut self) -> Result<i64, Failure> {
            // SAFETY: NULL requests only the return value; no pointer is dereferenced.
            // time(-1) has no guaranteed errno, so do not consume stale errno.
            clock_reply(unsafe { libc::time(ptr::null_mut()) })
        }
    }
    pub(crate) fn collect(context: &CollectContext) -> Result<Observed<u64>, ScopeError> {
        collect_with(&mut NativeApi, || context.check())
    }
    #[cfg(test)]
    #[test]
    fn public_boot_time_and_time_match_native_sdk_contract() {
        let field = collect_with(&mut NativeApi, || Ok(())).expect("context");
        assert_eq!(field.availability(), Availability::Available, "{field:?}");
        assert_eq!(field.source(), Source::Sysctl);
        assert!(field.value().is_some());
    }
}
#[cfg(target_os = "macos")]
pub(crate) use native::collect;

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::VecDeque;
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };

    enum Call {
        Boot(Result<Boot, Failure>),
        Now(Result<i64, Failure>),
    }
    struct Fake {
        calls: VecDeque<Call>,
        reads: Arc<AtomicUsize>,
    }
    impl Fake {
        fn new(calls: Vec<Call>) -> Self {
            Self {
                calls: calls.into(),
                reads: Arc::new(AtomicUsize::new(0)),
            }
        }
        fn healthy(boot: Boot, now: i64) -> Self {
            Self::new(vec![
                Call::Boot(Ok(boot)),
                Call::Now(Ok(now)),
                Call::Boot(Ok(boot)),
            ])
        }
    }
    impl Api for Fake {
        fn boot(&mut self) -> Result<Boot, Failure> {
            self.reads.fetch_add(1, Ordering::SeqCst);
            match self.calls.pop_front().expect("unexpected extra call") {
                Call::Boot(result) => result,
                _ => panic!("wrong call order"),
            }
        }
        fn now(&mut self) -> Result<i64, Failure> {
            self.reads.fetch_add(1, Ordering::SeqCst);
            match self.calls.pop_front().expect("unexpected extra call") {
                Call::Now(result) => result,
                _ => panic!("wrong call order"),
            }
        }
    }
    fn boot() -> Boot {
        boot_reply(100, 500_000, 16).expect("boot")
    }
    fn missing(field: &Observed<u64>, reason: ReasonCode) {
        assert_eq!(field.value(), None);
        assert_eq!(field.observed_at(), None);
        assert_eq!(field.reason(), Some(reason));
        assert_eq!(field.source(), Source::Sysctl);
    }
    #[test]
    fn fixed_reply_shape_and_signed_values_are_validated() {
        for length in [0, 1, 12, 15, 17, usize::MAX] {
            assert_eq!(boot_reply(100, 0, length), Err(Failure::Invalid));
        }
        for (seconds, micros) in [
            (-1, 0),
            (i64::MIN, 0),
            (1, -1),
            (1, 1_000_000),
            (1, i64::MAX),
        ] {
            assert_eq!(boot_reply(seconds, micros, 16), Err(Failure::Invalid));
        }
        assert!(boot_reply(0, 0, 16).is_ok());
        assert!(boot_reply(i64::MAX, 999_999, 16).is_ok());
        assert_eq!(clock_reply(-1), Err(Failure::Clock));
        assert_eq!(clock_reply(-2), Err(Failure::Invalid));
        assert_eq!(clock_reply(i64::MIN), Err(Failure::Invalid));
        assert_eq!(clock_reply(0), Ok(0));
        assert_eq!(clock_reply(i64::MAX), Ok(i64::MAX));
    }
    #[test]
    fn whole_seconds_keep_zero_and_exact_large_integers_without_float() {
        for (start, now, expected) in [
            (0, 0, 0),
            (100, 100, 0),
            (100, 101, 1),
            (0, i64::MAX, i64::MAX as u64),
        ] {
            let b = boot_reply(start, 999_999, 16).expect("boot");
            let mut api = Fake::healthy(b, now);
            let field = collect_with(&mut api, || Ok(())).expect("read");
            assert_eq!(field.value(), Some(&expected));
            assert_eq!(field.availability(), Availability::Available);
            assert_eq!(field.source(), Source::Sysctl);
            assert_eq!(field.reason(), None);
            assert!(field.observed_at().is_some());
            assert_eq!(api.reads.load(Ordering::SeqCst), 3);
        }
        assert_eq!(elapsed(boot(), 99, boot()), Err(Failure::Invalid));
    }
    #[test]
    fn errno_namespace_and_missing_metadata_are_explicit() {
        for (error, state, reason) in [
            (
                Failure::Errno(1),
                Availability::Restricted,
                ReasonCode::PermissionDenied,
            ),
            (
                Failure::Errno(13),
                Availability::Restricted,
                ReasonCode::PermissionDenied,
            ),
            (
                Failure::Errno(2),
                Availability::Unavailable,
                ReasonCode::NotPresent,
            ),
            (
                Failure::Errno(45),
                Availability::Unsupported,
                ReasonCode::NotSupported,
            ),
            (
                Failure::Errno(22),
                Availability::Unavailable,
                ReasonCode::InvalidData,
            ),
            (
                Failure::Invalid,
                Availability::Unavailable,
                ReasonCode::InvalidData,
            ),
            (
                Failure::Errno(4),
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            (
                Failure::Errno(12),
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            (
                Failure::Errno(16),
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            (
                Failure::Errno(35),
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            (
                Failure::Errno(0),
                Availability::Unavailable,
                ReasonCode::Unknown,
            ),
            (
                Failure::Errno(9999),
                Availability::Unavailable,
                ReasonCode::Unknown,
            ),
            (
                Failure::Clock,
                Availability::Unavailable,
                ReasonCode::Unknown,
            ),
        ] {
            let field = error.observed();
            missing(&field, reason);
            assert_eq!(field.availability(), state);
        }
    }
    #[test]
    fn each_failed_call_short_circuits_without_consuming_later_output() {
        let b = boot();
        let mut cases = [
            (
                Fake::new(vec![Call::Boot(Err(Failure::Errno(13)))]),
                1,
                ReasonCode::PermissionDenied,
            ),
            (
                Fake::new(vec![Call::Boot(Ok(b)), Call::Now(clock_reply(-1))]),
                2,
                ReasonCode::Unknown,
            ),
            (
                Fake::new(vec![
                    Call::Boot(Ok(b)),
                    Call::Now(Ok(101)),
                    Call::Boot(Err(Failure::Errno(12))),
                ]),
                3,
                ReasonCode::TemporarilyUnavailable,
            ),
        ];
        for (api, expected, reason) in &mut cases {
            let field = collect_with(api, || Ok(())).expect("field failure isolated");
            missing(&field, *reason);
            assert_eq!(api.reads.load(Ordering::SeqCst), *expected);
            assert!(api.calls.is_empty());
        }
    }
    #[test]
    fn boot_changes_in_either_component_are_temporary_without_retry() {
        let b = boot();
        for after in [
            Boot { seconds: 101, ..b },
            Boot {
                microseconds: 500_001,
                ..b
            },
        ] {
            let mut api = Fake::new(vec![
                Call::Boot(Ok(b)),
                Call::Now(Ok(102)),
                Call::Boot(Ok(after)),
            ]);
            let field = collect_with(&mut api, || Ok(())).expect("isolated change");
            missing(&field, ReasonCode::TemporarilyUnavailable);
            assert_eq!(api.reads.load(Ordering::SeqCst), 3);
        }
    }
    #[test]
    fn failure_discards_previous_value_and_next_read_recovers_without_warmup() {
        let b = boot();
        let mut api = Fake::new(vec![
            Call::Boot(Ok(b)),
            Call::Now(Ok(101)),
            Call::Boot(Ok(b)),
            Call::Boot(Err(Failure::Errno(13))),
            Call::Boot(Ok(b)),
            Call::Now(Ok(103)),
            Call::Boot(Ok(b)),
        ]);
        assert_eq!(collect_with(&mut api, || Ok(())).unwrap().value(), Some(&1));
        missing(
            &collect_with(&mut api, || Ok(())).unwrap(),
            ReasonCode::PermissionDenied,
        );
        assert_eq!(collect_with(&mut api, || Ok(())).unwrap().value(), Some(&3));
        assert_eq!(api.reads.load(Ordering::SeqCst), 7);
    }
    #[test]
    fn context_errors_around_each_call_stop_publication_and_further_calls() {
        for code in [ErrorCode::Cancelled, ErrorCode::Timeout] {
            for reject_at in 1..=6 {
                let mut api = Fake::healthy(boot(), 101);
                let mut checks = 0;
                let result = collect_with(&mut api, || {
                    checks += 1;
                    if checks == reject_at {
                        Err(ScopeError::new(code))
                    } else {
                        Ok(())
                    }
                });
                assert_eq!(result.expect_err("context error").code, code);
                assert_eq!(checks, reject_at);
                assert_eq!(api.reads.load(Ordering::SeqCst), reject_at / 2);
            }
        }
    }
    struct TestBackend {
        api: Fake,
        static_reads: Arc<AtomicUsize>,
    }
    impl Backend for TestBackend {
        fn name(&self) -> &'static str {
            "uptime_test"
        }
        fn capabilities(&self) -> Capabilities {
            vec![Capability::new(
                "runtime.uptime_seconds",
                CapabilityLevel::Partial,
                Source::Sysctl,
            )]
        }
        fn collect_static(
            &mut self,
            context: &CollectContext,
        ) -> Result<StaticSnapshot, ScopeError> {
            context.check()?;
            self.static_reads.fetch_add(1, Ordering::SeqCst);
            assert_eq!(self.api.reads.load(Ordering::SeqCst), 0);
            let mut result = StaticSnapshot::default();
            result.system.cpu.brand =
                Observed::available("fixture".into(), Source::Custom, Timestamp(1));
            Ok(result)
        }
        fn refresh_dynamic(
            &mut self,
            context: &CollectContext,
        ) -> Result<DynamicSnapshot, ScopeError> {
            let mut result = DynamicSnapshot::default();
            result.runtime.uptime_seconds = collect_with(&mut self.api, || context.check())?;
            Ok(result)
        }
    }
    #[test]
    fn hardware_keeps_static_cache_and_isolates_uptime_failure_and_recovery() {
        let b = boot();
        let api = Fake::new(vec![
            Call::Boot(Ok(b)),
            Call::Now(Ok(101)),
            Call::Boot(Ok(b)),
            Call::Boot(Err(Failure::Errno(13))),
            Call::Boot(Ok(b)),
            Call::Now(Ok(103)),
            Call::Boot(Ok(b)),
        ]);
        let reads = api.reads.clone();
        let static_reads = Arc::new(AtomicUsize::new(0));
        let hardware = HardwareBuilder::default()
            .with_backend(
                100,
                TestBackend {
                    api,
                    static_reads: static_reads.clone(),
                },
            )
            .build()
            .unwrap();
        let initial = hardware.collect().unwrap();
        assert_eq!(initial.dynamic.runtime.uptime_seconds.value(), Some(&1));
        missing(
            &hardware.refresh_dynamic().unwrap().runtime.uptime_seconds,
            ReasonCode::PermissionDenied,
        );
        let recovered = hardware.collect().unwrap();
        assert_eq!(recovered.static_info, initial.static_info);
        assert_eq!(recovered.dynamic.runtime.uptime_seconds.value(), Some(&3));
        assert_eq!(static_reads.load(Ordering::SeqCst), 1);
        assert_eq!(reads.load(Ordering::SeqCst), 7);
    }
}
