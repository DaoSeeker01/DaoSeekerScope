#![no_main]
mod common;
use daoseeker_scope::Source;
use daoseeker_scope_linux::fuzzing::storage_capacity;
libfuzzer_sys::fuzz_target!(|data: &[u8]| {
    let item = storage_capacity(data);
    common::observed(&item, Source::Sysfs);
    assert_eq!(storage_capacity(data), item);
    if let Some(value) = item.value() {
        assert!(data.len() <= 128);
        assert_eq!(value % 512, 0);
        let text = std::str::from_utf8(data)
            .expect("valid decimal")
            .trim_ascii();
        let sectors = text.parse::<u64>().expect("valid sectors");
        assert_eq!(sectors.checked_mul(512), Some(*value));
    }
});
