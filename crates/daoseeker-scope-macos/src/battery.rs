//! Public IOPowerSources internal batteries; no names or stable identifiers.
use daoseeker_scope_core::*;

const MAX_SOURCES: usize = 256;
#[derive(Debug, Clone, Copy, PartialEq)]
struct Failure(Availability, ReasonCode);
const INVALID: Failure = Failure(Availability::Unavailable, ReasonCode::InvalidData);
const UNKNOWN: Failure = Failure(Availability::Unavailable, ReasonCode::Unknown);
const MISSING: Failure = Failure(Availability::Unavailable, ReasonCode::NotPresent);
const TEMPORARY: Failure = Failure(
    Availability::Unavailable,
    ReasonCode::TemporarilyUnavailable,
);
const UNSUPPORTED: Failure = Failure(Availability::Unsupported, ReasonCode::NotSupported);
impl Failure {
    fn observed<T>(self) -> Observed<T> {
        Observed::missing(self.0, Source::Iokit, self.1).expect("missing battery observation")
    }
}
#[derive(Debug, Clone, Copy)]
enum Power {
    Ac,
    Battery,
    Offline,
}
#[derive(Debug, Clone, Copy)]
struct Reading {
    current: Result<i64, Failure>,
    maximum: Result<i64, Failure>,
    power: Result<Power, Failure>,
}
trait Api {
    fn count(&self) -> usize;
    fn entry(&mut self, index: usize) -> Result<Option<Reading>, Failure>;
}
fn percentage(
    current: Result<i64, Failure>,
    maximum: Result<i64, Failure>,
) -> Result<f64, Failure> {
    let (current, maximum) = (current?, maximum?);
    if maximum <= 0 || current < 0 || current > maximum {
        return Err(INVALID);
    }
    Ok(current as f64 / maximum as f64 * 100.0)
}
fn observed<T>(value: Result<T, Failure>, at: Timestamp) -> Observed<T> {
    match value {
        Ok(value) => Observed::available(value, Source::Iokit, at),
        Err(failure) => failure.observed(),
    }
}
fn collect_with(
    api: &mut impl Api,
    options: &Options,
    at: Timestamp,
    mut check: impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<Vec<BatteryInfo>>, ScopeError> {
    options.validate()?;
    check()?;
    let count = api.count();
    if count > MAX_SOURCES {
        return Ok(INVALID.observed());
    }
    let mut entries = Vec::with_capacity(count.min(options.max_entries));
    for index in 0..count {
        check()?;
        let reading = api.entry(index);
        check()?;
        let reading = match reading {
            Ok(None) => continue,
            Ok(Some(value)) if entries.len() < options.max_entries => value,
            Ok(Some(_)) => return Ok(INVALID.observed()),
            Err(failure) => return Ok(failure.observed()),
        };
        let power = match reading.power {
            Ok(Power::Ac) => Ok(true),
            Ok(Power::Battery) => Ok(false),
            Ok(Power::Offline) => Err(TEMPORARY),
            Err(error) => Err(error),
        };
        let mut battery = BatteryInfo::default();
        battery.charge_percent = observed(percentage(reading.current, reading.maximum), at);
        battery.on_ac_power = observed(power, at);
        entries.push(battery);
    }
    check()?;
    Ok(Observed::available(entries, Source::Iokit, at))
}

#[cfg(target_os = "macos")]
mod native {
    use super::*;
    use objc2_core_foundation::{
        CFArray, CFBoolean, CFDictionary, CFNumber, CFRetained, CFString, CFType,
    };
    use objc2_io_kit::{
        IOPSCopyPowerSourcesInfo, IOPSCopyPowerSourcesList, IOPSGetPowerSourceDescription,
    };

    // Drop the list before its opaque source snapshot. No native references escape.
    struct NativeApi {
        list: CFRetained<CFArray<CFType>>,
        blob: CFRetained<CFType>,
    }
    impl NativeApi {
        fn new() -> Result<Self, Failure> {
            let blob = IOPSCopyPowerSourcesInfo().ok_or(UNKNOWN)?;
            // SAFETY: the live opaque object came from IOPSCopyPowerSourcesInfo.
            let list = unsafe { IOPSCopyPowerSourcesList(Some(&blob)) }.ok_or(UNKNOWN)?;
            // SAFETY: IOPSCopyPowerSourcesList documents an array of CFType handles.
            let list = unsafe { CFRetained::cast_unchecked::<CFArray<CFType>>(list) };
            Ok(Self { list, blob })
        }
        fn property(
            object: &CFDictionary<CFString, CFType>,
            key: &str,
        ) -> Result<CFRetained<CFType>, Failure> {
            object.get(&CFString::from_str(key)).ok_or(MISSING)
        }
        fn integer(object: &CFDictionary<CFString, CFType>, key: &str) -> Result<i64, Failure> {
            let property = Self::property(object, key)?;
            let number = property.downcast_ref::<CFNumber>().ok_or(INVALID)?;
            if number.is_float_type() {
                return Err(INVALID);
            }
            number.as_i64().ok_or(INVALID)
        }
        fn is(object: &CFType, text: &str) -> Result<bool, Failure> {
            let value = object.downcast_ref::<CFString>().ok_or(INVALID)?;
            Ok(value == &*CFString::from_str(text))
        }
        fn description(
            object: &CFDictionary<CFString, CFType>,
        ) -> Result<Option<Reading>, Failure> {
            let kind = Self::property(object, "Type").map_err(|_| INVALID)?;
            if Self::is(&kind, "UPS")? {
                return Ok(None);
            }
            if !Self::is(&kind, "InternalBattery")? {
                return Err(UNSUPPORTED);
            }
            let present = Self::property(object, "Is Present").map_err(|_| INVALID)?;
            if !present.downcast_ref::<CFBoolean>().ok_or(INVALID)?.value() {
                return Ok(None);
            }
            let power = Self::property(object, "Power Source State").and_then(|value| {
                if Self::is(&value, "AC Power")? {
                    Ok(Power::Ac)
                } else if Self::is(&value, "Battery Power")? {
                    Ok(Power::Battery)
                } else if Self::is(&value, "Off Line")? {
                    Ok(Power::Offline)
                } else {
                    Err(INVALID)
                }
            });
            Ok(Some(Reading {
                current: Self::integer(object, "Current Capacity"),
                maximum: Self::integer(object, "Max Capacity"),
                power,
            }))
        }
    }
    impl Api for NativeApi {
        fn count(&self) -> usize {
            self.list.len()
        }
        fn entry(&mut self, index: usize) -> Result<Option<Reading>, Failure> {
            let handle = self.list.get(index).ok_or(INVALID)?;
            // SAFETY: both references originate from the same still-live snapshot.
            // The binding retains the Get result; its CFRetained releases that retain.
            let object = unsafe { IOPSGetPowerSourceDescription(Some(&self.blob), Some(&handle)) }
                .ok_or(UNKNOWN)?;
            // SAFETY: the public description contains CFString keys and CFType values.
            // Individual value types are still checked before conversion below.
            let object =
                unsafe { CFRetained::cast_unchecked::<CFDictionary<CFString, CFType>>(object) };
            Self::description(&object)
        }
    }
    pub(crate) fn collect(
        context: &CollectContext,
    ) -> Result<Observed<Vec<BatteryInfo>>, ScopeError> {
        context.options.validate()?;
        context.check()?;
        let api = NativeApi::new();
        context.check()?;
        match api {
            Ok(mut api) => collect_with(&mut api, &context.options, Timestamp::now()?, || {
                context.check()
            }),
            Err(failure) => Ok(failure.observed()),
        }
    }
    #[cfg(test)]
    mod tests {
        use super::*;
        fn dictionary(
            fields: Vec<(&str, CFRetained<CFType>)>,
        ) -> CFRetained<CFDictionary<CFString, CFType>> {
            let keys: Vec<_> = fields
                .iter()
                .map(|(key, _)| CFString::from_str(key))
                .collect();
            let keys: Vec<_> = keys.iter().map(|key| &**key).collect();
            let values: Vec<_> = fields.iter().map(|(_, value)| &**value).collect();
            CFDictionary::from_slices(&keys, &values)
        }
        fn boolean(value: bool) -> CFRetained<CFType> {
            CFRetained::<CFBoolean>::from(CFBoolean::new(value)).into()
        }
        #[test]
        fn public_cf_battery_description_units_types_and_filtering() {
            let create = |current: CFRetained<CFType>, state: &str| {
                dictionary(vec![
                    ("Type", CFString::from_str("InternalBattery").into()),
                    ("Is Present", boolean(true)),
                    ("Current Capacity", current),
                    ("Max Capacity", CFNumber::new_i64(200).into()),
                    ("Power Source State", CFString::from_str(state).into()),
                    (
                        "Name",
                        CFString::from_str("PRIVATE-must-not-be-extracted").into(),
                    ),
                ])
            };
            let reading = NativeApi::description(&create(CFNumber::new_i64(50).into(), "AC Power"))
                .expect("description")
                .expect("battery");
            assert_eq!(percentage(reading.current, reading.maximum), Ok(25.0));
            assert!(matches!(reading.power, Ok(Power::Ac)));
            for state in ["AC Power", "Battery Power", "Off Line", "unknown"] {
                let reading = NativeApi::description(&create(CFNumber::new_f64(1.0).into(), state))
                    .expect("description")
                    .expect("battery");
                assert_eq!(reading.current, Err(INVALID));
                assert_eq!(reading.maximum, Ok(200));
                assert!(match state {
                    "AC Power" => matches!(reading.power, Ok(Power::Ac)),
                    "Battery Power" => matches!(reading.power, Ok(Power::Battery)),
                    "Off Line" => matches!(reading.power, Ok(Power::Offline)),
                    _ => matches!(reading.power, Err(INVALID)),
                });
            }
            assert!(
                NativeApi::description(&dictionary(vec![(
                    "Type",
                    CFString::from_str("UPS").into()
                )]))
                .expect("UPS")
                .is_none()
            );
            assert!(
                NativeApi::description(&dictionary(vec![
                    ("Type", CFString::from_str("InternalBattery").into()),
                    ("Is Present", boolean(false))
                ]))
                .expect("absent")
                .is_none()
            );
            assert!(matches!(
                NativeApi::description(&dictionary(vec![(
                    "Type",
                    CFString::from_str("other").into()
                )])),
                Err(UNSUPPORTED)
            ));
            assert!(matches!(
                NativeApi::description(&dictionary(vec![
                    ("Type", CFString::from_str("InternalBattery").into()),
                    ("Is Present", CFNumber::new_i64(1).into())
                ])),
                Err(INVALID)
            ));
            assert!(matches!(
                NativeApi::description(&dictionary(vec![])),
                Err(INVALID)
            ));
        }
    }
}
#[cfg(target_os = "macos")]
pub(super) use native::collect;

#[cfg(test)]
mod tests {
    use super::*;
    type Row = Result<Option<Reading>, Failure>;
    struct Fake {
        rows: Vec<Row>,
        reads: usize,
    }
    impl Api for Fake {
        fn count(&self) -> usize {
            self.rows.len()
        }
        fn entry(&mut self, index: usize) -> Row {
            self.reads += 1;
            self.rows[index]
        }
    }
    fn row(current: i64, maximum: i64, power: Power) -> Row {
        Ok(Some(Reading {
            current: Ok(current),
            maximum: Ok(maximum),
            power: Ok(power),
        }))
    }
    fn read(rows: Vec<Row>) -> Observed<Vec<BatteryInfo>> {
        collect_with(
            &mut Fake { rows, reads: 0 },
            &Options::default(),
            Timestamp(1),
            || Ok(()),
        )
        .expect("collection")
    }
    #[test]
    fn battery_percentage_has_real_zero_and_validates_units() {
        for (current, maximum, value) in [
            (0, 100, 0.0),
            (50, 200, 25.0),
            (200, 200, 100.0),
            (i64::MAX, i64::MAX, 100.0),
        ] {
            assert_eq!(percentage(Ok(current), Ok(maximum)), Ok(value));
        }
        for (current, maximum) in [(-1, 100), (1, 0), (0, 0), (101, 100), (1, -100)] {
            assert_eq!(percentage(Ok(current), Ok(maximum)), Err(INVALID));
        }
        assert_eq!(percentage(Err(MISSING), Ok(100)), Err(MISSING));
    }
    #[test]
    fn battery_field_failures_do_not_drop_healthy_values() {
        let result = read(vec![
            Ok(Some(Reading {
                current: Err(INVALID),
                maximum: Ok(100),
                power: Ok(Power::Ac),
            })),
            Ok(Some(Reading {
                current: Ok(50),
                maximum: Ok(100),
                power: Err(MISSING),
            })),
            row(100, 200, Power::Offline),
        ]);
        assert_eq!(result.source(), Source::Iokit);
        let entries = result.value().expect("entries");
        assert_eq!(
            entries[0].charge_percent.reason(),
            Some(ReasonCode::InvalidData)
        );
        assert_eq!(entries[0].on_ac_power.value(), Some(&true));
        assert_eq!(entries[1].charge_percent.value(), Some(&50.0));
        assert_eq!(
            entries[1].on_ac_power.reason(),
            Some(ReasonCode::NotPresent)
        );
        assert_eq!(entries[2].charge_percent.value(), Some(&50.0));
        assert_eq!(
            entries[2].on_ac_power.reason(),
            Some(ReasonCode::TemporarilyUnavailable)
        );
        assert_eq!(entries[1].charge_percent.observed_at(), Some(Timestamp(1)));
    }
    #[test]
    fn battery_empty_error_and_unsupported_views_differ() {
        assert!(read(vec![Ok(None)]).value().expect("filtered").is_empty());
        for failure in [UNKNOWN, UNSUPPORTED, INVALID] {
            let result = read(vec![Err(failure)]);
            assert_eq!(result.availability(), failure.0);
            assert_eq!(result.reason(), Some(failure.1));
            assert!(result.value().is_none());
        }
    }
    #[test]
    fn battery_limits_include_filtered_sources() {
        let mut fake = Fake {
            rows: vec![Ok(None); MAX_SOURCES + 1],
            reads: 0,
        };
        let result =
            collect_with(&mut fake, &Options::default(), Timestamp(1), || Ok(())).expect("limited");
        assert_eq!(result.reason(), Some(ReasonCode::InvalidData));
        assert_eq!(fake.reads, 0);
        assert!(
            read(vec![Ok(None); MAX_SOURCES])
                .value()
                .expect("boundary")
                .is_empty()
        );
        let options = Options {
            max_entries: 1,
            ..Options::default()
        };
        let result = collect_with(
            &mut Fake {
                rows: vec![row(50, 100, Power::Battery); 2],
                reads: 0,
            },
            &options,
            Timestamp(1),
            || Ok(()),
        )
        .expect("entry limit");
        assert_eq!(result.reason(), Some(ReasonCode::InvalidData));
    }
    #[test]
    fn battery_cancel_and_timeout_precede_api_failure() {
        for code in [ErrorCode::Cancelled, ErrorCode::Timeout] {
            let mut checks = 0;
            let result = collect_with(
                &mut Fake {
                    rows: vec![Err(UNKNOWN)],
                    reads: 0,
                },
                &Options::default(),
                Timestamp(1),
                || {
                    checks += 1;
                    if checks == 3 {
                        Err(ScopeError::new(code))
                    } else {
                        Ok(())
                    }
                },
            );
            assert_eq!(result.expect_err("stopped").code, code);
        }
    }
    #[test]
    fn battery_refresh_observes_changes_without_static_reread() {
        use std::sync::{
            Arc, Mutex,
            atomic::{AtomicUsize, Ordering},
        };
        struct Fixture {
            rows: Arc<Mutex<Vec<Row>>>,
            statics: Arc<AtomicUsize>,
        }
        impl Backend for Fixture {
            fn name(&self) -> &'static str {
                "battery-fixture"
            }
            fn capabilities(&self) -> Capabilities {
                vec![Capability::new(
                    "batteries",
                    CapabilityLevel::Partial,
                    Source::Iokit,
                )]
            }
            fn collect_static(
                &mut self,
                context: &CollectContext,
            ) -> Result<StaticSnapshot, ScopeError> {
                context.check()?;
                self.statics.fetch_add(1, Ordering::SeqCst);
                Ok(StaticSnapshot::default())
            }
            fn refresh_dynamic(
                &mut self,
                context: &CollectContext,
            ) -> Result<DynamicSnapshot, ScopeError> {
                let mut result = DynamicSnapshot::default();
                let rows = self.rows.lock().expect("rows").clone();
                result.batteries = collect_with(
                    &mut Fake { rows, reads: 0 },
                    &context.options,
                    Timestamp::now()?,
                    || context.check(),
                )?;
                Ok(result)
            }
        }
        let rows = Arc::new(Mutex::new(vec![row(50, 200, Power::Ac)]));
        let statics = Arc::new(AtomicUsize::new(0));
        let hardware = HardwareBuilder::default()
            .with_backend(
                100,
                Fixture {
                    rows: rows.clone(),
                    statics: statics.clone(),
                },
            )
            .build()
            .expect("hardware");
        let first = hardware.collect().expect("first");
        assert_eq!(
            first.dynamic.batteries.value().expect("battery")[0]
                .charge_percent
                .value(),
            Some(&25.0)
        );
        *rows.lock().expect("rows") = vec![row(0, 100, Power::Battery)];
        let fresh = hardware.refresh_dynamic().expect("refresh");
        assert_eq!(
            fresh.batteries.value().expect("battery")[0]
                .charge_percent
                .value(),
            Some(&0.0)
        );
        assert_eq!(
            fresh.batteries.value().expect("battery")[0]
                .on_ac_power
                .value(),
            Some(&false)
        );
        assert_eq!(
            hardware.collect().expect("cached static").static_info,
            first.static_info
        );
        assert_eq!(statics.load(Ordering::SeqCst), 1);
    }
}
