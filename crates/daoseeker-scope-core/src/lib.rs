//! Platform-independent, versioned observations. Units are explicit in field names.
#![forbid(unsafe_code)]
use std::fmt;
use std::time::{SystemTime, UNIX_EPOCH};

pub const SCHEMA_VERSION: u32 = 1;
pub const MAX_JSON_BYTES: usize = 1024 * 1024;

/// Milliseconds since Unix epoch; clock failure is a real collection error.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct Timestamp(pub u64);
impl Timestamp {
    pub fn now() -> Result<Self, ScopeError> {
        let duration = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| ScopeError::new(ErrorCode::BackendFailure))?;
        Ok(Self(
            u64::try_from(duration.as_millis())
                .map_err(|_| ScopeError::new(ErrorCode::BackendFailure))?,
        ))
    }
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(rename_all = "snake_case")
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub enum CapabilityLevel {
    Supported,
    Partial,
    Unsupported,
    Restricted,
    NotApplicable,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(rename_all = "snake_case")
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub enum Availability {
    Available,
    Unavailable,
    Restricted,
    Unsupported,
    NotApplicable,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(rename_all = "snake_case")
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub enum Source {
    Sysinfo,
    Wmi,
    Win32,
    Setupapi,
    Dxgi,
    Smbios,
    Sysfs,
    Procfs,
    Udev,
    Hwmon,
    Pci,
    Drm,
    Iokit,
    Sysctl,
    AppleApi,
    AndroidApi,
    WebApi,
    Hal,
    Custom,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(rename_all = "snake_case")
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub enum ReasonCode {
    PermissionDenied,
    Sandbox,
    NotSupported,
    NotPresent,
    Timeout,
    InvalidData,
    PrivacyRedacted,
    TemporarilyUnavailable,
    Unknown,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(rename_all = "snake_case")
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub enum ErrorCode {
    InvalidArgument,
    UnsupportedPlatform,
    Timeout,
    Cancelled,
    Busy,
    BackendFailure,
    ResourceLimit,
    Panic,
    InvalidBuffer,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ScopeError {
    pub code: ErrorCode,
}
impl ScopeError {
    pub const fn new(code: ErrorCode) -> Self {
        Self { code }
    }
}
impl fmt::Display for ScopeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "collection error: {:?}", self.code)
    }
}
impl std::error::Error for ScopeError {}

/// A missing value never represents a successful observation. Constructors and JSON validate this invariant.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct Observed<T> {
    value: Option<T>,
    availability: Availability,
    source: Source,
    observed_at: Option<Timestamp>,
    reason: Option<ReasonCode>,
}
impl<T> Observed<T> {
    pub fn available(value: T, source: Source, observed_at: Timestamp) -> Self {
        Self {
            value: Some(value),
            availability: Availability::Available,
            source,
            observed_at: Some(observed_at),
            reason: None,
        }
    }
    pub fn missing(
        availability: Availability,
        source: Source,
        reason: ReasonCode,
    ) -> Result<Self, ScopeError> {
        if availability == Availability::Available {
            return Err(ScopeError::new(ErrorCode::InvalidArgument));
        }
        Ok(Self {
            value: None,
            availability,
            source,
            observed_at: None,
            reason: Some(reason),
        })
    }
    pub fn unavailable(source: Source, reason: ReasonCode) -> Self {
        Self {
            value: None,
            availability: Availability::Unavailable,
            source,
            observed_at: None,
            reason: Some(reason),
        }
    }
    pub fn restricted(source: Source, reason: ReasonCode) -> Self {
        Self {
            value: None,
            availability: Availability::Restricted,
            source,
            observed_at: None,
            reason: Some(reason),
        }
    }
    pub fn not_applicable(source: Source) -> Self {
        Self {
            value: None,
            availability: Availability::NotApplicable,
            source,
            observed_at: None,
            reason: Some(ReasonCode::NotPresent),
        }
    }
    pub fn value(&self) -> Option<&T> {
        self.value.as_ref()
    }
    pub fn availability(&self) -> Availability {
        self.availability
    }
    pub fn source(&self) -> Source {
        self.source
    }
    pub fn observed_at(&self) -> Option<Timestamp> {
        self.observed_at
    }
    pub fn reason(&self) -> Option<ReasonCode> {
        self.reason
    }
}
impl<T> Default for Observed<T> {
    fn default() -> Self {
        Self {
            value: None,
            availability: Availability::Unsupported,
            source: Source::Custom,
            observed_at: None,
            reason: Some(ReasonCode::NotSupported),
        }
    }
}
#[cfg(feature = "serde")]
impl<'de, T: serde::Deserialize<'de>> serde::Deserialize<'de> for Observed<T> {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        #[derive(serde::Deserialize)]
        struct Wire<T> {
            value: Option<T>,
            availability: Availability,
            source: Source,
            observed_at: Option<Timestamp>,
            reason: Option<ReasonCode>,
        }
        let wire = Wire::<T>::deserialize(deserializer)?;
        let available = wire.availability == Availability::Available;
        if available != wire.value.is_some()
            || available != wire.observed_at.is_some()
            || available == wire.reason.is_some()
        {
            return Err(serde::de::Error::custom("inconsistent observation"));
        }
        Ok(Self {
            value: wire.value,
            availability: wire.availability,
            source: wire.source,
            observed_at: wire.observed_at,
            reason: wire.reason,
        })
    }
}
#[derive(Debug, Clone, PartialEq, Default)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(default)
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct OsInfo {
    pub name: Observed<String>,
    pub version: Observed<String>,
    pub kernel_version: Observed<String>,
}
#[derive(Debug, Clone, PartialEq, Default)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(default)
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct DeviceInfo {
    pub model: Observed<String>,
    pub vendor: Observed<String>,
    pub serial_number: Observed<String>,
}
#[derive(Debug, Clone, PartialEq, Default)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(default)
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct CpuInfo {
    pub brand: Observed<String>,
    pub architecture: Observed<String>,
    pub logical_count: Observed<u32>,
    pub physical_count: Observed<u32>,
}
#[derive(Debug, Clone, PartialEq, Default)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(default)
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct MemoryInfo {
    pub total_usable_bytes: Observed<u64>,
    pub installed_bytes: Observed<u64>,
}
#[derive(Debug, Clone, PartialEq, Default)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(default)
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct GpuInfo {
    /// Adapter product description, not a stable device identifier. Cached static data.
    pub name: Observed<String>,
    /// Dedicated video memory in bytes, excluding CPU-shared memory. Not usage or a budget.
    /// A reported zero is valid. Cached until a new Hardware instance is constructed.
    pub dedicated_memory_bytes: Observed<u64>,
}
#[derive(Debug, Clone, PartialEq, Default)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(default)
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct StorageInfo {
    pub name: Observed<String>,
    pub capacity_bytes: Observed<u64>,
}
#[derive(Debug, Clone, PartialEq, Default)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(default)
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct NetworkInfo {
    /// OS interface name; may contain user identifiers. Redacted by default.
    /// Collection ordering is not a persistent identity across refreshes.
    pub interface_name: Observed<String>,
    /// Cumulative OS interface counter in bytes, not a rate or sampling delta.
    /// May reset when the interface is recreated; valid zero is preserved.
    pub received_bytes: Observed<u64>,
    /// Cumulative transmitted bytes, with the same reset semantics as received.
    pub transmitted_bytes: Observed<u64>,
}
#[derive(Debug, Clone, PartialEq, Default)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(default)
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct BatteryInfo {
    /// Fresh reported percentage, not a remaining-time or health estimate.
    pub charge_percent: Observed<f64>,
    /// OS-reported AC state. Linux aggregates only Mains supplies: any known online
    /// is true; all known offline is false. No Mains is unavailable; charging and
    /// USB/Wireless status do not imply AC. Applies to each battery, not its wiring.
    pub on_ac_power: Observed<bool>,
}
#[derive(Debug, Clone, PartialEq, Default)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(default)
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct SensorInfo {
    /// A backend-provided label, when collected. Linux hwmon leaves labels
    /// privacy-redacted; array indices are not stable device identifiers.
    pub label: Observed<String>,
    /// Fresh backend-reported Celsius observation, not a control value or voltage.
    /// Linux routes coretemp, k10temp Tdie (channel 2) and nvme (channels 1..9).
    /// NVMe Composite may be computed and need not represent a physical point.
    pub temperature_celsius: Observed<f64>,
}
#[derive(Debug, Clone, PartialEq, Default)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(default)
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct MotherboardInfo {
    pub vendor: Observed<String>,
    pub model: Observed<String>,
}
#[derive(Debug, Clone, PartialEq, Default)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(default)
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct FirmwareInfo {
    pub vendor: Observed<String>,
    pub version: Observed<String>,
}
#[derive(Debug, Clone, PartialEq, Default)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(default)
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct DisplayInfo {
    /// Backend-reported product description, not a stable device identifier.
    pub name: Observed<String>,
    /// Cached pixel width; Windows CCD reports the target signal's active size.
    /// This is not a promise of panel-native resolution or logical DPI coordinates.
    pub width_pixels: Observed<u32>,
    /// Cached pixel height, using the same platform extent as `width_pixels`.
    pub height_pixels: Observed<u32>,
}
#[derive(Debug, Clone, PartialEq, Default)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(default)
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct RuntimeInfo {
    pub uptime_seconds: Observed<u64>,
}
#[derive(Debug, Clone, PartialEq, Default)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(default)
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct SystemInfo {
    pub os: OsInfo,
    pub device: DeviceInfo,
    pub cpu: CpuInfo,
    pub memory: MemoryInfo,
    pub motherboard: MotherboardInfo,
    pub firmware: FirmwareInfo,
}
#[derive(Debug, Clone, PartialEq, Default)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(default)
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct StaticSnapshot {
    pub system: SystemInfo,
    pub gpus: Observed<Vec<GpuInfo>>,
    pub storage: Observed<Vec<StorageInfo>>,
    pub displays: Observed<Vec<DisplayInfo>>,
}
#[derive(Debug, Clone, PartialEq, Default)]
#[non_exhaustive]
#[cfg_attr(
    feature = "serde",
    derive(serde::Serialize, serde::Deserialize),
    serde(default)
)]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct DynamicSnapshot {
    pub runtime: RuntimeInfo,
    pub cpu_usage_percent: Observed<f64>,
    pub memory_available_bytes: Observed<u64>,
    pub batteries: Observed<Vec<BatteryInfo>>,
    pub sensors: Observed<Vec<SensorInfo>>,
    pub networks: Observed<Vec<NetworkInfo>>,
}

#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct Capability {
    pub field: String,
    pub level: CapabilityLevel,
    pub source: Source,
    pub reason: Option<ReasonCode>,
}
impl Capability {
    pub fn new(field: &str, level: CapabilityLevel, source: Source) -> Self {
        Self {
            field: field.into(),
            level,
            source,
            reason: None,
        }
    }
}
pub type Capabilities = Vec<Capability>;
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct MergeEvent {
    pub field: String,
    pub previous_source: Source,
    pub selected_source: Source,
    pub priority: i32,
}
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct BackendIssue {
    pub backend: String,
    pub code: ErrorCode,
}
#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
#[cfg_attr(feature = "schema", derive(schemars::JsonSchema))]
pub struct Snapshot {
    pub schema_version: u32,
    pub collected_at: Timestamp,
    pub static_info: StaticSnapshot,
    pub dynamic: DynamicSnapshot,
    pub capabilities: Capabilities,
    pub conflicts: Vec<MergeEvent>,
    pub issues: Vec<BackendIssue>,
}
mod hardware;
pub use hardware::*;
