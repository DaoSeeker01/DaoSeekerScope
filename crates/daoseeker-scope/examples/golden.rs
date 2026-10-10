use daoseeker_scope::*;
fn main() {
    let mut static_info = StaticSnapshot::default();
    static_info.system.cpu.brand =
        Observed::available("Fixture CPU".to_string(), Source::Custom, Timestamp(1000));
    static_info.system.cpu.logical_count = Observed::available(4, Source::Custom, Timestamp(1000));
    static_info.system.memory.total_usable_bytes =
        Observed::available(8_589_934_592, Source::Custom, Timestamp(1000));
    static_info.system.device.serial_number =
        Observed::restricted(Source::Custom, ReasonCode::PrivacyRedacted);
    let hardware = HardwareBuilder::new(Options::default())
        .with_backend(0, Fixture(static_info))
        .build()
        .expect("fixture");
    let mut snapshot = hardware.collect().expect("fixture collect");
    snapshot.collected_at = Timestamp(1000);
    println!("{}", to_json(&snapshot).expect("json"));
}
struct Fixture(StaticSnapshot);
impl Backend for Fixture {
    fn name(&self) -> &'static str {
        "fixture"
    }
    fn capabilities(&self) -> Capabilities {
        [
            "system.cpu.brand",
            "system.cpu.logical_count",
            "system.memory.total_usable_bytes",
        ]
        .into_iter()
        .map(|field| Capability::new(field, CapabilityLevel::Supported, Source::Custom))
        .collect()
    }
    fn collect_static(&mut self, _: &CollectContext) -> Result<StaticSnapshot, ScopeError> {
        Ok(self.0.clone())
    }
    fn refresh_dynamic(&mut self, _: &CollectContext) -> Result<DynamicSnapshot, ScopeError> {
        Ok(DynamicSnapshot::default())
    }
}
