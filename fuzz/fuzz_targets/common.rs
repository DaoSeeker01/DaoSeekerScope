use daoseeker_scope::{Availability, Observed, Source};

pub fn observed<T>(item: &Observed<T>, source: Source) {
    assert_eq!(item.source(), source);
    if item.value().is_some() {
        assert_eq!(item.availability(), Availability::Available);
        assert!(item.observed_at().is_some());
        assert!(item.reason().is_none());
    } else {
        assert_ne!(item.availability(), Availability::Available);
        assert!(item.observed_at().is_none());
        assert!(item.reason().is_some());
    }
}
