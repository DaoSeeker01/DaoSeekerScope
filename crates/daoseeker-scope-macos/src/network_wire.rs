//! Safe decoding of the public Darwin routing wire format (ADR 0012).
use daoseeker_scope_core::ReasonCode;
use std::collections::BTreeSet;

pub(crate) const MAX_BYTES: usize = 512 * 1024;
pub(crate) const MAX_RECORDS: usize = 8192;
pub(crate) const HEADER_BYTES: usize = 160;
pub(crate) const INDEX_OFFSET: usize = 12;
pub(crate) const RECEIVED_OFFSET: usize = 96;
pub(crate) const TRANSMITTED_OFFSET: usize = 104;
pub(crate) const VERSION: u8 = 5;
pub(crate) const IFINFO: u8 = 0x12;
pub(crate) const NEWADDR: u8 = 0x0c;
pub(crate) const NEWMADDR: u8 = 0x13;

#[derive(Debug, PartialEq)]
pub(crate) struct Row {
    pub index: u16,
    pub received: u64,
    pub transmitted: u64,
}

pub(crate) fn parse(data: &[u8], max_entries: usize) -> Result<Vec<Row>, ReasonCode> {
    if data.len() > MAX_BYTES || !(1..=1024).contains(&max_entries) {
        return Err(ReasonCode::InvalidData);
    }
    let mut rows = Vec::new();
    let mut indices = BTreeSet::new();
    let mut remaining = data;
    let mut records = 0;
    while !remaining.is_empty() {
        records += 1;
        if records > MAX_RECORDS || remaining.len() < 4 || remaining[2] != VERSION {
            return Err(ReasonCode::InvalidData);
        }
        let length = u16::from_ne_bytes([remaining[0], remaining[1]]) as usize;
        let minimum = match remaining[3] {
            IFINFO => HEADER_BYTES,
            NEWADDR => 20,
            NEWMADDR => 20,
            _ => return Err(ReasonCode::InvalidData),
        };
        if length < minimum || length > remaining.len() || !length.is_multiple_of(4) {
            return Err(ReasonCode::InvalidData);
        }
        let message = &remaining[..length];
        if message[3] == IFINFO {
            let index = u16::from_ne_bytes([message[INDEX_OFFSET], message[INDEX_OFFSET + 1]]);
            if rows.len() == max_entries || index == 0 || !indices.insert(index) {
                return Err(ReasonCode::InvalidData);
            }
            let counter = |offset| {
                u64::from_ne_bytes(
                    message[offset..offset + 8]
                        .try_into()
                        .expect("validated header contains eight counter bytes"),
                )
            };
            rows.push(Row {
                index,
                received: counter(RECEIVED_OFFSET),
                transmitted: counter(TRANSMITTED_OFFSET),
            });
        }
        remaining = &remaining[length..];
    }
    if !data.is_empty() && rows.is_empty() {
        return Err(ReasonCode::InvalidData);
    }
    Ok(rows)
}

#[cfg(test)]
pub(crate) fn fixture(index: u16, received: u64, transmitted: u64) -> Vec<u8> {
    let mut data = vec![0; HEADER_BYTES];
    data[..2].copy_from_slice(&(HEADER_BYTES as u16).to_ne_bytes());
    data[2] = VERSION;
    data[3] = IFINFO;
    data[INDEX_OFFSET..INDEX_OFFSET + 2].copy_from_slice(&index.to_ne_bytes());
    data[RECEIVED_OFFSET..RECEIVED_OFFSET + 8].copy_from_slice(&received.to_ne_bytes());
    data[TRANSMITTED_OFFSET..TRANSMITTED_OFFSET + 8].copy_from_slice(&transmitted.to_ne_bytes());
    data
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preserves_os_bytes_without_alignment_casts_or_precision_reconstruction() {
        let mut data = vec![0xff];
        data.extend(fixture(1, 0, u64::MAX));
        data.extend([0xff; 16]); // Opaque link metadata must not be decoded.
        data[1..3].copy_from_slice(&176u16.to_ne_bytes());
        assert_eq!(
            parse(&data[1..], 1),
            Ok(vec![Row {
                index: 1,
                received: 0,
                transmitted: u64::MAX
            }])
        );
        assert_eq!(parse(&[], 1), Ok(vec![]));
        assert_eq!(
            parse(&fixture(1, 1024, 2048), 1).expect("valid")[0].received,
            1024
        );
    }

    #[test]
    fn rejects_truncation_bad_lengths_versions_and_types() {
        let data = fixture(1, 10, 20);
        for end in 1..data.len() {
            assert_eq!(parse(&data[..end], 1), Err(ReasonCode::InvalidData));
        }
        for length in [0u16, 3, 159, 161, u16::MAX] {
            let mut bad = data.clone();
            bad[..2].copy_from_slice(&length.to_ne_bytes());
            assert!(parse(&bad, 1).is_err());
        }
        for (offset, value) in [(2, 0), (2, 6), (3, 0xff)] {
            let mut bad = data.clone();
            bad[offset] = value;
            assert!(parse(&bad, 1).is_err());
        }
        let mut trailing = data;
        trailing.push(0);
        assert!(parse(&trailing, 1).is_err());
    }

    #[test]
    fn rejects_duplicates_limits_and_oversized_messages_without_prefix_success() {
        assert!(parse(&fixture(0, 1, 2), 1).is_err());
        let mut duplicate = fixture(1, 1, 2);
        duplicate.extend(fixture(1, 3, 4));
        assert!(parse(&duplicate, 2).is_err());
        let mut data = Vec::new();
        for index in 1..=1024 {
            data.extend(fixture(index, u64::from(index), 0));
        }
        assert_eq!(parse(&data, 1024).expect("at limit").len(), 1024);
        assert!(parse(&data, 1023).is_err());
        assert!(parse(&[], 0).is_err());
        assert!(parse(&[], 1025).is_err());
        assert!(parse(&vec![0; MAX_BYTES + 1], 1024).is_err());
    }

    #[test]
    fn skips_only_bounded_known_auxiliary_records() {
        let mut data = fixture(1, 1, 2);
        for kind in [NEWADDR, NEWMADDR] {
            let mut auxiliary = vec![0xff; 20];
            auxiliary[..2].copy_from_slice(&20u16.to_ne_bytes());
            auxiliary[2] = VERSION;
            auxiliary[3] = kind;
            assert!(parse(&auxiliary, 1).is_err()); // Not evidence of zero interfaces.
            data.extend(auxiliary);
        }
        assert_eq!(parse(&data, 1).expect("known ancillary messages").len(), 1);
        let extra = data[HEADER_BYTES..HEADER_BYTES + 20].to_vec();
        for _ in 0..MAX_RECORDS {
            data.extend(&extra);
        }
        assert!(parse(&data, 1).is_err());
    }
}
