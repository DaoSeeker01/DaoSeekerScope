"""Read-only nonroot connected DRM fixtures; no real EDID or physical monitors."""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any
from linux_battery_smoke import Expectation
from linux_dynamic_smoke import execute, receive
from linux_container_smoke import IMAGE
from native_smoke import ROOT, ValidationFailure, check_linux_displays

REDACTED: Expectation = ("restricted", "privacy_redacted", None)
INVALID: Expectation = ("unavailable", "invalid_data", None)
TEMP: Expectation = ("unavailable", "temporarily_unavailable", None)
DENIED: Expectation = ("restricted", "permission_denied", None)
ABSENT: Expectation = ("unavailable", "not_present", None)
SAMPLE_COUNT = 26


def edid(name: bytes | None) -> bytes:
    data = bytearray(128)
    data[:8] = bytes([0, 255, 255, 255, 255, 255, 255, 0])
    data[12:16] = bytes([1, 2, 3, 4])
    data[18:20] = bytes([1, 4])
    if name is not None:
        if not 1 <= len(name) <= 12:
            raise ValueError("fixture name length")
        data[57] = 0xFC
        data[59:72] = (name + b"\n").ljust(13, b" ")
    data[75] = 0xFF
    data[77:90] = b"SYNTH_SERIAL "
    data[127] = -sum(data) % 256
    return bytes(data)


def verify(
    snapshot: dict[str, Any],
    expected: list[Expectation] | Expectation,
    sensitive: bool = False,
) -> dict[str, Any]:
    import jsonschema

    try:
        schema = json.loads(
            (ROOT / "docs/schema/snapshot-v1.schema.json").read_text("utf-8")
        )
        jsonschema.Draft202012Validator(schema).validate(snapshot)
        summary = check_linux_displays(snapshot, sensitive)
        observed = snapshot["static_info"]["displays"]
        if snapshot["issues"]:
            raise ValidationFailure("display: backend_issue")
        if isinstance(expected, list):
            if observed["availability"] != "available" or len(observed["value"]) != len(
                expected
            ):
                raise ValidationFailure("display: enumeration")
            for entry, (state, reason, value) in zip(observed["value"], expected):
                name = entry["name"]
                if (name["availability"], name["reason"], name["value"]) != (
                    state,
                    reason,
                    value,
                ):
                    raise ValidationFailure("display: expected_name")
        else:
            if (observed["availability"], observed["reason"]) != expected[:2]:
                raise ValidationFailure("display: expected_state")
        if snapshot["dynamic"]["memory_available_bytes"]["availability"] != "available":
            raise ValidationFailure("display: unrelated_memory_failure")
        if snapshot["static_info"]["system"]["device"]["serial_number"][
            "value"
        ] is not None or "SYNTH_SERIAL" in json.dumps(snapshot):
            raise ValidationFailure("display: serial_exported")
        return dict(
            display_summary=summary,
            healthy_memory=True,
            schema_validated=True,
            synthetic_serial_not_exported=True,
        )
    except (KeyError, TypeError, jsonschema.ValidationError) as error:
        raise ValidationFailure("display: malformed") from error


def observe(
    process: subprocess.Popen[bytes], paths: dict[str, Path], report: dict[str, Any]
) -> None:
    root = paths["drm"]
    previous: dict[str, Any] | None = None
    sensitive = False

    def sample(
        label: str,
        expected: list[Expectation] | Expectation,
        command: bytes | None = b"rebuild\n",
    ) -> None:
        nonlocal previous, sensitive
        report["samples"][label] = dict(status="running")
        if command is not None:
            if process.stdin is None:
                raise ValidationFailure("display: missing_stdin")
            if command == b"rebuild\n":
                sensitive = False
            if command == b"authorize\n":
                sensitive = True
            process.stdin.write(command)
            process.stdin.flush()
        snapshot = receive(process)
        checked = verify(snapshot, expected, sensitive)
        if command == b"refresh\n" and snapshot["static_info"]["displays"] != previous:
            raise ValidationFailure("display: static_cache_changed")
        previous = snapshot["static_info"]["displays"]
        report["samples"][label] = dict(
            status="passed", sensitive_requested=sensitive, **checked
        )

    sample("initial_empty", [], None)
    panel = root / "card0-DP-1"
    panel.mkdir(mode=0o755)
    status = panel / "status"
    status.write_bytes(b"connected\n")
    status.chmod(0o644)
    data = panel / "edid"
    data.write_bytes(edid(b"Unit panel A"))
    data.chmod(0o644)
    (panel / "modes").write_bytes(b"9999x9999\n")
    sample("connected_default", [REDACTED])
    data.write_bytes(b"bad")
    sample("default_ignores_bad_edid", [REDACTED])
    data.write_bytes(edid(b"Unit panel A"))
    sample("authorized_name", [("available", None, "Unit panel A")], b"authorize\n")
    data.write_bytes(edid(b"Unit panel B"))
    sample(
        "dynamic_keeps_static_name", [("available", None, "Unit panel A")], b"refresh\n"
    )
    sample(
        "new_authorized_reads_name",
        [("available", None, "Unit panel B")],
        b"authorize\n",
    )
    data.chmod(0)
    sample("edid_permission_denied", [DENIED], b"authorize\n")
    sample("default_ignores_denied_edid", [REDACTED])
    data.unlink()
    mkfifo = getattr(os, "mkfifo", None)
    if not callable(mkfifo):
        raise ValidationFailure("platform: mkfifo_required")
    mkfifo(data, 0o644)
    sample("default_does_not_open_fifo", [REDACTED])
    sample("authorized_rejects_fifo", [INVALID], b"authorize\n")
    data.unlink()
    data.symlink_to("status")
    sample("authorized_rejects_attribute_link", [INVALID], b"authorize\n")
    data.unlink()
    payload = bytearray(edid(b"Unit panel"))
    payload[12] ^= 1
    data.write_bytes(payload)
    sample("invalid_checksum", [INVALID], b"authorize\n")
    data.write_bytes(edid(None))
    sample("valid_base_without_name", [ABSENT], b"authorize\n")
    status.write_bytes(b"unknown\n")
    sample("status_unknown", TEMP)
    status.write_bytes(b"connected extra\n")
    sample("status_invalid", INVALID)
    status.write_bytes(b"connected\n")
    status.chmod(0)
    sample("status_permission_denied", DENIED)
    status.chmod(0o644)
    sample("cached_failure_after_permission_recovery", DENIED, b"refresh\n")
    sample("new_hardware_after_recovery", [REDACTED])
    status.write_bytes(b"disconnected\n")
    sample("disconnected_empty", [])
    status.unlink()
    sample("status_missing_no_prefix", TEMP)
    mkfifo(status, 0o644)
    sample("status_fifo_rejected", INVALID)
    status.unlink()
    status.write_bytes(b"connected\n")
    status.chmod(0o644)
    root.chmod(0)
    sample("directory_denied", DENIED)
    root.chmod(0o755)
    shutil.rmtree(root)
    sample("directory_missing", ABSENT)
    root.mkdir(mode=0o755)
    sample("restored_empty", [])
    for i in range(129):
        p = root / f"card0-DP-{i}"
        p.mkdir(mode=0o755)
        (p / "status").write_bytes(b"connected\n")
        (p / "status").chmod(0o644)
    sample("count_limit_no_prefix", INVALID)
    shutil.rmtree(root)
    root.mkdir(mode=0o755)
    sample("final_empty_recovery", [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe", type=Path, default=ROOT / "target/debug/examples/dynamic_probe"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/linux-display-evidence.json"
    )
    args = parser.parse_args()
    report: dict[str, Any] = dict(
        report_version=1,
        recorded_at_utc=datetime.now(timezone.utc).isoformat(),
        overall="incomplete",
        image_reference=IMAGE,
        synthetic_drm_connectors=True,
        synthetic_edid=True,
        samples={},
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        execute(args.probe.resolve(), report, observe=observe, gpu=True)
        if len(report["samples"]) != SAMPLE_COUNT or any(
            s["status"] != "passed" for s in report["samples"].values()
        ):
            raise ValidationFailure("display: incomplete_campaign")
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
    args.output.write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    print(f"Linux display smoke: {report['overall']}")
    return 0 if report["overall"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
