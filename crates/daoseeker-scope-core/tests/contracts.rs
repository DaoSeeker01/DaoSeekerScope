use daoseeker_scope_core::*;
use std::{
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
    time::{Duration, Instant},
};
#[derive(Clone)]
struct Fake {
    brand: Option<&'static str>,
    source: Source,
    static_calls: Arc<AtomicUsize>,
    dynamic_calls: Arc<AtomicUsize>,
    panic: bool,
    delay: Duration,
    entries: usize,
}
impl Default for Fake {
    fn default() -> Self {
        Self {
            brand: Some("generic"),
            source: Source::Custom,
            static_calls: Arc::default(),
            dynamic_calls: Arc::default(),
            panic: false,
            delay: Duration::ZERO,
            entries: 0,
        }
    }
}
impl Backend for Fake {
    fn name(&self) -> &'static str {
        "fake"
    }
    fn capabilities(&self) -> Capabilities {
        vec![Capability::new(
            "system.cpu.brand",
            CapabilityLevel::Supported,
            self.source,
        )]
    }
    fn collect_static(&mut self, ctx: &CollectContext) -> Result<StaticSnapshot, ScopeError> {
        self.static_calls.fetch_add(1, Ordering::SeqCst);
        if self.panic {
            panic!("broken backend");
        }
        std::thread::sleep(self.delay);
        ctx.check()?;
        let mut result = StaticSnapshot::default();
        result.system.cpu.brand = match self.brand {
            Some(brand) => Observed::available(brand.into(), self.source, Timestamp(1)),
            None => Observed::unavailable(self.source, ReasonCode::NotPresent),
        };
        // A misbehaving injected backend tries to expose a serial; core must redact it.
        result.system.device.serial_number =
            Observed::available("secret".into(), self.source, Timestamp(1));
        Ok(result)
    }
    fn refresh_dynamic(&mut self, ctx: &CollectContext) -> Result<DynamicSnapshot, ScopeError> {
        self.dynamic_calls.fetch_add(1, Ordering::SeqCst);
        if self.panic {
            panic!("broken dynamic");
        }
        ctx.check()?;
        let mut result = DynamicSnapshot::default();
        result.runtime.uptime_seconds = Observed::available(0, self.source, Timestamp(1));
        result.sensors = Observed::available(
            vec![SensorInfo::default(); self.entries],
            self.source,
            Timestamp(1),
        );
        Ok(result)
    }
}
#[test]
fn static_cache_and_dynamic_refresh_are_separate() {
    let fake = Fake::default();
    let static_calls = fake.static_calls.clone();
    let dynamic_calls = fake.dynamic_calls.clone();
    let hw = HardwareBuilder::new(Options::default())
        .with_backend(0, fake)
        .build()
        .expect("build");
    let first = hw.collect().expect("collect");
    let second = hw.collect().expect("collect");
    hw.refresh_dynamic().expect("refresh");
    assert_eq!(first.static_info, second.static_info);
    assert_eq!(static_calls.load(Ordering::SeqCst), 1);
    assert_eq!(dynamic_calls.load(Ordering::SeqCst), 3);
    assert_eq!(first.dynamic.runtime.uptime_seconds.value(), Some(&0)); // real zero is valid
}
#[test]
fn priority_and_same_priority_registration_order_are_fixed() {
    let hw = HardwareBuilder::new(Options::default())
        .with_backend(
            100,
            Fake {
                brand: Some("enhanced"),
                source: Source::Win32,
                ..Fake::default()
            },
        )
        .with_backend(0, Fake::default())
        .with_backend(
            100,
            Fake {
                brand: Some("last"),
                source: Source::Sysctl,
                ..Fake::default()
            },
        )
        .build()
        .expect("build");
    let result = hw.collect().expect("collect");
    assert_eq!(
        result
            .static_info
            .system
            .cpu
            .brand
            .value()
            .map(String::as_str),
        Some("last")
    );
    assert_eq!(
        result
            .conflicts
            .iter()
            .filter(|event| event.field == "system.cpu.brand")
            .count(),
        2
    );
    assert_eq!(
        result
            .capabilities
            .iter()
            .find(|cap| cap.field == "system.cpu.brand")
            .expect("cap")
            .source,
        Source::Sysctl
    );
}
#[test]
fn missing_enhancement_preserves_generic_value() {
    let hw = HardwareBuilder::new(Options::default())
        .with_backend(0, Fake::default())
        .with_backend(
            100,
            Fake {
                brand: None,
                source: Source::Sysfs,
                ..Fake::default()
            },
        )
        .build()
        .expect("build");
    assert_eq!(
        hw.collect()
            .expect("collect")
            .static_info
            .system
            .cpu
            .brand
            .value()
            .map(String::as_str),
        Some("generic")
    );
}
#[test]
fn privacy_is_enforced_even_for_custom_backend() {
    let hw = HardwareBuilder::new(Options::default())
        .with_backend(0, Fake::default())
        .build()
        .expect("build");
    let result = hw.collect().expect("collect");
    assert_eq!(
        result.static_info.system.device.serial_number.reason(),
        Some(ReasonCode::PrivacyRedacted)
    );
    assert_eq!(
        result
            .static_info
            .system
            .device
            .serial_number
            .availability(),
        Availability::Restricted
    );
    let options = Options {
        privacy: PrivacyOptions {
            include_sensitive: true,
            caller_authorized: true,
        },
        ..Options::default()
    };
    let hw = HardwareBuilder::new(options)
        .with_backend(0, Fake::default())
        .build()
        .expect("build");
    assert_eq!(
        hw.collect()
            .expect("collect")
            .static_info
            .system
            .device
            .serial_number
            .value()
            .map(String::as_str),
        Some("secret")
    );
}
#[test]
fn authorization_and_resource_options_are_validated() {
    let mut options = Options::default();
    options.privacy.include_sensitive = true;
    assert_eq!(
        options.validate().expect_err("auth").code,
        ErrorCode::InvalidArgument
    );
    options.privacy.include_sensitive = false;
    options.max_entries = 0;
    assert!(options.validate().is_err());
    options.max_entries = 1025;
    assert!(options.validate().is_err());
    options.max_entries = 1;
    options.timeout = Duration::ZERO;
    assert!(options.validate().is_err());
    assert!(HardwareBuilder::default().build().is_err());
}
#[test]
fn collection_limits_and_empty_collection_have_distinct_states() {
    let options = Options {
        max_entries: 100,
        ..Options::default()
    };
    let hw = HardwareBuilder::new(options)
        .with_backend(
            0,
            Fake {
                entries: 101,
                ..Fake::default()
            },
        )
        .build()
        .expect("build");
    assert_eq!(
        hw.collect().expect("collect").dynamic.sensors.reason(),
        Some(ReasonCode::InvalidData)
    );
    let hw = HardwareBuilder::default()
        .with_backend(0, Fake::default())
        .build()
        .expect("build");
    let result = hw.collect().expect("collect");
    assert_eq!(
        result.dynamic.sensors.availability(),
        Availability::Available
    );
    assert_eq!(result.dynamic.sensors.value().expect("list").len(), 0);
    assert_eq!(
        result.static_info.gpus.availability(),
        Availability::Unsupported
    );
}
#[test]
fn backend_panic_is_isolated_and_all_failed_is_error() {
    let hw = HardwareBuilder::default()
        .with_backend(
            0,
            Fake {
                panic: true,
                ..Fake::default()
            },
        )
        .with_backend(100, Fake::default())
        .build()
        .expect("build");
    let result = hw.collect().expect("fallback");
    assert_eq!(result.issues.len(), 2);
    assert!(
        result
            .issues
            .iter()
            .all(|issue| issue.code == ErrorCode::Panic)
    );
    let hw = HardwareBuilder::default()
        .with_backend(
            0,
            Fake {
                panic: true,
                ..Fake::default()
            },
        )
        .build()
        .expect("build");
    assert_eq!(
        hw.collect().expect_err("all failed").code,
        ErrorCode::BackendFailure
    );
}
#[test]
fn timeout_and_cancellation_bound_the_caller() {
    let options = Options {
        timeout: Duration::from_millis(20),
        ..Options::default()
    };
    let hw = HardwareBuilder::new(options)
        .with_backend(
            0,
            Fake {
                delay: Duration::from_millis(100),
                ..Fake::default()
            },
        )
        .build()
        .expect("build");
    let start = Instant::now();
    assert_eq!(hw.collect().expect_err("timeout").code, ErrorCode::Timeout);
    assert!(start.elapsed() < Duration::from_millis(500));
    let token = CancelToken::default();
    token.cancel();
    assert_eq!(
        hw.collect_with(token).expect_err("cancelled").code,
        ErrorCode::Cancelled
    );
}
#[test]
fn dynamic_requires_a_static_baseline() {
    let hw = HardwareBuilder::default()
        .with_backend(0, Fake::default())
        .build()
        .expect("build");
    assert_eq!(
        hw.refresh_dynamic().expect_err("no static").code,
        ErrorCode::InvalidArgument
    );
}

#[test]
fn cancelled_backend_failure_can_retry_without_committing_static_cache() {
    struct CancelOnce {
        cancellation: Option<CancelToken>,
        during_dynamic: bool,
        static_calls: Arc<AtomicUsize>,
        dynamic_calls: Arc<AtomicUsize>,
    }
    impl Backend for CancelOnce {
        fn name(&self) -> &'static str {
            "cancel-once"
        }
        fn capabilities(&self) -> Capabilities {
            Vec::new()
        }
        fn collect_static(&mut self, _: &CollectContext) -> Result<StaticSnapshot, ScopeError> {
            self.static_calls.fetch_add(1, Ordering::SeqCst);
            if !self.during_dynamic
                && let Some(token) = self.cancellation.take()
            {
                token.cancel();
                return Err(ScopeError::new(ErrorCode::BackendFailure));
            }
            Ok(StaticSnapshot::default())
        }
        fn refresh_dynamic(&mut self, _: &CollectContext) -> Result<DynamicSnapshot, ScopeError> {
            self.dynamic_calls.fetch_add(1, Ordering::SeqCst);
            if self.during_dynamic
                && let Some(token) = self.cancellation.take()
            {
                token.cancel();
                return Err(ScopeError::new(ErrorCode::BackendFailure));
            }
            Ok(DynamicSnapshot::default())
        }
    }

    for during_dynamic in [false, true] {
        let token = CancelToken::default();
        let static_calls = Arc::new(AtomicUsize::new(0));
        let dynamic_calls = Arc::new(AtomicUsize::new(0));
        let hardware = HardwareBuilder::default()
            .with_backend(
                0,
                CancelOnce {
                    cancellation: Some(token.clone()),
                    during_dynamic,
                    static_calls: static_calls.clone(),
                    dynamic_calls: dynamic_calls.clone(),
                },
            )
            .build()
            .expect("hardware");
        let capabilities = hardware.capabilities();
        assert_eq!(
            hardware.collect_with(token).expect_err("cancelled").code,
            ErrorCode::Cancelled
        );
        assert_eq!(hardware.capabilities(), capabilities);
        let recovered = hardware.collect().expect("fresh token can retry");
        assert!(recovered.issues.is_empty());
        assert_eq!(static_calls.load(Ordering::SeqCst), 2);
        hardware
            .refresh_dynamic()
            .expect("successful cache baseline");
        assert_eq!(static_calls.load(Ordering::SeqCst), 2);
        assert_eq!(
            dynamic_calls.load(Ordering::SeqCst),
            if during_dynamic { 3 } else { 2 }
        );
    }
}
#[test]
fn concurrent_call_is_busy_and_active_call_can_be_cancelled() {
    let fake = Fake {
        delay: Duration::from_millis(100),
        ..Fake::default()
    };
    let calls = fake.static_calls.clone();
    let hw = Arc::new(
        HardwareBuilder::default()
            .with_backend(0, fake)
            .build()
            .expect("build"),
    );
    let token = CancelToken::default();
    let thread_token = token.clone();
    let thread_hw = hw.clone();
    let caller = std::thread::spawn(move || thread_hw.collect_with(thread_token));
    let wait_started = Instant::now();
    while calls.load(Ordering::SeqCst) == 0 {
        assert!(wait_started.elapsed() < Duration::from_secs(1));
        std::thread::yield_now();
    }
    assert_eq!(hw.collect().expect_err("concurrent").code, ErrorCode::Busy);
    token.cancel();
    assert_eq!(
        caller.join().expect("caller").expect_err("cancel").code,
        ErrorCode::Cancelled
    );
}
#[cfg(feature = "serde")]
#[test]
fn observation_json_invariants_and_unknown_fields() {
    let valid = Observed::available(42u64, Source::Custom, Timestamp(1));
    assert_eq!(
        serde_json::from_str::<Observed<u64>>(&serde_json::to_string(&valid).expect("json"))
            .expect("roundtrip"),
        valid
    );
    for json in [
        r#"{"value":null,"availability":"available","source":"custom","observed_at":1,"reason":null}"#,
        r#"{"value":42,"availability":"restricted","source":"custom","observed_at":1,"reason":"permission_denied"}"#,
        r#"{"value":null,"availability":"unavailable","source":"custom","observed_at":null,"reason":null}"#,
        r#"{"value":42,"availability":"future","source":"custom","observed_at":1,"reason":null}"#,
    ] {
        assert!(serde_json::from_str::<Observed<u64>>(json).is_err());
    }
    let json = r#"{"value":42,"availability":"available","source":"custom","observed_at":1,"reason":null,"future_field":true}"#;
    assert!(serde_json::from_str::<Observed<u64>>(json).is_ok());
}
