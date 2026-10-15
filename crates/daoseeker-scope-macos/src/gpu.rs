//! Owned Metal device projection; no identifiers, budgets or native pointers cached.
use daoseeker_scope_core::*;

const NAME_BYTES: usize = 4097;
const MAX_NAME_UNITS: usize = 1024;
#[derive(Debug, Clone, Copy)]
struct Failure(Availability, ReasonCode);
const INVALID: Failure = Failure(Availability::Unavailable, ReasonCode::InvalidData);
impl Failure {
    fn observed<T>(self) -> Observed<T> {
        Observed::missing(self.0, Source::AppleApi, self.1).expect("failure is a missing state")
    }
}
struct RawName {
    units: usize,
    bytes: [u8; NAME_BYTES],
}
fn name(raw: &RawName, at: Timestamp) -> Observed<String> {
    if !(1..=MAX_NAME_UNITS).contains(&raw.units) {
        return INVALID.observed();
    }
    let Some(end) = raw.bytes.iter().position(|byte| *byte == 0) else {
        return INVALID.observed();
    };
    match std::str::from_utf8(&raw.bytes[..end]) {
        Ok(text)
            if !text.trim().is_empty()
                && !text.chars().any(char::is_control)
                && text.encode_utf16().count() == raw.units =>
        {
            Observed::available(text.to_owned(), Source::AppleApi, at)
        }
        _ => INVALID.observed(),
    }
}
#[cfg(any(target_os = "macos", test))]
fn memory(unified: Option<bool>) -> Observed<u64> {
    if unified == Some(true) {
        Observed::not_applicable(Source::AppleApi)
    } else {
        Observed::missing(
            Availability::Unsupported,
            Source::AppleApi,
            ReasonCode::NotSupported,
        )
        .expect("Unsupported is a missing state")
    }
}
#[cfg(any(target_os = "macos", test))]
trait Api {
    type Object;
    fn count(&mut self) -> Result<usize, Failure>;
    fn object(&mut self, index: usize) -> Result<Self::Object, Failure>;
    fn name(&mut self, object: &Self::Object) -> Result<RawName, Failure>;
    fn unified(&mut self, object: &Self::Object) -> Result<Option<bool>, Failure>;
}
#[cfg(any(target_os = "macos", test))]
fn collect_with(
    api: &mut impl Api,
    options: &Options,
    mut check: impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<Vec<GpuInfo>>, ScopeError> {
    options.validate()?;
    check()?;
    let count = api.count();
    check()?;
    let count = match count {
        Ok(count) => count,
        Err(failure) => return Ok(failure.observed()),
    };
    if count > options.max_entries {
        return Ok(INVALID.observed());
    }
    let mut entries = Vec::with_capacity(count);
    for index in 0..count {
        check()?;
        let object = api.object(index);
        check()?;
        let object = match object {
            Ok(object) => object,
            Err(failure) => return Ok(failure.observed()),
        };
        let raw_name = api.name(&object);
        check()?;
        let mut entry = GpuInfo::default();
        entry.name = match raw_name {
            Ok(raw) => name(&raw, Timestamp::now()?),
            Err(failure) => failure.observed(),
        };
        check()?;
        let unified = api.unified(&object);
        check()?;
        entry.dedicated_memory_bytes = match unified {
            Ok(unified) => memory(unified),
            Err(failure) => failure.observed(),
        };
        entries.push(entry);
    }
    check()?;
    Ok(Observed::available(
        entries,
        Source::AppleApi,
        Timestamp::now()?,
    ))
}

#[cfg(target_os = "macos")]
mod native {
    use super::*;
    use objc2::{
        available,
        rc::{Retained, autoreleasepool},
        runtime::ProtocolObject,
    };
    use objc2_foundation::{NSArray, NSUTF8StringEncoding};
    use objc2_metal::{MTLCopyAllDevices, MTLDevice};
    struct Native(Retained<NSArray<ProtocolObject<dyn MTLDevice>>>);
    impl Api for Native {
        type Object = Retained<ProtocolObject<dyn MTLDevice>>;
        fn count(&mut self) -> Result<usize, Failure> {
            Ok(self.0.count())
        }
        fn object(&mut self, index: usize) -> Result<Self::Object, Failure> {
            // The copy API returns an immutable snapshot owned for this entire call.
            Ok(self.0.objectAtIndex(index))
        }
        fn name(&mut self, object: &Self::Object) -> Result<RawName, Failure> {
            let string = object.name();
            let units = string.length();
            if !(1..=MAX_NAME_UNITS).contains(&units) {
                return Err(INVALID);
            }
            let mut bytes = [0; NAME_BYTES];
            // SAFETY: non-null pointer to the live writable buffer of NAME_BYTES
            // bytes, matching the supplied capacity. NSString is retained during
            // conversion. No pointer or borrowed string escapes this function.
            let converted = unsafe {
                string.getCString_maxLength_encoding(
                    std::ptr::NonNull::from(&mut bytes[0]).cast(),
                    bytes.len(),
                    NSUTF8StringEncoding,
                )
            };
            if !converted {
                return Err(INVALID);
            }
            Ok(RawName { units, bytes })
        }
        fn unified(&mut self, object: &Self::Object) -> Result<Option<bool>, Failure> {
            // The selector was introduced in macOS 10.15; don't raise the OS floor.
            Ok(if available!(macos = 10.15) {
                Some(object.hasUnifiedMemory())
            } else {
                None
            })
        }
    }
    pub(crate) fn collect(context: &CollectContext) -> Result<Observed<Vec<GpuInfo>>, ScopeError> {
        context.options.validate()?;
        context.check()?;
        autoreleasepool(|_| {
            context.check()?;
            let devices = MTLCopyAllDevices();
            context.check()?;
            collect_with(&mut Native(devices), &context.options, || context.check())
        })
    }
}
#[cfg(target_os = "macos")]
pub(super) use native::collect;

#[cfg(feature = "fuzzing")]
pub(crate) fn fuzz_name(data: &[u8]) -> Observed<String> {
    if data.len() >= NAME_BYTES {
        return INVALID.observed();
    }
    let mut bytes = [0; NAME_BYTES];
    bytes[..data.len()].copy_from_slice(data);
    let units = std::str::from_utf8(data)
        .map(|text| text.encode_utf16().count())
        .unwrap_or(0);
    name(&RawName { units, bytes }, Timestamp(0))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    fn raw(text: &str) -> RawName {
        let mut bytes = [0; NAME_BYTES];
        bytes[..text.len()].copy_from_slice(text.as_bytes());
        RawName {
            units: text.encode_utf16().count(),
            bytes,
        }
    }
    struct Object(usize, Arc<AtomicUsize>);
    impl Drop for Object {
        fn drop(&mut self) {
            self.1.fetch_add(1, Ordering::SeqCst);
        }
    }
    struct Fake {
        count: usize,
        denied: bool,
        fail_at: Option<usize>,
        bad_name: bool,
        unified: Option<bool>,
        drops: Arc<AtomicUsize>,
    }
    impl Fake {
        fn new(count: usize) -> Self {
            Self {
                count,
                denied: false,
                fail_at: None,
                bad_name: false,
                unified: Some(true),
                drops: Arc::new(AtomicUsize::new(0)),
            }
        }
    }
    impl Api for Fake {
        type Object = Object;
        fn count(&mut self) -> Result<usize, Failure> {
            if self.denied {
                Err(Failure(
                    Availability::Restricted,
                    ReasonCode::PermissionDenied,
                ))
            } else {
                Ok(self.count)
            }
        }
        fn object(&mut self, index: usize) -> Result<Object, Failure> {
            if self.fail_at == Some(index) {
                Err(Failure(Availability::Unavailable, ReasonCode::Unknown))
            } else {
                Ok(Object(index, self.drops.clone()))
            }
        }
        fn name(&mut self, object: &Object) -> Result<RawName, Failure> {
            if self.bad_name && object.0 == 0 {
                Err(INVALID)
            } else {
                Ok(raw("Unit GPU"))
            }
        }
        fn unified(&mut self, _: &Object) -> Result<Option<bool>, Failure> {
            Ok(self.unified)
        }
    }
    #[test]
    fn names_are_strict_and_utf16_length_prevents_embedded_nul_truncation() {
        assert_eq!(
            name(&raw("GPU 🌟"), Timestamp(1))
                .value()
                .map(String::as_str),
            Some("GPU 🌟")
        );
        for item in [
            raw(""),
            raw(" \n"),
            raw("A\0B"),
            raw("A\nB"),
            RawName {
                units: 1,
                bytes: [b'x'; NAME_BYTES],
            },
            {
                let mut r = raw("x");
                r.bytes[0] = 255;
                r
            },
            {
                let mut r = raw("GPU");
                r.units = 9;
                r
            },
        ] {
            let result = name(&item, Timestamp(1));
            assert_eq!(result.reason(), Some(ReasonCode::InvalidData));
            assert!(result.value().is_none() && result.observed_at().is_none());
        }
        assert!(
            name(&raw(&"x".repeat(MAX_NAME_UNITS)), Timestamp(1))
                .value()
                .is_some()
        );
        assert!(
            name(&raw(&"x".repeat(MAX_NAME_UNITS + 1)), Timestamp(1))
                .value()
                .is_none()
        );
    }
    #[test]
    fn unified_memory_is_not_applicable_and_discrete_or_unknown_is_unsupported() {
        for unified in [Some(true), Some(false), None] {
            let result = memory(unified);
            assert!(result.value().is_none() && result.observed_at().is_none());
            assert_eq!(result.source(), Source::AppleApi);
            assert_eq!(
                result.availability(),
                if unified == Some(true) {
                    Availability::NotApplicable
                } else {
                    Availability::Unsupported
                }
            );
        }
    }
    #[test]
    fn empty_is_success_and_count_is_bounded_before_objects_are_requested() {
        let result = collect_with(&mut Fake::new(0), &Options::default(), || Ok(())).unwrap();
        assert_eq!(result.value().unwrap().len(), 0);
        let mut fake = Fake::new(129);
        let result = collect_with(&mut fake, &Options::default(), || Ok(())).unwrap();
        assert_eq!(result.reason(), Some(ReasonCode::InvalidData));
        assert_eq!(fake.drops.load(Ordering::SeqCst), 0);
        fake.count = usize::MAX;
        assert!(
            collect_with(&mut fake, &Options::default(), || Ok(()))
                .unwrap()
                .value()
                .is_none()
        );
    }
    #[test]
    fn a_bad_name_is_isolated_and_objects_release_on_success_or_enumeration_error() {
        let mut fake = Fake::new(2);
        fake.bad_name = true;
        let result = collect_with(&mut fake, &Options::default(), || Ok(())).unwrap();
        let entries = result.value().unwrap();
        assert_eq!(entries[0].name.reason(), Some(ReasonCode::InvalidData));
        assert_eq!(
            entries[0].dedicated_memory_bytes.availability(),
            Availability::NotApplicable
        );
        assert!(entries[1].name.value().is_some());
        assert_eq!(fake.drops.load(Ordering::SeqCst), 2);
        fake.fail_at = Some(1);
        let result = collect_with(&mut fake, &Options::default(), || Ok(())).unwrap();
        assert!(result.value().is_none());
        assert_eq!(result.reason(), Some(ReasonCode::Unknown));
        assert_eq!(fake.drops.load(Ordering::SeqCst), 3);
    }
    #[test]
    fn cancellation_and_timeout_release_the_current_owned_object() {
        let mut fake = Fake::new(1);
        let mut checks = 0;
        let error = collect_with(&mut fake, &Options::default(), || {
            checks += 1;
            if checks == 5 {
                Err(ScopeError::new(ErrorCode::Cancelled))
            } else {
                Ok(())
            }
        })
        .unwrap_err();
        assert_eq!(error.code, ErrorCode::Cancelled);
        assert_eq!(fake.drops.load(Ordering::SeqCst), 1);
        assert_eq!(
            collect_with(&mut fake, &Options::default(), || Err(ScopeError::new(
                ErrorCode::Timeout
            )))
            .unwrap_err()
            .code,
            ErrorCode::Timeout
        );
    }
    #[test]
    fn backend_failure_is_not_a_successful_empty_array() {
        let mut fake = Fake::new(0);
        fake.denied = true;
        let result = collect_with(&mut fake, &Options::default(), || Ok(())).unwrap();
        assert_eq!(result.availability(), Availability::Restricted);
        assert!(result.value().is_none());
        // Synthetic interface error; real Metal enumeration has no permission out-parameter.
    }
    #[test]
    fn static_success_and_failure_stay_cached_until_new_hardware() {
        struct BackendFixture(Arc<AtomicUsize>);
        impl Backend for BackendFixture {
            fn name(&self) -> &'static str {
                "metal-fixture"
            }
            fn capabilities(&self) -> Capabilities {
                vec![]
            }
            fn collect_static(
                &mut self,
                context: &CollectContext,
            ) -> Result<StaticSnapshot, ScopeError> {
                let state = self.0.load(Ordering::SeqCst);
                let mut api = Fake::new(state.min(1));
                api.denied = state == 2;
                let mut result = StaticSnapshot::default();
                result.gpus = collect_with(&mut api, &context.options, || context.check())?;
                Ok(result)
            }
            fn refresh_dynamic(
                &mut self,
                context: &CollectContext,
            ) -> Result<DynamicSnapshot, ScopeError> {
                context.check()?;
                Ok(DynamicSnapshot::default())
            }
        }
        for initial in [1, 2] {
            let state = Arc::new(AtomicUsize::new(initial));
            let create = || {
                HardwareBuilder::default()
                    .with_backend(100, BackendFixture(state.clone()))
                    .build()
                    .unwrap()
            };
            let hardware = create();
            let first = hardware.collect().unwrap().static_info.gpus;
            state.store(0, Ordering::SeqCst);
            hardware.refresh_dynamic().unwrap();
            assert_eq!(hardware.collect().unwrap().static_info.gpus, first);
            assert!(
                create()
                    .collect()
                    .unwrap()
                    .static_info
                    .gpus
                    .value()
                    .unwrap()
                    .is_empty()
            );
        }
    }
}
