#![no_main]
libfuzzer_sys::fuzz_target!(|data: &[u8]| {
    let observation = daoseeker_scope_linux::parse_dmi_text(data);
    if let Some(value) = observation.value() {
        assert!(!value.is_empty() && value.len() <= 4096);
        assert!(!value.chars().any(char::is_control));
    }
    let (amd, nvidia) = daoseeker_scope_linux::fuzzing::gpu_names(data);
    let metal = daoseeker_scope_macos::fuzzing::gpu_name(data);
    let edid = daoseeker_scope_linux::fuzzing::display_name(data);
    for (item, source) in [
        (amd, daoseeker_scope::Source::Sysfs),
        (nvidia, daoseeker_scope::Source::Procfs),
        (metal, daoseeker_scope::Source::AppleApi),
        (edid, daoseeker_scope::Source::Sysfs),
    ] {
        assert_eq!(item.source(), source);
        if let Some(value) = item.value() {
            assert!(!value.is_empty() && value.len() <= 4096);
            assert!(!value.chars().any(char::is_control));
            assert!(item.observed_at().is_some() && item.reason().is_none());
        } else {
            assert!(item.observed_at().is_none() && item.reason().is_some());
        }
    }
});
