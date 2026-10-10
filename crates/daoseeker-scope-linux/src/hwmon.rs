//! Conservative unit routing; unknown drivers and relative Tctl are not Celsius.
//! NVMe Composite is a device-computed Celsius value, not a physical-point claim.
use daoseeker_scope_core::*;
use std::io::{self, Read};
use std::path::{Path, PathBuf};

const MAX_CHIPS: usize = 256;
const MAX_CHIP_ENTRIES: usize = 1024;
const MAX_TOTAL_ENTRIES: usize = 4096;
const MAX_ATTRIBUTE: usize = 128;

fn invalid<T>() -> Observed<T> {
    Observed::unavailable(Source::Hwmon, ReasonCode::InvalidData)
}
fn failure<T>(error: io::Error) -> Observed<T> {
    match error.kind() {
        io::ErrorKind::PermissionDenied => {
            Observed::restricted(Source::Hwmon, ReasonCode::PermissionDenied)
        }
        io::ErrorKind::NotFound => Observed::unavailable(Source::Hwmon, ReasonCode::NotPresent),
        _ => {
            // Linux hwmon returns ENODATA for disabled/unready inputs.
            let reason = if cfg!(target_os = "linux") && error.raw_os_error() == Some(61) {
                ReasonCode::TemporarilyUnavailable
            } else {
                ReasonCode::Unknown
            };
            Observed::unavailable(Source::Hwmon, reason)
        }
    }
}
fn propagate<T, U>(value: &Observed<T>) -> Result<Observed<U>, ScopeError> {
    Observed::missing(
        value.availability(),
        value.source(),
        value.reason().unwrap_or(ReasonCode::Unknown),
    )
}
fn text(bytes: &[u8]) -> Option<&str> {
    if bytes.len() > MAX_ATTRIBUTE {
        return None;
    }
    let s = std::str::from_utf8(bytes).ok()?.trim_ascii();
    (!s.is_empty() && s.bytes().all(|b| b.is_ascii_graphic() || b == b' ')).then_some(s)
}
fn temperature(bytes: &[u8], at: Timestamp) -> Observed<f64> {
    let number = text(bytes)
        .filter(|s| {
            let digits = s.strip_prefix('-').unwrap_or(s);
            !digits.is_empty() && digits.bytes().all(|b| b.is_ascii_digit())
        })
        .and_then(|s| s.parse::<i32>().ok())
        .filter(|n| (-273_150..=1_000_000).contains(n));
    match number {
        Some(n) => Observed::available(f64::from(n) / 1000.0, Source::Hwmon, at),
        None => invalid(),
    }
}
fn routed(driver: &str, index: usize) -> bool {
    driver == "coretemp"
        || (driver == "k10temp" && index == 2)
        || (driver == "nvme" && (1..=9).contains(&index))
}
fn driver_temperature(driver: &str, index: usize, bytes: &[u8], at: Timestamp) -> Observed<f64> {
    let value = temperature(bytes, at);
    if driver == "coretemp" && value.value().is_some_and(|n| *n < 0.0) {
        invalid()
    } else if driver == "nvme" && value.value() == Some(&-273.15) {
        // Zero Kelvin means unimplemented for secondary SMART sensors only.
        // Composite has no such absence contract; reject its unusable zero K.
        Observed::unavailable(
            Source::Hwmon,
            if index == 1 {
                ReasonCode::InvalidData
            } else {
                ReasonCode::NotPresent
            },
        )
    } else {
        value
    }
}
fn read(path: &Path, context: &CollectContext) -> Result<Observed<Vec<u8>>, ScopeError> {
    context.check()?;
    let metadata = std::fs::symlink_metadata(path);
    context.check()?;
    match metadata {
        Err(error) => return Ok(failure(error)),
        Ok(metadata) if !metadata.is_file() => return Ok(invalid()),
        Ok(_) => {}
    }
    // Ordinary attributes only. This is not a defense against hostile TOCTOU.
    let input = std::fs::File::open(path);
    context.check()?;
    let input = match input {
        Ok(input) => input,
        Err(error) => return Ok(failure(error)),
    };
    let mut bytes = Vec::with_capacity(MAX_ATTRIBUTE + 1);
    let result = input
        .take((MAX_ATTRIBUTE + 1) as u64)
        .read_to_end(&mut bytes);
    context.check()?;
    Ok(match result {
        Err(error) => failure(error),
        Ok(_) if bytes.len() > MAX_ATTRIBUTE => invalid(),
        Ok(_) => Observed::available(bytes, Source::Hwmon, Timestamp::now()?),
    })
}
fn channel(name: &str) -> Option<usize> {
    let digits = name.strip_prefix("temp")?.strip_suffix("_input")?;
    if digits.starts_with('0') || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    digits.parse::<usize>().ok().filter(|n| *n > 0)
}
fn chip(name: &str) -> bool {
    name.strip_prefix("hwmon")
        .is_some_and(|s| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit()))
}
fn sample(
    path: &Path,
    index: usize,
    driver: &Observed<Vec<u8>>,
    context: &CollectContext,
) -> Result<Observed<f64>, ScopeError> {
    let driver = match driver.value() {
        Some(value) => match text(value) {
            Some(value) => value,
            None => return Ok(invalid()),
        },
        None => return propagate(driver),
    };
    if !routed(driver, index) {
        return Observed::missing(
            Availability::Unsupported,
            Source::Hwmon,
            ReasonCode::NotSupported,
        );
    }
    for (suffix, ready) in [("enable", b"1".as_slice()), ("fault", b"0".as_slice())] {
        let flag = read(&path.join(format!("temp{index}_{suffix}")), context)?;
        if flag.reason() == Some(ReasonCode::NotPresent) {
            continue; // Optional ABI attribute; no fabricated value is published.
        }
        let bytes = match flag.value() {
            Some(bytes) => bytes,
            None => return propagate(&flag),
        };
        let flag = bytes.trim_ascii();
        if flag != b"0" && flag != b"1" {
            return Ok(invalid());
        }
        if flag != ready {
            return Ok(Observed::unavailable(
                Source::Hwmon,
                ReasonCode::TemporarilyUnavailable,
            ));
        }
    }
    let raw = read(&path.join(format!("temp{index}_input")), context)?;
    match (raw.value(), raw.observed_at()) {
        (Some(bytes), Some(at)) => Ok(driver_temperature(driver, index, bytes, at)),
        _ => propagate(&raw),
    }
}
pub(crate) fn collect(
    root: &Path,
    context: &CollectContext,
) -> Result<Observed<Vec<SensorInfo>>, ScopeError> {
    context.check()?;
    let directory = std::fs::read_dir(root);
    context.check()?;
    let directory = match directory {
        Ok(directory) => directory,
        Err(error) => return Ok(failure(error)),
    };
    let mut chips: Vec<PathBuf> = Vec::new();
    for (count, entry) in directory.enumerate() {
        context.check()?;
        if count == MAX_CHIPS {
            return Ok(invalid());
        }
        let entry = match entry {
            Ok(entry) => entry,
            Err(error) => return Ok(failure(error)),
        };
        if entry.file_name().to_str().is_some_and(chip) {
            chips.push(entry.path());
        }
    }
    chips.sort();
    let mut sensors = Vec::new();
    let mut total = 0;
    for path in chips {
        context.check()?;
        let entries = std::fs::read_dir(&path);
        context.check()?;
        let entries = match entries {
            Ok(entries) => entries,
            Err(error) => return Ok(failure(error)),
        };
        let mut channels = Vec::new();
        for (count, entry) in entries.enumerate() {
            context.check()?;
            if count == MAX_CHIP_ENTRIES || total == MAX_TOTAL_ENTRIES {
                return Ok(invalid());
            }
            total += 1;
            let entry = match entry {
                Ok(entry) => entry,
                Err(error) => return Ok(failure(error)),
            };
            if let Some(index) = entry.file_name().to_str().and_then(channel) {
                if sensors.len() + channels.len() == context.options.max_entries {
                    return Ok(invalid());
                }
                channels.push(index);
            }
        }
        channels.sort_unstable();
        if channels.is_empty() {
            continue;
        }
        let driver = read(&path.join("name"), context)?;
        for index in channels {
            let mut sensor = SensorInfo::default();
            sensor.label = Observed::restricted(Source::Hwmon, ReasonCode::PrivacyRedacted);
            sensor.temperature_celsius = sample(&path, index, &driver, context)?;
            sensors.push(sensor);
        }
    }
    context.check()?;
    Ok(Observed::available(
        sensors,
        Source::Hwmon,
        Timestamp::now()?,
    ))
}

#[cfg(feature = "fuzzing")]
pub(crate) fn fuzz_temperature(bytes: &[u8]) -> Observed<f64> {
    temperature(bytes, Timestamp(1))
}
#[cfg(feature = "fuzzing")]
pub(crate) fn fuzz_nvme_temperature(bytes: &[u8], secondary: bool) -> Observed<f64> {
    driver_temperature("nvme", if secondary { 2 } else { 1 }, bytes, Timestamp(1))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};
    static NEXT: AtomicU64 = AtomicU64::new(0);
    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "dscope-hwmon-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            std::fs::create_dir(&path).expect("own fixture");
            Self(path)
        }
        fn chip(&self, name: &str, driver: &[u8]) {
            std::fs::create_dir(self.0.join(name)).expect("chip");
            self.write(name, "name", driver);
        }
        fn write(&self, name: &str, attr: &str, bytes: &[u8]) {
            std::fs::write(self.0.join(name).join(attr), bytes).expect("attribute");
        }
        fn hardware(&self, max: usize) -> Hardware {
            let hardware = HardwareBuilder::new(Options {
                max_entries: max,
                ..Options::default()
            })
            .with_backend(
                100,
                crate::LinuxBackend {
                    hwmon_root: self.0.clone(),
                    ..crate::LinuxBackend::new()
                },
            )
            .build()
            .expect("hardware");
            hardware.collect().expect("initial collection");
            hardware
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            std::fs::remove_dir_all(&self.0).expect("own fixture cleanup");
        }
    }
    fn values(observation: &Observed<Vec<SensorInfo>>) -> &[SensorInfo] {
        assert_eq!(observation.availability(), Availability::Available);
        assert_eq!(observation.source(), Source::Hwmon);
        assert!(observation.observed_at().is_some());
        observation.value().expect("enumeration")
    }
    fn missing<T>(observation: &Observed<T>, reason: ReasonCode) {
        assert_eq!(observation.reason(), Some(reason));
        assert_eq!(observation.source(), Source::Hwmon);
        assert!(observation.value().is_none());
        assert!(observation.observed_at().is_none());
    }
    #[test]
    fn route_units_isolate_bad_fields_and_refresh_members_without_static_reread() {
        let f = Fixture::new();
        f.chip("hwmon0", b"coretemp\n");
        f.write("hwmon0", "temp1_input", b"0\n");
        f.write("hwmon0", "temp2_input", b"NaN");
        f.write("hwmon0", "temp1_label", b"DO-NOT-COLLECT");
        f.chip("hwmon1", b"k10temp");
        f.write("hwmon1", "temp1_input", b"100000");
        f.write("hwmon1", "temp2_input", b"-1250");
        f.chip("hwmon2", b"unknown-thermistor");
        f.write("hwmon2", "temp1_input", b"500");
        let hardware = f.hardware(128);
        let snapshot = hardware.collect().expect("snapshot");
        let items = values(&snapshot.dynamic.sensors);
        assert_eq!(items.len(), 5);
        assert_eq!(items[0].temperature_celsius.value(), Some(&0.0));
        missing(&items[1].temperature_celsius, ReasonCode::InvalidData);
        assert_eq!(
            items[2].temperature_celsius.availability(),
            Availability::Unsupported
        );
        assert_eq!(items[3].temperature_celsius.value(), Some(&-1.25));
        assert_eq!(
            items[4].temperature_celsius.availability(),
            Availability::Unsupported
        );
        for sensor in items {
            assert_eq!(sensor.label.availability(), Availability::Restricted);
            missing(&sensor.label, ReasonCode::PrivacyRedacted);
        }
        f.write("hwmon0", "temp2_input", b"42500");
        std::fs::remove_file(f.0.join("hwmon1/temp2_input")).expect("hot unplug");
        let refreshed = hardware.refresh_dynamic().expect("refresh");
        let items = values(&refreshed.sensors);
        assert_eq!(items.len(), 4);
        assert_eq!(items[1].temperature_celsius.value(), Some(&42.5));
        assert_eq!(
            hardware.collect().expect("cached").static_info,
            snapshot.static_info
        );
    }
    #[test]
    fn flags_and_driver_failures_recover_without_using_stale_temperature() {
        let f = Fixture::new();
        f.chip("hwmon0", b"coretemp");
        f.write("hwmon0", "temp1_input", b"50000");
        let hw = f.hardware(128);
        for (attr, raw, reason) in [
            (
                "temp1_enable",
                b"0".as_slice(),
                ReasonCode::TemporarilyUnavailable,
            ),
            ("temp1_enable", b"2", ReasonCode::InvalidData),
            ("temp1_fault", b"1", ReasonCode::TemporarilyUnavailable),
            ("temp1_fault", b"NaN", ReasonCode::InvalidData),
        ] {
            f.write("hwmon0", attr, raw);
            let result = hw.refresh_dynamic().expect("refresh");
            missing(&values(&result.sensors)[0].temperature_celsius, reason);
            std::fs::remove_file(f.0.join("hwmon0").join(attr)).expect("remove flag");
            let result = hw.refresh_dynamic().expect("recover");
            assert_eq!(
                values(&result.sensors)[0].temperature_celsius.value(),
                Some(&50.0)
            );
        }
        for (raw, reason) in [
            (b"".as_slice(), ReasonCode::InvalidData),
            (b"\xff", ReasonCode::InvalidData),
        ] {
            f.write("hwmon0", "name", raw);
            let result = hw.refresh_dynamic().expect("refresh");
            missing(&values(&result.sensors)[0].temperature_celsius, reason);
        }
        std::fs::remove_file(f.0.join("hwmon0/name")).expect("remove name");
        let result = hw.refresh_dynamic().expect("refresh");
        missing(
            &values(&result.sensors)[0].temperature_celsius,
            ReasonCode::NotPresent,
        );
    }
    #[test]
    fn signed_numeric_boundaries_and_invalid_formats() {
        for (raw, expected) in [
            (b"0".as_slice(), 0.0),
            (b"-1250\n", -1.25),
            (b"-273150", -273.15),
            (b"1000000", 1000.0),
        ] {
            assert_eq!(temperature(raw, Timestamp(1)).value(), Some(&expected));
        }
        for raw in [
            b"NaN".as_slice(),
            b"+1",
            b"1.5",
            b"1 C",
            b"-273151",
            b"1000001",
            b"2147483648",
            b"\xff",
            b"",
            b"-",
            &[b'0'; 129],
        ] {
            missing(&temperature(raw, Timestamp(1)), ReasonCode::InvalidData);
        }
        assert_eq!(channel("temp1_input"), Some(1));
        for raw in [
            "temp0_input",
            "temp01_input",
            "temp-1_input",
            "temp1_label",
            "temp184467440737095516160_input",
        ] {
            assert!(channel(raw).is_none());
        }
    }
    #[test]
    fn nvme_channels_units_zero_kelvin_and_refresh_recovery() {
        let f = Fixture::new();
        f.chip("hwmon0", b"nvme\n");
        for index in 1..=9 {
            f.write("hwmon0", &format!("temp{index}_input"), b"26850\n");
        }
        // A higher channel must not be opened, even when it is not a file.
        std::fs::create_dir(f.0.join("hwmon0/temp10_input")).expect("unsupported input");
        f.write("hwmon0", "serial", b"DO-NOT-COLLECT");
        let hw = f.hardware(128);
        let first = hw.collect().expect("baseline");
        let items = values(&first.dynamic.sensors);
        assert_eq!(items.len(), 10);
        for sensor in &items[..9] {
            assert_eq!(sensor.temperature_celsius.value(), Some(&26.85));
            missing(&sensor.label, ReasonCode::PrivacyRedacted);
        }
        assert_eq!(
            items[9].temperature_celsius.availability(),
            Availability::Unsupported
        );
        missing(&items[9].temperature_celsius, ReasonCode::NotSupported);
        f.write("hwmon0", "temp1_input", b"-273150");
        f.write("hwmon0", "temp2_input", b"-273150");
        f.write("hwmon0", "temp3_input", b"0");
        f.write("hwmon0", "temp4_input", b"-150");
        f.write("hwmon0", "temp9_input", b"NaN");
        let next = hw.refresh_dynamic().expect("zero K");
        let items = values(&next.sensors);
        missing(&items[0].temperature_celsius, ReasonCode::InvalidData);
        missing(&items[1].temperature_celsius, ReasonCode::NotPresent);
        assert_eq!(items[2].temperature_celsius.value(), Some(&0.0));
        assert_eq!(items[3].temperature_celsius.value(), Some(&-0.15));
        missing(&items[8].temperature_celsius, ReasonCode::InvalidData);
        for index in [1, 2, 9] {
            f.write("hwmon0", &format!("temp{index}_input"), b"27850");
        }
        std::fs::remove_file(f.0.join("hwmon0/temp3_input")).expect("unplug channel");
        let next = hw.refresh_dynamic().expect("recover");
        let items = values(&next.sensors);
        assert_eq!(items.len(), 9);
        assert_eq!(items[0].temperature_celsius.value(), Some(&27.85));
        assert_eq!(items[1].temperature_celsius.value(), Some(&27.85));
        assert_eq!(items[7].temperature_celsius.value(), Some(&27.85));
        assert_eq!(hw.collect().expect("cached").static_info, first.static_info);
    }
    #[test]
    fn empty_missing_and_each_enumeration_limit_are_distinct() {
        let f = Fixture::new();
        let hw = f.hardware(1);
        assert!(values(&hw.refresh_dynamic().expect("empty").sensors).is_empty());
        f.chip("hwmon0", b"coretemp");
        f.write("hwmon0", "temp1_input", b"1");
        f.write("hwmon0", "temp2_input", b"2");
        missing(
            &hw.refresh_dynamic().expect("limit").sensors,
            ReasonCode::InvalidData,
        );
        std::fs::remove_file(f.0.join("hwmon0/temp2_input")).expect("remove");
        assert_eq!(
            values(&hw.refresh_dynamic().expect("recover").sensors).len(),
            1
        );
        for i in 0..MAX_CHIP_ENTRIES {
            f.write("hwmon0", &format!("ignored{i}"), b"");
        }
        missing(
            &hw.refresh_dynamic().expect("scan limit").sensors,
            ReasonCode::InvalidData,
        );
        let f2 = Fixture::new();
        for i in 0..=MAX_CHIPS {
            std::fs::write(f2.0.join(format!("ignored{i}")), b"").expect("entry");
        }
        missing(
            &f2.hardware(128)
                .refresh_dynamic()
                .expect("class limit")
                .sensors,
            ReasonCode::InvalidData,
        );
        let f3 = Fixture::new();
        for n in 0..5 {
            f3.chip(&format!("hwmon{n}"), b"coretemp");
            for i in 0..900 {
                f3.write(&format!("hwmon{n}"), &format!("ignored{i}"), b"");
            }
        }
        missing(
            &f3.hardware(128)
                .refresh_dynamic()
                .expect("global scan limit")
                .sensors,
            ReasonCode::InvalidData,
        );
        let absent = crate::LinuxBackend {
            hwmon_root: f.0.join("missing"),
            ..crate::LinuxBackend::new()
        };
        let hw = HardwareBuilder::default()
            .with_backend(100, absent)
            .build()
            .expect("hardware");
        hw.collect().expect("initial collection");
        missing(
            &hw.refresh_dynamic().expect("missing").sensors,
            ReasonCode::NotPresent,
        );
    }
    #[test]
    fn directories_are_rejected_as_attributes_and_negative_coretemp_is_invalid() {
        let f = Fixture::new();
        f.chip("hwmon0", b"coretemp");
        f.write("hwmon0", "temp1_input", b"-1");
        let hw = f.hardware(128);
        missing(
            &values(&hw.refresh_dynamic().expect("refresh").sensors)[0].temperature_celsius,
            ReasonCode::InvalidData,
        );
        std::fs::remove_file(f.0.join("hwmon0/temp1_input")).expect("remove");
        std::fs::create_dir(f.0.join("hwmon0/temp1_input")).expect("directory");
        missing(
            &values(&hw.refresh_dynamic().expect("refresh").sensors)[0].temperature_celsius,
            ReasonCode::InvalidData,
        );
    }
    #[cfg(unix)]
    #[test]
    fn class_symlinks_are_allowed_but_attribute_symlinks_are_rejected() {
        use std::os::unix::fs::symlink;
        let f = Fixture::new();
        let target = Fixture::new();
        target.chip("device", b"coretemp");
        target.write("device", "temp1_input", b"50000");
        symlink(target.0.join("device"), f.0.join("hwmon0")).expect("class link");
        let hw = f.hardware(128);
        assert_eq!(
            values(&hw.refresh_dynamic().expect("refresh").sensors)[0]
                .temperature_celsius
                .value(),
            Some(&50.0)
        );
        symlink("temp1_input", target.0.join("device/temp2_input")).expect("attribute link");
        missing(
            &values(&hw.refresh_dynamic().expect("refresh").sensors)[1].temperature_celsius,
            ReasonCode::InvalidData,
        );
    }
    #[cfg(feature = "fuzzing")]
    #[test]
    fn mutation_smoke_keeps_finite_bounded_values_and_missing_metadata() {
        let mut state = 20261010u32;
        for len in 0..512 {
            let bytes: Vec<_> = (0..len)
                .map(|_| {
                    state = state.wrapping_mul(1664525).wrapping_add(1013904223);
                    (state >> 24) as u8
                })
                .collect();
            let value = fuzz_temperature(&bytes);
            if let Some(n) = value.value() {
                assert!(n.is_finite() && (-273.15..=1000.0).contains(n));
                assert_eq!(value.availability(), Availability::Available);
            } else {
                missing(&value, ReasonCode::InvalidData);
            }
        }
    }
}
