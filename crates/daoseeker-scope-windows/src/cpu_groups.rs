//! Fixed-bound group topology and per-group deltas, without SDK types.
use super::cpu::{Failure, Sample};
use daoseeker_scope_core::*;

use super::cpu_groups_wire::WireError;
pub(super) use super::cpu_groups_wire::{MAX_GROUPS, Topology};
pub(super) type Check<'a> = dyn FnMut() -> Result<(), ScopeError> + Send + 'a;
impl From<WireError> for Failure {
    fn from(error: WireError) -> Self {
        match error {
            WireError::Invalid => Self::Api(13),
            WireError::Limit => Self::Limit,
        }
    }
}
#[derive(Clone, Copy, Debug, Default)]
pub(super) struct Counters {
    pub idle: u64,
    pub kernel: u64,
    pub user: u64,
}
impl Counters {
    pub fn valid(self) -> bool {
        self.idle <= self.kernel
    }
    pub fn delta(self, previous: Self) -> Option<(u128, u128, u128)> {
        let idle = self.idle.checked_sub(previous.idle)?;
        let kernel = self.kernel.checked_sub(previous.kernel)?;
        let user = self.user.checked_sub(previous.user)?;
        (idle <= kernel).then_some((u128::from(idle), u128::from(kernel), u128::from(user)))
    }
}
#[derive(Clone, Copy, Debug)]
pub(super) struct Frame {
    pub topology: Topology,
    pub counters: [Counters; MAX_GROUPS],
}
impl Frame {
    pub fn valid(&self) -> bool {
        self.topology.processors().is_ok()
            && self.counters[..usize::from(self.topology.count)]
                .iter()
                .all(|c| c.valid())
    }
    pub fn delta(&self, previous: &Self) -> Option<(u128, u128, u128)> {
        if self.topology != previous.topology {
            return None;
        }
        let mut total = (0, 0, 0);
        for (current, previous) in self
            .counters
            .iter()
            .zip(&previous.counters)
            .take(usize::from(self.topology.count))
        {
            let d = current.delta(*previous)?;
            total.0 += d.0;
            total.1 += d.1;
            total.2 += d.2;
        }
        Some(total)
    }
}
fn parse(bytes: &[u8]) -> Result<Topology, Failure> {
    super::cpu_groups_wire::parse(bytes).map_err(Into::into)
}
#[derive(Debug)]
pub(super) enum ReadError {
    Field(Failure),
    Context(ScopeError),
}
pub(super) fn checked<T>(
    read: impl FnOnce() -> Result<T, Failure>,
    check: &mut Check<'_>,
) -> Result<T, ReadError> {
    check().map_err(ReadError::Context)?;
    let value = read();
    check().map_err(ReadError::Context)?;
    value.map_err(ReadError::Field)
}
pub(super) trait GroupApi {
    fn topology(&mut self) -> Result<Topology, Failure>;
    fn select(&mut self, group: u16, mask: u64) -> Result<(), Failure>;
    fn times(&mut self) -> Result<Counters, Failure>;
}
pub(super) fn collect(api: &mut impl GroupApi, check: &mut Check<'_>) -> Result<Sample, ReadError> {
    let topology = checked(|| api.topology(), check)?;
    let processors = topology
        .processors()
        .map_err(|error| ReadError::Field(error.into()))?;
    let mut frame = Frame {
        topology,
        counters: [Counters::default(); MAX_GROUPS],
    };
    for group in 0..topology.count {
        checked(
            || api.select(group, topology.masks[usize::from(group)]),
            check,
        )?;
        let counters = checked(|| api.times(), check)?;
        if !counters.valid() {
            return Err(ReadError::Field(Failure::Api(13)));
        }
        frame.counters[usize::from(group)] = counters;
    }
    if checked(|| api.topology(), check)? != topology {
        return Err(ReadError::Field(Failure::TopologyChanged));
    }
    Ok(Sample {
        groups: topology.count,
        processors,
        idle: 0,
        kernel: 0,
        user: 0,
        frame: Some(frame),
    })
}

#[cfg(all(target_os = "windows", target_pointer_width = "64"))]
mod native {
    use super::*;
    use std::{mem, ptr, thread};
    use windows_sys::Win32::{
        Foundation::{FILETIME, GetLastError},
        System::{
            SystemInformation::{
                GROUP_AFFINITY, GROUP_RELATIONSHIP, GetLogicalProcessorInformationEx,
                PROCESSOR_GROUP_INFO, RelationGroup, SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX,
            },
            Threading::{GetCurrentThread, GetSystemTimes, SetThreadGroupAffinity},
        },
    };
    const _: () = {
        assert!(mem::size_of::<PROCESSOR_GROUP_INFO>() == 48);
        assert!(mem::offset_of!(PROCESSOR_GROUP_INFO, ActiveProcessorMask) == 40);
        assert!(mem::offset_of!(GROUP_RELATIONSHIP, GroupInfo) == 24);
        assert!(mem::offset_of!(SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX, Anonymous) == 8);
        assert!(mem::align_of::<SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX>() <= 8);
        assert!(mem::size_of::<GROUP_AFFINITY>() == 16);
    };
    struct NativeApi;
    impl GroupApi for NativeApi {
        fn topology(&mut self) -> Result<Topology, Failure> {
            let mut buffer = [0u64; 128];
            let mut length = 1024u32;
            // SAFETY: initialized 1024-byte buffer aligned for the SDK record;
            // read-only fixed relation. Length is checked before any output is read.
            if unsafe {
                GetLogicalProcessorInformationEx(
                    RelationGroup,
                    buffer.as_mut_ptr().cast(),
                    &mut length,
                )
            } == 0
            {
                // SAFETY: immediate documented failure status.
                let code = unsafe { GetLastError() };
                return Err(if code == 122 && length > 1024 {
                    Failure::Limit
                } else {
                    Failure::Api(code)
                });
            }
            if length > 1024 {
                return Err(Failure::Api(13));
            }
            // SAFETY: length is bounded by the fully initialized buffer; byte views
            // have alignment 1 and parse only validated integer fields, not unions.
            let bytes = unsafe {
                std::slice::from_raw_parts(buffer.as_ptr().cast::<u8>(), length as usize)
            };
            parse(bytes)
        }
        fn select(&mut self, group: u16, mask: u64) -> Result<(), Failure> {
            let affinity = GROUP_AFFINITY {
                Mask: mask as usize,
                Group: group,
                Reserved: [0; 3],
            };
            // SAFETY: this method runs exclusively on a newly owned helper thread.
            // The pseudo handle is borrowed, never closed. No caller affinity changes.
            if unsafe { SetThreadGroupAffinity(GetCurrentThread(), &affinity, ptr::null_mut()) }
                == 0
            {
                // SAFETY: immediate documented failure status.
                Err(Failure::Api(unsafe { GetLastError() }))
            } else {
                Ok(())
            }
        }
        fn times(&mut self) -> Result<Counters, Failure> {
            let mut idle = FILETIME::default();
            let mut kernel = FILETIME::default();
            let mut user = FILETIME::default();
            // SAFETY: distinct live initialized outputs; no pointer is retained.
            if unsafe { GetSystemTimes(&mut idle, &mut kernel, &mut user) } == 0 {
                // SAFETY: immediate documented failure status.
                return Err(Failure::Api(unsafe { GetLastError() }));
            }
            fn ticks(value: FILETIME) -> u64 {
                (u64::from(value.dwHighDateTime) << 32) | u64::from(value.dwLowDateTime)
            }
            Ok(Counters {
                idle: ticks(idle),
                kernel: ticks(kernel),
                user: ticks(user),
            })
        }
    }
    pub(crate) fn read_native(check: &mut Check<'_>) -> Result<Sample, ReadError> {
        check().map_err(ReadError::Context)?;
        let result = thread::scope(|scope| {
            let child_check = &mut *check;
            let child = thread::Builder::new()
                .name("dscope-cpu-groups".into())
                .spawn_scoped(scope, move || collect(&mut NativeApi, child_check));
            match child {
                Ok(child) => child
                    .join()
                    .unwrap_or(Err(ReadError::Field(Failure::Api(0)))),
                Err(error) => Err(ReadError::Field(Failure::Api(
                    error
                        .raw_os_error()
                        .and_then(|code| u32::try_from(code).ok())
                        .unwrap_or(0),
                ))),
            }
        });
        check().map_err(ReadError::Context)?;
        result
    }
    #[cfg(test)]
    #[test]
    fn native_group_worker_reads_sdk_topology_without_changing_caller_affinity() {
        use windows_sys::Win32::System::Threading::GetThreadGroupAffinity;
        fn affinity() -> GROUP_AFFINITY {
            let mut value = GROUP_AFFINITY::default();
            // SAFETY: borrowed current-thread pseudo handle and live SDK output.
            let ok = unsafe { GetThreadGroupAffinity(GetCurrentThread(), &mut value) };
            assert_ne!(ok, 0);
            value
        }
        let before = affinity();
        let first = read_native(&mut || Ok(())).expect("first group frame");
        thread::sleep(std::time::Duration::from_millis(350));
        let second = read_native(&mut || Ok(())).expect("second group frame");
        let after = affinity();
        assert_eq!((before.Group, before.Mask), (after.Group, after.Mask));
        let frame = second.frame.expect("group frame");
        let d = frame
            .delta(&first.frame.expect("first"))
            .expect("valid per-group deltas");
        assert!(d.1 + d.2 > 0 && d.0 <= d.1);
        eprintln!(
            "group SDK metadata: groups={} processors={} helper=true caller_affinity_unchanged=true",
            second.groups, second.processors
        );
    }
}
#[cfg(all(target_os = "windows", target_pointer_width = "64"))]
pub(super) use native::read_native;
#[cfg(all(target_os = "windows", not(target_pointer_width = "64")))]
pub(super) fn read_native(_check: &mut Check<'_>) -> Result<Sample, ReadError> {
    Err(ReadError::Field(Failure::Limit))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn wire(masks: &[u64]) -> Vec<u8> {
        let mut bytes = vec![0; 32 + 48 * masks.len()];
        let size = bytes.len() as u32;
        bytes[0..4].copy_from_slice(&4u32.to_le_bytes());
        bytes[4..8].copy_from_slice(&size.to_le_bytes());
        bytes[8..10].copy_from_slice(&(masks.len() as u16).to_le_bytes());
        bytes[10..12].copy_from_slice(&(masks.len() as u16).to_le_bytes());
        for (index, mask) in masks.iter().enumerate() {
            let start = 32 + 48 * index;
            bytes[start] = 64;
            bytes[start + 1] = mask.count_ones() as u8;
            bytes[start + 40..start + 48].copy_from_slice(&mask.to_le_bytes());
        }
        bytes
    }
    fn topology() -> Topology {
        parse(&wire(&[0x8000_0000_0000_0005, 3])).unwrap()
    }
    #[test]
    fn topology_accepts_sparse_masks_and_bounded_maximum() {
        let value = topology();
        assert_eq!(value.count, 2);
        assert_eq!(value.processors().unwrap(), 5);
        let value = parse(&wire(&[u64::MAX; MAX_GROUPS])).unwrap();
        assert_eq!(value.processors().unwrap(), 1024);
    }
    #[test]
    fn topology_rejects_truncation_counts_masks_and_wrong_record_shape() {
        let valid = wire(&[3, 7]);
        for length in 0..valid.len() {
            assert!(parse(&valid[..length]).is_err());
        }
        for (index, value) in [
            (0, 3),
            (4, 0),
            (8, 0),
            (10, 0),
            (32, 0),
            (32, 65),
            (33, 0),
            (33, 3),
        ] {
            let mut bad = valid.clone();
            bad[index] = value;
            assert!(parse(&bad).is_err(), "{index}");
        }
        let mut bad = wire(&[1u64 << 63]);
        bad[32] = 2;
        assert!(parse(&bad).is_err());
        assert!(matches!(
            parse(&wire(&[1; MAX_GROUPS + 1])),
            Err(Failure::Limit)
        ));
        assert!(parse(&vec![0; 1025]).is_err());
    }
    #[test]
    fn topology_validation_never_slices_an_out_of_bounds_count() {
        for count in [0, 17, u16::MAX] {
            assert!(
                Topology {
                    count,
                    ..Topology::default()
                }
                .processors()
                .is_err()
            );
        }
        let mut value = topology();
        value.masks[2] = 1;
        assert!(value.processors().is_err());
        let mut value = topology();
        value.masks[0] = 0;
        assert!(value.processors().is_err());
    }
    #[test]
    fn per_group_deltas_detect_resets_and_sum_above_u64() {
        let base = Frame {
            topology: topology(),
            counters: [Counters::default(); MAX_GROUPS],
        };
        let mut current = base;
        for value in &mut current.counters[..2] {
            *value = Counters {
                idle: u64::MAX,
                kernel: u64::MAX,
                user: u64::MAX,
            };
        }
        let d = current.delta(&base).unwrap();
        assert_eq!(
            d,
            (
                u128::from(u64::MAX) * 2,
                u128::from(u64::MAX) * 2,
                u128::from(u64::MAX) * 2
            )
        );
        let mut previous = base;
        previous.counters[0] = Counters {
            idle: 20,
            kernel: 100,
            user: 100,
        };
        for value in [
            Counters {
                idle: 19,
                kernel: 200,
                user: 200,
            },
            Counters {
                idle: 20,
                kernel: 99,
                user: 200,
            },
            Counters {
                idle: 20,
                kernel: 200,
                user: 99,
            },
        ] {
            current.counters[0] = value;
            assert!(current.delta(&previous).is_none());
        }
    }
    struct Fake {
        calls: usize,
        fail_at: Option<usize>,
        changed: bool,
        selected: Vec<(u16, u64)>,
    }
    impl Fake {
        fn healthy() -> Self {
            Self {
                calls: 0,
                fail_at: None,
                changed: false,
                selected: Vec::new(),
            }
        }
        fn tick(&mut self) -> Result<(), Failure> {
            self.calls += 1;
            if self.fail_at == Some(self.calls) {
                Err(Failure::Api(5))
            } else {
                Ok(())
            }
        }
    }
    impl GroupApi for Fake {
        fn topology(&mut self) -> Result<Topology, Failure> {
            self.tick()?;
            let mut value = topology();
            if self.changed && self.calls > 1 {
                value.masks[1] = 6;
            }
            Ok(value)
        }
        fn select(&mut self, group: u16, mask: u64) -> Result<(), Failure> {
            self.tick()?;
            self.selected.push((group, mask));
            Ok(())
        }
        fn times(&mut self) -> Result<Counters, Failure> {
            self.tick()?;
            Ok(Counters {
                idle: 0,
                kernel: 1,
                user: 1,
            })
        }
    }
    #[test]
    fn collection_uses_actual_masks_and_rechecks_complete_topology() {
        let mut api = Fake::healthy();
        let sample = collect(&mut api, &mut || Ok(())).unwrap();
        assert_eq!((sample.groups, sample.processors), (2, 5));
        assert_eq!(api.calls, 6);
        assert_eq!(api.selected, vec![(0, 0x8000_0000_0000_0005), (1, 3)]);
        assert!(sample.frame.unwrap().valid());
    }
    #[test]
    fn any_group_api_failure_discards_whole_frame_and_stops_calls() {
        for failure in 1..=6 {
            let mut api = Fake {
                fail_at: Some(failure),
                ..Fake::healthy()
            };
            assert!(matches!(
                collect(&mut api, &mut || Ok(())),
                Err(ReadError::Field(Failure::Api(5)))
            ));
            assert_eq!(api.calls, failure);
        }
    }
    #[test]
    fn changed_mask_with_same_count_is_not_a_successful_frame() {
        let mut api = Fake {
            changed: true,
            ..Fake::healthy()
        };
        assert!(matches!(
            collect(&mut api, &mut || Ok(())),
            Err(ReadError::Field(Failure::TopologyChanged))
        ));
        assert_eq!(api.calls, 6);
    }
    #[test]
    fn cancellation_and_deadline_checks_cover_every_group_operation() {
        for code in [ErrorCode::Cancelled, ErrorCode::Timeout] {
            for reject_at in 1..=12 {
                let mut api = Fake::healthy();
                let mut checks = 0;
                let error = collect(&mut api, &mut || {
                    checks += 1;
                    if checks == reject_at {
                        Err(ScopeError::new(code))
                    } else {
                        Ok(())
                    }
                });
                assert!(matches!(error,Err(ReadError::Context(error)) if error.code==code));
                assert_eq!(checks, reject_at);
                assert_eq!(api.calls, reject_at / 2);
            }
        }
    }
}
