//! Bounded active-for-drawing view; native IDs and modes are never cached.
use daoseeker_scope_core::*;
use std::collections::BTreeSet;

const SLOTS: usize = 1025;
#[derive(Clone, Copy, Debug)]
struct Failure(Availability, ReasonCode);
const INVALID: Failure = Failure(Availability::Unavailable, ReasonCode::InvalidData);
const TEMP: Failure = Failure(
    Availability::Unavailable,
    ReasonCode::TemporarilyUnavailable,
);
impl Failure {
    fn observed<T>(self) -> Observed<T> {
        Observed::missing(self.0, Source::AppleApi, self.1).expect("missing failure state")
    }
}
fn error(code: i32) -> Failure {
    match code {
        1001 | 1007 | 1008 => INVALID,
        1002..=1004 | 1010 => TEMP,
        1006 => Failure(Availability::Unsupported, ReasonCode::NotSupported),
        1011 => Failure(Availability::Unavailable, ReasonCode::NotPresent),
        _ => Failure(Availability::Unavailable, ReasonCode::Unknown),
    }
}
struct List {
    ids: [u32; SLOTS],
    count: u32,
}
trait Api {
    fn active(&mut self) -> Result<List, Failure>;
    fn pixels(&mut self, id: u32) -> Result<(u64, u64), Failure>;
}
fn ids(list: List, limit: usize) -> Result<Vec<u32>, Failure> {
    let count = list.count as usize;
    if count >= SLOTS || count > limit {
        return Err(INVALID);
    }
    let ids = &list.ids[..count];
    if ids.contains(&0) || ids.iter().copied().collect::<BTreeSet<_>>().len() != count {
        return Err(INVALID);
    }
    Ok(ids.to_vec())
}
fn pixels(raw: Result<(u64, u64), Failure>, at: Timestamp) -> (Observed<u32>, Observed<u32>) {
    let pair = raw.and_then(|(w, h)| match (u32::try_from(w), u32::try_from(h)) {
        (Ok(w), Ok(h)) if w > 0 && h > 0 => Ok((w, h)),
        _ => Err(INVALID),
    });
    match pair {
        Ok((w, h)) => (
            Observed::available(w, Source::AppleApi, at),
            Observed::available(h, Source::AppleApi, at),
        ),
        Err(f) => (f.observed(), f.observed()),
    }
}
fn collect_with(
    api: &mut impl Api,
    options: &Options,
    mut check: impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<Vec<DisplayInfo>>, ScopeError> {
    options.validate()?;
    for _ in 0..3 {
        check()?;
        let initial = api.active();
        check()?;
        let initial = match initial.and_then(|list| ids(list, options.max_entries)) {
            Ok(ids) => ids,
            Err(f) => return Ok(f.observed()),
        };
        let mut entries = Vec::with_capacity(initial.len());
        for &id in &initial {
            check()?;
            let raw = api.pixels(id);
            check()?;
            let (width, height) = pixels(raw, Timestamp::now()?);
            let mut entry = DisplayInfo::default();
            entry.name = Failure(Availability::Unsupported, ReasonCode::NotSupported).observed();
            entry.width_pixels = width;
            entry.height_pixels = height;
            entries.push(entry);
        }
        check()?;
        let final_ids = api.active();
        check()?;
        let final_ids = match final_ids.and_then(|list| ids(list, options.max_entries)) {
            Ok(ids) => ids,
            Err(f) => return Ok(f.observed()),
        };
        if initial.iter().collect::<BTreeSet<_>>() != final_ids.iter().collect::<BTreeSet<_>>() {
            continue;
        }
        return Ok(Observed::available(
            entries,
            Source::AppleApi,
            Timestamp::now()?,
        ));
    }
    Ok(TEMP.observed())
}

#[cfg(target_os = "macos")]
mod native {
    use super::*;
    use std::{ffi::c_void, ptr::NonNull};
    // Public C ABI: SDK types are uint32_t, int32_t, size_t and an opaque CF pointer.
    // The independent C probe checks SDK scalar widths and CGError values.
    #[link(name = "CoreGraphics", kind = "framework")]
    unsafe extern "C" {
        fn CGGetActiveDisplayList(max: u32, displays: *mut u32, count: *mut u32) -> i32;
        fn CGDisplayCopyDisplayMode(display: u32) -> *mut c_void;
        fn CGDisplayModeGetPixelWidth(mode: *const c_void) -> usize;
        fn CGDisplayModeGetPixelHeight(mode: *const c_void) -> usize;
        fn CGDisplayModeRelease(mode: *const c_void);
    }
    struct Mode(NonNull<c_void>);
    impl Drop for Mode {
        fn drop(&mut self) {
            // SAFETY: exactly one owned Copy result, still live; no other release.
            unsafe { CGDisplayModeRelease(self.0.as_ptr()) };
        }
    }
    struct Native;
    impl Api for Native {
        fn active(&mut self) -> Result<List, Failure> {
            let mut list = List {
                ids: [0; SLOTS],
                count: 0,
            };
            // SAFETY: initialized array has SLOTS writable u32s, count is writable.
            let code = unsafe {
                CGGetActiveDisplayList(SLOTS as u32, list.ids.as_mut_ptr(), &mut list.count)
            };
            if code == 0 {
                Ok(list)
            } else {
                Err(error(code))
            }
        }
        fn pixels(&mut self, id: u32) -> Result<(u64, u64), Failure> {
            // SAFETY: display IDs are scalar tokens returned by enumeration; API
            // accepts stale/invalid tokens and returns NULL. Copy gives ownership.
            let mode = Mode(NonNull::new(unsafe { CGDisplayCopyDisplayMode(id) }).ok_or(TEMP)?);
            // SAFETY: nonnull owned mode stays alive until both accessors return.
            let pair = unsafe {
                (
                    CGDisplayModeGetPixelWidth(mode.0.as_ptr()),
                    CGDisplayModeGetPixelHeight(mode.0.as_ptr()),
                )
            };
            Ok((pair.0 as u64, pair.1 as u64))
        }
    }
    pub(crate) fn collect(ctx: &CollectContext) -> Result<Observed<Vec<DisplayInfo>>, ScopeError> {
        collect_with(&mut Native, &ctx.options, || ctx.check())
    }
}
#[cfg(target_os = "macos")]
pub(crate) use native::collect;

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::VecDeque;
    struct Fake {
        lists: VecDeque<Result<List, Failure>>,
        sizes: VecDeque<Result<(u64, u64), Failure>>,
        reads: usize,
    }
    fn list(values: &[u32]) -> List {
        let mut result = List {
            ids: [0; SLOTS],
            count: values.len() as u32,
        };
        result.ids[..values.len()].copy_from_slice(values);
        result
    }
    impl Fake {
        fn new(initial: &[u32], final_ids: &[u32]) -> Self {
            Self {
                lists: [Ok(list(initial)), Ok(list(final_ids))].into(),
                sizes: initial.iter().map(|_| Ok((3840, 2160))).collect(),
                reads: 0,
            }
        }
    }
    impl Api for Fake {
        fn active(&mut self) -> Result<List, Failure> {
            self.reads += 1;
            self.lists.pop_front().expect("scripted query")
        }
        fn pixels(&mut self, _: u32) -> Result<(u64, u64), Failure> {
            self.reads += 1;
            self.sizes.pop_front().expect("scripted mode")
        }
    }
    #[test]
    fn actual_empty_view_is_rechecked_and_names_are_not_fabricated() {
        let mut api = Fake::new(&[], &[]);
        assert!(
            collect_with(&mut api, &Options::default(), || Ok(()))
                .unwrap()
                .value()
                .unwrap()
                .is_empty()
        );
        assert_eq!(api.reads, 2);
        let result =
            collect_with(&mut Fake::new(&[7], &[7]), &Options::default(), || Ok(())).unwrap();
        let entry = &result.value().unwrap()[0];
        assert_eq!(entry.name.availability(), Availability::Unsupported);
        assert_eq!(entry.name.source(), Source::AppleApi);
        assert_eq!(entry.width_pixels.value(), Some(&3840));
        assert_eq!(entry.height_pixels.value(), Some(&2160));
    }
    #[test]
    fn counts_and_ids_are_validated_before_projecting_a_prefix() {
        for count in [1025, 1026, u32::MAX] {
            let mut bad = list(&[]);
            bad.count = count;
            assert!(ids(bad, 1024).is_err());
        }
        assert!(ids(list(&[0]), 128).is_err());
        assert!(ids(list(&[1, 1]), 128).is_err());
        assert!(ids(list(&[1, 2]), 1).is_err());
        let full: Vec<_> = (1..=1024).collect();
        assert_eq!(ids(list(&full), 1024).unwrap().len(), 1024);
        let mut api = Fake::new(&[1, 2], &[1, 2]);
        let options = Options {
            max_entries: 1,
            ..Options::default()
        };
        assert_eq!(
            collect_with(&mut api, &options, || Ok(()))
                .unwrap()
                .reason(),
            Some(ReasonCode::InvalidData)
        );
        assert_eq!(api.reads, 1);
    }
    #[test]
    fn invalid_modes_fail_as_a_pair_without_losing_other_entries() {
        for raw in [
            Ok((0, 1080)),
            Ok((1920, 0)),
            Ok((u64::MAX, 1080)),
            Err(TEMP),
        ] {
            let (w, h) = pixels(raw, Timestamp(1));
            assert!(w.value().is_none() && h.value().is_none());
            assert_eq!(w.reason(), h.reason());
            assert_eq!(w.observed_at(), h.observed_at());
        }
        let mut api = Fake::new(&[1, 2], &[1, 2]);
        api.sizes = [Err(TEMP), Ok((1920, 1080))].into();
        let result = collect_with(&mut api, &Options::default(), || Ok(())).unwrap();
        assert_eq!(result.value().unwrap().len(), 2);
        assert!(result.value().unwrap()[0].width_pixels.value().is_none());
        assert_eq!(result.value().unwrap()[1].width_pixels.value(), Some(&1920));
    }
    #[test]
    fn cg_errors_do_not_invent_permissions_or_empty_success() {
        for (code, reason) in [
            (1001, ReasonCode::InvalidData),
            (1002, ReasonCode::TemporarilyUnavailable),
            (1004, ReasonCode::TemporarilyUnavailable),
            (1006, ReasonCode::NotSupported),
            (1011, ReasonCode::NotPresent),
            (1000, ReasonCode::Unknown),
            (1009, ReasonCode::Unknown),
        ] {
            assert_eq!(error(code).1, reason);
            let mut api = Fake::new(&[], &[]);
            api.lists = [Err(error(code))].into();
            let result = collect_with(&mut api, &Options::default(), || Ok(())).unwrap();
            assert!(result.value().is_none());
            assert_eq!(result.reason(), Some(reason));
            let mut api = Fake::new(&[1], &[1]);
            api.lists.pop_back();
            api.lists.push_back(Err(error(code)));
            assert!(
                collect_with(&mut api, &Options::default(), || Ok(()))
                    .unwrap()
                    .value()
                    .is_none()
            );
        }
    }
    #[test]
    fn reorder_is_allowed_and_topology_changes_retry_without_old_prefix() {
        let result = collect_with(
            &mut Fake::new(&[1, 2], &[2, 1]),
            &Options::default(),
            || Ok(()),
        )
        .unwrap();
        assert_eq!(result.value().unwrap().len(), 2);
        let mut api = Fake::new(&[], &[]);
        api.lists = [vec![], vec![1], vec![2], vec![3], vec![4], vec![5]]
            .iter()
            .map(|v| Ok(list(v)))
            .collect();
        api.sizes = [Ok((1, 1)), Ok((1, 1))].into();
        assert_eq!(
            collect_with(&mut api, &Options::default(), || Ok(()))
                .unwrap()
                .reason(),
            Some(ReasonCode::TemporarilyUnavailable)
        );
        let mut api = Fake::new(&[], &[]);
        api.lists = [vec![], vec![1], vec![2], vec![2]]
            .iter()
            .map(|v| Ok(list(v)))
            .collect();
        api.sizes = [Ok((640, 480))].into();
        assert_eq!(
            collect_with(&mut api, &Options::default(), || Ok(()))
                .unwrap()
                .value()
                .unwrap()[0]
                .width_pixels
                .value(),
            Some(&640)
        );
    }
    #[test]
    fn cancellation_deadline_and_invalid_options_prevent_reads() {
        for code in [ErrorCode::Cancelled, ErrorCode::Timeout] {
            let mut api = Fake::new(&[], &[]);
            assert_eq!(
                collect_with(&mut api, &Options::default(), || Err(ScopeError::new(code)))
                    .unwrap_err()
                    .code,
                code
            );
            assert_eq!(api.reads, 0);
        }
        let mut api = Fake::new(&[], &[]);
        let options = Options {
            max_entries: 0,
            ..Options::default()
        };
        assert_eq!(
            collect_with(&mut api, &options, || Ok(()))
                .unwrap_err()
                .code,
            ErrorCode::InvalidArgument
        );
        assert_eq!(api.reads, 0);
    }
    #[test]
    fn cancellation_after_mode_query_prevents_the_confirmation_call() {
        use std::sync::{
            Arc,
            atomic::{AtomicBool, Ordering},
        };
        struct Cancelling(Arc<AtomicBool>, usize);
        impl Api for Cancelling {
            fn active(&mut self) -> Result<List, Failure> {
                self.1 += 1;
                assert_eq!(self.1, 1, "confirmation must not run after cancellation");
                Ok(list(&[1]))
            }
            fn pixels(&mut self, _: u32) -> Result<(u64, u64), Failure> {
                self.0.store(true, Ordering::SeqCst);
                Ok((1920, 1080))
            }
        }
        let flag = Arc::new(AtomicBool::new(false));
        let mut api = Cancelling(flag.clone(), 0);
        let result = collect_with(&mut api, &Options::default(), || {
            if flag.load(Ordering::SeqCst) {
                Err(ScopeError::new(ErrorCode::Cancelled))
            } else {
                Ok(())
            }
        });
        assert_eq!(result.unwrap_err().code, ErrorCode::Cancelled);
    }
    #[test]
    fn static_values_empty_and_failures_are_cached_until_new_hardware() {
        use std::sync::{
            Arc,
            atomic::{AtomicUsize, Ordering},
        };
        struct Reader(Arc<AtomicUsize>, Arc<AtomicUsize>);
        impl Backend for Reader {
            fn name(&self) -> &'static str {
                "display-fixture"
            }
            fn capabilities(&self) -> Capabilities {
                vec![]
            }
            fn collect_static(
                &mut self,
                ctx: &CollectContext,
            ) -> Result<StaticSnapshot, ScopeError> {
                self.1.fetch_add(1, Ordering::SeqCst);
                let mut api = match self.0.load(Ordering::SeqCst) {
                    0 => Fake::new(&[1], &[1]),
                    1 => Fake::new(&[], &[]),
                    _ => {
                        let mut a = Fake::new(&[], &[]);
                        a.lists = [Err(TEMP)].into();
                        a
                    }
                };
                let mut result = StaticSnapshot::default();
                result.displays = collect_with(&mut api, &ctx.options, || ctx.check())?;
                Ok(result)
            }
            fn refresh_dynamic(
                &mut self,
                _: &CollectContext,
            ) -> Result<DynamicSnapshot, ScopeError> {
                Ok(DynamicSnapshot::default())
            }
        }
        for initial in 0..3 {
            let state = Arc::new(AtomicUsize::new(initial));
            let reads = Arc::new(AtomicUsize::new(0));
            let build = || {
                HardwareBuilder::new(Options::default())
                    .with_backend(10, Reader(state.clone(), reads.clone()))
                    .build()
                    .unwrap()
            };
            let hardware = build();
            let first = hardware.collect().unwrap().static_info.displays;
            state.store((initial + 1) % 3, Ordering::SeqCst);
            hardware.refresh_dynamic().unwrap();
            assert_eq!(hardware.collect().unwrap().static_info.displays, first);
            assert_eq!(reads.load(Ordering::SeqCst), 1);
            assert_ne!(build().collect().unwrap().static_info.displays, first);
            assert_eq!(reads.load(Ordering::SeqCst), 2);
        }
    }
}
