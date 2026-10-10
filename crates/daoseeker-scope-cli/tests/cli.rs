use std::process::Command;
fn cli(args: &[&str]) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_dscope"))
        .args(args)
        .output()
        .expect("cli")
}
#[test]
fn help_version_and_usage_codes() {
    assert!(cli(&["--help"]).status.success());
    assert!(cli(&["--version"]).status.success());
    assert_eq!(cli(&["bad"]).status.code(), Some(2));
    assert_eq!(cli(&["--include-sensitive"]).status.code(), Some(2));
    assert_eq!(cli(&["--json", "--json"]).status.code(), Some(2));
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
    assert!(String::from_utf8_lossy(&output.stdout).contains("Unsupported"));
    let output = cli(&["--json", "--include-sensitive", "--authorized"]);
    assert!(output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("Warning"));
    assert!(daoseeker_scope::from_json(&output.stdout).is_ok());
}
