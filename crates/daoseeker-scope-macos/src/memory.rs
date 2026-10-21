//! Checked public memory queries; OS VM statistics may be rate-limited/cached.
use daoseeker_scope_core::*;
const VM_REV1_WORDS: u32 = 38;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Failure {
    Errno(i32),
    Mach(i32),
    Invalid,
}
impl Failure {
    fn observed(self, source: Source) -> Observed<u64> {
        let (state, reason) = match self {
            Self::Errno(1 | 13) | Self::Mach(2 | 8) => {
                (Availability::Restricted, ReasonCode::PermissionDenied)
            }
            Self::Invalid | Self::Errno(22) | Self::Mach(4 | 18) => {
                (Availability::Unavailable, ReasonCode::InvalidData)
            }
            Self::Errno(12 | 16 | 35) | Self::Mach(6) => (
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            Self::Errno(2) => (Availability::Unavailable, ReasonCode::NotPresent),
            Self::Errno(45 | 102) | Self::Mach(46) => {
                (Availability::Unsupported, ReasonCode::NotSupported)
            }
            _ => (Availability::Unavailable, ReasonCode::Unknown),
        };
        Observed::missing(state, source, reason).expect("missing observation")
    }
}
#[derive(Debug, Clone, Copy)]
struct Pages {
    size: u64,
    active: u32,
    inactive: u32,
    free: u32,
    speculative: u32,
}
fn vm_count(count: u32) -> Result<(), Failure> {
    if count == VM_REV1_WORDS {
        Ok(())
    } else {
        Err(Failure::Invalid)
    }
}
fn total_reply(bytes: u64, length: usize) -> Result<u64, Failure> {
    if bytes == 0 || length != size_of::<u64>() {
        Err(Failure::Invalid)
    } else {
        Ok(bytes)
    }
}
fn available(pages: Pages, total: u64) -> Result<u64, Failure> {
    if total == 0 || !pages.size.is_power_of_two() || pages.speculative > pages.free {
        return Err(Failure::Invalid);
    }
    // SDK free_count already includes speculative; never add it again.
    let count = u64::from(pages.active) + u64::from(pages.inactive) + u64::from(pages.free);
    let bytes = count.checked_mul(pages.size).ok_or(Failure::Invalid)?;
    if bytes > total {
        Err(Failure::Invalid)
    } else {
        Ok(bytes)
    }
}
trait Api: Send + 'static {
    fn total(&mut self) -> Result<u64, Failure>;
    fn pages(&mut self) -> Result<Pages, Failure>;
}
fn checked_total(
    api: &mut impl Api,
    check: &mut impl FnMut() -> Result<(), ScopeError>,
) -> Result<Result<u64, Failure>, ScopeError> {
    check()?;
    let total = api
        .total()
        .and_then(|n| if n == 0 { Err(Failure::Invalid) } else { Ok(n) });
    check()?;
    Ok(total)
}
fn dynamic_with(
    api: &mut impl Api,
    cached_total: Option<u64>,
    mut check: impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<u64>, ScopeError> {
    let total = match checked_total(api, &mut check)? {
        Ok(total) => total,
        Err(error) => return Ok(error.observed(Source::AppleApi)),
    };
    if cached_total.is_some_and(|cached| cached != total) {
        return Ok(Observed::unavailable(
            Source::AppleApi,
            ReasonCode::TemporarilyUnavailable,
        ));
    }
    check()?;
    let raw = api.pages();
    check()?;
    Ok(match raw.and_then(|pages| available(pages, total)) {
        Ok(bytes) => Observed::available(bytes, Source::AppleApi, Timestamp::now()?),
        Err(error) => error.observed(Source::AppleApi),
    })
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
        "macos_memory"
    }
    fn capabilities(&self) -> Capabilities {
        [
            ("system.memory.total_usable_bytes", Source::Sysctl),
            ("memory_available_bytes", Source::AppleApi),
        ]
        .into_iter()
        .map(|(field, source)| Capability::new(field, CapabilityLevel::Partial, source))
        .collect()
    }
    fn collect_static(&mut self, context: &CollectContext) -> Result<StaticSnapshot, ScopeError> {
        let total = checked_total(&mut self.api, &mut || context.check())?;
        self.cached_total = total.ok();
        let mut result = StaticSnapshot::default();
        result.system.memory.total_usable_bytes = match total {
            Ok(bytes) => Observed::available(bytes, Source::Sysctl, Timestamp::now()?),
            Err(error) => error.observed(Source::Sysctl),
        };
        Ok(result)
    }
    fn refresh_dynamic(&mut self, context: &CollectContext) -> Result<DynamicSnapshot, ScopeError> {
        let mut result = DynamicSnapshot::default();
        result.memory_available_bytes =
            dynamic_with(&mut self.api, self.cached_total, || context.check())?;
        Ok(result)
    }
}

// Own exactly one acquired host right. Take before release, including errors.
struct HostRight<F: FnMut(u32) -> Result<(), Failure>> {
    port: Option<u32>,
    release: F,
}
impl<F: FnMut(u32) -> Result<(), Failure>> HostRight<F> {
    fn close(&mut self) -> Result<(), Failure> {
        match self.port.take() {
            Some(port) => (self.release)(port),
            None => Ok(()),
        }
    }
}
impl<F: FnMut(u32) -> Result<(), Failure>> Drop for HostRight<F> {
    fn drop(&mut self) {
        let _ = self.close();
    }
}

#[cfg(target_os = "macos")]
mod native {
    use super::*;
    use std::{io, mem, ptr};
    // The binding may contain fields newer than the running kernel/SDK. Request
    // only this stable prefix and verify its layout at compile time, including
    // cross builds where native assertions cannot run.
    const _: () = {
        assert!(mem::size_of::<libc::integer_t>() == 4);
        assert!(mem::size_of::<libc::vm_statistics64>() >= VM_REV1_WORDS as usize * 4);
        assert!(mem::offset_of!(libc::vm_statistics64, free_count) == 0);
        assert!(mem::offset_of!(libc::vm_statistics64, speculative_count) == 92);
        assert!(
            mem::offset_of!(
                libc::vm_statistics64,
                total_uncompressed_pages_in_compressor
            ) == 144
        );
    };
    unsafe extern "C" {
        static mach_task_self_: libc::mach_port_t;
        fn mach_host_self() -> libc::mach_port_t;
        fn mach_port_deallocate(
            task: libc::mach_port_t,
            name: libc::mach_port_t,
        ) -> libc::kern_return_t;
        fn host_page_size(
            host: libc::mach_port_t,
            size: *mut libc::vm_size_t,
        ) -> libc::kern_return_t;
    }
    fn status(code: i32) -> Result<(), Failure> {
        if code == libc::KERN_SUCCESS {
            Ok(())
        } else {
            Err(Failure::Mach(code))
        }
    }
    struct NativeApi;
    impl Api for NativeApi {
        fn total(&mut self) -> Result<u64, Failure> {
            let mut bytes = 0u64;
            let mut length = mem::size_of::<u64>();
            // SAFETY: fixed public read-only MIB, writable aligned u64 of exact size;
            // synchronous API retains no pointer. Never inspect failed output.
            if unsafe {
                libc::sysctlbyname(
                    c"hw.memsize".as_ptr(),
                    (&mut bytes as *mut u64).cast(),
                    &mut length,
                    ptr::null_mut(),
                    0,
                )
            } != 0
            {
                // Capture errno immediately; do not interpret it as a Mach code.
                return Err(Failure::Errno(
                    io::Error::last_os_error().raw_os_error().unwrap_or(0),
                ));
            }
            total_reply(bytes, length)
        }
        fn pages(&mut self) -> Result<Pages, Failure> {
            // SAFETY: public argument-free acquisition of one owned send right.
            let host = unsafe { mach_host_self() };
            if host == 0 {
                return Err(Failure::Mach(0));
            }
            let mut right = HostRight {
                port: Some(host),
                release: |port| {
                    // SAFETY: libSystem task-self is borrowed, this host right owned;
                    // exactly one release, no use after release or retry on error.
                    status(unsafe { mach_port_deallocate(mach_task_self_, port) })
                },
            };
            let mut page_size = 0;
            // SAFETY: live aligned vm_size_t output and valid acquired host right.
            status(unsafe { host_page_size(host, &mut page_size) })?;
            // SAFETY: the SDK structure is plain integer fields, all-zero valid.
            let mut stats: libc::vm_statistics64 = unsafe { mem::zeroed() };
            // Do not request the full binding struct: it can be newer/larger
            // than the kernel. Only consume the explicitly requested rev1 prefix.
            let mut count = VM_REV1_WORDS;
            // SAFETY: initialized binding buffer contains the compile-checked
            // prefix; count limits writes to 152 bytes. Only success is consumed.
            status(unsafe {
                libc::host_statistics64(
                    host,
                    libc::HOST_VM_INFO64,
                    (&mut stats as *mut libc::vm_statistics64).cast(),
                    &mut count,
                )
            })?;
            #[cfg(test)]
            eprintln!(
                "memory SDK metadata: buffer_bytes={} binding_words={} requested_words={} returned_words={count} page_size={page_size}",
                mem::size_of::<libc::vm_statistics64>(),
                libc::HOST_VM_INFO64_COUNT,
                VM_REV1_WORDS
            );
            let result = vm_count(count).map(|()| Pages {
                size: page_size as u64,
                active: stats.active_count,
                inactive: stats.inactive_count,
                free: stats.free_count,
                speculative: stats.speculative_count,
            });
            // Refuse a success sample when explicit cleanup failed. Drop handles
            // earlier API failures/unwinding and never releases an owned right twice.
            right.close()?;
            result
        }
    }
    /// Public macOS memory queries. VM statistics can be cached by the OS;
    /// available is a non-compressed estimate, not immediately allocatable bytes.
    /// Total uses hw.memsize as a physical-memory proxy. See ADR 0026.
    pub struct MacosMemoryBackend(MemoryBackend<NativeApi>);
    impl MacosMemoryBackend {
        pub fn new() -> Self {
            Self(MemoryBackend::new(NativeApi))
        }
    }
    impl Default for MacosMemoryBackend {
        fn default() -> Self {
            Self::new()
        }
    }
    impl Backend for MacosMemoryBackend {
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
    fn public_vm_memory_read_matches_rust_sdk_contract() {
        let mut api = NativeApi;
        let total = api.total().expect("native total");
        let pages = api.pages().expect("native VM query");
        let result = available(pages, total);
        assert!(
            result.is_ok(),
            "total={total} pages={pages:?} result={result:?}"
        );
    }
    #[test]
    fn public_vm_rev1_layout_matches_requested_buffer() {
        assert_eq!(mem::size_of::<libc::integer_t>(), 4);
        assert_eq!(mem::size_of::<libc::vm_size_t>(), 8);
        assert!(mem::size_of::<libc::vm_statistics64>() >= 152);
        assert_eq!(VM_REV1_WORDS, 38);
        assert_eq!(mem::offset_of!(libc::vm_statistics64, free_count), 0);
        assert_eq!(
            mem::offset_of!(libc::vm_statistics64, speculative_count),
            92
        );
        assert_eq!(
            mem::offset_of!(
                libc::vm_statistics64,
                total_uncompressed_pages_in_compressor
            ),
            144
        );
    }
}
#[cfg(target_os = "macos")]
pub use native::MacosMemoryBackend;

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn truncated_or_oversized_vm_reply_is_not_a_successful_zero_sample() {
        assert_eq!(vm_count(38), Ok(()));
        for count in [0, 26, 37, 39, 40, 62, 104, u32::MAX] {
            assert_eq!(vm_count(count), Err(Failure::Invalid));
        }
        assert_eq!(total_reply(u64::MAX, 8), Ok(u64::MAX));
        assert_eq!(total_reply(0, 8), Err(Failure::Invalid));
        for length in [0, 4, 7, 9, usize::MAX] {
            assert_eq!(total_reply(4096, length), Err(Failure::Invalid));
        }
    }
    use std::{
        collections::VecDeque,
        sync::atomic::{AtomicUsize, Ordering},
        sync::{Arc, Mutex},
    };
    #[derive(Clone)]
    struct Fake {
        totals: Arc<Mutex<VecDeque<Result<u64, Failure>>>>,
        pages: Arc<Mutex<VecDeque<Result<Pages, Failure>>>>,
        calls: Arc<[AtomicUsize; 2]>,
    }
    impl Api for Fake {
        fn total(&mut self) -> Result<u64, Failure> {
            self.calls[0].fetch_add(1, Ordering::SeqCst);
            self.totals.lock().unwrap().pop_front().expect("total read")
        }
        fn pages(&mut self) -> Result<Pages, Failure> {
            self.calls[1].fetch_add(1, Ordering::SeqCst);
            self.pages.lock().unwrap().pop_front().expect("VM read")
        }
    }
    fn pages(free: u32) -> Result<Pages, Failure> {
        Ok(Pages {
            size: 4096,
            active: 0,
            inactive: 0,
            free,
            speculative: 0,
        })
    }
    fn fake(totals: Vec<Result<u64, Failure>>, pages: Vec<Result<Pages, Failure>>) -> Fake {
        Fake {
            totals: Arc::new(Mutex::new(totals.into())),
            pages: Arc::new(Mutex::new(pages.into())),
            calls: Arc::new([AtomicUsize::new(0), AtomicUsize::new(0)]),
        }
    }
    fn build(api: Fake) -> Hardware {
        HardwareBuilder::default()
            .with_backend(100, MemoryBackend::new(api))
            .build()
            .expect("hardware")
    }
    #[test]
    fn every_refresh_calls_apis_again_static_total_never_replaced_and_zero_is_valid() {
        let api = fake(vec![Ok(40960); 4], vec![pages(5), pages(5), pages(0)]);
        let hw = build(api.clone());
        let first = hw.collect().unwrap();
        let at = first.static_info.system.memory.total_usable_bytes.clone();
        assert_eq!(at.value(), Some(&40960));
        assert_eq!(at.source(), Source::Sysctl);
        assert_eq!(first.dynamic.memory_available_bytes.value(), Some(&20480));
        assert_eq!(
            hw.refresh_dynamic().unwrap().memory_available_bytes.value(),
            Some(&20480)
        );
        let last = hw.collect().unwrap();
        assert_eq!(last.static_info.system.memory.total_usable_bytes, at);
        assert_eq!(last.dynamic.memory_available_bytes.value(), Some(&0));
        assert_eq!(
            last.dynamic.memory_available_bytes.source(),
            Source::AppleApi
        );
        assert_eq!(api.calls[0].load(Ordering::SeqCst), 4);
        assert_eq!(api.calls[1].load(Ordering::SeqCst), 3);
    }
    #[test]
    fn failed_vm_read_has_no_old_value_or_time_and_recovers_without_rebuilding() {
        let hw = build(fake(
            vec![Ok(40960); 4],
            vec![pages(5), Err(Failure::Mach(2)), pages(0)],
        ));
        assert_eq!(
            hw.collect().unwrap().dynamic.memory_available_bytes.value(),
            Some(&20480)
        );
        let bad = hw.refresh_dynamic().unwrap().memory_available_bytes;
        assert!(bad.value().is_none() && bad.observed_at().is_none());
        assert_eq!(bad.availability(), Availability::Restricted);
        assert_eq!(bad.reason(), Some(ReasonCode::PermissionDenied));
        let cap = hw
            .capabilities()
            .into_iter()
            .find(|c| c.field == "memory_available_bytes")
            .unwrap();
        assert_eq!(cap.level, CapabilityLevel::Restricted);
        assert_eq!(
            hw.refresh_dynamic().unwrap().memory_available_bytes.value(),
            Some(&0)
        );
        let cap = hw
            .capabilities()
            .into_iter()
            .find(|c| c.field == "memory_available_bytes")
            .unwrap();
        assert_eq!(cap.level, CapabilityLevel::Partial);
    }
    #[test]
    fn cached_static_failure_does_not_prevent_dynamic_recovery_or_read_vm_for_static() {
        let api = fake(
            vec![Err(Failure::Errno(13)), Ok(40960), Ok(40960)],
            vec![pages(3), pages(2)],
        );
        let hw = build(api.clone());
        let first = hw.collect().unwrap();
        assert_eq!(
            first.static_info.system.memory.total_usable_bytes.reason(),
            Some(ReasonCode::PermissionDenied)
        );
        assert_eq!(first.dynamic.memory_available_bytes.value(), Some(&12288));
        let next = hw.collect().unwrap();
        assert_eq!(first.static_info, next.static_info);
        assert_eq!(next.dynamic.memory_available_bytes.value(), Some(&8192));
        assert_eq!(api.calls[1].load(Ordering::SeqCst), 2);
    }
    #[test]
    fn changed_or_failed_total_prevents_unrelated_vm_query_and_does_not_update_cache() {
        let api = fake(
            vec![Ok(40960), Ok(81920), Err(Failure::Errno(1)), Ok(40960)],
            vec![pages(1)],
        );
        let hw = build(api.clone());
        let first = hw.collect().unwrap();
        assert_eq!(
            first.dynamic.memory_available_bytes.reason(),
            Some(ReasonCode::TemporarilyUnavailable)
        );
        assert_eq!(
            hw.refresh_dynamic()
                .unwrap()
                .memory_available_bytes
                .reason(),
            Some(ReasonCode::PermissionDenied)
        );
        assert_eq!(api.calls[1].load(Ordering::SeqCst), 0);
        let next = hw.collect().unwrap();
        assert_eq!(next.static_info, first.static_info);
        assert_eq!(next.dynamic.memory_available_bytes.value(), Some(&4096));
        assert_eq!(api.calls[1].load(Ordering::SeqCst), 1);
    }
    #[test]
    fn unsigned_units_no_double_speculative_overflow_or_clamping() {
        let mut p = pages(3).unwrap();
        p.active = 1;
        p.inactive = 2;
        p.speculative = 2;
        assert_eq!(available(p, 24576), Ok(24576));
        p.size = 16384;
        assert_eq!(available(p, 98304), Ok(98304));
        for size in [0, 3, 4095] {
            p.size = size;
            assert_eq!(available(p, u64::MAX), Err(Failure::Invalid));
        }
        p.size = 4096;
        p.speculative = 4;
        assert_eq!(available(p, u64::MAX), Err(Failure::Invalid));
        p.speculative = 0;
        p.size = 1 << 63;
        assert_eq!(available(p, u64::MAX), Err(Failure::Invalid));
        p.size = 4096;
        p.free = u32::MAX;
        p.active = u32::MAX;
        p.inactive = u32::MAX;
        assert_eq!(available(p, u64::MAX), Ok(3 * u64::from(u32::MAX) * 4096));
        assert_eq!(available(p, 1), Err(Failure::Invalid));
        assert_eq!(available(p, 0), Err(Failure::Invalid));
    }
    #[test]
    fn errno_and_mach_namespaces_are_not_confused_or_guessed() {
        for (error, state, reason) in [
            (
                Failure::Errno(2),
                Availability::Unavailable,
                ReasonCode::NotPresent,
            ),
            (
                Failure::Mach(2),
                Availability::Restricted,
                ReasonCode::PermissionDenied,
            ),
            (
                Failure::Errno(13),
                Availability::Restricted,
                ReasonCode::PermissionDenied,
            ),
            (
                Failure::Mach(13),
                Availability::Unavailable,
                ReasonCode::Unknown,
            ),
            (
                Failure::Errno(22),
                Availability::Unavailable,
                ReasonCode::InvalidData,
            ),
            (
                Failure::Mach(18),
                Availability::Unavailable,
                ReasonCode::InvalidData,
            ),
            (
                Failure::Mach(6),
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            (
                Failure::Errno(35),
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            (
                Failure::Mach(46),
                Availability::Unsupported,
                ReasonCode::NotSupported,
            ),
            (
                Failure::Errno(45),
                Availability::Unsupported,
                ReasonCode::NotSupported,
            ),
            (
                Failure::Mach(0),
                Availability::Unavailable,
                ReasonCode::Unknown,
            ),
            (
                Failure::Errno(0),
                Availability::Unavailable,
                ReasonCode::Unknown,
            ),
            (
                Failure::Mach(-1),
                Availability::Unavailable,
                ReasonCode::Unknown,
            ),
        ] {
            let value = error.observed(Source::AppleApi);
            assert_eq!(value.availability(), state);
            assert_eq!(value.reason(), Some(reason));
            assert!(value.value().is_none() && value.observed_at().is_none());
        }
    }
    #[test]
    fn zero_total_is_invalid_and_does_not_query_vm() {
        let mut api = fake(vec![Ok(0)], vec![]);
        assert_eq!(
            dynamic_with(&mut api, None, || Ok(())).unwrap().reason(),
            Some(ReasonCode::InvalidData)
        );
        assert_eq!(api.calls[1].load(Ordering::SeqCst), 0);
    }
    #[test]
    fn cancel_before_read_or_timeout_after_each_api_never_publishes_output() {
        for code in [ErrorCode::Cancelled, ErrorCode::Timeout] {
            for boundary in 1..=4 {
                let mut api = fake(vec![Ok(40960)], vec![pages(1)]);
                let mut checks = 0;
                let error = dynamic_with(&mut api, None, || {
                    checks += 1;
                    if checks == boundary {
                        Err(ScopeError::new(code))
                    } else {
                        Ok(())
                    }
                })
                .unwrap_err();
                assert_eq!(error.code, code);
                assert_eq!(
                    api.calls[0].load(Ordering::SeqCst),
                    usize::from(boundary > 1)
                );
                assert_eq!(
                    api.calls[1].load(Ordering::SeqCst),
                    usize::from(boundary > 3)
                );
            }
        }
    }
    #[test]
    fn acquired_host_right_is_closed_once_even_on_failed_release_and_unwind() {
        let calls = std::cell::RefCell::new(Vec::new());
        {
            let mut right = HostRight {
                port: Some(7),
                release: |p| {
                    calls.borrow_mut().push(p);
                    Err(Failure::Mach(5))
                },
            };
            assert_eq!(right.close(), Err(Failure::Mach(5)));
            assert_eq!(right.close(), Ok(()));
        }
        assert_eq!(*calls.borrow(), vec![7]);
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _right = HostRight {
                port: Some(9),
                release: |p| {
                    calls.borrow_mut().push(p);
                    Ok(())
                },
            };
            panic!("fixture unwind");
        }));
        assert!(result.is_err());
        assert_eq!(*calls.borrow(), vec![7, 9]);
    }
}
