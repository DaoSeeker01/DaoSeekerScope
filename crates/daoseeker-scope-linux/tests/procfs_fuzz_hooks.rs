#![cfg(feature = "fuzzing")]
use daoseeker_scope_core::{Availability, Observed, ReasonCode, Source};
use daoseeker_scope_linux::fuzzing::{cpu_stat, meminfo, uptime};

fn state<T>(item: &Observed<T>) {
    assert_eq!(item.source(), Source::Procfs);
    assert_eq!(
        item.value().is_some(),
        item.availability() == Availability::Available
    );
    assert_eq!(item.value().is_some(), item.observed_at().is_some());
    assert_eq!(item.value().is_none(), item.reason().is_some());
}

#[test]
fn cpu_frames_cover_fast_polling_io_reset_and_bounded_recovery() {
    let samples = cpu_stat(b"\x02cpu 100 0 0 100\n\0\x01cpu 125 0 0 125\n\0\x02cpu 150 0 0 150\n\0\x06ignored\0\x02cpu 200 0 0 200\n");
    assert_eq!(
        samples[0].reason(),
        Some(ReasonCode::TemporarilyUnavailable)
    );
    assert_eq!(
        samples[1].reason(),
        Some(ReasonCode::TemporarilyUnavailable)
    );
    assert_eq!(samples[2].value(), Some(&50.0));
    assert_eq!(samples[3].availability(), Availability::Restricted);
    assert_eq!(samples[3].reason(), Some(ReasonCode::PermissionDenied));
    assert_eq!(
        samples[4].reason(),
        Some(ReasonCode::TemporarilyUnavailable)
    );
    assert_eq!(samples, cpu_stat(b"\x02cpu 100 0 0 100\n\0\x01cpu 125 0 0 125\n\0\x02cpu 150 0 0 150\n\0\x06ignored\0\x02cpu 200 0 0 200\n"));
    for item in samples {
        state(&item);
    }
    assert_eq!(cpu_stat(&[0; 100_000]).len(), 21);
    let mut oversized = vec![b'x'; 100_000];
    oversized[0] = 2; // Read data after 300 ms, rather than synthesize an IO error.
    let samples = cpu_stat(&oversized);
    assert_eq!(samples.len(), 6);
    assert_eq!(samples[0].reason(), Some(ReasonCode::InvalidData));
}

#[test]
fn memory_and_uptime_hooks_keep_zero_failure_and_field_isolation_distinct() {
    let (total, available) = meminfo(b"MemTotal: 1 kB\nMemAvailable: 0 kB\n");
    assert_eq!(total.value(), Some(&1024));
    assert_eq!(available.value(), Some(&0));
    let (total, available) = meminfo(b"MemTotal: 1 kB\nMemAvailable: -1 kB\n");
    assert_eq!(total.value(), Some(&1024));
    assert_eq!(available.reason(), Some(ReasonCode::InvalidData));
    assert_eq!(uptime(b"0.99 999.99\n").value(), Some(&0));
    assert_eq!(
        uptime(b"18446744073709551615.99 0.00\n").value(),
        Some(&u64::MAX)
    );
    assert_eq!(
        uptime(b"NaN 0.00\n").reason(),
        Some(ReasonCode::InvalidData)
    );
    assert_eq!(uptime(&[b'1'; 257]).reason(), Some(ReasonCode::InvalidData));
    assert_eq!(
        meminfo(&[b'x'; 4097]).0.reason(),
        Some(ReasonCode::InvalidData)
    );
}

#[test]
fn deterministic_mutations_check_procfs_state_and_numeric_invariants() {
    let mut random = 0x4453_435f_5052_4f43u64;
    for case in 0..512 {
        let mut bytes = vec![0; case * 17 % 8193];
        for byte in &mut bytes {
            random ^= random << 13;
            random ^= random >> 7;
            random ^= random << 17;
            *byte = random as u8;
        }
        let (total, available) = meminfo(&bytes);
        state(&total);
        state(&available);
        if let Some(value) = available.value() {
            assert!(*value <= *total.value().expect("valid total"));
            assert_eq!(value % 1024, 0);
        }
        state(&uptime(&bytes));
        let cpu = cpu_stat(&bytes);
        assert!((6..=21).contains(&cpu.len()));
        for item in &cpu {
            state(item);
            if let Some(value) = item.value() {
                assert!(value.is_finite() && (0.0..=100.0).contains(value));
            }
        }
        let suffix = &cpu[cpu.len() - 5..];
        assert_eq!(suffix[0].reason(), Some(ReasonCode::InvalidData));
        assert_eq!(suffix[1].reason(), Some(ReasonCode::TemporarilyUnavailable));
        assert_eq!(suffix[2].value(), Some(&50.0));
        assert_eq!(suffix[3].value(), Some(&0.0));
        assert_eq!(suffix[4].value(), Some(&100.0));
    }
}
