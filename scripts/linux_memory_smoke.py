"""Memory/uptime failure and recovery in one production Hardware process.

Reuses the nonroot, read-only, bounded Docker probe controller. Only synthetic
meminfo/uptime observations are retained; no full hardware snapshot is archived.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from linux_container_smoke import IMAGE
from linux_dynamic_smoke import execute, receive
from native_smoke import ROOT, ValidationFailure

MEMORY = b"MemTotal: 1024 kB\nMemFree: 512 kB\nMemAvailable: 512 kB\n"
UPTIME = b"123.99 200.00\n"
Expectation = tuple[str, str | None, int | None]
HEALTHY_MEMORY: Expectation = ("available", None, 524288)
HEALTHY_UPTIME: Expectation = ("available", None, 123)
INVALID: Expectation = ("unavailable", "invalid_data", None)
DENIED: Expectation = ("restricted", "permission_denied", None)


def verify(snapshot: dict[str, Any], expectations: dict[str, Expectation]) -> None:
    import jsonschema

    schema = json.loads(
        (ROOT / "docs/schema/snapshot-v1.schema.json").read_text("utf-8")
    )
    try:
        jsonschema.Draft202012Validator(schema).validate(snapshot)
        if snapshot["issues"]:
            raise ValidationFailure("snapshot: backend_issue")
        serial = snapshot["static_info"]["system"]["device"]["serial_number"]
        if serial["value"] is not None or serial["reason"] != "privacy_redacted":
            raise ValidationFailure("snapshot: privacy")
        total = snapshot["static_info"]["system"]["memory"]["total_usable_bytes"]
        if total["availability"] != "available" or total["value"] != 1048576:
            raise ValidationFailure("memory: cached_total")
        for field, (state, reason, value) in expectations.items():
            item = (
                snapshot["dynamic"]["runtime"]["uptime_seconds"]
                if field == "runtime.uptime_seconds"
                else snapshot["dynamic"][field]
            )
            if (
                item["availability"] != state
                or item["reason"] != reason
                or item["value"] != value
                or (state == "available" and type(item["observed_at"]) is not int)
                or (state != "available" and item["observed_at"] is not None)
                or item["source"] not in ("procfs", "sysinfo")
            ):
                raise ValidationFailure(f"{field}: unexpected_observation")
            cap = next(c for c in snapshot["capabilities"] if c["field"] == field)
            level = (
                "restricted"
                if state == "restricted"
                else "supported"
                if item["source"] == "procfs"
                else "partial"
            )
            if (
                cap["source"] != item["source"]
                or cap["reason"] != reason
                or cap["level"] != level
            ):
                raise ValidationFailure(f"{field}: capability_metadata")
    except (KeyError, TypeError, StopIteration, jsonschema.ValidationError) as error:
        raise ValidationFailure("snapshot: malformed") from error


def observe(
    process: subprocess.Popen[bytes], paths: dict[str, Path], report: dict[str, Any]
) -> None:
    cached_total = None

    def sample(
        label: str,
        memory: Expectation = HEALTHY_MEMORY,
        uptime: Expectation = HEALTHY_UPTIME,
        changes: dict[str, tuple[bytes, int]] | None = None,
    ) -> None:
        nonlocal cached_total
        if changes is not None:
            for file, (payload, mode) in changes.items():
                paths[file].chmod(0o644)
                paths[file].write_bytes(payload)  # Preserve the mounted inode.
                paths[file].chmod(mode)
            if process.stdin is None:
                raise ValidationFailure("probe: missing_stdin")
            process.stdin.write(b"refresh\n")
            process.stdin.flush()
        snapshot = receive(process)
        item = {
            "status": "failed",
            "memory": snapshot["dynamic"]["memory_available_bytes"],
            "uptime": snapshot["dynamic"]["runtime"]["uptime_seconds"],
            "capabilities": [
                cap
                for cap in snapshot["capabilities"]
                if cap["field"] in ("memory_available_bytes", "runtime.uptime_seconds")
            ],
        }
        report["samples"][label] = item
        verify(
            snapshot,
            {"memory_available_bytes": memory, "runtime.uptime_seconds": uptime},
        )
        total = snapshot["static_info"]["system"]["memory"]["total_usable_bytes"]
        if cached_total is not None and total != cached_total:
            raise ValidationFailure("memory: static_cache_changed")
        cached_total = total
        report["cached_total"] = total
        item.update(status="passed", schema_validated=True, static_cache_unchanged=True)

    sample("initial")
    sample("empty", INVALID, INVALID, {"meminfo": (b"", 0o644), "uptime": (b"", 0o644)})
    sample(
        "empty_recovery",
        changes={"meminfo": (MEMORY, 0o644), "uptime": (UPTIME, 0o644)},
    )
    sample("memory_denied", DENIED, changes={"meminfo": (MEMORY, 0)})
    sample("memory_recovery", changes={"meminfo": (MEMORY, 0o644)})
    sample("uptime_denied", uptime=DENIED, changes={"uptime": (UPTIME, 0)})
    sample("uptime_recovery", changes={"uptime": (UPTIME, 0o644)})
    for label, payload, expected in [
        ("memory_utf8", b"\xff", INVALID),
        ("memory_oversize", b"x" * 4097, INVALID),
        ("memory_wrong_unit", b"MemTotal: 1024 kB\nMemAvailable: 512 MB\n", INVALID),
        (
            "memory_overflow",
            b"MemTotal: 1024 kB\nMemAvailable: 18446744073709551615 kB\n",
            INVALID,
        ),
        ("memory_duplicate", MEMORY + b"MemAvailable: 512 kB\n", INVALID),
        (
            "memory_exceeds_total",
            b"MemTotal: 1024 kB\nMemAvailable: 1025 kB\n",
            INVALID,
        ),
        (
            "memory_missing_key",
            b"MemTotal: 1024 kB\nMemFree: 512 kB\n",
            ("unavailable", "not_present", None),
        ),
        (
            "memory_genuine_zero",
            b"MemTotal: 1024 kB\nMemAvailable: 0 kB\n",
            ("available", None, 0),
        ),
    ]:
        sample(label, expected, changes={"meminfo": (payload, 0o644)})
    sample("memory_final_recovery", changes={"meminfo": (MEMORY, 0o644)})
    sample(
        "memory_total_changed",
        ("unavailable", "temporarily_unavailable", None),
        changes={"meminfo": (b"MemTotal: 2048 kB\nMemAvailable: 1536 kB\n", 0o644)},
    )
    sample("memory_total_recovery", changes={"meminfo": (MEMORY, 0o644)})
    for label, payload, expected in [
        ("uptime_utf8", b"\xff", INVALID),
        ("uptime_oversize", b"x" * 257, INVALID),
        ("uptime_nan", b"NaN 0.00\n", INVALID),
        ("uptime_negative", b"-1.00 0.00\n", INVALID),
        ("uptime_overflow", b"18446744073709551616.00 0.00\n", INVALID),
        ("uptime_missing_idle", b"123.99\n", INVALID),
        ("uptime_genuine_zero", b"0.00 0.00\n", ("available", None, 0)),
    ]:
        sample(label, uptime=expected, changes={"uptime": (payload, 0o644)})
    sample("uptime_final_recovery", changes={"uptime": (UPTIME, 0o644)})
    if any(
        item[field]["source"] != "procfs"
        for item in report["samples"].values()
        for field in ("memory", "uptime")
    ):
        raise ValidationFailure("procfs: repaired_source_required")
    if cached_total is None or cached_total["source"] != "procfs":
        raise ValidationFailure("procfs: static_source_required")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe", type=Path, default=ROOT / "target/debug/examples/dynamic_probe"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/linux-memory-evidence.json"
    )
    args = parser.parse_args()
    report: dict[str, Any] = {
        "report_version": 1,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "overall": "incomplete",
        "image_reference": IMAGE,
        "synthetic_memory_and_uptime": True,
        "samples": {},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        execute(
            args.probe.resolve(),
            report,
            inputs={"meminfo": MEMORY, "uptime": UPTIME},
            observe=observe,
        )
        report["overall"] = "passed"
    except (
        ValidationFailure,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ImportError,
        subprocess.TimeoutExpired,
    ) as error:
        report["overall"] = "failed"
        report["failure"] = (
            str(error)
            if isinstance(error, ValidationFailure)
            else "prerequisite_or_cleanup_failed"
        )
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Linux memory smoke: {report['overall']}")
    return 0 if report["overall"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
