//! Regression checks for shared fuzz harness contracts; no runtime API.
#[cfg(test)]
#[path = "../fuzz_targets/common.rs"]
mod common;

#[cfg(test)]
mod tests {
    use super::common;
    use daoseeker_scope::{Observed, Source, Timestamp};
    use daoseeker_scope_macos::fuzzing::network_route;

    #[test]
    fn windows_registry_utf16_uses_win32_and_rejects_placeholder() {
        let value = daoseeker_scope_windows::fuzzing::bios_registry_text(include_bytes!(
            "../corpus/dmi_text/windows_registry_utf16"
        ));
        common::observed(&value, Source::Win32);
        assert_eq!(value.value().map(String::as_str), Some("观微 Board 🦀"));
        let invalid = daoseeker_scope_windows::fuzzing::bios_registry_text(include_bytes!(
            "../corpus/dmi_text/windows_registry_placeholder"
        ));
        common::observed(&invalid, Source::Win32);
        assert!(invalid.value().is_none());
    }

    #[test]
    fn windows_group_wire_seed_uses_win32_without_native_io() {
        let value = daoseeker_scope_windows::fuzzing::cpu_group_topology(include_bytes!(
            "../corpus/windows_cpu_groups/valid_group_table"
        ));
        common::observed(&value, Source::Win32);
        assert_eq!(value.value(), Some(&(2, 3)));
    }

    #[test]
    fn empty_and_binary_darwin_routes_use_sysctl_in_shared_fuzz_checks() {
        for data in [
            &[][..],
            &include_bytes!("../corpus/macos_network/valid")[..],
        ] {
            let networks = network_route(data, 128);
            common::observed(&networks, Source::Sysctl);
            for entry in networks.value().expect("successful route table") {
                common::observed(&entry.interface_name, Source::Sysctl);
                common::observed(&entry.received_bytes, Source::Sysctl);
                common::observed(&entry.transmitted_bytes, Source::Sysctl);
            }
        }
        let procfs = Observed::available(0u64, Source::Procfs, Timestamp(0));
        common::observed(&procfs, Source::Procfs);
    }

    #[test]
    #[should_panic(expected = "assertion `left == right` failed")]
    fn shared_fuzz_check_still_rejects_the_wrong_source() {
        // Actual empty libFuzzer reproducer from CI 38095804975.
        common::observed(&network_route(&[], 128), Source::Procfs);
    }
}
