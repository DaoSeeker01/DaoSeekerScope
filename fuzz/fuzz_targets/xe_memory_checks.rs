use daoseeker_scope::{Availability, ReasonCode, Source, Timestamp};
use daoseeker_scope_linux::fuzzing::xe_memory;
use std::collections::BTreeSet;

pub fn check(data: &[u8]) {
    let result = xe_memory(data);
    assert_eq!(result, xe_memory(data));
    assert_eq!(result.source(), Source::Drm);
    if result.availability() == Availability::Unavailable {
        assert_eq!(result.reason(), Some(ReasonCode::InvalidData));
        assert!(result.value().is_none() && result.observed_at().is_none());
        return;
    }
    assert!((96..=2824).contains(&data.len()));
    assert_eq!((data.len() - 8) % 88, 0);
    let count = u32::from_ne_bytes(data[..4].try_into().unwrap()) as usize;
    assert_eq!(count, (data.len() - 8) / 88);
    assert_eq!(&data[4..8], &[0; 4]);
    let mut instances = BTreeSet::new();
    let mut local_regions = 0;
    let mut total = 0u128;
    for region in data[8..].chunks_exact(88) {
        let class = u16::from_ne_bytes(region[..2].try_into().unwrap());
        let instance = u16::from_ne_bytes(region[2..4].try_into().unwrap());
        assert!(instance < 64 && instances.insert(instance));
        match class {
            0 => {}
            1 => {
                local_regions += 1;
                total += u128::from(u64::from_ne_bytes(region[8..16].try_into().unwrap()));
            }
            _ => panic!("unknown region class accepted"),
        }
    }
    if local_regions == 0 {
        assert_eq!(result.availability(), Availability::NotApplicable);
        assert_eq!(result.reason(), Some(ReasonCode::NotPresent));
        assert!(result.value().is_none() && result.observed_at().is_none());
    } else {
        assert!(total <= u128::from(u64::MAX));
        assert_eq!(result.value().copied().map(u128::from), Some(total));
        assert_eq!(result.observed_at(), Some(Timestamp(0)));
        assert_eq!(result.reason(), None);
    }
    // Page size, usage, visible memory and reserved fields do not set capacity.
    let mut changed = data.to_vec();
    for region in changed[8..].chunks_exact_mut(88) {
        region[4..8].fill(0x55);
        region[16..].fill(0xaa);
        if u16::from_ne_bytes(region[..2].try_into().unwrap()) == 0 {
            region[8..16].fill(0xff);
        }
    }
    assert_eq!(xe_memory(&changed), result);
    // Drivers may enumerate the same regions in a different order.
    for (output, input) in changed[8..]
        .chunks_exact_mut(88)
        .zip(data[8..].rchunks_exact(88))
    {
        output.copy_from_slice(input);
    }
    assert_eq!(xe_memory(&changed), result);
}
