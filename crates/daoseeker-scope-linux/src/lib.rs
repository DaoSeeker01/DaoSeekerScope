//! Bounded DMI, procfs, power_supply and hwmon readers; no default identifiers.
#![forbid(unsafe_code)]
use daoseeker_scope_core::*;
use std::io::{self, Read};
use std::path::PathBuf;
mod battery;
mod cpu;
/// Internal, synthetic-input test hooks. No platform reads; no stability promise.
#[cfg(feature = "fuzzing")]
#[doc(hidden)]
pub mod fuzzing;
mod hwmon;
mod procfs;

fn failure<T>(error: io::Error) -> Observed<T> {
    match error.kind() {
        io::ErrorKind::PermissionDenied => {
            Observed::restricted(Source::Sysfs, ReasonCode::PermissionDenied)
        }
        io::ErrorKind::NotFound => Observed::unavailable(Source::Sysfs, ReasonCode::NotPresent),
        _ => Observed::unavailable(Source::Sysfs, ReasonCode::Unknown),
    }
}
fn parse_text(bytes: &[u8], at: Timestamp) -> Observed<String> {
    if bytes.len() > 4096 {
        return Observed::unavailable(Source::Sysfs, ReasonCode::InvalidData);
    }
    match std::str::from_utf8(bytes).map(str::trim) {
        Ok(text)
            if !text.is_empty()
                && !text.chars().any(|c| c.is_control())
                && ![
                    "to be filled by o.e.m.",
                    "default string",
                    "unknown",
                    "none",
                    "not specified",
                ]
                .contains(&text.to_ascii_lowercase().as_str()) =>
        {
            Observed::available(text.to_string(), Source::Sysfs, at)
        }
        _ => Observed::unavailable(Source::Sysfs, ReasonCode::InvalidData),
    }
}
pub struct LinuxBackend {
    root: PathBuf,
    proc_root: PathBuf,
    power_root: PathBuf,
    hwmon_root: PathBuf,
    cpu: cpu::CpuSampler,
    cached_total: Option<u64>,
}
impl Default for LinuxBackend {
    fn default() -> Self {
        Self::new()
    }
}
impl LinuxBackend {
    pub fn new() -> Self {
        Self {
            root: PathBuf::from("/sys/class/dmi/id"),
            proc_root: PathBuf::from("/proc"),
            power_root: PathBuf::from("/sys/class/power_supply"),
            hwmon_root: PathBuf::from("/sys/class/hwmon"),
            cpu: cpu::CpuSampler::default(),
            cached_total: None,
        }
    }
    fn read(&self, file: &str, context: &CollectContext) -> Result<Observed<String>, ScopeError> {
        context.check()?;
        let observation = match std::fs::File::open(self.root.join(file)) {
            Ok(input) => {
                let mut bytes = Vec::with_capacity(4097);
                match input.take(4097).read_to_end(&mut bytes) {
                    Ok(_) => parse_text(&bytes, Timestamp::now()?),
                    Err(error) => failure(error),
                }
            }
            Err(error) => failure(error),
        };
        context.check()?;
        Ok(observation)
    }
}
impl Backend for LinuxBackend {
    fn name(&self) -> &'static str {
        "linux"
    }
    fn capabilities(&self) -> Capabilities {
        let mut capabilities: Capabilities = [
            "system.device.model",
            "system.device.vendor",
            "system.device.serial_number",
            "system.motherboard.vendor",
            "system.motherboard.model",
            "system.firmware.vendor",
            "system.firmware.version",
        ]
        .into_iter()
        .map(|field| Capability::new(field, CapabilityLevel::Supported, Source::Sysfs))
        .collect();
        capabilities.extend(
            [
                "cpu_usage_percent",
                "system.memory.total_usable_bytes",
                "memory_available_bytes",
                "runtime.uptime_seconds",
            ]
            .into_iter()
            .map(|field| Capability::new(field, CapabilityLevel::Supported, Source::Procfs)),
        );
        capabilities.push(Capability::new(
            "batteries",
            CapabilityLevel::Partial,
            Source::Sysfs,
        ));
        capabilities.push(Capability::new(
            "sensors",
            CapabilityLevel::Partial,
            Source::Hwmon,
        ));
        capabilities
    }
    fn collect_static(&mut self, context: &CollectContext) -> Result<StaticSnapshot, ScopeError> {
        let mut result = StaticSnapshot::default();
        context.check()?;
        result.system.memory.total_usable_bytes =
            procfs::memory(&self.proc_root.join("meminfo"), Timestamp::now()?).0;
        self.cached_total = result.system.memory.total_usable_bytes.value().copied();
        context.check()?;
        result.system.device.model = self.read("product_name", context)?;
        result.system.device.vendor = self.read("sys_vendor", context)?;
        result.system.motherboard.vendor = self.read("board_vendor", context)?;
        result.system.motherboard.model = self.read("board_name", context)?;
        result.system.firmware.vendor = self.read("bios_vendor", context)?;
        result.system.firmware.version = self.read("bios_version", context)?;
        result.system.device.serial_number = if context.options.privacy.permits_sensitive() {
            self.read("product_serial", context)?
        } else {
            Observed::restricted(Source::Sysfs, ReasonCode::PrivacyRedacted)
        };
        Ok(result)
    }
    fn refresh_dynamic(&mut self, context: &CollectContext) -> Result<DynamicSnapshot, ScopeError> {
        context.check()?;
        let mut result = DynamicSnapshot::default();
        result.cpu_usage_percent = self.cpu.refresh(Timestamp::now()?);
        context.check()?;
        let (total, available) = procfs::memory(&self.proc_root.join("meminfo"), Timestamp::now()?);
        // MemTotal is read only to validate the fresh dynamic value. The public
        // static total stays cached; hotplug requires a new Hardware instance.
        result.memory_available_bytes = if available.value().is_some()
            && self.cached_total.is_some()
            && total.value().copied() != self.cached_total
        {
            Observed::unavailable(Source::Procfs, ReasonCode::TemporarilyUnavailable)
        } else {
            available
        };
        context.check()?;
        result.runtime.uptime_seconds =
            procfs::uptime(&self.proc_root.join("uptime"), Timestamp::now()?);
        context.check()?;
        result.batteries = battery::collect(&self.power_root, context)?;
        result.sensors = hwmon::collect(&self.hwmon_root, context)?;
        Ok(result)
    }
}
/// Bounded parser entry point for fuzzing; not a platform support claim.
pub fn parse_dmi_text(bytes: &[u8]) -> Observed<String> {
    parse_text(bytes, Timestamp(0))
}
#[cfg(test)]
mod tests {
    use super::*;
    struct Fixture(PathBuf);
    impl Fixture {
        fn new(memory: &[u8]) -> Self {
            let path = std::env::temp_dir().join(format!(
                "dscope-memory-{}-{}",
                std::process::id(),
                Timestamp::now().expect("clock").0
            ));
            std::fs::create_dir(&path).expect("create fixture");
            let fixture = Self(path);
            fixture.memory(memory);
            std::fs::write(fixture.0.join("uptime"), b"123.99 999.99\n").expect("uptime");
            fixture
        }
        fn memory(&self, bytes: &[u8]) {
            std::fs::write(self.0.join("meminfo"), bytes).expect("memory");
        }
        fn hardware(&self) -> Hardware {
            HardwareBuilder::default()
                .with_backend(
                    100,
                    LinuxBackend {
                        root: self.0.join("no-dmi"),
                        proc_root: self.0.clone(),
                        ..LinuxBackend::new()
                    },
                )
                .build()
                .expect("build")
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            std::fs::remove_dir_all(&self.0).expect("remove own fixture");
        }
    }
    #[test]
    fn fresh_failures_recovery_and_total_changes_preserve_static_cache() {
        let fixture = Fixture::new(b"MemTotal: 1024 kB\nMemAvailable: 512 kB\n");
        let hw = fixture.hardware();
        let first = hw.collect().expect("collect");
        assert_eq!(first.dynamic.memory_available_bytes.value(), Some(&524288));
        fixture.memory(b"");
        let bad = hw.refresh_dynamic().expect("field isolation");
        assert_eq!(
            bad.memory_available_bytes.reason(),
            Some(ReasonCode::InvalidData)
        );
        assert!(bad.memory_available_bytes.value().is_none());
        assert!(bad.memory_available_bytes.observed_at().is_none());
        assert_eq!(bad.runtime.uptime_seconds.value(), Some(&123));
        fixture.memory(b"MemTotal: 2048 kB\nMemAvailable: 1536 kB\n");
        assert_eq!(
            hw.refresh_dynamic()
                .expect("refresh")
                .memory_available_bytes
                .reason(),
            Some(ReasonCode::TemporarilyUnavailable)
        );
        fixture.memory(b"MemTotal: 1024 kB\nMemAvailable: 0 kB\n");
        let recovered = hw.collect().expect("recovery");
        assert_eq!(recovered.dynamic.memory_available_bytes.value(), Some(&0));
        assert_eq!(recovered.static_info, first.static_info);
        let cap = recovered
            .capabilities
            .iter()
            .find(|c| c.field == "memory_available_bytes")
            .expect("capability");
        assert_eq!(cap.level, CapabilityLevel::Supported);
        assert_eq!(cap.reason, None);
    }
    #[test]
    fn failed_static_total_remains_cached_while_dynamic_read_can_recover() {
        let fixture = Fixture::new(b"");
        let hw = fixture.hardware();
        let first = hw.collect().expect("collect");
        fixture.memory(b"MemTotal: 1024 kB\nMemAvailable: 512 kB\n");
        std::fs::remove_file(fixture.0.join("uptime")).expect("remove own file");
        let recovered = hw.collect().expect("collect");
        assert_eq!(
            recovered.dynamic.memory_available_bytes.value(),
            Some(&524288)
        );
        assert_eq!(
            recovered.dynamic.runtime.uptime_seconds.reason(),
            Some(ReasonCode::NotPresent)
        );
        assert_eq!(recovered.static_info, first.static_info);
        std::fs::write(fixture.0.join("uptime"), b"0.00 0.00\n").expect("restore");
        assert_eq!(
            hw.refresh_dynamic()
                .expect("refresh")
                .runtime
                .uptime_seconds
                .value(),
            Some(&0)
        );
    }
    #[test]
    fn missing_dmi_degrades_by_field_and_serial_stays_redacted() {
        let backend = LinuxBackend {
            root: std::env::temp_dir().join("dscope-fixture-no-dmi-directory-20261008"),
            ..LinuxBackend::new()
        };
        assert!(!backend.root.exists());
        let hw = HardwareBuilder::default()
            .with_backend(100, backend)
            .build()
            .expect("build");
        let result = hw.collect().expect("collect");
        assert_eq!(
            result.static_info.system.device.model.reason(),
            Some(ReasonCode::NotPresent)
        );
        assert_eq!(
            result.static_info.system.device.serial_number.reason(),
            Some(ReasonCode::PrivacyRedacted)
        );
    }
    #[test]
    fn bad_input_and_placeholder_are_not_values() {
        for data in [b"".as_slice(), b"To Be Filled By O.E.M.", &[0xff], b"a\0b"] {
            assert_eq!(
                parse_dmi_text(data).availability(),
                Availability::Unavailable
            );
        }
        assert!(parse_dmi_text(&vec![b'a'; 4097]).value().is_none());
        assert_eq!(
            parse_dmi_text(b" model\n").value().map(String::as_str),
            Some("model")
        );
    }
    #[test]
    fn permission_and_absence_differ() {
        assert_eq!(
            failure::<String>(io::Error::from(io::ErrorKind::PermissionDenied)).availability(),
            Availability::Restricted
        );
        assert_eq!(
            failure::<String>(io::Error::from(io::ErrorKind::NotFound)).reason(),
            Some(ReasonCode::NotPresent)
        );
    }
}
