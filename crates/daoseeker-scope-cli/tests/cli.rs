use std::process::Command;
fn cli(args: &[&str]) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_dscope"))
        .args(args)
        .output()
        .expect("cli")
}

#[test]
fn display_json_keeps_real_states_without_fabricating_resolution() {
    let output = cli(&["--json"]);
    assert!(output.status.success() && output.stderr.is_empty());
    let snapshot = daoseeker_scope::from_json(&output.stdout).expect("snapshot");
    let displays = snapshot.static_info.displays;
    #[cfg(target_os = "windows")]
    if displays.availability() != daoseeker_scope::Availability::Unsupported {
        assert_eq!(displays.source(), daoseeker_scope::Source::Win32);
        if let Some(entries) = displays.value() {
            for entry in entries {
                assert_eq!(entry.name.source(), daoseeker_scope::Source::Win32);
                assert_eq!(entry.width_pixels.source(), daoseeker_scope::Source::Win32);
                assert_eq!(entry.height_pixels.source(), daoseeker_scope::Source::Win32);
                match (entry.width_pixels.value(), entry.height_pixels.value()) {
                    (Some(w), Some(h)) => assert!(*w > 0 && *h > 0),
                    (None, None) => assert!(entry.width_pixels.reason().is_some()),
                    _ => panic!("partial dimension pair"),
                }
            }
        } else {
            assert!(displays.reason().is_some() && displays.observed_at().is_none());
        }
    }
    #[cfg(target_os = "linux")]
    {
        assert_eq!(displays.source(), daoseeker_scope::Source::Drm);
        if let Some(entries) = displays.value() {
            for entry in entries {
                assert_eq!(
                    entry.name.reason(),
                    Some(daoseeker_scope::ReasonCode::PrivacyRedacted)
                );
                assert_eq!(
                    entry.width_pixels.availability(),
                    daoseeker_scope::Availability::Unsupported
                );
                assert!(
                    entry.width_pixels.value().is_none() && entry.height_pixels.value().is_none()
                );
            }
        } else {
            assert!(displays.reason().is_some());
        }
    }
    #[cfg(target_os = "macos")]
    {
        assert!(
            displays.source() == daoseeker_scope::Source::AppleApi
                || (displays.availability() == daoseeker_scope::Availability::Unsupported
                    && displays.source() == daoseeker_scope::Source::Custom)
        );
        if let Some(entries) = displays.value() {
            for entry in entries {
                assert_eq!(
                    entry.name.availability(),
                    daoseeker_scope::Availability::Unsupported
                );
                assert_eq!(entry.name.source(), daoseeker_scope::Source::AppleApi);
                assert_eq!(
                    entry.width_pixels.source(),
                    daoseeker_scope::Source::AppleApi
                );
                assert_eq!(
                    entry.height_pixels.source(),
                    daoseeker_scope::Source::AppleApi
                );
                match (entry.width_pixels.value(), entry.height_pixels.value()) {
                    (Some(w), Some(h)) => assert!(*w > 0 && *h > 0),
                    (None, None) => assert!(entry.width_pixels.reason().is_some()),
                    _ => panic!("partial dimension pair"),
                }
            }
        } else {
            assert!(displays.reason().is_some());
        }
    }
}

#[test]
fn every_text_command_keeps_metadata_and_json_roundtrips() {
    for command in [
        "cpu",
        "memory",
        "gpu",
        "disk",
        "display",
        "network",
        "battery",
        "sensors",
        "system",
        "capabilities",
    ] {
        let output = cli(&[command]);
        assert!(output.status.success(), "{command}");
        assert!(output.stderr.is_empty(), "{command}");
        let text = String::from_utf8(output.stdout).expect("UTF-8");
        assert!(!text.is_empty() && text.ends_with('\n'), "{command}");
        for line in text.lines().filter(|line| line.contains(": ")) {
            // Values, empty collections and missing states all carry provenance.
            assert!(
                line.ends_with(')') && line.contains(" ("),
                "{command}: {line}"
            );
        }
        let json = cli(&[command, "--json"]);
        assert!(json.status.success() && json.stderr.is_empty(), "{command}");
        assert!(
            daoseeker_scope::from_json(&json.stdout).is_ok(),
            "{command}"
        );
        // The two processes may see different values or device membership.
    }
}

#[test]
fn network_text_and_json_preserve_states_and_privacy() {
    let text = cli(&["network"]);
    let json = cli(&["network", "--json"]);
    assert!(text.status.success() && json.status.success());
    assert!(text.stderr.is_empty() && json.stderr.is_empty());
    let snapshot = daoseeker_scope::from_json(&json.stdout).expect("snapshot");
    let text = String::from_utf8(text.stdout).expect("text");
    if let Some(entries) = snapshot.dynamic.networks.value() {
        for entry in entries {
            assert!(entry.interface_name.value().is_none());
            assert_eq!(
                entry.interface_name.reason(),
                Some(daoseeker_scope::ReasonCode::PrivacyRedacted)
            );
        }
        if !entries.is_empty() {
            assert!(text.contains("Received cumulative bytes"));
            assert!(text.contains("PrivacyRedacted"));
        }
    } else {
        assert!(text.contains(&format!("{:?}", snapshot.dynamic.networks.availability())));
    }
}
#[test]
fn storage_text_and_json_preserve_capacity_states_and_privacy() {
    let text = cli(&["disk"]);
    let json = cli(&["disk", "--json"]);
    assert!(text.status.success() && json.status.success());
    assert!(text.stderr.is_empty() && json.stderr.is_empty());
    let snapshot = daoseeker_scope::from_json(&json.stdout).expect("snapshot");
    let text = String::from_utf8(text.stdout).expect("text");
    assert!(text.starts_with("Storage: "));
    // Separate processes can see different membership; do not compare counts
    // or capacities across snapshots during real hotplug.
    if let Some(entries) = snapshot.static_info.storage.value() {
        for entry in entries {
            assert!(entry.name.value().is_none());
            assert_eq!(
                entry.name.reason(),
                Some(daoseeker_scope::ReasonCode::PrivacyRedacted)
            );
        }
    }
    if text.contains("Storage entry ") {
        assert!(text.contains("Capacity: ") && text.contains("PrivacyRedacted"));
        assert!(text.contains("capacities may overlap"));
    }
}
#[test]
fn help_version_and_usage_codes() {
    let help = cli(&["--help"]);
    assert!(help.status.success());
    assert!(String::from_utf8_lossy(&help.stdout).contains("display"));
    assert!(cli(&["--version"]).status.success());
    assert_eq!(cli(&["bad"]).status.code(), Some(2));
    assert_eq!(cli(&["--include-sensitive"]).status.code(), Some(2));
    assert_eq!(cli(&["--json", "--json"]).status.code(), Some(2));
}

#[test]
fn display_text_uses_public_snapshot_states_and_explicit_sensitive_warning() {
    let output = cli(&["display"]);
    assert!(output.status.success() && output.stderr.is_empty());
    let text = String::from_utf8(output.stdout).expect("text");
    assert!(text.starts_with("Displays: "));
    if text.contains("Display entry ") {
        assert!(text.contains("Name: ") && text.contains("physical monitor count"));
        assert!(text.contains("panel-native resolution"));
        #[cfg(target_os = "windows")]
        assert!(text.contains("Signal width pixels: ") && text.contains("Signal height pixels: "));
        #[cfg(target_os = "macos")]
        assert!(text.contains("Mode width pixels: ") && text.contains("Mode height pixels: "));
        #[cfg(target_os = "linux")]
        {
            assert!(text.contains("Name: Restricted (Sysfs, PrivacyRedacted)"));
            assert!(text.contains("Width pixels: Unsupported (Drm, NotSupported)"));
        }
    }
    // New processes can observe topology changes; never compare their counts.
    let output = cli(&["display", "--json"]);
    assert!(output.status.success() && output.stderr.is_empty());
    assert!(daoseeker_scope::from_json(&output.stdout).is_ok());
    let denied = cli(&["display", "--include-sensitive"]);
    assert_eq!(denied.status.code(), Some(2));
    assert!(denied.stdout.is_empty());
    let authorized = cli(&["display", "--include-sensitive", "--authorized"]);
    assert!(authorized.status.success());
    assert!(String::from_utf8_lossy(&authorized.stderr).contains("Warning"));
}
#[test]
fn json_is_full_roundtrippable_and_redacted() {
    let capabilities = cli(&["capabilities", "--json"]);
    assert!(capabilities.status.success());
    assert!(daoseeker_scope::from_json(&capabilities.stdout).is_ok());
    let output = cli(&["cpu", "--json"]);
    assert!(output.status.success());
    let snapshot = daoseeker_scope::from_json(&output.stdout).expect("json");
    assert!(
        snapshot
            .dynamic
            .cpu_usage_percent
            .value()
            .is_some_and(|value| value.is_finite() && (0.0..=100.0).contains(value))
    );
    assert_eq!(
        snapshot.static_info.system.device.serial_number.reason(),
        Some(daoseeker_scope::ReasonCode::PrivacyRedacted)
    );
    assert!(output.stderr.is_empty());
}

#[test]
fn closed_output_pipe_does_not_panic() {
    use std::process::Stdio;
    let mut child = Command::new(env!("CARGO_BIN_EXE_dscope"))
        .args(["cpu", "--json"])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("cli");
    drop(child.stdout.take());
    let output = child.wait_with_output().expect("wait");
    assert!(output.status.success());
    assert!(output.stderr.is_empty());
}
#[test]
fn unsupported_is_visible_and_sensitive_warning_is_stderr() {
    let output = cli(&["gpu"]);
    assert!(output.status.success());
    #[cfg(not(any(target_os = "windows", target_os = "linux", target_os = "macos")))]
    assert!(String::from_utf8_lossy(&output.stdout).contains("Unsupported"));
    #[cfg(target_os = "macos")]
    {
        let snapshot = cli(&["gpu", "--json"]);
        assert!(snapshot.status.success());
        let snapshot = daoseeker_scope::from_json(&snapshot.stdout).expect("snapshot");
        let gpus = snapshot.static_info.gpus;
        assert_eq!(gpus.source(), daoseeker_scope::Source::AppleApi);
        for entry in gpus.value().expect("Metal enumeration") {
            assert_eq!(entry.name.source(), daoseeker_scope::Source::AppleApi);
            let memory = &entry.dedicated_memory_bytes;
            assert_eq!(memory.source(), daoseeker_scope::Source::AppleApi);
            assert!(memory.value().is_none() && memory.observed_at().is_none());
            assert!(matches!(
                memory.availability(),
                daoseeker_scope::Availability::NotApplicable
                    | daoseeker_scope::Availability::Unsupported
            ));
        }
        assert!(String::from_utf8_lossy(&output.stdout).contains("(AppleApi)"));
    }
    #[cfg(target_os = "linux")]
    {
        let snapshot = cli(&["gpu", "--json"]);
        assert!(snapshot.status.success());
        let snapshot = daoseeker_scope::from_json(&snapshot.stdout).expect("snapshot");
        let gpus = snapshot.static_info.gpus;
        assert_eq!(gpus.source(), daoseeker_scope::Source::Drm);
        if let Some(entries) = gpus.value() {
            assert!(String::from_utf8_lossy(&output.stdout).contains("(Drm)"));
            for entry in entries {
                assert_eq!(
                    entry.dedicated_memory_bytes.availability(),
                    daoseeker_scope::Availability::Unsupported
                );
                assert!(entry.dedicated_memory_bytes.value().is_none());
            }
        } else {
            assert!(gpus.reason().is_some());
        }
    }
    #[cfg(target_os = "windows")]
    {
        let snapshot = cli(&["gpu", "--json"]);
        assert!(snapshot.status.success());
        let snapshot = daoseeker_scope::from_json(&snapshot.stdout).expect("snapshot");
        let gpus = snapshot.static_info.gpus;
        if let Some(entries) = gpus.value() {
            assert_eq!(gpus.source(), daoseeker_scope::Source::Dxgi);
            assert!(String::from_utf8_lossy(&output.stdout).contains("(Dxgi)"));
            for entry in entries {
                assert_eq!(
                    entry.dedicated_memory_bytes.source(),
                    daoseeker_scope::Source::Dxgi
                );
                assert!(entry.dedicated_memory_bytes.value().is_some());
            }
        } else {
            assert!(gpus.reason().is_some());
            assert!(String::from_utf8_lossy(&output.stdout).contains("GPU: "));
        }
    }
    let output = cli(&["--json", "--include-sensitive", "--authorized"]);
    assert!(output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("Warning"));
    assert!(daoseeker_scope::from_json(&output.stdout).is_ok());
}
