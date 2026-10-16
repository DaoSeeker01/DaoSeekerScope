//! Bounded CCD active paths. Native identities never enter the public snapshot.
use daoseeker_scope_core::*;
use std::collections::BTreeSet;

const MAX_PATHS: usize = 1024;
const MAX_MODES: usize = 4096;
const INVALID: u32 = 13; // ERROR_INVALID_DATA, from the public Windows SDK.
const BUFFER: u32 = 122; // ERROR_INSUFFICIENT_BUFFER.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
struct Key(u32, i32, u32); // Adapter LUID halves and target ID, transient only.
struct Path {
    key: Key,
    active: bool,
    virtual_mode: bool,
    index: u32,
}
struct Mode {
    key: Key,
    size: Option<(u32, u32)>, // Only TARGET_MODE has a size.
}
struct Frame {
    paths: Vec<Path>,
    modes: Vec<Mode>,
}
struct Name {
    from_edid: bool,
    text: [u16; 64],
}
trait Api {
    fn sizes(&mut self) -> Result<(usize, usize), u32>;
    fn query(&mut self, paths: usize, modes: usize) -> Result<Frame, u32>;
    fn name(&mut self, key: Key) -> Result<Name, u32>;
}
fn failure<T>(code: u32) -> Observed<T> {
    match code {
        5 => Observed::restricted(Source::Win32, ReasonCode::PermissionDenied),
        50 => Observed::missing(
            Availability::Unsupported,
            Source::Win32,
            ReasonCode::NotSupported,
        )
        .expect("Unsupported is a missing state"),
        13 | 87 => Observed::unavailable(Source::Win32, ReasonCode::InvalidData),
        8 | 14 | 122 | 170 | 1167 | 1237 => {
            Observed::unavailable(Source::Win32, ReasonCode::TemporarilyUnavailable)
        }
        1460 => Observed::unavailable(Source::Win32, ReasonCode::Timeout),
        _ => Observed::unavailable(Source::Win32, ReasonCode::Unknown),
    }
}
fn name(raw: Name, at: Timestamp) -> Observed<String> {
    if !raw.from_edid {
        return Observed::unavailable(Source::Win32, ReasonCode::NotPresent);
    }
    let value = raw
        .text
        .iter()
        .position(|c| *c == 0)
        .and_then(|end| String::from_utf16(&raw.text[..end]).ok())
        .filter(|s| !s.trim().is_empty() && !s.chars().any(char::is_control));
    match value {
        Some(value) => Observed::available(value, Source::Win32, at),
        None => failure(INVALID),
    }
}
fn dimensions(path: &Path, modes: &[Mode], at: Timestamp) -> (Observed<u32>, Observed<u32>) {
    let index = if path.virtual_mode {
        path.index >> 16
    } else {
        path.index
    };
    let absent = if path.virtual_mode {
        u16::MAX as u32
    } else {
        u32::MAX
    };
    if index == absent {
        return (
            Observed::unavailable(Source::Win32, ReasonCode::NotPresent),
            Observed::unavailable(Source::Win32, ReasonCode::NotPresent),
        );
    }
    let size = modes
        .get(index as usize)
        .filter(|mode| mode.key == path.key)
        .and_then(|mode| mode.size);
    match size {
        Some((width, height)) if width > 0 && height > 0 => (
            Observed::available(width, Source::Win32, at),
            Observed::available(height, Source::Win32, at),
        ),
        _ => (failure(INVALID), failure(INVALID)),
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
        let sizes = api.sizes();
        check()?;
        let (paths, modes) = match sizes {
            Ok(sizes) => sizes,
            Err(code) => return Ok(failure(code)),
        };
        if paths > MAX_PATHS || modes > MAX_MODES {
            return Ok(failure(INVALID));
        }
        let (paths, modes) = (paths.max(1), modes.max(1));
        check()?;
        let frame = api.query(paths, modes);
        check()?;
        let frame = match frame {
            Err(BUFFER) => continue,
            Err(code) => return Ok(failure(code)),
            Ok(frame) => frame,
        };
        if frame.paths.len() > paths
            || frame.modes.len() > modes
            || frame.paths.len() > options.max_entries
        {
            return Ok(failure(INVALID));
        }
        let mut seen = BTreeSet::new();
        if frame
            .paths
            .iter()
            .any(|path| !path.active || !seen.insert(path.key))
        {
            return Ok(failure(INVALID));
        }
        let mut entries = Vec::with_capacity(frame.paths.len());
        for path in &frame.paths {
            check()?;
            let at = Timestamp::now()?;
            let (width_pixels, height_pixels) = dimensions(path, &frame.modes, at);
            let raw = api.name(path.key);
            check()?;
            let mut entry = DisplayInfo::default();
            entry.name = match raw {
                Ok(raw) => name(raw, at),
                Err(code) => failure(code),
            };
            entry.width_pixels = width_pixels;
            entry.height_pixels = height_pixels;
            entries.push(entry);
        }
        check()?;
        return Ok(Observed::available(
            entries,
            Source::Win32,
            Timestamp::now()?,
        ));
    }
    Ok(failure(BUFFER))
}

#[cfg(target_os = "windows")]
mod native {
    use super::*;
    use windows_sys::Win32::{Devices::Display::*, Foundation::LUID};
    struct Reader;
    fn key(adapter: LUID, id: u32) -> Key {
        Key(adapter.LowPart, adapter.HighPart, id)
    }
    impl Api for Reader {
        fn sizes(&mut self) -> Result<(usize, usize), u32> {
            let (mut paths, mut modes) = (0, 0);
            // SAFETY: two live aligned writable u32 outputs; fixed read-only query flags.
            let status = unsafe {
                GetDisplayConfigBufferSizes(
                    QDC_ONLY_ACTIVE_PATHS | QDC_VIRTUAL_MODE_AWARE,
                    &mut paths,
                    &mut modes,
                )
            };
            if status == 0 {
                Ok((paths as usize, modes as usize))
            } else {
                Err(status)
            }
        }
        fn query(&mut self, paths: usize, modes: usize) -> Result<Frame, u32> {
            // Caller validates capacities; keep this boundary independently bounded too.
            if !(1..=MAX_PATHS).contains(&paths) || !(1..=MAX_MODES).contains(&modes) {
                return Err(INVALID);
            }
            let mut native_paths = vec![DISPLAYCONFIG_PATH_INFO::default(); paths];
            let mut native_modes = vec![DISPLAYCONFIG_MODE_INFO::default(); modes];
            let (mut p, mut m) = (paths as u32, modes as u32);
            // SAFETY: initialized arrays match supplied capacities and remain live and
            // uniquely writable; counts are aligned u32s. Non-database query needs NULL
            // topology. Success counts are checked before indexing/truncation below.
            let status = unsafe {
                QueryDisplayConfig(
                    QDC_ONLY_ACTIVE_PATHS | QDC_VIRTUAL_MODE_AWARE,
                    &mut p,
                    native_paths.as_mut_ptr(),
                    &mut m,
                    native_modes.as_mut_ptr(),
                    std::ptr::null_mut(),
                )
            };
            if status != 0 {
                return Err(status);
            }
            if p as usize > paths || m as usize > modes {
                return Err(INVALID);
            }
            native_paths.truncate(p as usize);
            native_modes.truncate(m as usize);
            let paths = native_paths
                .into_iter()
                .map(|p| Path {
                    key: key(p.targetInfo.adapterId, p.targetInfo.id),
                    active: p.flags & 1 != 0, // DISPLAYCONFIG_PATH_ACTIVE
                    virtual_mode: p.flags & 8 != 0, // DISPLAYCONFIG_PATH_SUPPORT_VIRTUAL_MODE
                    // SAFETY: the initialized SDK union is a u32 or two packed 16-bit
                    // indices. Reading its u32 representation is valid for either case.
                    index: unsafe { p.targetInfo.Anonymous.modeInfoIdx },
                })
                .collect();
            let modes = native_modes
                .into_iter()
                .map(|m| Mode {
                    key: key(m.adapterId, m.id),
                    size: if m.infoType == DISPLAYCONFIG_MODE_INFO_TYPE_TARGET {
                        // SAFETY: API returned an initialized mode tagged TARGET; only
                        // this tag selects targetMode. All members read here are integers.
                        let signal = unsafe { m.Anonymous.targetMode.targetVideoSignalInfo };
                        Some((signal.activeSize.cx, signal.activeSize.cy))
                    } else {
                        None
                    },
                })
                .collect();
            Ok(Frame { paths, modes })
        }
        fn name(&mut self, key: Key) -> Result<Name, u32> {
            let mut packet = DISPLAYCONFIG_TARGET_DEVICE_NAME::default();
            packet.header.r#type = DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME;
            packet.header.size = std::mem::size_of_val(&packet) as u32;
            packet.header.adapterId = LUID {
                LowPart: key.0,
                HighPart: key.1,
            };
            packet.header.id = key.2;
            // SAFETY: header is the first field of the initialized repr(C) request;
            // type and size identify the full live writable target-name packet.
            let status = unsafe { DisplayConfigGetDeviceInfo(&mut packet.header) };
            if status != 0 {
                return Err(status as u32);
            }
            Ok(Name {
                // SAFETY: the initialized flags union contains a u32 bit representation.
                from_edid: unsafe { packet.flags.Anonymous.value } & 1 != 0,
                text: packet.monitorFriendlyDeviceName,
            })
        }
    }
    pub(crate) fn collect(
        context: &CollectContext,
    ) -> Result<Observed<Vec<DisplayInfo>>, ScopeError> {
        collect_with(&mut Reader, &context.options, || context.check())
    }
}
#[cfg(target_os = "windows")]
pub(super) use native::collect;

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        collections::VecDeque,
        sync::{
            Arc,
            atomic::{AtomicUsize, Ordering},
        },
    };
    const KEY: Key = Key(2, -3, 4);
    fn path(index: u32) -> Path {
        Path {
            key: KEY,
            active: true,
            virtual_mode: false,
            index,
        }
    }
    fn raw(text: &str) -> Name {
        let mut name = Name {
            from_edid: true,
            text: [0; 64],
        };
        for (a, b) in name.text.iter_mut().zip(text.encode_utf16()) {
            *a = b;
        }
        name
    }
    fn frame() -> Frame {
        Frame {
            paths: vec![path(0)],
            modes: vec![Mode {
                key: KEY,
                size: Some((1920, 1080)),
            }],
        }
    }
    struct Fake {
        sizes: Result<(usize, usize), u32>,
        frames: VecDeque<Result<Frame, u32>>,
        queries: usize,
        names: usize,
        name_error: Option<u32>,
    }
    impl Fake {
        fn new(frame: Frame) -> Self {
            Self {
                sizes: Ok((1, 1)),
                frames: VecDeque::from([Ok(frame)]),
                queries: 0,
                names: 0,
                name_error: None,
            }
        }
    }
    impl Api for Fake {
        fn sizes(&mut self) -> Result<(usize, usize), u32> {
            self.sizes
        }
        fn query(&mut self, paths: usize, modes: usize) -> Result<Frame, u32> {
            assert!((1..=MAX_PATHS).contains(&paths) && (1..=MAX_MODES).contains(&modes));
            self.queries += 1;
            self.frames.pop_front().expect("fixture query")
        }
        fn name(&mut self, _: Key) -> Result<Name, u32> {
            self.names += 1;
            self.name_error
                .map_or_else(|| Ok(raw("Unit panel 🌟")), Err)
        }
    }
    #[test]
    fn names_are_strict_and_absence_is_not_a_fake_monitor() {
        assert_eq!(
            name(raw("Unit 🌟"), Timestamp(1)).value().unwrap(),
            "Unit 🌟"
        );
        for text in ["", " ", "x\nx"] {
            assert_eq!(
                name(raw(text), Timestamp(1)).reason(),
                Some(ReasonCode::InvalidData)
            );
        }
        for text in [[65; 64], {
            let mut a = [0; 64];
            a[0] = 0xd800;
            a
        }] {
            assert!(
                name(
                    Name {
                        from_edid: true,
                        text
                    },
                    Timestamp(1)
                )
                .value()
                .is_none()
            );
        }
        let mut n = raw("Not used");
        n.from_edid = false;
        assert_eq!(name(n, Timestamp(1)).reason(), Some(ReasonCode::NotPresent));
    }
    #[test]
    fn dimensions_validate_virtual_indices_types_keys_and_positive_pairs() {
        let modes = frame().modes;
        let mut p = path(0);
        let (w, h) = dimensions(&p, &modes, Timestamp(7));
        assert_eq!((w.value(), h.value()), (Some(&1920), Some(&1080)));
        p.virtual_mode = true;
        p.index = 0x0000ffff;
        assert!(dimensions(&p, &modes, Timestamp(7)).0.value().is_some());
        p.index = 0xffff0000;
        assert_eq!(
            dimensions(&p, &modes, Timestamp(7)).0.reason(),
            Some(ReasonCode::NotPresent)
        );
        p.virtual_mode = false;
        p.index = u32::MAX;
        assert_eq!(
            dimensions(&p, &modes, Timestamp(7)).0.reason(),
            Some(ReasonCode::NotPresent)
        );
        p.index = 1;
        assert_eq!(
            dimensions(&p, &modes, Timestamp(7)).0.reason(),
            Some(ReasonCode::InvalidData)
        );
        p.index = 0;
        for mode in [
            Mode {
                key: KEY,
                size: None,
            },
            Mode {
                key: Key(0, 0, 0),
                size: Some((1, 1)),
            },
            Mode {
                key: KEY,
                size: Some((0, 1)),
            },
            Mode {
                key: KEY,
                size: Some((1, 0)),
            },
        ] {
            let (w, h) = dimensions(&p, &[mode], Timestamp(7));
            assert_eq!(w.reason(), Some(ReasonCode::InvalidData));
            assert!(h.value().is_none());
        }
    }
    #[test]
    fn direct_error_codes_do_not_become_successful_empty_lists() {
        for (code, state, reason) in [
            (5, Availability::Restricted, ReasonCode::PermissionDenied),
            (50, Availability::Unsupported, ReasonCode::NotSupported),
            (13, Availability::Unavailable, ReasonCode::InvalidData),
            (1460, Availability::Unavailable, ReasonCode::Timeout),
            (31, Availability::Unavailable, ReasonCode::Unknown),
        ] {
            let mut api = Fake::new(frame());
            api.sizes = Err(code);
            let observed = collect_with(&mut api, &Options::default(), || Ok(())).unwrap();
            assert_eq!(
                (observed.availability(), observed.reason()),
                (state, Some(reason))
            );
            assert!(observed.value().is_none() && observed.observed_at().is_none());
            assert_eq!(api.queries, 0);
        }
    }
    #[test]
    fn buffer_races_retry_three_times_then_fail_without_prefix() {
        let mut api = Fake::new(frame());
        api.frames = VecDeque::from([Err(BUFFER), Err(BUFFER), Ok(frame())]);
        assert_eq!(
            collect_with(&mut api, &Options::default(), || Ok(()))
                .unwrap()
                .value()
                .unwrap()
                .len(),
            1
        );
        assert_eq!(api.queries, 3);
        api.frames = VecDeque::from([Err(BUFFER), Err(BUFFER), Err(BUFFER)]);
        api.queries = 0;
        let result = collect_with(&mut api, &Options::default(), || Ok(())).unwrap();
        assert_eq!(result.reason(), Some(ReasonCode::TemporarilyUnavailable));
        assert_eq!(api.queries, 3);
    }
    #[test]
    fn estimates_and_returned_counts_are_bounded_before_projection() {
        for sizes in [
            (MAX_PATHS + 1, 1),
            (1, MAX_MODES + 1),
            (usize::MAX, usize::MAX),
        ] {
            let mut api = Fake::new(frame());
            api.sizes = Ok(sizes);
            assert_eq!(
                collect_with(&mut api, &Options::default(), || Ok(()))
                    .unwrap()
                    .reason(),
                Some(ReasonCode::InvalidData)
            );
            assert_eq!(api.queries, 0);
        }
        let mut f = frame();
        f.paths.push(path(0));
        let mut api = Fake::new(f);
        assert!(
            collect_with(&mut api, &Options::default(), || Ok(()))
                .unwrap()
                .value()
                .is_none()
        );
        assert_eq!(api.names, 0);
        let mut f = frame();
        f.modes.push(Mode {
            key: KEY,
            size: None,
        });
        let mut api = Fake::new(f);
        assert!(
            collect_with(&mut api, &Options::default(), || Ok(()))
                .unwrap()
                .value()
                .is_none()
        );
    }
    #[test]
    fn duplicate_targets_inactive_paths_and_output_limits_are_not_prefix_success() {
        for variant in 0..3 {
            let mut f = frame();
            f.paths.push(path(0));
            if variant == 1 {
                f.paths.pop();
                f.paths[0].active = false;
            }
            if variant == 2 {
                f.paths[1].key = Key(1, 1, 1);
            }
            let mut api = Fake::new(f);
            api.sizes = Ok((2, 1));
            let options = Options {
                max_entries: if variant == 2 { 1 } else { 2 },
                ..Options::default()
            };
            assert_eq!(
                collect_with(&mut api, &options, || Ok(()))
                    .unwrap()
                    .reason(),
                Some(ReasonCode::InvalidData)
            );
            assert_eq!(api.names, 0);
        }
    }
    #[test]
    fn zero_estimates_still_query_and_empty_success_has_metadata() {
        let mut api = Fake::new(Frame {
            paths: vec![],
            modes: vec![],
        });
        api.sizes = Ok((0, 0));
        let result = collect_with(&mut api, &Options::default(), || Ok(())).unwrap();
        assert_eq!(api.queries, 1);
        assert!(result.value().unwrap().is_empty());
        assert!(result.observed_at().is_some());
    }
    #[test]
    fn name_failure_and_bad_modes_are_isolated() {
        let mut api = Fake::new(frame());
        api.name_error = Some(5);
        let result = collect_with(&mut api, &Options::default(), || Ok(())).unwrap();
        let entry = &result.value().unwrap()[0];
        assert_eq!(entry.name.availability(), Availability::Restricted);
        assert_eq!(entry.width_pixels.value(), Some(&1920));
        let mut f = frame();
        f.paths[0].index = 99;
        let mut api = Fake::new(f);
        let result = collect_with(&mut api, &Options::default(), || Ok(())).unwrap();
        let entry = &result.value().unwrap()[0];
        assert!(entry.name.value().is_some());
        assert!(entry.width_pixels.value().is_none());
    }
    #[test]
    fn cancellation_and_deadlines_stop_before_further_calls() {
        let mut api = Fake::new(frame());
        let mut calls = 0;
        let error = collect_with(&mut api, &Options::default(), || {
            calls += 1;
            if calls == 4 {
                Err(ScopeError::new(ErrorCode::Cancelled))
            } else {
                Ok(())
            }
        })
        .unwrap_err();
        assert_eq!(error.code, ErrorCode::Cancelled);
        assert_eq!(api.names, 0);
        let error = collect_with(&mut api, &Options::default(), || {
            Err(ScopeError::new(ErrorCode::Timeout))
        })
        .unwrap_err();
        assert_eq!(error.code, ErrorCode::Timeout);
    }
    #[test]
    fn static_success_empty_and_failure_stay_cached_until_new_hardware() {
        struct BackendFixture(Arc<AtomicUsize>);
        impl Backend for BackendFixture {
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
                let state = self.0.load(Ordering::SeqCst);
                let mut api = Fake::new(if state == 0 {
                    Frame {
                        paths: vec![],
                        modes: vec![],
                    }
                } else {
                    frame()
                });
                if state == 2 {
                    api.sizes = Err(5);
                }
                let mut s = StaticSnapshot::default();
                s.displays = collect_with(&mut api, &ctx.options, || ctx.check())?;
                Ok(s)
            }
            fn refresh_dynamic(
                &mut self,
                ctx: &CollectContext,
            ) -> Result<DynamicSnapshot, ScopeError> {
                ctx.check()?;
                Ok(DynamicSnapshot::default())
            }
        }
        for initial in 0..3 {
            let state = Arc::new(AtomicUsize::new(initial));
            let create = || {
                HardwareBuilder::default()
                    .with_backend(100, BackendFixture(state.clone()))
                    .build()
                    .unwrap()
            };
            let hardware = create();
            let first = hardware.collect().unwrap().static_info.displays;
            state.store(1, Ordering::SeqCst);
            hardware.refresh_dynamic().unwrap();
            assert_eq!(hardware.collect().unwrap().static_info.displays, first);
            assert_eq!(
                create()
                    .collect()
                    .unwrap()
                    .static_info
                    .displays
                    .value()
                    .unwrap()
                    .len(),
                1
            );
        }
    }
}
