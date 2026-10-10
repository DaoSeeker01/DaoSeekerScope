#![cfg(feature = "fuzzing")]
use daoseeker_scope_core::{Availability, ReasonCode};
use daoseeker_scope_linux::fuzzing::network_dev;

#[test]
fn network_synthetic_inputs_and_entry_limits_use_production_parser() {
    let head = "Inter-| Receive | Transmit\nface |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n";
    let valid = format!("{head}eth0: 10 0 0 0 0 0 0 0 20 0 0 0 0 0 0 0\n");
    let sample = network_dev(valid.as_bytes(), 1, false);
    let entry = &sample.value().expect("valid seed")[0];
    assert_eq!(entry.received_bytes.value(), Some(&10));
    assert_eq!(
        entry.interface_name.reason(),
        Some(ReasonCode::PrivacyRedacted)
    );
    for (seed, available) in [
        ("lo: 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n", true),
        (
            "eth0: 18446744073709551616 0 0 0 0 0 0 0 8 0 0 0 0 0 0 0\n",
            true,
        ),
        ("bad: 1 2\n", true),
        ("", true),
        (
            "lo: 1 0 0 0 0 0 0 0 2 0 0 0 0 0 0 0\nlo: 3 0 0 0 0 0 0 0 4 0 0 0 0 0 0 0\n",
            false,
        ),
    ] {
        let input = format!("{head}{seed}");
        let first = network_dev(input.as_bytes(), 128, false);
        assert_eq!(first.availability() == Availability::Available, available);
        assert_eq!(network_dev(input.as_bytes(), 128, false), first);
    }
    let mut input = head.to_owned();
    for i in 0..1024 {
        input.push_str(&format!("n{i}: 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n"));
    }
    assert_eq!(
        network_dev(input.as_bytes(), 1024, false)
            .value()
            .expect("maximum")
            .len(),
        1024
    );
    assert_eq!(
        network_dev(input.as_bytes(), 128, false).reason(),
        Some(ReasonCode::InvalidData)
    );
    input.push_str("extra: 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n");
    assert_eq!(
        network_dev(input.as_bytes(), 1024, false).reason(),
        Some(ReasonCode::InvalidData)
    );
}
