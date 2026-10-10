//! Opt-in test hooks for the production parsers. Synthetic timestamps only.
use daoseeker_scope_core::Observed;

/// Bounded production /proc/net/dev parser; synthetic timestamp, no files.
pub fn network_dev(
    data: &[u8],
    max_entries: usize,
    sensitive: bool,
) -> Observed<Vec<daoseeker_scope_core::NetworkInfo>> {
    super::network::fuzz(data, max_entries, sensitive)
}

/// At most 16 NUL-separated frames within the first 8192 bytes, plus five fixed
/// recovery observations. Each frame's first byte controls elapsed time (low
/// two bits: 0/50/300/1000 ms) and synthetic IO (next two bits: read/denied/
/// missing/other). The remaining bytes go through the production bounded reader.
/// The fixed suffix proves malformed data clears arbitrary prior baselines and
/// that recovery, idle-only zero and busy-only 100 percent remain distinguishable.
pub fn cpu_stat(data: &[u8]) -> Vec<Observed<f64>> {
    super::cpu::fuzz_sequence(data)
}

/// Same memory parser and observation conversion used by the real backend.
/// Returns static total and dynamic available bytes; no files are opened.
pub fn meminfo(data: &[u8]) -> (Observed<u64>, Observed<u64>) {
    super::procfs::fuzz_memory(data)
}

/// Same uptime parser and observation conversion used by the real backend.
pub fn uptime(data: &[u8]) -> Observed<u64> {
    super::procfs::fuzz_uptime(data)
}

/// Production power_supply attribute parsing: percent, boolean, type validity.
/// No enumeration, files, identifiers or permission simulation.
pub fn power_supply(data: &[u8]) -> (Observed<u8>, Observed<u8>, bool) {
    super::battery::fuzz_attributes(data)
}

/// Bounded signed millidegree parser; no driver enumeration or physical reads.
pub fn hwmon_temperature(data: &[u8]) -> Observed<f64> {
    super::hwmon::fuzz_temperature(data)
}

/// Production NVMe zero-Kelvin policy, for Composite or a secondary sensor.
/// No files are opened; synthetic timestamp only. Not a stable public API.
pub fn hwmon_nvme_temperature(data: &[u8], secondary: bool) -> Observed<f64> {
    super::hwmon::fuzz_nvme_temperature(data, secondary)
}
