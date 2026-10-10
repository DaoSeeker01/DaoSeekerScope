//! Pure parser validation hooks; not a stable consumption API. No native I/O.
use daoseeker_scope_core::*;

pub fn network_route(data: &[u8], max_entries: usize) -> Observed<Vec<NetworkInfo>> {
    match crate::network_wire::parse(data, max_entries) {
        Ok(rows) => {
            let entries = rows
                .into_iter()
                .map(|row| {
                    let mut entry = NetworkInfo::default();
                    entry.interface_name =
                        Observed::restricted(Source::Sysctl, ReasonCode::PrivacyRedacted);
                    entry.received_bytes =
                        Observed::available(row.received, Source::Sysctl, Timestamp(0));
                    entry.transmitted_bytes =
                        Observed::available(row.transmitted, Source::Sysctl, Timestamp(0));
                    entry
                })
                .collect();
            Observed::available(entries, Source::Sysctl, Timestamp(0))
        }
        Err(reason) => Observed::unavailable(Source::Sysctl, reason),
    }
}
