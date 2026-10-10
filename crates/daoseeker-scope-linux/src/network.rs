//! Fresh counters only: no address, link identifier, or cached fallback queries.
use daoseeker_scope_core::*;
use std::collections::BTreeSet;
use std::io::{self, Read};
use std::path::Path;

const MAX_BYTES: usize = 512 * 1024;
const HEADER: [&str; 3] = ["Inter-", "Receive", "Transmit"];
const COLUMNS: [&str; 3] = [
    "face",
    "bytes packets errs drop fifo frame compressed multicast",
    "bytes packets errs drop fifo colls carrier compressed",
];

fn invalid<T>() -> Observed<T> {
    Observed::unavailable(Source::Procfs, ReasonCode::InvalidData)
}

fn failure(kind: io::ErrorKind) -> Observed<Vec<NetworkInfo>> {
    match kind {
        io::ErrorKind::PermissionDenied => {
            Observed::restricted(Source::Procfs, ReasonCode::PermissionDenied)
        }
        io::ErrorKind::NotFound => Observed::unavailable(Source::Procfs, ReasonCode::NotPresent),
        _ => Observed::unavailable(Source::Procfs, ReasonCode::Unknown),
    }
}

fn header(line: &str, expected: &[&str; 3]) -> bool {
    let mut sections = line.split('|');
    expected.iter().all(|expected| {
        sections.next().is_some_and(|section| {
            section
                .split_ascii_whitespace()
                .eq(expected.split_ascii_whitespace())
        })
    }) && sections.next().is_none()
}

fn counter(value: &str, at: Timestamp) -> Observed<u64> {
    if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
        return invalid();
    }
    match value.parse() {
        Ok(number) => Observed::available(number, Source::Procfs, at),
        Err(_) => invalid(),
    }
}

fn parse(
    bytes: &[u8],
    max_entries: usize,
    privacy: PrivacyOptions,
    at: Timestamp,
) -> Observed<Vec<NetworkInfo>> {
    if bytes.len() > MAX_BYTES || !(1..=1024).contains(&max_entries) || !bytes.ends_with(b"\n") {
        return invalid();
    }
    let Ok(text) = std::str::from_utf8(bytes) else {
        return invalid();
    };
    let mut lines = text.lines();
    if !lines.next().is_some_and(|line| header(line, &HEADER))
        || !lines.next().is_some_and(|line| header(line, &COLUMNS))
    {
        return invalid();
    }
    let mut names = BTreeSet::new();
    let mut entries = Vec::new();
    for line in lines {
        if entries.len() >= max_entries || line.len() > 1024 {
            return invalid();
        }
        let Some((name, counters)) = line.split_once(':') else {
            return invalid();
        };
        let name = name.trim_matches([' ', '\t']);
        if name.is_empty()
            || name.len() > 15
            || name
                .chars()
                .any(|ch| ch.is_control() || ch.is_whitespace() || ch == '/')
            || !names.insert(name)
        {
            return invalid();
        }
        let mut fields = counters.split_ascii_whitespace();
        let mut columns = [""; 16];
        let complete = columns.iter_mut().all(|column| {
            if let Some(value) = fields.next() {
                *column = value;
                true
            } else {
                false
            }
        }) && fields.next().is_none();
        let mut entry = NetworkInfo::default();
        entry.interface_name = if privacy.permits_sensitive() {
            Observed::available(name.to_owned(), Source::Procfs, at)
        } else {
            Observed::restricted(Source::Procfs, ReasonCode::PrivacyRedacted)
        };
        entry.received_bytes = if complete {
            counter(columns[0], at)
        } else {
            invalid()
        };
        entry.transmitted_bytes = if complete {
            counter(columns[8], at)
        } else {
            invalid()
        };
        entries.push(entry);
    }
    Observed::available(entries, Source::Procfs, at)
}

pub(super) fn collect(
    path: &Path,
    context: &CollectContext,
) -> Result<Observed<Vec<NetworkInfo>>, ScopeError> {
    context.check()?;
    let input = std::fs::File::open(path).and_then(|file| {
        let mut bytes = Vec::with_capacity(4096);
        file.take((MAX_BYTES + 1) as u64).read_to_end(&mut bytes)?;
        Ok(bytes)
    });
    context.check()?;
    let observation = match input {
        Ok(bytes) => parse(
            &bytes,
            context.options.max_entries,
            context.options.privacy,
            Timestamp::now()?,
        ),
        Err(error) => failure(error.kind()),
    };
    context.check()?;
    Ok(observation)
}

#[cfg(feature = "fuzzing")]
pub(super) fn fuzz(data: &[u8], max_entries: usize, sensitive: bool) -> Observed<Vec<NetworkInfo>> {
    parse(
        data,
        max_entries,
        PrivacyOptions {
            include_sensitive: sensitive,
            caller_authorized: sensitive,
        },
        Timestamp(0),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    const HEAD: &str = "Inter-| Receive | Transmit\n face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n";
    fn sample(rows: &str, limit: usize, sensitive: bool) -> Observed<Vec<NetworkInfo>> {
        parse(
            format!("{HEAD}{rows}").as_bytes(),
            limit,
            PrivacyOptions {
                include_sensitive: sensitive,
                caller_authorized: sensitive,
            },
            Timestamp(42),
        )
    }
    fn row(name: &str, rx: &str, tx: &str) -> String {
        format!(" {name}: {rx} 0 0 0 0 0 0 0 {tx} 0 0 0 0 0 0 0\n")
    }
    #[test]
    fn counters_preserve_zero_max_and_redact_names() {
        let value = sample(&row("eth0", "0", "18446744073709551615"), 1, false);
        let entry = &value.value().expect("available")[0];
        assert_eq!(entry.received_bytes.value(), Some(&0));
        assert_eq!(entry.transmitted_bytes.value(), Some(&u64::MAX));
        assert_eq!(entry.received_bytes.observed_at(), Some(Timestamp(42)));
        assert_eq!(
            entry.interface_name.availability(),
            Availability::Restricted
        );
        assert_eq!(
            entry.interface_name.reason(),
            Some(ReasonCode::PrivacyRedacted)
        );
        assert!(entry.interface_name.value().is_none());
        let named = sample(&row("eth0", "1", "2"), 1, true);
        assert_eq!(
            named.value().expect("named")[0]
                .interface_name
                .value()
                .map(String::as_str),
            Some("eth0")
        );
        let mut options = PrivacyOptions {
            include_sensitive: true,
            caller_authorized: false,
        };
        let refused = parse(
            format!("{HEAD}{}", row("eth0", "1", "2")).as_bytes(),
            1,
            options,
            Timestamp(42),
        );
        assert!(
            refused.value().expect("collection")[0]
                .interface_name
                .value()
                .is_none()
        );
        options.include_sensitive = false;
        options.caller_authorized = true;
        assert!(!options.permits_sensitive());
    }
    #[test]
    fn bad_counter_does_not_erase_other_field_or_interface() {
        for damaged in ["-1", "+1", "NaN", "1.5", "18446744073709551616"] {
            let value = sample(
                &(row("bad", damaged, "4") + &row("good", "5", "6")),
                2,
                false,
            );
            let entries = value.value().expect("isolated");
            assert_eq!(
                entries[0].received_bytes.reason(),
                Some(ReasonCode::InvalidData)
            );
            assert_eq!(entries[0].transmitted_bytes.value(), Some(&4));
            assert_eq!(entries[1].received_bytes.value(), Some(&5));
        }
        let value = sample(&(row("good", "5", "6") + "bad: 1 2\n"), 2, false);
        let entries = value.value().expect("isolated row");
        assert_eq!(entries[0].received_bytes.value(), Some(&5));
        assert_eq!(
            entries[1].transmitted_bytes.reason(),
            Some(ReasonCode::InvalidData)
        );
    }
    #[test]
    fn corrupt_headers_names_duplicates_and_limits_are_not_success() {
        for bytes in [
            b"".as_slice(),
            b"\xff\n",
            HEAD.as_bytes().strip_suffix(b"\n").expect("suffix"),
            b"Inter-|Receive|Transmit\nface|bytes|bytes\n",
        ] {
            assert_eq!(
                parse(bytes, 1, PrivacyOptions::default(), Timestamp(42)).reason(),
                Some(ReasonCode::InvalidData)
            );
        }
        for rows in [
            row("eth0", "1", "2") + &row("eth0", "3", "4"),
            row("sixteenbytesname!", "1", "2"),
            row("bad name", "1", "2"),
            row("bad/name", "1", "2"),
            "missing colon\n".into(),
        ] {
            assert_eq!(
                sample(&rows, 2, false).reason(),
                Some(ReasonCode::InvalidData)
            );
        }
        assert_eq!(
            sample(&(row("a", "1", "2") + &row("b", "3", "4")), 1, false).reason(),
            Some(ReasonCode::InvalidData)
        );
        assert_eq!(
            parse(
                &vec![b' '; MAX_BYTES + 1],
                1,
                PrivacyOptions::default(),
                Timestamp(42)
            )
            .reason(),
            Some(ReasonCode::InvalidData)
        );
        assert_eq!(sample("", 0, false).reason(), Some(ReasonCode::InvalidData));
        assert_eq!(
            sample("", 1025, false).reason(),
            Some(ReasonCode::InvalidData)
        );
        assert_eq!(sample("", 1, false).value(), Some(&Vec::new()));
    }
    #[test]
    fn io_errors_are_distinct() {
        assert_eq!(
            failure(io::ErrorKind::PermissionDenied).availability(),
            Availability::Restricted
        );
        assert_eq!(
            failure(io::ErrorKind::PermissionDenied).reason(),
            Some(ReasonCode::PermissionDenied)
        );
        assert_eq!(
            failure(io::ErrorKind::NotFound).reason(),
            Some(ReasonCode::NotPresent)
        );
        assert_eq!(
            failure(io::ErrorKind::Other).reason(),
            Some(ReasonCode::Unknown)
        );
    }
}
