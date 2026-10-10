//! Ordinary-user Windows enhancement, compiled only on Windows.
#[cfg(target_os = "windows")]
mod native {
    use daoseeker_scope_core::*;
    use windows_sys::Win32::{
        Foundation::{ERROR_ACCESS_DENIED, ERROR_INVALID_DATA, GetLastError},
        System::{
            Power::{GetSystemPowerStatus, SYSTEM_POWER_STATUS},
            SystemInformation::GetPhysicallyInstalledSystemMemory,
        },
    };
    pub struct WindowsBackend;
    fn missing<T>() -> Observed<T> {
        // SAFETY: GetLastError has no arguments and reads this thread's last API error.
        match unsafe { GetLastError() } {
            ERROR_ACCESS_DENIED => {
                Observed::restricted(Source::Win32, ReasonCode::PermissionDenied)
            }
            ERROR_INVALID_DATA => Observed::unavailable(Source::Win32, ReasonCode::InvalidData),
            _ => Observed::unavailable(Source::Win32, ReasonCode::Unknown),
        }
    }
    impl Backend for WindowsBackend {
        fn name(&self) -> &'static str {
            "windows"
        }
        fn capabilities(&self) -> Capabilities {
            ["system.memory.installed_bytes", "batteries"]
                .into_iter()
                .map(|field| Capability::new(field, CapabilityLevel::Supported, Source::Win32))
                .collect()
        }
        fn collect_static(
            &mut self,
            context: &CollectContext,
        ) -> Result<StaticSnapshot, ScopeError> {
            context.check()?;
            let mut kib = 0u64;
            // SAFETY: kib is a live, aligned u64 out parameter for this synchronous API.
            let ok = unsafe { GetPhysicallyInstalledSystemMemory(&mut kib) };
            let observation = if ok == 0 {
                missing()
            } else {
                match kib.checked_mul(1024).filter(|n| *n > 0) {
                    Some(bytes) => Observed::available(bytes, Source::Win32, Timestamp::now()?),
                    None => Observed::unavailable(Source::Win32, ReasonCode::InvalidData),
                }
            };
            context.check()?;
            let mut result = StaticSnapshot::default();
            result.system.memory.installed_bytes = observation;
            Ok(result)
        }
        fn refresh_dynamic(
            &mut self,
            context: &CollectContext,
        ) -> Result<DynamicSnapshot, ScopeError> {
            context.check()?;
            let mut status = SYSTEM_POWER_STATUS::default();
            // SAFETY: status is a live initialized SYSTEM_POWER_STATUS out parameter.
            let ok = unsafe { GetSystemPowerStatus(&mut status) };
            let batteries = if ok == 0 {
                missing()
            } else if status.BatteryFlag == 255 {
                Observed::unavailable(Source::Win32, ReasonCode::TemporarilyUnavailable)
            } else if status.BatteryFlag & 128 != 0 {
                Observed::not_applicable(Source::Win32)
            } else {
                let at = Timestamp::now()?;
                let mut battery = BatteryInfo::default();
                battery.charge_percent = match status.BatteryLifePercent {
                    0..=100 => {
                        Observed::available(f64::from(status.BatteryLifePercent), Source::Win32, at)
                    }
                    255 => Observed::unavailable(Source::Win32, ReasonCode::TemporarilyUnavailable),
                    _ => Observed::unavailable(Source::Win32, ReasonCode::InvalidData),
                };
                battery.on_ac_power = match status.ACLineStatus {
                    0 => Observed::available(false, Source::Win32, at),
                    1 => Observed::available(true, Source::Win32, at),
                    _ => Observed::unavailable(Source::Win32, ReasonCode::TemporarilyUnavailable),
                };
                Observed::available(vec![battery], Source::Win32, at)
            };
            context.check()?;
            let mut result = DynamicSnapshot::default();
            result.batteries = batteries;
            Ok(result)
        }
    }
}
#[cfg(target_os = "windows")]
pub use native::WindowsBackend;
