//! Six fixed non-identifier registry values, read only during static collection.
use super::registry_text::{LIMIT, parse};
use daoseeker_scope_core::*;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Field {
    DeviceVendor,
    DeviceModel,
    BoardVendor,
    BoardModel,
    BiosVendor,
    BiosVersion,
}
const FIELDS: [(Field, &str); 6] = [
    (Field::DeviceVendor, "system.device.vendor"),
    (Field::DeviceModel, "system.device.model"),
    (Field::BoardVendor, "system.motherboard.vendor"),
    (Field::BoardModel, "system.motherboard.model"),
    (Field::BiosVendor, "system.firmware.vendor"),
    (Field::BiosVersion, "system.firmware.version"),
];
impl Field {
    fn name(self) -> &'static str {
        match self {
            Self::DeviceVendor => "SystemManufacturer",
            Self::DeviceModel => "SystemProductName",
            Self::BoardVendor => "BaseBoardManufacturer",
            Self::BoardModel => "BaseBoardProduct",
            Self::BiosVendor => "BIOSVendor",
            Self::BiosVersion => "BIOSVersion",
        }
    }
    fn target(self, system: &mut SystemInfo) -> &mut Observed<String> {
        match self {
            Self::DeviceVendor => &mut system.device.vendor,
            Self::DeviceModel => &mut system.device.model,
            Self::BoardVendor => &mut system.motherboard.vendor,
            Self::BoardModel => &mut system.motherboard.model,
            Self::BiosVendor => &mut system.firmware.vendor,
            Self::BiosVersion => &mut system.firmware.version,
        }
    }
}
#[repr(align(2))]
struct Buffer([u8; LIMIT]);
struct Metadata {
    kind: u32,
    bytes: usize,
}
trait Api {
    fn read(&mut self, field: Field, output: &mut Buffer) -> Result<Metadata, u32>;
}
fn failure(code: u32) -> Observed<String> {
    match code {
        2 | 3 => Observed::unavailable(Source::Win32, ReasonCode::NotPresent),
        5 | 1314 => Observed::restricted(Source::Win32, ReasonCode::PermissionDenied),
        13 | 87 | 234 | 1630 => Observed::unavailable(Source::Win32, ReasonCode::InvalidData),
        8 | 14 | 170 | 1018 | 1237 => {
            Observed::unavailable(Source::Win32, ReasonCode::TemporarilyUnavailable)
        }
        50 | 120 => Observed::missing(
            Availability::Unsupported,
            Source::Win32,
            ReasonCode::NotSupported,
        )
        .expect("unsupported registry"),
        _ => Observed::unavailable(Source::Win32, ReasonCode::Unknown),
    }
}
pub(super) fn capabilities() -> Capabilities {
    FIELDS
        .iter()
        .map(|(_, name)| Capability::new(name, CapabilityLevel::Partial, Source::Win32))
        .collect()
}
fn collect_with(
    api: &mut impl Api,
    mut check: impl FnMut() -> Result<(), ScopeError>,
) -> Result<StaticSnapshot, ScopeError> {
    let mut result = StaticSnapshot::default();
    for (field, _) in FIELDS {
        check()?;
        let mut buffer = Buffer([0; LIMIT]);
        let raw = api.read(field, &mut buffer);
        check()?;
        let observed = match raw {
            Ok(meta) if meta.bytes <= LIMIT => {
                parse(meta.kind, &buffer.0[..meta.bytes], Timestamp::now()?)
            }
            Ok(_) => failure(13),
            Err(code) => failure(code),
        };
        *field.target(&mut result.system) = observed;
    }
    Ok(result)
}
#[cfg(target_os = "windows")]
pub(super) fn collect(context: &CollectContext) -> Result<StaticSnapshot, ScopeError> {
    use windows_sys::Win32::System::Registry::{
        HKEY_LOCAL_MACHINE, RRF_NOEXPAND, RRF_RT_REG_SZ, RRF_ZEROONFAILURE, RegGetValueW,
    };
    struct Native;
    impl Api for Native {
        fn read(&mut self, field: Field, output: &mut Buffer) -> Result<Metadata, u32> {
            // Fixed ASCII whitelist, each bounded by this literal key/name length.
            let key: Vec<u16> = "HARDWARE\\DESCRIPTION\\System\\BIOS"
                .encode_utf16()
                .chain([0])
                .collect();
            let name: Vec<u16> = field.name().encode_utf16().chain([0]).collect();
            let mut kind = 0;
            let mut bytes = LIMIT as u32;
            // SAFETY: predefined borrowed key; live NUL-terminated fixed key/name;
            // initialized WCHAR-aligned output and distinct metadata, retained only
            // for this read-only call. We never close a predefined key or read failure output.
            let code = unsafe {
                RegGetValueW(
                    HKEY_LOCAL_MACHINE,
                    key.as_ptr(),
                    name.as_ptr(),
                    RRF_RT_REG_SZ | RRF_NOEXPAND | RRF_ZEROONFAILURE,
                    &mut kind,
                    output.0.as_mut_ptr().cast(),
                    &mut bytes,
                )
            };
            if code == 0 {
                Ok(Metadata {
                    kind,
                    bytes: bytes as usize,
                })
            } else {
                Err(code)
            }
        }
    }
    collect_with(&mut Native, || context.check())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    struct Fake {
        calls: Arc<AtomicUsize>,
        failure: Option<Field>,
        invalid_size: bool,
    }
    impl Fake {
        fn new() -> Self {
            Self {
                calls: Arc::new(AtomicUsize::new(0)),
                failure: None,
                invalid_size: false,
            }
        }
    }
    impl Api for Fake {
        fn read(&mut self, field: Field, buffer: &mut Buffer) -> Result<Metadata, u32> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            let wire: Vec<u8> = field
                .name()
                .encode_utf16()
                .chain([0])
                .flat_map(u16::to_le_bytes)
                .collect();
            buffer.0[..wire.len()].copy_from_slice(&wire);
            if self.failure == Some(field) {
                return Err(5);
            }
            Ok(Metadata {
                kind: 1,
                bytes: if self.invalid_size {
                    usize::MAX
                } else {
                    wire.len()
                },
            })
        }
    }
    #[test]
    fn six_field_whitelist_maps_values_and_partial_capabilities() {
        let mut api = Fake::new();
        let mut result = collect_with(&mut api, || Ok(())).unwrap();
        assert_eq!(api.calls.load(Ordering::SeqCst), 6);
        for ((field, name), cap) in FIELDS.into_iter().zip(capabilities()) {
            assert_eq!(
                field.target(&mut result.system).value().map(String::as_str),
                Some(field.name())
            );
            assert_eq!(cap.field, name);
            assert_eq!(cap.level, CapabilityLevel::Partial);
            assert_eq!(cap.source, Source::Win32);
            assert!(!field.name().to_ascii_lowercase().contains("serial"));
        }
        assert!(result.system.device.serial_number.value().is_none());
    }
    #[test]
    fn registry_status_distinguishes_missing_restricted_invalid_temporary_unsupported() {
        for (codes, state, reason) in [
            (
                &[2, 3][..],
                Availability::Unavailable,
                ReasonCode::NotPresent,
            ),
            (
                &[5, 1314][..],
                Availability::Restricted,
                ReasonCode::PermissionDenied,
            ),
            (
                &[13, 87, 234, 1630][..],
                Availability::Unavailable,
                ReasonCode::InvalidData,
            ),
            (
                &[8, 14, 170, 1018, 1237][..],
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            (
                &[50, 120][..],
                Availability::Unsupported,
                ReasonCode::NotSupported,
            ),
            (
                &[0, 999][..],
                Availability::Unavailable,
                ReasonCode::Unknown,
            ),
        ] {
            for &code in codes {
                let value = failure(code);
                assert_eq!(value.availability(), state);
                assert_eq!(value.reason(), Some(reason));
                assert!(value.value().is_none() && value.observed_at().is_none());
            }
        }
    }
    #[test]
    fn failed_field_output_is_not_consumed_and_other_fields_survive() {
        for (failed, _) in FIELDS {
            let mut api = Fake {
                failure: Some(failed),
                ..Fake::new()
            };
            let mut result = collect_with(&mut api, || Ok(())).unwrap();
            assert_eq!(api.calls.load(Ordering::SeqCst), 6);
            for (field, _) in FIELDS {
                let value = field.target(&mut result.system);
                if field == failed {
                    assert_eq!(value.reason(), Some(ReasonCode::PermissionDenied));
                    assert!(value.value().is_none());
                } else {
                    assert!(value.value().is_some());
                }
            }
        }
    }
    #[test]
    fn invalid_success_length_never_slices_out_of_bounds() {
        let mut api = Fake {
            invalid_size: true,
            ..Fake::new()
        };
        let mut result = collect_with(&mut api, || Ok(())).unwrap();
        for (field, _) in FIELDS {
            assert_eq!(
                field.target(&mut result.system).reason(),
                Some(ReasonCode::InvalidData)
            );
        }
    }
    #[test]
    fn cancellation_and_timeout_are_checked_before_and_after_each_read() {
        for code in [ErrorCode::Cancelled, ErrorCode::Timeout] {
            for at in 1..=12 {
                let mut api = Fake::new();
                let mut checks = 0;
                let result = collect_with(&mut api, || {
                    checks += 1;
                    if checks == at {
                        Err(ScopeError::new(code))
                    } else {
                        Ok(())
                    }
                });
                assert!(matches!(result,Err(error) if error.code==code));
                assert_eq!(api.calls.load(Ordering::SeqCst), at / 2);
            }
        }
    }
    struct TestBackend(Fake);
    impl Backend for TestBackend {
        fn name(&self) -> &'static str {
            "summary_fixture"
        }
        fn capabilities(&self) -> Capabilities {
            capabilities()
        }
        fn collect_static(&mut self, c: &CollectContext) -> Result<StaticSnapshot, ScopeError> {
            collect_with(&mut self.0, || c.check())
        }
        fn refresh_dynamic(&mut self, c: &CollectContext) -> Result<DynamicSnapshot, ScopeError> {
            c.check()?;
            Ok(DynamicSnapshot::default())
        }
    }
    #[test]
    fn successes_failures_and_timestamps_are_cached_until_rebuild_without_identifier_requests() {
        for privacy in [
            PrivacyOptions::default(),
            PrivacyOptions {
                include_sensitive: true,
                caller_authorized: true,
            },
        ] {
            let calls = Arc::new(AtomicUsize::new(0));
            let hardware = HardwareBuilder::new(Options {
                privacy,
                ..Options::default()
            })
            .with_backend(
                10,
                TestBackend(Fake {
                    calls: calls.clone(),
                    failure: Some(Field::BiosVersion),
                    invalid_size: false,
                }),
            )
            .build()
            .unwrap();
            let first = hardware.collect().unwrap();
            hardware.refresh_dynamic().unwrap();
            let again = hardware.collect().unwrap();
            assert_eq!(first.static_info, again.static_info);
            assert_eq!(calls.load(Ordering::SeqCst), 6);
            assert_eq!(
                first.static_info.system.firmware.version.reason(),
                Some(ReasonCode::PermissionDenied)
            );
            let rebuilt = HardwareBuilder::new(Options::default())
                .with_backend(
                    10,
                    TestBackend(Fake {
                        calls: calls.clone(),
                        failure: None,
                        invalid_size: false,
                    }),
                )
                .build()
                .unwrap()
                .collect()
                .unwrap();
            assert!(
                rebuilt
                    .static_info
                    .system
                    .firmware
                    .version
                    .value()
                    .is_some()
            );
            assert_eq!(calls.load(Ordering::SeqCst), 12);
        }
    }
}
