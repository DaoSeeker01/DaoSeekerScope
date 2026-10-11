#![no_main]
mod common;
use daoseeker_scope::{ReasonCode, Source, Timestamp};
use daoseeker_scope_linux::fuzzing::cpu_stat;

libfuzzer_sys::fuzz_target!(|data: &[u8]| {
    let samples = cpu_stat(data);
    assert!((6..=21).contains(&samples.len()));
    for item in &samples {
        common::observed(item, Source::Procfs);
        if let Some(value) = item.value() {
            assert!(value.is_finite() && (0.0..=100.0).contains(value));
        }
    }
    assert!(samples[0].value().is_none());
    let suffix = &samples[samples.len() - 5..];
    assert_eq!(suffix[0].reason(), Some(ReasonCode::InvalidData));
    assert_eq!(suffix[1].reason(), Some(ReasonCode::TemporarilyUnavailable));
    for (index, value) in [50.0, 0.0, 100.0].into_iter().enumerate() {
        assert_eq!(suffix[index + 2].value(), Some(&value));
        assert_eq!(
            suffix[index + 2].observed_at(),
            Some(Timestamp(index as u64 + 102))
        );
    }
});
