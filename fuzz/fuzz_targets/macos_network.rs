#![no_main]
mod common;
use daoseeker_scope::{ReasonCode, Source};
use daoseeker_scope_macos::fuzzing::network_route;

libfuzzer_sys::fuzz_target!(|data: &[u8]| {
    for limit in [1, 128, 1024] {
        let observed = network_route(data, limit);
        common::observed(&observed, Source::Sysctl);
        assert_eq!(network_route(data, limit), observed);
        assert_eq!(observed.source(), Source::Sysctl);
        if let Some(entries) = observed.value() {
            assert!(entries.len() <= limit);
            for entry in entries {
                common::observed(&entry.interface_name, Source::Sysctl);
                common::observed(&entry.received_bytes, Source::Sysctl);
                common::observed(&entry.transmitted_bytes, Source::Sysctl);
                assert!(entry.interface_name.value().is_none());
                assert_eq!(
                    entry.interface_name.reason(),
                    Some(ReasonCode::PrivacyRedacted)
                );
                assert!(entry.received_bytes.value().is_some());
                assert!(entry.transmitted_bytes.value().is_some());
            }
        }
        if data.len() > 512 * 1024 {
            assert_eq!(observed.reason(), Some(ReasonCode::InvalidData));
        }
    }
});
