//! Fresh public Mach processor samples, bounded copies and explicit ownership.
use daoseeker_scope_core::*;
use std::time::{Duration, Instant};

const MAX_CPUS: usize = 1024;
const INTERVAL: Duration = Duration::from_millis(300);
// Public PROCESSOR_CPU_LOAD_INFO order: user, system, idle, nice.
#[derive(Debug)]
struct Sample(Vec<[u32; 4]>);
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Failure {
    Mach(i32),
    Invalid,
    Limit,
    Temporary,
}
impl Failure {
    fn observed<T>(self) -> Observed<T> {
        let (state, reason) = match self {
            Self::Mach(2 | 8) => (Availability::Restricted, ReasonCode::PermissionDenied),
            Self::Mach(4 | 18) | Self::Invalid => {
                (Availability::Unavailable, ReasonCode::InvalidData)
            }
            Self::Mach(6) | Self::Temporary => (
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            Self::Limit => (Availability::Unsupported, ReasonCode::NotSupported),
            Self::Mach(_) => (Availability::Unavailable, ReasonCode::Unknown),
        };
        Observed::missing(state, Source::AppleApi, reason).expect("missing observation")
    }
}
fn layout(processors: u32, words: u32) -> Result<usize, Failure> {
    if processors == 0 {
        return Err(Failure::Invalid);
    }
    if processors as usize > MAX_CPUS {
        return Err(Failure::Limit);
    }
    if words != processors * 4 {
        return Err(Failure::Invalid);
    }
    Ok(processors as usize)
}
fn copy_words(processors: u32, words: &[i32]) -> Result<Sample, Failure> {
    let count = layout(
        processors,
        u32::try_from(words.len()).map_err(|_| Failure::Invalid)?,
    )?;
    let mut cpus = Vec::new();
    cpus.try_reserve_exact(count)
        .map_err(|_| Failure::Temporary)?;
    for values in words.chunks_exact(4) {
        // integer_t carries natural_t's unsigned bit pattern, not signed ticks.
        cpus.push(std::array::from_fn(|index| values[index] as u32));
    }
    Ok(Sample(cpus))
}
// Each resource is closed at most once, including errors and unwinding.
struct Owned<T, F: FnMut(T) -> Result<(), Failure>> {
    raw: Option<T>,
    release: F,
}
impl<T, F: FnMut(T) -> Result<(), Failure>> Owned<T, F> {
    fn new(raw: T, release: F) -> Self {
        Self {
            raw: Some(raw),
            release,
        }
    }
    fn close(&mut self) -> Result<(), Failure> {
        match self.raw.take() {
            Some(raw) => (self.release)(raw),
            None => Ok(()),
        }
    }
}
impl<T, F: FnMut(T) -> Result<(), Failure>> Drop for Owned<T, F> {
    fn drop(&mut self) {
        let _ = self.close();
    }
}
trait Api: Send + 'static {
    fn read(&mut self) -> Result<Sample, Failure>;
}
fn read_checked(
    api: &mut impl Api,
    mut check: impl FnMut() -> Result<(), ScopeError>,
) -> Result<Result<Sample, Failure>, ScopeError> {
    check()?;
    let result = api.read();
    check()?;
    Ok(result)
}
#[derive(Default)]
struct Sampler {
    baseline: Option<(Sample, Instant)>,
    cached_count: Option<usize>,
}
impl Sampler {
    fn observe(
        &mut self,
        input: Result<Sample, Failure>,
        now: Instant,
        at: Timestamp,
    ) -> Observed<f64> {
        let sample = match input {
            Ok(sample) => sample,
            Err(error) => {
                self.baseline = None;
                return error.observed();
            }
        };
        let count = sample.0.len();
        if count == 0 || count > MAX_CPUS {
            self.baseline = None;
            return if count == 0 {
                Failure::Invalid
            } else {
                Failure::Limit
            }
            .observed();
        }
        if self.cached_count.is_some_and(|previous| previous != count) {
            self.baseline = None;
            return Failure::Temporary.observed();
        }
        let Some((previous, previous_at)) = &self.baseline else {
            self.baseline = Some((sample, now));
            return Failure::Temporary.observed();
        };
        if previous.0.len() != count {
            self.baseline = Some((sample, now));
            return Failure::Temporary.observed();
        }
        let mut delta = [0u64; 4];
        for (new, old) in sample.0.iter().zip(&previous.0) {
            for index in 0..4 {
                let Some(ticks) = new[index].checked_sub(old[index]) else {
                    self.baseline = None;
                    return Failure::Invalid.observed();
                };
                // At most 1024 * u32::MAX per state; neither sum can overflow u64.
                delta[index] += u64::from(ticks);
            }
        }
        let Some(elapsed) = now.checked_duration_since(*previous_at) else {
            self.baseline = None;
            return Failure::Invalid.observed();
        };
        if elapsed < INTERVAL {
            return Failure::Temporary.observed();
        }
        self.baseline = Some((sample, now));
        let total: u64 = delta.iter().sum();
        if total == 0 {
            return Failure::Temporary.observed();
        }
        Observed::available(
            100.0 * ((total - delta[2]) as f64 / total as f64),
            Source::AppleApi,
            at,
        )
    }
    fn refresh(
        &mut self,
        api: &mut impl Api,
        check: impl FnMut() -> Result<(), ScopeError>,
    ) -> Result<Observed<f64>, ScopeError> {
        let result = (|| {
            let raw = read_checked(api, check)?;
            Ok(self.observe(raw, Instant::now(), Timestamp::now()?))
        })();
        if result.is_err() {
            self.baseline = None;
        }
        result
    }
}
struct CpuBackend<A> {
    api: A,
    sampler: Sampler,
}
impl<A: Api> CpuBackend<A> {
    fn new(api: A) -> Self {
        Self {
            api,
            sampler: Sampler::default(),
        }
    }
}
impl<A: Api> Backend for CpuBackend<A> {
    fn name(&self) -> &'static str {
        "macos_cpu"
    }
    fn capabilities(&self) -> Capabilities {
        ["system.cpu.logical_count", "cpu_usage_percent"]
            .into_iter()
            .map(|field| Capability::new(field, CapabilityLevel::Partial, Source::AppleApi))
            .collect()
    }
    fn collect_static(&mut self, context: &CollectContext) -> Result<StaticSnapshot, ScopeError> {
        self.sampler = Sampler::default();
        let raw = read_checked(&mut self.api, || context.check())?;
        let count = raw.and_then(|sample| {
            if sample.0.is_empty() {
                Err(Failure::Invalid)
            } else if sample.0.len() > MAX_CPUS {
                Err(Failure::Limit)
            } else {
                Ok(sample.0.len())
            }
        });
        let mut result = StaticSnapshot::default();
        result.system.cpu.logical_count = match count {
            Ok(count) => {
                self.sampler.cached_count = Some(count);
                Observed::available(count as u32, Source::AppleApi, Timestamp::now()?)
            }
            Err(error) => error.observed(),
        };
        Ok(result)
    }
    fn refresh_dynamic(&mut self, context: &CollectContext) -> Result<DynamicSnapshot, ScopeError> {
        let mut result = DynamicSnapshot::default();
        result.cpu_usage_percent = self.sampler.refresh(&mut self.api, || context.check())?;
        Ok(result)
    }
}

#[cfg(target_os = "macos")]
mod native {
    use super::*;
    use std::{mem, ptr, slice};
    // Public libSystem SDK symbols absent from libc's non-deprecated interface.
    unsafe extern "C" {
        static mach_task_self_: libc::mach_port_t;
        fn mach_host_self() -> libc::mach_port_t;
        fn mach_port_deallocate(
            task: libc::mach_port_t,
            name: libc::mach_port_t,
        ) -> libc::kern_return_t;
    }
    fn status(code: i32) -> Result<(), Failure> {
        if code == libc::KERN_SUCCESS {
            Ok(())
        } else {
            Err(Failure::Mach(code))
        }
    }
    fn task() -> libc::mach_port_t {
        // SAFETY: libSystem initializes its public task-self global before main;
        // this is a borrowed right for the current task, never released by us.
        unsafe { mach_task_self_ }
    }
    struct NativeApi;
    impl Api for NativeApi {
        fn read(&mut self) -> Result<Sample, Failure> {
            // SAFETY: argument-free public SDK call yielding one owned send right.
            let host = unsafe { mach_host_self() };
            if host == 0 {
                return Err(Failure::Mach(0));
            }
            let mut port = Owned::new(host, |value| {
                // SAFETY: exactly one release of this acquired host right, in our task.
                status(unsafe { mach_port_deallocate(task(), value) })
            });
            let mut processors = 0;
            let mut words = 0;
            let mut pointer = ptr::null_mut();
            // SAFETY: live aligned SDK outputs, valid owned host right, fixed public
            // flavor. MIG owns failed-call outputs; we only consume KERN_SUCCESS.
            status(unsafe {
                libc::host_processor_info(
                    host,
                    libc::PROCESSOR_CPU_LOAD_INFO,
                    &mut processors,
                    &mut pointer,
                    &mut words,
                )
            })?;
            let mut allocation = Owned::new((pointer, words), |(address, length)| {
                if address.is_null() || length == 0 {
                    return Ok(());
                }
                // word count is u32 and supported macOS targets have 64-bit usize.
                let bytes = u64::from(length) * mem::size_of::<i32>() as u64;
                // SAFETY: returned OOL VM allocation belongs to the current task;
                // exact SDK byte length, released once without dereferencing it.
                status(unsafe { libc::vm_deallocate(task(), address as usize, bytes as usize) })
            });
            let result = (|| {
                layout(processors, words)?;
                if pointer.is_null() || !pointer.is_aligned() {
                    return Err(Failure::Invalid);
                }
                // SAFETY: successful public MIG contract guarantees this allocation's
                // valid range. Metadata was bounded to <=4096 aligned i32 words;
                // allocation guard stays alive until the bounded copy completes.
                let raw = unsafe { slice::from_raw_parts(pointer, words as usize) };
                copy_words(processors, raw)
            })();
            // Attempt both cleanups even if one fails, without retries/double free.
            let array_release = allocation.close();
            let port_release = port.close();
            array_release?;
            port_release?;
            result
        }
    }
    /// Fresh public Mach CPU usage and cached logical count (at most 1024 CPUs).
    /// Facade registration is automatic; first dynamic sample needs 300 ms.
    pub struct MacosCpuBackend(CpuBackend<NativeApi>);
    impl MacosCpuBackend {
        pub fn new() -> Self {
            Self(CpuBackend::new(NativeApi))
        }
    }
    impl Default for MacosCpuBackend {
        fn default() -> Self {
            Self::new()
        }
    }
    impl Backend for MacosCpuBackend {
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
    fn sdk_scalar_layout_and_processor_states_match() {
        assert_eq!(mem::size_of::<libc::integer_t>(), 4);
        assert_eq!(mem::size_of::<libc::natural_t>(), 4);
        assert_eq!(mem::size_of::<libc::mach_port_t>(), 4);
        assert_eq!(mem::size_of::<usize>(), 8);
        assert_eq!(
            [
                libc::CPU_STATE_USER,
                libc::CPU_STATE_SYSTEM,
                libc::CPU_STATE_IDLE,
                libc::CPU_STATE_NICE
            ],
            [0, 1, 2, 3]
        );
    }
}
#[cfg(target_os = "macos")]
pub use native::MacosCpuBackend;

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        cell::RefCell,
        collections::VecDeque,
        sync::{
            Arc, Mutex,
            atomic::{AtomicUsize, Ordering},
        },
    };
    fn sample(values: &[[u32; 4]]) -> Result<Sample, Failure> {
        Ok(Sample(values.to_vec()))
    }
    fn absent(value: &Observed<f64>, reason: ReasonCode) {
        assert!(value.value().is_none() && value.observed_at().is_none());
        assert_eq!(value.source(), Source::AppleApi);
        assert_eq!(value.reason(), Some(reason));
    }
    #[test]
    fn shape_bounds_unsigned_words_and_no_partial_cpu_prefix() {
        assert_eq!(layout(0, 0), Err(Failure::Invalid));
        assert_eq!(layout(1, 3), Err(Failure::Invalid));
        assert_eq!(layout(1, 5), Err(Failure::Invalid));
        assert_eq!(layout(1024, 4096), Ok(1024));
        assert_eq!(layout(u32::MAX, 0), Err(Failure::Limit));
        assert_eq!(layout(1025, 4100), Err(Failure::Limit));
        let copied = copy_words(1, &[-1, i32::MIN, 0, i32::MAX]).expect("unsigned representation");
        assert_eq!(copied.0, vec![[u32::MAX, 1 << 31, 0, i32::MAX as u32]]);
        assert!(copy_words(2, &[0; 4]).is_err());
    }
    #[test]
    fn fast_reads_preserve_baseline_and_exact_interval_publishes_fresh_percentage() {
        let mut sampler = Sampler::default();
        let now = Instant::now();
        for millis in [0, 100, 200, 299] {
            absent(
                &sampler.observe(
                    sample(&[[millis, 0, millis, 0]]),
                    now + Duration::from_millis(millis.into()),
                    Timestamp(millis.into()),
                ),
                ReasonCode::TemporarilyUnavailable,
            );
        }
        let value = sampler.observe(sample(&[[300, 0, 300, 0]]), now + INTERVAL, Timestamp(300));
        assert_eq!(value.value(), Some(&50.0));
        assert_eq!(value.observed_at(), Some(Timestamp(300)));
        absent(
            &sampler.observe(sample(&[[301, 0, 301, 0]]), now + INTERVAL, Timestamp(301)),
            ReasonCode::TemporarilyUnavailable,
        );
    }
    #[test]
    fn legal_zero_full_load_nice_and_weighted_multi_cpu_deltas() {
        for (values, expected) in [
            (vec![[0, 0, 100, 0]], 0.0),
            (vec![[0, 0, 0, 100]], 100.0),
            (vec![[10, 10, 20, 0]], 50.0),
            (vec![[0, 0, 100, 0], [900, 0, 0, 0]], 90.0),
        ] {
            let mut sampler = Sampler::default();
            let now = Instant::now();
            sampler.observe(Ok(Sample(vec![[0; 4]; values.len()])), now, Timestamp(0));
            assert_eq!(
                sampler
                    .observe(Ok(Sample(values)), now + INTERVAL, Timestamp(1))
                    .value(),
                Some(&expected)
            );
        }
        let mut sampler = Sampler::default();
        let now = Instant::now();
        sampler.observe(Ok(Sample(vec![[0; 4]; 1024])), now, Timestamp(0));
        assert_eq!(
            sampler
                .observe(
                    Ok(Sample(vec![[u32::MAX; 4]; 1024])),
                    now + INTERVAL,
                    Timestamp(1)
                )
                .value(),
            Some(&75.0)
        );
    }
    #[test]
    fn per_cpu_wrap_or_decrease_cannot_be_hidden_by_other_cpus_growth() {
        let now = Instant::now();
        let mut sampler = Sampler::default();
        sampler.observe(sample(&[[u32::MAX, 0, 0, 0], [0; 4]]), now, Timestamp(0));
        absent(
            &sampler.observe(
                sample(&[[0; 4], [u32::MAX; 4]]),
                now + INTERVAL,
                Timestamp(1),
            ),
            ReasonCode::InvalidData,
        );
        assert!(sampler.baseline.is_none());
        absent(
            &sampler.observe(
                sample(&[[1; 4], [u32::MAX; 4]]),
                now + INTERVAL * 2,
                Timestamp(2),
            ),
            ReasonCode::TemporarilyUnavailable,
        );
    }
    #[test]
    fn explicit_error_states_clear_baseline_and_recovery_needs_two_samples() {
        for (error, state, reason) in [
            (
                Failure::Mach(2),
                Availability::Restricted,
                ReasonCode::PermissionDenied,
            ),
            (
                Failure::Mach(8),
                Availability::Restricted,
                ReasonCode::PermissionDenied,
            ),
            (
                Failure::Mach(4),
                Availability::Unavailable,
                ReasonCode::InvalidData,
            ),
            (
                Failure::Mach(6),
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            (
                Failure::Mach(5),
                Availability::Unavailable,
                ReasonCode::Unknown,
            ),
            (
                Failure::Mach(-300),
                Availability::Unavailable,
                ReasonCode::Unknown,
            ),
        ] {
            let mut sampler = Sampler::default();
            let now = Instant::now();
            sampler.observe(sample(&[[0; 4]]), now, Timestamp(0));
            assert!(
                sampler
                    .observe(sample(&[[1; 4]]), now + INTERVAL, Timestamp(1))
                    .value()
                    .is_some()
            );
            let bad = sampler.observe(Err(error), now + INTERVAL * 2, Timestamp(2));
            absent(&bad, reason);
            assert_eq!(bad.availability(), state);
            assert!(sampler.baseline.is_none());
            absent(
                &sampler.observe(sample(&[[3; 4]]), now + INTERVAL * 3, Timestamp(3)),
                ReasonCode::TemporarilyUnavailable,
            );
            assert_eq!(
                sampler
                    .observe(sample(&[[4; 4]]), now + INTERVAL * 4, Timestamp(4))
                    .value(),
                Some(&75.0)
            );
        }
    }
    #[test]
    fn zero_delta_invalid_count_clock_regression_and_cached_topology() {
        let now = Instant::now();
        let mut sampler = Sampler::default();
        sampler.observe(sample(&[[1; 4]]), now, Timestamp(0));
        absent(
            &sampler.observe(sample(&[[1; 4]]), now + INTERVAL, Timestamp(1)),
            ReasonCode::TemporarilyUnavailable,
        );
        absent(
            &sampler.observe(sample(&[[2; 4]]), now, Timestamp(2)),
            ReasonCode::InvalidData,
        );
        absent(
            &sampler.observe(sample(&[]), now, Timestamp(3)),
            ReasonCode::InvalidData,
        );
        absent(
            &sampler.observe(Ok(Sample(vec![[0; 4]; 1025])), now, Timestamp(4)),
            ReasonCode::NotSupported,
        );
        sampler.cached_count = Some(1);
        absent(
            &sampler.observe(sample(&[[0; 4], [0; 4]]), now, Timestamp(5)),
            ReasonCode::TemporarilyUnavailable,
        );
        assert!(sampler.baseline.is_none());
        absent(
            &sampler.observe(sample(&[[3; 4]]), now + INTERVAL, Timestamp(6)),
            ReasonCode::TemporarilyUnavailable,
        );
        assert_eq!(
            sampler
                .observe(sample(&[[4; 4]]), now + INTERVAL * 2, Timestamp(7))
                .value(),
            Some(&75.0)
        );
    }
    #[derive(Clone)]
    struct Fake {
        values: Arc<Mutex<VecDeque<Result<Sample, Failure>>>>,
        calls: Arc<AtomicUsize>,
    }
    impl Api for Fake {
        fn read(&mut self) -> Result<Sample, Failure> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            self.values
                .lock()
                .expect("fixture")
                .pop_front()
                .expect("fixture read")
        }
    }
    fn fake(values: Vec<Result<Sample, Failure>>) -> Fake {
        Fake {
            values: Arc::new(Mutex::new(values.into())),
            calls: Arc::new(AtomicUsize::new(0)),
        }
    }
    fn build(api: Fake) -> Hardware {
        HardwareBuilder::default()
            .with_backend(100, CpuBackend::new(api))
            .build()
            .expect("build")
    }
    #[test]
    fn static_count_is_cached_and_changed_count_requires_recreation() {
        let api = fake(vec![
            sample(&[[0; 4]]),
            sample(&[[1; 4]]),
            sample(&[[1; 4], [1; 4]]),
            sample(&[[2; 4], [2; 4]]),
        ]);
        let hw = build(api.clone());
        let first = hw.collect().expect("collect");
        assert_eq!(first.static_info.system.cpu.logical_count.value(), Some(&1));
        absent(
            &hw.refresh_dynamic()
                .expect("changed count")
                .cpu_usage_percent,
            ReasonCode::TemporarilyUnavailable,
        );
        let next = hw.collect().expect("cached static");
        assert_eq!(first.static_info, next.static_info);
        absent(
            &next.dynamic.cpu_usage_percent,
            ReasonCode::TemporarilyUnavailable,
        );
        assert_eq!(api.calls.load(Ordering::SeqCst), 4);
        let recreated = build(fake(vec![
            sample(&[[0; 4], [0; 4]]),
            sample(&[[1; 4], [1; 4]]),
        ]))
        .collect()
        .expect("recreate");
        assert_eq!(
            recreated.static_info.system.cpu.logical_count.value(),
            Some(&2)
        );
    }
    #[test]
    fn static_failure_is_cached_but_dynamic_recovery_does_not_invent_logical_count() {
        let api = fake(vec![
            Err(Failure::Mach(2)),
            Err(Failure::Mach(8)),
            sample(&[[1; 4]]),
            sample(&[[2; 4]]),
        ]);
        let hw = build(api.clone());
        let first = hw.collect().expect("field errors");
        assert_eq!(
            first.static_info.system.cpu.logical_count.availability(),
            Availability::Restricted
        );
        let cap = hw
            .capabilities()
            .into_iter()
            .find(|c| c.field == "cpu_usage_percent")
            .expect("cap");
        assert_eq!(cap.level, CapabilityLevel::Restricted);
        absent(
            &hw.refresh_dynamic().expect("recovery").cpu_usage_percent,
            ReasonCode::TemporarilyUnavailable,
        );
        let next = hw.collect().expect("static cached");
        assert_eq!(first.static_info, next.static_info);
        assert_eq!(api.calls.load(Ordering::SeqCst), 4);
        let cap = hw
            .capabilities()
            .into_iter()
            .find(|c| c.field == "cpu_usage_percent")
            .expect("cap");
        assert_eq!(cap.level, CapabilityLevel::Partial);
        let mut sampler = Sampler::default();
        let now = Instant::now();
        sampler.observe(sample(&[[1; 4]]), now, Timestamp(0));
        assert_eq!(
            sampler
                .observe(sample(&[[2; 4]]), now + INTERVAL, Timestamp(1))
                .value(),
            Some(&75.0)
        );
    }
    #[test]
    fn context_boundaries_clear_baseline_without_extra_reads() {
        let mut api = fake(vec![sample(&[[1; 4]])]);
        let mut sampler = Sampler::default();
        sampler.observe(sample(&[[0; 4]]), Instant::now(), Timestamp(0));
        assert_eq!(
            sampler
                .refresh(&mut api, || Err(ScopeError::new(ErrorCode::Cancelled)))
                .expect_err("cancel")
                .code,
            ErrorCode::Cancelled
        );
        assert_eq!(api.calls.load(Ordering::SeqCst), 0);
        assert!(sampler.baseline.is_none());
        sampler.observe(sample(&[[0; 4]]), Instant::now(), Timestamp(0));
        let mut checks = 0;
        assert_eq!(
            sampler
                .refresh(&mut api, || {
                    checks += 1;
                    if checks == 2 {
                        Err(ScopeError::new(ErrorCode::Timeout))
                    } else {
                        Ok(())
                    }
                })
                .expect_err("timeout")
                .code,
            ErrorCode::Timeout
        );
        assert_eq!(api.calls.load(Ordering::SeqCst), 1);
        assert!(sampler.baseline.is_none());
    }
    #[test]
    fn owned_resources_release_in_reverse_order_once_on_error_or_unwind() {
        let log = RefCell::new(Vec::new());
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _port = Owned::new("port", |name| {
                log.borrow_mut().push(name);
                Ok(())
            });
            let _array = Owned::new("array", |name| {
                log.borrow_mut().push(name);
                Ok(())
            });
            panic!("fixture unwind");
        }));
        assert!(result.is_err());
        assert_eq!(*log.borrow(), vec!["array", "port"]);
        log.borrow_mut().clear();
        {
            let mut resource = Owned::new("failed release", |name| {
                log.borrow_mut().push(name);
                Err(Failure::Mach(5))
            });
            assert_eq!(resource.close(), Err(Failure::Mach(5)));
            assert_eq!(resource.close(), Ok(()));
        }
        assert_eq!(*log.borrow(), vec!["failed release"]);
    }
}
