//! Pure bounded 64-bit RelationGroup wire format; no native I/O.
#[derive(Clone, Copy, Debug)]
pub(super) enum WireError {
    Invalid,
    Limit,
}
pub(super) const MAX_GROUPS: usize = 16;
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub(super) struct Topology {
    pub count: u16,
    pub masks: [u64; MAX_GROUPS],
}
impl Topology {
    pub fn processors(&self) -> Result<u32, WireError> {
        if self.count == 0 {
            return Err(WireError::Invalid);
        }
        if usize::from(self.count) > MAX_GROUPS {
            return Err(WireError::Limit);
        }
        let masks = &self.masks[..usize::from(self.count)];
        if masks.contains(&0)
            || self.masks[usize::from(self.count)..]
                .iter()
                .any(|m| *m != 0)
        {
            return Err(WireError::Invalid);
        }
        Ok(masks.iter().map(|mask| mask.count_ones()).sum())
    }
}
// RelationGroup's 64-bit SDK layout. Native compile assertions and C probe verify it.
pub(super) fn parse(bytes: &[u8]) -> Result<Topology, WireError> {
    if bytes.len() < 32 || bytes.len() > 1024 {
        return Err(WireError::Invalid);
    }
    let relation = u32::from_le_bytes(bytes[0..4].try_into().expect("header"));
    let size = u32::from_le_bytes(bytes[4..8].try_into().expect("header")) as usize;
    let maximum = u16::from_le_bytes(bytes[8..10].try_into().expect("header"));
    let count = u16::from_le_bytes(bytes[10..12].try_into().expect("header"));
    if relation != 4 || size != bytes.len() || count == 0 || count > maximum {
        return Err(WireError::Invalid);
    }
    if usize::from(count) > MAX_GROUPS {
        return Err(WireError::Limit);
    }
    if bytes.len() != 32 + 48 * usize::from(count) {
        return Err(WireError::Invalid);
    }
    let mut result = Topology {
        count,
        ..Topology::default()
    };
    for index in 0..usize::from(count) {
        let start = 32 + index * 48;
        let max = bytes[start];
        let active = bytes[start + 1];
        let mask = u64::from_le_bytes(
            bytes[start + 40..start + 48]
                .try_into()
                .expect("bounded group"),
        );
        if max == 0
            || max > 64
            || active == 0
            || active > max
            || mask.count_ones() != u32::from(active)
            || (max < 64 && mask >> max != 0)
        {
            return Err(WireError::Invalid);
        }
        result.masks[index] = mask;
    }
    result.processors()?;
    Ok(result)
}
