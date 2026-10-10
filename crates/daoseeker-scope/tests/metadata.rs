#![cfg(feature = "serde")]
use daoseeker_scope::*;

#[test]
fn invalid_metadata_is_rejected_on_encode_and_decode() {
    let base = from_json(include_bytes!("fixtures/snapshot-v1.json")).unwrap();
    for value in ["", "field\nname", &"观".repeat(43)] {
        let mut snapshot = base.clone();
        snapshot.capabilities[0] = Capability::new(value, CapabilityLevel::Partial, Source::Custom);
        assert!(to_json(&snapshot).is_err());
        let bytes = serde_json::to_vec(&snapshot).unwrap();
        assert!(from_json(&bytes).is_err());
        let mut snapshot = base.clone();
        snapshot.issues.push(BackendIssue {
            backend: value.into(),
            code: ErrorCode::BackendFailure,
        });
        assert!(to_json(&snapshot).is_err());
        assert!(from_json(&serde_json::to_vec(&snapshot).unwrap()).is_err());
    }
    let mut snapshot = base;
    snapshot.capabilities[0] =
        Capability::new("future_field", CapabilityLevel::Partial, Source::Custom);
    assert_eq!(
        from_json(to_json(&snapshot).unwrap().as_bytes()).unwrap(),
        snapshot
    );
}
