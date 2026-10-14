//! Bounded DXGI adapter enumeration; no adapter identifiers escape this module.
use daoseeker_scope_core::{
    Availability, GpuInfo, Observed, ReasonCode, ScopeError, Source, Timestamp,
};

const MAX_SCANNED: usize = 4096;
struct Descriptor {
    software: bool,
    description: [u16; 128],
    dedicated_bytes: u64,
}
enum ReadError {
    Native(i32),
    Context(ScopeError),
}
trait AdapterReader {
    fn next(
        &mut self,
        index: u32,
        check: &mut dyn FnMut() -> Result<(), ScopeError>,
    ) -> Result<Option<Descriptor>, ReadError>;
}

fn missing<T>(code: i32) -> Observed<T> {
    // HRESULT constants from the public Windows SDK; never retain native error text.
    match code as u32 {
        0x80070005 | 0x887a002b => Observed::restricted(Source::Dxgi, ReasonCode::PermissionDenied),
        0x80004001 | 0x887a0004 => Observed::missing(
            Availability::Unsupported,
            Source::Dxgi,
            ReasonCode::NotSupported,
        )
        .expect("Unsupported is a missing state"),
        0x80070057 | 0x887a0001 | 0x887a0003 => {
            Observed::unavailable(Source::Dxgi, ReasonCode::InvalidData)
        }
        0x887a0027 => Observed::unavailable(Source::Dxgi, ReasonCode::Timeout),
        0x8007000e
        | 0x887a0005..=0x887a0007
        | 0x887a000a
        | 0x887a0020
        | 0x887a0022..=0x887a0026
        | 0x887a0028
        | 0x887a002e => Observed::unavailable(Source::Dxgi, ReasonCode::TemporarilyUnavailable),
        _ => Observed::unavailable(Source::Dxgi, ReasonCode::Unknown),
    }
}

fn name(description: &[u16; 128], at: Timestamp) -> Observed<String> {
    let parsed = description
        .iter()
        .position(|unit| *unit == 0)
        .and_then(|end| {
            String::from_utf16(&description[..end])
                .ok()
                .filter(|s| !s.trim().is_empty() && !s.chars().any(char::is_control))
        });
    match parsed {
        Some(value) => Observed::available(value, Source::Dxgi, at),
        None => Observed::unavailable(Source::Dxgi, ReasonCode::InvalidData),
    }
}

fn enumerate(
    reader: &mut impl AdapterReader,
    max_entries: usize,
    mut check: impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<Vec<GpuInfo>>, ScopeError> {
    let mut entries = Vec::new();
    for index in 0..=MAX_SCANNED {
        check()?;
        let next = reader.next(index as u32, &mut check);
        check()?;
        let descriptor = match next {
            Ok(None) => {
                return Ok(Observed::available(
                    entries,
                    Source::Dxgi,
                    Timestamp::now()?,
                ));
            }
            Ok(Some(descriptor)) => descriptor,
            Err(ReadError::Native(code)) => return Ok(missing(code)),
            Err(ReadError::Context(error)) => return Err(error),
        };
        // Probe the end before rejecting a prefix. Count software adapters too.
        if index == MAX_SCANNED || (!descriptor.software && entries.len() == max_entries) {
            return Ok(Observed::unavailable(Source::Dxgi, ReasonCode::InvalidData));
        }
        if descriptor.software {
            continue;
        }
        let at = Timestamp::now()?;
        let mut entry = GpuInfo::default();
        entry.name = name(&descriptor.description, at);
        entry.dedicated_memory_bytes =
            Observed::available(descriptor.dedicated_bytes, Source::Dxgi, at);
        entries.push(entry);
    }
    Ok(Observed::unavailable(Source::Dxgi, ReasonCode::InvalidData))
}

#[cfg(target_os = "windows")]
mod native {
    use super::*;
    use daoseeker_scope_core::CollectContext;
    use windows::Win32::Graphics::Dxgi::{
        CreateDXGIFactory1, DXGI_ADAPTER_FLAG_SOFTWARE, DXGI_ERROR_NOT_FOUND, IDXGIFactory1,
    };
    struct Reader(IDXGIFactory1);
    impl AdapterReader for Reader {
        fn next(
            &mut self,
            index: u32,
            check: &mut dyn FnMut() -> Result<(), ScopeError>,
        ) -> Result<Option<Descriptor>, ReadError> {
            check().map_err(ReadError::Context)?;
            // SAFETY: factory is a live owned COM interface. SDK supplies a valid
            // output pointer and transfers the successful reference to its RAII wrapper.
            let result = unsafe { self.0.EnumAdapters1(index) };
            check().map_err(ReadError::Context)?;
            let adapter = match result {
                Ok(adapter) => adapter,
                Err(error) if error.code() == DXGI_ERROR_NOT_FOUND => return Ok(None),
                Err(error) => return Err(ReadError::Native(error.code().0)),
            };
            // SAFETY: adapter is live; SDK initializes the fixed descriptor and
            // passes its aligned output pointer. No borrowed native memory is returned.
            let result = unsafe { adapter.GetDesc1() };
            check().map_err(ReadError::Context)?;
            let descriptor = result.map_err(|error| ReadError::Native(error.code().0))?;
            let dedicated_bytes = u64::try_from(descriptor.DedicatedVideoMemory)
                .map_err(|_| ReadError::Native(0x80070057u32 as i32))?;
            // The SDK descriptor temporarily contains IDs; only this projection
            // survives. The adapter releases on all return paths and on unwind.
            Ok(Some(Descriptor {
                software: descriptor.Flags & DXGI_ADAPTER_FLAG_SOFTWARE.0 as u32 != 0,
                description: descriptor.Description,
                dedicated_bytes,
            }))
        }
    }
    pub(crate) fn collect(context: &CollectContext) -> Result<Observed<Vec<GpuInfo>>, ScopeError> {
        context.options.validate()?;
        context.check()?;
        // SAFETY: SDK supplies IDXGIFactory1's IID and output pointer, adopting
        // its reference into an owned wrapper. No COM pointers cross worker threads.
        let factory = unsafe { CreateDXGIFactory1::<IDXGIFactory1>() };
        context.check()?;
        let factory = match factory {
            Ok(factory) => factory,
            Err(error) => return Ok(missing(error.code().0)),
        };
        enumerate(&mut Reader(factory), context.options.max_entries, || {
            context.check()
        })
    }
}
#[cfg(target_os = "windows")]
pub(super) use native::collect;

#[cfg(test)]
mod tests {
    use super::*;
    use daoseeker_scope_core::{Availability, ErrorCode};
    struct Fake(Vec<Result<Option<Descriptor>, ReadError>>);
    impl AdapterReader for Fake {
        fn next(
            &mut self,
            _: u32,
            _: &mut dyn FnMut() -> Result<(), ScopeError>,
        ) -> Result<Option<Descriptor>, ReadError> {
            if self.0.is_empty() {
                Ok(None)
            } else {
                self.0.remove(0)
            }
        }
    }
    fn descriptor(software: bool, bytes: u64) -> Descriptor {
        let mut description = [0; 128];
        for (out, value) in description
            .iter_mut()
            .zip("Software Adapter".encode_utf16())
        {
            *out = value;
        }
        Descriptor {
            software,
            description,
            dedicated_bytes: bytes,
        }
    }
    #[test]
    fn only_flags_filter_software_and_zero_is_real() {
        let mut fake = Fake(vec![
            Ok(Some(descriptor(true, 999))),
            Ok(Some(descriptor(false, 0))),
            Ok(Some(descriptor(false, u64::MAX))),
        ]);
        let observed = enumerate(&mut fake, 2, || Ok(())).unwrap();
        let entries = observed.value().unwrap();
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].name.value().unwrap(), "Software Adapter");
        assert_eq!(entries[0].dedicated_memory_bytes.value(), Some(&0));
        assert_eq!(entries[1].dedicated_memory_bytes.value(), Some(&u64::MAX));
        assert_eq!(observed.source(), Source::Dxgi);
        assert!(observed.observed_at().is_some());
    }
    #[test]
    fn malformed_names_do_not_discard_memory() {
        for units in [
            [0u16; 128],
            [65u16; 128],
            {
                let mut x = [0; 128];
                x[0] = 0xd800;
                x
            },
            {
                let mut x = [0; 128];
                x[0] = 10;
                x
            },
        ] {
            let mut desc = descriptor(false, 123);
            desc.description = units;
            let observed = enumerate(&mut Fake(vec![Ok(Some(desc))]), 1, || Ok(())).unwrap();
            let entry = &observed.value().unwrap()[0];
            assert_eq!(entry.name.reason(), Some(ReasonCode::InvalidData));
            assert_eq!(entry.dedicated_memory_bytes.value(), Some(&123));
        }
    }
    #[test]
    fn empty_is_success_and_not_found_outside_enumeration_is_failure() {
        assert_eq!(
            enumerate(&mut Fake(vec![]), 1, || Ok(())).unwrap().value(),
            Some(&vec![])
        );
        assert_eq!(
            missing::<()>(0x887a0002u32 as i32).availability(),
            Availability::Unavailable
        );
    }
    #[test]
    fn native_error_states_are_distinct() {
        for (code, state, reason) in [
            (
                0x80070005u32,
                Availability::Restricted,
                ReasonCode::PermissionDenied,
            ),
            (
                0x887a0004,
                Availability::Unsupported,
                ReasonCode::NotSupported,
            ),
            (
                0x887a0022,
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
            (0x887a0027, Availability::Unavailable, ReasonCode::Timeout),
            (
                0x80070057,
                Availability::Unavailable,
                ReasonCode::InvalidData,
            ),
            (0x80004005, Availability::Unavailable, ReasonCode::Unknown),
        ] {
            let observed = enumerate(
                &mut Fake(vec![Err(ReadError::Native(code as i32))]),
                1,
                || Ok(()),
            )
            .unwrap();
            assert_eq!(observed.availability(), state);
            assert_eq!(observed.reason(), Some(reason));
            assert!(observed.value().is_none());
        }
    }
    #[test]
    fn failed_enumeration_does_not_claim_complete_prefix() {
        let observed = enumerate(
            &mut Fake(vec![
                Ok(Some(descriptor(false, 1))),
                Err(ReadError::Native(0x80070005u32 as i32)),
            ]),
            4,
            || Ok(()),
        )
        .unwrap();
        assert!(observed.value().is_none());
        assert_eq!(observed.availability(), Availability::Restricted);
    }
    #[test]
    fn entry_limit_rejects_prefix() {
        let observed = enumerate(
            &mut Fake(vec![
                Ok(Some(descriptor(false, 1))),
                Ok(Some(descriptor(false, 2))),
            ]),
            1,
            || Ok(()),
        )
        .unwrap();
        assert_eq!(observed.reason(), Some(ReasonCode::InvalidData));
        assert!(observed.value().is_none());
    }
    #[test]
    fn software_scan_is_bounded() {
        struct Endless(usize);
        impl AdapterReader for Endless {
            fn next(
                &mut self,
                _: u32,
                _: &mut dyn FnMut() -> Result<(), ScopeError>,
            ) -> Result<Option<Descriptor>, ReadError> {
                self.0 += 1;
                Ok(Some(descriptor(true, 0)))
            }
        }
        let mut reader = Endless(0);
        assert_eq!(
            enumerate(&mut reader, 1, || Ok(())).unwrap().reason(),
            Some(ReasonCode::InvalidData)
        );
        assert_eq!(reader.0, MAX_SCANNED + 1);
    }
    #[test]
    fn cancellation_before_and_after_native_call_is_propagated() {
        let mut unread = Fake(vec![Ok(Some(descriptor(false, 1)))]);
        assert_eq!(
            enumerate(&mut unread, 1, || Err(ScopeError::new(
                ErrorCode::Cancelled
            )))
            .unwrap_err()
            .code,
            ErrorCode::Cancelled
        );
        assert_eq!(unread.0.len(), 1);
        let mut calls = 0;
        let error = enumerate(&mut Fake(vec![Ok(Some(descriptor(false, 1)))]), 1, || {
            calls += 1;
            if calls == 2 {
                Err(ScopeError::new(ErrorCode::Cancelled))
            } else {
                Ok(())
            }
        })
        .unwrap_err();
        assert_eq!(error.code, ErrorCode::Cancelled);
        let error = enumerate(
            &mut Fake(vec![Err(ReadError::Context(ScopeError::new(
                ErrorCode::Timeout,
            )))]),
            1,
            || Ok(()),
        )
        .unwrap_err();
        assert_eq!(error.code, ErrorCode::Timeout);
    }
    #[test]
    fn static_gpu_success_and_failure_are_cached_until_recreation() {
        use daoseeker_scope_core::{
            Backend, Capabilities, CollectContext, DynamicSnapshot, HardwareBuilder, StaticSnapshot,
        };
        use std::sync::{
            Arc,
            atomic::{AtomicBool, AtomicUsize, Ordering},
        };
        struct Fixture {
            denied: Arc<AtomicBool>,
            calls: Arc<AtomicUsize>,
        }
        impl Backend for Fixture {
            fn name(&self) -> &'static str {
                "gpu-fixture"
            }
            fn capabilities(&self) -> Capabilities {
                vec![]
            }
            fn collect_static(
                &mut self,
                context: &CollectContext,
            ) -> Result<StaticSnapshot, ScopeError> {
                self.calls.fetch_add(1, Ordering::SeqCst);
                let next = if self.denied.load(Ordering::SeqCst) {
                    Err(ReadError::Native(0x80070005u32 as i32))
                } else {
                    Ok(Some(descriptor(false, 123)))
                };
                let mut result = StaticSnapshot::default();
                result.gpus =
                    enumerate(&mut Fake(vec![next]), context.options.max_entries, || {
                        context.check()
                    })?;
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
        for initial_denied in [false, true] {
            let denied = Arc::new(AtomicBool::new(initial_denied));
            let calls = Arc::new(AtomicUsize::new(0));
            let create = || {
                HardwareBuilder::default()
                    .with_backend(
                        100,
                        Fixture {
                            denied: denied.clone(),
                            calls: calls.clone(),
                        },
                    )
                    .build()
                    .unwrap()
            };
            let hardware = create();
            let first = hardware.collect().unwrap().static_info.gpus;
            denied.store(!initial_denied, Ordering::SeqCst);
            hardware.refresh_dynamic().unwrap();
            assert_eq!(hardware.collect().unwrap().static_info.gpus, first);
            assert_eq!(calls.load(Ordering::SeqCst), 1);
            let recreated = create().collect().unwrap().static_info.gpus;
            assert_eq!(recreated.value().is_none(), !initial_denied);
            assert_eq!(calls.load(Ordering::SeqCst), 2);
        }
    }
}
