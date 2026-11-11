//! Bounded native-endian Xe memory-region response parsing.
#![forbid(unsafe_code)]
use daoseeker_scope_core::{Observed, ReasonCode, ScopeError, Source, Timestamp};

pub(super) const REGION_HEADER: usize = 8;
pub(super) const REGION_SIZE: usize = 88;
pub(super) const MAX_REGIONS: usize = 32;
pub(super) const MAX_PAYLOAD: usize = REGION_HEADER + MAX_REGIONS * REGION_SIZE;

pub(super) fn valid_size(size: usize) -> bool {
    (REGION_HEADER + REGION_SIZE..=MAX_PAYLOAD).contains(&size)
        && (size - REGION_HEADER).is_multiple_of(REGION_SIZE)
}

fn capacity(bytes: &[u8]) -> Option<Option<u64>> {
    if !valid_size(bytes.len()) {
        return None;
    }
    let (header, entries) = bytes.split_at(REGION_HEADER);
    let count = u32::from_ne_bytes(header[..4].try_into().ok()?) as usize;
    if count != entries.len() / REGION_SIZE || header[4..] != [0; 4] {
        return None;
    }
    let mut instances = 0u64;
    let mut total = None::<u64>;
    for entry in entries.chunks_exact(REGION_SIZE) {
        let class = u16::from_ne_bytes(entry[..2].try_into().ok()?);
        let instance = u16::from_ne_bytes(entry[2..4].try_into().ok()?);
        let bit = 1u64.checked_shl(u32::from(instance))?;
        if instances & bit != 0 {
            return None;
        }
        instances |= bit;
        match class {
            0 => {} // System memory is shared with the CPU.
            1 => {
                let bytes = u64::from_ne_bytes(entry[8..16].try_into().ok()?);
                total = Some(total.unwrap_or(0).checked_add(bytes)?);
            }
            _ => return None,
        }
    }
    Some(total)
}

pub(crate) fn observe(
    bytes: &[u8],
    observed_at: impl FnOnce() -> Result<Timestamp, ScopeError>,
) -> Result<Observed<u64>, ScopeError> {
    Ok(match capacity(bytes) {
        Some(Some(value)) => Observed::available(value, Source::Drm, observed_at()?),
        Some(None) => Observed::not_applicable(Source::Drm),
        None => Observed::unavailable(Source::Drm, ReasonCode::InvalidData),
    })
}

#[cfg(test)]
pub(super) fn response(regions: &[(u16, u16, u64)]) -> Vec<u8> {
    let mut bytes = vec![0; REGION_HEADER + regions.len() * REGION_SIZE];
    bytes[..4].copy_from_slice(&(regions.len() as u32).to_ne_bytes());
    for (entry, &(class, instance, total)) in bytes[REGION_HEADER..]
        .chunks_exact_mut(REGION_SIZE)
        .zip(regions)
    {
        entry[..2].copy_from_slice(&class.to_ne_bytes());
        entry[2..4].copy_from_slice(&instance.to_ne_bytes());
        entry[8..16].copy_from_slice(&total.to_ne_bytes());
        entry[16..40].fill(0x55); // Usage and CPU-visible fields are irrelevant.
    }
    bytes
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn sums_device_local_regions_without_system_or_visible_memory() {
        assert_eq!(capacity(&response(&[(0, 0, u64::MAX)])), Some(None));
        assert_eq!(capacity(&response(&[(1, 0, 0)])), Some(Some(0)));
        assert_eq!(
            capacity(&response(&[(1, 4, 4096), (0, 0, u64::MAX), (1, 1, 8192)])),
            Some(Some(12288))
        );
    }

    #[test]
    fn invalid_or_oversized_responses_never_return_a_partial_sum() {
        for regions in [
            &[][..],
            &[(1, 0, 4096), (1, 0, 8192)],
            &[(1, 0, 4096), (2, 1, 8192)],
            &[(1, 0, 4096), (1, 64, 8192)],
            &[(1, 0, u64::MAX), (1, 1, 1)],
            &[(1, 0, 4096); MAX_REGIONS + 1],
        ] {
            assert_eq!(capacity(&response(regions)), None);
        }
        let mut bytes = response(&[(1, 0, 4096)]);
        assert_eq!(capacity(&bytes[..bytes.len() - 1]), None);
        bytes[..4].copy_from_slice(&2u32.to_ne_bytes());
        assert_eq!(capacity(&bytes), None);
        assert!(!valid_size(usize::MAX));
    }

    #[test]
    fn observed_capacity_keeps_source_timestamp_and_missing_reason() {
        use daoseeker_scope_core::Availability;
        let available = observe(&response(&[(1, 0, 0)]), || Ok(Timestamp(7))).unwrap();
        assert_eq!(available.value(), Some(&0));
        assert_eq!(available.source(), Source::Drm);
        assert_eq!(available.observed_at(), Some(Timestamp(7)));
        assert_eq!(available.reason(), None);
        let shared = observe(&response(&[(0, 0, 8192)]), || {
            panic!("missing capacity has no timestamp")
        })
        .unwrap();
        assert_eq!(shared.availability(), Availability::NotApplicable);
        assert_eq!(shared.observed_at(), None);
        assert_eq!(shared.reason(), Some(ReasonCode::NotPresent));
        let invalid = observe(&[], || panic!("invalid data has no timestamp")).unwrap();
        assert_eq!(invalid.availability(), Availability::Unavailable);
        assert_eq!(invalid.reason(), Some(ReasonCode::InvalidData));
    }
}
