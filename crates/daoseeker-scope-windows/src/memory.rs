//! Fresh fixed-size physical-memory reads; failures never consume API output.
use daoseeker_scope_core::*;

#[derive(Clone, Copy)]
struct Sample {
    total: u64,
    available: u64,
}
trait Api: Send + 'static {
    fn read(&mut self) -> Result<Sample, u32>;
}
fn failure(code: u32) -> Observed<u64> {
    match code {
        5 => Observed::restricted(Source::Win32, ReasonCode::PermissionDenied),
        13 | 87 => Observed::unavailable(Source::Win32, ReasonCode::InvalidData),
        8 | 14 | 170 | 1237 => {
            Observed::unavailable(Source::Win32, ReasonCode::TemporarilyUnavailable)
        }
        _ => Observed::unavailable(Source::Win32, ReasonCode::Unknown),
    }
}
fn read_with(
    api: &mut impl Api,
    mut check: impl FnMut() -> Result<(), ScopeError>,
) -> Result<(Observed<u64>, Observed<u64>), ScopeError> {
    check()?;
    let raw = api.read();
    check()?;
    let sample = match raw {
        Ok(sample) => sample,
        Err(code) => return Ok((failure(code), failure(code))),
    };
    if sample.total == 0 {
        return Ok((failure(13), failure(13)));
    }
    let at = Timestamp::now()?;
    let total = Observed::available(sample.total, Source::Win32, at);
    let available = if sample.available <= sample.total {
        Observed::available(sample.available, Source::Win32, at)
    } else {
        failure(13)
    };
    Ok((total, available))
}
struct MemoryBackend<A> {
    api: A,
    cached_total: Option<u64>,
}
impl<A: Api> MemoryBackend<A> {
    fn new(api: A) -> Self {
        Self {
            api,
            cached_total: None,
        }
    }
}
impl<A: Api> Backend for MemoryBackend<A> {
    fn name(&self) -> &'static str {
        "windows_memory"
    }
    fn capabilities(&self) -> Capabilities {
        ["system.memory.total_usable_bytes", "memory_available_bytes"]
            .into_iter()
            .map(|field| Capability::new(field, CapabilityLevel::Supported, Source::Win32))
            .collect()
    }
    fn collect_static(&mut self, context: &CollectContext) -> Result<StaticSnapshot, ScopeError> {
        let (total, _) = read_with(&mut self.api, || context.check())?;
        self.cached_total = total.value().copied();
        let mut result = StaticSnapshot::default();
        result.system.memory.total_usable_bytes = total;
        Ok(result)
    }
    fn refresh_dynamic(&mut self, context: &CollectContext) -> Result<DynamicSnapshot, ScopeError> {
        let (total, available) = read_with(&mut self.api, || context.check())?;
        let mut result = DynamicSnapshot::default();
        result.memory_available_bytes = if available.value().is_some()
            && self.cached_total.is_some()
            && total.value().copied() != self.cached_total
        {
            Observed::unavailable(Source::Win32, ReasonCode::TemporarilyUnavailable)
        } else {
            available
        };
        Ok(result)
    }
}

#[cfg(target_os = "windows")]
mod native {
    use super::*;
    use windows_sys::Win32::{
        Foundation::GetLastError,
        System::SystemInformation::{GlobalMemoryStatusEx, MEMORYSTATUSEX},
    };
    struct NativeApi;
    impl Api for NativeApi {
        fn read(&mut self) -> Result<Sample, u32> {
            let mut status = MEMORYSTATUSEX {
                dwLength: size_of::<MEMORYSTATUSEX>() as u32,
                ..Default::default()
            };
            // SAFETY: initialized, aligned live SDK structure with its exact size;
            // synchronous API retains no pointer. Failed output is never inspected.
            if unsafe { GlobalMemoryStatusEx(&mut status) } == 0 {
                // SAFETY: reads this thread's error immediately after the failed call.
                return Err(unsafe { GetLastError() });
            }
            if status.dwLength as usize != size_of::<MEMORYSTATUSEX>() {
                return Err(13);
            }
            Ok(Sample {
                total: status.ullTotalPhys,
                available: status.ullAvailPhys,
            })
        }
    }
    /// Fresh Windows physical-memory observations with explicit API failure states.
    /// The facade registers this automatically; standalone adapters must register it.
    pub struct WindowsMemoryBackend(MemoryBackend<NativeApi>);
    impl WindowsMemoryBackend {
        pub fn new() -> Self {
            Self(MemoryBackend::new(NativeApi))
        }
    }
    impl Default for WindowsMemoryBackend {
        fn default() -> Self {
            Self::new()
        }
    }
    impl Backend for WindowsMemoryBackend {
        fn name(&self) -> &'static str {
            self.0.name()
        }
        fn capabilities(&self) -> Capabilities {
            self.0.capabilities()
        }
        fn collect_static(
            &mut self,
            context: &CollectContext,
        ) -> Result<StaticSnapshot, ScopeError> {
            self.0.collect_static(context)
        }
        fn refresh_dynamic(
            &mut self,
            context: &CollectContext,
        ) -> Result<DynamicSnapshot, ScopeError> {
            self.0.refresh_dynamic(context)
        }
    }
    #[test]
    fn sdk_memory_layout_matches_fixed_public_structure() {
        assert_eq!(size_of::<MEMORYSTATUSEX>(), 64);
        assert_eq!(std::mem::offset_of!(MEMORYSTATUSEX, ullTotalPhys), 8);
        assert_eq!(std::mem::offset_of!(MEMORYSTATUSEX, ullAvailPhys), 16);
    }
}
#[cfg(target_os = "windows")]
pub use native::WindowsMemoryBackend;

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        collections::VecDeque,
        sync::{
            Arc, Mutex,
            atomic::{AtomicUsize, Ordering},
        },
    };
    #[derive(Clone)]
    struct Fake {
        values: Arc<Mutex<VecDeque<Result<Sample, u32>>>>,
        calls: Arc<AtomicUsize>,
    }
    impl Api for Fake {
        fn read(&mut self) -> Result<Sample, u32> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            self.values
                .lock()
                .expect("fixture lock")
                .pop_front()
                .expect("fixture read")
        }
    }
    fn fake(values: Vec<Result<Sample, u32>>) -> Fake {
        Fake {
            values: Arc::new(Mutex::new(values.into())),
            calls: Arc::new(AtomicUsize::new(0)),
        }
    }
    fn good(total: u64, available: u64) -> Result<Sample, u32> {
        Ok(Sample { total, available })
    }
    fn build(api: Fake) -> Hardware {
        HardwareBuilder::default()
            .with_backend(100, MemoryBackend::new(api))
            .build()
            .expect("hardware")
    }
    #[test]
    fn every_dynamic_request_reads_again_while_static_total_is_cached() {
        let api = fake(vec![
            good(100, 99),
            good(100, 80),
            good(100, 50),
            good(100, 0),
        ]);
        let hw = build(api.clone());
        let first = hw.collect().expect("first");
        assert_eq!(
            first.static_info.system.memory.total_usable_bytes.value(),
            Some(&100)
        );
        assert_eq!(first.dynamic.memory_available_bytes.value(), Some(&80));
        let next = hw.refresh_dynamic().expect("refresh");
        assert_eq!(next.memory_available_bytes.value(), Some(&50));
        let last = hw.collect().expect("cached static");
        assert_eq!(
            last.static_info.system.memory.total_usable_bytes,
            first.static_info.system.memory.total_usable_bytes
        );
        assert_eq!(last.dynamic.memory_available_bytes.value(), Some(&0));
        assert_eq!(last.dynamic.memory_available_bytes.source(), Source::Win32);
        assert_eq!(api.calls.load(Ordering::SeqCst), 4);
    }
    #[test]
    fn failed_refresh_never_reuses_a_value_and_next_success_recovers() {
        let api = fake(vec![
            good(100, 90),
            good(100, 75),
            Err(5),
            Err(13),
            good(100, 0),
        ]);
        let hw = build(api.clone());
        assert_eq!(
            hw.collect()
                .expect("collect")
                .dynamic
                .memory_available_bytes
                .value(),
            Some(&75)
        );
        for (state, reason) in [
            (Availability::Restricted, ReasonCode::PermissionDenied),
            (Availability::Unavailable, ReasonCode::InvalidData),
        ] {
            let bad = hw
                .refresh_dynamic()
                .expect("field failure")
                .memory_available_bytes;
            assert_eq!(bad.availability(), state);
            assert_eq!(bad.reason(), Some(reason));
            assert!(bad.value().is_none() && bad.observed_at().is_none());
        }
        let recovered = hw
            .refresh_dynamic()
            .expect("recovery")
            .memory_available_bytes;
        assert_eq!(recovered.value(), Some(&0));
        assert!(recovered.observed_at().is_some() && recovered.reason().is_none());
        assert_eq!(api.calls.load(Ordering::SeqCst), 5);
        let cap = hw
            .capabilities()
            .into_iter()
            .find(|c| c.field == "memory_available_bytes")
            .expect("capability");
        assert_eq!(cap.level, CapabilityLevel::Supported);
    }
    #[test]
    fn static_failure_is_cached_but_does_not_block_fresh_available_memory() {
        let api = fake(vec![Err(5), good(100, 70), good(100, 60)]);
        let hw = build(api.clone());
        let first = hw.collect().expect("first");
        assert_eq!(
            first.static_info.system.memory.total_usable_bytes.reason(),
            Some(ReasonCode::PermissionDenied)
        );
        assert_eq!(first.dynamic.memory_available_bytes.value(), Some(&70));
        let next = hw.collect().expect("second");
        assert_eq!(first.static_info, next.static_info);
        assert_eq!(next.dynamic.memory_available_bytes.value(), Some(&60));
        assert_eq!(api.calls.load(Ordering::SeqCst), 3);
    }
    #[test]
    fn changed_total_requires_recreation_even_when_available_fits_cached_total() {
        let hw = build(fake(vec![
            good(100, 90),
            good(200, 80),
            good(50, 40),
            good(100, 70),
        ]));
        let first = hw.collect().expect("collect");
        assert_eq!(
            first.dynamic.memory_available_bytes.reason(),
            Some(ReasonCode::TemporarilyUnavailable)
        );
        assert_eq!(
            hw.refresh_dynamic()
                .expect("changed total")
                .memory_available_bytes
                .reason(),
            Some(ReasonCode::TemporarilyUnavailable)
        );
        assert_eq!(
            hw.refresh_dynamic()
                .expect("recovered total")
                .memory_available_bytes
                .value(),
            Some(&70)
        );
        let recreated = build(fake(vec![good(200, 150), good(200, 140)]))
            .collect()
            .expect("recreated");
        assert_eq!(
            recreated
                .static_info
                .system
                .memory
                .total_usable_bytes
                .value(),
            Some(&200)
        );
        assert_eq!(recreated.dynamic.memory_available_bytes.value(), Some(&140));
    }
    #[test]
    fn invalid_total_and_available_are_isolated_and_integer_bounds_do_not_overflow() {
        let mut api = fake(vec![
            good(0, 0),
            good(0, 1),
            good(10, 11),
            good(u64::MAX, u64::MAX),
            good(1, 0),
        ]);
        for _ in 0..2 {
            let (total, available) = read_with(&mut api, || Ok(())).expect("invalid fields");
            assert!(total.value().is_none() && available.value().is_none());
            assert_eq!(total.reason(), Some(ReasonCode::InvalidData));
        }
        let (total, available) = read_with(&mut api, || Ok(())).expect("isolated");
        assert_eq!(total.value(), Some(&10));
        assert_eq!(available.reason(), Some(ReasonCode::InvalidData));
        let (total, available) = read_with(&mut api, || Ok(())).expect("no arithmetic");
        assert_eq!(total.value(), Some(&u64::MAX));
        assert_eq!(available.value(), Some(&u64::MAX));
        let (_, zero) = read_with(&mut api, || Ok(())).expect("genuine zero");
        assert_eq!(zero.value(), Some(&0));
    }
    #[test]
    fn error_codes_are_explicit_and_never_invent_sandbox_or_permission() {
        for code in [0, 5, 8, 13, 14, 87, 170, 1237, 9999] {
            let expected = match code {
                5 => ReasonCode::PermissionDenied,
                13 | 87 => ReasonCode::InvalidData,
                8 | 14 | 170 | 1237 => ReasonCode::TemporarilyUnavailable,
                _ => ReasonCode::Unknown,
            };
            let mut api = fake(vec![Err(code)]);
            let (total, available) = read_with(&mut api, || Ok(())).expect("error fields");
            assert_eq!(total, available);
            assert_eq!(total.source(), Source::Win32);
            assert_eq!(total.reason(), Some(expected));
            assert_eq!(
                total.availability(),
                if code == 5 {
                    Availability::Restricted
                } else {
                    Availability::Unavailable
                }
            );
            assert!(total.value().is_none() && total.observed_at().is_none());
        }
    }
    #[test]
    fn cancellation_and_timeout_boundaries_do_not_publish_or_repeat_reads() {
        let mut api = fake(vec![good(100, 50)]);
        let err =
            read_with(&mut api, || Err(ScopeError::new(ErrorCode::Cancelled))).expect_err("cancel");
        assert_eq!(err.code, ErrorCode::Cancelled);
        assert_eq!(api.calls.load(Ordering::SeqCst), 0);
        let mut checks = 0;
        let err = read_with(&mut api, || {
            checks += 1;
            if checks == 2 {
                Err(ScopeError::new(ErrorCode::Timeout))
            } else {
                Ok(())
            }
        })
        .expect_err("timeout after read");
        assert_eq!(err.code, ErrorCode::Timeout);
        assert_eq!(api.calls.load(Ordering::SeqCst), 1);
    }
    #[test]
    fn capability_restriction_and_recovery_follow_each_field_without_stale_fallback() {
        let hw = build(fake(vec![good(100, 90), Err(5), good(100, 60)]));
        let first = hw.collect().expect("field failure");
        assert_eq!(
            first.static_info.system.memory.total_usable_bytes.value(),
            Some(&100)
        );
        let cap = hw
            .capabilities()
            .into_iter()
            .find(|c| c.field == "memory_available_bytes")
            .expect("cap");
        assert_eq!(cap.level, CapabilityLevel::Restricted);
        assert_eq!(cap.source, Source::Win32);
        assert_eq!(cap.reason, Some(ReasonCode::PermissionDenied));
        assert_eq!(
            hw.refresh_dynamic()
                .expect("recovery")
                .memory_available_bytes
                .value(),
            Some(&60)
        );
        let cap = hw
            .capabilities()
            .into_iter()
            .find(|c| c.field == "memory_available_bytes")
            .expect("cap");
        assert_eq!(cap.level, CapabilityLevel::Supported);
        assert!(cap.reason.is_none());
    }
}
