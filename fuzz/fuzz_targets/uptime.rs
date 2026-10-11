#![no_main]
mod common;
use daoseeker_scope::{ReasonCode, Source};
use daoseeker_scope_linux::fuzzing::uptime;

libfuzzer_sys::fuzz_target!(|data: &[u8]| {
    let item = uptime(data);
    common::observed(&item, Source::Procfs);
    assert_eq!(uptime(data), item);
    if data.len() > 256 {
        assert_eq!(item.reason(), Some(ReasonCode::InvalidData));
    }
    if let Some(value) = item.value() {
        // Fraction is truncated, not rounded, including u64::MAX and real zero.
        let canonical = format!("{value}.99 999.99\n");
        assert_eq!(uptime(canonical.as_bytes()).value(), Some(value));
        let extra = canonical + " extra";
        assert_eq!(
            uptime(extra.as_bytes()).reason(),
            Some(ReasonCode::InvalidData)
        );
        let damaged = format!("{value}.x 0.00\n");
        assert_eq!(
            uptime(damaged.as_bytes()).reason(),
            Some(ReasonCode::InvalidData)
        );
    }
});
