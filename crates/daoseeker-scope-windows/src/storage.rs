//! Present whole-disk metadata with bounded enumeration and owned native handles.
//! Device paths remain opaque temporary OS buffers; see ADR 0014.
use daoseeker_scope_core::*;
use std::mem::{align_of, offset_of, size_of};
use std::ptr::null_mut;
use windows_sys::Win32::{
    Devices::DeviceAndDriverInstallation::{
        DIGCF_DEVICEINTERFACE, DIGCF_PRESENT, SP_DEVICE_INTERFACE_DATA,
        SP_DEVICE_INTERFACE_DETAIL_DATA_W, SetupDiDestroyDeviceInfoList,
        SetupDiEnumDeviceInterfaces, SetupDiGetClassDevsW, SetupDiGetDeviceInterfaceDetailW,
    },
    Foundation::{
        CloseHandle, ERROR_ACCESS_DENIED, ERROR_FILE_NOT_FOUND, ERROR_INSUFFICIENT_BUFFER,
        ERROR_INVALID_DATA, ERROR_INVALID_FUNCTION, ERROR_INVALID_PARAMETER, ERROR_MORE_DATA,
        ERROR_NO_MORE_ITEMS, ERROR_NOT_ENOUGH_MEMORY, ERROR_NOT_FOUND, ERROR_NOT_READY,
        ERROR_NOT_SUPPORTED, ERROR_SEM_TIMEOUT, GetLastError, HANDLE, INVALID_HANDLE_VALUE,
    },
    Storage::FileSystem::{
        CreateFileW, FILE_DEVICE_DISK, FILE_SHARE_READ, FILE_SHARE_WRITE, OPEN_EXISTING,
    },
    System::{
        IO::DeviceIoControl,
        Ioctl::{
            DISK_GEOMETRY_EX, GUID_DEVINTERFACE_DISK, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX,
            IOCTL_STORAGE_GET_DEVICE_NUMBER, STORAGE_DEVICE_NUMBER,
        },
    },
};

const DETAIL_BYTES: usize = 8192;
const GEOMETRY_BYTES: usize = 1024;
const SIZE_OFFSET: usize = offset_of!(DISK_GEOMETRY_EX, DiskSize);
#[repr(C)]
struct Detail {
    cb_size: u32,
    path: [u16; (DETAIL_BYTES - 4) / 2],
}
#[repr(C, align(8))]
struct Geometry([u8; GEOMETRY_BYTES]);
const _: () = {
    assert!(size_of::<Detail>() == DETAIL_BYTES);
    assert!(align_of::<Detail>() >= align_of::<SP_DEVICE_INTERFACE_DETAIL_DATA_W>());
    assert!(offset_of!(Detail, path) == offset_of!(SP_DEVICE_INTERFACE_DETAIL_DATA_W, DevicePath));
    assert!(SIZE_OFFSET == 24);
    assert!(align_of::<Geometry>() >= align_of::<DISK_GEOMETRY_EX>());
};

// The release function is fixed when acquiring the resource; no ownership alias
// is exposed. Tests can exercise unwinding without invoking native APIs.
struct Resource<T: Copy> {
    raw: T,
    release: fn(T),
}
impl<T: Copy> Drop for Resource<T> {
    fn drop(&mut self) {
        (self.release)(self.raw);
    }
}
fn release_set(raw: isize) {
    // SAFETY: Resource owns one successful SetupDiGetClassDevsW result and drops once.
    unsafe { SetupDiDestroyDeviceInfoList(raw) };
}
fn release_disk(raw: HANDLE) {
    // SAFETY: Resource owns one successful CreateFileW result and drops once.
    unsafe { CloseHandle(raw) };
}
fn last_error() -> u32 {
    // SAFETY: read the current thread's error immediately after a failed native call.
    unsafe { GetLastError() }
}
fn missing<T>(code: u32, source: Source) -> Observed<T> {
    match code {
        ERROR_ACCESS_DENIED => Observed::restricted(source, ReasonCode::PermissionDenied),
        ERROR_NOT_SUPPORTED | ERROR_INVALID_FUNCTION => {
            Observed::missing(Availability::Unsupported, source, ReasonCode::NotSupported)
                .expect("unsupported is a missing state")
        }
        ERROR_FILE_NOT_FOUND | ERROR_NOT_FOUND => {
            Observed::unavailable(source, ReasonCode::NotPresent)
        }
        ERROR_INSUFFICIENT_BUFFER
        | ERROR_MORE_DATA
        | ERROR_INVALID_DATA
        | ERROR_INVALID_PARAMETER => Observed::unavailable(source, ReasonCode::InvalidData),
        ERROR_NOT_READY | ERROR_NOT_ENOUGH_MEMORY => {
            Observed::unavailable(source, ReasonCode::TemporarilyUnavailable)
        }
        ERROR_SEM_TIMEOUT => Observed::unavailable(source, ReasonCode::Timeout),
        _ => Observed::unavailable(source, ReasonCode::Unknown),
    }
}

fn path_units(detail: &Detail, required: u32) -> Result<&[u16], u32> {
    let required = required as usize;
    let offset = offset_of!(Detail, path);
    if detail.cb_size != size_of::<SP_DEVICE_INTERFACE_DETAIL_DATA_W>() as u32
        || required < offset + 2
        || required > DETAIL_BYTES
        || !required.is_multiple_of(2)
    {
        return Err(ERROR_INVALID_DATA);
    }
    let units = &detail.path[..(required - offset) / 2];
    match units.iter().position(|unit| *unit == 0) {
        Some(end) if end > 0 => Ok(&units[..=end]),
        _ => Err(ERROR_INVALID_DATA),
    }
}
fn capacity(bytes: &[u8], returned: u32) -> Result<u64, u32> {
    let returned = returned as usize;
    if returned < SIZE_OFFSET + 8 || returned > bytes.len() {
        return Err(ERROR_INVALID_DATA);
    }
    let raw = i64::from_le_bytes(
        bytes[SIZE_OFFSET..SIZE_OFFSET + 8]
            .try_into()
            .expect("validated eight-byte capacity slice"),
    );
    u64::try_from(raw).map_err(|_| ERROR_INVALID_DATA)
}

fn device_number(number: &STORAGE_DEVICE_NUMBER, returned: u32) -> Result<u32, u32> {
    if returned as usize != size_of::<STORAGE_DEVICE_NUMBER>()
        || number.DeviceType != FILE_DEVICE_DISK
        || !matches!(number.PartitionNumber, 0 | u32::MAX)
    {
        Err(ERROR_INVALID_DATA)
    } else {
        Ok(number.DeviceNumber)
    }
}

struct NativeApi(Resource<isize>);
impl NativeApi {
    fn new() -> Result<Self, u32> {
        // SAFETY: fixed SDK GUID, no enumerator or parent window; returns an owned set.
        let set = unsafe {
            SetupDiGetClassDevsW(
                &GUID_DEVINTERFACE_DISK,
                std::ptr::null(),
                null_mut(),
                DIGCF_PRESENT | DIGCF_DEVICEINTERFACE,
            )
        };
        if set == INVALID_HANDLE_VALUE as isize {
            Err(last_error())
        } else {
            Ok(Self(Resource {
                raw: set,
                release: release_set,
            }))
        }
    }
}
trait Api {
    fn interface(&mut self, index: u32) -> Result<Option<SP_DEVICE_INTERFACE_DATA>, u32>;
    fn read(
        &mut self,
        row: &mut SP_DEVICE_INTERFACE_DATA,
        sensitive: bool,
        check: &mut dyn FnMut() -> Result<(), ScopeError>,
    ) -> Result<DeviceRead, ScopeError>;
}
struct DeviceRead {
    capacity: Result<u64, u32>,
    number: Option<Result<u32, u32>>,
}
impl DeviceRead {
    fn failed(code: u32, sensitive: bool) -> Self {
        Self {
            capacity: Err(code),
            number: sensitive.then_some(Err(code)),
        }
    }
}
impl Api for NativeApi {
    fn interface(&mut self, index: u32) -> Result<Option<SP_DEVICE_INTERFACE_DATA>, u32> {
        let mut row = SP_DEVICE_INTERFACE_DATA {
            cbSize: size_of::<SP_DEVICE_INTERFACE_DATA>() as u32,
            ..Default::default()
        };
        // SAFETY: owned live set; fixed initialized SDK output row and GUID.
        let ok = unsafe {
            SetupDiEnumDeviceInterfaces(
                self.0.raw,
                std::ptr::null(),
                &GUID_DEVINTERFACE_DISK,
                index,
                &mut row,
            )
        };
        if ok != 0 {
            Ok(Some(row))
        } else {
            match last_error() {
                ERROR_NO_MORE_ITEMS => Ok(None),
                code => Err(code),
            }
        }
    }
    fn read(
        &mut self,
        row: &mut SP_DEVICE_INTERFACE_DATA,
        sensitive: bool,
        check: &mut dyn FnMut() -> Result<(), ScopeError>,
    ) -> Result<DeviceRead, ScopeError> {
        check()?;
        let mut detail = Detail {
            cb_size: size_of::<SP_DEVICE_INTERFACE_DETAIL_DATA_W>() as u32,
            path: [0; (DETAIL_BYTES - 4) / 2],
        };
        let mut required = 0;
        // SAFETY: initialized aligned fixed buffer (const assertions), SDK cbSize,
        // live interface from this set; native writes at most the supplied capacity.
        // No reference to the SDK flexible array is created and no OS size is allocated.
        let ok = unsafe {
            SetupDiGetDeviceInterfaceDetailW(
                self.0.raw,
                row,
                (&mut detail as *mut Detail).cast(),
                DETAIL_BYTES as u32,
                &mut required,
                null_mut(),
            )
        };
        let code = if ok == 0 { Some(last_error()) } else { None };
        check()?;
        if let Some(code) = code {
            return Ok(DeviceRead::failed(code, sensitive));
        }
        let path = match path_units(&detail, required) {
            Ok(path) => path,
            Err(code) => return Ok(DeviceRead::failed(code, sensitive)),
        };
        // SAFETY: path is bounded, nonempty and NUL-terminated UTF-16 in a live
        // buffer. No parsing of the opaque path, no read/write access, no async IO.
        let raw = unsafe {
            CreateFileW(
                path.as_ptr(),
                0,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                std::ptr::null(),
                OPEN_EXISTING,
                0,
                null_mut(),
            )
        };
        let disk = if raw == INVALID_HANDLE_VALUE {
            let code = last_error();
            check()?;
            return Ok(DeviceRead::failed(code, sensitive));
        } else {
            Resource {
                raw,
                release: release_disk,
            }
        };
        check()?;
        let mut bytes = Geometry([0; GEOMETRY_BYTES]);
        let mut returned = 0;
        // SAFETY: synchronous metadata IOCTL, owned handle and initialized aligned
        // fixed output buffer/length. No input or OVERLAPPED and no retained pointers.
        let ok = unsafe {
            DeviceIoControl(
                disk.raw,
                IOCTL_DISK_GET_DRIVE_GEOMETRY_EX,
                std::ptr::null(),
                0,
                bytes.0.as_mut_ptr().cast(),
                GEOMETRY_BYTES as u32,
                &mut returned,
                null_mut(),
            )
        };
        let capacity = if ok == 0 {
            Err(last_error())
        } else {
            capacity(&bytes.0, returned)
        };
        check()?;
        let number = if sensitive {
            let mut number = STORAGE_DEVICE_NUMBER::default();
            returned = 0;
            // SAFETY: synchronous fixed-size SDK output, owned live handle. This
            // query is reached only after both explicit privacy flags permit names.
            let ok = unsafe {
                DeviceIoControl(
                    disk.raw,
                    IOCTL_STORAGE_GET_DEVICE_NUMBER,
                    std::ptr::null(),
                    0,
                    (&mut number as *mut STORAGE_DEVICE_NUMBER).cast(),
                    size_of::<STORAGE_DEVICE_NUMBER>() as u32,
                    &mut returned,
                    null_mut(),
                )
            };
            let value = if ok == 0 {
                Err(last_error())
            } else {
                device_number(&number, returned)
            };
            check()?;
            Some(value)
        } else {
            None
        };
        Ok(DeviceRead { capacity, number })
    }
}

fn collect_with(
    api: &mut impl Api,
    options: &Options,
    mut check: impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<Vec<StorageInfo>>, ScopeError> {
    options.validate()?;
    let mut interfaces = Vec::with_capacity(options.max_entries);
    for index in 0..=options.max_entries {
        check()?;
        let row = api.interface(index as u32);
        check()?;
        match row {
            Ok(None) => break,
            Ok(Some(row)) if index < options.max_entries => interfaces.push(row),
            Ok(Some(_)) => return Ok(missing(ERROR_INVALID_DATA, Source::Setupapi)),
            Err(code) => return Ok(missing(code, Source::Setupapi)),
        }
    }
    let sensitive = options.privacy.permits_sensitive();
    let mut entries = Vec::with_capacity(interfaces.len());
    for mut row in interfaces {
        check()?;
        let read = api.read(&mut row, sensitive, &mut check)?;
        check()?;
        let at = Timestamp::now()?;
        let mut entry = StorageInfo::default();
        entry.capacity_bytes = match read.capacity {
            Ok(value) => Observed::available(value, Source::Win32, at),
            Err(code) => missing(code, Source::Win32),
        };
        entry.name = if sensitive {
            match read.number.unwrap_or(Err(ERROR_INVALID_DATA)) {
                Ok(number) => {
                    Observed::available(format!("PhysicalDrive{number}"), Source::Win32, at)
                }
                Err(code) => missing(code, Source::Win32),
            }
        } else {
            Observed::restricted(Source::Win32, ReasonCode::PrivacyRedacted)
        };
        entries.push(entry);
    }
    check()?;
    Ok(Observed::available(
        entries,
        Source::Setupapi,
        Timestamp::now()?,
    ))
}

pub(super) fn collect(context: &CollectContext) -> Result<Observed<Vec<StorageInfo>>, ScopeError> {
    context.check()?;
    let api = NativeApi::new();
    context.check()?;
    match api {
        Ok(mut api) => collect_with(&mut api, &context.options, || context.check()),
        Err(code) => Ok(missing(code, Source::Setupapi)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::VecDeque;
    use std::sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    };

    struct FakeApi {
        count: usize,
        enum_error: Option<(u32, u32)>,
        reads: VecDeque<DeviceRead>,
        enum_calls: usize,
        read_flags: Vec<bool>,
    }
    impl Api for FakeApi {
        fn interface(&mut self, index: u32) -> Result<Option<SP_DEVICE_INTERFACE_DATA>, u32> {
            self.enum_calls += 1;
            if let Some((at, code)) = self.enum_error
                && index == at
            {
                return Err(code);
            }
            Ok(((index as usize) < self.count).then(SP_DEVICE_INTERFACE_DATA::default))
        }
        fn read(
            &mut self,
            _: &mut SP_DEVICE_INTERFACE_DATA,
            sensitive: bool,
            check: &mut dyn FnMut() -> Result<(), ScopeError>,
        ) -> Result<DeviceRead, ScopeError> {
            check()?;
            self.read_flags.push(sensitive);
            Ok(self.reads.pop_front().expect("fixture device read"))
        }
    }
    fn fake(values: Vec<DeviceRead>) -> FakeApi {
        FakeApi {
            count: values.len(),
            enum_error: None,
            reads: values.into(),
            enum_calls: 0,
            read_flags: vec![],
        }
    }
    fn good(value: u64) -> DeviceRead {
        DeviceRead {
            capacity: Ok(value),
            number: Some(Ok(42)),
        }
    }
    #[test]
    fn sdk_layout_and_detail_response_are_bounded() {
        assert_eq!(
            size_of::<SP_DEVICE_INTERFACE_DETAIL_DATA_W>(),
            if cfg!(target_arch = "x86") { 6 } else { 8 }
        );
        let mut detail = Detail {
            cb_size: size_of::<SP_DEVICE_INTERFACE_DETAIL_DATA_W>() as u32,
            path: [0; (DETAIL_BYTES - 4) / 2],
        };
        detail.path[..3].copy_from_slice(&[92, 92, 0]);
        assert_eq!(path_units(&detail, 10), Ok(&[92, 92, 0][..]));
        // No decode or parsing: an opaque OS path is only structurally bounded.
        detail.path[0] = 0xd800;
        assert!(path_units(&detail, 10).is_ok());
        for size in [0, 4, 5, 8, 11, DETAIL_BYTES as u32 + 2, u32::MAX] {
            assert_eq!(path_units(&detail, size), Err(ERROR_INVALID_DATA));
        }
        detail.path.fill(1);
        assert_eq!(
            path_units(&detail, DETAIL_BYTES as u32),
            Err(ERROR_INVALID_DATA)
        );
        detail.path[0] = 0;
        assert_eq!(
            path_units(&detail, DETAIL_BYTES as u32),
            Err(ERROR_INVALID_DATA)
        );
        detail.cb_size = 0;
        assert_eq!(path_units(&detail, 10), Err(ERROR_INVALID_DATA));
    }
    #[test]
    fn exact_disk_size_and_number_reject_invalid_native_responses() {
        let mut bytes = [0; GEOMETRY_BYTES];
        for value in [0, 1, 1000204886016, i64::MAX] {
            bytes[SIZE_OFFSET..SIZE_OFFSET + 8].copy_from_slice(&value.to_le_bytes());
            assert_eq!(capacity(&bytes, 32), Ok(value as u64));
        }
        for value in [-1i64, i64::MIN] {
            bytes[SIZE_OFFSET..SIZE_OFFSET + 8].copy_from_slice(&value.to_le_bytes());
            assert_eq!(capacity(&bytes, 32), Err(ERROR_INVALID_DATA));
        }
        for size in [0, 31, GEOMETRY_BYTES as u32 + 1, u32::MAX] {
            assert_eq!(capacity(&bytes, size), Err(ERROR_INVALID_DATA));
        }
        assert_eq!(capacity(&[], 32), Err(ERROR_INVALID_DATA));
        let mut number = STORAGE_DEVICE_NUMBER {
            DeviceType: FILE_DEVICE_DISK,
            DeviceNumber: 9,
            PartitionNumber: 0,
        };
        for partition in [0, u32::MAX] {
            number.PartitionNumber = partition;
            assert_eq!(device_number(&number, 12), Ok(9));
        }
        for partition in [1, 128] {
            number.PartitionNumber = partition;
            assert_eq!(device_number(&number, 12), Err(ERROR_INVALID_DATA));
        }
        number.PartitionNumber = 0;
        number.DeviceType = 0;
        assert_eq!(device_number(&number, 12), Err(ERROR_INVALID_DATA));
        for size in [0, 11, 13, u32::MAX] {
            assert_eq!(device_number(&number, size), Err(ERROR_INVALID_DATA));
        }
    }
    #[test]
    fn enumeration_limit_or_failure_never_returns_a_successful_prefix() {
        for limit in [1, 128, 1024] {
            let options = Options {
                max_entries: limit,
                ..Default::default()
            };
            let mut api = fake(vec![]);
            api.count = limit + 1;
            let result = collect_with(&mut api, &options, || Ok(())).expect("bounded");
            assert_eq!(result.reason(), Some(ReasonCode::InvalidData));
            assert_eq!(api.enum_calls, limit + 1);
            assert!(api.read_flags.is_empty());
            let mut api = fake((0..limit).map(|_| good(0)).collect());
            assert_eq!(
                collect_with(&mut api, &options, || Ok(()))
                    .expect("exact bound")
                    .value()
                    .expect("entries")
                    .len(),
                limit
            );
            assert_eq!(api.enum_calls, limit + 1);
        }
        let mut api = fake(vec![good(1)]);
        api.enum_error = Some((1, ERROR_ACCESS_DENIED));
        let result = collect_with(&mut api, &Options::default(), || Ok(())).expect("denied");
        assert_eq!(result.availability(), Availability::Restricted);
        assert_eq!(result.source(), Source::Setupapi);
        assert!(api.read_flags.is_empty());
        for limit in [0, 1025, usize::MAX] {
            let options = Options {
                max_entries: limit,
                ..Default::default()
            };
            assert!(collect_with(&mut api, &options, || Ok(())).is_err());
        }
    }
    #[test]
    fn errors_are_isolated_and_authorized_name_query_is_optional() {
        let mut api = fake(vec![
            good(0),
            DeviceRead::failed(ERROR_ACCESS_DENIED, false),
            good(1),
        ]);
        let result = collect_with(&mut api, &Options::default(), || Ok(())).expect("collected");
        let entries = result.value().expect("entries");
        assert_eq!(result.source(), Source::Setupapi);
        assert_eq!(entries[0].capacity_bytes.value(), Some(&0));
        assert_eq!(
            entries[1].capacity_bytes.availability(),
            Availability::Restricted
        );
        assert_eq!(entries[2].capacity_bytes.value(), Some(&1));
        assert_eq!(entries[2].capacity_bytes.source(), Source::Win32);
        assert!(entries[2].capacity_bytes.observed_at().is_some());
        assert_eq!(api.read_flags, vec![false; 3]);
        for entry in entries {
            assert_eq!(entry.name.reason(), Some(ReasonCode::PrivacyRedacted));
            assert!(entry.name.value().is_none());
        }
        let options = Options {
            privacy: PrivacyOptions {
                include_sensitive: true,
                caller_authorized: true,
            },
            ..Default::default()
        };
        let mut api = fake(vec![
            good(4096),
            DeviceRead {
                capacity: Ok(8192),
                number: Some(Err(ERROR_NOT_SUPPORTED)),
            },
        ]);
        let named = collect_with(&mut api, &options, || Ok(())).expect("authorized");
        assert_eq!(api.read_flags, vec![true; 2]);
        let entries = named.value().expect("entries");
        assert_eq!(
            entries[0].name.value().map(String::as_str),
            Some("PhysicalDrive42")
        );
        assert_eq!(entries[1].name.availability(), Availability::Unsupported);
        assert_eq!(entries[1].capacity_bytes.value(), Some(&8192));
    }
    #[test]
    fn empty_enumeration_and_error_states_remain_distinct() {
        assert!(
            collect_with(&mut fake(vec![]), &Options::default(), || Ok(()))
                .expect("empty")
                .value()
                .expect("available")
                .is_empty()
        );
        for (code, state, reason) in [
            (
                ERROR_ACCESS_DENIED,
                Availability::Restricted,
                ReasonCode::PermissionDenied,
            ),
            (
                ERROR_FILE_NOT_FOUND,
                Availability::Unavailable,
                ReasonCode::NotPresent,
            ),
            (
                ERROR_NOT_SUPPORTED,
                Availability::Unsupported,
                ReasonCode::NotSupported,
            ),
            (
                ERROR_INVALID_FUNCTION,
                Availability::Unsupported,
                ReasonCode::NotSupported,
            ),
            (
                ERROR_NOT_READY,
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            (
                ERROR_MORE_DATA,
                Availability::Unavailable,
                ReasonCode::InvalidData,
            ),
            (
                ERROR_SEM_TIMEOUT,
                Availability::Unavailable,
                ReasonCode::Timeout,
            ),
            (12345678, Availability::Unavailable, ReasonCode::Unknown),
        ] {
            let field = missing::<u64>(code, Source::Win32);
            assert_eq!(field.availability(), state);
            assert_eq!(field.reason(), Some(reason));
            assert!(field.value().is_none());
            assert!(field.observed_at().is_none());
        }
    }
    #[test]
    fn cancellation_stops_before_or_after_an_api_boundary() {
        for code in [ErrorCode::Cancelled, ErrorCode::Timeout] {
            for stop in [1, 2, 5] {
                let mut calls = 0;
                let mut api = fake(vec![good(1)]);
                let error = collect_with(&mut api, &Options::default(), || {
                    calls += 1;
                    if calls == stop {
                        Err(ScopeError::new(code))
                    } else {
                        Ok(())
                    }
                })
                .expect_err("cancelled");
                assert_eq!(error.code, code);
                assert_eq!(calls, stop);
                assert!(api.read_flags.is_empty());
            }
        }
    }
    #[test]
    fn owned_resources_release_once_on_error_and_unwind() {
        thread_local! {static RELEASES: std::cell::Cell<usize> = const {std::cell::Cell::new(0)};}
        fn release(_: usize) {
            RELEASES.with(|count| count.set(count.get() + 1));
        }
        fn fail() -> Result<(), u32> {
            let _resource = Resource { raw: 1, release };
            Err(ERROR_INVALID_DATA)
        }
        assert!(fail().is_err());
        assert!(
            std::panic::catch_unwind(|| {
                let _resource = Resource { raw: 2, release };
                panic!("fixture unwind");
            })
            .is_err()
        );
        {
            let _resource = Resource { raw: 3, release };
        }
        RELEASES.with(|count| assert_eq!(count.get(), 3));
    }
    #[test]
    fn static_storage_is_cached_and_recreation_reads_changes() {
        struct Fixture(Arc<AtomicU64>);
        impl Backend for Fixture {
            fn name(&self) -> &'static str {
                "windows-storage-fixture"
            }
            fn capabilities(&self) -> Capabilities {
                vec![Capability::new(
                    "storage",
                    CapabilityLevel::Partial,
                    Source::Setupapi,
                )]
            }
            fn collect_static(
                &mut self,
                context: &CollectContext,
            ) -> Result<StaticSnapshot, ScopeError> {
                let mut result = StaticSnapshot::default();
                result.storage = collect_with(
                    &mut fake(vec![good(self.0.load(Ordering::SeqCst))]),
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
            hardware.collect().expect("cached").static_info.storage,
            first
        );
        assert_eq!(
            create()
                .collect()
                .expect("recreated")
                .static_info
                .storage
                .value()
                .expect("entries")[0]
                .capacity_bytes
                .value(),
            Some(&8192)
        );
        assert!(
            crate::WindowsBackend
                .capabilities()
                .iter()
                .any(|cap| cap.field == "storage" && cap.level == CapabilityLevel::Partial)
        );
    }
}
