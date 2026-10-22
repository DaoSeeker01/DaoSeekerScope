//! Windows tick time includes sleep/hibernation; successful zero is valid.
use daoseeker_scope_core::*;

fn read_with(
    read: impl FnOnce() -> u64,
    mut check: impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<u64>, ScopeError> {
    check()?;
    let milliseconds = read();
    check()?;
    Ok(Observed::available(
        milliseconds / 1000,
        Source::Win32,
        Timestamp::now()?,
    ))
}

#[cfg(target_os = "windows")]
pub(crate) fn collect(context: &CollectContext) -> Result<Observed<u64>, ScopeError> {
    read_with(
        || {
            // SAFETY: GetTickCount64 takes no pointers and has no failure sentinel.
            unsafe { windows_sys::Win32::System::SystemInformation::GetTickCount64() }
        },
        || context.check(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;

    #[test]
    fn integer_seconds_preserve_zero_and_u64_domain() {
        for (raw, expected) in [
            (0, 0),
            (999, 0),
            (1000, 1),
            (1999, 1),
            (u64::from(u32::MAX) + 1, 4_294_967),
            (u64::MAX, u64::MAX / 1000),
        ] {
            let field = read_with(|| raw, || Ok(())).expect("read");
            assert_eq!(field.value(), Some(&expected));
            assert_eq!(field.availability(), Availability::Available);
            assert_eq!(field.source(), Source::Win32);
            assert!(field.observed_at().is_some());
            assert_eq!(field.reason(), None);
        }
    }

    #[test]
    fn every_read_calls_api_once_without_a_baseline_or_old_value() {
        let calls = Cell::new(0);
        // Equal samples and a new counter domain are passed through, not guessed errors.
        for raw in [1000, 1000, 3000, 0] {
            let field = read_with(
                || {
                    calls.set(calls.get() + 1);
                    raw
                },
                || Ok(()),
            )
            .expect("read");
            assert_eq!(field.value(), Some(&(raw / 1000)));
        }
        assert_eq!(calls.get(), 4);
    }

    #[test]
    fn cancellation_before_read_skips_api_and_after_read_rejects_sample() {
        for error in [ErrorCode::Cancelled, ErrorCode::Timeout] {
            for reject_at in [1, 2] {
                let calls = Cell::new(0);
                let checks = Cell::new(0);
                let result = read_with(
                    || {
                        calls.set(calls.get() + 1);
                        1000
                    },
                    || {
                        checks.set(checks.get() + 1);
                        if checks.get() == reject_at {
                            Err(ScopeError::new(error))
                        } else {
                            Ok(())
                        }
                    },
                );
                assert_eq!(result.expect_err("cancelled").code, error);
                assert_eq!(calls.get(), reject_at - 1);
                assert_eq!(checks.get(), reject_at);
            }
        }
    }
}
