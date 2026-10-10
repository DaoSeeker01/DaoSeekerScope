use daoseeker_scope::*;

struct NetworkBackend;
impl Backend for NetworkBackend {
    fn name(&self) -> &'static str {
        "network-fixture"
    }
    fn capabilities(&self) -> Capabilities {
        vec![Capability::new(
            "networks",
            CapabilityLevel::Supported,
            Source::Custom,
        )]
    }
    fn collect_static(&mut self, _: &CollectContext) -> Result<StaticSnapshot, ScopeError> {
        Ok(StaticSnapshot::default())
    }
    fn refresh_dynamic(&mut self, _: &CollectContext) -> Result<DynamicSnapshot, ScopeError> {
        let mut network = NetworkInfo::default();
        network.interface_name =
            Observed::available("customer-interface".into(), Source::Custom, Timestamp(1));
        network.received_bytes = Observed::available(0, Source::Custom, Timestamp(1));
        network.transmitted_bytes = Observed::available(u64::MAX, Source::Custom, Timestamp(1));
        let mut result = DynamicSnapshot::default();
        result.networks = Observed::available(vec![network], Source::Custom, Timestamp(1));
        Ok(result)
    }
}

#[test]
fn injected_names_are_redacted_and_counters_round_trip() {
    let hardware = HardwareBuilder::default()
        .with_backend(0, NetworkBackend)
        .build()
        .expect("build");
    let snapshot = hardware.collect().expect("collect");
    let entry = &snapshot.dynamic.networks.value().expect("network")[0];
    assert_eq!(
        entry.interface_name.availability(),
        Availability::Restricted
    );
    assert_eq!(
        entry.interface_name.reason(),
        Some(ReasonCode::PrivacyRedacted)
    );
    let json = to_json(&snapshot).expect("encode");
    assert!(!json.contains("customer-interface"));
    assert_eq!(from_json(json.as_bytes()).expect("decode"), snapshot);
}

#[test]
fn authorized_names_round_trip_and_invalid_authorization_is_rejected() {
    let mut options = Options {
        privacy: PrivacyOptions {
            include_sensitive: true,
            caller_authorized: true,
        },
        ..Options::default()
    };
    let hardware = HardwareBuilder::new(options.clone())
        .with_backend(0, NetworkBackend)
        .build()
        .expect("build");
    let snapshot = hardware.collect().expect("collect");
    assert_eq!(
        snapshot.dynamic.networks.value().expect("network")[0]
            .interface_name
            .value()
            .map(String::as_str),
        Some("customer-interface")
    );
    assert_eq!(
        from_json(to_json(&snapshot).expect("encode").as_bytes()).expect("decode"),
        snapshot
    );
    options.privacy.caller_authorized = false;
    assert_eq!(
        options.validate().expect_err("unauthorized").code,
        ErrorCode::InvalidArgument
    );
}
