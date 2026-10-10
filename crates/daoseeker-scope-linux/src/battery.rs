//! Fresh, bounded power_supply enumeration. No identifiers or charging inference.
use daoseeker_scope_core::*;
use std::io::{self, Read};
use std::path::{Path, PathBuf};

const MAX_SUPPLIES: usize = 256;
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

fn text(bytes: &[u8]) -> Option<&str> {
    if bytes.len() > MAX_ATTRIBUTE {
        return None;
    }
    let value = std::str::from_utf8(bytes).ok()?.trim_ascii();
    (!value.is_empty() && value.bytes().all(|b| b.is_ascii_graphic() || b == b' ')).then_some(value)
}

fn integer(bytes: &[u8], max: u8, at: Timestamp) -> Observed<u8> {
    let number = text(bytes)
        .filter(|s| s.bytes().all(|b| b.is_ascii_digit()))
        .and_then(|s| s.parse::<u8>().ok())
        .filter(|n| *n <= max);
    match number {
        Some(n) => Observed::available(n, Source::Sysfs, at),
        None => invalid(),
    }
}

fn read(path: &Path, context: &CollectContext) -> Result<Observed<Vec<u8>>, ScopeError> {
    context.check()?;
    // Class entries may be symlinks; their attributes must be regular files.
    // This rejects an unchanged FIFO/device before open, not a hostile TOCTOU race.
    let metadata = std::fs::symlink_metadata(path);
    context.check()?;
    match metadata {
        Err(error) => return Ok(failure(error.kind())),
        Ok(metadata) if !metadata.is_file() => return Ok(invalid()),
        Ok(_) => {}
    }
    let input = std::fs::File::open(path);
    context.check()?;
    let input = match input {
        Ok(input) => input,
        Err(error) => return Ok(failure(error.kind())),
    };
    let mut bytes = Vec::with_capacity(MAX_ATTRIBUTE + 1);
    let read = input
        .take((MAX_ATTRIBUTE + 1) as u64)
        .read_to_end(&mut bytes);
    context.check()?;
    Ok(match read {
        Err(error) => failure(error.kind()),
        Ok(_) if bytes.len() > MAX_ATTRIBUTE => invalid(),
        Ok(_) => Observed::available(bytes, Source::Sysfs, Timestamp::now()?),
    })
}

fn propagate<T, U>(observation: &Observed<T>) -> Result<Observed<U>, ScopeError> {
    Observed::missing(
        observation.availability(),
        observation.source(),
        observation.reason().unwrap_or(ReasonCode::Unknown),
    )
}

fn convert<T, U>(
    observation: &Observed<T>,
    map: impl FnOnce(&T) -> U,
) -> Result<Observed<U>, ScopeError> {
    match (observation.value(), observation.observed_at()) {
        (Some(value), Some(at)) => Ok(Observed::available(map(value), observation.source(), at)),
        _ => propagate(observation),
    }
}

fn number(path: &Path, max: u8, context: &CollectContext) -> Result<Observed<u8>, ScopeError> {
    let raw = read(path, context)?;
    match (raw.value(), raw.observed_at()) {
        (Some(bytes), Some(at)) => Ok(integer(bytes, max, at)),
        _ => propagate(&raw),
    }
}

pub(crate) fn collect(
    root: &Path,
    context: &CollectContext,
) -> Result<Observed<Vec<BatteryInfo>>, ScopeError> {
    context.check()?;
    let directory = std::fs::read_dir(root);
    context.check()?;
    let entries = match directory {
        Ok(entries) => entries,
        Err(error) => return Ok(failure(error.kind())),
    };
    let mut paths: Vec<PathBuf> = Vec::new();
    for entry in entries {
        context.check()?;
        let entry = match entry {
            Ok(entry) => entry,
            Err(error) => return Ok(failure(error.kind())),
        };
        if paths.len() == MAX_SUPPLIES {
            return Ok(invalid());
        }
        paths.push(entry.path());
    }
    paths.sort();
    let mut batteries = Vec::new();
    let mut mains = Vec::new();
    for path in paths {
        let kind = read(&path.join("type"), context)?;
        let bytes = match kind.value() {
            Some(bytes) => bytes,
            None => return propagate(&kind),
        };
        match text(bytes) {
            Some("Battery") => {
                let present = number(&path.join("present"), 1, context)?;
                if present.value() == Some(&0) {
                    continue;
                }
                if present.value().is_none() && present.reason() != Some(ReasonCode::NotPresent) {
                    return propagate(&present);
                }
                if batteries.len() == context.options.max_entries {
                    return Ok(invalid());
                }
                let mut battery = BatteryInfo::default();
                battery.charge_percent =
                    convert(&number(&path.join("capacity"), 100, context)?, |n| {
                        f64::from(*n)
                    })?;
                batteries.push(battery);
            }
            Some("Mains") => mains.push(number(&path.join("online"), 1, context)?),
            Some(_) => {}
            None => return Ok(invalid()),
        }
    }
    let ac = if let Some(online) = mains.iter().find(|o| o.value() == Some(&1)) {
        convert(online, |_| true)?
    } else if let Some(error) = mains.iter().find(|o| o.value().is_none()) {
        propagate(error)?
    } else if let Some(offline) = mains.first() {
        convert(offline, |_| false)?
    } else {
        Observed::unavailable(Source::Sysfs, ReasonCode::NotPresent)
    };
    for battery in &mut batteries {
        battery.on_ac_power = ac.clone();
    }
    context.check()?;
    Ok(Observed::available(
        batteries,
        Source::Sysfs,
        Timestamp::now()?,
    ))
}

#[cfg(feature = "fuzzing")]
pub(crate) fn fuzz_attributes(bytes: &[u8]) -> (Observed<u8>, Observed<u8>, bool) {
    // One raw attribute evaluated at both production ranges and as a type string.
    (
        integer(bytes, 100, Timestamp(1)),
        integer(bytes, 1, Timestamp(1)),
        text(bytes).is_some(),
    )
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
                "dscope-battery-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            std::fs::create_dir(&path).expect("fresh fixture");
            Self(path)
        }
        fn supply(&self, name: &str, kind: &str) {
            std::fs::create_dir(self.0.join(name)).expect("supply");
            self.write(name, "type", kind.as_bytes());
        }
        fn write(&self, name: &str, field: &str, value: &[u8]) {
            std::fs::write(self.0.join(name).join(field), value).expect("attribute");
        }
        fn hardware(&self, max: usize) -> Hardware {
            let options = Options {
                max_entries: max,
                ..Options::default()
            };
            HardwareBuilder::new(options)
                .with_backend(
                    100,
                    crate::LinuxBackend {
                        power_root: self.0.clone(),
                        ..crate::LinuxBackend::new()
                    },
                )
                .build()
                .expect("hardware")
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            std::fs::remove_dir_all(&self.0).expect("own fixture cleanup");
        }
    }
    fn entries(value: &Observed<Vec<BatteryInfo>>) -> &[BatteryInfo] {
        assert_eq!(value.source(), Source::Sysfs);
        assert_eq!(value.availability(), Availability::Available);
        assert!(value.observed_at().is_some());
        value.value().expect("complete enumeration")
    }
    fn missing<T>(value: &Observed<T>, reason: ReasonCode) {
        assert_eq!(value.availability(), Availability::Unavailable);
        assert_eq!(value.source(), Source::Sysfs);
        assert_eq!(value.reason(), Some(reason));
        assert!(value.value().is_none() && value.observed_at().is_none());
    }
    #[test]
    fn dynamic_members_capacity_and_mains_recover_without_static_reread() {
        let f = Fixture::new();
        f.supply("z-battery", "Battery\n");
        f.write("z-battery", "capacity", b"100\n");
        f.supply("a-battery", "Battery");
        f.write("a-battery", "capacity", b"0\n");
        f.supply("mains", "Mains");
        f.write("mains", "online", b"1\n");
        f.write("a-battery", "serial_number", b"DO-NOT-COLLECT");
        let hw = f.hardware(128);
        let first = hw.collect().expect("collect");
        let list = entries(&first.dynamic.batteries);
        assert_eq!(list.len(), 2);
        assert_eq!(list[0].charge_percent.value(), Some(&0.0));
        assert_eq!(list[1].charge_percent.value(), Some(&100.0));
        assert_eq!(list[0].on_ac_power.value(), Some(&true));
        f.write("a-battery", "capacity", b"73\n");
        f.write("mains", "online", b"0\n");
        std::fs::remove_dir_all(f.0.join("z-battery")).expect("remove member");
        let fresh = hw.collect().expect("refresh");
        assert_eq!(fresh.static_info, first.static_info);
        assert_eq!(entries(&fresh.dynamic.batteries).len(), 1);
        assert_eq!(
            entries(&fresh.dynamic.batteries)[0].charge_percent.value(),
            Some(&73.0)
        );
        assert_eq!(
            entries(&fresh.dynamic.batteries)[0].on_ac_power.value(),
            Some(&false)
        );
        let cap = hw
            .capabilities()
            .into_iter()
            .find(|c| c.field == "batteries")
            .expect("cap");
        assert_eq!(cap.level, CapabilityLevel::Partial);
        assert_eq!(cap.source, Source::Sysfs);
        assert_eq!(cap.reason, None);
    }
    #[test]
    fn capacity_failure_is_local_and_never_reuses_old_value() {
        let f = Fixture::new();
        f.supply("a", "Battery");
        f.write("a", "capacity", b"50");
        f.supply("b", "Battery");
        f.write("b", "capacity", b"88");
        let hw = f.hardware(128);
        hw.collect().expect("baseline");
        for bytes in [
            b"".as_slice(),
            b"101",
            b"-1",
            b"NaN",
            b"50%",
            b"1.2",
            b"+1",
            b"12\0",
            b"\xff",
            &[b'x'; 129],
        ] {
            f.write("a", "capacity", bytes);
            let fresh = hw.refresh_dynamic().expect("isolated");
            let list = entries(&fresh.batteries);
            missing(&list[0].charge_percent, ReasonCode::InvalidData);
            assert_eq!(list[1].charge_percent.value(), Some(&88.0));
        }
        std::fs::remove_file(f.0.join("a/capacity")).expect("remove attribute");
        missing(
            &entries(&hw.refresh_dynamic().expect("missing").batteries)[0].charge_percent,
            ReasonCode::NotPresent,
        );
        f.write("a", "capacity", b"0");
        assert_eq!(
            entries(&hw.refresh_dynamic().expect("recovered").batteries)[0]
                .charge_percent
                .value(),
            Some(&0.0)
        );
    }
    #[test]
    fn complete_empty_absent_and_missing_directory_are_distinct() {
        let f = Fixture::new();
        let hw = f.hardware(128);
        let first = hw.collect().expect("empty");
        assert!(entries(&first.dynamic.batteries).is_empty());
        f.supply("bat", "Battery");
        f.write("bat", "present", b"0");
        assert!(entries(&hw.refresh_dynamic().expect("absent").batteries).is_empty());
        f.write("bat", "present", b"1");
        f.write("bat", "capacity", b"42");
        assert_eq!(
            entries(&hw.refresh_dynamic().expect("present").batteries).len(),
            1
        );
        std::fs::remove_dir_all(f.0.join("bat")).expect("remove battery");
        std::fs::remove_dir(&f.0).expect("remove empty root");
        missing(
            &hw.refresh_dynamic().expect("directory missing").batteries,
            ReasonCode::NotPresent,
        );
        std::fs::create_dir(&f.0).expect("restore root");
        assert!(entries(&hw.refresh_dynamic().expect("recovered").batteries).is_empty());
        assert_eq!(
            hw.capabilities()
                .into_iter()
                .find(|c| c.field == "batteries")
                .expect("cap")
                .reason,
            None
        );
    }
    #[test]
    fn unknown_membership_and_excess_entries_never_return_prefix() {
        let f = Fixture::new();
        f.supply("a", "Battery");
        f.write("a", "capacity", b"50");
        f.supply("z", "Battery");
        f.write("z", "capacity", b"51");
        let limited = f.hardware(1);
        missing(
            &limited.collect().expect("limited").dynamic.batteries,
            ReasonCode::InvalidData,
        );
        let hw = f.hardware(128);
        hw.collect().expect("baseline");
        f.write("z", "type", b"\xff");
        missing(
            &hw.refresh_dynamic().expect("unknown type").batteries,
            ReasonCode::InvalidData,
        );
        f.write("z", "type", b"Battery");
        f.write("z", "present", b"2");
        missing(
            &hw.refresh_dynamic().expect("bad present").batteries,
            ReasonCode::InvalidData,
        );
        std::fs::remove_file(f.0.join("z/type")).expect("remove type");
        missing(
            &hw.refresh_dynamic().expect("missing type").batteries,
            ReasonCode::NotPresent,
        );
    }
    #[test]
    fn scan_budget_includes_non_batteries() {
        let f = Fixture::new();
        for i in 0..MAX_SUPPLIES {
            f.supply(&format!("s{i:03}"), "USB");
        }
        let hw = f.hardware(128);
        assert!(entries(&hw.collect().expect("limit boundary").dynamic.batteries).is_empty());
        f.supply("overflow", "Mains");
        missing(
            &hw.refresh_dynamic().expect("scan limit").batteries,
            ReasonCode::InvalidData,
        );
    }
    #[test]
    fn ac_is_proven_by_mains_not_charging_or_usb() {
        let f = Fixture::new();
        f.supply("bat", "Battery");
        f.write("bat", "capacity", b"30");
        f.write("bat", "status", b"Charging");
        f.supply("usb", "USB");
        f.write("usb", "online", b"1");
        let hw = f.hardware(128);
        missing(
            &entries(&hw.collect().expect("collect").dynamic.batteries)[0].on_ac_power,
            ReasonCode::NotPresent,
        );
        f.supply("a-mains", "Mains");
        f.write("a-mains", "online", b"bad");
        f.supply("z-mains", "Mains");
        f.write("z-mains", "online", b"1");
        assert_eq!(
            entries(&hw.refresh_dynamic().expect("known true").batteries)[0]
                .on_ac_power
                .value(),
            Some(&true)
        );
        f.write("z-mains", "online", b"0");
        missing(
            &entries(&hw.refresh_dynamic().expect("unknown ac").batteries)[0].on_ac_power,
            ReasonCode::InvalidData,
        );
        f.write("a-mains", "online", b"0");
        assert_eq!(
            entries(&hw.refresh_dynamic().expect("known false").batteries)[0]
                .on_ac_power
                .value(),
            Some(&false)
        );
    }
    #[test]
    fn non_regular_attributes_are_rejected_without_open() {
        let f = Fixture::new();
        f.supply("bat", "Battery");
        std::fs::create_dir(f.0.join("bat/capacity")).expect("bad attribute");
        let hw = f.hardware(128);
        missing(
            &entries(&hw.collect().expect("collect").dynamic.batteries)[0].charge_percent,
            ReasonCode::InvalidData,
        );
    }
    #[cfg(unix)]
    #[test]
    fn class_symlink_is_allowed_but_attribute_symlink_is_rejected() {
        let f = Fixture::new();
        let devices = Fixture::new();
        devices.supply("device", "Battery");
        devices.write("device", "capacity", b"67");
        std::os::unix::fs::symlink(devices.0.join("device"), f.0.join("BAT0")).expect("class link");
        let hw = f.hardware(128);
        assert_eq!(
            entries(&hw.collect().expect("class").dynamic.batteries)[0]
                .charge_percent
                .value(),
            Some(&67.0)
        );
        devices.write("device", "other", b"90");
        std::fs::remove_file(devices.0.join("device/capacity")).expect("replace");
        std::os::unix::fs::symlink("other", devices.0.join("device/capacity"))
            .expect("attribute link");
        missing(
            &entries(&hw.refresh_dynamic().expect("reject").batteries)[0].charge_percent,
            ReasonCode::InvalidData,
        );
    }
}
