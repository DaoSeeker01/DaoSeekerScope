//! Independent Rust measurements for the native C/Rust contract check.
use daoseeker_scope::SCHEMA_VERSION;
use daoseeker_scope_ffi::{
    ABI_VERSION, DscBuffer, DscOptions, dsc_abi_version, dsc_buffer_free, dsc_collect_json,
    dsc_last_error,
};
use std::{
    ffi::c_char,
    mem::{align_of, offset_of, size_of},
};

fn main() {
    // Assignments also type-check the public Rust function signatures. Only the
    // version function is called: this probe does not start a hardware worker.
    let version: extern "C" fn() -> u32 = dsc_abi_version;
    let _: unsafe extern "C" fn(*const DscOptions, *mut DscBuffer) -> i32 = dsc_collect_json;
    let _: unsafe extern "C" fn(*mut DscBuffer) -> i32 = dsc_buffer_free;
    let _: extern "C" fn() -> *const c_char = dsc_last_error;
    assert_eq!(version(), ABI_VERSION);
    println!(
        concat!(
            "{{\"abi_version\":{},\"schema_version\":{},\"pointer_bytes\":{},",
            "\"options\":{{\"size\":{},\"alignment\":{},\"offsets\":[{},{},{},{},{}]}},",
            "\"buffer\":{{\"size\":{},\"alignment\":{},\"offsets\":[{},{},{}]}}}}"
        ),
        version(),
        SCHEMA_VERSION,
        size_of::<*const u8>(),
        size_of::<DscOptions>(),
        align_of::<DscOptions>(),
        offset_of!(DscOptions, size),
        offset_of!(DscOptions, version),
        offset_of!(DscOptions, flags),
        offset_of!(DscOptions, timeout_ms),
        offset_of!(DscOptions, max_entries),
        size_of::<DscBuffer>(),
        align_of::<DscBuffer>(),
        offset_of!(DscBuffer, data),
        offset_of!(DscBuffer, len),
        offset_of!(DscBuffer, token),
    );
}
