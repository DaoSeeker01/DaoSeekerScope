use daoseeker_scope::*;
#[test]
fn desktop_minimum_real_read_and_refresh() {
    let hardware = Hardware::new().expect("desktop");
    let snapshot = hardware.collect().expect("collect");
    assert!(
        snapshot
            .static_info
            .system
            .cpu
            .logical_count
            .value()
            .is_some_and(|n| *n > 0)
    );
    assert!(
        snapshot
            .static_info
            .system
            .memory
            .total_usable_bytes
            .value()
            .is_some_and(|n| *n > 0)
    );
    assert!(snapshot.static_info.system.os.name.value().is_some());
    assert_eq!(
        snapshot.static_info.system.device.serial_number.reason(),
        Some(ReasonCode::PrivacyRedacted)
    );
    assert_eq!(
        snapshot.dynamic.cpu_usage_percent.reason(),
        Some(ReasonCode::TemporarilyUnavailable)
    );
    std::thread::sleep(std::time::Duration::from_millis(300));
    let dynamic = hardware.refresh_dynamic().expect("refresh");
    assert!(dynamic.memory_available_bytes.value().is_some());
    assert!(dynamic.runtime.uptime_seconds.value().is_some());
    #[cfg(target_os = "linux")]
    {
        assert_eq!(dynamic.memory_available_bytes.source(), Source::Procfs);
        assert_eq!(dynamic.runtime.uptime_seconds.source(), Source::Procfs);
        assert_eq!(
            snapshot
                .static_info
                .system
                .memory
                .total_usable_bytes
                .source(),
            Source::Procfs
        );
    }
    assert!(
        dynamic
            .cpu_usage_percent
            .value()
            .is_some_and(|n| n.is_finite() && (0.0..=100.0).contains(n))
    );
}
#[cfg(feature = "serde")]
#[test]
fn golden_roundtrip_and_version_rejection() {
    let bytes = include_bytes!("fixtures/snapshot-v1.json");
    let snapshot = from_json(bytes).expect("golden");
    assert_eq!(
        from_json(to_json(&snapshot).expect("json").as_bytes()).expect("roundtrip"),
        snapshot
    );
    let mutated = String::from_utf8(bytes.to_vec())
        .expect("utf8")
        .replace("\"schema_version\":1", "\"schema_version\":2");
    assert!(from_json(mutated.as_bytes()).is_err());
    assert_eq!(
        from_json(&vec![b' '; MAX_JSON_BYTES + 1])
            .expect_err("large")
            .code,
        ErrorCode::ResourceLimit
    );
}
#[cfg(feature = "serde")]
#[test]
fn exchange_rejects_invalid_values_and_oversized_collections() {
    let bytes = include_bytes!("fixtures/snapshot-v1.json");
    let mut snapshot = from_json(bytes).expect("golden");
    snapshot.dynamic.cpu_usage_percent =
        Observed::available(f64::NAN, Source::Custom, Timestamp(1));
    assert!(to_json(&snapshot).is_err());
    snapshot.dynamic.cpu_usage_percent = Observed::available(-1.0, Source::Custom, Timestamp(1));
    assert!(to_json(&snapshot).is_err());
    snapshot.dynamic.cpu_usage_percent = Observed::default();
    snapshot.dynamic.sensors = Observed::available(
        vec![SensorInfo::default(); 1025],
        Source::Custom,
        Timestamp(1),
    );
    assert!(to_json(&snapshot).is_err());
}
