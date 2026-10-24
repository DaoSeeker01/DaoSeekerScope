"""Native group SDK plus persistent public facade regression.

On a single-group machine the facade retains its fast path. The forced Rust
helper is validated separately by the native unit test, not fabricated hardware.
"""

from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time
from typing import Any
from windows_cpu_smoke import check_field, read_json, send

ROOT = Path(__file__).resolve().parent.parent


def require(condition: bool) -> None:
    if not condition:
        raise ValueError("cpu_groups_probe: invalid_observation")


def check_sdk(sample: dict[str, Any], calls: int) -> None:
    require(
        sample["status"] == "passed" and sample["caller_affinity_unchanged"] is True
    )
    for key in (
        "calls",
        "groups",
        "processors",
        "group_info_size",
        "group_info_offset",
    ):
        require(type(sample[key]) is int)
    require(sample["calls"] == calls and 1 <= sample["groups"] <= 16)
    require(sample["group_info_size"] == 48 and sample["group_info_offset"] == 32)
    require(
        isinstance(sample["samples"], list)
        and len(sample["samples"]) == sample["groups"]
    )
    processors = 0
    for group in sample["samples"]:
        for key in ("processors", "mask", "idle", "kernel", "user"):
            require(type(group[key]) is int)
        require(1 <= group["processors"] <= 64)
        require(0 < group["mask"] <= 2**64 - 1)
        require(group["mask"].bit_count() == group["processors"])
        processors += group["processors"]
        require(0 <= group["idle"] <= group["kernel"] <= 2**64 - 1)
        require(0 <= group["user"] <= 2**64 - 1)
    require(processors == sample["processors"] and processors <= 1024)


def sdk_usage(previous: dict[str, Any], current: dict[str, Any]) -> float:
    require(
        previous["groups"] == current["groups"]
        and previous["processors"] == current["processors"]
    )
    idle = kernel = user = 0
    for first, last in zip(previous["samples"], current["samples"]):
        require(first["processors"] == last["processors"])
        require(first["mask"] == last["mask"])
        di = last["idle"] - first["idle"]
        dk = last["kernel"] - first["kernel"]
        du = last["user"] - first["user"]
        require(0 <= di <= dk and du >= 0)
        idle += di
        kernel += dk
        user += du
    require(kernel + user > 0)
    return 100 * (kernel + user - idle) / (kernel + user)


def collect(report: dict[str, Any]) -> None:
    require(platform.system() == "Windows")
    paths = (
        ROOT / "target/debug/examples/dynamic_probe.exe",
        ROOT / "target/cpu-groups-probe.exe",
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
        check_sdk(previous, 1)
        report["actual_groups"] = previous["groups"]
        report["real_multi_group_device"] = previous["groups"] > 1
        report["facade_group_path_exercised"] = previous["groups"] > 1
        require(initial["schema_version"] == 1)
        static = initial["static_info"]["system"]["cpu"]
        check_field(initial["dynamic"]["cpu_usage_percent"], warmup=True)
        report["initial"] = {
            "cpu": initial["dynamic"]["cpu_usage_percent"],
            "sdk": previous,
        }
        observations: list[dict[str, Any]] = []
        report["observations"] = observations
        last_at = -1
        for index in range(3):
            time.sleep(0.35)
            send(sdk, b"sample\n")
            current = read_json(sdk)
            check_sdk(current, index + 2)
            send(rust, b"refresh\n")
            snapshot = read_json(rust)
            require(snapshot["schema_version"] == 1)
            require(snapshot["static_info"]["system"]["cpu"] == static)
            field = snapshot["dynamic"]["cpu_usage_percent"]
            check_field(field)
            require(field["observed_at"] > last_at)
            last_at = field["observed_at"]
            observations.append(
                {
                    "cpu": field,
                    "sdk": current,
                    "sdk_usage_percent": sdk_usage(previous, current),
                }
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
            "Actual groups recorded; single-group success is not real cross-group evidence",
            "real multi-group switching, API errors, hotplug and Job constraints need dedicated machines",
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
    print(f"Windows CPU group SDK and facade: {report['status']}")
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/windows-cpu-groups-evidence.json"
    )
    return run(parser.parse_args().output)


if __name__ == "__main__":
    raise SystemExit(main())
