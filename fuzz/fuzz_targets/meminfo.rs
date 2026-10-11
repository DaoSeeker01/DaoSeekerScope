#![no_main]
mod common;
use daoseeker_scope::{ReasonCode, Source};
use daoseeker_scope_linux::fuzzing::meminfo;

libfuzzer_sys::fuzz_target!(|data: &[u8]| {
    let (total, available) = meminfo(data);
    common::observed(&total, Source::Procfs);
    common::observed(&available, Source::Procfs);
    assert_eq!(meminfo(data), (total.clone(), available.clone()));
    if data.len() > 4096 {
        assert_eq!(total.reason(), Some(ReasonCode::InvalidData));
        assert_eq!(available.reason(), Some(ReasonCode::InvalidData));
    }
    if let Some(total) = total.value() {
        assert!(*total > 0 && total % 1024 == 0);
        // A damaged available value must not erase an independently valid total.
        let input = format!("MemTotal: {} kB\nMemAvailable: -1 kB\n", total / 1024);
        let (valid_total, bad_available) = meminfo(input.as_bytes());
        assert_eq!(valid_total.value(), Some(total));
        assert_eq!(bad_available.reason(), Some(ReasonCode::InvalidData));
    }
    if let Some(available) = available.value() {
        let total = total.value().expect("available requires valid total");
        assert!(*available <= *total && available % 1024 == 0);
        let input = format!(
            "MemTotal: {} kB\nMemAvailable: {} kB\n",
            total / 1024,
            available / 1024
        );
        let canonical = meminfo(input.as_bytes());
        assert_eq!(canonical.0.value(), Some(total));
        assert_eq!(canonical.1.value(), Some(available));
        let duplicate = input + "MemAvailable: 0 kB\n";
        let (still_valid, rejected) = meminfo(duplicate.as_bytes());
        assert_eq!(still_valid.value(), Some(total));
        assert_eq!(rejected.reason(), Some(ReasonCode::InvalidData));
    }
});
