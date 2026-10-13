use daoseeker_scope::*;
use daoseeker_scope_cli::{Command, Invocation, MAX_ARGUMENTS, parse_args};
use std::{
    fmt::{Display, Write as FmtWrite},
    io::{self, Write},
    process::ExitCode,
    time::Duration,
};
const HELP: &str = "寻道者观微 DaoSeekerScope\nUsage: dscope [cpu|memory|gpu|disk|network|battery|sensors|system|capabilities] [--json]\n  --include-sensitive --authorized   Explicit sensitive access (caller authorization)\n  cpu samples usage over at least 300 ms\n  disk shows whole-device capacity in bytes and IEC units\n  --version  --help\nExit codes: 0 success, 2 usage, 3 collection error\nUnavailable fields are successful structured results, not process errors.";
fn show<T: Display>(output: &mut String, label: &str, value: &Observed<T>) {
    if let Some(observed) = value.value() {
        writeln!(output, "{label}: {observed} ({:?})", value.source()).expect("string formatting");
    } else {
        writeln!(
            output,
            "{label}: {:?} ({:?}, {:?})",
            value.availability(),
            value.source(),
            value.reason()
        )
        .expect("string formatting");
    }
}
fn list<T>(output: &mut String, label: &str, value: &Observed<Vec<T>>) {
    match value.value() {
        Some(items) => writeln!(
            output,
            "{label}: {} entries ({:?})",
            items.len(),
            value.source()
        )
        .expect("string formatting"),
        None => writeln!(
            output,
            "{label}: {:?} ({:?}, {:?})",
            value.availability(),
            value.source(),
            value.reason()
        )
        .expect("string formatting"),
    }
}
fn readable_bytes(bytes: u64) -> String {
    const UNITS: [&str; 7] = ["B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB"];
    if bytes < 1024 {
        return format!("{bytes} B");
    }
    let mut unit = 0;
    let mut divisor = 1u64;
    while unit + 1 < UNITS.len() && bytes / divisor >= 1024 {
        divisor *= 1024;
        unit += 1;
    }
    // Integer rounding preserves exact input even above f64's integer precision.
    // u128 accommodates u64::MAX * 100; the raw byte count is always printed too.
    let hundredths = (u128::from(bytes) * 100 + u128::from(divisor) / 2) / u128::from(divisor);
    format!(
        "{}.{:02} {}",
        hundredths / 100,
        hundredths % 100,
        UNITS[unit]
    )
}
fn storage(output: &mut String, observed: &Observed<Vec<StorageInfo>>) {
    list(output, "Storage", observed);
    let Some(entries) = observed.value() else {
        return;
    };
    if entries.is_empty() {
        writeln!(output, "No storage entries visible to this backend.").expect("string formatting");
        return;
    }
    for (index, entry) in entries.iter().enumerate() {
        writeln!(output, "Storage entry {}", index + 1).expect("string formatting");
        show(output, "Name", &entry.name);
        if let Some(bytes) = entry.capacity_bytes.value() {
            writeln!(
                output,
                "Capacity: {} ({bytes} bytes; {:?})",
                readable_bytes(*bytes),
                entry.capacity_bytes.source()
            )
            .expect("string formatting");
        } else {
            show(output, "Capacity", &entry.capacity_bytes);
        }
    }
    writeln!(
        output,
        "Entries are OS objects, including virtual devices; capacities may overlap."
    )
    .expect("string formatting");
}
fn run(args: &[String]) -> Result<String, (u8, String)> {
    let mut output = String::new();
    let (command, json, options) = match parse_args(args).map_err(|text| (2, text.to_owned()))? {
        Invocation::Help => {
            writeln!(output, "{HELP}").expect("string formatting");
            return Ok(output);
        }
        Invocation::Version => {
            writeln!(output, "dscope {}", env!("CARGO_PKG_VERSION")).expect("string formatting");
            return Ok(output);
        }
        Invocation::Collect {
            command,
            json,
            options,
        } => (command, json, options),
    };
    if options.privacy.include_sensitive {
        let _ = writeln!(
            io::stderr().lock(),
            "Warning: sensitive identifiers requested; caller asserts authorization."
        );
    }
    let hardware = Hardware::with_options(options).map_err(|e| (3, e.to_string()))?;
    let mut snapshot = hardware.collect().map_err(|e| (3, e.to_string()))?;
    if command == Command::Cpu {
        std::thread::sleep(Duration::from_millis(300));
        snapshot = hardware.collect().map_err(|e| (3, e.to_string()))?;
    }
    if json {
        // All data commands emit a full versioned snapshot so every JSON result round-trips.
        writeln!(
            output,
            "{}",
            to_json(&snapshot).map_err(|e| (3, e.to_string()))?
        )
        .expect("string formatting");
        return Ok(output);
    }
    render_text(&mut output, command, &snapshot);
    Ok(output)
}
// Presentation consumes the same public snapshot as JSON; it never collects.
fn render_text(output: &mut String, command: Command, snapshot: &Snapshot) {
    let system = &snapshot.static_info.system;
    match command {
        Command::Cpu => {
            show(output, "CPU", &system.cpu.brand);
            show(output, "Architecture", &system.cpu.architecture);
            show(output, "Logical CPUs", &system.cpu.logical_count);
            show(output, "Physical cores", &system.cpu.physical_count);
            show(output, "Usage percent", &snapshot.dynamic.cpu_usage_percent);
        }
        Command::Memory => {
            show(
                output,
                "OS usable total bytes",
                &system.memory.total_usable_bytes,
            );
            show(output, "Installed bytes", &system.memory.installed_bytes);
            show(
                output,
                "Available bytes",
                &snapshot.dynamic.memory_available_bytes,
            );
        }
        Command::Gpu => {
            list(output, "GPU", &snapshot.static_info.gpus);
            if let Some(items) = snapshot.static_info.gpus.value() {
                for (index, gpu) in items.iter().enumerate() {
                    writeln!(output, "GPU entry {}", index + 1).expect("string formatting");
                    show(output, "Name", &gpu.name);
                    show(
                        output,
                        "Dedicated memory bytes",
                        &gpu.dedicated_memory_bytes,
                    );
                }
            }
        }
        Command::Disk => storage(output, &snapshot.static_info.storage),
        Command::Network => {
            list(output, "Network", &snapshot.dynamic.networks);
            if let Some(items) = snapshot.dynamic.networks.value() {
                for (index, network) in items.iter().enumerate() {
                    writeln!(output, "Interface entry {}", index + 1).expect("string formatting");
                    show(output, "Name", &network.interface_name);
                    show(output, "Received cumulative bytes", &network.received_bytes);
                    show(
                        output,
                        "Transmitted cumulative bytes",
                        &network.transmitted_bytes,
                    );
                }
            }
        }
        Command::Battery => {
            list(output, "Batteries", &snapshot.dynamic.batteries);
            if let Some(items) = snapshot.dynamic.batteries.value() {
                for (index, battery) in items.iter().enumerate() {
                    writeln!(output, "Battery entry {}", index + 1).expect("string formatting");
                    show(output, "Charge percent", &battery.charge_percent);
                    show(output, "AC power", &battery.on_ac_power);
                }
            }
        }
        Command::Sensors => {
            list(output, "Sensors", &snapshot.dynamic.sensors);
            if let Some(items) = snapshot.dynamic.sensors.value() {
                for (index, sensor) in items.iter().enumerate() {
                    writeln!(output, "Sensor entry {}", index + 1).expect("string formatting");
                    show(output, "Label", &sensor.label);
                    show(output, "Temperature Celsius", &sensor.temperature_celsius);
                }
            }
        }
        Command::Capabilities => {
            for cap in &snapshot.capabilities {
                match cap.reason {
                    Some(reason) => writeln!(
                        output,
                        "{}: {:?} ({:?}, {reason:?})",
                        cap.field, cap.level, cap.source
                    ),
                    None => writeln!(output, "{}: {:?} ({:?})", cap.field, cap.level, cap.source),
                }
                .expect("string formatting");
            }
        }
        Command::System => {
            show(output, "OS", &system.os.name);
            show(output, "OS version", &system.os.version);
            show(output, "Kernel", &system.os.kernel_version);
            show(output, "CPU", &system.cpu.brand);
            show(
                output,
                "OS usable total bytes",
                &system.memory.total_usable_bytes,
            );
            show(output, "Device model", &system.device.model);
            show(
                output,
                "Uptime seconds",
                &snapshot.dynamic.runtime.uptime_seconds,
            );
        }
    }
}
fn main() -> ExitCode {
    let args = std::env::args_os()
        .skip(1)
        .take(MAX_ARGUMENTS + 1)
        .map(|arg| arg.into_string())
        .collect::<Result<Vec<_>, _>>();
    let result = args
        .map_err(|_| (2, "invalid argument encoding".to_owned()))
        .and_then(|args| run(&args));
    match result {
        Ok(output) => match io::stdout().lock().write_all(output.as_bytes()) {
            Ok(()) => ExitCode::SUCCESS,
            Err(error) if error.kind() == io::ErrorKind::BrokenPipe => ExitCode::SUCCESS,
            Err(_) => {
                let _ = writeln!(io::stderr().lock(), "dscope: output failed");
                ExitCode::from(3)
            }
        },
        Err((code, text)) => {
            let _ = writeln!(io::stderr().lock(), "dscope: {text}");
            ExitCode::from(code)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> Snapshot {
        // Self-contained so tests also compile from an extracted .crate archive.
        let mut snapshot = from_json(br#"{"schema_version":1,"collected_at":1,"static_info":{},"dynamic":{},"capabilities":[],"conflicts":[],"issues":[]}"#).expect("fixture");
        snapshot.static_info.system.cpu.brand =
            Observed::available("Fixture CPU".into(), Source::Custom, Timestamp(1));
        snapshot.static_info.system.cpu.logical_count =
            Observed::available(4, Source::Custom, Timestamp(1));
        snapshot.static_info.system.memory.total_usable_bytes =
            Observed::available(8589934592, Source::Custom, Timestamp(1));
        snapshot
    }
    fn text(command: Command, snapshot: &Snapshot) -> String {
        let mut output = String::new();
        render_text(&mut output, command, snapshot);
        output
    }
    #[test]
    fn scalar_sources_and_missing_reasons_survive_presentation() {
        let mut snapshot = fixture();
        snapshot.dynamic.cpu_usage_percent = Observed::available(0.0, Source::Procfs, Timestamp(2));
        snapshot.dynamic.memory_available_bytes =
            Observed::available(0, Source::Sysfs, Timestamp(2));
        snapshot.static_info.system.device.model =
            Observed::restricted(Source::Wmi, ReasonCode::PermissionDenied);
        snapshot.dynamic.runtime.uptime_seconds =
            Observed::unavailable(Source::Procfs, ReasonCode::InvalidData);
        let cpu = text(Command::Cpu, &snapshot);
        assert!(cpu.contains("CPU: Fixture CPU (Custom)"));
        assert!(cpu.contains("Logical CPUs: 4 (Custom)"));
        assert!(cpu.contains("Usage percent: 0 (Procfs)"));
        let memory = text(Command::Memory, &snapshot);
        assert!(memory.contains("Available bytes: 0 (Sysfs)"));
        assert!(memory.contains("Installed bytes: Unsupported (Custom, Some(NotSupported))"));
        let system = text(Command::System, &snapshot);
        assert!(system.contains("Device model: Restricted (Wmi, Some(PermissionDenied))"));
        assert!(system.contains("Uptime seconds: Unavailable (Procfs, Some(InvalidData))"));
        assert!(!system.contains("Uptime seconds: 0"));
    }
    #[test]
    fn numbered_entries_isolate_bad_fields_and_keep_zero_false_and_negative_values() {
        let mut snapshot = fixture();
        let mut battery = BatteryInfo::default();
        battery.charge_percent = Observed::unavailable(Source::Sysfs, ReasonCode::InvalidData);
        battery.on_ac_power = Observed::available(false, Source::Sysfs, Timestamp(2));
        let mut charged = battery.clone();
        charged.charge_percent = Observed::available(0.0, Source::Sysfs, Timestamp(2));
        snapshot.dynamic.batteries =
            Observed::available(vec![battery, charged], Source::Sysfs, Timestamp(2));
        let battery_text = text(Command::Battery, &snapshot);
        assert!(battery_text.contains("Batteries: 2 entries (Sysfs)"));
        assert!(battery_text.contains("Battery entry 1\nCharge percent: Unavailable"));
        assert!(battery_text.contains("Battery entry 2\nCharge percent: 0 (Sysfs)"));
        assert_eq!(battery_text.matches("AC power: false (Sysfs)").count(), 2);
        let mut sensor = SensorInfo::default();
        sensor.label = Observed::restricted(Source::Hwmon, ReasonCode::PrivacyRedacted);
        sensor.temperature_celsius = Observed::unavailable(Source::Hwmon, ReasonCode::InvalidData);
        let mut cold = sensor.clone();
        cold.temperature_celsius = Observed::available(-10.5, Source::Hwmon, Timestamp(2));
        snapshot.dynamic.sensors =
            Observed::available(vec![sensor, cold], Source::Hwmon, Timestamp(2));
        let sensors = text(Command::Sensors, &snapshot);
        assert!(sensors.contains("Sensor entry 1\nLabel: Restricted"));
        assert!(sensors.contains("Sensor entry 2\nLabel: Restricted"));
        assert!(sensors.contains("Temperature Celsius: -10.5 (Hwmon)"));
        let mut gpu = GpuInfo::default();
        gpu.name = Observed::available("Fixture GPU".into(), Source::Custom, Timestamp(1));
        gpu.dedicated_memory_bytes = Observed::available(0, Source::Custom, Timestamp(1));
        snapshot.static_info.gpus = Observed::available(vec![gpu], Source::Custom, Timestamp(1));
        assert!(text(Command::Gpu, &snapshot).contains(
            "GPU: 1 entries (Custom)\nGPU entry 1\nName: Fixture GPU (Custom)\nDedicated memory bytes: 0 (Custom)"
        ));
        // A fixture GPU tests presentation, not a native GPU implementation.
        snapshot.static_info.gpus = Observed::available(vec![], Source::Custom, Timestamp(1));
        assert_eq!(text(Command::Gpu, &snapshot), "GPU: 0 entries (Custom)\n");
        snapshot.dynamic.networks = Observed::restricted(Source::Win32, ReasonCode::Sandbox);
        assert_eq!(
            text(Command::Network, &snapshot),
            "Network: Restricted (Win32, Some(Sandbox))\n"
        );
    }
    #[test]
    fn capabilities_show_each_level_source_and_only_present_reasons() {
        let mut snapshot = fixture();
        snapshot.capabilities.clear();
        for (index, level) in [
            CapabilityLevel::Supported,
            CapabilityLevel::Partial,
            CapabilityLevel::Unsupported,
            CapabilityLevel::Restricted,
            CapabilityLevel::NotApplicable,
        ]
        .into_iter()
        .enumerate()
        {
            let mut cap = Capability::new(&format!("field_{index}"), level, Source::Custom);
            if index != 0 {
                cap.reason = Some(ReasonCode::PermissionDenied);
            }
            snapshot.capabilities.push(cap);
        }
        let output = text(Command::Capabilities, &snapshot);
        assert!(output.contains("field_0: Supported (Custom)\n"));
        for (index, level) in ["Partial", "Unsupported", "Restricted", "NotApplicable"]
            .into_iter()
            .enumerate()
        {
            assert!(output.contains(&format!(
                "field_{}: {level} (Custom, PermissionDenied)\n",
                index + 1
            )));
        }
        assert!(!output.contains("None") && !output.contains("Some("));
    }
    fn entry(capacity: Observed<u64>) -> StorageInfo {
        let mut entry = StorageInfo::default();
        entry.name = Observed::restricted(Source::Win32, ReasonCode::PrivacyRedacted);
        entry.capacity_bytes = capacity;
        entry
    }
    fn render(observed: Observed<Vec<StorageInfo>>) -> String {
        let mut output = String::new();
        storage(&mut output, &observed);
        output
    }
    #[test]
    fn exact_bytes_and_iec_rounding_cover_zero_boundaries_and_u64_max() {
        for (bytes, expected) in [
            (0, "0 B"),
            (1023, "1023 B"),
            (1024, "1.00 KiB"),
            (1536, "1.50 KiB"),
            (1048575, "1024.00 KiB"),
            (1048576, "1.00 MiB"),
            (1000204886016, "931.51 GiB"),
            (u64::MAX, "16.00 EiB"),
        ] {
            let output = render(Observed::available(
                vec![entry(Observed::available(
                    bytes,
                    Source::Win32,
                    Timestamp(1),
                ))],
                Source::Setupapi,
                Timestamp(1),
            ));
            assert!(
                output.contains(&format!("Capacity: {expected} ({bytes} bytes; Win32)")),
                "{output}"
            );
            assert!(output.contains("Name: Restricted (Win32, Some(PrivacyRedacted))"));
            assert!(!output.contains("PhysicalDrive"));
        }
        for unit in ["GiB", "TiB", "PiB", "EiB"] {
            let power = match unit {
                "GiB" => 30,
                "TiB" => 40,
                "PiB" => 50,
                _ => 60,
            };
            assert_eq!(readable_bytes(1u64 << power), format!("1.00 {unit}"));
        }
    }
    #[test]
    fn empty_and_each_missing_state_never_gain_a_capacity_or_entry() {
        let empty = render(Observed::available(vec![], Source::Iokit, Timestamp(1)));
        assert_eq!(
            empty,
            "Storage: 0 entries (Iokit)\nNo storage entries visible to this backend.\n"
        );
        for (availability, reason) in [
            (Availability::Unavailable, ReasonCode::NotPresent),
            (Availability::Restricted, ReasonCode::PermissionDenied),
            (Availability::Unsupported, ReasonCode::NotSupported),
            (Availability::NotApplicable, ReasonCode::NotPresent),
        ] {
            let output =
                render(Observed::missing(availability, Source::Iokit, reason).expect("missing"));
            assert!(output.contains(&format!(
                "Storage: {availability:?} (Iokit, Some({reason:?}))"
            )));
            assert!(
                !output.contains("Storage entry")
                    && !output.contains("0 entries")
                    && !output.contains("Capacity:")
            );
        }
    }
    #[test]
    fn field_failures_preserve_other_capacities_and_authorized_names() {
        let mut named = entry(Observed::available(4096, Source::Sysfs, Timestamp(1)));
        named.name = Observed::available("测试 disk7".to_owned(), Source::Sysfs, Timestamp(1));
        let output = render(Observed::available(
            vec![
                entry(Observed::unavailable(
                    Source::Sysfs,
                    ReasonCode::InvalidData,
                )),
                entry(Observed::restricted(
                    Source::Sysfs,
                    ReasonCode::PermissionDenied,
                )),
                named,
            ],
            Source::Sysfs,
            Timestamp(1),
        ));
        assert!(output.contains("Storage: 3 entries (Sysfs)"));
        assert!(output.contains("Capacity: Unavailable (Sysfs, Some(InvalidData))"));
        assert!(output.contains("Capacity: Restricted (Sysfs, Some(PermissionDenied))"));
        assert!(output.contains(
            "Storage entry 3\nName: 测试 disk7 (Sysfs)\nCapacity: 4.00 KiB (4096 bytes; Sysfs)"
        ));
        assert!(!output.contains("Capacity: 0"));
        assert!(output.contains("capacities may overlap"));
    }
}
