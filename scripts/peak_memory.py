"""Measure release C ABI process high-water memory in three separate processes."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import tempfile
from typing import Any

import jsonschema

from native_smoke import check_snapshot

ROOT = Path(__file__).resolve().parent.parent
PRESSURE = 64 * 1024 * 1024
STAGES = {"cached": [0, 1, 100, 300], "fresh": [0, 1, 10, 30]}


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(f"peak_memory: {code}")


def run(arguments: list[str], timeout: int = 180) -> bytes:
    # Bound captured output and caller wait. Never copy raw child errors to evidence.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        result = subprocess.run(
            arguments, cwd=ROOT, stdout=stdout, stderr=stderr, timeout=timeout
        )
        require(result.returncode == 0, "child_failed")
        stdout.seek(0)
        output = stdout.read(2 * 1024 * 1024 + 1)
        require(len(output) <= 2 * 1024 * 1024, "output_limit")
        return output


def source_state() -> tuple[str, str]:
    return (
        run(["git", "rev-parse", "HEAD"], 10).decode().strip(),
        run(["git", "status", "--porcelain"], 10).decode().strip(),
    )


def validate(data: Any, mode: str, system: str) -> dict[str, Any]:
    require(isinstance(data, dict), "object")
    require(type(data.get("format")) is int and data["format"] == 1, "format")
    require(data.get("mode") == mode, "mode")
    metric, unit, multiplier = {
        "Windows": ("peak_working_set", "bytes", 1),
        "Linux": ("ru_maxrss", "kibibytes", 1024),
        "Darwin": ("ru_maxrss", "bytes", 1),
    }[system]
    require(data.get("metric") == metric and data.get("raw_unit") == unit, "metric")
    require(
        type(data.get("multiplier")) is int and data["multiplier"] == multiplier,
        "unit_multiplier",
    )
    require(
        type(data.get("pressure_bytes")) is int
        and data["pressure_bytes"] == (PRESSURE if mode == "calibrate" else 0),
        "pressure",
    )
    samples = data.get("samples")
    stages = [0, 0, 0] if mode == "calibrate" else STAGES[mode]
    require(isinstance(samples, list) and len(samples) == len(stages), "stages")
    previous_peak = 0
    for index, (sample, calls) in enumerate(zip(samples, stages, strict=True)):
        require(isinstance(sample, dict), "sample")
        for key in ("calls", "peak_raw", "peak_bytes", "elapsed_ns", "max_json_bytes"):
            require(type(sample.get(key)) is int, "counter_type")
        expected_phase = (
            ["baseline", "touched", "freed"][index]
            if mode == "calibrate"
            else ("baseline" if index == 0 else "collected")
        )
        require(sample.get("phase") == expected_phase, "phase")
        require(sample["calls"] == calls, "calls")
        raw, peak = sample["peak_raw"], sample["peak_bytes"]
        require(0 < raw <= (2**64 - 1) // multiplier, "raw_range")
        require(peak == raw * multiplier and peak >= previous_peak, "peak_counter")
        previous_peak = peak
        require(0 <= sample["elapsed_ns"] <= 600 * 10**9, "elapsed_range")
        require(0 <= sample["max_json_bytes"] <= 1024 * 1024, "json_range")
        if calls == 0:
            require(sample["elapsed_ns"] == sample["max_json_bytes"] == 0, "idle")
        else:
            require(sample["max_json_bytes"] > 0, "json_empty")
    if mode == "calibrate":
        growth = samples[1]["peak_bytes"] - samples[0]["peak_bytes"]
        # Tolerate baseline/OS noise, while rejecting a missing or extra 1024 factor.
        require(PRESSURE // 2 <= growth <= PRESSURE * 2, "calibration_growth")
    return data


def fingerprint(paths: list[Path]) -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def verify_unchanged(
    initial: tuple[str, str], binaries: list[Path], hashes: dict[str, str]
) -> None:
    require(fingerprint(binaries) == hashes, "binaries_changed")
    require(source_state() == initial, "source_changed")


def measure(report: dict[str, Any]) -> None:
    initial = source_state()
    require(not initial[1], "dirty_checkout")
    system = platform.system()
    require(system in ("Windows", "Linux", "Darwin"), "unsupported_host")
    rustc = run(["rustc", "-vV"], 10).decode().strip()
    host = next(
        (line[6:] for line in rustc.splitlines() if line.startswith("host: ")), ""
    )
    require(re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", host) is not None, "rust_host")
    report.update(
        git_revision=initial[0],
        git_dirty=False,
        system=system,
        os_release=platform.release(),
        machine=platform.machine(),
        profile="release",
        features="default serde; target desktop backend",
        rustc=rustc,
        target=host,
        scope="process lifetime high-water; not allocator bytes or leak proof",
        options={"timeout_ms": 2000, "max_entries": 128, "sensitive": False},
    )
    run(
        [
            "cargo",
            "build",
            "--locked",
            "--release",
            "--target-dir",
            "target/peak-memory-build",
            "--target",
            host,
            "-p",
            "daoseeker-scope-ffi",
            "-p",
            "daoseeker-scope-cli",
        ],
        900,
    )
    release = ROOT / "target/peak-memory-build" / host / "release"
    suffix = ".exe" if system == "Windows" else ""
    probe = release / f"ffi-memory-probe{suffix}"
    library = (
        release
        / {
            "Windows": "daoseeker_scope_ffi.dll",
            "Linux": "libdaoseeker_scope_ffi.so",
            "Darwin": "libdaoseeker_scope_ffi.dylib",
        }[system]
    )
    cli = release / f"dscope{suffix}"
    if system == "Windows":
        build = [
            "pwsh",
            "-NoProfile",
            "-File",
            "scripts/build_c_example.ps1",
            "-PeakMemoryProbe",
            "-PeakMemoryDirectory",
            str(release),
        ]
    else:
        build = [
            "cc",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-std=c11",
            "docs/research/ffi_memory_probe.c",
            f"-L{release}",
            "-ldaoseeker_scope_ffi",
            f"-Wl,-rpath,{release}",
            "-o",
            str(probe),
        ]
    build_output = run(build).decode("utf-8")
    if system == "Windows":
        version = re.search(
            r"^c_compiler_version=([0-9. ]+)\r?$", build_output, re.MULTILINE
        )
        require(version is not None, "c_compiler_version")
        report["c_compiler"] = version[1].strip() if version else ""
    else:
        report["c_compiler"] = (
            run(["cc", "--version"], 10).decode().splitlines()[0][:256]
        )
    report["c_build"] = (
        "MSVC /W4 /WX /O2 /std:c11; release import library; Psapi.lib"
        if system == "Windows"
        else "cc -O2 -Wall -Wextra -Werror -std=c11; release shared library and rpath"
    )
    binaries = [probe, library, cli]
    hashes = fingerprint(binaries)
    report["binary_sha256"] = hashes
    snapshot = json.loads(run([str(cli), "--json"]))
    schema = json.loads((ROOT / "docs/schema/snapshot-v1.schema.json").read_bytes())
    jsonschema.validate(snapshot, schema)
    check_snapshot(snapshot)
    hardware = snapshot["static_info"]["system"]
    report["hardware"] = {
        "cpu_brand": hardware["cpu"]["brand"],
        "logical_count": hardware["cpu"]["logical_count"],
        "total_usable_bytes": hardware["memory"]["total_usable_bytes"],
    }
    report["snapshot_schema_and_privacy"] = True
    modes: dict[str, Any] = {}
    report["measurements"] = modes
    for mode in ("calibrate", "cached", "fresh"):
        # Separate processes: the 64 MiB calibration must not raise workload peaks.
        data = json.loads(run([str(probe), mode]))
        modes[mode] = {"accepted": False, "observation": data}
        validate(data, mode, system)
        modes[mode]["accepted"] = True
    verify_unchanged(initial, binaries, hashes)
    report["source_and_binaries_unchanged"] = True


def main() -> None:
    output = ROOT / "target/peak-memory-evidence.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "overall": "incomplete",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    output.write_text(json.dumps(report) + "\n", encoding="utf-8")
    try:
        measure(report)
        report["overall"] = "passed"
    except Exception:
        report["overall"] = "failed"
        raise
    finally:
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
