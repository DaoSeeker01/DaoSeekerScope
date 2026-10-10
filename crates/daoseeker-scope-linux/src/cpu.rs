//! Fresh aggregate procfs samples; errors never reuse a previous percentage.
use daoseeker_scope_core::{Observed, ReasonCode, Source, Timestamp};
use std::io::{self, BufRead, BufReader, Read};
use std::time::{Duration, Instant};

const MAX_LINE: usize = 4096;
const SAMPLE_INTERVAL: Duration = Duration::from_millis(300);

#[derive(Clone, Copy)]
struct Counters([u64; 8]);

fn parse(line: &[u8]) -> Result<Counters, ReasonCode> {
    if line.len() > MAX_LINE {
        return Err(ReasonCode::InvalidData);
    }
    let mut fields = std::str::from_utf8(line)
        .map_err(|_| ReasonCode::InvalidData)?
        .split_ascii_whitespace();
    if fields.next() != Some("cpu") {
        return Err(ReasonCode::InvalidData);
    }
    let mut values = [0u64; 8];
    let mut count = 0;
    for field in fields {
        if count == 10 || !field.bytes().all(|byte| byte.is_ascii_digit()) {
            return Err(ReasonCode::InvalidData);
        }
        let value = field.parse::<u64>().map_err(|_| ReasonCode::InvalidData)?;
        if count < values.len() {
            values[count] = value;
        }
        // guest and guest_nice are already included in user and nice.
        count += 1;
    }
    if count < 4
        || values
            .iter()
            .try_fold(0u64, |sum, value| sum.checked_add(*value))
            .is_none()
    {
        return Err(ReasonCode::InvalidData);
    }
    Ok(Counters(values))
}

fn read_line(input: impl Read) -> Result<Counters, ReadFailure> {
    let mut line = Vec::with_capacity(MAX_LINE + 1);
    BufReader::new(input.take((MAX_LINE + 1) as u64))
        .read_until(b'\n', &mut line)
        .map_err(|error| ReadFailure::Io(error.kind()))?;
    parse(&line).map_err(ReadFailure::Data)
}

enum ReadFailure {
    Io(io::ErrorKind),
    Data(ReasonCode),
}

#[derive(Default)]
pub(super) struct CpuSampler {
    baseline: Option<(Counters, Instant)>,
}

impl CpuSampler {
    pub(super) fn refresh(&mut self, at: Timestamp) -> Observed<f64> {
        let input = std::fs::File::open("/proc/stat")
            .map_err(|error| ReadFailure::Io(error.kind()))
            .and_then(read_line);
        self.observe(input, Instant::now(), at)
    }

    fn observe(
        &mut self,
        input: Result<Counters, ReadFailure>,
        now: Instant,
        at: Timestamp,
    ) -> Observed<f64> {
        let current = match input {
            Ok(current) => current,
            Err(error) => {
                self.baseline = None;
                return match error {
                    ReadFailure::Io(io::ErrorKind::PermissionDenied) => {
                        Observed::restricted(Source::Procfs, ReasonCode::PermissionDenied)
                    }
                    ReadFailure::Io(io::ErrorKind::NotFound) => {
                        Observed::unavailable(Source::Procfs, ReasonCode::NotPresent)
                    }
                    ReadFailure::Io(_) => {
                        Observed::unavailable(Source::Procfs, ReasonCode::Unknown)
                    }
                    ReadFailure::Data(reason) => Observed::unavailable(Source::Procfs, reason),
                };
            }
        };
        let Some((previous, previous_at)) = self.baseline else {
            self.baseline = Some((current, now));
            return Observed::unavailable(Source::Procfs, ReasonCode::TemporarilyUnavailable);
        };
        // A reset (including decreasing iowait) cannot yield a trustworthy delta.
        if current
            .0
            .iter()
            .zip(previous.0)
            .any(|(new, old)| *new < old)
        {
            self.baseline = Some((current, now));
            return Observed::unavailable(Source::Procfs, ReasonCode::InvalidData);
        }
        if now.duration_since(previous_at) < SAMPLE_INTERVAL {
            // Keep the old valid baseline; fast polling must not starve readiness.
            return Observed::unavailable(Source::Procfs, ReasonCode::TemporarilyUnavailable);
        }
        self.baseline = Some((current, now));
        let mut delta = [0; 8];
        for (index, value) in delta.iter_mut().enumerate() {
            *value = current.0[index] - previous.0[index];
        }
        // Both cumulative totals were checked, so the sum of deltas cannot overflow.
        let total: u64 = delta.iter().sum();
        if total == 0 {
            return Observed::unavailable(Source::Procfs, ReasonCode::TemporarilyUnavailable);
        }
        let idle = delta[3] + delta[4];
        Observed::available(
            100.0 * ((total - idle) as f64 / total as f64),
            Source::Procfs,
            at,
        )
    }
}

#[cfg(feature = "fuzzing")]
pub(super) fn fuzz_sequence(data: &[u8]) -> Vec<Observed<f64>> {
    let mut sampler = CpuSampler::default();
    let mut now = Instant::now();
    let mut observations = Vec::with_capacity(21);
    for (index, frame) in data[..data.len().min(8192)]
        .split(|byte| *byte == 0)
        .take(16)
        .enumerate()
    {
        let (control, text) = frame
            .split_first()
            .map_or((0, &[][..]), |(byte, text)| (*byte, text));
        now += Duration::from_millis(match control & 3 {
            0 => 0,
            1 => 50,
            2 => 300,
            _ => 1000,
        });
        let input = match (control >> 2) & 3 {
            0 => read_line(text),
            1 => Err(ReadFailure::Io(io::ErrorKind::PermissionDenied)),
            2 => Err(ReadFailure::Io(io::ErrorKind::NotFound)),
            _ => Err(ReadFailure::Io(io::ErrorKind::Other)),
        };
        observations.push(sampler.observe(input, now, Timestamp(index as u64 + 1)));
    }
    for (index, text) in [
        &b""[..],
        b"cpu 100 0 0 100\n",
        b"cpu 150 0 0 150\n",
        b"cpu 150 0 0 250\n",
        b"cpu 250 0 0 250\n",
    ]
    .into_iter()
    .enumerate()
    {
        now += SAMPLE_INTERVAL;
        observations.push(sampler.observe(read_line(text), now, Timestamp(index as u64 + 100)));
    }
    observations
}

#[cfg(test)]
mod tests {
    use super::*;
    use daoseeker_scope_core::Availability;

    fn counters(user: u64, idle: u64) -> Result<Counters, ReadFailure> {
        Ok(Counters([user, 0, 0, idle, 0, 0, 0, 0]))
    }

    #[test]
    fn sampling_requires_two_valid_samples_and_fast_polling_does_not_starve() {
        let start = Instant::now();
        let mut sampler = CpuSampler::default();
        assert_eq!(
            sampler
                .observe(counters(100, 100), start, Timestamp(1))
                .reason(),
            Some(ReasonCode::TemporarilyUnavailable)
        );
        for millis in [1, 50, 299] {
            assert!(
                sampler
                    .observe(
                        counters(125, 125),
                        start + Duration::from_millis(millis),
                        Timestamp(2)
                    )
                    .value()
                    .is_none()
            );
        }
        assert_eq!(
            sampler
                .observe(counters(150, 150), start + SAMPLE_INTERVAL, Timestamp(3))
                .value(),
            Some(&50.0)
        );
    }

    #[test]
    fn failures_clear_baseline_and_recovery_requires_a_new_pair() {
        for failure in [
            ReadFailure::Data(ReasonCode::InvalidData),
            ReadFailure::Io(io::ErrorKind::NotFound),
            ReadFailure::Io(io::ErrorKind::PermissionDenied),
            ReadFailure::Io(io::ErrorKind::Other),
        ] {
            let start = Instant::now();
            let mut sampler = CpuSampler::default();
            sampler.observe(counters(100, 100), start, Timestamp(1));
            assert_eq!(
                sampler
                    .observe(counters(150, 150), start + SAMPLE_INTERVAL, Timestamp(2))
                    .value(),
                Some(&50.0)
            );
            let failed = sampler.observe(Err(failure), start + SAMPLE_INTERVAL * 2, Timestamp(3));
            assert!(failed.value().is_none());
            assert!(failed.observed_at().is_none());
            assert_eq!(failed.source(), Source::Procfs);
            assert_eq!(
                sampler
                    .observe(
                        counters(200, 200),
                        start + SAMPLE_INTERVAL * 3,
                        Timestamp(4)
                    )
                    .reason(),
                Some(ReasonCode::TemporarilyUnavailable)
            );
            assert_eq!(
                sampler
                    .observe(
                        counters(250, 250),
                        start + SAMPLE_INTERVAL * 4,
                        Timestamp(5)
                    )
                    .value(),
                Some(&50.0)
            );
        }
    }

    #[test]
    fn permission_missing_and_bad_data_remain_distinct() {
        let mut sampler = CpuSampler::default();
        let at = Timestamp(1);
        let denied = sampler.observe(
            Err(ReadFailure::Io(io::ErrorKind::PermissionDenied)),
            Instant::now(),
            at,
        );
        assert_eq!(denied.availability(), Availability::Restricted);
        assert_eq!(denied.reason(), Some(ReasonCode::PermissionDenied));
        let missing = sampler.observe(
            Err(ReadFailure::Io(io::ErrorKind::NotFound)),
            Instant::now(),
            at,
        );
        assert_eq!(missing.reason(), Some(ReasonCode::NotPresent));
        assert_eq!(missing.availability(), Availability::Unavailable);
        assert_eq!(
            sampler
                .observe(read_line(&b""[..]), Instant::now(), at)
                .reason(),
            Some(ReasonCode::InvalidData)
        );
    }

    #[test]
    fn no_progress_is_not_zero_but_idle_only_is_a_real_zero() {
        let start = Instant::now();
        let mut sampler = CpuSampler::default();
        sampler.observe(counters(100, 100), start, Timestamp(1));
        assert_eq!(
            sampler
                .observe(counters(100, 100), start + SAMPLE_INTERVAL, Timestamp(2))
                .reason(),
            Some(ReasonCode::TemporarilyUnavailable)
        );
        assert_eq!(
            sampler
                .observe(
                    counters(100, 200),
                    start + SAMPLE_INTERVAL * 2,
                    Timestamp(3)
                )
                .value(),
            Some(&0.0)
        );
        assert_eq!(
            sampler
                .observe(
                    counters(200, 200),
                    start + SAMPLE_INTERVAL * 3,
                    Timestamp(4)
                )
                .value(),
            Some(&100.0)
        );
    }

    #[test]
    fn decreasing_counters_rebaseline_instead_of_wrapping_or_clamping() {
        let start = Instant::now();
        let mut sampler = CpuSampler::default();
        sampler.observe(counters(1000, 1000), start, Timestamp(1));
        assert_eq!(
            sampler
                .observe(counters(100, 100), start + SAMPLE_INTERVAL, Timestamp(2))
                .reason(),
            Some(ReasonCode::InvalidData)
        );
        assert_eq!(
            sampler
                .observe(
                    counters(150, 150),
                    start + SAMPLE_INTERVAL * 2,
                    Timestamp(3)
                )
                .value(),
            Some(&50.0)
        );
        let mut sample = Counters([150, 0, 0, 150, 10, 0, 0, 0]);
        sampler.observe(Ok(sample), start + SAMPLE_INTERVAL * 3, Timestamp(4));
        sample.0[4] = 9;
        assert_eq!(
            sampler
                .observe(Ok(sample), start + SAMPLE_INTERVAL * 4, Timestamp(5))
                .reason(),
            Some(ReasonCode::InvalidData)
        );
    }

    #[test]
    fn guest_is_not_double_counted_and_iowait_is_idle() {
        let parsed = parse(b"cpu 10 10 10 30 10 10 10 10 9 9\n").expect("valid");
        assert_eq!(parsed.0.iter().sum::<u64>(), 100);
        let mut sampler = CpuSampler::default();
        let start = Instant::now();
        sampler.observe(Ok(Counters([0; 8])), start, Timestamp(1));
        assert_eq!(
            sampler
                .observe(Ok(parsed), start + SAMPLE_INTERVAL, Timestamp(2))
                .value(),
            Some(&60.0)
        );
    }

    #[test]
    fn bounded_reader_ignores_other_cpu_lines_and_rejects_malformed_input() {
        let mut data = b"cpu 100 0 0 100\n".to_vec();
        data.extend(vec![b'x'; 100_000]);
        assert!(read_line(data.as_slice()).is_ok());
        for data in [
            b"".as_slice(),
            b"cpu0 1 2 3 4",
            b"cpu 1 2 3",
            b"cpu +1 2 3 4",
            b"cpu 1 -2 3 4",
            b"cpu 1.5 2 3 4",
            b"cpu 1 2 3 4 x",
            b"cpu 18446744073709551615 1 0 0",
            b"cpu 1 2 3 4 5 6 7 8 9 10 11",
            b"cpu \xff 1 2 3",
        ] {
            assert!(read_line(data).is_err());
        }
        assert!(read_line(vec![b'x'; 4097].as_slice()).is_err());
    }
}
