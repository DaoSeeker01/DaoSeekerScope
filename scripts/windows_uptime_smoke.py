"""Bracket persistent Windows uptime reads with an independent C SDK counter.

No pressure, sleep/hibernate, reboot or API interception. Equal seconds are valid.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import queue
import subprocess
import threading
import time
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LIMIT = 1024 * 1024


def require(condition: bool) -> None:
    if not condition:
        raise ValueError("uptime_probe: invalid_observation")


def check_field(field: dict[str, Any], before: int, after: int) -> None:
    require(type(before) is int and type(after) is int)
    require(0 <= before <= after <= 2**64 - 1)
    require(type(field["value"]) is int)
    require(before // 1000 <= field["value"] <= after // 1000)
    require(field["availability"] == "available" and field["source"] == "win32")
    require(field["reason"] is None)
    require(type(field["observed_at"]) is int and field["observed_at"] >= 0)


def check_sdk(sample: dict[str, Any], calls: int) -> int:
    require(type(sample["milliseconds"]) is int)
    require(0 <= sample["milliseconds"] <= 2**64 - 1)
    require(type(sample["calls"]) is int and sample["calls"] == calls)
    return int(sample["milliseconds"])


def read_json(process: subprocess.Popen[bytes]) -> dict[str, Any]:
    stream = process.stdout
    require(stream is not None)
    result: queue.Queue[bytes | None] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            result.put(stream.readline(LIMIT + 1) if stream else None)
        except (OSError, ValueError):
            result.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    line = result.get(timeout=5)
    reader.join(timeout=1)
    require(line is not None and 0 < len(line) <= LIMIT and line.endswith(b"\n"))
    value = json.loads(line)  # type: ignore[arg-type]
    require(isinstance(value, dict))
    return value


def send(process: subprocess.Popen[bytes], command: bytes) -> None:
    if process.stdin is None:
        raise ValueError("uptime_probe: missing_pipe")
    process.stdin.write(command)
    process.stdin.flush()


def collect(report: dict[str, Any]) -> None:
    require(platform.system() == "Windows")
    report["git_revision"] = (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, timeout=5, stderr=subprocess.DEVNULL
        )
        .decode()
        .strip()
    )
    report["git_dirty"] = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            timeout=5,
            stderr=subprocess.DEVNULL,
        ).strip()
    )
    paths = {
        "sdk": ROOT / "target/uptime-probe.exe",
        "rust": ROOT / "target/debug/examples/dynamic_probe.exe",
    }
    report["artifact_sha256"] = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in paths.items()
    }
    processes: list[subprocess.Popen[bytes]] = []
    observations: list[dict[str, Any]] = []
    report["observations"] = observations
    try:

        def start(path: Path) -> subprocess.Popen[bytes]:
            process = subprocess.Popen(
                [str(path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=ROOT,
            )
            processes.append(process)
            return process

        sdk = start(paths["sdk"])
        calls = 1
        before = check_sdk(read_json(sdk), calls)
        rust = start(paths["rust"])
        static = None
        last_at = -1
        last_seconds = -1
        for index, command in enumerate(
            (None, b"refresh\n", b"refresh\n", b"refresh\n", b"rebuild\n")
        ):
            if command is not None:
                if command == b"refresh\n":
                    time.sleep(1.1)
                send(sdk, b"sample\n")
                calls += 1
                before = check_sdk(read_json(sdk), calls)
                send(rust, command)
            snapshot = read_json(rust)
            send(sdk, b"sample\n")
            calls += 1
            after = check_sdk(read_json(sdk), calls)
            require(snapshot["schema_version"] == 1)
            require(
                any(
                    c["field"] == "runtime.uptime_seconds"
                    and c["source"] == "win32"
                    and c["level"] == "partial"
                    for c in snapshot["capabilities"]
                )
            )
            field = snapshot["dynamic"]["runtime"]["uptime_seconds"]
            check_field(field, before, after)
            require(field["observed_at"] >= last_at)
            if command == b"refresh\n":
                require(snapshot["static_info"] == static)
                require(field["observed_at"] > last_at)
                require(field["value"] > last_seconds)
            if index == 0:
                static = snapshot["static_info"]
            observations.append(
                {
                    "operation": "collect"
                    if command is None
                    else command.decode().strip(),
                    "uptime": field,
                    "sdk_before_ms": before,
                    "sdk_after_ms": after,
                }
            )
            last_at, last_seconds = field["observed_at"], field["value"]
        for process in processes:
            send(process, b"quit\n")
        for process in processes:
            require(process.wait(timeout=5) == 0)
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()


def run(output: Path) -> int:
    report: dict[str, Any] = {
        "status": "failed",
        "platform": platform.system(),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "limitations": [
            "no sleep, hibernation, reboot, fast-startup or checked-kernel experiment",
            "GetTickCount64 has no failure sentinel; no fabricated API error test",
            "SDK brackets validate tick domain, not exact boot time or wall clock",
            "cooperative cancellation cannot interrupt a blocked native API",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    code = 1
    try:
        collect(report)
        report["status"] = "passed"
        code = 0
    except KeyboardInterrupt:
        report["error"] = "interrupted"
        code = 130
    except Exception:
        report["error"] = "validation_failed"
    finally:
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Windows uptime SDK and refresh: {report['status']}")
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/windows-uptime-evidence.json"
    )
    return run(parser.parse_args().output)


if __name__ == "__main__":
    raise SystemExit(main())
