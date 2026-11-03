//! Optional CLI process boundary. Only this executable is launched; no shell.
use daoseeker_scope::{MAX_JSON_BYTES, Options, Snapshot, from_json};
use daoseeker_scope_cli::Command;
use std::{
    fmt,
    io::{self, Read},
    process::{Child, ExitStatus, Stdio},
    sync::mpsc,
    time::{Duration, Instant},
};

pub(super) const WORKER: &str = "--internal-json-worker";
const CLEANUP: Duration = Duration::from_secs(1);

#[derive(Debug, PartialEq, Eq)]
pub(super) enum Failure {
    Spawn,
    Read,
    Timeout,
    OutputLimit,
    ChildFailed,
    InvalidSnapshot,
    StopUnconfirmed(u32),
}
impl fmt::Display for Failure {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Spawn => f.write_str("could not start isolated collector"),
            Self::Read => f.write_str("could not read isolated result; child exited"),
            Self::Timeout => f.write_str("isolated collection timed out; child exited"),
            Self::OutputLimit => f.write_str("isolated result exceeded 1 MiB; child exited"),
            Self::ChildFailed => f.write_str("isolated collection failed; child exited"),
            Self::InvalidSnapshot => f.write_str("isolated collector returned invalid JSON"),
            Self::StopUnconfirmed(pid) => write!(
                f,
                "could not confirm collector {pid} termination; check OS process state"
            ),
        }
    }
}

struct ManagedChild {
    child: Child,
    reaped: bool,
}
impl ManagedChild {
    fn status(&mut self) -> io::Result<Option<ExitStatus>> {
        let status = self.child.try_wait()?;
        self.reaped |= status.is_some();
        Ok(status)
    }
    fn stop(&mut self, reason: Failure) -> Failure {
        if self.reaped {
            return reason;
        }
        // Closing the liveness pipe also tells the worker to exit if its parent
        // loses the ability to terminate it through the process handle.
        drop(self.child.stdin.take());
        let _ = self.child.kill();
        let deadline = Instant::now() + CLEANUP;
        loop {
            match self.status() {
                Ok(Some(_)) => return reason,
                Ok(None) if Instant::now() < deadline => {
                    std::thread::sleep(Duration::from_millis(2))
                }
                _ => return Failure::StopUnconfirmed(self.child.id()),
            }
        }
    }
}
impl Drop for ManagedChild {
    fn drop(&mut self) {
        if !self.reaped {
            // Fallback for unwinding only. Normal exits use bounded stop/status.
            drop(self.child.stdin.take());
            let _ = self.child.kill();
            let _ = self.child.try_wait();
        }
    }
}

fn capture(child: Child, deadline: Instant) -> Result<Snapshot, Failure> {
    let mut child = ManagedChild {
        child,
        reaped: false,
    };
    let Some(stdout) = child.child.stdout.take() else {
        return Err(child.stop(Failure::Read));
    };
    let (send, receive) = mpsc::sync_channel(1);
    if std::thread::Builder::new()
        .name("dscope-json-reader".into())
        .spawn(move || {
            let mut bytes = Vec::with_capacity(MAX_JSON_BYTES + 1);
            let result = stdout
                .take((MAX_JSON_BYTES + 1) as u64)
                .read_to_end(&mut bytes);
            let value = match result {
                Err(_) => Err(Failure::Read),
                Ok(_) if bytes.len() > MAX_JSON_BYTES => Err(Failure::OutputLimit),
                Ok(_) => Ok(bytes),
            };
            let _ = send.send(value);
        })
        .is_err()
    {
        return Err(child.stop(Failure::Spawn));
    }
    let mut bytes = None;
    loop {
        if Instant::now() >= deadline {
            return Err(child.stop(Failure::Timeout));
        }
        if bytes.is_none() {
            match receive.try_recv() {
                Ok(Ok(value)) => bytes = Some(value),
                Ok(Err(error)) => return Err(child.stop(error)),
                Err(mpsc::TryRecvError::Disconnected) => return Err(child.stop(Failure::Read)),
                Err(mpsc::TryRecvError::Empty) => {}
            }
        }
        match child.status() {
            Ok(Some(status)) if !status.success() => return Err(Failure::ChildFailed),
            Ok(Some(_)) if bytes.is_some() => {
                let snapshot = from_json(bytes.as_deref().expect("result present"));
                if Instant::now() >= deadline {
                    return Err(Failure::Timeout);
                }
                return snapshot.map_err(|_| Failure::InvalidSnapshot);
            }
            Err(_) => return Err(child.stop(Failure::Read)),
            _ => {}
        }
        std::thread::sleep(
            deadline
                .saturating_duration_since(Instant::now())
                .min(Duration::from_millis(2)),
        );
    }
}

pub(super) fn collect(command: Command, options: &Options) -> Result<Snapshot, Failure> {
    let deadline = Instant::now() + options.timeout;
    let name = match command {
        Command::Cpu => "cpu",
        Command::Memory => "memory",
        Command::Gpu => "gpu",
        Command::Disk => "disk",
        Command::Display => "display",
        Command::Network => "network",
        Command::Battery => "battery",
        Command::Sensors => "sensors",
        Command::System => "system",
        Command::Capabilities => "capabilities",
    };
    let executable = std::env::current_exe().map_err(|_| Failure::Spawn)?;
    let mut child = std::process::Command::new(executable);
    child.args([
        WORKER,
        name,
        "--json",
        &format!("--timeout-ms={}", options.timeout.as_millis()),
    ]);
    if options.privacy.include_sensitive {
        child.arg("--include-sensitive");
    }
    if options.privacy.caller_authorized {
        child.arg("--authorized");
    }
    child
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        child.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }
    capture(child.spawn().map_err(|_| Failure::Spawn)?, deadline)
}

pub(super) fn watch_parent() -> Result<(), Failure> {
    std::thread::Builder::new()
        .name("dscope-parent-watch".into())
        .spawn(|| {
            let mut byte = [0u8; 1];
            loop {
                match io::stdin().lock().read(&mut byte) {
                    Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                    // The parent never sends data. EOF, unexpected data or failure
                    // closes this worker process, including its collection threads.
                    _ => std::process::exit(3),
                }
            }
        })
        .map(|_| ())
        .map_err(|_| Failure::Spawn)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::Write,
        path::PathBuf,
        sync::atomic::{AtomicU64, Ordering},
    };
    static NEXT: AtomicU64 = AtomicU64::new(0);
    struct Probe {
        directory: PathBuf,
        child: Option<Child>,
    }
    impl Probe {
        fn spawn(mode: &str) -> Self {
            let directory = std::env::temp_dir().join(format!(
                "dscope-process-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            std::fs::create_dir(&directory).expect("own probe directory");
            let mut command =
                std::process::Command::new(std::env::current_exe().expect("test executable"));
            command
                .args([
                    "--exact",
                    "isolation::tests::child_process_fixture",
                    "--ignored",
                    "--nocapture",
                ])
                .env("DSCOPE_PROCESS_TEST_CHILD", mode)
                .env("DSCOPE_PROCESS_READY", directory.join("ready"))
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::null());
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                command.creation_flags(0x08000000);
            }
            let mut probe = Self {
                directory,
                child: Some(command.spawn().expect("test child")),
            };
            let deadline = Instant::now() + Duration::from_secs(5);
            while !probe.directory.join("ready").exists() && Instant::now() < deadline {
                if probe
                    .child
                    .as_mut()
                    .expect("child")
                    .try_wait()
                    .expect("child status")
                    .is_some()
                {
                    assert!(
                        probe.directory.join("ready").exists(),
                        "fixture exited before ready"
                    );
                    break;
                }
                std::thread::sleep(Duration::from_millis(2));
            }
            assert!(probe.directory.join("ready").exists(), "fixture not ready");
            probe
        }
        fn take(&mut self) -> Child {
            self.child.take().expect("owned child")
        }
    }
    impl Drop for Probe {
        fn drop(&mut self) {
            if let Some(child) = self.child.take() {
                let _ = ManagedChild {
                    child,
                    reaped: false,
                }
                .stop(Failure::Timeout);
            }
            let _ = std::fs::remove_dir_all(&self.directory);
        }
    }
    #[test]
    #[ignore = "only spawned by process supervision tests"]
    fn child_process_fixture() {
        let Ok(mode) = std::env::var("DSCOPE_PROCESS_TEST_CHILD") else {
            return;
        };
        if mode == "guardian" {
            watch_parent().expect("watch parent");
        }
        std::fs::write(
            std::env::var_os("DSCOPE_PROCESS_READY").expect("ready file"),
            b"ready",
        )
        .expect("ready");
        match mode.as_str() {
            "fail" => std::process::exit(7),
            "invalid" => {
                print!("not a snapshot");
                return;
            }
            "overflow" => {
                let _ = io::stdout()
                    .lock()
                    .write_all(&vec![b'x'; MAX_JSON_BYTES + 1]);
            }
            _ => {}
        }
        loop {
            std::thread::park_timeout(Duration::from_secs(1));
        }
    }
    #[test]
    fn hung_child_is_terminated_and_reaped_on_deadline() {
        let mut probe = Probe::spawn("hang");
        let started = Instant::now();
        assert_eq!(
            capture(probe.take(), started + Duration::from_millis(20)).expect_err("deadline"),
            Failure::Timeout
        );
        assert!(started.elapsed() < Duration::from_secs(3));
    }
    #[test]
    fn oversized_child_output_is_stopped_and_not_returned() {
        let mut probe = Probe::spawn("overflow");
        assert_eq!(
            capture(probe.take(), Instant::now() + Duration::from_secs(3))
                .expect_err("output limit"),
            Failure::OutputLimit
        );
    }
    #[test]
    fn failed_or_invalid_children_never_become_snapshots() {
        for (mode, expected) in [
            ("fail", Failure::ChildFailed),
            ("invalid", Failure::InvalidSnapshot),
        ] {
            let mut probe = Probe::spawn(mode);
            assert_eq!(
                capture(probe.take(), Instant::now() + Duration::from_secs(3))
                    .expect_err("failed child"),
                expected
            );
        }
    }
    #[test]
    fn closing_parent_pipe_stops_worker_without_a_kill_request() {
        let mut probe = Probe::spawn("guardian");
        let mut child = ManagedChild {
            child: probe.take(),
            reaped: false,
        };
        drop(child.child.stdin.take());
        let deadline = Instant::now() + Duration::from_secs(3);
        loop {
            if let Some(status) = child.status().expect("guardian status") {
                assert_eq!(status.code(), Some(3));
                break;
            }
            if Instant::now() >= deadline {
                let _ = child.stop(Failure::Timeout);
                panic!("guardian did not exit");
            }
            std::thread::sleep(Duration::from_millis(2));
        }
    }
}
