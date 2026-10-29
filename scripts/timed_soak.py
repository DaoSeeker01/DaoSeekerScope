"""Run a bounded wall-time C ABI sampling trial; not a long-term leak proof."""

from __future__ import annotations

import argparse
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

import peak_memory as peak
from native_smoke import check_snapshot

ROOT = Path(__file__).resolve().parent.parent
BUDGET = 16 * 1024 * 1024
MAX_TRACE = 128 * 1024


def require(value: bool, code: str) -> None:
    if not value:
        raise ValueError(f"timed_soak: {code}")


def duration(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "duration must be an integer number of seconds"
        ) from error
    if seconds < 120 or seconds > 3600 or seconds % 60:
        raise argparse.ArgumentTypeError(
            "duration must be 120..3600 seconds, in multiples of 60"
        )
    return seconds


def analyse(records: list[Any], seconds: int, system: str) -> dict[str, Any]:
    require(120 <= seconds <= 3600 and seconds % 60 == 0, "duration")
    require(len(records) == seconds // 60 + 3, "record_count")
    header, complete = records[0], records[-1]
    require(isinstance(header, dict) and isinstance(complete, dict), "record_object")
    expected = {
        "record": "header",
        "format": 1,
        "mode": "soak_cached",
        "duration_seconds": seconds,
        "checkpoint_seconds": 60,
        "call_interval_ms": 100,
        "warmup_seconds": 300 if seconds >= 600 else 60,
        "tail_budget_bytes": BUDGET,
    }
    for key, value in expected.items():
        require(
            type(header.get(key)) is type(value) and header[key] == value,
            "plan_changed",
        )
    peak.validate_launch(
        header.get("launch"), "linux_fork" if system == "Linux" else "direct"
    )
    metric, unit, multiplier, resident_metric, resident_unit = {
        "Windows": ("peak_working_set", "bytes", 1, "working_set_size", "bytes"),
        "Linux": ("ru_maxrss", "kibibytes", 1024, "proc_statm_resident", "pages"),
        "Darwin": ("ru_maxrss", "bytes", 1, "mach_task_basic_resident", "bytes"),
    }[system]
    for key, value in {
        "metric": metric,
        "raw_unit": unit,
        "multiplier": multiplier,
        "resident_metric": resident_metric,
        "resident_raw_unit": resident_unit,
    }.items():
        require(type(header.get(key)) is type(value) and header[key] == value, "metric")
    factor = header.get("resident_multiplier")
    require(
        type(factor) is int
        and (
            512 <= factor <= 65536 and factor & (factor - 1) == 0
            if system == "Linux"
            else factor == 1
        ),
        "resident_multiplier",
    )
    previous_calls = previous_peak = previous_bytes = 0
    samples = []
    for index, record in enumerate(records[1:-1]):
        require(
            isinstance(record, dict)
            and record.get("record") == "sample"
            and type(record.get("ordinal")) is int
            and record["ordinal"] == index,
            "checkpoint_order",
        )
        item = record.get("observation")
        require(isinstance(item, dict), "sample_object")
        for key in (
            "calls",
            "peak_raw",
            "peak_bytes",
            "resident_raw",
            "resident_bytes",
            "elapsed_ns",
            "max_json_bytes",
        ):
            require(
                type(item.get(key)) is int and 0 <= item[key] < 2**64, "sample_counter"
            )
        require(
            item.get("phase") == ("baseline" if index == 0 else "collected"), "phase"
        )
        require(
            item["peak_raw"] > 0
            and item["peak_bytes"] == item["peak_raw"] * multiplier
            and item["peak_bytes"] >= previous_peak,
            "peak_conversion",
        )
        require(
            item["resident_raw"] > 0
            and item["resident_bytes"] == item["resident_raw"] * factor,
            "resident_conversion",
        )
        require(
            index * 60 * 10**9
            <= item["elapsed_ns"]
            <= (index * 60 + (5 if index else 0)) * 10**9,
            "checkpoint_time",
        )
        require(
            (item["calls"] == item["max_json_bytes"] == 0)
            if index == 0
            else (
                previous_calls < item["calls"] <= seconds * 20 + 1
                and previous_bytes <= item["max_json_bytes"] <= 1024 * 1024
                and item["max_json_bytes"] > 0
            ),
            "call_or_json_limit",
        )
        previous_calls, previous_peak, previous_bytes = (
            item["calls"],
            item["peak_bytes"],
            item["max_json_bytes"],
        )
        samples.append(item)
    require(
        complete.get("record") == "complete"
        and type(complete.get("calls")) is int
        and complete["calls"] == previous_calls
        and type(complete.get("samples")) is int
        and complete["samples"] == len(samples),
        "completion",
    )
    tail = [
        s["resident_bytes"]
        for s in samples
        if s["elapsed_ns"] >= header["warmup_seconds"] * 10**9
    ]
    require(len(tail) >= 2, "warmup")
    span = max(tail) - min(tail)
    return {
        "within_budget": span <= BUDGET,
        "budget_bytes": BUDGET,
        "tail_samples": len(tail),
        "tail_min_bytes": min(tail),
        "tail_max_bytes": max(tail),
        "tail_range_bytes": span,
        "net_change_bytes": tail[-1] - tail[0],
        "calls": previous_calls,
        "elapsed_ns": samples[-1]["elapsed_ns"],
        "max_json_bytes": previous_bytes,
        "scope": "sampled OS residency; no allocator attribution or no-leak guarantee",
    }


def measure(seconds: int, report: dict[str, Any], trace_path: Path) -> None:
    initial = peak.source_state()
    require(not initial[1], "dirty_checkout")
    system = platform.system()
    rustc = peak.run(["rustc", "-vV"], 10).decode().strip()
    host = next(line[6:] for line in rustc.splitlines() if line.startswith("host: "))
    require(
        host
        in (
            "x86_64-pc-windows-msvc",
            "x86_64-unknown-linux-gnu",
            "aarch64-apple-darwin",
        ),
        "native_target",
    )
    build = ROOT / "target/timed-soak-build"
    peak.run(
        [
            "cargo",
            "build",
            "--locked",
            "--offline",
            "--release",
            "--target",
            host,
            "--target-dir",
            str(build),
            "-p",
            "daoseeker-scope-ffi",
            "-p",
            "daoseeker-scope-cli",
        ],
        900,
    )
    folder = build / host / "release"
    probe, compiler = peak.compile_probe(system, folder)
    library = (
        folder
        / {
            "Windows": "daoseeker_scope_ffi.dll",
            "Linux": "libdaoseeker_scope_ffi.so",
            "Darwin": "libdaoseeker_scope_ffi.dylib",
        }[system]
    )
    cli = folder / ("dscope.exe" if system == "Windows" else "dscope")
    binaries = [probe, library, cli]
    hashes = peak.fingerprint(binaries)
    report.update(
        source_before={"revision": initial[0], "status": initial[1]},
        system=system,
        os_release=platform.release(),
        target=host,
        rustc=rustc,
        c_compiler=compiler,
        binary_sha256=hashes,
        profile="release; default serde",
        duration_seconds=seconds,
        options={
            "default_cached_collector": True,
            "sensitive": False,
            "timeout_ms": 2000,
        },
        limits="requested 100 ms between completed calls; scheduling and OS residency affect samples; not hour/day or leak proof",
    )
    snapshot = json.loads(peak.run([str(cli), "--json"], 15))
    schema = json.loads((ROOT / "docs/schema/snapshot-v1.schema.json").read_bytes())
    jsonschema.Draft202012Validator(schema).validate(snapshot)
    check_snapshot(snapshot)
    system_info = snapshot["static_info"]["system"]
    report["environment"] = {
        "cpu": system_info["cpu"]["brand"],
        "memory": system_info["memory"]["total_usable_bytes"],
        "os": system_info["os"],
    }
    report["snapshot_schema_and_privacy"] = True
    calibration = json.loads(peak.run([str(probe), "resident_calibrate"], 15))
    report["calibration"] = calibration
    report["calibration_analysis"] = peak.resident_analysis(
        calibration, "resident_calibrate", system
    )
    invalid_arguments = ("0", "60", "119", "121", "3601", "-120", "abc", "--direct")
    for invalid in invalid_arguments:
        result = subprocess.run(
            [str(probe), "soak_cached", invalid],
            cwd=ROOT,
            capture_output=True,
            timeout=5,
        )
        require(
            result.returncode != 0 and not result.stdout, "invalid_duration_accepted"
        )
    report["invalid_duration_cases"] = len(invalid_arguments)
    # The C stream is bounded to 63 records; retain complete checkpoints on failure.
    with trace_path.open("w+b") as output, tempfile.TemporaryFile() as error:
        try:
            result = subprocess.run(
                [str(probe), "soak_cached", str(seconds)],
                cwd=ROOT,
                stdout=output,
                stderr=error,
                timeout=seconds + 60,
            )
            report["probe_exit_code"] = result.returncode
        finally:
            output.seek(0)
            raw = output.read(MAX_TRACE + 1)
            require(len(raw) <= MAX_TRACE, "trace_limit")
            report["trace_utf8"] = raw.decode("utf-8")
            report["trace_sha256"] = hashlib.sha256(raw).hexdigest()
            error.seek(0)
            diagnostic = error.read(4097)
            report["stderr_sha256"] = hashlib.sha256(diagnostic).hexdigest()
            report["probe_error"] = (
                diagnostic.decode("ascii").strip()
                if re.fullmatch(rb"ffi_memory_probe: [a-z_]+\n", diagnostic)
                else ("redacted_non_probe_diagnostic" if diagnostic else None)
            )
    require(result.returncode == 0, "probe_failed")
    records = [json.loads(line) for line in raw.splitlines()]
    report["analysis"] = analyse(records, seconds, system)
    require(report["analysis"]["within_budget"], "resident_budget_exceeded")
    require(
        records[0]["resident_multiplier"] == calibration["resident_multiplier"],
        "calibration_unit_changed",
    )
    peak.verify_unchanged(initial, binaries, hashes)
    report["source_after"] = {"revision": initial[0], "status": initial[1]}
    report["checked_at"] = datetime.now(timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=duration, default=120)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/timed-soak-evidence.json"
    )
    options = parser.parse_args()
    report: dict[str, Any] = {"format": 1, "overall": "incomplete"}
    options.output.parent.mkdir(parents=True, exist_ok=True)
    trace_path = options.output.with_suffix(".ndjson")
    require(trace_path != options.output, "report_trace_conflict")
    trace_path.write_bytes(b"")
    options.output.write_bytes((json.dumps(report) + "\n").encode())
    try:
        measure(options.seconds, report, trace_path)
        report["overall"] = "passed"
    except Exception:
        report["overall"] = "failed"
        raise
    finally:
        options.output.write_bytes(
            (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
        )


if __name__ == "__main__":
    main()
