#[cfg(unix)]
#[test]
fn invalid_os_argument_returns_usage_error_without_panic() {
    use std::os::unix::ffi::OsStringExt;
    let output = std::process::Command::new(env!("CARGO_BIN_EXE_dscope"))
        .arg(std::ffi::OsString::from_vec(vec![0xff]))
        .output()
        .expect("run CLI");
    assert_eq!(output.status.code(), Some(2));
    assert!(output.stdout.is_empty());
    assert_eq!(
        String::from_utf8(output.stderr).expect("stderr"),
        "dscope: invalid argument encoding\n"
    );
}
#[cfg(windows)]
#[test]
fn invalid_os_argument_returns_usage_error_without_panic() {
    use std::os::windows::ffi::OsStringExt;
    let output = std::process::Command::new(env!("CARGO_BIN_EXE_dscope"))
        .arg(std::ffi::OsString::from_wide(&[0xd800]))
        .output()
        .expect("run CLI");
    assert_eq!(output.status.code(), Some(2));
    assert!(output.stdout.is_empty());
    assert_eq!(
        String::from_utf8(output.stderr).expect("stderr"),
        "dscope: invalid argument encoding\n"
    );
}
