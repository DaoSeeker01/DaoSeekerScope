use daoseeker_scope_core::*;

#[derive(Default)]
struct Fixture {
    static_info: StaticSnapshot,
    dynamic: DynamicSnapshot,
    caps: Capabilities,
    failing_name: Option<&'static str>,
}
impl Backend for Fixture {
    fn name(&self) -> &'static str {
        if self.failing_name == Some("panic-name") {
            panic!("name failed");
        }
        self.failing_name.unwrap_or("fixture")
    }
    fn capabilities(&self) -> Capabilities {
        self.caps.clone()
    }
    fn collect_static(&mut self, _: &CollectContext) -> Result<StaticSnapshot, ScopeError> {
        if self.failing_name.is_some() {
            return Err(ScopeError::new(ErrorCode::BackendFailure));
        }
        Ok(self.static_info.clone())
    }
    fn refresh_dynamic(&mut self, _: &CollectContext) -> Result<DynamicSnapshot, ScopeError> {
        if self.failing_name.is_some() {
            return Err(ScopeError::new(ErrorCode::BackendFailure));
        }
        Ok(self.dynamic.clone())
    }
}
fn available<T>(value: T) -> Observed<T> {
    Observed::available(value, Source::Custom, Timestamp(1))
}

#[test]
fn zero_counts_and_capacity_are_isolated() {
    let mut backend = Fixture::default();
    backend.static_info.system.cpu.logical_count = available(0);
    backend.static_info.system.cpu.physical_count = available(0);
    backend.static_info.system.memory.total_usable_bytes = available(0);
    backend.static_info.system.memory.installed_bytes = available(0);
    backend.dynamic.runtime.uptime_seconds = available(0);
    let hardware = HardwareBuilder::default()
        .with_backend(0, backend)
        .build()
        .unwrap();
    let snapshot = hardware.collect().unwrap();
    assert_eq!(
        snapshot.static_info.system.cpu.logical_count.reason(),
        Some(ReasonCode::InvalidData)
    );
    assert_eq!(
        snapshot.static_info.system.cpu.physical_count.reason(),
        Some(ReasonCode::InvalidData)
    );
    assert_eq!(
        snapshot
            .static_info
            .system
            .memory
            .total_usable_bytes
            .reason(),
        Some(ReasonCode::InvalidData)
    );
    assert_eq!(
        snapshot.static_info.system.memory.installed_bytes.reason(),
        Some(ReasonCode::InvalidData)
    );
    assert_eq!(snapshot.dynamic.runtime.uptime_seconds.value(), Some(&0));
}

#[test]
fn dynamic_memory_cannot_exceed_cached_total() {
    let mut backend = Fixture::default();
    backend.static_info.system.memory.total_usable_bytes = available(1024);
    backend.dynamic.memory_available_bytes = available(2048);
    backend.dynamic.cpu_usage_percent = available(0.0);
    let hardware = HardwareBuilder::default()
        .with_backend(0, backend)
        .build()
        .unwrap();
    let snapshot = hardware.collect().unwrap();
    assert_eq!(
        snapshot.dynamic.memory_available_bytes.reason(),
        Some(ReasonCode::InvalidData)
    );
    assert_eq!(snapshot.dynamic.cpu_usage_percent.value(), Some(&0.0));
    assert_eq!(
        hardware
            .refresh_dynamic()
            .unwrap()
            .memory_available_bytes
            .reason(),
        Some(ReasonCode::InvalidData)
    );
}

#[test]
fn unsupported_enhancement_keeps_generic_capability() {
    let mut generic = Fixture::default();
    generic.static_info.system.cpu.brand = available("CPU".to_owned());
    generic.caps.push(Capability::new(
        "system.cpu.brand",
        CapabilityLevel::Supported,
        Source::Custom,
    ));
    let mut enhancement = Fixture::default();
    enhancement.caps.push(Capability::new(
        "system.cpu.brand",
        CapabilityLevel::Unsupported,
        Source::Custom,
    ));
    let hardware = HardwareBuilder::default()
        .with_backend(0, generic)
        .with_backend(100, enhancement)
        .build()
        .unwrap();
    assert_eq!(
        hardware
            .capabilities()
            .iter()
            .find(|cap| cap.field == "system.cpu.brand")
            .unwrap()
            .level,
        CapabilityLevel::Supported
    );
    let snapshot = hardware.collect().unwrap();
    assert_eq!(
        snapshot
            .capabilities
            .iter()
            .find(|cap| cap.field == "system.cpu.brand")
            .unwrap()
            .level,
        CapabilityLevel::Supported
    );
}

#[test]
fn unadvertised_available_value_has_partial_capability() {
    let mut backend = Fixture::default();
    backend.dynamic.sensors = available(Vec::new());
    let hardware = HardwareBuilder::default()
        .with_backend(0, backend)
        .build()
        .unwrap();
    let snapshot = hardware.collect().unwrap();
    assert_eq!(
        snapshot
            .capabilities
            .iter()
            .find(|cap| cap.field == "sensors")
            .unwrap()
            .level,
        CapabilityLevel::Partial
    );
}

#[test]
fn equal_values_with_different_metadata_are_not_conflicts() {
    let mut first = Fixture::default();
    first.static_info.system.cpu.brand = available("CPU".to_owned());
    let mut second = Fixture::default();
    second.static_info.system.cpu.brand =
        Observed::available("CPU".to_owned(), Source::Sysinfo, Timestamp(2));
    let hardware = HardwareBuilder::default()
        .with_backend(0, first)
        .with_backend(100, second)
        .build()
        .unwrap();
    let snapshot = hardware.collect().unwrap();
    assert!(snapshot.conflicts.is_empty());
    assert_eq!(
        snapshot.static_info.system.cpu.brand.source(),
        Source::Sysinfo
    );
}

#[test]
fn invalid_backend_names_do_not_break_fallback_metadata() {
    for name in [
        "",
        "bad\nname",
        "panic-name",
        "观微观微观微观微观微观微观微观微观微观微观微观微观微观微观微观微观微观微观微观微观微观微",
    ] {
        let hardware = HardwareBuilder::default()
            .with_backend(
                0,
                Fixture {
                    failing_name: Some(name),
                    ..Fixture::default()
                },
            )
            .with_backend(100, Fixture::default())
            .build()
            .unwrap();
        let snapshot = hardware.collect().unwrap();
        assert_eq!(snapshot.issues.len(), 2);
        for issue in snapshot.issues {
            assert!(!issue.backend.is_empty());
            assert!(issue.backend.len() <= 128);
            assert!(!issue.backend.chars().any(char::is_control));
        }
    }
}

#[test]
fn invalid_enhancement_keeps_valid_generic_fields() {
    let mut generic = Fixture::default();
    generic.static_info.system.cpu.logical_count = available(4);
    generic.static_info.system.memory.total_usable_bytes = available(1024);
    generic.dynamic.memory_available_bytes = available(512);
    let mut invalid = Fixture::default();
    invalid.static_info.system.cpu.logical_count = available(0);
    invalid.static_info.system.memory.total_usable_bytes = available(0);
    invalid.dynamic.memory_available_bytes = available(2048);
    let hardware = HardwareBuilder::default()
        .with_backend(0, generic)
        .with_backend(100, invalid)
        .build()
        .unwrap();
    let snapshot = hardware.collect().unwrap();
    assert_eq!(
        snapshot.static_info.system.cpu.logical_count.value(),
        Some(&4)
    );
    assert_eq!(
        snapshot
            .static_info
            .system
            .memory
            .total_usable_bytes
            .value(),
        Some(&1024)
    );
    assert_eq!(snapshot.dynamic.memory_available_bytes.value(), Some(&512));
}

#[test]
fn zero_available_memory_remains_a_real_value() {
    let mut backend = Fixture::default();
    backend.static_info.system.memory.total_usable_bytes = available(1024);
    backend.dynamic.memory_available_bytes = available(0);
    let hardware = HardwareBuilder::default()
        .with_backend(0, backend)
        .build()
        .unwrap();
    assert_eq!(
        hardware
            .collect()
            .unwrap()
            .dynamic
            .memory_available_bytes
            .value(),
        Some(&0)
    );
}
