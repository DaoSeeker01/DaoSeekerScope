use daoseeker_scope::*;
use std::{
    hint::black_box,
    time::{Duration, Instant},
};
fn main() {
    let hardware = Hardware::new().expect("hardware");
    let started = Instant::now();
    black_box(hardware.collect().expect("collect"));
    println!("first_collect_us={}", started.elapsed().as_micros());
    let mut times = Vec::with_capacity(100);
    for _ in 0..100 {
        let started = Instant::now();
        black_box(hardware.refresh_dynamic().expect("refresh"));
        times.push(started.elapsed().as_micros());
    }
    times.sort_unstable();
    println!(
        "refresh_n=100 p50_us={} p95_us={} max_us={}",
        times[49], times[94], times[99]
    );
    std::thread::sleep(Duration::from_millis(300));
    let dynamic = hardware.refresh_dynamic().expect("sample");
    println!(
        "cpu_usage_state={:?}",
        dynamic.cpu_usage_percent.availability()
    );
    let options = Options {
        max_entries: 1024,
        ..Options::default()
    };
    let synthetic = HardwareBuilder::new(options)
        .with_backend(0, StressBackend)
        .build()
        .expect("stress");
    let started = Instant::now();
    let snapshot = synthetic.collect().expect("stress collect");
    println!(
        "synthetic_sensors=100 synthetic_networks=1024 collect_us={} serialized_bytes={}",
        started.elapsed().as_micros(),
        to_json(&snapshot).expect("stress json").len()
    );
}
struct StressBackend;
impl Backend for StressBackend {
    fn name(&self) -> &'static str {
        "synthetic-stress"
    }
    fn capabilities(&self) -> Capabilities {
        ["sensors", "networks"]
            .into_iter()
            .map(|field| Capability::new(field, CapabilityLevel::Supported, Source::Custom))
            .collect()
    }
    fn collect_static(&mut self, context: &CollectContext) -> Result<StaticSnapshot, ScopeError> {
        context.check()?;
        Ok(StaticSnapshot::default())
    }
    fn refresh_dynamic(&mut self, context: &CollectContext) -> Result<DynamicSnapshot, ScopeError> {
        context.check()?;
        let at = Timestamp(1);
        let mut result = DynamicSnapshot::default();
        result.sensors = Observed::available(
            (0..100)
                .map(|index| {
                    let mut item = SensorInfo::default();
                    item.label = Observed::available(format!("sensor-{index}"), Source::Custom, at);
                    item.temperature_celsius = Observed::available(20.0, Source::Custom, at);
                    item
                })
                .collect(),
            Source::Custom,
            at,
        );
        result.networks = Observed::available(
            (0..1024)
                .map(|index| {
                    let mut item = NetworkInfo::default();
                    item.interface_name =
                        Observed::available(format!("interface-{index}"), Source::Custom, at);
                    item.received_bytes = Observed::available(0, Source::Custom, at);
                    item.transmitted_bytes = Observed::available(0, Source::Custom, at);
                    item
                })
                .collect(),
            Source::Custom,
            at,
        );
        Ok(result)
    }
}
