//! Windows system power summary. Entries do not enumerate individual batteries.
use daoseeker_scope_core::*;

pub(crate) fn observe(
    flag: u8,
    percent: u8,
    ac: u8,
) -> Result<Observed<Vec<BatteryInfo>>, ScopeError> {
    if flag == 255 {
        return Ok(Observed::unavailable(
            Source::Win32,
            ReasonCode::TemporarilyUnavailable,
        ));
    }
    if flag & 128 != 0 {
        return Ok(Observed::not_applicable(Source::Win32));
    }
    let at = Timestamp::now()?;
    let mut battery = BatteryInfo::default();
    battery.charge_percent = match percent {
        0..=100 => Observed::available(f64::from(percent), Source::Win32, at),
        255 => Observed::unavailable(Source::Win32, ReasonCode::TemporarilyUnavailable),
        _ => Observed::unavailable(Source::Win32, ReasonCode::InvalidData),
    };
    battery.on_ac_power = match ac {
        0 => Observed::available(false, Source::Win32, at),
        1 => Observed::available(true, Source::Win32, at),
        255 => Observed::unavailable(Source::Win32, ReasonCode::TemporarilyUnavailable),
        _ => Observed::unavailable(Source::Win32, ReasonCode::InvalidData),
    };
    Ok(Observed::available(vec![battery], Source::Win32, at))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn battery(percent: u8, ac: u8) -> BatteryInfo {
        let result = observe(0, percent, ac).expect("observation");
        assert_eq!(result.availability(), Availability::Available);
        assert_eq!(result.source(), Source::Win32);
        assert!(result.observed_at().is_some());
        let mut items = result.value().expect("one summary").clone();
        assert_eq!(items.len(), 1);
        items.pop().expect("summary")
    }

    #[test]
    fn every_percentage_preserves_ac_and_distinguishes_invalid_from_unknown() {
        for percent in 0..=255 {
            let result = battery(percent, 1);
            assert_eq!(result.on_ac_power.value(), Some(&true));
            assert_eq!(result.charge_percent.source(), Source::Win32);
            match percent {
                0..=100 => {
                    assert_eq!(result.charge_percent.value(), Some(&f64::from(percent)));
                    assert!(result.charge_percent.observed_at().is_some());
                    assert_eq!(result.charge_percent.reason(), None);
                }
                _ => {
                    assert_eq!(result.charge_percent.value(), None);
                    assert_eq!(result.charge_percent.observed_at(), None);
                    assert_eq!(
                        result.charge_percent.reason(),
                        Some(if percent == 255 {
                            ReasonCode::TemporarilyUnavailable
                        } else {
                            ReasonCode::InvalidData
                        })
                    );
                }
            }
        }
    }

    #[test]
    fn every_ac_byte_preserves_charge_and_never_infers_online_from_charging() {
        for ac in 0..=255 {
            let result = observe(8, 50, ac).expect("charging summary");
            let result = &result.value().expect("battery")[0];
            assert_eq!(result.charge_percent.value(), Some(&50.0));
            assert_eq!(result.on_ac_power.source(), Source::Win32);
            match ac {
                0 | 1 => {
                    assert_eq!(result.on_ac_power.value(), Some(&(ac == 1)));
                    assert!(result.on_ac_power.observed_at().is_some());
                    assert_eq!(result.on_ac_power.reason(), None);
                }
                _ => {
                    assert_eq!(result.on_ac_power.value(), None);
                    assert_eq!(result.on_ac_power.observed_at(), None);
                    assert_eq!(
                        result.on_ac_power.reason(),
                        Some(if ac == 255 {
                            ReasonCode::TemporarilyUnavailable
                        } else {
                            ReasonCode::InvalidData
                        })
                    );
                }
            }
        }
    }

    #[test]
    fn no_system_battery_and_unknown_flag_do_not_produce_fake_entries() {
        for (flag, availability, reason) in [
            (128, Availability::NotApplicable, ReasonCode::NotPresent),
            (
                255,
                Availability::Unavailable,
                ReasonCode::TemporarilyUnavailable,
            ),
        ] {
            let result = observe(flag, 0, 0).expect("missing summary");
            assert_eq!(result.availability(), availability);
            assert_eq!(result.reason(), Some(reason));
            assert_eq!(result.value(), None);
            assert_eq!(result.observed_at(), None);
        }
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn native_battery_summary_matches_sdk_and_declares_partial_scope() {
        use windows_sys::Win32::System::Power::{GetSystemPowerStatus, SYSTEM_POWER_STATUS};

        fn sdk() -> (u8, u8, u8) {
            let mut status = SYSTEM_POWER_STATUS::default();
            // SAFETY: live, initialized, correctly aligned SDK out parameter.
            assert_ne!(unsafe { GetSystemPowerStatus(&mut status) }, 0);
            (
                status.BatteryFlag,
                status.BatteryLifePercent,
                status.ACLineStatus,
            )
        }

        let cap = crate::WindowsBackend
            .capabilities()
            .into_iter()
            .find(|cap| cap.field == "batteries")
            .expect("battery capability");
        assert_eq!(cap.level, CapabilityLevel::Partial);
        let hardware = HardwareBuilder::new(Options {
            timeout: std::time::Duration::from_secs(5),
            ..Options::default()
        })
        .with_backend(100, crate::WindowsBackend)
        .build()
        .expect("native collector");
        for _ in 0..3 {
            let before = sdk();
            let snapshot = hardware.collect().expect("production collect");
            let after = sdk();
            if before != after {
                continue;
            }
            let observed = &snapshot.dynamic.batteries;
            assert_eq!(observed.source(), Source::Win32);
            match before.0 {
                255 => assert_eq!(observed.reason(), Some(ReasonCode::TemporarilyUnavailable)),
                flag if flag & 128 != 0 => {
                    assert_eq!(observed.availability(), Availability::NotApplicable)
                }
                _ => {
                    let batteries = observed.value().expect("available summary");
                    assert_eq!(batteries.len(), 1);
                    let battery = &batteries[0];
                    if before.1 <= 100 {
                        assert_eq!(battery.charge_percent.value(), Some(&f64::from(before.1)));
                    } else {
                        assert!(battery.charge_percent.value().is_none());
                    }
                    if before.2 <= 1 {
                        assert_eq!(battery.on_ac_power.value(), Some(&(before.2 == 1)));
                    } else {
                        assert!(battery.on_ac_power.value().is_none());
                    }
                }
            }
            eprintln!(
                "DSC_WINDOWS_BATTERY_SDK flag={} percent={} ac={} matched=true",
                before.0, before.1, before.2
            );
            hardware.shutdown().expect("collector released");
            return;
        }
        panic!("system power status changed during all three SDK comparisons");
    }
}
