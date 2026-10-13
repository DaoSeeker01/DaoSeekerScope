//! macOS public sysctl and IOMedia metadata; no private sensor interfaces.
#[cfg(feature = "fuzzing")]
#[doc(hidden)]
pub mod fuzzing;
#[cfg(any(target_os = "macos", test))]
mod network;
#[cfg(any(target_os = "macos", test, feature = "fuzzing"))]
mod network_wire;
#[cfg(any(target_os = "macos", test))]
mod storage;
#[cfg(target_os = "macos")]
mod native {
    use daoseeker_scope_core::*;
    use std::{ffi::CStr, io};
    pub struct MacosBackend;
    fn failure<T>() -> Observed<T> {
        match io::Error::last_os_error().kind() {
            io::ErrorKind::PermissionDenied => {
                Observed::restricted(Source::Sysctl, ReasonCode::PermissionDenied)
            }
            io::ErrorKind::NotFound => {
                Observed::unavailable(Source::Sysctl, ReasonCode::NotPresent)
            }
            _ => Observed::unavailable(Source::Sysctl, ReasonCode::Unknown),
        }
    }
    impl Backend for MacosBackend {
        fn name(&self) -> &'static str {
            "macos"
        }
        fn capabilities(&self) -> Capabilities {
            let mut capabilities: Capabilities =
                ["system.device.model", "system.memory.installed_bytes"]
                    .into_iter()
                    .map(|field| Capability::new(field, CapabilityLevel::Supported, Source::Sysctl))
                    .collect();
            capabilities.push(Capability::new(
                "networks",
                CapabilityLevel::Partial,
                Source::Sysctl,
            ));
            capabilities.push(Capability::new(
                "storage",
                CapabilityLevel::Partial,
                Source::Iokit,
            ));
            capabilities
        }
        fn collect_static(
            &mut self,
            context: &CollectContext,
        ) -> Result<StaticSnapshot, ScopeError> {
            context.check()?;
            let mut result = StaticSnapshot::default();
            let mut model = [0u8; 4096];
            let mut length = model.len();
            // SAFETY: literal C name; model is writable for length bytes; newp NULL means read-only.
            let ok = unsafe {
                libc::sysctlbyname(
                    c"hw.model".as_ptr(),
                    model.as_mut_ptr().cast(),
                    &mut length,
                    std::ptr::null_mut(),
                    0,
                )
            };
            result.system.device.model = if ok != 0 {
                failure()
            } else if length == 0 || length > model.len() {
                Observed::unavailable(Source::Sysctl, ReasonCode::InvalidData)
            } else {
                match CStr::from_bytes_with_nul(&model[..length])
                    .ok()
                    .and_then(|s| s.to_str().ok())
                    .filter(|s| !s.is_empty())
                {
                    Some(text) => {
                        Observed::available(text.into(), Source::Sysctl, Timestamp::now()?)
                    }
                    None => Observed::unavailable(Source::Sysctl, ReasonCode::InvalidData),
                }
            };
            context.check()?;
            let mut bytes = 0u64;
            let mut length = std::mem::size_of::<u64>();
            // SAFETY: writable aligned u64 with matching size; read-only fixed public MIB.
            let ok = unsafe {
                libc::sysctlbyname(
                    c"hw.memsize".as_ptr(),
                    (&mut bytes as *mut u64).cast(),
                    &mut length,
                    std::ptr::null_mut(),
                    0,
                )
            };
            result.system.memory.installed_bytes = if ok != 0 {
                failure()
            } else if length != std::mem::size_of::<u64>() || bytes == 0 {
                Observed::unavailable(Source::Sysctl, ReasonCode::InvalidData)
            } else {
                Observed::available(bytes, Source::Sysctl, Timestamp::now()?)
            };
            context.check()?;
            result.storage = crate::storage::collect(context)?;
            Ok(result)
        }
        fn refresh_dynamic(
            &mut self,
            context: &CollectContext,
        ) -> Result<DynamicSnapshot, ScopeError> {
            context.check()?;
            let mut result = DynamicSnapshot::default();
            result.networks = crate::network::collect(context)?;
            Ok(result)
        }
    }
}
#[cfg(target_os = "macos")]
pub use native::MacosBackend;
