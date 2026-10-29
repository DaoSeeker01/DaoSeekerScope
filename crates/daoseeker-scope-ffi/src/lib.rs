//! C ABI v1. See bindings/daoseeker_scope.h for pointer and ownership contracts.
//!
//! After any `dsc_collect_json` call, including failure or timeout, keep the
//! shared library loaded until process exit. ABI v1 has no shutdown/drain
//! operation; freeing every buffer does not make unloading or hot reload safe.
use daoseeker_scope::*;
use std::{
    cell::Cell,
    collections::HashMap,
    ffi::{CStr, c_char},
    panic::{AssertUnwindSafe, catch_unwind},
    sync::{Arc, LazyLock, Mutex},
    time::Duration,
};

pub const ABI_VERSION: u32 = 1;
#[repr(C)]
#[derive(Clone, Copy)]
pub struct DscOptions {
    pub size: u32,
    pub version: u32,
    pub flags: u32,
    pub timeout_ms: u32,
    pub max_entries: u32,
}
#[repr(C)]
#[derive(Clone, Copy)]
pub struct DscBuffer {
    pub data: *const u8,
    pub len: usize,
    pub token: u64,
}
impl Default for DscBuffer {
    fn default() -> Self {
        Self {
            data: std::ptr::null(),
            len: 0,
            token: 0,
        }
    }
}
struct Registry {
    next: u64,
    entries: HashMap<u64, Arc<[u8]>>,
}
impl Registry {
    fn insert(&mut self, bytes: Box<[u8]>) -> Result<DscBuffer, ScopeError> {
        if self.entries.len() >= 64 || bytes.len() > MAX_JSON_BYTES {
            return Err(ScopeError::new(ErrorCode::ResourceLimit));
        }
        let token = self.next;
        self.next = token
            .checked_add(1)
            .ok_or(ScopeError::new(ErrorCode::ResourceLimit))?;
        // Arc has shared ownership semantics: moving/rehashing the owner must not
        // invalidate a raw pointer already exported to a C reader. A Box moved
        // after deriving its data pointer acquires a new unique borrow tag.
        let bytes: Arc<[u8]> = Arc::from(bytes);
        let output = DscBuffer {
            data: Arc::as_ptr(&bytes).cast::<u8>(),
            len: bytes.len(),
            token,
        };
        self.entries.insert(token, bytes);
        Ok(output)
    }
}
static REGISTRY: LazyLock<Mutex<Registry>> = LazyLock::new(|| {
    Mutex::new(Registry {
        next: 1,
        entries: HashMap::new(),
    })
});
static DEFAULT_HARDWARE: LazyLock<Mutex<Option<Arc<Hardware>>>> =
    LazyLock::new(|| Mutex::new(None));
fn get_or_build(
    slot: &Mutex<Option<Arc<Hardware>>>,
    build: impl FnOnce() -> Result<Hardware, ScopeError>,
) -> Result<Arc<Hardware>, ScopeError> {
    let mut cached = slot.try_lock().map_err(|error| match error {
        std::sync::TryLockError::WouldBlock => ScopeError::new(ErrorCode::Busy),
        std::sync::TryLockError::Poisoned(_) => ScopeError::new(ErrorCode::Panic),
    })?;
    if let Some(hardware) = &*cached {
        return Ok(hardware.clone());
    }
    let hardware = Arc::new(build()?);
    *cached = Some(hardware.clone());
    Ok(hardware)
}
thread_local! { static LAST_ERROR: Cell<&'static CStr> = const { Cell::new(c"") }; }
fn status(error: ErrorCode) -> (i32, &'static CStr) {
    match error {
        ErrorCode::InvalidArgument => (1, c"invalid argument"),
        ErrorCode::UnsupportedPlatform => (2, c"unsupported platform"),
        ErrorCode::Timeout => (3, c"timeout"),
        ErrorCode::Cancelled => (4, c"cancelled"),
        ErrorCode::Busy => (5, c"busy"),
        ErrorCode::BackendFailure => (6, c"backend failure"),
        ErrorCode::ResourceLimit => (7, c"resource limit"),
        ErrorCode::Panic => (8, c"panic"),
        ErrorCode::InvalidBuffer => (9, c"invalid buffer"),
        _ => (6, c"backend failure"),
    }
}
fn boundary(action: impl FnOnce() -> Result<(), ScopeError>) -> i32 {
    match catch_unwind(AssertUnwindSafe(|| {
        LAST_ERROR.set(c"");
        action()
    })) {
        Ok(Ok(())) => 0,
        Ok(Err(error)) => {
            let (code, text) = status(error.code);
            LAST_ERROR.set(text);
            code
        }
        Err(_) => {
            LAST_ERROR.set(c"panic");
            8
        }
    }
}
#[unsafe(no_mangle)]
pub extern "C" fn dsc_abi_version() -> u32 {
    catch_unwind(|| {
        LAST_ERROR.set(c"");
        ABI_VERSION
    })
    .unwrap_or(0)
}
/// Returns a thread-local error string valid until this thread's next ABI call.
#[unsafe(no_mangle)]
pub extern "C" fn dsc_last_error() -> *const c_char {
    catch_unwind(|| LAST_ERROR.get().as_ptr()).unwrap_or(c"panic".as_ptr())
}
fn options(raw: DscOptions) -> Result<Options, ScopeError> {
    if raw.size as usize != std::mem::size_of::<DscOptions>()
        || raw.version != ABI_VERSION
        || raw.flags & !3 != 0
    {
        return Err(ScopeError::new(ErrorCode::InvalidArgument));
    }
    let options = Options {
        timeout: Duration::from_millis(u64::from(raw.timeout_ms)),
        max_entries: raw.max_entries as usize,
        privacy: PrivacyOptions {
            include_sensitive: raw.flags & 1 != 0,
            caller_authorized: raw.flags & 2 != 0,
        },
    };
    options.validate()?;
    Ok(options)
}
/// Collects UTF-8 JSON into an initially empty output buffer.
///
/// # Safety
/// buffer must point to an initialized, aligned, writable DscBuffer for this call.
/// options must be null or point to a readable aligned DscOptions.
/// Neither struct may be modified concurrently.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn dsc_collect_json(raw: *const DscOptions, buffer: *mut DscBuffer) -> i32 {
    boundary(|| {
        if buffer.is_null() {
            return Err(ScopeError::new(ErrorCode::InvalidArgument));
        }
        // SAFETY: caller guarantees a live initialized aligned output struct.
        let previous = unsafe { buffer.read() };
        if !previous.data.is_null() || previous.len != 0 || previous.token != 0 {
            return Err(ScopeError::new(ErrorCode::InvalidBuffer));
        }
        let snapshot = if raw.is_null() {
            get_or_build(&DEFAULT_HARDWARE, Hardware::new)?.collect()?
        } else {
            // SAFETY: caller guarantees a readable aligned options struct.
            let options = options(unsafe { raw.read() })?;
            Hardware::with_options(options)?.collect()?
        };
        let bytes = to_json(&snapshot)?.into_bytes().into_boxed_slice();
        let mut registry = REGISTRY
            .lock()
            .map_err(|_| ScopeError::new(ErrorCode::Panic))?;
        let output = registry.insert(bytes)?;
        // SAFETY: valid writable output; data remains owned by registry until free.
        unsafe { buffer.write(output) };
        Ok(())
    })
}
/// Frees a registered allocation and zeroes the output. Empty buffers are idempotent.
///
/// # Safety
/// buffer must point to a live initialized aligned writable DscBuffer.
/// No thread may use or release its allocation concurrently.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn dsc_buffer_free(buffer: *mut DscBuffer) -> i32 {
    boundary(|| {
        if buffer.is_null() {
            return Err(ScopeError::new(ErrorCode::InvalidArgument));
        }
        // SAFETY: caller guarantees a live initialized buffer struct.
        let value = unsafe { buffer.read() };
        if value.token == 0 && value.data.is_null() && value.len == 0 {
            return Ok(());
        }
        let mut registry = REGISTRY
            .lock()
            .map_err(|_| ScopeError::new(ErrorCode::Panic))?;
        let registered = registry
            .entries
            .get(&value.token)
            .ok_or(ScopeError::new(ErrorCode::InvalidBuffer))?;
        if Arc::as_ptr(registered).cast::<u8>() != value.data || registered.len() != value.len {
            return Err(ScopeError::new(ErrorCode::InvalidBuffer));
        }
        registry.entries.remove(&value.token);
        // SAFETY: same writable struct; allocation is now gone.
        unsafe { buffer.write(DscBuffer::default()) };
        Ok(())
    })
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn abi_v1_error_numbers_and_redacted_messages_are_stable() {
        for (error, number, message) in [
            (ErrorCode::InvalidArgument, 1, c"invalid argument"),
            (ErrorCode::UnsupportedPlatform, 2, c"unsupported platform"),
            (ErrorCode::Timeout, 3, c"timeout"),
            (ErrorCode::Cancelled, 4, c"cancelled"),
            (ErrorCode::Busy, 5, c"busy"),
            (ErrorCode::BackendFailure, 6, c"backend failure"),
            (ErrorCode::ResourceLimit, 7, c"resource limit"),
            (ErrorCode::Panic, 8, c"panic"),
            (ErrorCode::InvalidBuffer, 9, c"invalid buffer"),
        ] {
            assert_eq!(status(error), (number, message));
        }
    }
    #[test]
    fn transient_constructor_failure_is_not_cached() {
        let slot = Mutex::new(None);
        let first = get_or_build(&slot, || Err(ScopeError::new(ErrorCode::ResourceLimit)));
        assert!(matches!(
            first,
            Err(ScopeError {
                code: ErrorCode::ResourceLimit
            })
        ));
        assert!(slot.lock().expect("slot").is_none());
        assert!(get_or_build(&slot, Hardware::new).is_ok());
    }
    #[test]
    fn live_buffer_limit_and_real_collection_leave_no_registry_entries() {
        let baseline = REGISTRY.lock().expect("registry").entries.len();
        let mut buffers = Vec::new();
        for _ in baseline..64 {
            let mut buffer = DscBuffer::default();
            // SAFETY: live zero-initialized output, default options; serial test execution.
            let code = unsafe { dsc_collect_json(std::ptr::null(), &mut buffer) };
            assert_eq!(code, 0);
            // SAFETY: library allocation is live for buffer.len bytes until free below.
            let bytes = unsafe { std::slice::from_raw_parts(buffer.data, buffer.len) };
            assert!(from_json(bytes).is_ok());
            buffers.push(buffer);
        }
        let mut overflow = DscBuffer::default();
        // SAFETY: same live output contract, capacity failure leaves it empty.
        let code = unsafe { dsc_collect_json(std::ptr::null(), &mut overflow) };
        assert_eq!(code, 7);
        assert!(overflow.data.is_null());
        for buffer in &mut buffers {
            // SAFETY: each buffer owns a distinct live registered allocation, used no longer.
            assert_eq!(unsafe { dsc_buffer_free(buffer) }, 0);
        }
        assert_eq!(REGISTRY.lock().expect("registry").entries.len(), baseline);
    }
    // These tests contain no hardware calls; the entire module runs under Miri.
    mod memory_contracts {
        use super::*;
        fn allocate() -> DscBuffer {
            REGISTRY
                .lock()
                .expect("registry")
                .insert(b"test".to_vec().into_boxed_slice())
                .expect("allocation")
        }
        #[test]
        fn free_rejects_stale_copy_and_tampering() {
            let mut buffer = allocate();
            let mut stale = buffer;
            let mut wrong = buffer;
            wrong.len += 1;
            // SAFETY: all pointers reference live local initialized structs; no data is dereferenced.
            unsafe {
                assert_eq!(dsc_buffer_free(&mut wrong), 9);
                assert_eq!(dsc_buffer_free(&mut buffer), 0);
                assert!(buffer.data.is_null());
                assert_eq!(dsc_buffer_free(&mut buffer), 0);
                assert_eq!(dsc_buffer_free(&mut stale), 9);
                assert_eq!(dsc_buffer_free(std::ptr::null_mut()), 1);
            }
        }
        #[test]
        fn catches_panic_and_error_is_thread_local() {
            assert_eq!(boundary(|| panic!("test")), 8);
            assert_eq!(LAST_ERROR.get(), c"panic");
            std::thread::spawn(|| {
                assert_eq!(LAST_ERROR.get(), c"");
                assert_eq!(boundary(|| Err(ScopeError::new(ErrorCode::Timeout))), 3);
            })
            .join()
            .expect("thread");
            assert_eq!(LAST_ERROR.get(), c"panic");
        }
        #[test]
        fn validates_options_without_collecting() {
            let valid = DscOptions {
                size: 20,
                version: 1,
                flags: 0,
                timeout_ms: 1000,
                max_entries: 10,
            };
            assert!(options(valid).is_ok());
            for raw in [
                DscOptions {
                    version: 2,
                    ..valid
                },
                DscOptions { flags: 4, ..valid },
                DscOptions { flags: 1, ..valid },
                DscOptions {
                    max_entries: 0,
                    ..valid
                },
            ] {
                assert!(options(raw).is_err());
            }
        }
        #[test]
        fn invalid_abi_inputs_leave_output_empty() {
            let invalid = DscOptions {
                size: 20,
                version: 2,
                flags: 0,
                timeout_ms: 1000,
                max_entries: 10,
            };
            let mut empty = DscBuffer::default();
            let mut occupied = DscBuffer {
                data: std::ptr::dangling(),
                len: 1,
                token: 999,
            };
            // SAFETY: local live aligned structs; invalid version/nonempty output are rejected before collection.
            unsafe {
                assert_eq!(dsc_collect_json(&invalid, &mut empty), 1);
                assert_eq!(CStr::from_ptr(dsc_last_error()), c"invalid argument");
                assert_eq!(dsc_collect_json(&invalid, &mut occupied), 9);
                assert_eq!(dsc_collect_json(&invalid, std::ptr::null_mut()), 1);
            }
            assert!(empty.data.is_null());
            assert_eq!(empty.len, 0);
            assert_eq!(empty.token, 0);
            assert_eq!(occupied.token, 999);
        }
        #[test]
        fn independent_threads_read_and_free_owned_buffers() {
            let baseline = REGISTRY.lock().expect("registry").entries.len();
            let threads = (0..8)
                .map(|_| {
                    std::thread::spawn(|| {
                        for _ in 0..8 {
                            let mut buffer = allocate();
                            // SAFETY: each thread owns its distinct registered allocation until free.
                            unsafe {
                                assert_eq!(
                                    std::slice::from_raw_parts(buffer.data, buffer.len),
                                    b"test"
                                );
                                assert_eq!(dsc_buffer_free(&mut buffer), 0);
                            }
                        }
                    })
                })
                .collect::<Vec<_>>();
            for thread in threads {
                thread.join().expect("worker");
            }
            assert_eq!(REGISTRY.lock().expect("registry").entries.len(), baseline);
        }
        #[test]
        fn live_pointers_survive_registry_growth() {
            let baseline = REGISTRY.lock().expect("registry").entries.len();
            let mut buffers = (baseline..64).map(|_| allocate()).collect::<Vec<_>>();
            for buffer in &mut buffers {
                // SAFETY: all allocations are still owned by the registry after growth/rehashing.
                unsafe {
                    assert_eq!(std::slice::from_raw_parts(buffer.data, buffer.len), b"test");
                    assert_eq!(dsc_buffer_free(buffer), 0);
                }
            }
            assert_eq!(REGISTRY.lock().expect("registry").entries.len(), baseline);
        }
        #[test]
        fn allocation_limits_and_token_exhaustion_are_transactional() {
            let mut registry = Registry {
                next: u64::MAX,
                entries: HashMap::new(),
            };
            assert!(matches!(
                registry.insert(vec![0; 4].into_boxed_slice()),
                Err(ScopeError {
                    code: ErrorCode::ResourceLimit
                })
            ));
            assert!(registry.entries.is_empty());
            assert_eq!(registry.next, u64::MAX);
            registry.next = 1;
            assert!(
                registry
                    .insert(vec![0; MAX_JSON_BYTES + 1].into_boxed_slice())
                    .is_err()
            );
            assert_eq!(registry.next, 1);
            for _ in 0..64 {
                registry
                    .insert(vec![1].into_boxed_slice())
                    .expect("within limit");
            }
            assert!(registry.insert(vec![2].into_boxed_slice()).is_err());
            assert_eq!(registry.next, 65);
            assert_eq!(registry.entries.len(), 64);
        }
        #[test]
        fn repeated_cycles_reject_forged_and_stale_descriptors() {
            let baseline = REGISTRY.lock().expect("registry").entries.len();
            let mut previous = DscBuffer::default();
            for _ in 0..128 {
                let mut buffer = allocate();
                // SAFETY: allocation is live and holds exactly buffer.len initialized bytes.
                let contents = unsafe { std::slice::from_raw_parts(buffer.data, buffer.len) };
                assert_eq!(contents, b"test");
                let mut wrong = buffer;
                wrong.data = std::ptr::dangling();
                // SAFETY: local initialized structs; free checks but never dereferences data pointers.
                unsafe {
                    assert_eq!(dsc_buffer_free(&mut wrong), 9);
                    wrong = buffer;
                    wrong.token = 0;
                    assert_eq!(dsc_buffer_free(&mut wrong), 9);
                    if previous.token != 0 {
                        assert_eq!(dsc_buffer_free(&mut previous), 9);
                    }
                    previous = buffer;
                    assert_eq!(dsc_buffer_free(&mut buffer), 0);
                }
                assert!(buffer.data.is_null());
                assert_eq!(buffer.len, 0);
                assert_eq!(buffer.token, 0);
                assert_eq!(REGISTRY.lock().expect("registry").entries.len(), baseline);
            }
        }
    }
}
