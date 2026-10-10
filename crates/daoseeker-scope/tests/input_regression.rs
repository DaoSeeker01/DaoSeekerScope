#![cfg(feature = "serde")]
use daoseeker_scope::{from_json, to_json};

#[test]
fn seeded_json_mutations_preserve_invariants_when_accepted() {
    let golden = include_bytes!("fixtures/snapshot-v1.json");
    let mut state = 0x4453_435f_2026_1008u64;
    let mut accepted = 0;
    for case in 0..512 {
        let mut bytes = golden.to_vec();
        if case % 8 != 0 {
            for _ in 0..=case % 16 {
                state ^= state << 13;
                state ^= state >> 7;
                state ^= state << 17;
                let index = state as usize % bytes.len();
                match state % 4 {
                    0 => bytes[index] = (state >> 32) as u8,
                    1 => {
                        bytes.remove(index);
                    }
                    2 => bytes.insert(index, (state >> 24) as u8),
                    _ => bytes[index] = b' ',
                }
            }
        }
        if let Ok(snapshot) = from_json(&bytes) {
            accepted += 1;
            let encoded = to_json(&snapshot).expect("accepted model serializes");
            assert_eq!(from_json(encoded.as_bytes()).expect("roundtrip"), snapshot);
        }
    }
    assert!(
        accepted >= 64,
        "valid corpus must exercise successful decoding"
    );
}

#[test]
fn excessive_json_nesting_is_rejected_without_stack_overflow() {
    let bytes = format!("{}0{}", "[".repeat(512), "]".repeat(512));
    assert!(from_json(bytes.as_bytes()).is_err());
}

#[test]
fn compact_json_cannot_expand_beyond_exchange_limit() {
    let mut value: serde_json::Value =
        serde_json::from_slice(include_bytes!("fixtures/snapshot-v1.json")).unwrap();
    let collection = serde_json::json!({"value": vec![serde_json::json!({}); 1024], "availability": "available", "source": "custom", "observed_at": 1, "reason": null});
    for field in ["gpus", "storage", "displays"] {
        value["static_info"][field] = collection.clone();
    }
    for field in ["batteries", "sensors", "networks"] {
        value["dynamic"][field] = collection.clone();
    }
    let bytes = serde_json::to_vec(&value).unwrap();
    assert!(bytes.len() < daoseeker_scope::MAX_JSON_BYTES);
    let error = match from_json(&bytes) {
        Err(error) => error,
        Ok(_) => panic!("expanded JSON must be rejected"),
    };
    assert_eq!(error.code, daoseeker_scope::ErrorCode::ResourceLimit);
    let snapshot = serde_json::from_slice(&bytes).unwrap();
    match to_json(&snapshot) {
        Err(error) => assert_eq!(error.code, daoseeker_scope::ErrorCode::ResourceLimit),
        Ok(_) => panic!("encoding is bounded"),
    }
}
