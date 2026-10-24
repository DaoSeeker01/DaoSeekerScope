#![no_main]
mod common;
use daoseeker_scope::Source;
use daoseeker_scope_windows::fuzzing::cpu_group_topology;

libfuzzer_sys::fuzz_target!(|data: &[u8]| {
    let observed = cpu_group_topology(data);
    common::observed(&observed, Source::Win32);
    assert_eq!(observed, cpu_group_topology(data));
    if let Some((groups, processors)) = observed.value() {
        assert!((1..=16).contains(groups));
        assert!((u32::from(*groups)..=64 * u32::from(*groups)).contains(processors));
    }
    if data.len() > 1024 {
        assert!(observed.value().is_none());
    }
});
