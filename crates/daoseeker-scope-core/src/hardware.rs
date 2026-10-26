use crate::*;
use std::collections::BTreeMap;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicBool, AtomicUsize, Ordering},
    mpsc,
};
use std::time::{Duration, Instant};

static WORKERS: AtomicUsize = AtomicUsize::new(0);
const MAX_WORKERS: usize = 16;

/// Sensitive access requires an explicit request and caller authorization assertion.
#[derive(Debug, Clone, Copy, Default)]
pub struct PrivacyOptions {
    pub include_sensitive: bool,
    pub caller_authorized: bool,
}
impl PrivacyOptions {
    pub fn permits_sensitive(self) -> bool {
        self.include_sensitive && self.caller_authorized
    }
}
#[derive(Debug, Clone)]
pub struct Options {
    pub timeout: Duration,
    pub max_entries: usize,
    pub privacy: PrivacyOptions,
}
impl Default for Options {
    fn default() -> Self {
        Self {
            timeout: Duration::from_secs(2),
            max_entries: 128,
            privacy: PrivacyOptions::default(),
        }
    }
}
impl Options {
    pub fn validate(&self) -> Result<(), ScopeError> {
        if self.timeout < Duration::from_millis(1)
            || self.timeout > Duration::from_secs(60)
            || !(1..=1024).contains(&self.max_entries)
            || (self.privacy.include_sensitive && !self.privacy.caller_authorized)
        {
            return Err(ScopeError::new(ErrorCode::InvalidArgument));
        }
        Ok(())
    }
}
#[derive(Debug, Clone, Default)]
pub struct CancelToken(Arc<AtomicBool>);
impl CancelToken {
    pub fn cancel(&self) {
        self.0.store(true, Ordering::Release);
    }
    pub fn is_cancelled(&self) -> bool {
        self.0.load(Ordering::Acquire)
    }
}
/// Cooperative checks cannot interrupt a blocking native API. See ADR 0003.
pub struct CollectContext {
    pub options: Options,
    cancellation: CancelToken,
    deadline: Instant,
}
impl CollectContext {
    pub fn check(&self) -> Result<(), ScopeError> {
        if self.cancellation.is_cancelled() {
            Err(ScopeError::new(ErrorCode::Cancelled))
        } else if Instant::now() >= self.deadline {
            Err(ScopeError::new(ErrorCode::Timeout))
        } else {
            Ok(())
        }
    }
}
/// Implementations must avoid unbounded allocation and check context around native calls.
/// Capability queries must be pure and fast. A backend is trusted application code.
pub trait Backend: Send + 'static {
    fn name(&self) -> &'static str;
    fn capabilities(&self) -> Capabilities;
    fn collect_static(&mut self, context: &CollectContext) -> Result<StaticSnapshot, ScopeError>;
    fn refresh_dynamic(&mut self, context: &CollectContext) -> Result<DynamicSnapshot, ScopeError>;
}
struct Registered {
    priority: i32,
    backend: Box<dyn Backend>,
}
#[derive(Default)]
pub struct HardwareBuilder {
    options: Options,
    backends: Vec<Registered>,
}
impl HardwareBuilder {
    pub fn new(options: Options) -> Self {
        Self {
            options,
            backends: Vec::new(),
        }
    }
    pub fn with_backend<B: Backend>(mut self, priority: i32, backend: B) -> Self {
        self.backends.push(Registered {
            priority,
            backend: Box::new(backend),
        });
        self
    }
    pub fn build(mut self) -> Result<Hardware, ScopeError> {
        self.options.validate()?;
        if self.backends.is_empty() {
            return Err(ScopeError::new(ErrorCode::BackendFailure));
        }
        if self.backends.len() > 16 {
            return Err(ScopeError::new(ErrorCode::ResourceLimit));
        }
        self.backends.sort_by_key(|entry| entry.priority);
        let mut caps = BTreeMap::new();
        for field in FIELDS {
            caps.insert(
                field.to_string(),
                Capability::new(field, CapabilityLevel::Unsupported, Source::Custom),
            );
        }
        for entry in &self.backends {
            let values = catch_unwind(AssertUnwindSafe(|| entry.backend.capabilities()))
                .map_err(|_| ScopeError::new(ErrorCode::Panic))?;
            if values.len() > FIELDS.len() {
                return Err(ScopeError::new(ErrorCode::ResourceLimit));
            }
            for value in values {
                if caps.get(&value.field).is_some_and(|previous| {
                    value.level != CapabilityLevel::Unsupported
                        || previous.level == CapabilityLevel::Unsupported
                }) {
                    caps.insert(value.field.clone(), value);
                }
            }
        }
        if !self.options.privacy.permits_sensitive() {
            let mut cap = Capability::new(
                "system.device.serial_number",
                CapabilityLevel::Restricted,
                Source::Custom,
            );
            cap.reason = Some(ReasonCode::PrivacyRedacted);
            caps.insert(cap.field.clone(), cap);
        }
        let capabilities: Vec<_> = caps.into_values().collect();
        let published_caps = Arc::new(Mutex::new(capabilities.clone()));
        let worker_published_caps = published_caps.clone();
        let (sender, receiver) = mpsc::sync_channel::<Request>(1);
        WORKERS
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| {
                (n < MAX_WORKERS).then_some(n + 1)
            })
            .map_err(|_| ScopeError::new(ErrorCode::ResourceLimit))?;
        let permit = WorkerPermit;
        let worker_caps = capabilities.clone();
        std::thread::Builder::new()
            .name("dscope-collect".into())
            .spawn(move || {
                let _permit = permit;
                let mut cache: Option<(StaticSnapshot, Vec<MergeEvent>, Vec<BackendIssue>)> = None;
                while let Ok(request) = receiver.recv() {
                    let result = catch_unwind(AssertUnwindSafe(|| {
                        if request.dynamic_only && cache.is_none() {
                            return Err(ScopeError::new(ErrorCode::InvalidArgument));
                        }
                        request.context.check()?;
                        let static_result = if let Some(cached) = &cache {
                            cached.clone()
                        } else {
                            collect_static(&mut self.backends, &request.context)?
                        };
                        let (dynamic, mut conflicts, mut issues) = collect_dynamic(
                            &mut self.backends,
                            &request.context,
                            static_result.0.system.memory.total_usable_bytes.value,
                        )?;
                        request.context.check()?;
                        let collected_at = Timestamp::now()?;
                        cache = Some(static_result.clone());
                        conflicts.splice(0..0, static_result.1.clone());
                        issues.splice(0..0, static_result.2.clone());
                        let mut capabilities = worker_caps.clone();
                        update_capabilities(&mut capabilities, &static_result.0, &dynamic);
                        *worker_published_caps
                            .lock()
                            .unwrap_or_else(|error| error.into_inner()) = capabilities.clone();
                        Ok(Snapshot {
                            schema_version: SCHEMA_VERSION,
                            collected_at,
                            static_info: static_result.0,
                            dynamic,
                            capabilities,
                            conflicts,
                            issues,
                        })
                    }))
                    .unwrap_or_else(|_| Err(ScopeError::new(ErrorCode::Panic)));
                    let _ = request.reply.send(result);
                }
            })
            .map_err(|_| ScopeError::new(ErrorCode::ResourceLimit))?;
        Ok(Hardware {
            sender: Mutex::new(sender),
            capabilities: published_caps,
            options: self.options,
        })
    }
}
struct WorkerPermit;
impl Drop for WorkerPermit {
    fn drop(&mut self) {
        WORKERS.fetch_sub(1, Ordering::AcqRel);
    }
}
struct Request {
    dynamic_only: bool,
    context: CollectContext,
    reply: mpsc::SyncSender<Result<Snapshot, ScopeError>>,
}
/// One bounded worker per instance; calls serialize with Busy on concurrent access.
pub struct Hardware {
    sender: Mutex<mpsc::SyncSender<Request>>,
    capabilities: Arc<Mutex<Capabilities>>,
    options: Options,
}
impl Hardware {
    pub fn capabilities(&self) -> Capabilities {
        self.capabilities
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .clone()
    }
    pub fn collect(&self) -> Result<Snapshot, ScopeError> {
        self.collect_with(CancelToken::default())
    }
    pub fn collect_with(&self, cancellation: CancelToken) -> Result<Snapshot, ScopeError> {
        self.request(false, cancellation)
    }
    /// Requires one successful collect. Cached static information is not read again.
    pub fn refresh_dynamic(&self) -> Result<DynamicSnapshot, ScopeError> {
        self.refresh_dynamic_with(CancelToken::default())
    }
    pub fn refresh_dynamic_with(
        &self,
        cancellation: CancelToken,
    ) -> Result<DynamicSnapshot, ScopeError> {
        Ok(self.request(true, cancellation)?.dynamic)
    }
    fn request(
        &self,
        dynamic_only: bool,
        cancellation: CancelToken,
    ) -> Result<Snapshot, ScopeError> {
        let deadline = Instant::now() + self.options.timeout;
        let context = CollectContext {
            options: self.options.clone(),
            cancellation: cancellation.clone(),
            deadline,
        };
        context.check()?;
        let sender = self
            .sender
            .try_lock()
            .map_err(|_| ScopeError::new(ErrorCode::Busy))?;
        let (reply, result) = mpsc::sync_channel(1);
        sender
            .try_send(Request {
                dynamic_only,
                context,
                reply,
            })
            .map_err(|error| match error {
                mpsc::TrySendError::Full(_) => ScopeError::new(ErrorCode::Busy),
                mpsc::TrySendError::Disconnected(_) => ScopeError::new(ErrorCode::BackendFailure),
            })?;
        loop {
            if cancellation.is_cancelled() {
                return Err(ScopeError::new(ErrorCode::Cancelled));
            }
            let left = deadline.saturating_duration_since(Instant::now());
            if left.is_zero() {
                cancellation.cancel();
                return Err(ScopeError::new(ErrorCode::Timeout));
            }
            match result.recv_timeout(left.min(Duration::from_millis(5))) {
                Ok(value) => return value,
                Err(mpsc::RecvTimeoutError::Timeout) => {}
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    return Err(ScopeError::new(ErrorCode::BackendFailure));
                }
            }
        }
    }
}

fn update_capabilities(
    caps: &mut Capabilities,
    static_info: &StaticSnapshot,
    dynamic: &DynamicSnapshot,
) {
    fn update<T>(caps: &mut Capabilities, field: &str, value: &Observed<T>) {
        if let Some(cap) = caps.iter_mut().find(|cap| cap.field == field) {
            cap.reason = value.reason;
            if value.availability != Availability::Unsupported {
                cap.source = value.source;
            }
            cap.level = match value.availability {
                Availability::Available
                    if !matches!(
                        cap.level,
                        CapabilityLevel::Supported | CapabilityLevel::Partial
                    ) =>
                {
                    CapabilityLevel::Partial
                }
                Availability::Restricted => CapabilityLevel::Restricted,
                Availability::NotApplicable => CapabilityLevel::NotApplicable,
                // A backend failure is captured separately; retain implementation capability for unavailable fields.
                _ => cap.level,
            };
        }
    }
    update(caps, "system.os.name", &static_info.system.os.name);
    update(caps, "system.os.version", &static_info.system.os.version);
    update(
        caps,
        "system.os.kernel_version",
        &static_info.system.os.kernel_version,
    );
    update(
        caps,
        "system.device.model",
        &static_info.system.device.model,
    );
    update(
        caps,
        "system.device.vendor",
        &static_info.system.device.vendor,
    );
    update(
        caps,
        "system.device.serial_number",
        &static_info.system.device.serial_number,
    );
    update(caps, "system.cpu.brand", &static_info.system.cpu.brand);
    update(
        caps,
        "system.cpu.architecture",
        &static_info.system.cpu.architecture,
    );
    update(
        caps,
        "system.cpu.logical_count",
        &static_info.system.cpu.logical_count,
    );
    update(
        caps,
        "system.cpu.physical_count",
        &static_info.system.cpu.physical_count,
    );
    update(
        caps,
        "system.memory.total_usable_bytes",
        &static_info.system.memory.total_usable_bytes,
    );
    update(
        caps,
        "system.memory.installed_bytes",
        &static_info.system.memory.installed_bytes,
    );
    update(
        caps,
        "system.motherboard.vendor",
        &static_info.system.motherboard.vendor,
    );
    update(
        caps,
        "system.motherboard.model",
        &static_info.system.motherboard.model,
    );
    update(
        caps,
        "system.firmware.vendor",
        &static_info.system.firmware.vendor,
    );
    update(
        caps,
        "system.firmware.version",
        &static_info.system.firmware.version,
    );
    update(caps, "gpus", &static_info.gpus);
    update(caps, "storage", &static_info.storage);
    update(caps, "displays", &static_info.displays);
    update(
        caps,
        "runtime.uptime_seconds",
        &dynamic.runtime.uptime_seconds,
    );
    update(caps, "cpu_usage_percent", &dynamic.cpu_usage_percent);
    update(
        caps,
        "memory_available_bytes",
        &dynamic.memory_available_bytes,
    );
    update(caps, "batteries", &dynamic.batteries);
    update(caps, "sensors", &dynamic.sensors);
    update(caps, "networks", &dynamic.networks);
}
const FIELDS: &[&str] = &[
    "system.os.name",
    "system.os.version",
    "system.os.kernel_version",
    "system.device.model",
    "system.device.vendor",
    "system.device.serial_number",
    "system.cpu.brand",
    "system.cpu.architecture",
    "system.cpu.logical_count",
    "system.cpu.physical_count",
    "system.memory.total_usable_bytes",
    "system.memory.installed_bytes",
    "system.motherboard.vendor",
    "system.motherboard.model",
    "system.firmware.vendor",
    "system.firmware.version",
    "gpus",
    "storage",
    "displays",
    "runtime.uptime_seconds",
    "cpu_usage_percent",
    "memory_available_bytes",
    "batteries",
    "sensors",
    "networks",
];

fn merge<T: PartialEq>(
    field: &str,
    old: &mut Observed<T>,
    next: Observed<T>,
    priority: i32,
    events: &mut Vec<MergeEvent>,
) {
    let redacted = next.reason == Some(ReasonCode::PrivacyRedacted);
    if old.reason == Some(ReasonCode::PrivacyRedacted) && !redacted {
        return;
    }
    if redacted
        || next.value.is_some()
        || (old.value.is_none() && next.availability != Availability::Unsupported)
    {
        if old.value.is_some() && next.value.is_some() && old.value != next.value {
            events.push(MergeEvent {
                field: field.into(),
                previous_source: old.source,
                selected_source: next.source,
                priority,
            });
        }
        *old = next;
    }
}
fn limit_string(value: &mut Observed<String>) {
    if value
        .value
        .as_ref()
        .is_some_and(|s| s.is_empty() || s.len() > 4096 || s.chars().any(|c| c.is_control()))
    {
        *value = Observed::unavailable(value.source, ReasonCode::InvalidData);
    }
}
fn limit_list<T>(value: &mut Observed<Vec<T>>, max: usize) {
    if value.value.as_ref().is_some_and(|v| v.len() > max) {
        *value = Observed::unavailable(value.source, ReasonCode::InvalidData);
    }
}
fn positive<T: Default + PartialEq>(value: &mut Observed<T>) {
    if value.value.as_ref().is_some_and(|n| *n == T::default()) {
        *value = Observed::unavailable(value.source, ReasonCode::InvalidData);
    }
}
fn diagnostic_name(backend: &dyn Backend) -> String {
    let name = catch_unwind(AssertUnwindSafe(|| backend.name())).unwrap_or("custom");
    if name.is_empty() || name.len() > 128 || name.chars().any(char::is_control) {
        "custom".into()
    } else {
        name.into()
    }
}
fn collect_static(
    backends: &mut [Registered],
    context: &CollectContext,
) -> Result<(StaticSnapshot, Vec<MergeEvent>, Vec<BackendIssue>), ScopeError> {
    let mut output = StaticSnapshot::default();
    let mut conflicts = Vec::new();
    let mut issues = Vec::new();
    let mut successes = 0;
    for entry in backends {
        context.check()?;
        let result = catch_unwind(AssertUnwindSafe(|| entry.backend.collect_static(context)))
            .unwrap_or_else(|_| Err(ScopeError::new(ErrorCode::Panic)));
        match result {
            Ok(mut next) => {
                successes += 1;
                if !context.options.privacy.permits_sensitive() {
                    next.system.device.serial_number =
                        Observed::restricted(Source::Custom, ReasonCode::PrivacyRedacted);
                }
                limit_string(&mut next.system.os.name);
                limit_string(&mut next.system.os.version);
                limit_string(&mut next.system.os.kernel_version);
                limit_string(&mut next.system.device.model);
                limit_string(&mut next.system.device.vendor);
                limit_string(&mut next.system.device.serial_number);
                limit_string(&mut next.system.cpu.brand);
                limit_string(&mut next.system.cpu.architecture);
                limit_string(&mut next.system.motherboard.vendor);
                limit_string(&mut next.system.motherboard.model);
                limit_string(&mut next.system.firmware.vendor);
                limit_string(&mut next.system.firmware.version);
                positive(&mut next.system.cpu.logical_count);
                positive(&mut next.system.cpu.physical_count);
                positive(&mut next.system.memory.total_usable_bytes);
                positive(&mut next.system.memory.installed_bytes);
                limit_list(&mut next.gpus, context.options.max_entries);
                limit_list(&mut next.storage, context.options.max_entries);
                limit_list(&mut next.displays, context.options.max_entries);
                if let Some(entries) = &mut next.gpus.value {
                    for item in entries {
                        limit_string(&mut item.name);
                    }
                }
                if let Some(entries) = &mut next.storage.value {
                    for item in entries {
                        if !context.options.privacy.permits_sensitive() {
                            item.name =
                                Observed::restricted(item.name.source, ReasonCode::PrivacyRedacted);
                        }
                        limit_string(&mut item.name);
                    }
                }
                if let Some(entries) = &mut next.displays.value {
                    for item in entries {
                        limit_string(&mut item.name);
                        positive(&mut item.width_pixels);
                        positive(&mut item.height_pixels);
                    }
                }
                merge(
                    "system.os.name",
                    &mut output.system.os.name,
                    next.system.os.name,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "system.os.version",
                    &mut output.system.os.version,
                    next.system.os.version,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "system.os.kernel_version",
                    &mut output.system.os.kernel_version,
                    next.system.os.kernel_version,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "system.device.model",
                    &mut output.system.device.model,
                    next.system.device.model,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "system.device.vendor",
                    &mut output.system.device.vendor,
                    next.system.device.vendor,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "system.device.serial_number",
                    &mut output.system.device.serial_number,
                    next.system.device.serial_number,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "system.cpu.brand",
                    &mut output.system.cpu.brand,
                    next.system.cpu.brand,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "system.cpu.architecture",
                    &mut output.system.cpu.architecture,
                    next.system.cpu.architecture,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "system.cpu.logical_count",
                    &mut output.system.cpu.logical_count,
                    next.system.cpu.logical_count,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "system.cpu.physical_count",
                    &mut output.system.cpu.physical_count,
                    next.system.cpu.physical_count,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "system.memory.total_usable_bytes",
                    &mut output.system.memory.total_usable_bytes,
                    next.system.memory.total_usable_bytes,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "system.memory.installed_bytes",
                    &mut output.system.memory.installed_bytes,
                    next.system.memory.installed_bytes,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "system.motherboard.vendor",
                    &mut output.system.motherboard.vendor,
                    next.system.motherboard.vendor,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "system.motherboard.model",
                    &mut output.system.motherboard.model,
                    next.system.motherboard.model,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "system.firmware.vendor",
                    &mut output.system.firmware.vendor,
                    next.system.firmware.vendor,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "system.firmware.version",
                    &mut output.system.firmware.version,
                    next.system.firmware.version,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "gpus",
                    &mut output.gpus,
                    next.gpus,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "storage",
                    &mut output.storage,
                    next.storage,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "displays",
                    &mut output.displays,
                    next.displays,
                    entry.priority,
                    &mut conflicts,
                );
            }
            Err(error) => issues.push(BackendIssue {
                backend: diagnostic_name(entry.backend.as_ref()),
                code: error.code,
            }),
        }
    }
    if successes == 0 {
        return Err(ScopeError::new(ErrorCode::BackendFailure));
    }
    Ok((output, conflicts, issues))
}
fn collect_dynamic(
    backends: &mut [Registered],
    context: &CollectContext,
    total_usable_bytes: Option<u64>,
) -> Result<(DynamicSnapshot, Vec<MergeEvent>, Vec<BackendIssue>), ScopeError> {
    let mut output = DynamicSnapshot::default();
    let mut conflicts = Vec::new();
    let mut issues = Vec::new();
    let mut successes = 0;
    for entry in backends {
        context.check()?;
        let result = catch_unwind(AssertUnwindSafe(|| entry.backend.refresh_dynamic(context)))
            .unwrap_or_else(|_| Err(ScopeError::new(ErrorCode::Panic)));
        match result {
            Ok(mut next) => {
                successes += 1;
                limit_list(&mut next.batteries, context.options.max_entries);
                limit_list(&mut next.sensors, context.options.max_entries);
                limit_list(&mut next.networks, context.options.max_entries);
                if next
                    .memory_available_bytes
                    .value
                    .zip(total_usable_bytes)
                    .is_some_and(|(available, total)| available > total)
                {
                    next.memory_available_bytes = Observed::unavailable(
                        next.memory_available_bytes.source,
                        ReasonCode::InvalidData,
                    );
                }
                if next
                    .cpu_usage_percent
                    .value
                    .is_some_and(|n| !n.is_finite() || !(0.0..=100.0).contains(&n))
                {
                    next.cpu_usage_percent = Observed::unavailable(
                        next.cpu_usage_percent.source,
                        ReasonCode::InvalidData,
                    );
                }
                if let Some(entries) = &mut next.batteries.value {
                    for item in entries {
                        if item
                            .charge_percent
                            .value
                            .is_some_and(|n| !n.is_finite() || !(0.0..=100.0).contains(&n))
                        {
                            item.charge_percent = Observed::unavailable(
                                item.charge_percent.source,
                                ReasonCode::InvalidData,
                            );
                        }
                    }
                }
                if let Some(entries) = &mut next.sensors.value {
                    for item in entries {
                        limit_string(&mut item.label);
                        if item
                            .temperature_celsius
                            .value
                            .is_some_and(|n| !n.is_finite() || !(-273.15..=1000.0).contains(&n))
                        {
                            item.temperature_celsius = Observed::unavailable(
                                item.temperature_celsius.source,
                                ReasonCode::InvalidData,
                            );
                        }
                    }
                }
                if let Some(entries) = &mut next.networks.value {
                    for item in entries {
                        if !context.options.privacy.permits_sensitive() {
                            item.interface_name = Observed::restricted(
                                item.interface_name.source,
                                ReasonCode::PrivacyRedacted,
                            );
                        }
                        limit_string(&mut item.interface_name);
                    }
                }
                merge(
                    "runtime.uptime_seconds",
                    &mut output.runtime.uptime_seconds,
                    next.runtime.uptime_seconds,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "cpu_usage_percent",
                    &mut output.cpu_usage_percent,
                    next.cpu_usage_percent,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "memory_available_bytes",
                    &mut output.memory_available_bytes,
                    next.memory_available_bytes,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "batteries",
                    &mut output.batteries,
                    next.batteries,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "sensors",
                    &mut output.sensors,
                    next.sensors,
                    entry.priority,
                    &mut conflicts,
                );
                merge(
                    "networks",
                    &mut output.networks,
                    next.networks,
                    entry.priority,
                    &mut conflicts,
                );
            }
            Err(error) => issues.push(BackendIssue {
                backend: diagnostic_name(entry.backend.as_ref()),
                code: error.code,
            }),
        }
    }
    if successes == 0 {
        return Err(ScopeError::new(ErrorCode::BackendFailure));
    }
    Ok((output, conflicts, issues))
}
