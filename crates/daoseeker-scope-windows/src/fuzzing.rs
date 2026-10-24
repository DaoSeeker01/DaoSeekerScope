//! Pure synthetic parser hook, not a stable consumption API or native backend.
use daoseeker_scope_core::*;

pub fn bios_registry_text(data: &[u8]) -> Observed<String> {
    crate::registry_text::parse(1, data, Timestamp(0))
}

pub fn cpu_group_topology(data: &[u8]) -> Observed<(u16, u32)> {
    match crate::cpu_groups_wire::parse(data) {
        Ok(topology) => Observed::available(
            (
                topology.count,
                topology.processors().expect("validated topology"),
            ),
            Source::Win32,
            Timestamp(0),
        ),
        Err(crate::cpu_groups_wire::WireError::Invalid) => {
            Observed::unavailable(Source::Win32, ReasonCode::InvalidData)
        }
        Err(crate::cpu_groups_wire::WireError::Limit) => Observed::missing(
            Availability::Unsupported,
            Source::Win32,
            ReasonCode::NotSupported,
        )
        .expect("limit"),
    }
}
