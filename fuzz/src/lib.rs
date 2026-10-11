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
