use daoseeker_scope_core::{Availability, ReasonCode, Source};
use daoseeker_scope_linux::parse_dmi_text;

#[test]
fn seeded_dmi_bytes_are_bounded_and_never_forge_values() {
    let mut state = 0x4453_435f_444d_4901u64;
    let mut available = 0;
    let mut rejected = 0;
    for case in 0..512 {
        let len = case * 17 % 8193;
        let bytes = (0..len)
            .map(|_| {
                state ^= state << 13;
                state ^= state >> 7;
                state ^= state << 17;
                if case % 3 == 0 {
                    b'a' + (state % 26) as u8
                } else {
                    state as u8
                }
            })
            .collect::<Vec<_>>();
        let observation = parse_dmi_text(&bytes);
        assert_eq!(observation.source(), Source::Sysfs);
        if let Some(value) = observation.value() {
            available += 1;
            assert_eq!(observation.availability(), Availability::Available);
            assert!(!value.is_empty() && value.len() <= 4096);
            assert!(!value.chars().any(char::is_control));
            assert_eq!(value, std::str::from_utf8(&bytes).expect("utf8").trim());
            assert!(observation.observed_at().is_some());
            assert!(observation.reason().is_none());
        } else {
            rejected += 1;
            assert_eq!(observation.availability(), Availability::Unavailable);
            assert_eq!(observation.reason(), Some(ReasonCode::InvalidData));
            assert!(observation.observed_at().is_none());
        }
    }
    assert!(available > 0 && rejected > 0);
}
