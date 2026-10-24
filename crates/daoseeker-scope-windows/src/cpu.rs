//! Bounded CPU time sampling, including isolated multi-group collection.
use super::cpu_groups::{Check, Counters, Frame};
use daoseeker_scope_core::*;
use std::time::{Duration, Instant};

const INTERVAL: Duration = Duration::from_millis(300);

#[derive(Clone, Copy)]
pub(super) struct Sample {
    pub(super) groups: u16,
    pub(super) processors: u32,
    pub(super) idle: u64,
    pub(super) kernel: u64,
    pub(super) user: u64,
    pub(super) frame: Option<Frame>,
}
#[derive(Clone, Copy, Debug)]
pub(super) enum Failure {
    Api(u32),
    TopologyChanged,
    Limit,
}
trait Api: Send + 'static {
    fn read(&mut self) -> Result<Sample, Failure>;
    fn read_checked(
        &mut self,
        check: &mut Check<'_>,
    ) -> Result<Result<Sample, Failure>, ScopeError> {
        check()?;
        let result = self.read();
        check()?;
        Ok(result)
    }
}
fn missing(reason: ReasonCode) -> Observed<f64> {
    Observed::unavailable(Source::Win32, reason)
}
fn failure(error: Failure) -> Observed<f64> {
    match error {
        Failure::Api(5) => Observed::restricted(Source::Win32, ReasonCode::PermissionDenied),
        Failure::Api(13 | 87) => missing(ReasonCode::InvalidData),
        Failure::Api(8 | 14 | 170 | 1237) | Failure::TopologyChanged => {
            missing(ReasonCode::TemporarilyUnavailable)
        }
        Failure::Api(_) => missing(ReasonCode::Unknown),
        Failure::Limit => Observed::missing(
            Availability::Unsupported,
            Source::Win32,
            ReasonCode::NotSupported,
        )
        .expect("limit"),
    }
}
#[derive(Default)]
struct Sampler {
    baseline: Option<(Sample, Instant)>,
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
                return failure(error);
            }
        };
        if sample.groups > 1 && sample.frame.is_none() {
            self.baseline = None;
            return Observed::missing(
                Availability::Unsupported,
                Source::Win32,
                ReasonCode::NotSupported,
            )
            .expect("unsupported observation");
        }
        let valid = match sample.frame {
            Some(frame) => {
                frame.valid()
                    && frame.topology.count == sample.groups
                    && frame.topology.processors().ok() == Some(sample.processors)
            }
            None => {
                sample.groups == 1
                    && (1..=64).contains(&sample.processors)
                    && sample.idle <= sample.kernel
            }
        };
        if !valid {
            self.baseline = None;
            return missing(ReasonCode::InvalidData);
        }
        let Some((previous, previous_at)) = self.baseline else {
            self.baseline = Some((sample, now));
            return missing(ReasonCode::TemporarilyUnavailable);
        };
        if sample.groups != previous.groups
            || sample.processors != previous.processors
            || sample.frame.map(|f| f.topology) != previous.frame.map(|f| f.topology)
        {
            self.baseline = Some((sample, now));
            return missing(ReasonCode::TemporarilyUnavailable);
        }
        let deltas = match (sample.frame, previous.frame) {
            (Some(current), Some(previous)) => current.delta(&previous),
            (None, None) => Counters {
                idle: sample.idle,
                kernel: sample.kernel,
                user: sample.user,
            }
            .delta(Counters {
                idle: previous.idle,
                kernel: previous.kernel,
                user: previous.user,
            }),
            _ => None,
        };
        let Some((idle, kernel, user)) = deltas else {
            self.baseline = None;
            return missing(ReasonCode::InvalidData);
        };
        if now.checked_duration_since(previous_at).is_none() {
            self.baseline = None;
            return missing(ReasonCode::InvalidData);
        }
        if now.duration_since(previous_at) < INTERVAL {
            // Fresh reads still detect failures; keep the baseline to avoid starvation.
            return missing(ReasonCode::TemporarilyUnavailable);
        }
        self.baseline = Some((sample, now));
        let total = kernel + user;
        if total == 0 {
            return missing(ReasonCode::TemporarilyUnavailable);
        }
        Observed::available(
            100.0 * ((total - idle) as f64 / total as f64),
            Source::Win32,
            at,
        )
    }
    fn refresh(
        &mut self,
        api: &mut impl Api,
        mut check: impl FnMut() -> Result<(), ScopeError> + Send,
    ) -> Result<Observed<f64>, ScopeError> {
        let result = (|| {
            let raw = api.read_checked(&mut check)?;
            let now = Instant::now();
            let at = Timestamp::now()?;
            Ok(self.observe(raw, now, at))
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
        "windows_cpu"
    }
    fn capabilities(&self) -> Capabilities {
        vec![Capability::new(
            "cpu_usage_percent",
            CapabilityLevel::Partial,
            Source::Win32,
        )]
    }
    fn collect_static(&mut self, context: &CollectContext) -> Result<StaticSnapshot, ScopeError> {
        context.check()?;
        Ok(StaticSnapshot::default())
    }
    fn refresh_dynamic(&mut self, context: &CollectContext) -> Result<DynamicSnapshot, ScopeError> {
        let mut result = DynamicSnapshot::default();
        result.cpu_usage_percent = self.sampler.refresh(&mut self.api, || context.check())?;
        Ok(result)
    }
}

#[cfg(target_os = "windows")]
mod native {
    use super::*;
    use windows_sys::Win32::{
        Foundation::{FILETIME, GetLastError},
        System::Threading::{
            GetActiveProcessorCount, GetActiveProcessorGroupCount, GetSystemTimes,
        },
    };
    struct NativeApi;
    fn ticks(time: FILETIME) -> u64 {
        (u64::from(time.dwHighDateTime) << 32) | u64::from(time.dwLowDateTime)
    }
    fn group_count() -> Result<u16, Failure> {
        // SAFETY: argument-free synchronous query. No GetLastError contract.
        match unsafe { GetActiveProcessorGroupCount() } {
            0 => Err(Failure::Api(0)),
            value => Ok(value),
        }
    }
    fn processor_count() -> Result<u32, Failure> {
        // SAFETY: caller confirmed a single active group; group 0 exists.
        let count = unsafe { GetActiveProcessorCount(0) };
        if count == 0 {
            // SAFETY: immediate documented failure status.
            Err(Failure::Api(unsafe { GetLastError() }))
        } else {
            Ok(count)
        }
    }
    fn system_times() -> Result<Counters, Failure> {
        let mut idle = FILETIME::default();
        let mut kernel = FILETIME::default();
        let mut user = FILETIME::default();
        // SAFETY: distinct live initialized SDK outputs, retained for this call only.
        if unsafe { GetSystemTimes(&mut idle, &mut kernel, &mut user) } == 0 {
            // SAFETY: immediate documented failure status.
            return Err(Failure::Api(unsafe { GetLastError() }));
        }
        Ok(Counters {
            idle: ticks(idle),
            kernel: ticks(kernel),
            user: ticks(user),
        })
    }
    fn read_sample(check: &mut Check<'_>) -> Result<Sample, crate::cpu_groups::ReadError> {
        use crate::cpu_groups::{ReadError, checked};
        let groups = checked(group_count, check)?;
        if groups > 1 {
            return crate::cpu_groups::read_native(check);
        }
        let processors = checked(processor_count, check)?;
        let counters = checked(system_times, check)?;
        if checked(group_count, check)? != groups || checked(processor_count, check)? != processors
        {
            return Err(ReadError::Field(Failure::TopologyChanged));
        }
        Ok(Sample {
            groups,
            processors,
            idle: counters.idle,
            kernel: counters.kernel,
            user: counters.user,
            frame: None,
        })
    }
    impl Api for NativeApi {
        fn read(&mut self) -> Result<Sample, Failure> {
            match read_sample(&mut || Ok(())) {
                Ok(sample) => Ok(sample),
                Err(crate::cpu_groups::ReadError::Field(error)) => Err(error),
                Err(crate::cpu_groups::ReadError::Context(_)) => Err(Failure::Api(0)),
            }
        }
        fn read_checked(
            &mut self,
            check: &mut Check<'_>,
        ) -> Result<Result<Sample, Failure>, ScopeError> {
            match read_sample(check) {
                Ok(sample) => Ok(Ok(sample)),
                Err(crate::cpu_groups::ReadError::Field(error)) => Ok(Err(error)),
                Err(crate::cpu_groups::ReadError::Context(error)) => Err(error),
            }
        }
    }
    /// Fresh Windows CPU percentage; bounded multi-group reads use a private thread.
    /// The desktop facade registers this automatically. First sample needs 300 ms.
    pub struct WindowsCpuBackend(CpuBackend<NativeApi>);
    impl WindowsCpuBackend {
        pub fn new() -> Self {
            Self(CpuBackend::new(NativeApi))
        }
    }
    impl Default for WindowsCpuBackend {
        fn default() -> Self {
            Self::new()
        }
    }
    impl Backend for WindowsCpuBackend {
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
    fn sdk_filetime_layout_and_unsigned_high_bits() {
        assert_eq!(size_of::<FILETIME>(), 8);
        assert_eq!(std::mem::offset_of!(FILETIME, dwHighDateTime), 4);
        assert_eq!(
            ticks(FILETIME {
                dwLowDateTime: u32::MAX,
                dwHighDateTime: u32::MAX,
            }),
            u64::MAX
        );
    }
}
#[cfg(target_os = "windows")]
pub use native::WindowsCpuBackend;

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::VecDeque;
    struct Fake {
        values: VecDeque<Result<Sample, Failure>>,
        calls: usize,
    }
    impl Api for Fake {
        fn read(&mut self) -> Result<Sample, Failure> {
            self.calls += 1;
            self.values.pop_front().expect("fixture read")
        }
    }
    fn sample(idle: u64, kernel: u64, user: u64) -> Result<Sample, Failure> {
        Ok(Sample {
            groups: 1,
            processors: 8,
            idle,
            kernel,
            user,
            frame: None,
        })
    }
    fn absent(value: &Observed<f64>, reason: ReasonCode) {
        assert!(value.value().is_none() && value.observed_at().is_none());
        assert_eq!(value.source(), Source::Win32);
        assert_eq!(value.reason(), Some(reason));
    }
    #[test]
    fn two_samples_boundary_and_fast_polling_do_not_starve_or_publish_cached_values() {
        let mut sampler = Sampler::default();
        let now = Instant::now();
        for milliseconds in [0, 100, 200, 299] {
            absent(
                &sampler.observe(
                    sample(milliseconds, 1000 + milliseconds * 2, 1000),
                    now + Duration::from_millis(milliseconds),
                    Timestamp(milliseconds),
                ),
                ReasonCode::TemporarilyUnavailable,
            );
        }
        let value = sampler.observe(sample(100, 1100, 1100), now + INTERVAL, Timestamp(300));
        assert_eq!(value.value(), Some(&50.0));
        assert_eq!(value.observed_at(), Some(Timestamp(300)));
        absent(
            &sampler.observe(sample(100, 1100, 1100), now + INTERVAL, Timestamp(301)),
            ReasonCode::TemporarilyUnavailable,
        );
    }
    #[test]
    fn actual_zero_full_load_and_large_counter_sums_remain_valid() {
        for (current, expected) in [
            (sample(100, 100, 0), 0.0),
            (sample(0, 100, 100), 100.0),
            (sample(u64::MAX, u64::MAX, u64::MAX), 50.0),
        ] {
            let now = Instant::now();
            let mut sampler = Sampler::default();
            sampler.observe(sample(0, 0, 0), now, Timestamp(1));
            assert_eq!(
                sampler
                    .observe(current, now + INTERVAL, Timestamp(2))
                    .value(),
                Some(&expected)
            );
        }
    }
    #[test]
    fn api_failures_always_clear_baseline_and_recovery_needs_a_new_pair() {
        for (code, state, reason) in [
            (0, Availability::Unavailable, ReasonCode::Unknown),
            (5, Availability::Restricted, ReasonCode::PermissionDenied),
            (
                8,
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            (13, Availability::Unavailable, ReasonCode::InvalidData),
            (
                14,
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            (87, Availability::Unavailable, ReasonCode::InvalidData),
            (
                170,
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            (
                1237,
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            (9999, Availability::Unavailable, ReasonCode::Unknown),
        ] {
            let mut sampler = Sampler::default();
            let now = Instant::now();
            sampler.observe(sample(0, 100, 100), now, Timestamp(0));
            assert!(
                sampler
                    .observe(sample(50, 150, 150), now + INTERVAL, Timestamp(1))
                    .value()
                    .is_some()
            );
            let bad = sampler.observe(Err(Failure::Api(code)), now + INTERVAL * 2, Timestamp(2));
            absent(&bad, reason);
            assert_eq!(bad.availability(), state);
            assert!(sampler.baseline.is_none());
            absent(
                &sampler.observe(sample(100, 200, 200), now + INTERVAL * 3, Timestamp(3)),
                ReasonCode::TemporarilyUnavailable,
            );
            assert_eq!(
                sampler
                    .observe(sample(150, 250, 250), now + INTERVAL * 4, Timestamp(4))
                    .value(),
                Some(&50.0)
            );
        }
    }
    #[test]
    fn invalid_counters_clear_baseline_instead_of_clamping() {
        for current in [
            sample(11, 10, 10),
            sample(0, 99, 100),
            sample(0, 100, 99),
            sample(9, 101, 100),
        ] {
            let now = Instant::now();
            let mut sampler = Sampler::default();
            sampler.observe(sample(0, 100, 100), now, Timestamp(0));
            absent(
                &sampler.observe(current, now + INTERVAL, Timestamp(1)),
                ReasonCode::InvalidData,
            );
            assert!(sampler.baseline.is_none());
        }
        let mut sampler = Sampler::default();
        let now = Instant::now();
        sampler.observe(sample(10, 100, 100), now, Timestamp(0));
        absent(
            &sampler.observe(sample(9, 101, 101), now + INTERVAL, Timestamp(1)),
            ReasonCode::InvalidData,
        );
    }
    #[test]
    fn zero_elapsed_counters_and_clock_regression_never_invent_load() {
        let mut sampler = Sampler::default();
        let now = Instant::now();
        sampler.observe(sample(0, 100, 100), now + INTERVAL, Timestamp(1));
        absent(
            &sampler.observe(sample(0, 100, 100), now, Timestamp(2)),
            ReasonCode::InvalidData,
        );
        sampler.observe(sample(0, 100, 100), now, Timestamp(3));
        absent(
            &sampler.observe(sample(0, 100, 100), now + INTERVAL, Timestamp(4)),
            ReasonCode::TemporarilyUnavailable,
        );
    }
    #[test]
    fn topology_changes_and_multiple_groups_never_report_group_load_as_system_load() {
        let now = Instant::now();
        let mut sampler = Sampler::default();
        sampler.observe(sample(0, 100, 100), now, Timestamp(0));
        let mut topology = sample(50, 150, 150).expect("sample");
        topology.processors = 4;
        absent(
            &sampler.observe(Ok(topology), now + INTERVAL, Timestamp(1)),
            ReasonCode::TemporarilyUnavailable,
        );
        topology.idle += 50;
        topology.kernel += 50;
        topology.user += 50;
        assert_eq!(
            sampler
                .observe(Ok(topology), now + INTERVAL * 2, Timestamp(2))
                .value(),
            Some(&50.0)
        );
        topology.groups = 2;
        let multi = sampler.observe(Ok(topology), now + INTERVAL * 3, Timestamp(3));
        absent(&multi, ReasonCode::NotSupported);
        assert_eq!(multi.availability(), Availability::Unsupported);
        assert!(sampler.baseline.is_none());
        for (groups, processors) in [(0, 8), (1, 0), (1, 65)] {
            topology.groups = groups;
            topology.processors = processors;
            absent(
                &sampler.observe(Ok(topology), now, Timestamp(4)),
                ReasonCode::InvalidData,
            );
        }
        absent(
            &sampler.observe(Err(Failure::TopologyChanged), now, Timestamp(5)),
            ReasonCode::TemporarilyUnavailable,
        );
    }
    #[test]
    fn every_refresh_reads_once_but_static_collection_does_not_read_cpu() {
        let api = Fake {
            values: vec![
                sample(0, 100, 100),
                Err(Failure::Api(5)),
                sample(10, 110, 110),
            ]
            .into(),
            calls: 0,
        };
        let mut backend = CpuBackend::new(api);
        let hw = HardwareBuilder::default()
            .with_backend(
                100,
                CpuBackend::new(Fake {
                    values: vec![Err(Failure::Api(5)), sample(0, 100, 100)].into(),
                    calls: 0,
                }),
            )
            .build()
            .expect("hardware");
        let first = hw.collect().expect("field failure");
        assert_eq!(
            first.dynamic.cpu_usage_percent.availability(),
            Availability::Restricted
        );
        let cap = hw
            .capabilities()
            .into_iter()
            .find(|c| c.field == "cpu_usage_percent")
            .expect("cap");
        assert_eq!(cap.level, CapabilityLevel::Restricted);
        hw.refresh_dynamic().expect("recover warmup");
        let cap = hw
            .capabilities()
            .into_iter()
            .find(|c| c.field == "cpu_usage_percent")
            .expect("recovered cap");
        assert_eq!(cap.level, CapabilityLevel::Partial);
        assert_eq!(cap.reason, Some(ReasonCode::TemporarilyUnavailable));
        // Test the boundary without sleeping or relying on scheduler timing.
        for _ in 0..3 {
            backend
                .sampler
                .refresh(&mut backend.api, || Ok(()))
                .expect("refresh");
        }
        assert_eq!(backend.api.calls, 3);
        assert!(
            backend
                .capabilities()
                .iter()
                .any(|c| c.level == CapabilityLevel::Partial && c.source == Source::Win32)
        );
    }
    #[test]
    fn cancellation_before_and_timeout_after_read_clear_baseline() {
        let mut api = Fake {
            values: vec![sample(0, 100, 100)].into(),
            calls: 0,
        };
        let mut sampler = Sampler::default();
        sampler.observe(sample(0, 0, 0), Instant::now(), Timestamp(0));
        assert_eq!(
            sampler
                .refresh(&mut api, || Err(ScopeError::new(ErrorCode::Cancelled)))
                .expect_err("cancel")
                .code,
            ErrorCode::Cancelled
        );
        assert_eq!(api.calls, 0);
        assert!(sampler.baseline.is_none());
        sampler.observe(sample(0, 0, 0), Instant::now(), Timestamp(0));
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
        assert_eq!(api.calls, 1);
        assert!(sampler.baseline.is_none());
        absent(
            &sampler.observe(sample(0, 100, 100), Instant::now(), Timestamp(1)),
            ReasonCode::TemporarilyUnavailable,
        );
    }
    fn grouped(values: [(u64, u64, u64); 2], mask: u64) -> Result<Sample, Failure> {
        use crate::cpu_groups::{MAX_GROUPS, Topology};
        let mut topology = Topology {
            count: 2,
            ..Topology::default()
        };
        topology.masks[0] = u64::MAX;
        topology.masks[1] = mask;
        let mut frame = Frame {
            topology,
            counters: [Counters::default(); MAX_GROUPS],
        };
        for (slot, (idle, kernel, user)) in frame.counters.iter_mut().zip(values) {
            *slot = Counters { idle, kernel, user };
        }
        Ok(Sample {
            groups: 2,
            processors: 65,
            idle: 0,
            kernel: 0,
            user: 0,
            frame: Some(frame),
        })
    }
    #[test]
    fn multi_group_percentage_is_time_weighted_not_average_of_percentages() {
        let now = Instant::now();
        let mut sampler = Sampler::default();
        sampler.observe(grouped([(0, 0, 0); 2], 1), now, Timestamp(0));
        let value = sampler.observe(
            grouped([(0, 100, 0), (900, 900, 0)], 1),
            now + INTERVAL,
            Timestamp(1),
        );
        assert_eq!(value.value(), Some(&10.0));
        assert_eq!(value.source(), Source::Win32);
    }
    #[test]
    fn group_reset_cannot_hide_behind_growth_in_another_group() {
        let now = Instant::now();
        let mut sampler = Sampler::default();
        sampler.observe(
            grouped([(20, 100, 100), (0, 100, 100)], 1),
            now,
            Timestamp(0),
        );
        let value = sampler.observe(
            grouped([(20, 99, 100), (0, 10000, 10000)], 1),
            now + INTERVAL,
            Timestamp(1),
        );
        absent(&value, ReasonCode::InvalidData);
        assert!(sampler.baseline.is_none());
    }
    #[test]
    fn group_mask_change_rewarms_even_when_total_count_is_unchanged() {
        let now = Instant::now();
        let mut sampler = Sampler::default();
        sampler.observe(grouped([(0, 0, 0); 2], 1), now, Timestamp(0));
        absent(
            &sampler.observe(
                grouped([(0, 100, 0), (900, 900, 0)], 2),
                now + INTERVAL,
                Timestamp(1),
            ),
            ReasonCode::TemporarilyUnavailable,
        );
        assert_eq!(
            sampler
                .observe(
                    grouped([(0, 200, 0), (1800, 1800, 0)], 2),
                    now + INTERVAL * 2,
                    Timestamp(2)
                )
                .value(),
            Some(&10.0)
        );
    }
}
