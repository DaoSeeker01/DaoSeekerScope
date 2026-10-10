#![no_main]
libfuzzer_sys::fuzz_target!(|data: &[u8]| {
    if let Ok(snapshot) = daoseeker_scope::from_json(data) {
        let encoded = daoseeker_scope::to_json(&snapshot).expect("valid snapshot serializes");
        assert_eq!(
            snapshot,
            daoseeker_scope::from_json(encoded.as_bytes()).expect("round trip")
        );
    }
});
