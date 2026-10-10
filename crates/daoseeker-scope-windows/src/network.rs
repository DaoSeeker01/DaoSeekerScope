//! Bounded legacy interface enumeration with fresh 64-bit per-interface statistics.
//! Native buffers contain identifiers; only indices, counters and authorized aliases
//! are accessed. No native row is retained in the public snapshot (see ADR 0011).
use daoseeker_scope_core::*;
use std::collections::BTreeSet;
use std::mem::{align_of, offset_of, size_of};
use windows_sys::Win32::{
    Foundation::{
        ERROR_ACCESS_DENIED, ERROR_FILE_NOT_FOUND, ERROR_INSUFFICIENT_BUFFER, ERROR_INVALID_DATA,
        ERROR_INVALID_PARAMETER, ERROR_NOT_ENOUGH_MEMORY, ERROR_NOT_FOUND, ERROR_NOT_SUPPORTED,
    },
    NetworkManagement::IpHelper::{GetIfEntry2, GetIfTable, MIB_IF_ROW2, MIB_IFROW, MIB_IFTABLE},
};

const HEADER_BYTES: usize = offset_of!(MIB_IFTABLE, table);
const ROW_BYTES: usize = size_of::<MIB_IFROW>();
const INDEX_BYTES: usize = offset_of!(MIB_IFROW, dwIndex);
const WORD_BYTES: usize = size_of::<u32>();
const _: () = {
    assert!(align_of::<MIB_IFTABLE>() <= align_of::<u32>());
    assert!(align_of::<MIB_IFROW>() <= align_of::<u32>());
    assert!(offset_of!(MIB_IFTABLE, dwNumEntries) == 0);
    assert!(HEADER_BYTES.is_multiple_of(WORD_BYTES));
    assert!(ROW_BYTES.is_multiple_of(WORD_BYTES));
    assert!(INDEX_BYTES.is_multiple_of(WORD_BYTES));
    assert!(HEADER_BYTES + 1024 * ROW_BYTES <= 1024 * 1024);
};

fn missing<T>(code: u32) -> Observed<T> {
    match code {
        ERROR_ACCESS_DENIED => Observed::restricted(Source::Win32, ReasonCode::PermissionDenied),
        ERROR_NOT_SUPPORTED => Observed::missing(
            Availability::Unsupported,
            Source::Win32,
            ReasonCode::NotSupported,
        )
        .expect("unsupported is a missing state"),
        ERROR_FILE_NOT_FOUND | ERROR_NOT_FOUND => {
            Observed::unavailable(Source::Win32, ReasonCode::NotPresent)
        }
        ERROR_INSUFFICIENT_BUFFER | ERROR_INVALID_DATA | ERROR_INVALID_PARAMETER => {
            Observed::unavailable(Source::Win32, ReasonCode::InvalidData)
        }
        ERROR_NOT_ENOUGH_MEMORY => {
            Observed::unavailable(Source::Win32, ReasonCode::TemporarilyUnavailable)
        }
        _ => Observed::unavailable(Source::Win32, ReasonCode::Unknown),
    }
}

// A single attempt: do not allocate the system's requested size or retry without
// a bound if interfaces appear between calls. The Vec owns and frees the buffer.
fn enumerate_with(
    max_entries: usize,
    fill: impl FnOnce(&mut [u32], &mut u32) -> u32,
) -> Result<Vec<u32>, u32> {
    if !(1..=1024).contains(&max_entries) {
        return Err(ERROR_INVALID_PARAMETER);
    }
    let capacity = HEADER_BYTES + max_entries * ROW_BYTES;
    let mut words = vec![0u32; capacity / WORD_BYTES];
    let mut bytes = capacity as u32;
    let status = fill(&mut words, &mut bytes);
    if status != 0 {
        return Err(status);
    }
    let count = words[0] as usize;
    if count > max_entries
        || bytes as usize > capacity
        || (bytes as usize) < HEADER_BYTES + count * ROW_BYTES
    {
        return Err(ERROR_INVALID_DATA);
    }
    let mut seen = BTreeSet::new();
    let mut indices = Vec::with_capacity(count);
    for i in 0..count {
        let index = words[(HEADER_BYTES + i * ROW_BYTES + INDEX_BYTES) / WORD_BYTES];
        if index == 0 || !seen.insert(index) {
            return Err(ERROR_INVALID_DATA);
        }
        indices.push(index);
    }
    Ok(indices)
}

trait Api {
    fn enumerate(&mut self, max_entries: usize) -> Result<Vec<u32>, u32>;
    fn row(&mut self, index: u32) -> Result<MIB_IF_ROW2, u32>;
}
struct NativeApi;
impl Api for NativeApi {
    fn enumerate(&mut self, max_entries: usize) -> Result<Vec<u32>, u32> {
        enumerate_with(max_entries, |words, bytes| {
            // SAFETY: words is initialized, aligned for MIB_IFTABLE (const assertions),
            // and owns exactly the byte capacity passed to GetIfTable. The synchronous
            // API respects that capacity; no Rust reference to a flexible array is made.
            unsafe { GetIfTable(words.as_mut_ptr().cast(), bytes, 0) }
        })
    }
    fn row(&mut self, index: u32) -> Result<MIB_IF_ROW2, u32> {
        let mut row = MIB_IF_ROW2 {
            InterfaceIndex: index,
            ..Default::default()
        };
        // SAFETY: row is initialized and correctly aligned; its index came from the
        // bounded OS table, LUID is zero, and the API writes this fixed-size row.
        let status = unsafe { GetIfEntry2(&mut row) };
        if status == 0 { Ok(row) } else { Err(status) }
    }
}

fn alias(units: &[u16; 257], at: Timestamp) -> Observed<String> {
    let Some(end) = units.iter().position(|unit| *unit == 0) else {
        return missing(ERROR_INVALID_DATA);
    };
    if end == 0 {
        return Observed::unavailable(Source::Win32, ReasonCode::NotPresent);
    }
    match String::from_utf16(&units[..end]) {
        Ok(name) if !name.chars().any(char::is_control) && !name.trim().is_empty() => {
            Observed::available(name, Source::Win32, at)
        }
        _ => missing(ERROR_INVALID_DATA),
    }
}

fn collect_with(
    api: &mut impl Api,
    options: &Options,
    mut check: impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<Vec<NetworkInfo>>, ScopeError> {
    options.validate()?;
    check()?;
    let indices = api.enumerate(options.max_entries);
    check()?;
    let indices = match indices {
        Ok(indices) => indices,
        Err(code) => return Ok(missing(code)),
    };
    let mut entries = Vec::with_capacity(indices.len());
    for index in indices {
        check()?;
        let row = api.row(index);
        check()?;
        let mut entry = NetworkInfo::default();
        match row {
            Ok(row) => {
                let at = Timestamp::now()?;
                entry.received_bytes = Observed::available(row.InOctets, Source::Win32, at);
                entry.transmitted_bytes = Observed::available(row.OutOctets, Source::Win32, at);
                // Never inspect or decode the alias on the default path.
                if options.privacy.permits_sensitive() {
                    entry.interface_name = alias(&row.Alias, at);
                }
            }
            Err(code) => {
                entry.received_bytes = missing(code);
                entry.transmitted_bytes = missing(code);
                if options.privacy.permits_sensitive() {
                    entry.interface_name = missing(code);
                }
            }
        }
        if !options.privacy.permits_sensitive() {
            entry.interface_name = Observed::restricted(Source::Win32, ReasonCode::PrivacyRedacted);
        }
        entries.push(entry);
    }
    check()?;
    Ok(Observed::available(
        entries,
        Source::Win32,
        Timestamp::now()?,
    ))
}

pub(super) fn collect(context: &CollectContext) -> Result<Observed<Vec<NetworkInfo>>, ScopeError> {
    collect_with(&mut NativeApi, &context.options, || context.check())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::VecDeque;

    struct FakeApi {
        indices: Result<Vec<u32>, u32>,
        rows: VecDeque<Result<MIB_IF_ROW2, u32>>,
        row_calls: usize,
    }
    impl Api for FakeApi {
        fn enumerate(&mut self, _: usize) -> Result<Vec<u32>, u32> {
            self.indices.clone()
        }
        fn row(&mut self, _: u32) -> Result<MIB_IF_ROW2, u32> {
            self.row_calls += 1;
            self.rows.pop_front().expect("fixture row")
        }
    }
    fn fake(rows: Vec<Result<MIB_IF_ROW2, u32>>) -> FakeApi {
        FakeApi {
            indices: Ok((1..=rows.len() as u32).collect()),
            rows: rows.into(),
            row_calls: 0,
        }
    }
    fn table(
        count: usize,
        max: usize,
        bytes: Option<u32>,
        indices: &[u32],
    ) -> Result<Vec<u32>, u32> {
        enumerate_with(max, |words, size| {
            words[0] = count as u32;
            for (i, index) in indices.iter().enumerate() {
                words[(HEADER_BYTES + i * ROW_BYTES + INDEX_BYTES) / WORD_BYTES] = *index;
            }
            if let Some(bytes) = bytes {
                *size = bytes;
            }
            0
        })
    }
    #[test]
    fn bounded_enumeration_rejects_bad_counts_sizes_and_indices() {
        assert_eq!(table(0, 1, Some(HEADER_BYTES as u32), &[]), Ok(vec![]));
        assert_eq!(table(2, 2, None, &[3, 19]), Ok(vec![3, 19]));
        for max in [1, 128, 1024] {
            let indices: Vec<_> = (1..=max as u32).collect();
            assert_eq!(table(max, max, None, &indices), Ok(indices));
        }
        for result in [
            table(3, 2, None, &[]),
            table(usize::MAX, 1, None, &[]),
            table(1, 1, Some(0), &[]),
            table(1, 1, Some(u32::MAX), &[]),
            table(1, 1, None, &[0]),
            table(2, 2, None, &[7, 7]),
        ] {
            assert_eq!(result, Err(ERROR_INVALID_DATA));
        }
        for max in [0, 1025, usize::MAX] {
            assert_eq!(
                enumerate_with(max, |_, _| panic!("must not call OS")),
                Err(ERROR_INVALID_PARAMETER)
            );
        }
        assert_eq!(
            enumerate_with(1, |words, bytes| {
                assert_eq!(words.len() * WORD_BYTES, HEADER_BYTES + ROW_BYTES);
                *bytes = u32::MAX;
                ERROR_INSUFFICIENT_BUFFER
            }),
            Err(ERROR_INSUFFICIENT_BUFFER)
        );
    }
    #[test]
    fn fresh_counters_preserve_zero_max_and_ignore_invalid_private_alias() {
        let row = MIB_IF_ROW2 {
            InOctets: 0,
            OutOctets: u64::MAX,
            Alias: [0xd800; 257],
            ..Default::default()
        };
        let mut api = fake(vec![Ok(row)]);
        let collected = collect_with(&mut api, &Options::default(), || Ok(())).unwrap();
        let entry = &collected.value().unwrap()[0];
        assert_eq!(entry.received_bytes.value(), Some(&0));
        assert_eq!(entry.transmitted_bytes.value(), Some(&u64::MAX));
        assert_eq!(entry.received_bytes.source(), Source::Win32);
        assert!(entry.received_bytes.observed_at().is_some());
        assert_eq!(
            entry.interface_name.reason(),
            Some(ReasonCode::PrivacyRedacted)
        );
        assert!(entry.interface_name.value().is_none());
        api.indices = Err(ERROR_ACCESS_DENIED);
        assert_eq!(
            collect_with(&mut api, &Options::default(), || Ok(()))
                .unwrap()
                .availability(),
            Availability::Restricted
        );
        api.indices = Ok(vec![1]);
        api.rows.push_back(Ok(MIB_IF_ROW2::default()));
        let recovered = collect_with(&mut api, &Options::default(), || Ok(())).unwrap();
        assert_eq!(
            recovered.value().unwrap()[0].transmitted_bytes.value(),
            Some(&0)
        );
    }
    #[test]
    fn errors_are_isolated_and_empty_enumeration_is_available() {
        let mut api = fake(vec![
            Err(ERROR_FILE_NOT_FOUND),
            Ok(MIB_IF_ROW2::default()),
            Err(ERROR_ACCESS_DENIED),
        ]);
        let collected = collect_with(&mut api, &Options::default(), || Ok(())).unwrap();
        let rows = collected.value().unwrap();
        assert_eq!(
            rows[0].received_bytes.reason(),
            Some(ReasonCode::NotPresent)
        );
        assert_eq!(rows[1].received_bytes.value(), Some(&0));
        assert_eq!(
            rows[2].received_bytes.availability(),
            Availability::Restricted
        );
        assert_eq!(
            collect_with(&mut fake(vec![]), &Options::default(), || Ok(()))
                .unwrap()
                .value(),
            Some(&vec![])
        );
        for (code, state, reason) in [
            (
                ERROR_NOT_SUPPORTED,
                Availability::Unsupported,
                ReasonCode::NotSupported,
            ),
            (
                ERROR_NOT_ENOUGH_MEMORY,
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            (
                ERROR_INVALID_DATA,
                Availability::Unavailable,
                ReasonCode::InvalidData,
            ),
            (987654, Availability::Unavailable, ReasonCode::Unknown),
        ] {
            let observed = missing::<u64>(code);
            assert_eq!(observed.availability(), state);
            assert_eq!(observed.reason(), Some(reason));
            assert!(observed.value().is_none());
            assert!(observed.observed_at().is_none());
        }
    }
    #[test]
    fn authorized_alias_is_strict_utf16_and_field_failure_preserves_counters() {
        let at = Timestamp(42);
        let mut units = [0; 257];
        let name: Vec<_> = "测试 🦀".encode_utf16().collect();
        units[..name.len()].copy_from_slice(&name);
        assert_eq!(
            alias(&units, at).value().map(String::as_str),
            Some("测试 🦀")
        );
        assert_eq!(alias(&[0; 257], at).reason(), Some(ReasonCode::NotPresent));
        for input in [[1; 257], [0xd800; 257]] {
            assert_eq!(alias(&input, at).reason(), Some(ReasonCode::InvalidData));
        }
        for first in [0xd800, 10, 32] {
            let mut input = [0; 257];
            input[0] = first;
            assert_eq!(alias(&input, at).reason(), Some(ReasonCode::InvalidData));
        }
        let options = Options {
            privacy: PrivacyOptions {
                include_sensitive: true,
                caller_authorized: true,
            },
            ..Default::default()
        };
        let mut api = fake(vec![
            Ok(MIB_IF_ROW2 {
                Alias: units,
                ..Default::default()
            }),
            Ok(MIB_IF_ROW2::default()),
        ]);
        let result = collect_with(&mut api, &options, || Ok(())).unwrap();
        assert_eq!(
            result.value().unwrap()[0]
                .interface_name
                .value()
                .map(String::as_str),
            Some("测试 🦀")
        );
        assert_eq!(
            result.value().unwrap()[1].interface_name.reason(),
            Some(ReasonCode::NotPresent)
        );
        assert_eq!(result.value().unwrap()[1].received_bytes.value(), Some(&0));
    }
    #[test]
    fn cancellation_stops_before_api_or_next_interface_and_authorization_is_required() {
        let mut api = fake(vec![Ok(MIB_IF_ROW2::default()), Ok(MIB_IF_ROW2::default())]);
        let mut checks = 0;
        let error = collect_with(&mut api, &Options::default(), || {
            checks += 1;
            if checks == 4 {
                Err(ScopeError::new(ErrorCode::Cancelled))
            } else {
                Ok(())
            }
        })
        .unwrap_err();
        assert_eq!(error.code, ErrorCode::Cancelled);
        assert_eq!(api.row_calls, 1);
        api.row_calls = 0;
        let error = collect_with(&mut api, &Options::default(), || {
            Err(ScopeError::new(ErrorCode::Timeout))
        })
        .unwrap_err();
        assert_eq!(error.code, ErrorCode::Timeout);
        assert_eq!(api.row_calls, 0);
        let options = Options {
            privacy: PrivacyOptions {
                include_sensitive: true,
                caller_authorized: false,
            },
            ..Default::default()
        };
        assert_eq!(
            collect_with(&mut api, &options, || Ok(()))
                .unwrap_err()
                .code,
            ErrorCode::InvalidArgument
        );
    }
}
