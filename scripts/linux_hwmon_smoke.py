"""Nonroot read-only hwmon fixtures; unit routing, isolation, limits and recovery.

Only synthesized observations are archived. No physical temperature validation.
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

from linux_battery_smoke import Expectation, write_attribute
from linux_container_smoke import IMAGE
from linux_dynamic_smoke import execute, receive
from native_smoke import ROOT, ValidationFailure

INVALID: Expectation = ("unavailable", "invalid_data", None)
ABSENT: Expectation = ("unavailable", "not_present", None)
DENIED: Expectation = ("restricted", "permission_denied", None)
UNREADY: Expectation = ("unavailable", "temporarily_unavailable", None)
UNSUPPORTED: Expectation = ("unsupported", "not_supported", None)
PRIVATE = "Synthetic-hwmon-private-label-must-not-be-read"
SAMPLE_COUNT = 59


def check(item: dict[str, Any], expected: Expectation) -> None:
    state, reason, value = expected
    if (
        item["availability"] != state
        or item["reason"] != reason
        or item["source"] != "hwmon"
        or item["value"] != value
        or (value is not None and type(item["value"]) is not type(value))
        or (
            state == "available"
            and (type(item["observed_at"]) is not int or item["observed_at"] <= 0)
        )
        or (state != "available" and item["observed_at"] is not None)
    ):
        raise ValidationFailure("hwmon: unexpected_observation")


def verify(
    snapshot: dict[str, Any], expected: list[Expectation] | Expectation
) -> dict[str, Any]:
    import jsonschema

    schema = json.loads(
        (ROOT / "docs/schema/snapshot-v1.schema.json").read_text("utf-8")
    )
    try:
        jsonschema.Draft202012Validator(schema).validate(snapshot)
        if snapshot["issues"]:
            raise ValidationFailure("hwmon: backend_issue")
        serial = snapshot["static_info"]["system"]["device"]["serial_number"]
        if serial["value"] is not None or serial["reason"] != "privacy_redacted":
            raise ValidationFailure("hwmon: privacy")
        if PRIVATE in json.dumps(snapshot):
            raise ValidationFailure("hwmon: identifier_leak")
        memory = snapshot["dynamic"]["memory_available_bytes"]
        if memory["availability"] != "available" or type(memory["value"]) is not int:
            raise ValidationFailure("hwmon: unrelated_field_failure")
        sensors = snapshot["dynamic"]["sensors"]
        if isinstance(expected, list):
            values = sensors["value"]
            check(sensors, ("available", None, values))
            if not isinstance(values, list) or len(values) != len(expected):
                raise ValidationFailure("hwmon: incomplete_enumeration")
            for item, temperature in zip(values, expected, strict=True):
                if set(item) != {"label", "temperature_celsius"}:
                    raise ValidationFailure("hwmon: unexpected_fields")
                check(item["label"], ("restricted", "privacy_redacted", None))
                check(item["temperature_celsius"], temperature)
            state, reason = "available", None
        else:
            check(sensors, expected)
            state, reason, _ = expected
        cap = next(c for c in snapshot["capabilities"] if c["field"] == "sensors")
        if (
            cap["source"] != "hwmon"
            or cap["reason"] != reason
            or cap["level"] != ("restricted" if state == "restricted" else "partial")
        ):
            raise ValidationFailure("hwmon: capability_metadata")
        return {
            "sensors": sensors,
            "capability": cap,
            "healthy_memory": True,
            "schema_validated": True,
        }
    except (
        KeyError,
        TypeError,
        ValueError,
        StopIteration,
        jsonschema.ValidationError,
    ) as error:
        raise ValidationFailure("hwmon: malformed") from error


def observe(
    process: subprocess.Popen[bytes], paths: dict[str, Path], report: dict[str, Any]
) -> None:
    root = paths["hwmon"]
    cached_static = None

    def write(attr: str, data: bytes, mode: int = 0o644) -> None:
        write_attribute(root, "hwmon0", attr, data, mode)

    def sample(
        label: str, expected: list[Expectation] | Expectation, initial: bool = False
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
            raise ValidationFailure("hwmon: static_cache_changed")
        report["samples"][label] = {
            "status": "passed",
            **verify(snapshot, expected),
            "static_cache_unchanged": True,
        }

    good: Expectation = ("available", None, 42.5)
    sample("empty", [], True)
    (root / "hwmon0").mkdir(mode=0o755)
    write("name", b"coretemp")
    write("temp1_input", b"0")
    write("temp1_label", PRIVATE.encode())
    write("serial", PRIVATE.encode())
    sample("genuine_zero", [("available", None, 0.0)])
    write("temp1_input", b"42500")
    sample("positive", [good])
    for label, raw in [
        ("negative_coretemp", b"-1"),
        ("nan", b"NaN"),
        ("fraction", b"42.5"),
        ("utf8", b"\xff"),
        ("oversize", b"0" * 129),
    ]:
        write("temp1_input", raw)
        sample(label, [INVALID])
    write("temp1_input", b"42500", 0)
    sample("input_denied", [DENIED])
    (root / "hwmon0/temp1_input").unlink()
    mkfifo = getattr(os, "mkfifo", None)
    if not callable(mkfifo):
        raise ValidationFailure("fixture: fifo_unavailable")
    mkfifo(root / "hwmon0/temp1_input", 0o644)
    sample("input_fifo", [INVALID])
    (root / "hwmon0/temp1_input").unlink()
    write("temp1_input", b"42500")
    sample("input_recovery", [good])
    for attr, raw, label, expected in [
        ("temp1_fault", b"1", "fault", UNREADY),
        ("temp1_fault", b"2", "fault_invalid", INVALID),
        ("temp1_fault", b"0", "fault_denied", DENIED),
        ("temp1_enable", b"0", "disabled", UNREADY),
        ("temp1_enable", b"2", "enable_invalid", INVALID),
        ("temp1_enable", b"1", "enable_denied", DENIED),
    ]:
        write(attr, raw, 0 if expected == DENIED else 0o644)
        sample(label, [expected])
        (root / "hwmon0" / attr).unlink()
        if label.endswith("denied"):
            sample(label.replace("denied", "recovery"), [good])
    (root / "hwmon0/name").unlink()
    sample("name_missing", [ABSENT])
    write("name", b"coretemp", 0)
    sample("name_denied", [DENIED])
    write("name", b"\xff")
    sample("name_invalid", [INVALID])
    write("name", PRIVATE.encode())
    sample("unknown_driver", [UNSUPPORTED])
    write("name", b"k10temp")
    write("temp2_input", b"-1250")
    sample("k10_routes", [UNSUPPORTED, ("available", None, -1.25)])
    write("name", b"coretemp")
    write("temp2_input", b"NaN")
    sample("name_recovery_bad_channel_isolated", [good, INVALID])
    write("name", b"nvme")
    write("temp1_input", b"26850")
    write("temp2_input", b"27850")
    write("temp9_input", b"28850")
    composite: Expectation = ("available", None, 26.85)
    secondary: Expectation = ("available", None, 27.85)
    last: Expectation = ("available", None, 28.85)
    sample("nvme_routes", [composite, secondary, last])
    write("temp1_input", b"-273150")
    sample("nvme_composite_zero_kelvin", [INVALID, secondary, last])
    write("temp2_input", b"-273150")
    sample("nvme_secondary_zero_kelvin", [INVALID, ABSENT, last])
    write("temp1_input", b"0")
    sample("nvme_zero_celsius", [("available", None, 0.0), ABSENT, last])
    write("temp1_input", b"-150")
    sample("nvme_negative_celsius", [("available", None, -0.15), ABSENT, last])
    write("temp1_input", b"26850", 0)
    sample("nvme_input_denied", [DENIED, ABSENT, last])
    write("temp1_input", b"26850")
    write("temp2_input", b"NaN")
    sample("nvme_bad_channel_isolated", [composite, INVALID, last])
    write("temp2_input", b"27850")
    sample("nvme_recovery", [composite, secondary, last])
    mkfifo(root / "hwmon0/temp10_input", 0o644)
    sample("nvme_unsupported_channel_fifo", [composite, secondary, last, UNSUPPORTED])
    (root / "hwmon0/temp10_input").unlink()
    (root / "hwmon0/temp9_input").unlink()
    sample("nvme_unplug", [composite, secondary])
    write("temp9_input", b"28850")
    sample("nvme_replug", [composite, secondary, last])
    (root / "hwmon0/temp9_input").unlink()
    write("name", b"amdgpu")
    write("temp1_input", b"42500")
    write("temp2_input", b"68500")
    write("temp3_input", b"71500")
    edge: Expectation = ("available", None, 42.5)
    junction: Expectation = ("available", None, 68.5)
    memory: Expectation = ("available", None, 71.5)
    sample("amdgpu_routes", [edge, junction, memory])
    write("temp2_input", b"NaN")
    sample("amdgpu_bad_channel_isolated", [edge, INVALID, memory])
    write("temp1_input", b"42500", 0)
    sample("amdgpu_input_denied", [DENIED, INVALID, memory])
    write("temp1_input", b"42500")
    write("temp2_input", b"68500")
    sample("amdgpu_recovery", [edge, junction, memory])
    write("temp1_enable", b"0")
    sample("amdgpu_disabled", [UNREADY, junction, memory])
    (root / "hwmon0/temp1_enable").unlink()
    write("temp2_fault", b"1")
    sample("amdgpu_fault", [edge, UNREADY, memory])
    (root / "hwmon0/temp2_fault").unlink()
    mkfifo(root / "hwmon0/temp4_input", 0o644)
    sample("amdgpu_unsupported_channel_fifo", [edge, junction, memory, UNSUPPORTED])
    (root / "hwmon0/temp4_input").unlink()
    (root / "hwmon0/temp2_input").unlink()
    (root / "hwmon0/temp3_input").unlink()
    sample("amdgpu_optional_channels_absent", [edge])
    write("temp1_input", b"0")
    sample("amdgpu_zero_celsius", [("available", None, 0.0)])
    write("temp1_input", b"1000001")
    sample("amdgpu_out_of_range", [INVALID])
    write("temp1_input", b"-150")
    sample("amdgpu_negative_celsius", [("available", None, -0.15)])
    write("temp1_input", b"42500")
    write("temp2_input", b"NaN")
    sample("amdgpu_exit_recovery", [edge, INVALID])
    write("name", b"coretemp")
    write("temp1_input", b"42500")
    write("temp2_input", b"NaN")
    (root / "hwmon0").chmod(0)
    sample("chip_denied", DENIED)
    (root / "hwmon0").chmod(0o755)
    sample("chip_recovery", [good, INVALID])
    root.chmod(0)
    sample("root_denied", DENIED)
    root.chmod(0o755)
    sample("root_recovery", [good, INVALID])
    shutil.rmtree(root)
    sample("root_missing", ABSENT)
    root.mkdir(mode=0o755)
    sample("root_restore_empty", [])
    (root / "hwmon0").mkdir(mode=0o755)
    write("name", b"coretemp")
    for i in range(1, 130):
        write(f"temp{i}_input", b"42500")
    sample("sensor_count_limit", INVALID)
    shutil.rmtree(root / "hwmon0")
    (root / "hwmon0").mkdir(mode=0o755)
    for i in range(1025):
        write(f"ignored{i}", b"")
    sample("chip_scan_limit", INVALID)
    shutil.rmtree(root / "hwmon0")
    for i in range(257):
        (root / f"ignored{i}").touch()
    sample("class_scan_limit", INVALID)
    for path in root.iterdir():
        path.unlink()
    for n in range(5):
        folder = root / f"hwmon{n}"
        folder.mkdir(mode=0o755)
        for i in range(901):
            (folder / f"ignored{i}").touch()
    sample("global_scan_limit", INVALID)
    for path in root.iterdir():
        shutil.rmtree(path)
    sample("final_empty_recovery", [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe", type=Path, default=ROOT / "target/debug/examples/dynamic_probe"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/linux-hwmon-evidence.json"
    )
    args = parser.parse_args()
    report: dict[str, Any] = {
        "report_version": 1,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "overall": "incomplete",
        "image_reference": IMAGE,
        "synthetic_hwmon": True,
        "samples": {},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        execute(args.probe.resolve(), report, observe=observe, hwmon=True)
        if len(report["samples"]) != SAMPLE_COUNT or any(
            s["status"] != "passed" for s in report["samples"].values()
        ):
            raise ValidationFailure("hwmon: incomplete_campaign")
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
    print(f"Linux hwmon smoke: {report['overall']}")
    return 0 if report["overall"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
