"""macOS public memory SDK/refresh evidence; OS statistics may be cached.

No stress load, identifiers, private API, cross-process equality or delta claim.
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
        raise ValueError("memory_probe: invalid_observation")


def observed(field: dict[str, Any], source: str, positive: bool = False) -> int:
    value = field["value"]
    require(type(value) is int and (1 if positive else 0) <= value <= 2**64 - 1)
    require(field["availability"] == "available" and field["source"] == source)
    require(field["reason"] is None and type(field["observed_at"]) is int)
    require(0 <= field["observed_at"] <= 2**64 - 1)
    return value


def check_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    require(type(snapshot["schema_version"]) is int and snapshot["schema_version"] == 1)
    total = snapshot["static_info"]["system"]["memory"]["total_usable_bytes"]
    available = snapshot["dynamic"]["memory_available_bytes"]
    require(observed(available, "apple_api") <= observed(total, "sysctl", True))
    return {"total": total, "available": available}


def check_sdk(sample: dict[str, Any], calls: int) -> None:
    require(sample["status"] == "passed" and sample["released_host"] is True)
    for key in (
        "calls",
        "total",
        "available",
        "page_size",
        "active",
        "inactive",
        "free",
        "speculative",
        "requested_words",
        "returned_words",
        "sdk_struct_size",
        "rev1_prefix_bytes",
    ):
        require(type(sample[key]) is int)
    require(sample["calls"] == calls)
    require(sample["requested_words"] == sample["returned_words"] == 38)
    require(sample["rev1_prefix_bytes"] == 152 and sample["sdk_struct_size"] >= 152)
    require(sample["sdk_struct_size"] % 8 == 0)
    require(0 < sample["total"] <= 2**64 - 1)
    size = sample["page_size"]
    require(0 < size <= 2**64 - 1 and size & (size - 1) == 0)
    require(
        all(
            0 <= sample[key] <= 2**32 - 1
            for key in ("active", "inactive", "free", "speculative")
        )
    )
    require(sample["speculative"] <= sample["free"])
    expected = (sample["active"] + sample["inactive"] + sample["free"]) * size
    require(0 <= sample["available"] == expected <= sample["total"])


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
        raise ValueError("memory_probe: missing_pipe")
    process.stdin.write(command)
    process.stdin.flush()


def collect(report: dict[str, Any]) -> None:
    require(platform.system() == "Darwin")
    paths = (
        ROOT / "target/debug/examples/dynamic_probe",
        ROOT / "target/macos-memory-probe",
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
        snapshot = read_json(rust)
        current = read_json(sdk)
        first = {
            "total": snapshot["static_info"]["system"]["memory"]["total_usable_bytes"],
            "available": snapshot["dynamic"]["memory_available_bytes"],
        }
        report["initial"] = {"rust": first, "sdk": current}
        check_snapshot(snapshot)
        check_sdk(current, 1)
        require(observed(first["total"], "sysctl", True) == current["total"])
        phases: list[dict[str, Any]] = []
        report["observations"] = phases
        last_at = first["available"]["observed_at"]
        for index in range(3):
            time.sleep(0.35)
            send(sdk, b"sample\n")
            current = read_json(sdk)
            send(rust, b"refresh\n")
            snapshot = read_json(rust)
            # Preserve filtered fields before validation, including failed phases.
            memory = {
                "total": snapshot["static_info"]["system"]["memory"][
                    "total_usable_bytes"
                ],
                "available": snapshot["dynamic"]["memory_available_bytes"],
            }
            phase: dict[str, Any] = {
                "status": "running",
                "rust": memory,
                "sdk": current,
            }
            phases.append(phase)
            check_snapshot(snapshot)
            check_sdk(current, index + 2)
            require(memory["total"] == first["total"])
            require(observed(memory["total"], "sysctl", True) == current["total"])
            require(memory["available"]["observed_at"] > last_at)
            last_at = memory["available"]["observed_at"]
            phase["status"] = "passed"
        send(rust, b"rebuild\n")
        rebuilt = read_json(rust)
        report["rebuilt"] = check_snapshot(rebuilt)
        require(report["rebuilt"]["total"]["value"] == first["total"]["value"])
        report["static_total_cached"] = True
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
            "OS VM counters can be rate-limited/cached; no maximum age or fresh-kernel-counter claim",
            "non-compressed active+inactive+free estimate; not immediately allocatable or per-process limit",
            "SDK and Rust calls differ in time; no equality, fixed delta or pressure claim",
            "real API/cleanup errors, physical Mac and Intel native remain untested",
            "cooperative checks cannot interrupt blocked OS calls; no long native leak proof",
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
    print(f"macOS memory SDK and refresh: {report['status']}")
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/macos-memory-evidence.json"
    )
    return run(parser.parse_args().output)


if __name__ == "__main__":
    raise SystemExit(main())
