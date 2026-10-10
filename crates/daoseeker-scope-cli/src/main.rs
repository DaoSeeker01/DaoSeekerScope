use daoseeker_scope::*;
use daoseeker_scope_cli::{Command, Invocation, MAX_ARGUMENTS, parse_args};
use std::{
    fmt::{Display, Write as FmtWrite},
    io::{self, Write},
    process::ExitCode,
    time::Duration,
};
const HELP: &str = "寻道者观微 DaoSeekerScope\nUsage: dscope [cpu|memory|gpu|disk|network|battery|sensors|system|capabilities] [--json]\n  --include-sensitive --authorized   Explicit sensitive access (caller authorization)\n  cpu samples usage over at least 300 ms\n  --version  --help\nExit codes: 0 success, 2 usage, 3 collection error\nUnavailable fields are successful structured results, not process errors.";
fn show<T: Display>(output: &mut String, label: &str, value: &Observed<T>) {
    if let Some(value) = value.value() {
        writeln!(output, "{label}: {value}").expect("string formatting");
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
        Some(items) => {
            writeln!(output, "{label}: {} entries", items.len()).expect("string formatting")
        }
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
    if command == Command::Capabilities {
        let snapshot = hardware.collect().map_err(|e| (3, e.to_string()))?;
        if json {
            writeln!(
                output,
                "{}",
                to_json(&snapshot).map_err(|e| (3, e.to_string()))?
            )
            .expect("string formatting");
        } else {
            for cap in snapshot.capabilities {
                writeln!(output, "{}: {:?} ({:?})", cap.field, cap.level, cap.source)
                    .expect("string formatting");
            }
        }
        return Ok(output);
    }
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
    let system = &snapshot.static_info.system;
    match command {
        Command::Cpu => {
            show(&mut output, "CPU", &system.cpu.brand);
            show(&mut output, "Architecture", &system.cpu.architecture);
            show(&mut output, "Logical CPUs", &system.cpu.logical_count);
            show(&mut output, "Physical cores", &system.cpu.physical_count);
            show(
                &mut output,
                "Usage percent",
                &snapshot.dynamic.cpu_usage_percent,
            );
        }
        Command::Memory => {
            show(
                &mut output,
                "OS usable total bytes",
                &system.memory.total_usable_bytes,
            );
            show(
                &mut output,
                "Installed bytes",
                &system.memory.installed_bytes,
            );
            show(
                &mut output,
                "Available bytes",
                &snapshot.dynamic.memory_available_bytes,
            );
        }
        Command::Gpu => list(&mut output, "GPU", &snapshot.static_info.gpus),
        Command::Disk => list(&mut output, "Storage", &snapshot.static_info.storage),
        Command::Network => list(&mut output, "Network", &snapshot.dynamic.networks),
        Command::Battery => {
            list(&mut output, "Batteries", &snapshot.dynamic.batteries);
            if let Some(items) = snapshot.dynamic.batteries.value() {
                for battery in items {
                    show(&mut output, "Charge percent", &battery.charge_percent);
                    show(&mut output, "AC power", &battery.on_ac_power);
                }
            }
        }
        Command::Sensors => {
            list(&mut output, "Sensors", &snapshot.dynamic.sensors);
            if let Some(items) = snapshot.dynamic.sensors.value() {
                for sensor in items {
                    show(&mut output, "Label", &sensor.label);
                    show(
                        &mut output,
                        "Temperature Celsius",
                        &sensor.temperature_celsius,
                    );
                }
            }
        }
        _ => {
            show(&mut output, "OS", &system.os.name);
            show(&mut output, "OS version", &system.os.version);
            show(&mut output, "Kernel", &system.os.kernel_version);
            show(&mut output, "CPU", &system.cpu.brand);
            show(
                &mut output,
                "OS usable total bytes",
                &system.memory.total_usable_bytes,
            );
            show(&mut output, "Device model", &system.device.model);
            show(
                &mut output,
                "Uptime seconds",
                &snapshot.dynamic.runtime.uptime_seconds,
            );
        }
    }
    Ok(output)
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
