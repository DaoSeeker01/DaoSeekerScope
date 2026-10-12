//! Whole block-device capacities; no partitions, labels, identifiers or totals.
use daoseeker_scope_core::*;
use std::{
    io::{self, Read},
    path::{Path, PathBuf},
};

const MAX_ATTRIBUTE: usize = 128;
fn invalid<T>() -> Observed<T> {
    Observed::unavailable(Source::Sysfs, ReasonCode::InvalidData)
}
fn failure<T>(kind: io::ErrorKind) -> Observed<T> {
    match kind {
        io::ErrorKind::PermissionDenied => {
            Observed::restricted(Source::Sysfs, ReasonCode::PermissionDenied)
        }
        io::ErrorKind::NotFound => Observed::unavailable(Source::Sysfs, ReasonCode::NotPresent),
        _ => Observed::unavailable(Source::Sysfs, ReasonCode::Unknown),
    }
}
pub(crate) fn capacity(bytes: &[u8], at: Timestamp) -> Observed<u64> {
    if bytes.len() > MAX_ATTRIBUTE {
        return invalid();
    }
    let value = std::str::from_utf8(bytes)
        .ok()
        .map(str::trim_ascii)
        .filter(|text| !text.is_empty() && text.bytes().all(|byte| byte.is_ascii_digit()))
        .and_then(|text| text.parse::<u64>().ok())
        .and_then(|sectors| sectors.checked_mul(512));
    match value {
        Some(bytes) => Observed::available(bytes, Source::Sysfs, at),
        None => invalid(),
    }
}
fn read(
    path: &Path,
    check: &mut impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<u64>, ScopeError> {
    check()?;
    let metadata = std::fs::symlink_metadata(path);
    check()?;
    match metadata {
        Err(error) => return Ok(failure(error.kind())),
        Ok(metadata) if !metadata.is_file() => return Ok(invalid()),
        Ok(_) => {}
    }
    let input = std::fs::File::open(path);
    check()?;
    let input = match input {
        Ok(input) => input,
        Err(error) => return Ok(failure(error.kind())),
    };
    let mut bytes = Vec::with_capacity(MAX_ATTRIBUTE + 1);
    let status = input
        .take((MAX_ATTRIBUTE + 1) as u64)
        .read_to_end(&mut bytes);
    check()?;
    Ok(match status {
        Ok(_) => capacity(&bytes, Timestamp::now()?),
        Err(error) => failure(error.kind()),
    })
}
pub(crate) fn collect(
    root: &Path,
    context: &CollectContext,
) -> Result<Observed<Vec<StorageInfo>>, ScopeError> {
    collect_with(root, &context.options, || context.check())
}
fn collect_with(
    root: &Path,
    options: &Options,
    mut check: impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<Vec<StorageInfo>>, ScopeError> {
    options.validate()?;
    check()?;
    let directory = std::fs::read_dir(root);
    check()?;
    let directory = match directory {
        Ok(directory) => directory,
        Err(error) => return Ok(failure(error.kind())),
    };
    let mut paths: Vec<PathBuf> = Vec::new();
    for entry in directory {
        check()?;
        let path = match entry {
            Ok(entry) => entry.path(),
            Err(error) => return Ok(failure(error.kind())),
        };
        if paths.len() == options.max_entries {
            return Ok(invalid());
        }
        paths.push(path);
    }
    paths.sort_unstable();
    let mut entries = Vec::with_capacity(paths.len());
    for path in paths {
        check()?;
        let mut item = StorageInfo::default();
        item.name = if options.privacy.permits_sensitive() {
            match path
                .file_name()
                .and_then(|name| name.to_str())
                .filter(|name| {
                    !name.is_empty()
                        && name.len() <= 255
                        && !name.trim().is_empty()
                        && !name.chars().any(char::is_control)
                }) {
                Some(name) => Observed::available(name.into(), Source::Sysfs, Timestamp::now()?),
                None => invalid(),
            }
        } else {
            Observed::restricted(Source::Sysfs, ReasonCode::PrivacyRedacted)
        };
        item.capacity_bytes = read(&path.join("size"), &mut check)?;
        entries.push(item);
    }
    check()?;
    Ok(Observed::available(
        entries,
        Source::Sysfs,
        Timestamp::now()?,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    static NEXT: AtomicUsize = AtomicUsize::new(0);
    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "dscope-storage-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            std::fs::create_dir(&path).expect("fixture");
            Self(path)
        }
        fn device(&self, name: &str, bytes: &[u8]) {
            let path = self.0.join(name);
            std::fs::create_dir_all(&path).expect("device");
            std::fs::write(path.join("size"), bytes).expect("size");
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            std::fs::remove_dir_all(&self.0).expect("fixture cleanup");
        }
    }
    fn collect(root: &Path, options: &Options) -> Result<Observed<Vec<StorageInfo>>, ScopeError> {
        super::collect_with(root, options, || Ok(()))
    }
    #[test]
    fn sectors_are_always_512_bytes_and_numeric_errors_are_missing() {
        for (data, expected) in [(b"0".as_slice(), 0), (b"8\n", 4096), (b" 0002\n", 1024)] {
            assert_eq!(capacity(data, Timestamp(1)).value(), Some(&expected));
        }
        let largest = u64::MAX / 512;
        assert_eq!(
            capacity(largest.to_string().as_bytes(), Timestamp(1)).value(),
            Some(&(largest * 512))
        );
        for data in [
            b"".as_slice(),
            b"-1",
            b"+1",
            b"1.5",
            b"1 KiB",
            b"1 2",
            b"NaN",
            b"\xff",
            b"18446744073709551616",
        ] {
            let missing = capacity(data, Timestamp(1));
            assert_eq!(missing.reason(), Some(ReasonCode::InvalidData));
            assert!(missing.value().is_none());
            assert!(missing.observed_at().is_none());
        }
        assert_eq!(
            capacity((largest + 1).to_string().as_bytes(), Timestamp(1)).reason(),
            Some(ReasonCode::InvalidData)
        );
        assert_eq!(
            capacity(&[b'0'; 129], Timestamp(1)).reason(),
            Some(ReasonCode::InvalidData)
        );
    }
    #[test]
    fn fields_are_isolated_names_are_private_and_partitions_are_not_walked() {
        let fixture = Fixture::new();
        fixture.device("a", b"8");
        fixture.device("b", b"bad");
        std::fs::create_dir(fixture.0.join("a/a1")).expect("partition");
        std::fs::write(fixture.0.join("a/a1/size"), b"9999").expect("partition size");
        std::fs::write(fixture.0.join("a/serial"), b"private-secret").expect("unused metadata");
        let result = collect(&fixture.0, &Options::default()).expect("collect");
        let entries = result.value().expect("table");
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].capacity_bytes.value(), Some(&4096));
        assert_eq!(
            entries[1].capacity_bytes.reason(),
            Some(ReasonCode::InvalidData)
        );
        assert!(
            entries
                .iter()
                .all(|item| item.name.reason() == Some(ReasonCode::PrivacyRedacted))
        );
        let options = Options {
            privacy: PrivacyOptions {
                include_sensitive: true,
                caller_authorized: true,
            },
            ..Options::default()
        };
        let named = collect(&fixture.0, &options).expect("named");
        assert_eq!(
            named.value().expect("table")[0]
                .name
                .value()
                .map(String::as_str),
            Some("a")
        );
        assert_eq!(
            named.value().expect("table")[0].capacity_bytes.value(),
            Some(&4096)
        );
    }
    #[test]
    fn empty_missing_nonregular_and_limits_are_distinct() {
        let fixture = Fixture::new();
        assert!(
            collect(&fixture.0, &Options::default())
                .expect("empty")
                .value()
                .expect("available")
                .is_empty()
        );
        fixture.device("a", b"1");
        std::fs::remove_file(fixture.0.join("a/size")).expect("remove");
        let result = collect(&fixture.0, &Options::default()).expect("missing attribute");
        assert_eq!(
            result.value().expect("table")[0].capacity_bytes.reason(),
            Some(ReasonCode::NotPresent)
        );
        std::fs::create_dir(fixture.0.join("a/size")).expect("nonregular");
        let result = collect(&fixture.0, &Options::default()).expect("directory attribute");
        assert_eq!(
            result.value().expect("table")[0].capacity_bytes.reason(),
            Some(ReasonCode::InvalidData)
        );
        fixture.device("b", b"2");
        let options = Options {
            max_entries: 1,
            ..Options::default()
        };
        assert_eq!(
            collect(&fixture.0, &options).expect("limit").reason(),
            Some(ReasonCode::InvalidData)
        );
        assert_eq!(
            collect(&fixture.0.join("absent"), &Options::default())
                .expect("absent")
                .reason(),
            Some(ReasonCode::NotPresent)
        );
    }
    #[test]
    fn cancelled_or_expired_reads_stop_before_enumerating() {
        let fixture = Fixture::new();
        for code in [ErrorCode::Cancelled, ErrorCode::Timeout] {
            assert_eq!(
                super::collect_with(&fixture.0, &Options::default(), || Err(ScopeError::new(
                    code
                )))
                .expect_err("stopped")
                .code,
                code
            );
        }
    }
    #[test]
    fn static_storage_is_cached_and_new_hardware_observes_changes() {
        let fixture = Fixture::new();
        fixture.device("a", b"8");
        let create = || {
            let mut backend = crate::LinuxBackend::new();
            backend.block_root = fixture.0.clone();
            HardwareBuilder::default()
                .with_backend(0, backend)
                .build()
                .expect("hardware")
        };
        let hardware = create();
        let first = hardware.collect().expect("initial").static_info.storage;
        fixture.device("a", b"16");
        hardware.refresh_dynamic().expect("dynamic");
        assert_eq!(
            hardware.collect().expect("cached").static_info.storage,
            first
        );
        assert_eq!(
            create()
                .collect()
                .expect("new instance")
                .static_info
                .storage
                .value()
                .expect("entries")[0]
                .capacity_bytes
                .value(),
            Some(&8192)
        );
    }
}
