//! Bounded REG_SZ decoding; no registry I/O or lossy Unicode conversion.
use daoseeker_scope_core::*;

pub(super) const LIMIT: usize = 4096;
pub(super) fn parse(kind: u32, data: &[u8], at: Timestamp) -> Observed<String> {
    let invalid = || Observed::unavailable(Source::Win32, ReasonCode::InvalidData);
    if kind != 1
        || data.len() < 2
        || data.len() > LIMIT
        || !data.len().is_multiple_of(2)
        || !data.ends_with(&[0, 0])
    {
        return invalid();
    }
    let units = data[..data.len() - 2]
        .chunks_exact(2)
        .map(|pair| u16::from_le_bytes([pair[0], pair[1]]));
    let mut text = String::with_capacity(data.len());
    for unit in char::decode_utf16(units) {
        let Ok(ch) = unit else { return invalid() };
        if ch.is_control() || text.len() + ch.len_utf8() > LIMIT {
            return invalid();
        }
        text.push(ch);
    }
    let text = text.trim();
    if text.is_empty()
        || [
            "to be filled by o.e.m.",
            "default string",
            "unknown",
            "none",
            "not specified",
            "not applicable",
            "n/a",
            "unspecified",
            "system product name",
            "system manufacturer",
            "base board product name",
            "baseboard product name",
        ]
        .contains(&text.to_ascii_lowercase().as_str())
    {
        return invalid();
    }
    Observed::available(text.to_owned(), Source::Win32, at)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn wire(text: &str) -> Vec<u8> {
        text.encode_utf16()
            .chain([0])
            .flat_map(u16::to_le_bytes)
            .collect()
    }
    #[test]
    fn valid_unicode_is_trimmed_without_replacement_or_zero_guessing() {
        for text in ["  Acme Board  ", "观微 🦀", "0"] {
            let field = parse(1, &wire(text), Timestamp(7));
            assert_eq!(field.value().map(String::as_str), Some(text.trim()));
            assert_eq!(field.source(), Source::Win32);
            assert_eq!(field.observed_at(), Some(Timestamp(7)));
        }
    }
    #[test]
    fn malformed_type_length_terminators_surrogates_and_controls_are_missing() {
        let inputs = [
            vec![],
            vec![0],
            vec![0, 0],
            vec![65, 0],
            vec![65, 0, 0],
            wire("A\0B"),
            wire("A\n"),
            wire("\tA"),
            wire("  "),
            vec![0, 0xd8, 0, 0],
            vec![0, 0xdc, 0, 0],
            vec![0; LIMIT + 2],
        ];
        for bytes in inputs {
            let field = parse(1, &bytes, Timestamp(7));
            assert_eq!(field.reason(), Some(ReasonCode::InvalidData));
            assert!(field.value().is_none() && field.observed_at().is_none());
        }
        for kind in [0, 2, 3, 7, u32::MAX] {
            assert!(parse(kind, &wire("Acme"), Timestamp(7)).value().is_none());
        }
    }
    #[test]
    fn known_oem_placeholders_are_not_hardware_values() {
        for text in [
            "To Be Filled By O.E.M.",
            "DEFAULT STRING",
            "Unknown",
            "None",
            "Not Specified",
            "Not Applicable",
            "N/A",
            "Unspecified",
            "System Product Name",
            "System Manufacturer",
            "Base Board Product Name",
            "BaseBoard Product Name",
        ] {
            assert_eq!(
                parse(1, &wire(text), Timestamp(7)).reason(),
                Some(ReasonCode::InvalidData)
            );
        }
    }
    #[test]
    fn wire_and_utf8_limits_both_apply_without_truncation() {
        let good = "A".repeat(2047);
        assert_eq!(parse(1, &wire(&good), Timestamp(0)).value(), Some(&good));
        assert!(
            parse(1, &wire(&"A".repeat(2048)), Timestamp(0))
                .value()
                .is_none()
        );
        let oversized_utf8 = wire(&"观".repeat(1500));
        assert!(oversized_utf8.len() < LIMIT);
        assert!(parse(1, &oversized_utf8, Timestamp(0)).value().is_none());
    }
}
