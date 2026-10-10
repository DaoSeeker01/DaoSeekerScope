"""Nonroot kernel permission and hotplug fixtures through production Hardware.

Only synthetic power_supply values are archived. A full /sys fixture is mounted
read-only so missing class paths are testable; /proc reads remain real.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from linux_container_smoke import IMAGE
from linux_dynamic_smoke import execute, receive
from native_smoke import ROOT, ValidationFailure

Expectation = tuple[str, str | None, Any]
GOOD: Expectation = ("available", None, 50.0)
TRUE: Expectation = ("available", None, True)
FALSE: Expectation = ("available", None, False)
INVALID: Expectation = ("unavailable", "invalid_data", None)
ABSENT: Expectation = ("unavailable", "not_present", None)
DENIED: Expectation = ("restricted", "permission_denied", None)
PRIVATE = "Synthetic-battery-identifier-must-not-be-read"


def write_attribute(
    root: Path, name: str, field: str, data: bytes, mode: int = 0o644
) -> None:
    """Restore owner write access before mutating our own denied-read fixture."""
    path = root / name / field
    if path.exists():
        path.chmod(0o600)
    path.write_bytes(data)
    path.chmod(mode)


def check(item: dict[str, Any], expected: Expectation) -> None:
    state, reason, value = expected
    if (
        item["availability"] != state
        or item["reason"] != reason
        or item["source"] != "sysfs"
        or item["value"] != value
        or (value is not None and type(item["value"]) is not type(value))
        or (
            state == "available"
            and (type(item["observed_at"]) is not int or item["observed_at"] <= 0)
        )
        or (state != "available" and item["observed_at"] is not None)
    ):
        raise ValidationFailure("battery: unexpected_observation")


def verify(
    snapshot: dict[str, Any],
    expected: list[tuple[Expectation, Expectation]] | Expectation,
) -> dict[str, Any]:
    import jsonschema

    schema = json.loads(
        (ROOT / "docs/schema/snapshot-v1.schema.json").read_text("utf-8")
    )
    try:
        jsonschema.Draft202012Validator(schema).validate(snapshot)
        if snapshot["issues"]:
            raise ValidationFailure("battery: backend_issue")
        serial = snapshot["static_info"]["system"]["device"]["serial_number"]
        if (
            serial["availability"] != "restricted"
            or serial["reason"] != "privacy_redacted"
            or serial["value"] is not None
        ):
            raise ValidationFailure("battery: privacy")
        if PRIVATE in json.dumps(snapshot):
            raise ValidationFailure("battery: identifier_leak")
        memory = snapshot["dynamic"]["memory_available_bytes"]
        if memory["availability"] != "available" or type(memory["value"]) is not int:
            raise ValidationFailure("battery: unrelated_field_failure")
        batteries = snapshot["dynamic"]["batteries"]
        if isinstance(expected, list):
            values = batteries["value"]
            check(batteries, ("available", None, values))
            if not isinstance(values, list) or len(values) != len(expected):
                raise ValidationFailure("battery: incomplete_enumeration")
            for item, (charge, ac) in zip(values, expected, strict=True):
                if set(item) != {"charge_percent", "on_ac_power"}:
                    raise ValidationFailure("battery: unexpected_fields")
                check(item["charge_percent"], charge)
                check(item["on_ac_power"], ac)
            state, reason = "available", None
        else:
            check(batteries, expected)
            state, reason, _ = expected
        cap = next(c for c in snapshot["capabilities"] if c["field"] == "batteries")
        if (
            cap["source"] != "sysfs"
            or cap["reason"] != reason
            or cap["level"] != ("restricted" if state == "restricted" else "partial")
        ):
            raise ValidationFailure("battery: capability_metadata")
        return {
            "batteries": batteries,
            "capability": cap,
            "healthy_memory": True,
            "schema_validated": True,
        }
    except (
        KeyError,
        TypeError,
        StopIteration,
        ValueError,
        jsonschema.ValidationError,
    ) as error:
        raise ValidationFailure("battery: malformed") from error


def observe(
    process: subprocess.Popen[bytes], paths: dict[str, Path], report: dict[str, Any]
) -> None:
    root = paths["power_supply"]
    cached_static: dict[str, Any] | None = None

    def supply(name: str, kind: bytes) -> None:
        folder = root / name
        folder.mkdir(mode=0o755)
        write(name, "type", kind)

    def write(name: str, field: str, data: bytes, mode: int = 0o644) -> None:
        write_attribute(root, name, field, data, mode)

    def sample(
        label: str,
        expected: list[tuple[Expectation, Expectation]] | Expectation,
        initial: bool = False,
    ) -> None:
        nonlocal cached_static
        report["samples"][label] = {"status": "running"}
        if not initial:
            if process.stdin is None:
                raise ValidationFailure("probe: stdin_missing")
            process.stdin.write(b"refresh\n")
            process.stdin.flush()
        snapshot = receive(process)
        if cached_static is None:
            cached_static = snapshot["static_info"]
        if snapshot["static_info"] != cached_static:
            raise ValidationFailure("battery: static_cache_changed")
        checked = verify(snapshot, expected)
        report["samples"][label] = {
            "status": "passed",
            **checked,
            "static_cache_unchanged": True,
        }

    sample("empty", [], initial=True)
    supply("BAT0", b"Battery\n")
    write("BAT0", "capacity", b"50\n")
    write("BAT0", "serial_number", PRIVATE.encode(), 0)
    supply("AC", b"Mains\n")
    write("AC", "online", b"1\n")
    sample("added_default_present", [(GOOD, TRUE)])
    write("BAT0", "capacity", b"0\n")
    write("AC", "online", b"0\n")
    sample("genuine_zero_offline", [(("available", None, 0.0), FALSE)])
    for label, payload in [
        ("percent_exceeds", b"101"),
        ("percent_negative", b"-1"),
        ("percent_nan", b"NaN"),
        ("percent_utf8", b"\xff"),
        ("percent_oversize", b"x" * 129),
    ]:
        write("BAT0", "capacity", payload)
        sample(label, [(INVALID, FALSE)])
    (root / "BAT0/capacity").unlink()
    sample("capacity_missing", [(ABSENT, FALSE)])
    write("BAT0", "capacity", b"50", 0)
    sample("capacity_denied", [(DENIED, FALSE)])
    (root / "BAT0/capacity").unlink()
    mkfifo = getattr(os, "mkfifo", None)
    if not callable(mkfifo):
        raise ValidationFailure("platform: mkfifo_required")
    mkfifo(root / "BAT0/capacity", 0o644)
    sample("capacity_fifo_rejected", [(INVALID, FALSE)])
    (root / "BAT0/capacity").unlink()
    write("BAT0", "capacity", b"100")
    sample("capacity_recovered", [(("available", None, 100.0), FALSE)])
    write("AC", "online", b"1", 0)
    sample("online_denied", [(("available", None, 100.0), DENIED)])
    write("AC", "online", b"2")
    sample("online_invalid", [(("available", None, 100.0), INVALID)])
    shutil.rmtree(root / "AC")
    supply("USB", b"USB")
    write("USB", "online", b"1")
    sample("usb_does_not_imply_ac", [(("available", None, 100.0), ABSENT)])
    write("BAT0", "present", b"0")
    sample("battery_absent", [])
    write("BAT0", "present", b"2")
    sample("present_invalid", INVALID)
    write("BAT0", "present", b"1", 0)
    sample("present_denied", DENIED)
    (root / "BAT0/present").unlink()
    sample("present_recovered_missing", [(("available", None, 100.0), ABSENT)])
    (root / "BAT0/type").unlink()
    sample("type_missing", ABSENT)
    write("BAT0", "type", b"Battery", 0)
    sample("type_denied", DENIED)
    write("BAT0", "type", b"Battery")
    sample("type_recovered", [(("available", None, 100.0), ABSENT)])
    supply("BAT1", b"Battery")
    write("BAT1", "capacity", b"bad")
    sample(
        "second_bad_field_isolated",
        [(("available", None, 100.0), ABSENT), (INVALID, ABSENT)],
    )
    root.chmod(0)
    sample("directory_denied", DENIED)
    root.chmod(0o755)
    sample(
        "directory_recovered", [(("available", None, 100.0), ABSENT), (INVALID, ABSENT)]
    )
    shutil.rmtree(root)
    sample("directory_missing", ABSENT)
    root.mkdir(mode=0o755)
    sample("directory_restored_empty", [])
    for index in range(129):
        supply(f"b{index:03}", b"Battery")
    sample("battery_count_limit", INVALID)
    for path in root.iterdir():
        (path / "type").write_bytes(b"USB")
    for index in range(129, 257):
        supply(f"b{index:03}", b"USB")
    sample("scan_count_limit", INVALID)
    for path in list(root.iterdir()):
        shutil.rmtree(path)
    sample("final_empty_recovery", [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe", type=Path, default=ROOT / "target/debug/examples/dynamic_probe"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/linux-battery-evidence.json"
    )
    args = parser.parse_args()
    report: dict[str, Any] = {
        "report_version": 1,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "overall": "incomplete",
        "image_reference": IMAGE,
        "synthetic_power_supply": True,
        "samples": {},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        execute(args.probe.resolve(), report, observe=observe, power_supply=True)
        if len(report["samples"]) != 30 or any(
            s["status"] != "passed" for s in report["samples"].values()
        ):
            raise ValidationFailure("battery: incomplete_campaign")
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
    print(f"Linux battery smoke: {report['overall']}")
    return 0 if report["overall"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
