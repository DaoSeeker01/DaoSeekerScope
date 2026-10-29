//! Development-only workload for the native memory probe; no hardware is read.
use daoseeker_scope::*;
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};

#[derive(Default)]
struct Reads {
    static_count: AtomicUsize,
    dynamic_count: AtomicUsize,
}

struct Fixture {
    sensors: bool,
    count: usize,
    reads: Arc<Reads>,
}
impl Backend for Fixture {
    fn name(&self) -> &'static str {
        if self.sensors {
            "synthetic-sensors"
        } else {
            "synthetic-networks"
        }
    }
    fn capabilities(&self) -> Capabilities {
        vec![Capability::new(
            if self.sensors { "sensors" } else { "networks" },
            CapabilityLevel::Supported,
            Source::Custom,
        )]
    }
    fn collect_static(&mut self, context: &CollectContext) -> Result<StaticSnapshot, ScopeError> {
        context.check()?;
        self.reads.static_count.fetch_add(1, Ordering::Relaxed);
        Ok(StaticSnapshot::default())
    }
    fn refresh_dynamic(&mut self, context: &CollectContext) -> Result<DynamicSnapshot, ScopeError> {
        context.check()?;
        self.reads.dynamic_count.fetch_add(1, Ordering::Relaxed);
        let at = Timestamp(1);
        let mut result = DynamicSnapshot::default();
        if self.sensors {
            result.sensors = Observed::available(
                (0..self.count)
                    .map(|index| {
                        let mut item = SensorInfo::default();
                        item.label = Observed::available(
                            format!("synthetic-sensor-{index}"),
                            Source::Custom,
                            at,
                        );
                        item.temperature_celsius = Observed::available(20.0, Source::Custom, at);
                        item
                    })
                    .collect(),
                Source::Custom,
                at,
            );
        } else {
            result.networks = Observed::available(
                (0..self.count)
                    .map(|index| {
                        let mut item = NetworkInfo::default();
                        item.interface_name = Observed::available(
                            format!("synthetic-interface-{index}"),
                            Source::Custom,
                            at,
                        );
                        item.received_bytes = Observed::available(index as u64, Source::Custom, at);
                        item.transmitted_bytes =
                            Observed::available(index as u64, Source::Custom, at);
                        item
                    })
                    .collect(),
                Source::Custom,
                at,
            );
        }
        Ok(result)
    }
}

fn validate(snapshot: &Snapshot, over_limit: bool) -> usize {
    let sensors = snapshot
        .dynamic
        .sensors
        .value()
        .expect("synthetic sensors available");
    assert_eq!(sensors.len(), 100);
    assert!(
        sensors
            .iter()
            .all(|sensor| sensor.temperature_celsius.value() == Some(&20.0))
    );
    assert_eq!(snapshot.dynamic.sensors.source(), Source::Custom);
    if over_limit {
        assert_eq!(
            snapshot.dynamic.networks.availability(),
            Availability::Unavailable
        );
        assert_eq!(
            snapshot.dynamic.networks.reason(),
            Some(ReasonCode::InvalidData)
        );
        assert!(snapshot.dynamic.networks.value().is_none());
    } else {
        let networks = snapshot
            .dynamic
            .networks
            .value()
            .expect("synthetic networks available");
        assert_eq!(networks.len(), 1024);
        assert!(
            networks
                .iter()
                .all(|network| network.interface_name.value().is_none()
                    && network.interface_name.reason() == Some(ReasonCode::PrivacyRedacted))
        );
    }
    assert_eq!(snapshot.dynamic.networks.source(), Source::Custom);
    assert_eq!(
        snapshot.static_info.system.device.serial_number.reason(),
        Some(ReasonCode::PrivacyRedacted)
    );
    assert!(snapshot.issues.is_empty());
    assert!(snapshot.conflicts.is_empty());
    let json = to_json(snapshot).expect("synthetic JSON validation");
    assert_eq!(
        from_json(json.as_bytes()).expect("synthetic JSON roundtrip"),
        *snapshot
    );
    json.len()
}

fn workload(profile: u32, refreshes: u32) -> Result<u64, ScopeError> {
    if profile > 1 || refreshes > 100 {
        return Err(ScopeError::new(ErrorCode::InvalidArgument));
    }
    let sensors = Arc::new(Reads::default());
    let networks = Arc::new(Reads::default());
    let hardware = HardwareBuilder::new(Options {
        max_entries: 1024,
        ..Options::default()
    })
    .with_backend(
        0,
        Fixture {
            sensors: true,
            count: 100,
            reads: sensors.clone(),
        },
    )
    .with_backend(
        100,
        Fixture {
            sensors: false,
            count: 1024 + profile as usize,
            reads: networks.clone(),
        },
    )
    .build()?;
    let mut snapshot = hardware.collect()?;
    let mut max_json = validate(&snapshot, profile == 1);
    for _ in 0..refreshes {
        snapshot.dynamic = hardware.refresh_dynamic()?;
        snapshot.capabilities = hardware.capabilities();
        max_json = max_json.max(validate(&snapshot, profile == 1));
    }
    for reads in [sensors, networks] {
        assert_eq!(reads.static_count.load(Ordering::Relaxed), 1);
        assert_eq!(
            reads.dynamic_count.load(Ordering::Relaxed),
            1 + refreshes as usize
        );
    }
    Ok(max_json as u64)
}

fn boundary(action: impl FnOnce() -> Result<u64, ScopeError> + std::panic::UnwindSafe) -> u64 {
    std::panic::catch_unwind(action)
        .ok()
        .and_then(Result::ok)
        .unwrap_or(0)
}

// SAFETY: A unique, development-only symbol with a matching C integer prototype.
// No pointers/borrowed data cross the boundary; panics become the failure sentinel.
#[unsafe(no_mangle)]
pub extern "C" fn scope_probe_synthetic(profile: u32, refreshes: u32) -> u64 {
    boundary(|| workload(profile, refreshes))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn maximum_collection_survives_json_roundtrip_and_cached_refresh() {
        assert!(workload(0, 2).expect("valid workload") <= MAX_JSON_BYTES as u64);
    }
    #[test]
    fn oversized_network_field_does_not_drop_healthy_sensors() {
        assert!(workload(1, 2).expect("isolated invalid field") > 0);
    }
    #[test]
    fn invalid_profile_and_unbounded_refresh_count_are_rejected() {
        assert_eq!(scope_probe_synthetic(2, 0), 0);
        assert_eq!(scope_probe_synthetic(0, 101), 0);
        assert_eq!(scope_probe_synthetic(u32::MAX, u32::MAX), 0);
    }
    #[test]
    fn panic_cannot_cross_the_development_c_boundary() {
        assert_eq!(boundary(|| panic!("synthetic panic")), 0);
    }
}
