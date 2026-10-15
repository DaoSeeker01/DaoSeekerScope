"""Nonroot read-only DRM fixtures; not physical GPU or driver evidence."""

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
from native_smoke import ROOT, ValidationFailure, check_linux_gpu

INVALID: Expectation = ("unavailable", "invalid_data", None)
ABSENT: Expectation = ("unavailable", "not_present", None)
DENIED: Expectation = ("restricted", "permission_denied", None)
UNSUPPORTED: Expectation = ("unsupported", "not_supported", None)
SAMPLE_COUNT = 20


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
            raise ValidationFailure("gpu: backend_issue")
        summary = check_linux_gpu(snapshot)
        observed = snapshot["static_info"]["gpus"]
        if isinstance(expected, list):
            if observed["availability"] != "available" or len(observed["value"]) != len(
                expected
            ):
                raise ValidationFailure("gpu: enumeration")
            for entry, (state, reason, value) in zip(observed["value"], expected):
                name = entry["name"]
                if (
                    name["availability"] != state
                    or name["reason"] != reason
                    or name["value"] != value
                ):
                    raise ValidationFailure("gpu: name")
        else:
            state, reason, _ = expected
            if observed["availability"] != state or observed["reason"] != reason:
                raise ValidationFailure("gpu: missing_collection")
        if snapshot["dynamic"]["memory_available_bytes"]["availability"] != "available":
            raise ValidationFailure("gpu: unrelated_memory_failure")
        if (
            snapshot["static_info"]["system"]["device"]["serial_number"]["value"]
            is not None
        ):
            raise ValidationFailure("gpu: privacy")
        return dict(gpu_summary=summary, healthy_memory=True, schema_validated=True)
    except (KeyError, TypeError, jsonschema.ValidationError) as error:
        raise ValidationFailure("gpu: malformed") from error


def observe(
    process: subprocess.Popen[bytes], paths: dict[str, Path], report: dict[str, Any]
) -> None:
    root, devices = paths["drm"], paths["gpu_devices"]
    previous: dict[str, Any] | None = None

    def sample(
        label: str,
        expected: list[Expectation] | Expectation,
        command: bytes | None = b"rebuild\n",
    ) -> None:
        nonlocal previous
        report["samples"][label] = dict(status="running")
        if command is not None:
            if process.stdin is None:
                raise ValidationFailure("gpu: stdin_missing")
            process.stdin.write(command)
            process.stdin.flush()
        snapshot = receive(process)
        checked = verify(snapshot, expected)
        if command == b"refresh\n" and snapshot["static_info"]["gpus"] != previous:
            raise ValidationFailure("gpu: static_cache_changed")
        previous = snapshot["static_info"]["gpus"]
        report["samples"][label] = dict(
            status="passed", new_hardware=command == b"rebuild\n", **checked
        )

    def node(name: str, device: str) -> Path:
        (devices / device).mkdir(mode=0o755, exist_ok=True)
        (root / name).mkdir(mode=0o755)
        (root / name / "device").symlink_to("../../../devices/" + device)
        return devices / device

    sample("initial_empty", [], None)
    target = node("card0", "a")
    node("renderD128", "a")
    (target / "driver").symlink_to("../../bus/pci/drivers/amdgpu")
    product = target / "product_name"
    product.write_bytes(b"Unit GPU A\n")
    product.chmod(0o644)
    (target / "serial_number").write_bytes(b"Synthetic-not-read")
    (target / "mem_info_vram_total").write_bytes(b"999999999")
    (root / "card0-HDMI-A-1").mkdir(mode=0o755)
    sample("deduplicated_alias_and_connector", [("available", None, "Unit GPU A")])
    product.write_bytes(b"Unit GPU B\n")
    sample(
        "dynamic_keeps_static_name", [("available", None, "Unit GPU A")], b"refresh\n"
    )
    sample("new_hardware_reads_name", [("available", None, "Unit GPU B")])
    for label, payload in [
        ("invalid_utf8", b"\xff"),
        ("placeholder", b"unknown"),
        ("control_character", b"A\0B"),
        ("oversize", b"x" * 4097),
    ]:
        product.write_bytes(payload)
        sample(label, [INVALID])
    product.unlink()
    sample("missing_product", [ABSENT])
    product.write_bytes(b"Unit GPU")
    product.chmod(0)
    sample("permission_denied", [DENIED])
    product.unlink()
    mkfifo = getattr(os, "mkfifo", None)
    if not callable(mkfifo):
        raise ValidationFailure("platform: mkfifo_required")
    mkfifo(product, 0o644)
    sample("fifo_rejected", [INVALID])
    product.unlink()
    product.symlink_to("serial_number")
    sample("attribute_link_rejected", [INVALID])
    product.unlink()
    product.write_bytes(b"Unit GPU")
    node("card1", "b")
    sample(
        "unsupported_driver_isolated", [("available", None, "Unit GPU"), UNSUPPORTED]
    )
    root.chmod(0)
    sample("directory_denied", DENIED)
    root.chmod(0o755)
    sample("directory_recovered", [("available", None, "Unit GPU"), UNSUPPORTED])
    shutil.rmtree(target)
    sample("broken_identity_no_prefix", ABSENT)
    shutil.rmtree(root)
    sample("directory_missing", ABSENT)
    root.mkdir(mode=0o755)
    sample("restored_empty", [])
    for index in range(129):
        node(f"card{index}", f"limit{index}")
    sample("count_limit", INVALID)
    shutil.rmtree(root)
    root.mkdir(mode=0o755)
    sample("final_empty_recovery", [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe", type=Path, default=ROOT / "target/debug/examples/dynamic_probe"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/linux-gpu-evidence.json"
    )
    args = parser.parse_args()
    report: dict[str, Any] = dict(
        report_version=1,
        recorded_at_utc=datetime.now(timezone.utc).isoformat(),
        overall="incomplete",
        image_reference=IMAGE,
        synthetic_drm_devices=True,
        samples={},
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        execute(args.probe.resolve(), report, observe=observe, gpu=True)
        if len(report["samples"]) != SAMPLE_COUNT or any(
            sample["status"] != "passed" for sample in report["samples"].values()
        ):
            raise ValidationFailure("gpu: incomplete_campaign")
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
    print(f"Linux GPU smoke: {report['overall']}")
    return 0 if report["overall"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
