"""Nonroot read-only block fixtures: capacity units, isolation and static cache."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

from linux_battery_smoke import Expectation, write_attribute
from linux_container_smoke import IMAGE
from linux_dynamic_smoke import execute, receive
from native_smoke import ROOT, ValidationFailure

INVALID: Expectation = ("unavailable", "invalid_data", None)
ABSENT: Expectation = ("unavailable", "not_present", None)
DENIED: Expectation = ("restricted", "permission_denied", None)
SAMPLE_COUNT = 21


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
            raise ValidationFailure("storage: backend_issue")
        item = snapshot["static_info"]["storage"]
        if item["source"] != "sysfs":
            raise ValidationFailure("storage: wrong_source")
        if isinstance(expected, list):
            if (
                item["availability"] != "available"
                or item["reason"] is not None
                or type(item["observed_at"]) is not int
                or len(item["value"]) != len(expected)
            ):
                raise ValidationFailure("storage: enumeration")
            for entry, (state, reason, value) in zip(item["value"], expected):
                field = entry["capacity_bytes"]
                if (
                    field["source"] != "sysfs"
                    or field["availability"] != state
                    or field["reason"] != reason
                    or field["value"] != value
                    or (value is not None and type(field["value"]) is not int)
                    or ((type(field["observed_at"]) is int) != (state == "available"))
                ):
                    raise ValidationFailure("storage: capacity")
                name = entry["name"]
                if (
                    name["value"] is not None
                    or name["availability"] != "restricted"
                    or name["reason"] != "privacy_redacted"
                    or name["observed_at"] is not None
                ):
                    raise ValidationFailure("storage: privacy")
        else:
            state, reason, _ = expected
            if (
                item["availability"] != state
                or item["reason"] != reason
                or item["value"] is not None
                or item["observed_at"] is not None
            ):
                raise ValidationFailure("storage: missing_collection")
        memory = snapshot["dynamic"]["memory_available_bytes"]
        if memory["availability"] != "available" or type(memory["value"]) is not int:
            raise ValidationFailure("storage: unrelated_memory_failure")
        serial = snapshot["static_info"]["system"]["device"]["serial_number"]
        if serial["value"] is not None or serial["reason"] != "privacy_redacted":
            raise ValidationFailure("storage: device_privacy")
        return {"storage": item, "healthy_memory": True, "schema_validated": True}
    except (KeyError, TypeError, jsonschema.ValidationError) as error:
        raise ValidationFailure("storage: malformed") from error


def observe(
    process: subprocess.Popen[bytes], paths: dict[str, Path], report: dict[str, Any]
) -> None:
    root = paths["block"]
    previous: dict[str, Any] | None = None

    def sample(
        label: str,
        expected: list[Expectation] | Expectation,
        command: bytes | None = b"rebuild\n",
    ) -> None:
        nonlocal previous
        report["samples"][label] = {"status": "running"}
        if command is not None:
            if process.stdin is None:
                raise ValidationFailure("storage: stdin_missing")
            process.stdin.write(command)
            process.stdin.flush()
        snapshot = receive(process)
        checked = verify(snapshot, expected)
        if command == b"refresh\n" and snapshot["static_info"]["storage"] != previous:
            raise ValidationFailure("storage: static_cache_changed")
        previous = snapshot["static_info"]["storage"]
        report["samples"][label] = {
            "status": "passed",
            "new_hardware": command == b"rebuild\n",
            **checked,
        }

    sample("initial_empty", [], None)

    def write(payload: bytes, mode: int = 0o644) -> None:
        write_attribute(root, "a", "size", payload, mode)

    (root / "a").mkdir(mode=0o755)
    write(b"8\n")
    (root / "a/a1").mkdir(mode=0o755)
    (root / "a/a1/size").write_bytes(b"999999")
    (root / "a/serial").write_bytes(b"Synthetic-identifier-not-read")
    sample("added_whole_device", [("available", None, 4096)])
    write(b"16")
    sample("dynamic_keeps_static_capacity", [("available", None, 4096)], b"refresh\n")
    sample("new_hardware_reads_resize", [("available", None, 8192)])
    write(b"0")
    sample("genuine_zero", [("available", None, 0)])
    for label, payload in [
        ("negative", b"-1"),
        ("fraction", b"1.5"),
        ("units", b"8 KiB"),
        ("overflow", b"36028797018963968"),
        ("oversize", b"0" * 129),
        ("invalid_utf8", b"\xff"),
    ]:
        write(payload)
        sample(label, [INVALID])
    (root / "a/size").unlink()
    sample("missing_size", [ABSENT])
    write(b"8", 0)
    sample("permission_denied", [DENIED])
    (root / "a/size").unlink()
    mkfifo = getattr(os, "mkfifo", None)
    if not callable(mkfifo):
        raise ValidationFailure("platform: mkfifo_required")
    mkfifo(root / "a/size", 0o644)
    sample("fifo_rejected", [INVALID])
    (root / "a/size").unlink()
    write(b"8")
    (root / "b").mkdir(mode=0o755)
    write_attribute(root, "b", "size", b"broken")
    sample("one_bad_device_isolated", [("available", None, 4096), INVALID])
    root.chmod(0)
    sample("directory_denied", DENIED)
    root.chmod(0o755)
    sample("directory_recovered", [("available", None, 4096), INVALID])
    shutil.rmtree(root)
    sample("directory_missing", ABSENT)
    root.mkdir(mode=0o755)
    sample("restored_empty", [])
    for index in range(129):
        (root / f"s{index}").mkdir(mode=0o755)
        write_attribute(root, f"s{index}", "size", b"1")
    sample("count_limit", INVALID)
    for entry in root.iterdir():
        shutil.rmtree(entry)
    sample("final_empty_recovery", [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe", type=Path, default=ROOT / "target/debug/examples/dynamic_probe"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/linux-storage-evidence.json"
    )
    args = parser.parse_args()
    report: dict[str, Any] = {
        "report_version": 1,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "overall": "incomplete",
        "image_reference": IMAGE,
        "synthetic_block_devices": True,
        "samples": {},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        execute(args.probe.resolve(), report, observe=observe, storage=True)
        if len(report["samples"]) != SAMPLE_COUNT or any(
            sample["status"] != "passed" for sample in report["samples"].values()
        ):
            raise ValidationFailure("storage: incomplete_campaign")
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
    print(f"Linux storage smoke: {report['overall']}")
    return 0 if report["overall"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
