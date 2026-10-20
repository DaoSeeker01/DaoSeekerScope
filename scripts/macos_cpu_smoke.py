"""macOS CPU fresh-read evidence; real API faults remain untested.

Two bounded native children, no stress load, identifiers, or API interception.
Independent intervals are checked separately, never compared for equal usage.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
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
        raise ValueError("cpu_probe: invalid_observation")


def check_field(field: dict[str, Any], warmup: bool = False) -> None:
    require(field["source"] == "apple_api")
    if warmup:
        require(field["availability"] == "unavailable")
        require(field["reason"] == "temporarily_unavailable")
        require(field["value"] is None and field["observed_at"] is None)
    else:
        value = field["value"]
        require(type(value) in (int, float) and math.isfinite(value))
        require(0 <= value <= 100)
        require(field["availability"] == "available" and field["reason"] is None)
        require(type(field["observed_at"]) is int and field["observed_at"] >= 0)


def check_count(field: dict[str, Any]) -> int:
    require(field["availability"] == "available" and field["source"] == "apple_api")
    require(field["reason"] is None and type(field["observed_at"]) is int)
    require(field["observed_at"] >= 0)
    value = field["value"]
    require(type(value) is int and 1 <= value <= 1024)
    return value


def check_sdk(sample: dict[str, Any], calls: int) -> None:
    require(sample["status"] == "passed")
    for key in ("processors", "calls", "word_count", "word_size", "pointer_size"):
        require(type(sample[key]) is int)
    require(1 <= sample["processors"] <= 1024)
    require(
        sample["calls"] == calls and sample["word_count"] == sample["processors"] * 4
    )
    require(sample["word_size"] == 4 and sample["pointer_size"] == 8)
    require(sample["released_array"] is True and sample["released_host"] is True)
    require(
        type(sample["ticks"]) is list and len(sample["ticks"]) == sample["processors"]
    )
    for row in sample["ticks"]:
        require(type(row) is list and len(row) == 4)
        require(all(type(value) is int and 0 <= value <= 2**32 - 1 for value in row))


def sdk_usage(previous: dict[str, Any], current: dict[str, Any]) -> float:
    require(previous["processors"] == current["processors"])
    delta = [0, 0, 0, 0]
    for old, new in zip(previous["ticks"], current["ticks"], strict=True):
        for index in range(4):
            require(new[index] >= old[index])
            delta[index] += new[index] - old[index]
    total = sum(delta)
    require(total > 0)
    return 100 * (total - delta[2]) / total


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
        raise ValueError("cpu_probe: missing_pipe")
    process.stdin.write(command)
    process.stdin.flush()


def collect(report: dict[str, Any]) -> None:
    require(platform.system() == "Darwin")
    paths = (
        ROOT / "target/debug/examples/dynamic_probe",
        ROOT / "target/macos-cpu-probe",
    )
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
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in zip(("rust_probe", "c_sdk_probe"), paths)
    }
    processes: list[subprocess.Popen[bytes]] = []
    try:
        for path in paths:
            processes.append(
                subprocess.Popen(
                    [str(path)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    cwd=ROOT,
                )
            )
        rust, sdk = processes
        initial = read_json(rust)
        previous = read_json(sdk)
        static = initial["static_info"]["system"]["cpu"]["logical_count"]
        report["initial"] = {
            "cpu": initial["dynamic"]["cpu_usage_percent"],
            "logical_count": static,
            "sdk": previous,
        }
        check_sdk(previous, 1)
        require(initial["schema_version"] == 1)
        require(check_count(static) == previous["processors"])
        check_field(initial["dynamic"]["cpu_usage_percent"], warmup=True)
        observations: list[dict[str, Any]] = []
        report["observations"] = observations
        last_at = -1
        for index in range(3):
            time.sleep(0.35)
            send(sdk, b"sample\n")
            current = read_json(sdk)
            send(rust, b"refresh\n")
            snapshot = read_json(rust)
            require(snapshot["schema_version"] == 1)
            require(snapshot["static_info"]["system"]["cpu"]["logical_count"] == static)
            field = snapshot["dynamic"]["cpu_usage_percent"]
            phase: dict[str, Any] = {"status": "running", "cpu": field, "sdk": current}
            observations.append(phase)
            check_sdk(current, index + 2)
            require(current["processors"] == check_count(static))
            check_field(field)
            require(field["observed_at"] > last_at)
            last_at = field["observed_at"]
            phase.update(
                status="passed", sdk_usage_percent=sdk_usage(previous, current)
            )
            previous = current
        send(rust, b"rebuild\n")
        rebuilt = read_json(rust)["dynamic"]["cpu_usage_percent"]
        check_field(rebuilt, warmup=True)
        report["rebuilt"] = rebuilt
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
            "at most 1024 Mach processor entries; physical Intel/Apple Silicon and hotplug untested",
            "real API errors untested; injected failures tested separately",
            "SDK and Rust intervals differ; no equality or causal load assertion",
            "cooperative checks cannot interrupt a blocked native API",
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
    print(f"macOS CPU SDK and refresh: {report['status']}")
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/macos-cpu-evidence.json"
    )
    return run(parser.parse_args().output)


if __name__ == "__main__":
    raise SystemExit(main())
