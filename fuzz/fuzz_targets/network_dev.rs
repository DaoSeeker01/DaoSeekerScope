#![no_main]
mod common;
use daoseeker_scope::{ReasonCode, Source};
use daoseeker_scope_linux::fuzzing::network_dev;

libfuzzer_sys::fuzz_target!(|data: &[u8]| {
    for limit in [1, 128, 1024] {
        let redacted = network_dev(data, limit, false);
        let named = network_dev(data, limit, true);
        common::observed(&redacted, Source::Procfs);
        common::observed(&named, Source::Procfs);
        assert_eq!(network_dev(data, limit, false), redacted);
        assert_eq!(redacted.source(), Source::Procfs);
        assert_eq!(redacted.availability(), named.availability());
        if let Some(entries) = redacted.value() {
            assert!(entries.len() <= limit);
            let named_entries = named.value().expect("same collection");
            assert_eq!(entries.len(), named_entries.len());
            for (entry, named_entry) in entries.iter().zip(named_entries) {
                common::observed(&entry.interface_name, Source::Procfs);
                common::observed(&entry.received_bytes, Source::Procfs);
                common::observed(&entry.transmitted_bytes, Source::Procfs);
                assert!(entry.interface_name.value().is_none());
                assert_eq!(
                    entry.interface_name.reason(),
                    Some(ReasonCode::PrivacyRedacted)
                );
                assert_eq!(entry.received_bytes, named_entry.received_bytes);
                assert_eq!(entry.transmitted_bytes, named_entry.transmitted_bytes);
                assert!(
                    named_entry
                        .interface_name
                        .value()
                        .is_some_and(|name| !name.is_empty() && name.len() <= 15)
                );
            }
        }
        if data.len() > 512 * 1024 {
            assert_eq!(redacted.reason(), Some(ReasonCode::InvalidData));
        }
    }
});
