//! Whole IOMedia objects; exact byte capacity, bounded iteration and owned refs.
use daoseeker_scope_core::*;

const MAX_MEDIA: usize = 4096;
const NAME_BYTES: usize = 256;
#[derive(Debug, Clone, Copy, PartialEq)]
struct Failure(Availability, ReasonCode);
const INVALID: Failure = Failure(Availability::Unavailable, ReasonCode::InvalidData);
const UNKNOWN: Failure = Failure(Availability::Unavailable, ReasonCode::Unknown);
const TEMPORARY: Failure = Failure(
    Availability::Unavailable,
    ReasonCode::TemporarilyUnavailable,
);
impl Failure {
    fn observed<T>(self) -> Observed<T> {
        Observed::missing(self.0, Source::Iokit, self.1).expect("failure is a missing state")
    }
}
fn integer_capacity(is_float: bool, value: Option<i64>) -> Result<u64, Failure> {
    if is_float {
        return Err(INVALID);
    }
    value
        .and_then(|value| u64::try_from(value).ok())
        .ok_or(INVALID)
}
fn name(bytes: &[u8; NAME_BYTES], at: Timestamp) -> Observed<String> {
    let Some(end) = bytes.iter().position(|byte| *byte == 0) else {
        return INVALID.observed();
    };
    match std::str::from_utf8(&bytes[..end]) {
        Ok(text) if !text.trim().is_empty() && !text.chars().any(char::is_control) => {
            Observed::available(text.to_owned(), Source::Iokit, at)
        }
        _ => INVALID.observed(),
    }
}
// Destruction also handles cancellation/errors/unwinding without public aliases.
struct Owned<T: Copy> {
    raw: T,
    release: fn(T),
}
impl<T: Copy> Drop for Owned<T> {
    fn drop(&mut self) {
        (self.release)(self.raw);
    }
}
trait Api {
    type Object;
    fn next(&mut self) -> Result<Option<Self::Object>, Failure>;
    fn whole(&mut self, object: &Self::Object) -> Result<bool, Failure>;
    fn capacity(&mut self, object: &Self::Object) -> Result<u64, Failure>;
    fn name(&mut self, object: &Self::Object) -> Result<[u8; NAME_BYTES], Failure>;
}
fn collect_with(
    api: &mut impl Api,
    options: &Options,
    mut check: impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<Vec<StorageInfo>>, ScopeError> {
    options.validate()?;
    let mut objects = Vec::with_capacity(options.max_entries);
    for index in 0..=MAX_MEDIA {
        check()?;
        let next = api.next();
        check()?;
        let object = match next {
            Ok(None) => break,
            Ok(Some(_)) if index == MAX_MEDIA => return Ok(INVALID.observed()),
            Ok(Some(object)) => object,
            Err(failure) => return Ok(failure.observed()),
        };
        check()?;
        let whole = api.whole(&object);
        check()?;
        match whole {
            Ok(false) => {}
            Ok(true) if objects.len() < options.max_entries => objects.push(object),
            Ok(true) => return Ok(INVALID.observed()),
            Err(failure) => return Ok(failure.observed()),
        }
    }
    let mut entries = Vec::with_capacity(objects.len());
    for object in objects {
        check()?;
        let capacity = api.capacity(&object);
        check()?;
        let mut entry = StorageInfo::default();
        entry.capacity_bytes = match capacity {
            Ok(value) => Observed::available(value, Source::Iokit, Timestamp::now()?),
            Err(failure) => failure.observed(),
        };
        entry.name = if options.privacy.permits_sensitive() {
            check()?;
            let result = api.name(&object);
            check()?;
            match result {
                Ok(bytes) => name(&bytes, Timestamp::now()?),
                Err(failure) => failure.observed(),
            }
        } else {
            Observed::restricted(Source::Iokit, ReasonCode::PrivacyRedacted)
        };
        entries.push(entry);
    }
    check()?;
    Ok(Observed::available(
        entries,
        Source::Iokit,
        Timestamp::now()?,
    ))
}

#[cfg(target_os = "macos")]
mod native {
    use super::*;
    use objc2_core_foundation::{
        CFBoolean, CFDictionary, CFNumber, CFRetained, CFString, CFStringBuiltInEncodings, CFType,
    };
    use objc2_io_kit::{
        IOIteratorIsValid, IOIteratorNext, IOObjectRelease, IORegistryEntryCreateCFProperty,
        IOServiceGetMatchingServices, IOServiceMatching, kIOReturnNoDevice as IO_NO_DEVICE,
        kIOReturnNoMemory as IO_NO_MEMORY, kIOReturnNotPermitted as IO_NOT_PERMITTED,
        kIOReturnNotPrivileged as IO_NOT_PRIVILEGED, kIOReturnNotReady as IO_NOT_READY,
        kIOReturnTimeout as IO_TIMEOUT, kIOReturnUnsupported as IO_UNSUPPORTED,
    };

    fn release(raw: u32) {
        IOObjectRelease(raw);
    }
    fn io_failure(code: u32) -> Failure {
        match code {
            IO_NOT_PERMITTED | IO_NOT_PRIVILEGED => {
                Failure(Availability::Restricted, ReasonCode::PermissionDenied)
            }
            IO_NO_DEVICE => Failure(Availability::Unavailable, ReasonCode::NotPresent),
            IO_UNSUPPORTED => Failure(Availability::Unsupported, ReasonCode::NotSupported),
            IO_TIMEOUT => Failure(Availability::Unavailable, ReasonCode::Timeout),
            IO_NO_MEMORY | IO_NOT_READY => TEMPORARY,
            _ => UNKNOWN,
        }
    }
    struct NativeApi {
        iterator: Option<Owned<u32>>,
        whole_key: CFRetained<CFString>,
        size_key: CFRetained<CFString>,
        name_key: Option<CFRetained<CFString>>,
    }
    impl NativeApi {
        fn new(sensitive: bool) -> Result<Self, Failure> {
            // SAFETY: fixed valid class C string; the opaque dictionary is not retyped.
            let matching = unsafe { IOServiceMatching(c"IOMedia".as_ptr()) }.ok_or(UNKNOWN)?;
            // Safe superclass retain; drop the mutable owner before transferring the
            // single remaining reference to the consuming API (also on its error path).
            let dictionary = CFRetained::<CFDictionary>::from(&matching);
            drop(matching);
            let mut raw = 0;
            // SAFETY: zero uses the public default port, dictionary transfers one owned
            // reference, and raw is a live fixed-size iterator output initialized to zero.
            let code = unsafe { IOServiceGetMatchingServices(0, Some(dictionary), &mut raw) };
            let iterator = (raw != 0).then(|| Owned { raw, release });
            if code != 0 {
                return Err(io_failure(code as u32));
            }
            Ok(Self {
                iterator,
                whole_key: CFString::from_str("Whole"),
                size_key: CFString::from_str("Size"),
                name_key: sensitive.then(|| CFString::from_str("BSD Name")),
            })
        }
        fn property(object: &Owned<u32>, key: &CFString) -> Result<CFRetained<CFType>, Failure> {
            // SAFETY: owned live IOMedia handle and CFString key, default allocator,
            // options zero. The binding owns the returned +1 reference and releases it.
            unsafe { IORegistryEntryCreateCFProperty(object.raw, Some(key), None, 0) }
                .ok_or(UNKNOWN)
        }
    }
    impl Api for NativeApi {
        type Object = Owned<u32>;
        fn next(&mut self) -> Result<Option<Self::Object>, Failure> {
            let Some(iterator) = &self.iterator else {
                return Ok(None);
            };
            let raw = IOIteratorNext(iterator.raw);
            if raw != 0 {
                Ok(Some(Owned { raw, release }))
            } else if IOIteratorIsValid(iterator.raw) {
                Ok(None)
            } else {
                Err(TEMPORARY)
            }
        }
        fn whole(&mut self, object: &Self::Object) -> Result<bool, Failure> {
            let property = Self::property(object, &self.whole_key)?;
            property
                .downcast_ref::<CFBoolean>()
                .map(CFBoolean::value)
                .ok_or(INVALID)
        }
        fn capacity(&mut self, object: &Self::Object) -> Result<u64, Failure> {
            let property = Self::property(object, &self.size_key)?;
            let number = property.downcast_ref::<CFNumber>().ok_or(INVALID)?;
            integer_capacity(number.is_float_type(), number.as_i64())
        }
        fn name(&mut self, object: &Self::Object) -> Result<[u8; NAME_BYTES], Failure> {
            let key = self.name_key.as_deref().ok_or(INVALID)?;
            let property = Self::property(object, key)?;
            let string = property.downcast_ref::<CFString>().ok_or(INVALID)?;
            if !(1..NAME_BYTES as isize).contains(&string.length()) {
                return Err(INVALID);
            }
            let mut bytes = [0; NAME_BYTES];
            // SAFETY: verified CFString type and fixed initialized writable buffer;
            // conversion respects capacity and reports failure instead of reallocating.
            let ok = unsafe {
                string.c_string(
                    bytes.as_mut_ptr().cast(),
                    NAME_BYTES as isize,
                    CFStringBuiltInEncodings::EncodingUTF8.0,
                )
            };
            if !ok {
                return Err(INVALID);
            }
            // UTF-8 encoding does not expand a zero UTF-16 unit. Checking the CF
            // unit count avoids accepting a prefix when an embedded NUL is present.
            let end = bytes.iter().position(|byte| *byte == 0).ok_or(INVALID)?;
            let text = std::str::from_utf8(&bytes[..end]).map_err(|_| INVALID)?;
            if text.encode_utf16().count() as isize != string.length() {
                return Err(INVALID);
            }
            Ok(bytes)
        }
    }
    pub(crate) fn collect(
        context: &CollectContext,
    ) -> Result<Observed<Vec<StorageInfo>>, ScopeError> {
        context.check()?;
        let api = NativeApi::new(context.options.privacy.permits_sensitive());
        context.check()?;
        match api {
            Ok(mut api) => collect_with(&mut api, &context.options, || context.check()),
            Err(failure) => Ok(failure.observed()),
        }
    }
    #[cfg(test)]
    mod tests {
        use super::*;
        #[test]
        fn core_foundation_types_and_exact_integer_conversion() {
            for value in [0, 1, i64::MAX] {
                let property: CFRetained<CFType> = CFNumber::new_i64(value).into();
                let number = property
                    .downcast_ref::<CFNumber>()
                    .expect("integer CFNumber");
                assert_eq!(
                    integer_capacity(number.is_float_type(), number.as_i64()),
                    Ok(value as u64)
                );
                assert!(property.downcast_ref::<CFBoolean>().is_none());
            }
            let float = CFNumber::new_f64(1.0);
            assert_eq!(
                integer_capacity(float.is_float_type(), float.as_i64()),
                Err(INVALID)
            );
            let string: CFRetained<CFType> = CFString::from_str("1").into();
            assert!(string.downcast_ref::<CFNumber>().is_none());
            let boolean = CFBoolean::new(true);
            assert!(boolean.value());
            for (code, state, reason) in [
                (
                    IO_NOT_PERMITTED,
                    Availability::Restricted,
                    ReasonCode::PermissionDenied,
                ),
                (
                    IO_UNSUPPORTED,
                    Availability::Unsupported,
                    ReasonCode::NotSupported,
                ),
                (
                    IO_NO_DEVICE,
                    Availability::Unavailable,
                    ReasonCode::NotPresent,
                ),
                (IO_TIMEOUT, Availability::Unavailable, ReasonCode::Timeout),
            ] {
                assert_eq!(io_failure(code), Failure(state, reason));
            }
        }
    }
}
#[cfg(target_os = "macos")]
pub(super) use native::collect;

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{
        Arc,
        atomic::{AtomicU64, AtomicUsize, Ordering},
    };

    struct Object {
        index: usize,
        released: Arc<AtomicUsize>,
    }
    impl Drop for Object {
        fn drop(&mut self) {
            self.released.fetch_add(1, Ordering::SeqCst);
        }
    }
    struct FakeApi {
        rows: Vec<(Result<bool, Failure>, Result<u64, Failure>)>,
        position: usize,
        invalid_end: bool,
        released: Arc<AtomicUsize>,
        capacity_calls: usize,
        name_calls: usize,
        name_error: Option<Failure>,
    }
    impl Api for FakeApi {
        type Object = Object;
        fn next(&mut self) -> Result<Option<Object>, Failure> {
            if self.position == self.rows.len() {
                return if self.invalid_end {
                    Err(TEMPORARY)
                } else {
                    Ok(None)
                };
            }
            let index = self.position;
            self.position += 1;
            Ok(Some(Object {
                index,
                released: self.released.clone(),
            }))
        }
        fn whole(&mut self, object: &Object) -> Result<bool, Failure> {
            self.rows[object.index].0
        }
        fn capacity(&mut self, object: &Object) -> Result<u64, Failure> {
            self.capacity_calls += 1;
            self.rows[object.index].1
        }
        fn name(&mut self, _: &Object) -> Result<[u8; NAME_BYTES], Failure> {
            self.name_calls += 1;
            if let Some(failure) = self.name_error {
                return Err(failure);
            }
            let mut bytes = [0; NAME_BYTES];
            bytes[..5].copy_from_slice(b"disk7");
            Ok(bytes)
        }
    }
    fn fake(rows: Vec<(Result<bool, Failure>, Result<u64, Failure>)>) -> FakeApi {
        FakeApi {
            rows,
            position: 0,
            invalid_end: false,
            released: Arc::new(AtomicUsize::new(0)),
            capacity_calls: 0,
            name_calls: 0,
            name_error: None,
        }
    }
    fn run(api: &mut FakeApi, options: &Options) -> Observed<Vec<StorageInfo>> {
        collect_with(api, options, || Ok(())).expect("fixture collection")
    }
    #[test]
    fn integer_and_name_conversion_are_strict_and_bounded() {
        for value in [0, 1, i64::MAX] {
            assert_eq!(integer_capacity(false, Some(value)), Ok(value as u64));
        }
        for result in [
            integer_capacity(false, None),
            integer_capacity(true, Some(1)),
            integer_capacity(false, Some(-1)),
            integer_capacity(false, Some(i64::MIN)),
        ] {
            assert_eq!(result, Err(INVALID));
        }
        let at = Timestamp(1);
        let mut bytes = [0; NAME_BYTES];
        let text = "磁盘 🦀".as_bytes();
        bytes[..text.len()].copy_from_slice(text);
        assert_eq!(
            name(&bytes, at).value().map(String::as_str),
            Some("磁盘 🦀")
        );
        for input in [
            [0; NAME_BYTES],
            [1; NAME_BYTES],
            [0xff; NAME_BYTES],
            [b' '; NAME_BYTES],
        ] {
            assert_eq!(name(&input, at).reason(), Some(ReasonCode::InvalidData));
        }
        bytes[0] = b'\n';
        assert_eq!(name(&bytes, at).reason(), Some(ReasonCode::InvalidData));
    }
    #[test]
    fn partitions_are_skipped_and_defaults_never_request_names() {
        let mut api = fake(vec![
            (Ok(false), Err(INVALID)),
            (Ok(true), Ok(0)),
            (Ok(true), Ok(4096)),
        ]);
        let result = run(&mut api, &Options::default());
        assert_eq!(result.source(), Source::Iokit);
        let entries = result.value().expect("entries");
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].capacity_bytes.value(), Some(&0));
        assert_eq!(entries[1].capacity_bytes.value(), Some(&4096));
        assert_eq!(entries[1].capacity_bytes.source(), Source::Iokit);
        assert!(entries[1].capacity_bytes.observed_at().is_some());
        for entry in entries {
            assert_eq!(entry.name.availability(), Availability::Restricted);
            assert_eq!(entry.name.reason(), Some(ReasonCode::PrivacyRedacted));
            assert!(entry.name.value().is_none());
        }
        assert_eq!(api.capacity_calls, 2);
        assert_eq!(api.name_calls, 0);
        assert_eq!(api.released.load(Ordering::SeqCst), 3);
    }
    #[test]
    fn field_failures_are_isolated_and_names_require_both_flags() {
        let mut api = fake(vec![(Ok(true), Err(UNKNOWN)), (Ok(true), Ok(1))]);
        let result = run(&mut api, &Options::default());
        assert_eq!(
            result.value().expect("entries")[0].capacity_bytes.reason(),
            Some(ReasonCode::Unknown)
        );
        assert_eq!(
            result.value().expect("entries")[1].capacity_bytes.value(),
            Some(&1)
        );
        let options = Options {
            privacy: PrivacyOptions {
                include_sensitive: true,
                caller_authorized: true,
            },
            ..Default::default()
        };
        let mut api = fake(vec![(Ok(true), Ok(1))]);
        assert_eq!(
            run(&mut api, &options).value().expect("entries")[0]
                .name
                .value()
                .map(String::as_str),
            Some("disk7")
        );
        assert_eq!(api.name_calls, 1);
        api.position = 0;
        api.name_error = Some(UNKNOWN);
        let result = run(&mut api, &options);
        assert_eq!(
            result.value().expect("entries")[0].name.reason(),
            Some(ReasonCode::Unknown)
        );
        assert_eq!(
            result.value().expect("entries")[0].capacity_bytes.value(),
            Some(&1)
        );
        let options = Options {
            privacy: PrivacyOptions {
                include_sensitive: true,
                caller_authorized: false,
            },
            ..Default::default()
        };
        let mut api = fake(vec![]);
        assert!(collect_with(&mut api, &options, || Ok(())).is_err());
        assert_eq!(api.position, 0);
    }
    #[test]
    fn both_limits_refuse_prefix_and_release_all_objects() {
        for limit in [1, 128, 1024] {
            let options = Options {
                max_entries: limit,
                ..Default::default()
            };
            let mut api = fake(vec![(Ok(true), Ok(1)); limit + 1]);
            assert_eq!(
                run(&mut api, &options).reason(),
                Some(ReasonCode::InvalidData)
            );
            assert_eq!(api.capacity_calls, 0);
            assert_eq!(api.position, limit + 1);
            assert_eq!(api.released.load(Ordering::SeqCst), limit + 1);
            let mut api = fake(vec![(Ok(true), Ok(1)); limit]);
            assert_eq!(
                run(&mut api, &options).value().expect("entries").len(),
                limit
            );
            assert_eq!(api.released.load(Ordering::SeqCst), limit);
        }
        let mut api = fake(vec![(Ok(false), Ok(1)); MAX_MEDIA + 1]);
        assert_eq!(
            run(&mut api, &Options::default()).reason(),
            Some(ReasonCode::InvalidData)
        );
        assert_eq!(api.position, MAX_MEDIA + 1);
        assert_eq!(api.released.load(Ordering::SeqCst), MAX_MEDIA + 1);
        let mut api = fake(vec![(Ok(false), Ok(1)); MAX_MEDIA]);
        assert!(
            run(&mut api, &Options::default())
                .value()
                .expect("empty")
                .is_empty()
        );
        assert_eq!(api.released.load(Ordering::SeqCst), MAX_MEDIA);
    }
    #[test]
    fn empty_invalid_iterator_and_uncertain_classification_differ() {
        let mut api = fake(vec![]);
        assert!(
            run(&mut api, &Options::default())
                .value()
                .expect("empty")
                .is_empty()
        );
        let mut api = fake(vec![(Ok(true), Ok(1))]);
        api.invalid_end = true;
        assert_eq!(
            run(&mut api, &Options::default()).reason(),
            Some(ReasonCode::TemporarilyUnavailable)
        );
        assert_eq!(api.capacity_calls, 0);
        assert_eq!(api.released.load(Ordering::SeqCst), 1);
        for failure in [
            UNKNOWN,
            INVALID,
            Failure(Availability::Restricted, ReasonCode::PermissionDenied),
        ] {
            let mut api = fake(vec![(Ok(true), Ok(1)), (Err(failure), Ok(1))]);
            let result = run(&mut api, &Options::default());
            assert_eq!(result.availability(), failure.0);
            assert_eq!(result.reason(), Some(failure.1));
            assert!(result.value().is_none());
            assert!(result.observed_at().is_none());
            assert_eq!(api.capacity_calls, 0);
            assert_eq!(api.released.load(Ordering::SeqCst), 2);
        }
    }
    #[test]
    fn cancellation_releases_candidates_and_skipped_objects() {
        for code in [ErrorCode::Cancelled, ErrorCode::Timeout] {
            for stop in [1, 2, 4, 6, 10] {
                let mut api = fake(vec![(Ok(true), Ok(1)), (Ok(false), Ok(1))]);
                let mut calls = 0;
                assert_eq!(
                    collect_with(&mut api, &Options::default(), || {
                        calls += 1;
                        if calls == stop {
                            Err(ScopeError::new(code))
                        } else {
                            Ok(())
                        }
                    })
                    .expect_err("stopped")
                    .code,
                    code
                );
                assert_eq!(api.released.load(Ordering::SeqCst), api.position);
                assert_eq!(api.capacity_calls, 0);
            }
        }
    }
    #[test]
    fn owned_reference_releases_once_on_error_and_unwind() {
        thread_local! {static RELEASES: std::cell::Cell<usize> = const {std::cell::Cell::new(0)};}
        fn release(_: u32) {
            RELEASES.with(|n| n.set(n.get() + 1));
        }
        fn error() -> Result<(), Failure> {
            let _object = Owned { raw: 1, release };
            Err(UNKNOWN)
        }
        assert_eq!(error(), Err(UNKNOWN));
        assert!(
            std::panic::catch_unwind(|| {
                let _object = Owned { raw: 2, release };
                panic!("fixture");
            })
            .is_err()
        );
        {
            let _object = Owned { raw: 3, release };
        }
        RELEASES.with(|n| assert_eq!(n.get(), 3));
    }
    #[test]
    fn static_members_and_capacities_are_cached_until_recreation() {
        struct Fixture(Arc<AtomicU64>);
        impl Backend for Fixture {
            fn name(&self) -> &'static str {
                "iomedia-fixture"
            }
            fn capabilities(&self) -> Capabilities {
                vec![Capability::new(
                    "storage",
                    CapabilityLevel::Partial,
                    Source::Iokit,
                )]
            }
            fn collect_static(
                &mut self,
                context: &CollectContext,
            ) -> Result<StaticSnapshot, ScopeError> {
                let mut result = StaticSnapshot::default();
                result.storage = collect_with(
                    &mut fake(vec![(Ok(true), Ok(self.0.load(Ordering::SeqCst)))]),
                    &context.options,
                    || context.check(),
                )?;
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
        let value = Arc::new(AtomicU64::new(4096));
        let create = || {
            HardwareBuilder::default()
                .with_backend(100, Fixture(value.clone()))
                .build()
                .expect("hardware")
        };
        let hardware = create();
        let first = hardware.collect().expect("initial").static_info.storage;
        value.store(8192, Ordering::SeqCst);
        hardware.refresh_dynamic().expect("dynamic");
        assert_eq!(
            hardware.collect().expect("cache").static_info.storage,
            first
        );
        assert_eq!(
            create()
                .collect()
                .expect("new")
                .static_info
                .storage
                .value()
                .expect("entries")[0]
                .capacity_bytes
                .value(),
            Some(&8192)
        );
    }
}
