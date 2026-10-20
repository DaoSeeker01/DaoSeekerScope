"""Native Windows memory refresh experiment; synthetic failures live in Rust tests.

Run built dynamic_probe and independent C SDK probe. No OS hooks, identifiers,
admin access, or equality/causality assumption across volatile memory samples.
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
PRESSURE = 64 * 1024 * 1024


def require(condition: bool) -> None:
    if not condition:
        raise ValueError("memory_probe: invalid_observation")


def observed(field: dict[str, Any], positive: bool = False) -> int:
    value = field["value"]
    require(type(value) is int and (1 if positive else 0) <= value <= 2**64 - 1)
    require(field["availability"] == "available" and field["source"] == "win32")
    require(field["reason"] is None and type(field["observed_at"]) is int)
    require(0 <= field["observed_at"] <= 2**64 - 1)
    return value


def check_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    require(snapshot["schema_version"] == 1)
    total = snapshot["static_info"]["system"]["memory"]["total_usable_bytes"]
    available = snapshot["dynamic"]["memory_available_bytes"]
    require(observed(available) <= observed(total, positive=True))
    return {"total": total, "available": available}


def check_sdk(sample: dict[str, Any], calls: int, held: int) -> None:
    require(
        all(
            type(sample[key]) is int
            for key in ("status", "struct_size", "calls", "held_bytes")
        )
    )
    require(sample["status"] == 0 and sample["struct_size"] == 64)
    require(sample["calls"] == calls and sample["held_bytes"] == held)
    require(type(sample["total"]) is int and 0 < sample["total"] <= 2**64 - 1)
    require(
        type(sample["available"]) is int and 0 <= sample["available"] <= sample["total"]
    )


def read_json(process: subprocess.Popen[bytes]) -> dict[str, Any]:
    stream = process.stdout
    require(stream is not None)
    results: queue.Queue[bytes | None] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            results.put(stream.readline(LIMIT + 1) if stream else None)
        except (OSError, ValueError):
            results.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    line = results.get(timeout=5)
    reader.join(timeout=1)
    require(line is not None and 0 < len(line) <= LIMIT and line.endswith(b"\n"))
    result = json.loads(line)  # type: ignore[arg-type]
    require(isinstance(result, dict))
    return result


def send(process: subprocess.Popen[bytes], command: bytes) -> None:
    if process.stdin is None:
        raise ValueError("memory_probe: missing_pipe")
    process.stdin.write(command)
    process.stdin.flush()


def collect(report: dict[str, Any]) -> None:
    require(platform.system() == "Windows")
    rust = ROOT / "target/debug/examples/dynamic_probe.exe"
    sdk = ROOT / "target/memory-probe.exe"
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
    report["artifact_sha256"] = {
        "rust_probe": hashlib.sha256(rust.read_bytes()).hexdigest(),
        "c_sdk_probe": hashlib.sha256(sdk.read_bytes()).hexdigest(),
    }
    processes: list[subprocess.Popen[bytes]] = []
    try:
        for executable in (rust, sdk):
            processes.append(
                subprocess.Popen(
                    [str(executable)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    cwd=ROOT,
                )
            )
        rust_process, sdk_process = processes
        initial = check_snapshot(read_json(rust_process))
        last_time = initial["available"]["observed_at"]
        phases = report["phases"]
        for index, (name, command, held) in enumerate(
            [
                ("baseline", b"sample\n", 0),
                ("held", b"hold\n", PRESSURE),
                ("released", b"release\n", 0),
            ],
            1,
        ):
            send(sdk_process, command)
            sample = read_json(sdk_process)
            check_sdk(sample, index, held)
            time.sleep(0.02)
            send(rust_process, b"refresh\n")
            current = check_snapshot(read_json(rust_process))
            require(current["total"] == initial["total"])
            require(current["total"]["value"] == sample["total"])
            require(current["available"]["observed_at"] > last_time)
            last_time = current["available"]["observed_at"]
            phases[name] = {"rust": current, "sdk": sample, "status": "passed"}
        for process in processes:
            send(process, b"quit\n")
            require(process.wait(timeout=5) == 0)
        report["static_total_cached"] = True
        report["available_values_changed"] = (
            len({phase["rust"]["available"]["value"] for phase in phases.values()}) > 1
        )
        report["overall"] = "passed"
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if process.stdin:
                process.stdin.close()
            if process.stdout:
                process.stdout.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/windows-memory-evidence.json"
    )
    args = parser.parse_args()
    report: dict[str, Any] = {
        "report_version": 1,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "execution_platform": {
            "os": platform.system(),
            "architecture": platform.machine(),
        },
        "overall": "failed",
        "phases": {},
        "pressure_bytes": PRESSURE,
        "read_timeout_seconds": 5,
        "max_line_bytes": LIMIT,
        "limits": [
            "Sequential volatile SDK/Rust samples; no available-value equality or fixed pressure delta required",
            "Native success experiment only; injected failures are separate synthetic Rust tests",
            "Not physical DIMM, Job limit, peak-memory, or CPU freshness verification",
        ],
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        collect(report)
    except KeyboardInterrupt:
        report["overall"] = "interrupted"
        report["failure"] = "interrupted"
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        queue.Empty,
        subprocess.SubprocessError,
    ):
        report["overall"] = "failed"
        report["failure"] = "memory_probe_failed"
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Windows memory refresh: " + report["overall"])
    return (
        0
        if report["overall"] == "passed"
        else 130
        if report["overall"] == "interrupted"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
