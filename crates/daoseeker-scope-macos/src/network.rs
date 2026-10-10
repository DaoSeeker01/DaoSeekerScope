use crate::network_wire::{self, MAX_BYTES};
use daoseeker_scope_core::*;

#[derive(Clone, Copy)]
struct Failure(Availability, ReasonCode);
impl Failure {
    fn observed<T>(self) -> Observed<T> {
        Observed::missing(self.0, Source::Sysctl, self.1)
            .expect("API failures only contain missing availability states")
    }
}
const INVALID: Failure = Failure(Availability::Unavailable, ReasonCode::InvalidData);
trait Api {
    fn fill(&mut self, buffer: &mut [u8], length: &mut usize) -> Result<(), Failure>;
    fn name(&mut self, index: u16) -> Result<[u8; 16], Failure>;
}

fn name(bytes: &[u8; 16], at: Timestamp) -> Observed<String> {
    let Some(end) = bytes.iter().position(|byte| *byte == 0) else {
        return INVALID.observed();
    };
    if end == 0 {
        return Observed::unavailable(Source::Sysctl, ReasonCode::NotPresent);
    }
    match std::str::from_utf8(&bytes[..end]) {
        Ok(text) if !text.trim().is_empty() && !text.chars().any(char::is_control) => {
            Observed::available(text.into(), Source::Sysctl, at)
        }
        _ => INVALID.observed(),
    }
}

fn collect_with(
    api: &mut impl Api,
    options: &Options,
    mut check: impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<Vec<NetworkInfo>>, ScopeError> {
    options.validate()?;
    check()?;
    let mut buffer = vec![0u8; MAX_BYTES];
    let mut length = buffer.len();
    let status = api.fill(&mut buffer, &mut length);
    check()?;
    if let Err(failure) = status {
        return Ok(failure.observed());
    }
    if length > buffer.len() {
        return Ok(INVALID.observed());
    }
    let counters_at = Timestamp::now()?;
    let rows = network_wire::parse(&buffer[..length], options.max_entries);
    check()?;
    let rows = match rows {
        Ok(rows) => rows,
        Err(_) => return Ok(INVALID.observed()),
    };
    let mut entries = Vec::with_capacity(rows.len());
    for row in rows {
        check()?;
        let interface_name = if options.privacy.permits_sensitive() {
            let result = api.name(row.index);
            check()?;
            match result {
                Ok(bytes) => name(&bytes, Timestamp::now()?),
                Err(failure) => failure.observed(),
            }
        } else {
            Observed::restricted(Source::Sysctl, ReasonCode::PrivacyRedacted)
        };
        let mut entry = NetworkInfo::default();
        entry.interface_name = interface_name;
        entry.received_bytes = Observed::available(row.received, Source::Sysctl, counters_at);
        entry.transmitted_bytes = Observed::available(row.transmitted, Source::Sysctl, counters_at);
        entries.push(entry);
    }
    check()?;
    Ok(Observed::available(
        entries,
        Source::Sysctl,
        Timestamp::now()?,
    ))
}

#[cfg(target_os = "macos")]
mod native {
    use super::*;
    use std::{
        io,
        mem::{offset_of, size_of},
    };

    const _: () = {
        assert!(size_of::<libc::if_msghdr2>() == network_wire::HEADER_BYTES);
        assert!(offset_of!(libc::if_msghdr2, ifm_index) == network_wire::INDEX_OFFSET);
        assert!(
            offset_of!(libc::if_msghdr2, ifm_data) + offset_of!(libc::if_data64, ifi_ibytes)
                == network_wire::RECEIVED_OFFSET
        );
        assert!(
            offset_of!(libc::if_msghdr2, ifm_data) + offset_of!(libc::if_data64, ifi_obytes)
                == network_wire::TRANSMITTED_OFFSET
        );
        assert!(size_of::<libc::ifa_msghdr>() == 20);
        assert!(size_of::<libc::ifma_msghdr2>() == 20);
        assert!(libc::IFNAMSIZ == 16);
        assert!(libc::RTM_VERSION == network_wire::VERSION as i32);
        assert!(libc::RTM_IFINFO2 == network_wire::IFINFO as i32);
        assert!(libc::RTM_NEWADDR == network_wire::NEWADDR as i32);
        assert!(libc::RTM_NEWMADDR2 == network_wire::NEWMADDR as i32);
    };

    fn failure() -> Failure {
        match io::Error::last_os_error().raw_os_error() {
            Some(libc::EACCES | libc::EPERM) => {
                Failure(Availability::Restricted, ReasonCode::PermissionDenied)
            }
            Some(libc::ENOENT | libc::ENXIO | libc::ENODEV) => {
                Failure(Availability::Unavailable, ReasonCode::NotPresent)
            }
            Some(libc::ENOTSUP) => Failure(Availability::Unsupported, ReasonCode::NotSupported),
            Some(libc::ENOMEM | libc::ENOBUFS) => Failure(
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            _ => Failure(Availability::Unavailable, ReasonCode::Unknown),
        }
    }
    struct NativeApi;
    impl Api for NativeApi {
        fn fill(&mut self, buffer: &mut [u8], length: &mut usize) -> Result<(), Failure> {
            let mut mib = [
                libc::CTL_NET,
                libc::PF_ROUTE,
                0,
                libc::AF_LINK,
                libc::NET_RT_IFLIST2,
                0,
            ];
            // SAFETY: fixed initialized MIB; oldp is writable for the supplied buffer
            // length, oldlenp points to that capacity. NULL newp makes this read-only.
            // The synchronous API copies bytes; no typed/aligned header borrow is made.
            let status = unsafe {
                libc::sysctl(
                    mib.as_mut_ptr(),
                    mib.len() as u32,
                    buffer.as_mut_ptr().cast(),
                    length,
                    std::ptr::null_mut(),
                    0,
                )
            };
            if status == 0 { Ok(()) } else { Err(failure()) }
        }
        fn name(&mut self, index: u16) -> Result<[u8; 16], Failure> {
            let mut bytes = [0u8; 16];
            // SAFETY: nonzero OS index and an initialized writable IFNAMSIZ buffer.
            // Only the returned null/non-null status is used; Rust retains ownership.
            let result =
                unsafe { libc::if_indextoname(u32::from(index), bytes.as_mut_ptr().cast()) };
            if result.is_null() {
                Err(failure())
            } else {
                Ok(bytes)
            }
        }
    }
    pub(crate) fn collect(
        context: &CollectContext,
    ) -> Result<Observed<Vec<NetworkInfo>>, ScopeError> {
        collect_with(&mut NativeApi, &context.options, || context.check())
    }
}
#[cfg(target_os = "macos")]
pub(crate) use native::collect;

#[cfg(test)]
mod tests {
    use super::*;
    use crate::network_wire::fixture;
    struct Fake {
        data: Vec<u8>,
        error: Option<Failure>,
        name_error: Option<Failure>,
        names: usize,
        oversized: bool,
    }
    impl Fake {
        fn new() -> Self {
            Self {
                data: fixture(1, 0, u64::MAX),
                error: None,
                name_error: None,
                names: 0,
                oversized: false,
            }
        }
    }
    impl Api for Fake {
        fn fill(&mut self, buffer: &mut [u8], length: &mut usize) -> Result<(), Failure> {
            assert_eq!(buffer.len(), MAX_BYTES);
            if let Some(error) = self.error {
                return Err(error);
            }
            buffer[..self.data.len()].copy_from_slice(&self.data);
            *length = if self.oversized {
                MAX_BYTES + 1
            } else {
                self.data.len()
            };
            Ok(())
        }
        fn name(&mut self, _: u16) -> Result<[u8; 16], Failure> {
            self.names += 1;
            if let Some(error) = self.name_error {
                return Err(error);
            }
            let mut bytes = [0; 16];
            bytes[..3].copy_from_slice(b"en0");
            Ok(bytes)
        }
    }
    fn collect(api: &mut Fake, options: &Options) -> Observed<Vec<NetworkInfo>> {
        collect_with(api, options, || Ok(())).expect("valid options")
    }
    #[test]
    fn default_never_queries_names_and_authorization_does_not_change_counters() {
        let mut api = Fake::new();
        let redacted = collect(&mut api, &Options::default());
        assert_eq!(api.names, 0);
        let entry = &redacted.value().expect("table")[0];
        assert_eq!(
            entry.interface_name.reason(),
            Some(ReasonCode::PrivacyRedacted)
        );
        let mut options = Options {
            privacy: PrivacyOptions {
                include_sensitive: true,
                caller_authorized: true,
            },
            ..Options::default()
        };
        let named = collect(&mut api, &options);
        let named_entry = &named.value().expect("table")[0];
        assert_eq!(
            named_entry.interface_name.value().map(String::as_str),
            Some("en0")
        );
        assert_eq!(
            named_entry.received_bytes.value(),
            entry.received_bytes.value()
        );
        assert_eq!(
            named_entry.transmitted_bytes.value(),
            entry.transmitted_bytes.value()
        );
        assert_eq!(api.names, 1);
        options.privacy.caller_authorized = false;
        assert_eq!(
            collect_with(&mut api, &options, || Ok(()))
                .expect_err("authorization required")
                .code,
            ErrorCode::InvalidArgument
        );
        assert_eq!(api.names, 1);
    }
    #[test]
    fn error_states_are_missing_and_fresh_success_recovers_without_cached_rows() {
        let mut api = Fake::new();
        assert_eq!(
            collect(&mut api, &Options::default()).availability(),
            Availability::Available
        );
        for (state, reason) in [
            (Availability::Restricted, ReasonCode::PermissionDenied),
            (Availability::Unsupported, ReasonCode::NotSupported),
            (Availability::Unavailable, ReasonCode::NotPresent),
            (
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            (Availability::Unavailable, ReasonCode::Unknown),
        ] {
            api.error = Some(Failure(state, reason));
            let failed = collect(&mut api, &Options::default());
            assert_eq!(failed.availability(), state);
            assert_eq!(failed.reason(), Some(reason));
            assert!(failed.value().is_none());
            assert!(failed.observed_at().is_none());
        }
        api.error = None;
        api.data = fixture(2, 1024, 0);
        assert_eq!(
            collect(&mut api, &Options::default())
                .value()
                .expect("recovery")[0]
                .received_bytes
                .value(),
            Some(&1024)
        );
        api.data.clear();
        assert!(
            collect(&mut api, &Options::default())
                .value()
                .expect("zero byte success")
                .is_empty()
        );
    }
    #[test]
    fn name_failure_is_isolated_and_invalid_names_never_become_identity() {
        let mut api = Fake::new();
        api.name_error = Some(Failure(Availability::Unavailable, ReasonCode::NotPresent));
        let options = Options {
            privacy: PrivacyOptions {
                include_sensitive: true,
                caller_authorized: true,
            },
            ..Options::default()
        };
        let result = collect(&mut api, &options);
        let entry = &result.value().expect("table remains available")[0];
        assert_eq!(entry.interface_name.reason(), Some(ReasonCode::NotPresent));
        assert_eq!(entry.transmitted_bytes.value(), Some(&u64::MAX));
        for bytes in [[0xff; 16], [b'x'; 16], [b'\n'; 16]] {
            assert_eq!(
                name(&bytes, Timestamp(0)).reason(),
                Some(ReasonCode::InvalidData)
            );
        }
        let mut control = [0; 16];
        control[..2].copy_from_slice(b"x\n");
        assert_eq!(
            name(&control, Timestamp(0)).reason(),
            Some(ReasonCode::InvalidData)
        );
        assert_eq!(
            name(&[0; 16], Timestamp(0)).reason(),
            Some(ReasonCode::NotPresent)
        );
        let mut maximum = [b'x'; 16];
        maximum[15] = 0;
        assert_eq!(
            name(&maximum, Timestamp(0))
                .value()
                .expect("15 bytes")
                .len(),
            15
        );
    }
    #[test]
    fn limits_and_cancellation_do_not_return_a_successful_prefix() {
        let mut api = Fake::new();
        api.oversized = true;
        assert_eq!(
            collect(&mut api, &Options::default()).reason(),
            Some(ReasonCode::InvalidData)
        );
        api.oversized = false;
        api.data.extend(fixture(2, 1, 2));
        let options = Options {
            max_entries: 1,
            ..Options::default()
        };
        assert_eq!(
            collect(&mut api, &options).reason(),
            Some(ReasonCode::InvalidData)
        );
        for code in [ErrorCode::Cancelled, ErrorCode::Timeout] {
            let mut calls = 0;
            let failure = collect_with(&mut api, &Options::default(), || {
                calls += 1;
                if calls == 2 {
                    Err(ScopeError::new(code))
                } else {
                    Ok(())
                }
            })
            .expect_err("stopped after native read");
            assert_eq!(failure.code, code);
        }
    }
}
