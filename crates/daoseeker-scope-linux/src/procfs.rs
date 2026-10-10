//! Fresh bounded memory/uptime reads. No cache or silent alternate source.
use daoseeker_scope_core::{Observed, ReasonCode, Source, Timestamp};
use std::io::{self, Read};
use std::path::Path;

const MAX_MEMORY: usize = 4096;
const MAX_UPTIME: usize = 256;
type Parsed = Result<u64, ReasonCode>;

fn bounded(mut input: impl Read, limit: usize) -> io::Result<Vec<u8>> {
    let mut bytes = Vec::with_capacity(limit + 1);
    input
        .by_ref()
        .take((limit + 1) as u64)
        .read_to_end(&mut bytes)?;
    Ok(bytes)
}

fn failure<T>(kind: io::ErrorKind) -> Observed<T> {
    match kind {
        io::ErrorKind::PermissionDenied => {
            Observed::restricted(Source::Procfs, ReasonCode::PermissionDenied)
        }
        io::ErrorKind::NotFound => Observed::unavailable(Source::Procfs, ReasonCode::NotPresent),
        _ => Observed::unavailable(Source::Procfs, ReasonCode::Unknown),
    }
}

fn observed(value: Parsed, at: Timestamp) -> Observed<u64> {
    match value {
        Ok(value) => Observed::available(value, Source::Procfs, at),
        Err(reason) => Observed::unavailable(Source::Procfs, reason),
    }
}

fn unsigned(text: &str) -> Parsed {
    if text.is_empty() || !text.bytes().all(|b| b.is_ascii_digit()) {
        return Err(ReasonCode::InvalidData);
    }
    text.parse().map_err(|_| ReasonCode::InvalidData)
}

fn kibibytes(text: &str) -> Parsed {
    let mut parts = text.split_ascii_whitespace();
    let value = unsigned(parts.next().ok_or(ReasonCode::InvalidData)?)?;
    if parts.next() != Some("kB") || parts.next().is_some() {
        return Err(ReasonCode::InvalidData);
    }
    value.checked_mul(1024).ok_or(ReasonCode::InvalidData)
}

fn parse_memory(bytes: &[u8]) -> (Parsed, Parsed) {
    let invalid = (Err(ReasonCode::InvalidData), Err(ReasonCode::InvalidData));
    if bytes.is_empty() || bytes.len() > MAX_MEMORY {
        return invalid;
    }
    let Ok(text) = std::str::from_utf8(bytes) else {
        return invalid;
    };
    if text.trim().is_empty() {
        return invalid;
    }
    let mut total = None;
    let mut available = None;
    for line in text.lines() {
        let (key, value) = line
            .split_once(':')
            .unwrap_or((line.split_ascii_whitespace().next().unwrap_or(""), ""));
        let slot = match key.trim() {
            "MemTotal" => &mut total,
            "MemAvailable" => &mut available,
            _ => continue,
        };
        *slot = Some(if slot.is_some() {
            Err(ReasonCode::InvalidData)
        } else {
            kibibytes(value)
        });
    }
    let total = total.unwrap_or(Err(ReasonCode::NotPresent)).and_then(|n| {
        if n == 0 {
            Err(ReasonCode::InvalidData)
        } else {
            Ok(n)
        }
    });
    let available = total.and_then(|total| {
        available
            .unwrap_or(Err(ReasonCode::NotPresent))
            .and_then(|n| {
                if n > total {
                    Err(ReasonCode::InvalidData)
                } else {
                    Ok(n)
                }
            })
    });
    (total, available)
}

fn seconds(text: &str) -> Parsed {
    let (whole, fraction) = text.split_once('.').ok_or(ReasonCode::InvalidData)?;
    if fraction.is_empty() || !fraction.bytes().all(|b| b.is_ascii_digit()) {
        return Err(ReasonCode::InvalidData);
    }
    unsigned(whole)
}

fn parse_uptime(bytes: &[u8]) -> Parsed {
    if bytes.is_empty() || bytes.len() > MAX_UPTIME {
        return Err(ReasonCode::InvalidData);
    }
    let mut fields = std::str::from_utf8(bytes)
        .map_err(|_| ReasonCode::InvalidData)?
        .split_ascii_whitespace();
    let uptime = seconds(fields.next().ok_or(ReasonCode::InvalidData)?)?;
    // Idle is aggregate across CPUs and can exceed uptime; only validate syntax.
    seconds(fields.next().ok_or(ReasonCode::InvalidData)?)?;
    if fields.next().is_some() {
        return Err(ReasonCode::InvalidData);
    }
    Ok(uptime)
}

pub(super) fn memory(path: &Path, at: Timestamp) -> (Observed<u64>, Observed<u64>) {
    match std::fs::File::open(path).and_then(|input| bounded(input, MAX_MEMORY)) {
        Ok(bytes) => {
            let (total, available) = parse_memory(&bytes);
            (observed(total, at), observed(available, at))
        }
        Err(error) => (failure(error.kind()), failure(error.kind())),
    }
}

pub(super) fn uptime(path: &Path, at: Timestamp) -> Observed<u64> {
    match std::fs::File::open(path).and_then(|input| bounded(input, MAX_UPTIME)) {
        Ok(bytes) => observed(parse_uptime(&bytes), at),
        Err(error) => failure(error.kind()),
    }
}

#[cfg(feature = "fuzzing")]
pub(super) fn fuzz_memory(data: &[u8]) -> (Observed<u64>, Observed<u64>) {
    let (total, available) = parse_memory(data);
    (
        observed(total, Timestamp(0)),
        observed(available, Timestamp(0)),
    )
}

#[cfg(feature = "fuzzing")]
pub(super) fn fuzz_uptime(data: &[u8]) -> Observed<u64> {
    observed(parse_uptime(data), Timestamp(0))
}

#[cfg(test)]
mod tests {
    use super::*;
    use daoseeker_scope_core::Availability;

    #[test]
    fn memory_units_and_genuine_zero() {
        assert_eq!(
            parse_memory(b"MemTotal: 1024 kB\nMemAvailable: 512 kB\n"),
            (Ok(1048576), Ok(524288))
        );
        assert_eq!(
            parse_memory(b"MemTotal: 1 kB\nMemAvailable: 0 kB\n"),
            (Ok(1024), Ok(0))
        );
    }

    #[test]
    fn bad_available_does_not_discard_good_total() {
        for bad in [
            "",
            "-1 kB",
            "+1 kB",
            "1 MB",
            "1.5 kB",
            "2 kB extra",
            "18446744073709551615 kB",
            "2 kB",
        ] {
            let input = format!("MemTotal: 1 kB\nMemAvailable: {bad}\n");
            assert_eq!(
                parse_memory(input.as_bytes()),
                (Ok(1024), Err(ReasonCode::InvalidData))
            );
        }
        assert_eq!(
            parse_memory(b"MemTotal: 1 kB\nMemFree: 1 kB\n"),
            (Ok(1024), Err(ReasonCode::NotPresent))
        );
    }

    #[test]
    fn memory_missing_duplicate_and_invalid_total() {
        for input in [
            b"MemAvailable: 1 kB\n".as_slice(),
            b"MemTotal: 0 kB\nMemAvailable: 0 kB\n",
            b"MemTotal: 1 kB\nMemTotal: 1 kB\nMemAvailable: 1 kB\n",
        ] {
            assert!(parse_memory(input).0.is_err());
            assert!(parse_memory(input).1.is_err());
        }
        assert_eq!(
            parse_memory(b"MemTotal: 1 kB\nMemAvailable: 1 kB\nMemAvailable: 1 kB\n").1,
            Err(ReasonCode::InvalidData)
        );
    }

    #[test]
    fn bounded_corrupt_and_empty_input() {
        for bytes in [vec![], vec![0xff], vec![b'x'; MAX_MEMORY + 1]] {
            assert_eq!(
                parse_memory(&bytes),
                (Err(ReasonCode::InvalidData), Err(ReasonCode::InvalidData))
            );
        }
        let bytes = bounded(io::repeat(b'x'), MAX_MEMORY).expect("bounded");
        assert_eq!(bytes.len(), MAX_MEMORY + 1);
        assert!(parse_memory(&bytes).0.is_err());
        assert!(parse_uptime(&bounded(io::repeat(b'1'), MAX_UPTIME).expect("bounded")).is_err());
    }

    #[test]
    fn uptime_floor_zero_and_aggregate_idle() {
        assert_eq!(parse_uptime(b"123.99 999.99\n"), Ok(123));
        assert_eq!(parse_uptime(b"0.00 0.00\n"), Ok(0));
        assert_eq!(
            parse_uptime(b"18446744073709551615.99 0.00\n"),
            Ok(u64::MAX)
        );
    }

    #[test]
    fn uptime_rejects_bad_decimals_and_counts() {
        for input in [
            "",
            "123.99",
            "NaN 0.00",
            "-1.00 0.00",
            "+1.00 0.00",
            "1e3 0.00",
            "1. 0.00",
            ".99 0.00",
            "1.00 bad",
            "1.00 0.00 extra",
            "18446744073709551616.00 0.00",
        ] {
            assert_eq!(parse_uptime(input.as_bytes()), Err(ReasonCode::InvalidData));
        }
        assert_eq!(parse_uptime(&[0xff]), Err(ReasonCode::InvalidData));
    }

    #[test]
    fn io_failure_is_explicit_and_never_has_a_value_or_timestamp() {
        for (kind, state, reason) in [
            (
                io::ErrorKind::PermissionDenied,
                Availability::Restricted,
                ReasonCode::PermissionDenied,
            ),
            (
                io::ErrorKind::NotFound,
                Availability::Unavailable,
                ReasonCode::NotPresent,
            ),
            (
                io::ErrorKind::Other,
                Availability::Unavailable,
                ReasonCode::Unknown,
            ),
        ] {
            let item = failure::<u64>(kind);
            assert_eq!(item.availability(), state);
            assert_eq!(item.reason(), Some(reason));
            assert_eq!(item.source(), Source::Procfs);
            assert!(item.value().is_none());
            assert!(item.observed_at().is_none());
        }
    }
}
