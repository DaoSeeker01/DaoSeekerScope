//! Connected DRM view; default collection never opens raw EDID.
use daoseeker_scope_core::*;
use std::{
    collections::BTreeSet,
    io::{self, Read},
    path::Path,
};

#[derive(Clone, Copy)]
struct Fault(Availability, ReasonCode);
const INVALID: Fault = Fault(Availability::Unavailable, ReasonCode::InvalidData);
const TEMP: Fault = Fault(
    Availability::Unavailable,
    ReasonCode::TemporarilyUnavailable,
);
impl Fault {
    fn observed<T>(self, source: Source) -> Observed<T> {
        Observed::missing(self.0, source, self.1).expect("fault is a missing state")
    }
}
fn fault(kind: io::ErrorKind) -> Fault {
    match kind {
        io::ErrorKind::PermissionDenied => {
            Fault(Availability::Restricted, ReasonCode::PermissionDenied)
        }
        io::ErrorKind::NotFound => Fault(Availability::Unavailable, ReasonCode::NotPresent),
        io::ErrorKind::TimedOut => Fault(Availability::Unavailable, ReasonCode::Timeout),
        io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted => TEMP,
        _ => Fault(Availability::Unavailable, ReasonCode::Unknown),
    }
}
fn unsupported<T>() -> Observed<T> {
    Fault(Availability::Unsupported, ReasonCode::NotSupported).observed(Source::Drm)
}
pub(crate) fn edid_name(data: &[u8], at: Timestamp) -> Observed<String> {
    if data.is_empty() {
        return Fault(Availability::Unavailable, ReasonCode::NotPresent).observed(Source::Sysfs);
    }
    if data.len() != 128
        || data[..8] != [0, 255, 255, 255, 255, 255, 255, 0]
        || data.iter().fold(0u8, |a, b| a.wrapping_add(*b)) != 0
    {
        return INVALID.observed(Source::Sysfs);
    }
    if data[18] != 1 || !matches!(data[19], 3 | 4) {
        return Fault(Availability::Unsupported, ReasonCode::NotSupported).observed(Source::Sysfs);
    }
    let mut result: Option<String> = None;
    for block in data[54..126].chunks_exact(18) {
        // Independent format projection: zero pixel-clock descriptor, tag 0xfc.
        if block[0] != 0 || block[1] != 0 || block[3] != 0xfc {
            continue;
        }
        if block[2] != 0 || block[4] != 0 {
            return INVALID.observed(Source::Sysfs);
        }
        let payload = &block[5..18];
        let end = payload
            .iter()
            .position(|b| *b == b'\n')
            .unwrap_or(payload.len());
        if payload[..end].iter().any(|b| !(32..=126).contains(b))
            || payload[end.saturating_add(1).min(payload.len())..]
                .iter()
                .any(|b| *b != b' ')
        {
            return INVALID.observed(Source::Sysfs);
        }
        let Ok(name) = std::str::from_utf8(&payload[..end]) else {
            return INVALID.observed(Source::Sysfs);
        };
        let name = name.trim_ascii();
        if name.is_empty()
            || ["unknown", "none", "n/a", "not specified"]
                .contains(&name.to_ascii_lowercase().as_str())
            || result.as_deref().is_some_and(|old| old != name)
        {
            return INVALID.observed(Source::Sysfs);
        }
        result = Some(name.to_owned());
    }
    match result {
        Some(name) => Observed::available(name, Source::Sysfs, at),
        None => Fault(Availability::Unavailable, ReasonCode::NotPresent).observed(Source::Sysfs),
    }
}
fn connector(name: &str) -> bool {
    if name.len() > 128 {
        return false;
    }
    let Some((card, tail)) = name.split_once('-') else {
        return false;
    };
    let valid_card = card
        .strip_prefix("card")
        .and_then(|n| n.parse::<u32>().ok().map(|v| v.to_string() == n))
        .unwrap_or(false);
    valid_card
        && !tail.is_empty()
        && tail.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-')
        && tail.as_bytes().last().is_some_and(u8::is_ascii_digit)
}
fn status(bytes: &[u8]) -> Result<bool, Fault> {
    match bytes {
        b"connected" | b"connected\n" => Ok(true),
        b"disconnected" | b"disconnected\n" => Ok(false),
        b"unknown" | b"unknown\n" => Err(TEMP),
        _ => Err(INVALID),
    }
}
fn read(
    path: &Path,
    limit: usize,
    check: &mut impl FnMut() -> Result<(), ScopeError>,
) -> Result<Result<Vec<u8>, Fault>, ScopeError> {
    check()?;
    let meta = std::fs::symlink_metadata(path);
    check()?;
    match meta {
        Err(e) => return Ok(Err(fault(e.kind()))),
        Ok(m) if !m.is_file() => return Ok(Err(INVALID)),
        Ok(_) => {}
    }
    let input = std::fs::File::open(path);
    check()?;
    let input = match input {
        Ok(f) => f,
        Err(e) => return Ok(Err(fault(e.kind()))),
    };
    let mut bytes = Vec::with_capacity(limit);
    let result = input.take(limit as u64).read_to_end(&mut bytes);
    check()?;
    Ok(result.map(|_| bytes).map_err(|e| fault(e.kind())))
}
fn connected(
    path: &Path,
    check: &mut impl FnMut() -> Result<(), ScopeError>,
) -> Result<Result<bool, Fault>, ScopeError> {
    Ok(match read(&path.join("status"), 33, check)? {
        Ok(bytes) => status(&bytes),
        // A connector was enumerated, so a disappearing status is a topology race.
        Err(Fault(_, ReasonCode::NotPresent)) => Err(TEMP),
        Err(f) => Err(f),
    })
}
fn confirm(state: Result<bool, Fault>) -> Result<(), Fault> {
    match state {
        Ok(true) => Ok(()),
        Ok(false) => Err(TEMP),
        Err(fault) => Err(fault),
    }
}
pub(crate) fn collect(
    root: &Path,
    ctx: &CollectContext,
) -> Result<Observed<Vec<DisplayInfo>>, ScopeError> {
    collect_with(root, &ctx.options, || ctx.check())
}
fn collect_with(
    root: &Path,
    options: &Options,
    mut check: impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<Vec<DisplayInfo>>, ScopeError> {
    options.validate()?;
    check()?;
    let directory = std::fs::read_dir(root);
    check()?;
    let mut directory = match directory {
        Ok(d) => d,
        Err(e) => return Ok(fault(e.kind()).observed(Source::Drm)),
    };
    let mut candidates = BTreeSet::new();
    let mut scanned = 0;
    let mut matched = 0;
    loop {
        check()?;
        let next = directory.next();
        check()?;
        let entry = match next {
            None => break,
            Some(Ok(e)) => e,
            Some(Err(e)) => return Ok(fault(e.kind()).observed(Source::Drm)),
        };
        if scanned == 4096 {
            return Ok(INVALID.observed(Source::Drm));
        }
        scanned += 1;
        let name = entry.file_name();
        let Some(name) = name.to_str() else {
            return Ok(INVALID.observed(Source::Drm));
        };
        if !connector(name) {
            continue;
        }
        if matched == 1024 {
            return Ok(INVALID.observed(Source::Drm));
        }
        matched += 1;
        let target = std::fs::canonicalize(entry.path());
        check()?;
        let target = match target {
            Ok(p) => p,
            Err(e) => return Ok(fault(e.kind()).observed(Source::Drm)),
        };
        let meta = std::fs::metadata(&target);
        check()?;
        match meta {
            Ok(m) if m.is_dir() => {}
            Ok(_) => return Ok(INVALID.observed(Source::Drm)),
            Err(e) => return Ok(fault(e.kind()).observed(Source::Drm)),
        }
        candidates.insert(target);
    }
    let mut entries = Vec::new();
    for path in candidates {
        let attached = connected(&path, &mut check)?;
        match attached {
            Ok(false) => continue,
            Err(f) => return Ok(f.observed(Source::Drm)),
            Ok(true) => {}
        }
        if entries.len() == options.max_entries {
            return Ok(INVALID.observed(Source::Drm));
        }
        let name = if options.privacy.permits_sensitive() {
            match read(&path.join("edid"), 128, &mut check)? {
                Ok(data) => edid_name(&data, Timestamp::now()?),
                Err(f) => f.observed(Source::Sysfs),
            }
        } else {
            Observed::restricted(Source::Sysfs, ReasonCode::PrivacyRedacted)
        };
        if let Err(f) = confirm(connected(&path, &mut check)?) {
            return Ok(f.observed(Source::Drm));
        }
        let mut display = DisplayInfo::default();
        display.name = name;
        display.width_pixels = unsupported();
        display.height_pixels = unsupported();
        entries.push(display);
    }
    check()?;
    Ok(Observed::available(entries, Source::Drm, Timestamp::now()?))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        path::PathBuf,
        sync::atomic::{AtomicUsize, Ordering},
    };
    static NEXT: AtomicUsize = AtomicUsize::new(0);
    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let p = std::env::temp_dir().join(format!(
                "dscope-display-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::SeqCst)
            ));
            std::fs::create_dir(&p).unwrap();
            Self(p)
        }
        fn add(&self, name: &str, state: &[u8]) -> PathBuf {
            let p = self.0.join(name);
            std::fs::create_dir(&p).unwrap();
            std::fs::write(p.join("status"), state).unwrap();
            p
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            std::fs::remove_dir_all(&self.0).unwrap();
        }
    }
    fn edid(name: &[u8]) -> [u8; 128] {
        let mut b = [0u8; 128];
        b[..8].copy_from_slice(&[0, 255, 255, 255, 255, 255, 255, 0]);
        b[18] = 1;
        b[19] = 4;
        b[57] = 0xfc;
        b[59..72].fill(b' ');
        b[59..59 + name.len()].copy_from_slice(name);
        checksum(&mut b);
        b
    }
    fn checksum(b: &mut [u8; 128]) {
        b[127] = 0;
        b[127] = 0u8.wrapping_sub(b.iter().fold(0u8, |a, b| a.wrapping_add(*b)));
    }
    fn options() -> Options {
        Options {
            privacy: PrivacyOptions {
                include_sensitive: true,
                caller_authorized: true,
            },
            ..Options::default()
        }
    }
    #[test]
    fn edid_only_projects_name_and_rejects_corrupt_or_ambiguous_blocks() {
        let mut bytes = edid(b"Unit panel\n");
        bytes[12..16].copy_from_slice(&[1, 2, 3, 4]);
        bytes[75] = 0xff;
        bytes[77..90].copy_from_slice(b"Secret-serial");
        checksum(&mut bytes);
        assert_eq!(
            edid_name(&bytes, Timestamp(1)).value().map(String::as_str),
            Some("Unit panel")
        );
        let mut bad = bytes;
        bad[12] ^= 1;
        assert_eq!(
            edid_name(&bad, Timestamp(1)).reason(),
            Some(ReasonCode::InvalidData)
        );
        let mut bad = bytes;
        bad[18] = 2;
        checksum(&mut bad);
        assert_eq!(
            edid_name(&bad, Timestamp(1)).availability(),
            Availability::Unsupported
        );
        let mut bad = bytes;
        bad[75] = 0xfc;
        checksum(&mut bad);
        assert_eq!(
            edid_name(&bad, Timestamp(1)).reason(),
            Some(ReasonCode::InvalidData)
        );
        for payload in [b"".as_slice(), b"None", b"X\0Y", b"X\tY", b"X\nY", b"\xff"] {
            assert!(edid_name(&edid(payload), Timestamp(1)).value().is_none());
        }
        assert_eq!(
            edid_name(&[], Timestamp(1)).reason(),
            Some(ReasonCode::NotPresent)
        );
        assert!(edid_name(&bytes[..127], Timestamp(1)).value().is_none());
        assert!(edid_name(&[0; 129], Timestamp(1)).value().is_none());
    }
    #[test]
    fn status_is_strict_and_modes_are_never_resolution() {
        assert_eq!(status(b"connected\n").ok(), Some(true));
        assert_eq!(status(b"disconnected").ok(), Some(false));
        assert_eq!(
            status(b"unknown\n").err().unwrap().1,
            ReasonCode::TemporarilyUnavailable
        );
        for bytes in [
            b"".as_slice(),
            b"CONNECTED",
            b"connected extra",
            b"connected\0",
            b" \n",
            &[b'x'; 33],
        ] {
            assert_eq!(status(bytes).err().unwrap().1, ReasonCode::InvalidData);
        }
        let f = Fixture::new();
        let p = f.add("card0-HDMI-A-1", b"connected\n");
        std::fs::write(p.join("modes"), b"8192x8192\n").unwrap();
        let result = collect_with(&f.0, &Options::default(), || Ok(())).unwrap();
        let entry = &result.value().unwrap()[0];
        assert_eq!(entry.width_pixels.availability(), Availability::Unsupported);
        assert_eq!(entry.name.reason(), Some(ReasonCode::PrivacyRedacted));
    }
    #[test]
    fn default_never_inspects_edid_and_authorized_names_fail_independently() {
        let f = Fixture::new();
        let p = f.add("card0-eDP-1", b"connected\n");
        std::fs::create_dir(p.join("edid")).unwrap();
        let result = collect_with(&f.0, &Options::default(), || Ok(())).unwrap();
        assert_eq!(
            result.value().unwrap()[0].name.reason(),
            Some(ReasonCode::PrivacyRedacted)
        );
        let result = collect_with(&f.0, &options(), || Ok(())).unwrap();
        assert_eq!(
            result.value().unwrap()[0].name.reason(),
            Some(ReasonCode::InvalidData)
        );
        std::fs::remove_dir(p.join("edid")).unwrap();
        std::fs::write(p.join("edid"), edid(b"Synthetic\n")).unwrap();
        let result = collect_with(&f.0, &options(), || Ok(())).unwrap();
        assert_eq!(
            result.value().unwrap()[0].name.value().map(String::as_str),
            Some("Synthetic")
        );
        let invalid = Options {
            privacy: PrivacyOptions {
                include_sensitive: true,
                caller_authorized: false,
            },
            ..Options::default()
        };
        assert_eq!(
            collect_with(&f.0, &invalid, || Ok(())).unwrap_err().code,
            ErrorCode::InvalidArgument
        );
    }
    #[test]
    fn unknown_or_failed_status_refuses_collection_prefix() {
        let f = Fixture::new();
        f.add("card0-DP-1", b"connected");
        let p = f.add("card0-DP-2", b"unknown");
        assert_eq!(
            collect_with(&f.0, &Options::default(), || Ok(()))
                .unwrap()
                .reason(),
            Some(ReasonCode::TemporarilyUnavailable)
        );
        std::fs::remove_file(p.join("status")).unwrap();
        assert!(
            collect_with(&f.0, &Options::default(), || Ok(()))
                .unwrap()
                .value()
                .is_none()
        );
        std::fs::create_dir(p.join("status")).unwrap();
        assert_eq!(
            collect_with(&f.0, &Options::default(), || Ok(()))
                .unwrap()
                .reason(),
            Some(ReasonCode::InvalidData)
        );
    }
    #[test]
    fn connected_only_bounds_and_empty_are_real_enumeration_results() {
        let f = Fixture::new();
        f.add("card0-HDMI-A-1", b"disconnected");
        std::fs::write(f.0.join("version"), b"ignored").unwrap();
        assert!(
            collect_with(&f.0, &Options::default(), || Ok(()))
                .unwrap()
                .value()
                .unwrap()
                .is_empty()
        );
        f.add("card0-DP-1", b"connected");
        f.add("card0-DP-2", b"connected");
        let opts = Options {
            max_entries: 1,
            ..Options::default()
        };
        assert_eq!(
            collect_with(&f.0, &opts, || Ok(())).unwrap().reason(),
            Some(ReasonCode::InvalidData)
        );
        for good in ["card0-DP-1", "card123-HDMI-A-1", "card1-DP-1-2"] {
            assert!(connector(good));
        }
        for bad in [
            "card0",
            "renderD128",
            "card00-DP-1",
            "card0-/secret1",
            "card0-DP-x",
        ] {
            assert!(!connector(bad));
        }
    }
    #[test]
    fn scanning_is_bounded_and_cancellation_precedes_reads() {
        let f = Fixture::new();
        for i in 0..4097 {
            std::fs::write(f.0.join(format!("ignored{i}")), b"").unwrap();
        }
        assert_eq!(
            collect_with(&f.0, &Options::default(), || Ok(()))
                .unwrap()
                .reason(),
            Some(ReasonCode::InvalidData)
        );
        assert_eq!(
            collect_with(&f.0, &Options::default(), || Err(ScopeError::new(
                ErrorCode::Cancelled
            )))
            .unwrap_err()
            .code,
            ErrorCode::Cancelled
        );
        assert_eq!(
            collect_with(&f.0, &Options::default(), || Err(ScopeError::new(
                ErrorCode::Timeout
            )))
            .unwrap_err()
            .code,
            ErrorCode::Timeout
        );
        let candidates = Fixture::new();
        for i in 0..1025 {
            candidates.add(&format!("card0-DP-{i}"), b"disconnected\n");
        }
        // Even disconnected candidates are bounded before status reads.
        assert_eq!(
            collect_with(&candidates.0, &Options::default(), || Ok(()))
                .unwrap()
                .reason(),
            Some(ReasonCode::InvalidData)
        );
    }
    #[test]
    fn confirmation_reads_fresh_status_and_preserves_errors() {
        let f = Fixture::new();
        let p = f.add("card0-DP-1", b"connected");
        assert!(confirm(connected(&p, &mut || Ok(())).unwrap()).is_ok());
        std::fs::write(p.join("status"), b"disconnected").unwrap();
        assert_eq!(
            confirm(connected(&p, &mut || Ok(())).unwrap())
                .err()
                .unwrap()
                .1,
            ReasonCode::TemporarilyUnavailable
        );
        std::fs::remove_file(p.join("status")).unwrap();
        assert!(confirm(connected(&p, &mut || Ok(())).unwrap()).is_err());
    }
    #[test]
    fn static_success_empty_and_failure_are_cached_until_new_hardware() {
        struct Reader(std::path::PathBuf);
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
                let mut result = StaticSnapshot::default();
                result.displays = collect(&self.0, ctx)?;
                Ok(result)
            }
            fn refresh_dynamic(
                &mut self,
                ctx: &CollectContext,
            ) -> Result<DynamicSnapshot, ScopeError> {
                ctx.check()?;
                Ok(DynamicSnapshot::default())
            }
        }
        for initial in [b"connected".as_slice(), b"disconnected", b"unknown"] {
            let f = Fixture::new();
            let p = f.add("card0-DP-1", initial);
            let create = || {
                HardwareBuilder::default()
                    .with_backend(100, Reader(f.0.clone()))
                    .build()
                    .unwrap()
            };
            let h = create();
            let first = h.collect().unwrap().static_info.displays;
            std::fs::write(p.join("status"), b"connected").unwrap();
            h.refresh_dynamic().unwrap();
            assert_eq!(h.collect().unwrap().static_info.displays, first);
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
