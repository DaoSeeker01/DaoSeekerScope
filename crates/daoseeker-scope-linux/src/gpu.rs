//! DRM device view and driver product names; no inferred VRAM or exported IDs.
use daoseeker_scope_core::*;
use std::{
    collections::BTreeSet,
    io::{self, Read},
    path::Path,
};

const MAX_NAME: usize = 4096;
const MAX_SCANNED: usize = 4096;
fn invalid<T>(source: Source) -> Observed<T> {
    Observed::unavailable(source, ReasonCode::InvalidData)
}
fn unsupported<T>() -> Observed<T> {
    Observed::missing(
        Availability::Unsupported,
        Source::Drm,
        ReasonCode::NotSupported,
    )
    .expect("Unsupported is a missing state")
}
fn failure<T>(error: io::ErrorKind, source: Source) -> Observed<T> {
    match error {
        io::ErrorKind::PermissionDenied => {
            Observed::restricted(source, ReasonCode::PermissionDenied)
        }
        io::ErrorKind::NotFound => Observed::unavailable(source, ReasonCode::NotPresent),
        io::ErrorKind::TimedOut => Observed::unavailable(source, ReasonCode::Timeout),
        io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted => {
            Observed::unavailable(source, ReasonCode::TemporarilyUnavailable)
        }
        _ => Observed::unavailable(source, ReasonCode::Unknown),
    }
}
pub(crate) fn product_name(bytes: &[u8], source: Source, at: Timestamp) -> Observed<String> {
    if bytes.len() > MAX_NAME {
        return invalid(source);
    }
    let parsed = std::str::from_utf8(bytes)
        .ok()
        .map(str::trim_ascii)
        .filter(|name| {
            !name.is_empty()
                && !name.chars().any(char::is_control)
                && !["unknown", "none", "n/a", "not specified"]
                    .contains(&name.to_ascii_lowercase().as_str())
        });
    match parsed {
        Some(name) => Observed::available(name.into(), source, at),
        None => invalid(source),
    }
}
pub(crate) fn nvidia_name(line: &[u8], at: Timestamp) -> Observed<String> {
    if line.is_empty() {
        return Observed::unavailable(Source::Procfs, ReasonCode::TemporarilyUnavailable);
    }
    if line.len() > MAX_NAME {
        return invalid(Source::Procfs);
    }
    match line.strip_prefix(b"Model:") {
        Some(value) => product_name(value, Source::Procfs, at),
        None => invalid(Source::Procfs),
    }
}
fn node_name(name: &str) -> bool {
    name.strip_prefix("card")
        .or_else(|| name.strip_prefix("renderD"))
        .and_then(|suffix| suffix.parse::<u32>().ok().map(|n| n.to_string() == suffix))
        .unwrap_or(false)
}
fn pci_location(name: &str) -> bool {
    let parts: Vec<&str> = name.split([':', '.']).collect();
    if parts.len() != 4
        || !(4..=8).contains(&parts[0].len())
        || parts[1].len() != 2
        || parts[2].len() != 2
        || parts[3].len() != 1
    {
        return false;
    }
    parts
        .iter()
        .all(|part| part.bytes().all(|byte| byte.is_ascii_hexdigit()))
        && u8::from_str_radix(parts[2], 16).is_ok_and(|n| n <= 31)
        && u8::from_str_radix(parts[3], 16).is_ok_and(|n| n <= 7)
}
fn read_name(
    path: &Path,
    source: Source,
    first_line: bool,
    check: &mut impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<String>, ScopeError> {
    check()?;
    let metadata = std::fs::symlink_metadata(path);
    check()?;
    match metadata {
        Err(error) => return Ok(failure(error.kind(), source)),
        Ok(metadata) if !metadata.is_file() => return Ok(invalid(source)),
        Ok(_) => {}
    }
    let input = std::fs::File::open(path);
    check()?;
    let mut input = match input {
        Ok(input) => input,
        Err(error) => return Ok(failure(error.kind(), source)),
    };
    let mut bytes = Vec::with_capacity(MAX_NAME + 1);
    if first_line {
        // No BufReader/read-ahead: stop before NVIDIA's later UUID/BIOS lines.
        for _ in 0..=MAX_NAME {
            check()?;
            let mut byte = [0u8; 1];
            let status = input.read(&mut byte);
            check()?;
            match status {
                Ok(0) => break,
                Ok(_) if byte[0] == b'\n' => break,
                Ok(_) => {
                    // Reject a changed header before reading its payload, which
                    // may be an identifier rather than a product description.
                    if bytes.len() < b"Model:".len() && byte[0] != b"Model:"[bytes.len()] {
                        return Ok(invalid(source));
                    }
                    bytes.push(byte[0]);
                }
                Err(error) => return Ok(failure(error.kind(), source)),
            }
        }
        Ok(nvidia_name(&bytes, Timestamp::now()?))
    } else {
        let status = input.take((MAX_NAME + 1) as u64).read_to_end(&mut bytes);
        check()?;
        Ok(match status {
            Ok(_) => product_name(&bytes, source, Timestamp::now()?),
            Err(error) => failure(error.kind(), source),
        })
    }
}
fn device_name(
    device: &Path,
    nvidia_root: &Path,
    check: &mut impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<String>, ScopeError> {
    check()?;
    let driver = std::fs::read_link(device.join("driver"));
    check()?;
    let driver = match driver {
        Ok(driver) => driver,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(unsupported()),
        Err(error) => return Ok(failure(error.kind(), Source::Sysfs)),
    };
    match driver.file_name().and_then(|name| name.to_str()) {
        Some("amdgpu") => read_name(&device.join("product_name"), Source::Sysfs, false, check),
        Some("nvidia") => match device
            .file_name()
            .and_then(|name| name.to_str())
            .filter(|name| pci_location(name))
        {
            Some(location) => read_name(
                &nvidia_root.join(location).join("information"),
                Source::Procfs,
                true,
                check,
            ),
            None => Ok(invalid(Source::Drm)),
        },
        _ => Ok(unsupported()),
    }
}
pub(crate) fn collect(
    root: &Path,
    nvidia_root: &Path,
    context: &CollectContext,
) -> Result<Observed<Vec<GpuInfo>>, ScopeError> {
    collect_with(root, nvidia_root, &context.options, || context.check())
}
fn collect_with(
    root: &Path,
    nvidia_root: &Path,
    options: &Options,
    mut check: impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<Vec<GpuInfo>>, ScopeError> {
    options.validate()?;
    check()?;
    let directory = std::fs::read_dir(root);
    check()?;
    let mut directory = match directory {
        Ok(directory) => directory,
        Err(error) => return Ok(failure(error.kind(), Source::Drm)),
    };
    let mut devices = BTreeSet::new();
    let mut scanned = 0;
    loop {
        check()?;
        let next = directory.next();
        check()?;
        let entry = match next {
            None => break,
            Some(Ok(entry)) => entry,
            Some(Err(error)) => return Ok(failure(error.kind(), Source::Drm)),
        };
        if scanned == MAX_SCANNED {
            return Ok(invalid(Source::Drm));
        }
        scanned += 1;
        let name = entry.file_name();
        let Some(name) = name.to_str() else {
            return Ok(invalid(Source::Drm));
        };
        if !node_name(name) {
            continue;
        }
        let device = std::fs::canonicalize(entry.path().join("device"));
        check()?;
        let device = match device {
            Ok(device) => device,
            Err(error) => return Ok(failure(error.kind(), Source::Drm)),
        };
        let metadata = std::fs::metadata(&device);
        check()?;
        match metadata {
            Ok(metadata) if metadata.is_dir() => {}
            Ok(_) => return Ok(invalid(Source::Drm)),
            Err(error) => return Ok(failure(error.kind(), Source::Drm)),
        }
        if !devices.contains(&device) && devices.len() == options.max_entries {
            return Ok(invalid(Source::Drm));
        }
        devices.insert(device);
    }
    let mut entries = Vec::with_capacity(devices.len());
    for device in devices {
        check()?;
        let mut entry = GpuInfo::default();
        entry.name = device_name(&device, nvidia_root, &mut check)?;
        entry.dedicated_memory_bytes = unsupported();
        entries.push(entry);
    }
    check()?;
    Ok(Observed::available(entries, Source::Drm, Timestamp::now()?))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn product_text_is_bounded_and_has_no_identifiers_or_fake_names() {
        assert_eq!(
            product_name(b" Example GPU\n", Source::Sysfs, Timestamp(1))
                .value()
                .map(String::as_str),
            Some("Example GPU")
        );
        for bytes in [
            b"".as_slice(),
            b" \n",
            b"unknown",
            b"None",
            b"a\0b",
            b"a\nb",
            b"\xff",
        ] {
            let result = product_name(bytes, Source::Sysfs, Timestamp(1));
            assert_eq!(result.reason(), Some(ReasonCode::InvalidData));
            assert!(result.value().is_none() && result.observed_at().is_none());
        }
        assert!(
            product_name(&[b'x'; MAX_NAME], Source::Sysfs, Timestamp(1))
                .value()
                .is_some()
        );
        assert!(
            product_name(&[b'x'; MAX_NAME + 1], Source::Sysfs, Timestamp(1))
                .value()
                .is_none()
        );
    }
    #[test]
    fn nvidia_requires_first_model_line_and_keeps_procfs_source() {
        let result = nvidia_name(b"Model: \t Example GPU", Timestamp(1));
        assert_eq!(result.value().map(String::as_str), Some("Example GPU"));
        assert_eq!(result.source(), Source::Procfs);
        for line in [
            b"IRQ: 1".as_slice(),
            b"GPU UUID: secret",
            b"Model:",
            b"Model: GPU\nGPU UUID: secret",
            &[b'x'; MAX_NAME + 1],
        ] {
            assert_eq!(
                nvidia_name(line, Timestamp(1)).reason(),
                Some(ReasonCode::InvalidData)
            );
        }
        assert_eq!(
            nvidia_name(b"", Timestamp(1)).reason(),
            Some(ReasonCode::TemporarilyUnavailable)
        );
    }
    #[test]
    fn node_and_location_routes_cannot_escape() {
        for name in ["card0", "card12", "renderD128"] {
            assert!(node_name(name));
        }
        for name in [
            "card0-HDMI-A-1",
            "version",
            "card",
            "card01",
            "renderD",
            "card4294967296",
        ] {
            assert!(!node_name(name));
        }
        for name in ["0000:01:00.0", "12345678:ff:1f.7"] {
            assert!(pci_location(name));
        }
        for name in [
            "../../secret",
            "0000:00:ff.0",
            "0000:00:00.8",
            "000:01:00.0",
            "0000:01:0x.0",
        ] {
            assert!(!pci_location(name));
        }
    }
    #[test]
    fn io_states_are_distinct() {
        assert_eq!(
            failure::<()>(io::ErrorKind::PermissionDenied, Source::Drm).availability(),
            Availability::Restricted
        );
        assert_eq!(
            failure::<()>(io::ErrorKind::NotFound, Source::Drm).reason(),
            Some(ReasonCode::NotPresent)
        );
        assert_eq!(
            failure::<()>(io::ErrorKind::TimedOut, Source::Drm).reason(),
            Some(ReasonCode::Timeout)
        );
        assert_eq!(
            unsupported::<()>().availability(),
            Availability::Unsupported
        );
    }
    #[test]
    fn cancellation_does_not_open_a_path() {
        let error = collect_with(
            Path::new("absent"),
            Path::new("absent"),
            &Options::default(),
            || Err(ScopeError::new(ErrorCode::Cancelled)),
        )
        .unwrap_err();
        assert_eq!(error.code, ErrorCode::Cancelled);
    }
    #[test]
    fn static_success_and_missing_directory_are_cached_until_recreation() {
        use std::sync::atomic::{AtomicUsize, Ordering};
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        struct Fixture(std::path::PathBuf);
        impl Backend for Fixture {
            fn name(&self) -> &'static str {
                "gpu-cache-fixture"
            }
            fn capabilities(&self) -> Capabilities {
                vec![]
            }
            fn collect_static(
                &mut self,
                context: &CollectContext,
            ) -> Result<StaticSnapshot, ScopeError> {
                let mut result = StaticSnapshot::default();
                result.gpus = super::collect(&self.0, &self.0.join("absent"), context)?;
                Ok(result)
            }
            fn refresh_dynamic(
                &mut self,
                context: &CollectContext,
            ) -> Result<DynamicSnapshot, ScopeError> {
                context.check()?;
                Ok(DynamicSnapshot::default())
            }
        }
        for missing in [false, true] {
            let path = std::env::temp_dir().join(format!(
                "dscope-gpu-cache-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            if !missing {
                std::fs::create_dir(&path).unwrap();
            }
            let create = || {
                HardwareBuilder::default()
                    .with_backend(100, Fixture(path.clone()))
                    .build()
                    .unwrap()
            };
            let hardware = create();
            let first = hardware.collect().unwrap().static_info.gpus;
            assert_eq!(first.value().is_none(), missing);
            std::fs::create_dir_all(path.join("card0/device")).unwrap();
            hardware.refresh_dynamic().unwrap();
            assert_eq!(hardware.collect().unwrap().static_info.gpus, first);
            assert_eq!(
                create()
                    .collect()
                    .unwrap()
                    .static_info
                    .gpus
                    .value()
                    .unwrap()
                    .len(),
                1
            );
            std::fs::remove_dir_all(path).unwrap();
        }
    }
    #[cfg(unix)]
    mod unix {
        use super::*;
        use std::{
            os::unix::fs::{PermissionsExt, symlink},
            path::PathBuf,
            sync::atomic::{AtomicUsize, Ordering},
        };
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        struct Fixture(PathBuf);
        impl Fixture {
            fn new() -> Self {
                let path = std::env::temp_dir().join(format!(
                    "dscope-gpu-{}-{}",
                    std::process::id(),
                    NEXT.fetch_add(1, Ordering::Relaxed)
                ));
                std::fs::create_dir_all(path.join("drm")).unwrap();
                Self(path)
            }
            fn node(&self, node: &str, device: &str, driver: &str) -> PathBuf {
                let target = self.0.join("devices").join(device);
                std::fs::create_dir_all(&target).unwrap();
                std::fs::create_dir_all(self.0.join("drm").join(node)).unwrap();
                symlink(&target, self.0.join("drm").join(node).join("device")).unwrap();
                if !target.join("driver").is_symlink() {
                    symlink(self.0.join("drivers").join(driver), target.join("driver")).unwrap();
                }
                target
            }
            fn collect(&self, max: usize) -> Observed<Vec<GpuInfo>> {
                collect_with(
                    &self.0.join("drm"),
                    &self.0.join("nvidia"),
                    &Options {
                        max_entries: max,
                        ..Options::default()
                    },
                    || Ok(()),
                )
                .unwrap()
            }
        }
        impl Drop for Fixture {
            fn drop(&mut self) {
                std::fs::remove_dir_all(&self.0).unwrap();
            }
        }
        #[test]
        fn card_render_aliases_deduplicate_and_connectors_are_ignored() {
            let f = Fixture::new();
            let target = f.node("card0", "0000:01:00.0", "amdgpu");
            f.node("renderD128", "0000:01:00.0", "amdgpu");
            std::fs::write(target.join("product_name"), "Unit GPU\n").unwrap();
            std::fs::write(target.join("serial_number"), "private secret").unwrap();
            std::fs::write(target.join("mem_info_vram_total"), "999999").unwrap();
            std::fs::create_dir(f.0.join("drm/card0-HDMI-A-1")).unwrap();
            let result = f.collect(1);
            let entries = result.value().unwrap();
            assert_eq!(entries.len(), 1);
            assert_eq!(
                entries[0].name.value().map(String::as_str),
                Some("Unit GPU")
            );
            assert_eq!(
                entries[0].dedicated_memory_bytes.availability(),
                Availability::Unsupported
            );
            assert_eq!(result.source(), Source::Drm);
        }
        #[test]
        fn first_nvidia_line_stops_before_secret_or_oversized_tail() {
            let f = Fixture::new();
            f.node("card0", "0000:01:00.0", "nvidia");
            let path = f.0.join("nvidia/0000:01:00.0");
            std::fs::create_dir_all(&path).unwrap();
            let mut bytes = b"Model: Unit GPU\nGPU UUID: secret".to_vec();
            bytes.extend_from_slice(&[b'x'; MAX_NAME * 2]);
            std::fs::write(path.join("information"), bytes).unwrap();
            let result = f.collect(1);
            assert_eq!(
                result.value().unwrap()[0].name.value().map(String::as_str),
                Some("Unit GPU")
            );
            assert_eq!(result.value().unwrap()[0].name.source(), Source::Procfs);
        }
        #[test]
        fn empty_missing_broken_identity_and_limit_never_return_a_prefix() {
            let f = Fixture::new();
            assert_eq!(f.collect(1).value().unwrap().len(), 0);
            f.node("card0", "one", "other");
            f.node("card1", "two", "other");
            assert_eq!(f.collect(1).reason(), Some(ReasonCode::InvalidData));
            std::fs::remove_dir_all(f.0.join("drm/card1")).unwrap();
            std::fs::remove_dir_all(f.0.join("devices/one")).unwrap();
            assert_eq!(f.collect(1).reason(), Some(ReasonCode::NotPresent));
            std::fs::remove_dir_all(f.0.join("drm")).unwrap();
            assert_eq!(f.collect(1).reason(), Some(ReasonCode::NotPresent));
        }
        #[test]
        fn missing_bad_and_denied_names_are_field_isolated() {
            let f = Fixture::new();
            let target = f.node("card0", "one", "amdgpu");
            assert_eq!(
                f.collect(1).value().unwrap()[0].name.reason(),
                Some(ReasonCode::NotPresent)
            );
            std::fs::write(target.join("product_name"), b"\xff").unwrap();
            assert_eq!(
                f.collect(1).value().unwrap()[0].name.reason(),
                Some(ReasonCode::InvalidData)
            );
            std::fs::set_permissions(
                target.join("product_name"),
                std::fs::Permissions::from_mode(0o000),
            )
            .unwrap();
            // A root CI would bypass mode bits; do not pretend it proved denial.
            if std::fs::File::open(target.join("product_name")).is_err() {
                assert_eq!(
                    f.collect(1).value().unwrap()[0].name.availability(),
                    Availability::Restricted
                );
            }
        }
        #[test]
        fn final_attribute_links_and_directories_are_not_read() {
            let f = Fixture::new();
            let target = f.node("card0", "one", "amdgpu");
            symlink("serial_number", target.join("product_name")).unwrap();
            assert_eq!(
                f.collect(1).value().unwrap()[0].name.reason(),
                Some(ReasonCode::InvalidData)
            );
            std::fs::remove_file(target.join("product_name")).unwrap();
            std::fs::create_dir(target.join("product_name")).unwrap();
            assert_eq!(
                f.collect(1).value().unwrap()[0].name.reason(),
                Some(ReasonCode::InvalidData)
            );
        }
        #[test]
        fn ignored_entry_scanning_is_bounded() {
            let f = Fixture::new();
            for n in 0..=MAX_SCANNED {
                std::fs::write(f.0.join("drm").join(format!("ignored{n}")), []).unwrap();
            }
            assert_eq!(f.collect(1).reason(), Some(ReasonCode::InvalidData));
        }
    }
}
