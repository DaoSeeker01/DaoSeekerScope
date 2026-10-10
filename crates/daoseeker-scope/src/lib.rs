//! 寻道者观微 / DaoSeekerScope: local desktop observations with explicit provenance.
//!
//! ```no_run
//! let hardware = daoseeker_scope::Hardware::new()?;
//! let snapshot = hardware.collect()?;
//! println!("{:?}", snapshot.static_info.system.cpu.brand.value());
//! let _dynamic = hardware.refresh_dynamic()?;
//! # Ok::<(), daoseeker_scope::ScopeError>(())
//! ```
#![forbid(unsafe_code)]
pub use daoseeker_scope_core::{
    Availability, Backend, BackendIssue, BatteryInfo, CancelToken, Capabilities, Capability,
    CapabilityLevel, CollectContext, CpuInfo, DeviceInfo, DisplayInfo, DynamicSnapshot, ErrorCode,
    FirmwareInfo, GpuInfo, HardwareBuilder, MAX_JSON_BYTES, MemoryInfo, MergeEvent,
    MotherboardInfo, NetworkInfo, Observed, Options, OsInfo, PrivacyOptions, ReasonCode,
    RuntimeInfo, SCHEMA_VERSION, ScopeError, SensorInfo, Snapshot, Source, StaticSnapshot,
    SystemInfo, Timestamp,
};
pub struct Hardware(daoseeker_scope_core::Hardware);
impl Hardware {
    pub fn new() -> Result<Self, ScopeError> {
        Self::with_options(Options::default())
    }
    pub fn with_options(options: Options) -> Result<Self, ScopeError> {
        options.validate()?;
        #[cfg(not(any(target_os = "windows", target_os = "linux", target_os = "macos")))]
        return Err(ScopeError::new(ErrorCode::UnsupportedPlatform));
        #[cfg(any(target_os = "windows", target_os = "linux", target_os = "macos"))]
        {
            let builder = HardwareBuilder::new(options)
                .with_backend(0, daoseeker_scope_sysinfo::SysinfoBackend::new());
            #[cfg(target_os = "windows")]
            let builder = builder.with_backend(100, daoseeker_scope_windows::WindowsBackend);
            #[cfg(target_os = "linux")]
            let builder = builder.with_backend(100, daoseeker_scope_linux::LinuxBackend::new());
            #[cfg(target_os = "macos")]
            let builder = builder.with_backend(100, daoseeker_scope_macos::MacosBackend);
            Ok(Self(builder.build()?))
        }
    }
    pub fn capabilities(&self) -> Capabilities {
        self.0.capabilities()
    }
    pub fn collect(&self) -> Result<Snapshot, ScopeError> {
        self.0.collect()
    }
    pub fn collect_with(&self, cancellation: CancelToken) -> Result<Snapshot, ScopeError> {
        self.0.collect_with(cancellation)
    }
    pub fn refresh_dynamic(&self) -> Result<DynamicSnapshot, ScopeError> {
        self.0.refresh_dynamic()
    }
    pub fn refresh_dynamic_with(
        &self,
        cancellation: CancelToken,
    ) -> Result<DynamicSnapshot, ScopeError> {
        self.0.refresh_dynamic_with(cancellation)
    }
}
#[cfg(feature = "serde")]
mod exchange;
#[cfg(feature = "serde")]
pub fn to_json(snapshot: &Snapshot) -> Result<String, ScopeError> {
    exchange::validate(snapshot)?;
    let mut result = Vec::with_capacity(4096);
    exchange::encode(snapshot, &mut result)?;
    String::from_utf8(result).map_err(|_| ScopeError::new(ErrorCode::InvalidArgument))
}
#[cfg(feature = "serde")]
pub fn from_json(json: &[u8]) -> Result<Snapshot, ScopeError> {
    if json.len() > MAX_JSON_BYTES {
        return Err(ScopeError::new(ErrorCode::ResourceLimit));
    }
    let result: Snapshot =
        serde_json::from_slice(json).map_err(|_| ScopeError::new(ErrorCode::InvalidArgument))?;
    exchange::validate(&result)?;
    exchange::encode(&result, std::io::sink())?;
    Ok(result)
}
