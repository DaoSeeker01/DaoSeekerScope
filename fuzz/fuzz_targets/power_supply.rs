#![no_main]
use daoseeker_scope::{Availability, ReasonCode, Source, Timestamp};
use daoseeker_scope_linux::fuzzing::power_supply;
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let result = power_supply(data);
    assert_eq!(result, power_supply(data));
    for (value, max) in [(&result.0, 100), (&result.1, 1)] {
        assert_eq!(value.source(), Source::Sysfs);
        if let Some(n) = value.value() {
            assert!(*n <= max);
            assert!(result.2);
            assert_eq!(value.availability(), Availability::Available);
            assert_eq!(value.observed_at(), Some(Timestamp(1)));
            assert_eq!(value.reason(), None);
            let canonical = format!("{n}\n");
            let normalized = power_supply(canonical.as_bytes());
            assert_eq!(normalized.0.value(), Some(n));
            if max == 1 {
                assert_eq!(normalized.1.value(), Some(n));
            }
        } else {
            assert_eq!(value.availability(), Availability::Unavailable);
            assert_eq!(value.observed_at(), None);
            assert_eq!(value.reason(), Some(ReasonCode::InvalidData));
        }
        if data.len() > 128 {
            assert!(value.value().is_none());
            assert!(!result.2);
        }
    }
    if result.1.value().is_some() {
        assert_eq!(result.0.value(), result.1.value());
    }
});
