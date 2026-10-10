#![no_main]
use daoseeker_scope::{Availability, ReasonCode, Source, Timestamp};
use daoseeker_scope_linux::fuzzing::{hwmon_nvme_temperature, hwmon_temperature};
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let result = hwmon_temperature(data);
    assert_eq!(result, hwmon_temperature(data));
    assert_eq!(result.source(), Source::Hwmon);
    if let Some(value) = result.value() {
        assert!(value.is_finite() && (-273.15..=1000.0).contains(value));
        assert_eq!(result.availability(), Availability::Available);
        assert_eq!(result.observed_at(), Some(Timestamp(1)));
        assert_eq!(result.reason(), None);
        let milli = (value * 1000.0).round() as i32;
        let canonical = format!("{milli}\n");
        assert_eq!(hwmon_temperature(canonical.as_bytes()).value(), Some(value));
    } else {
        assert_eq!(result.availability(), Availability::Unavailable);
        assert_eq!(result.observed_at(), None);
        assert_eq!(result.reason(), Some(ReasonCode::InvalidData));
    }
    if data.len() > 128 {
        assert!(result.value().is_none());
    }
    for secondary in [false, true] {
        let nvme = hwmon_nvme_temperature(data, secondary);
        assert_eq!(nvme, hwmon_nvme_temperature(data, secondary));
        if result.value() == Some(&-273.15) {
            assert_eq!(nvme.value(), None);
            assert_eq!(nvme.source(), Source::Hwmon);
            assert_eq!(nvme.availability(), Availability::Unavailable);
            assert_eq!(nvme.observed_at(), None);
            assert_eq!(
                nvme.reason(),
                Some(if secondary {
                    ReasonCode::NotPresent
                } else {
                    ReasonCode::InvalidData
                })
            );
        } else {
            assert_eq!(nvme, result);
        }
    }
});
