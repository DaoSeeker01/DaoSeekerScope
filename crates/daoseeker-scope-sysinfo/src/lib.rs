//! Narrow sysinfo adapter. Process/user/device identifier enumeration is disabled.
#![forbid(unsafe_code)]
use daoseeker_scope_core::*;

/// Generic OS/CPU adapter. Linux CPU usage, memory and uptime are
/// delegated to `daoseeker-scope-linux` for explicit fresh-read failures.
/// Register both backends, or use the desktop facade, for those Linux fields.
/// On Windows, physical-memory fields require WindowsMemoryBackend or the facade.
/// Windows dynamic CPU usage requires WindowsCpuBackend or the facade.
/// Windows uptime requires WindowsBackend or the facade.
/// macOS CPU usage and logical count require MacosCpuBackend or the facade.
/// macOS memory fields require MacosMemoryBackend or the facade.
pub struct SysinfoBackend {
    system: sysinfo::System,
}
impl Default for SysinfoBackend {
    fn default() -> Self {
        Self::new()
    }
}
impl SysinfoBackend {
    pub fn new() -> Self {
        Self {
            system: sysinfo::System::new(),
        }
    }
}
fn text(value: Option<&str>, at: Timestamp) -> Observed<String> {
    match value.filter(|s| !s.trim().is_empty() && s.len() <= 4096) {
        Some(s) => Observed::available(s.trim().into(), Source::Sysinfo, at),
        None => Observed::unavailable(Source::Sysinfo, ReasonCode::Unknown),
    }
}
fn nonzero<T: Default + PartialEq>(value: T, at: Timestamp) -> Observed<T> {
    if value == T::default() {
        Observed::unavailable(Source::Sysinfo, ReasonCode::Unknown)
    } else {
        Observed::available(value, Source::Sysinfo, at)
    }
}
impl Backend for SysinfoBackend {
    fn name(&self) -> &'static str {
        "sysinfo"
    }
    fn capabilities(&self) -> Capabilities {
        [
            "system.os.name",
            "system.os.version",
            "system.os.kernel_version",
            "system.cpu.brand",
            "system.cpu.architecture",
            #[cfg(not(target_os = "macos"))]
            "system.cpu.logical_count",
            "system.cpu.physical_count",
        ]
        .into_iter()
        .map(|field| Capability::new(field, CapabilityLevel::Partial, Source::Sysinfo))
        .chain({
            #[cfg(not(any(target_os = "linux", target_os = "windows")))]
            let fields = ["runtime.uptime_seconds"];
            #[cfg(any(target_os = "linux", target_os = "windows"))]
            let fields: [&str; 0] = [];
            fields
                .into_iter()
                .map(|field| Capability::new(field, CapabilityLevel::Partial, Source::Sysinfo))
        })
        .collect()
    }
    fn collect_static(&mut self, context: &CollectContext) -> Result<StaticSnapshot, ScopeError> {
        context.check()?;
        if !sysinfo::IS_SUPPORTED_SYSTEM {
            return Err(ScopeError::new(ErrorCode::UnsupportedPlatform));
        }
        self.system
            .refresh_cpu_list(sysinfo::CpuRefreshKind::nothing());
        context.check()?;
        let at = Timestamp::now()?;
        let mut result = StaticSnapshot::default();
        result.system.os.name = text(sysinfo::System::name().as_deref(), at);
        result.system.os.version = text(sysinfo::System::os_version().as_deref(), at);
        result.system.os.kernel_version = text(sysinfo::System::kernel_version().as_deref(), at);
        result.system.cpu.architecture = text(Some(&sysinfo::System::cpu_arch()), at);
        result.system.cpu.brand = text(self.system.cpus().first().map(|cpu| cpu.brand()), at);
        #[cfg(not(target_os = "macos"))]
        {
            result.system.cpu.logical_count = match u32::try_from(self.system.cpus().len()) {
                Ok(n) => nonzero(n, at),
                Err(_) => Observed::unavailable(Source::Sysinfo, ReasonCode::InvalidData),
            };
        }
        result.system.cpu.physical_count =
            match sysinfo::System::physical_core_count().and_then(|n| u32::try_from(n).ok()) {
                Some(n) => nonzero(n, at),
                None => Observed::unavailable(Source::Sysinfo, ReasonCode::Unknown),
            };
        Ok(result)
    }
    fn refresh_dynamic(&mut self, context: &CollectContext) -> Result<DynamicSnapshot, ScopeError> {
        context.check()?;
        let result = DynamicSnapshot::default();
        #[cfg(not(any(target_os = "linux", target_os = "windows")))]
        let result = {
            let at = Timestamp::now()?;
            let mut result = result;
            result.runtime.uptime_seconds =
                Observed::available(sysinfo::System::uptime(), Source::Sysinfo, at);
            result
        };
        Ok(result)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(target_os = "macos")]
    #[test]
    fn standalone_adapter_never_masks_mach_cpu_or_memory_errors() {
        let backend = SysinfoBackend::new();
        assert!(!backend.capabilities().iter().any(|c| {
            [
                "system.cpu.logical_count",
                "cpu_usage_percent",
                "system.memory.total_usable_bytes",
                "memory_available_bytes",
            ]
            .contains(&c.field.as_str())
        }));
        let hardware = HardwareBuilder::default()
            .with_backend(0, backend)
            .build()
            .expect("build");
        let snapshot = hardware.collect().expect("collect");
        assert_eq!(
            snapshot.static_info.system.cpu.logical_count.availability(),
            Availability::Unsupported
        );
        assert_eq!(
            snapshot.dynamic.cpu_usage_percent.availability(),
            Availability::Unsupported
        );
        assert_eq!(
            snapshot
                .static_info
                .system
                .memory
                .total_usable_bytes
                .availability(),
            Availability::Unsupported
        );
        assert_eq!(
            snapshot.dynamic.memory_available_bytes.availability(),
            Availability::Unsupported
        );
    }
    #[cfg(target_os = "windows")]
    #[test]
    fn standalone_adapter_delegates_windows_memory_cpu_and_uptime() {
        let backend = SysinfoBackend::new();
        assert!(!backend.capabilities().iter().any(|c| {
            [
                "system.memory.total_usable_bytes",
                "memory_available_bytes",
                "cpu_usage_percent",
                "runtime.uptime_seconds",
            ]
            .contains(&c.field.as_str())
        }));
        let hardware = HardwareBuilder::default()
            .with_backend(0, backend)
            .build()
            .expect("build");
        let snapshot = hardware.collect().expect("collect");
        assert_eq!(
            snapshot.dynamic.runtime.uptime_seconds.availability(),
            Availability::Unsupported
        );
        assert_eq!(
            snapshot.dynamic.cpu_usage_percent.availability(),
            Availability::Unsupported
        );
        assert_eq!(
            snapshot
                .static_info
                .system
                .memory
                .total_usable_bytes
                .availability(),
            Availability::Unsupported
        );
        assert_eq!(
            snapshot.dynamic.memory_available_bytes.availability(),
            Availability::Unsupported
        );
    }
    #[cfg(target_os = "linux")]
    #[test]
    fn standalone_adapter_never_offers_a_stale_procfs_fallback() {
        let backend = SysinfoBackend::new();
        assert!(!backend.capabilities().iter().any(|cap| {
            [
                "cpu_usage_percent",
                "system.memory.total_usable_bytes",
                "memory_available_bytes",
                "runtime.uptime_seconds",
            ]
            .contains(&cap.field.as_str())
        }));
        let hardware = HardwareBuilder::default()
            .with_backend(0, backend)
            .build()
            .expect("build");
        let snapshot = hardware.collect().expect("collect");
        assert_eq!(
            snapshot.dynamic.cpu_usage_percent.availability(),
            Availability::Unsupported
        );
        for item in [
            &snapshot.dynamic.memory_available_bytes,
            &snapshot.dynamic.runtime.uptime_seconds,
            &snapshot.static_info.system.memory.total_usable_bytes,
        ] {
            assert_eq!(item.availability(), Availability::Unsupported);
        }
    }
    #[test]
    fn empty_and_zero_are_not_success() {
        assert_eq!(
            text(Some("  "), Timestamp(1)).availability(),
            Availability::Unavailable
        );
        assert_eq!(
            nonzero(0u64, Timestamp(1)).availability(),
            Availability::Unavailable
        );
        assert_eq!(nonzero(1024u64, Timestamp(1)).value(), Some(&1024));
    }
}
