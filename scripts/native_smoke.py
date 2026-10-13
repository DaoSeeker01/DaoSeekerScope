"""Record a real desktop CLI/C/Python smoke run without device identifiers.

Requires already built native artifacts and the existing jsonschema dev dependency.
This report records execution, not cross-platform support or release readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MAX_JSON_BYTES = 1024 * 1024


class ValidationFailure(Exception):
    """Fixed error codes; never echo arguments, system errors, or raw output."""


def run(command: list[str], label: str) -> bytes:
    try:
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, check=False, timeout=60
        )
    except subprocess.TimeoutExpired as error:
        raise ValidationFailure(f"{label}: timeout") from error
    except OSError as error:
        raise ValidationFailure(f"{label}: process_unavailable") from error
    if result.returncode != 0:
        raise ValidationFailure(f"{label}: process_failed")
    if len(result.stdout) > MAX_JSON_BYTES + 1:
        raise ValidationFailure(f"{label}: output_limit")
    return result.stdout


def check_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Check minimum real-read requirements and preserve observation metadata."""
    try:
        if snapshot["schema_version"] != 1:
            raise ValidationFailure("snapshot: version")
        system = snapshot["static_info"]["system"]
        selected = {
            "os.name": system["os"]["name"],
            "cpu.brand": system["cpu"]["brand"],
            "cpu.logical_count": system["cpu"]["logical_count"],
            "memory.total_usable_bytes": system["memory"]["total_usable_bytes"],
        }
        for field, observed in selected.items():
            value = observed["value"]
            valid = (
                type(value) is int and value > 0
                if field in ("cpu.logical_count", "memory.total_usable_bytes")
                else isinstance(value, str) and bool(value.strip())
            )
            if observed["availability"] != "available" or not valid:
                raise ValidationFailure(f"snapshot: minimum_read_unavailable:{field}")
        serial = system["device"]["serial_number"]
        if (
            serial["availability"] != "restricted"
            or serial["value"] is not None
            or serial["reason"] != "privacy_redacted"
            or serial["observed_at"] is not None
        ):
            raise ValidationFailure("snapshot: privacy_violation")
        selected["device.serial_number"] = serial
        if "storage" in snapshot["static_info"]:
            storage = snapshot["static_info"]["storage"]
            if storage["availability"] == "available":
                for entry in storage["value"]:
                    name = entry["name"]
                    if (
                        name["value"] is not None
                        or name["availability"] != "restricted"
                        or name["reason"] != "privacy_redacted"
                        or name["observed_at"] is not None
                    ):
                        raise ValidationFailure("storage: privacy_violation")
            selected["static.storage"] = storage
        # Optional observations retain their actual missing/restricted states;
        # they are not promoted to success by the minimum-read gate.
        for group, name in [
            ("os", "version"),
            ("os", "kernel_version"),
            ("cpu", "architecture"),
            ("cpu", "physical_count"),
            ("memory", "installed_bytes"),
        ]:
            if name in system[group]:
                selected[f"{group}.{name}"] = system[group][name]
        if "cpu_usage_percent" in snapshot.get("dynamic", {}):
            selected["dynamic.cpu_usage_percent"] = snapshot["dynamic"][
                "cpu_usage_percent"
            ]
        if "batteries" in snapshot.get("dynamic", {}):
            selected["dynamic.batteries"] = snapshot["dynamic"]["batteries"]
        if "sensors" in snapshot.get("dynamic", {}):
            selected["dynamic.sensors"] = snapshot["dynamic"]["sensors"]
        if "networks" in snapshot.get("dynamic", {}):
            networks = snapshot["dynamic"]["networks"]
            if networks["availability"] == "available":
                for entry in networks["value"]:
                    name = entry["interface_name"]
                    if (
                        name["value"] is not None
                        or name["availability"] != "restricted"
                        or name["reason"] != "privacy_redacted"
                        or name["observed_at"] is not None
                    ):
                        raise ValidationFailure("network: privacy_violation")
            selected["dynamic.networks"] = networks
        return selected
    except (KeyError, TypeError) as error:
        raise ValidationFailure("snapshot: malformed") from error


def decode(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_JSON_BYTES:
        raise ValidationFailure("snapshot: input_limit")
    try:
        snapshot = json.loads(data)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValidationFailure("snapshot: invalid_json") from error
    if not isinstance(snapshot, dict):
        raise ValidationFailure("snapshot: malformed")
    return snapshot


def check_real_network(observations: dict[str, Any], source: str) -> None:
    """Require real native counters; an empty list is insufficient smoke evidence."""
    networks = observations.get("dynamic.networks", {})
    if (
        networks.get("availability") != "available"
        or networks.get("source") != source
        or not networks.get("value")
    ):
        raise ValidationFailure("network: minimum_read_unavailable")
    for entry in networks["value"]:
        for field in ("received_bytes", "transmitted_bytes"):
            counter = entry[field]
            if (
                counter["availability"] != "available"
                or counter["source"] != source
                or type(counter["value"]) is not int
                or not 0 <= counter["value"] <= 2**64 - 1
                or counter["observed_at"] is None
                or counter["reason"] is not None
            ):
                raise ValidationFailure("network: invalid_real_counter")


def check_real_storage(
    observations: dict[str, Any], expected_source: str = "sysfs"
) -> None:
    """Require a positive OS-reported block capacity; zero alone is insufficient."""
    storage = observations.get("static.storage", {})
    if (
        storage.get("availability") != "available"
        or expected_source not in {"sysfs", "win32", "iokit"}
        or storage.get("source")
        != ("setupapi" if expected_source == "win32" else expected_source)
        or not storage.get("value")
    ):
        raise ValidationFailure("storage: minimum_read_unavailable")
    positive = False
    for entry in storage["value"]:
        field = entry["capacity_bytes"]
        if field["availability"] == "available":
            value = field["value"]
            if (
                type(value) is not int
                or not 0
                <= value
                <= (2**64 - 1 if expected_source == "sysfs" else 2**63 - 1)
                or (expected_source == "sysfs" and value % 512)
                or field["source"] != expected_source
                or type(field["observed_at"]) is not int
                or field["reason"] is not None
            ):
                raise ValidationFailure("storage: invalid_real_capacity")
            positive |= value > 0
    if not positive:
        raise ValidationFailure("storage: minimum_read_unavailable")


def check_storage_text(data: bytes, expected_source: str) -> dict[str, Any]:
    """Validate a real default disk presentation; never retain names/raw text."""
    try:
        if len(data) > MAX_JSON_BYTES:
            raise ValidationFailure("storage_text: output_limit")
        lines = data.decode("utf-8").splitlines()
        header = re.fullmatch(r"Storage: (\d+) entries", lines[0]) if lines else None
        if header is None:
            raise ValidationFailure("storage_text: minimum_read_unavailable")
        count = int(header[1])
        if not 1 <= count <= 1024 or len(lines) != 2 + count * 3:
            raise ValidationFailure("storage_text: malformed")
        if (
            lines[-1]
            != "Entries are OS objects, including virtual devices; capacities may overlap."
        ):
            raise ValidationFailure("storage_text: malformed")
        capacities = []
        for index in range(count):
            position = 1 + index * 3
            if lines[position] != f"Storage entry {index + 1}":
                raise ValidationFailure("storage_text: malformed")
            if (
                lines[position + 1]
                != f"Name: Restricted ({expected_source}, Some(PrivacyRedacted))"
            ):
                raise ValidationFailure("storage_text: privacy_violation")
            field = lines[position + 2]
            match = re.fullmatch(
                r"Capacity: \d+(?:\.\d{2})? (?:B|KiB|MiB|GiB|TiB|PiB|EiB) \((\d+) bytes; (\w+)\)",
                field,
            )
            if match:
                value = int(match[1])
                maximum = 2**64 - 1 if expected_source == "Sysfs" else 2**63 - 1
                if not 0 <= value <= maximum or match[2] != expected_source:
                    raise ValidationFailure("storage_text: invalid_capacity")
                capacities.append(value)
            elif (
                re.fullmatch(
                    r"Capacity: (?:Unavailable|Restricted|Unsupported|NotApplicable) \("
                    + re.escape(expected_source)
                    + r", Some\(\w+\)\)",
                    field,
                )
                is None
            ):
                raise ValidationFailure("storage_text: malformed")
        if not any(value > 0 for value in capacities):
            raise ValidationFailure("storage_text: minimum_read_unavailable")
        return {
            "entry_count": count,
            "available_capacity_bytes": capacities,
            "source": expected_source,
            "names_redacted": True,
            "output_sha256": hashlib.sha256(data).hexdigest(),
        }
    except (UnicodeError, ValueError, IndexError) as error:
        raise ValidationFailure("storage_text: malformed") from error


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            hasher.update(block)
    return hasher.hexdigest()


def collect(build_dir: Path, report: dict[str, Any]) -> None:
    names = {
        "Windows": ("dscope.exe", "c-example.exe", "daoseeker_scope_ffi.dll"),
        "Linux": ("dscope", "c-example", "libdaoseeker_scope_ffi.so"),
        "Darwin": ("dscope", "c-example", "libdaoseeker_scope_ffi.dylib"),
    }
    if platform.system() not in names:
        raise ValidationFailure("platform: unsupported")
    if sys.flags.optimize:
        raise ValidationFailure("python_ffi: assertions_disabled")
    cli, c_example, library = [build_dir / name for name in names[platform.system()]]
    report["artifact_sha256"] = {
        "cli": digest(cli),
        "c_example": digest(c_example),
        "ffi": digest(library),
        "cargo_lock": digest(ROOT / "Cargo.lock"),
    }
    report["available_rustc"] = run(["rustc", "-vV"], "rustc").decode("utf-8").strip()
    # No hostname/account/device UUID/path is written into the report.
    try:
        report["git_revision"] = (
            run(["git", "rev-parse", "HEAD"], "git").decode().strip()
        )
    except ValidationFailure:
        report["git_revision"] = None
    try:
        report["git_dirty"] = bool(run(["git", "status", "--porcelain"], "git"))
    except ValidationFailure:
        report["git_dirty"] = None
    import jsonschema

    schema = json.loads(
        (ROOT / "docs/schema/snapshot-v1.schema.json").read_text("utf-8")
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    for label, command in [("cli", [str(cli), "--json"]), ("c_abi", [str(c_example)])]:
        report["checks"][label] = "running"
        snapshot = decode(run(command, label).strip())
        try:
            validator.validate(snapshot)
        except jsonschema.ValidationError as error:
            raise ValidationFailure(f"{label}: schema_invalid") from error
        observations = check_snapshot(snapshot)
        expected_source = {
            "Linux": "procfs",
            "Windows": "win32",
            "Darwin": "sysctl",
        }.get(platform.system())
        if expected_source is not None:
            check_real_network(observations, expected_source)
        if platform.system() == "Linux":
            check_real_storage(observations)
        elif platform.system() == "Windows":
            check_real_storage(observations, "win32")
        elif platform.system() == "Darwin":
            check_real_storage(observations, "iokit")
        report["observations"][label] = observations
        report["checks"][label] = "passed"
    report["checks"]["python_ffi"] = "running"
    run([sys.executable, str(ROOT / "examples/collect.py"), str(library)], "python_ffi")
    report["checks"]["python_ffi"] = "passed"
    report["checks"]["storage_text"] = "running"
    source = {"Windows": "Win32", "Linux": "Sysfs", "Darwin": "Iokit"}[
        platform.system()
    ]
    report["observations"]["storage_text"] = check_storage_text(
        run([str(cli), "disk"], "storage_text"), source
    )
    report["checks"]["storage_text"] = "passed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "target/debug")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/native-evidence.json"
    )
    args = parser.parse_args()
    report: dict[str, Any] = {
        "report_version": 1,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "execution_platform": {
            "os": platform.system(),
            "architecture": platform.machine(),
        },
        "python_version": platform.python_version(),
        "overall": "incomplete",
        "checks": {
            "cli": "not_run",
            "c_abi": "not_run",
            "python_ffi": "not_run",
            "storage_text": "not_run",
        },
        "observations": {},
    }
    # Replace any previous success before starting processes. An interruption
    # must leave an incomplete report, never stale success from an earlier run.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    try:
        collect(args.build_dir.resolve(), report)
        report["overall"] = "passed"
    except (ValidationFailure, OSError, ValueError, ImportError) as error:
        report["overall"] = "failed"
        report["failure"] = (
            str(error)
            if isinstance(error, ValidationFailure)
            else "prerequisite_failed"
        )
        for label, status in report["checks"].items():
            if status == "running":
                report["checks"][label] = "failed"
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"native smoke: {report['overall']}")
    return 0 if report["overall"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
