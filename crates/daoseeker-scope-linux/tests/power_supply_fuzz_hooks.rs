#![cfg(feature = "fuzzing")]
use daoseeker_scope_core::{Availability, ReasonCode, Source};
use daoseeker_scope_linux::fuzzing::power_supply;

#[test]
fn bounded_attributes_and_seeded_mutations_preserve_numeric_and_state_contracts() {
    assert_eq!(power_supply(b"0\n").0.value(), Some(&0));
    assert_eq!(power_supply(b"100\n").0.value(), Some(&100));
    assert_eq!(power_supply(b"1\n").1.value(), Some(&1));
    assert_eq!(
        power_supply(b"2\n").1.reason(),
        Some(ReasonCode::InvalidData)
    );
    assert!(power_supply(b"Battery\n").2);
    for raw in [
        b"101".as_slice(),
        b"-1",
        b"1.5",
        b"NaN",
        b"\xff",
        &[b'1'; 129],
    ] {
        assert!(power_supply(raw).0.value().is_none());
    }
    let mut seed = 20261010_u64;
    for i in 0..512 {
        let raw: Vec<u8> = (0..i % 257)
            .map(|_| {
                seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
                (seed >> 32) as u8
            })
            .collect();
        let (percent, boolean, _) = power_supply(&raw);
        for (item, max) in [(percent, 100), (boolean, 1)] {
            assert_eq!(item.source(), Source::Sysfs);
            if let Some(n) = item.value() {
                assert!(*n <= max);
                assert_eq!(item.availability(), Availability::Available);
                assert!(item.reason().is_none() && item.observed_at().is_some());
            } else {
                assert_eq!(item.reason(), Some(ReasonCode::InvalidData));
                assert!(item.observed_at().is_none());
            }
        }
    }
}
