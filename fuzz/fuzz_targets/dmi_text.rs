#![no_main]
libfuzzer_sys::fuzz_target!(|data: &[u8]| {
    let observation = daoseeker_scope_linux::parse_dmi_text(data);
    if let Some(value) = observation.value() {
        assert!(!value.is_empty() && value.len() <= 4096);
        assert!(!value.chars().any(char::is_control));
    }
});
