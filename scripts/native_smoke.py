"""Record a real desktop CLI/C/Python smoke run without device identifiers.

Requires already built native artifacts and the existing jsonschema dev dependency.
This report records execution, not cross-platform support or release readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parent.parent
MAX_JSON_BYTES = 1024 * 1024
TEXT_SOURCES = r"(?:Sysinfo|Wmi|Win32|Setupapi|Dxgi|Smbios|Sysfs|Procfs|Udev|Hwmon|Pci|Drm|Iokit|Sysctl|AppleApi|AndroidApi|WebApi|Hal|Custom)"
TEXT_REASONS = r"(?:PermissionDenied|Sandbox|NotSupported|NotPresent|Timeout|InvalidData|PrivacyRedacted|TemporarilyUnavailable|Unknown)"
TEXT_MISSING = r"(?:Unavailable|Restricted|Unsupported|NotApplicable)"
TEXT_COMMANDS = (
    "cpu",
    "memory",
    "system",
    "gpu",
    "display",
    "network",
    "battery",
    "sensors",
    "capabilities",
)
PROCESS_LABELS = frozenset(
    {
        "rustc",
        "git_revision",
        "git_status",
        "cli",
        "c_abi",
        "python_ffi",
        "storage_text",
    }
    | {f"cli_text_{command}" for command in TEXT_COMMANDS}
)
SCOPE_ERRORS = {
    b"InvalidArgument": "invalid_argument",
    b"UnsupportedPlatform": "unsupported_platform",
    b"Timeout": "timeout",
    b"Cancelled": "cancelled",
    b"Busy": "busy",
    b"BackendFailure": "backend_failure",
    b"ResourceLimit": "resource_limit",
    b"Panic": "panic",
    b"InvalidBuffer": "invalid_buffer",
}
# Other smoke scripts import run(); preserve their existing fixed-label contract.
SHARED_PROCESS_LABELS = frozenset(
    {
        "git",
        "docker",
        "image_pull",
        "image_inspect",
        "container_create",
        "container_inspect",
        "container_state",
    }
)
C_ERRORS = {
    code.replace("_", " ").encode("ascii"): code for code in SCOPE_ERRORS.values()
}


class ValidationFailure(Exception):
    """Fixed error codes; never echo arguments, system errors, or raw output."""


class ProcessFailure(ValidationFailure):
    """Diagnostic payload omits child output and executable arguments."""

    def __init__(self, label: str, category: str, diagnostic: dict[str, Any]) -> None:
        super().__init__(f"{label}: {category}")
        self.diagnostic = diagnostic


def scope_error(label: str, return_code: int, stderr: bytes) -> str | None:
    # Match the entire bounded message, not a token buried in arbitrary output.
    # A process timeout is distinct from the library's caller-wait Timeout.
    if len(stderr) > 512:
        return None
    line = stderr.removesuffix(b"\n").removesuffix(b"\r")
    if (
        label == "cli" or label == "storage_text" or label.startswith("cli_text_")
    ) and return_code == 3:
        prefix = b"dscope: collection error: "
        return (
            SCOPE_ERRORS.get(line[len(prefix) :]) if line.startswith(prefix) else None
        )
    if label == "c_abi" and return_code == 2:
        return C_ERRORS.get(line)
    return None


def run(
    command: list[str], label: str, processes: dict[str, Any] | None = None
) -> bytes:
    if label not in PROCESS_LABELS | SHARED_PROCESS_LABELS:
        raise ValidationFailure("process: invalid_label")
    diagnostic: dict[str, Any] = {
        "status": "running",
        "command": label,
        "return_code": None,
        "scope_error": None,
        "stdout_bytes": None,
        "stderr_bytes": None,
    }
    if processes is not None:
        processes[label] = diagnostic

    def fail(category: str) -> NoReturn:
        diagnostic.update(status="failed", failure_category=category)
        raise ProcessFailure(label, category, diagnostic) from None

    result: subprocess.CompletedProcess[bytes] | None = None
    failure_category = "process_unavailable"
    try:
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, check=False, timeout=60
        )
    except subprocess.TimeoutExpired as error:
        diagnostic["stdout_bytes"] = (
            len(error.stdout) if isinstance(error.stdout, bytes) else None
        )
        diagnostic["stderr_bytes"] = (
            len(error.stderr) if isinstance(error.stderr, bytes) else None
        )
        failure_category = "timeout"
    except OSError as error:
        diagnostic["os_errno"] = error.errno
    # Raise outside the handler so the exception does not retain the original
    # OSError/TimeoutExpired (which can contain paths, arguments and raw output).
    if result is None:
        fail(failure_category)
    diagnostic.update(
        return_code=result.returncode,
        stdout_bytes=len(result.stdout),
        stderr_bytes=len(result.stderr),
    )
    if len(result.stdout) > MAX_JSON_BYTES + 1 or len(result.stderr) > MAX_JSON_BYTES:
        fail("output_limit")
    if result.returncode != 0:
        diagnostic["scope_error"] = scope_error(label, result.returncode, result.stderr)
        fail("process_failed")
    diagnostic["status"] = "passed"
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


def check_linux_gpu(snapshot: dict[str, Any]) -> dict[str, Any]:
    """DRM view metadata; no product descriptions or internal device locations retained."""
    try:
        observed = snapshot["static_info"]["gpus"]
        state = observed["availability"]
        if observed["source"] != "drm":
            raise ValidationFailure("gpu: collection_source")
        allowed = {
            "unavailable": {
                "not_present",
                "invalid_data",
                "unknown",
                "timeout",
                "temporarily_unavailable",
            },
            "restricted": {"permission_denied"},
            "unsupported": {"not_supported"},
        }
        summary: dict[str, Any] = {
            key: observed[key]
            for key in ("availability", "source", "reason", "observed_at")
        }
        if state != "available":
            if (
                observed["value"] is not None
                or observed["observed_at"] is not None
                or observed["reason"] not in allowed.get(state, set())
            ):
                raise ValidationFailure("gpu: missing_metadata")
            return summary
        entries = observed["value"]
        if (
            not isinstance(entries, list)
            or len(entries) > 128
            or type(observed["observed_at"]) is not int
            or observed["reason"] is not None
        ):
            raise ValidationFailure("gpu: collection_metadata")
        names = []
        for entry in entries:
            memory = entry["dedicated_memory_bytes"]
            expected_memory = dict(
                value=None,
                availability="unsupported",
                source="drm",
                reason="not_supported",
                observed_at=None,
            )
            if any(memory[key] != value for key, value in expected_memory.items()):
                raise ValidationFailure("gpu: fabricated_memory")
            name = entry["name"]
            name_state = name["availability"]
            if name["source"] not in {"sysfs", "procfs", "drm"}:
                raise ValidationFailure("gpu: name_source")
            if name_state == "available":
                value = name["value"]
                if (
                    name["source"] not in {"sysfs", "procfs"}
                    or not isinstance(value, str)
                    or not value.strip()
                    or len(value.encode("utf-8")) > 4096
                    or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
                    or type(name["observed_at"]) is not int
                    or name["reason"] is not None
                ):
                    raise ValidationFailure("gpu: name_metadata")
            elif (
                name["value"] is not None
                or name["observed_at"] is not None
                or name["reason"] not in allowed.get(name_state, set())
                or (name_state == "unsupported" and name["source"] != "drm")
            ):
                raise ValidationFailure("gpu: name_metadata")
            names.append(
                {
                    key: name[key]
                    for key in ("availability", "source", "reason", "observed_at")
                }
            )
        summary.update(
            entries=len(entries),
            names_available=sum(name["availability"] == "available" for name in names),
            name_metadata=names,
        )
        return summary
    except (KeyError, TypeError, UnicodeError) as error:
        raise ValidationFailure("gpu: malformed") from error


def check_macos_gpu(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Metal view: retain only counts and field states, never product names."""
    try:
        collection = snapshot["static_info"]["gpus"]
        if collection["source"] != "apple_api":
            raise ValidationFailure("gpu: collection_source")
        summary = {
            key: collection[key]
            for key in ("availability", "source", "reason", "observed_at")
        }
        if collection["availability"] != "available":
            if not (
                collection["availability"] == "unavailable"
                and collection["reason"] == "invalid_data"
                and collection["value"] is None
                and collection["observed_at"] is None
            ):
                raise ValidationFailure("gpu: missing_metadata")
            return summary
        entries = collection["value"]
        if (
            not isinstance(entries, list)
            or len(entries) > 128
            or type(collection["observed_at"]) is not int
            or collection["reason"] is not None
        ):
            raise ValidationFailure("gpu: collection_metadata")
        names_available = unified = 0
        for entry in entries:
            name = entry["name"]
            if name["source"] != "apple_api":
                raise ValidationFailure("gpu: name_source")
            if name["availability"] == "available":
                value = name["value"]
                if (
                    not isinstance(value, str)
                    or not value.strip()
                    or len(value.encode("utf-16-le")) > 2048
                    or len(value.encode("utf-8")) > 4096
                    or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value)
                    or type(name["observed_at"]) is not int
                    or name["reason"] is not None
                ):
                    raise ValidationFailure("gpu: name_metadata")
                names_available += 1
            elif not (
                name["availability"] == "unavailable"
                and name["reason"] == "invalid_data"
                and name["value"] is None
                and name["observed_at"] is None
            ):
                raise ValidationFailure("gpu: name_metadata")
            memory = entry["dedicated_memory_bytes"]
            if (
                memory["source"] != "apple_api"
                or memory["value"] is not None
                or memory["observed_at"] is not None
                or (memory["availability"], memory["reason"])
                not in {
                    ("not_applicable", "not_present"),
                    ("unsupported", "not_supported"),
                }
            ):
                raise ValidationFailure("gpu: fabricated_memory")
            unified += memory["availability"] == "not_applicable"
        summary.update(
            entries=len(entries),
            names_available=names_available,
            unified_memory=unified,
            dedicated_memory_unsupported=len(entries) - unified,
        )
        return summary
    except (KeyError, TypeError, UnicodeError) as error:
        raise ValidationFailure("gpu: malformed") from error


def check_linux_displays(
    snapshot: dict[str, Any], sensitive: bool = False
) -> dict[str, Any]:
    """Connected view only: retain counts/states, never names or raw EDID."""
    try:
        observed = snapshot["static_info"]["displays"]
        allowed = {
            "restricted": {"permission_denied"},
            "unavailable": {
                "not_present",
                "invalid_data",
                "temporarily_unavailable",
                "timeout",
                "unknown",
            },
        }
        if observed["source"] != "drm":
            raise ValidationFailure("display: collection_source")
        summary = {
            k: observed[k] for k in ("availability", "source", "reason", "observed_at")
        }
        if observed["availability"] != "available":
            if (
                observed["value"] is not None
                or observed["observed_at"] is not None
                or observed["reason"]
                not in allowed.get(observed["availability"], set())
            ):
                raise ValidationFailure("display: missing_metadata")
            return summary
        entries = observed["value"]
        if (
            not isinstance(entries, list)
            or len(entries) > 128
            or type(observed["observed_at"]) is not int
            or observed["reason"] is not None
        ):
            raise ValidationFailure("display: collection_metadata")
        names = []
        for entry in entries:
            for key in ("width_pixels", "height_pixels"):
                item = entry[key]
                expected = dict(
                    value=None,
                    availability="unsupported",
                    source="drm",
                    observed_at=None,
                    reason="not_supported",
                )
                if any(item[k] != v for k, v in expected.items()):
                    raise ValidationFailure("display: fabricated_resolution")
            item = entry["name"]
            if item["source"] != "sysfs":
                raise ValidationFailure("display: name_source")
            if not sensitive:
                expected = dict(
                    value=None,
                    availability="restricted",
                    source="sysfs",
                    observed_at=None,
                    reason="privacy_redacted",
                )
                if any(item[k] != v for k, v in expected.items()):
                    raise ValidationFailure("display: privacy")
            elif item["availability"] == "available":
                value = item["value"]
                if (
                    not isinstance(value, str)
                    or not value.strip()
                    or len(value) > 13
                    or any(not 32 <= ord(c) <= 126 for c in value)
                    or type(item["observed_at"]) is not int
                    or item["reason"] is not None
                ):
                    raise ValidationFailure("display: name_metadata")
            elif (
                item["value"] is not None
                or item["observed_at"] is not None
                or item["reason"]
                not in {**allowed, "unsupported": {"not_supported"}}.get(
                    item["availability"], set()
                )
            ):
                raise ValidationFailure("display: name_metadata")
            names.append(
                {
                    k: item[k]
                    for k in ("availability", "source", "reason", "observed_at")
                }
            )
        summary.update(
            entries=len(entries),
            names_available=sum(n["availability"] == "available" for n in names),
            name_metadata=names,
        )
        return summary
    except (KeyError, TypeError) as error:
        raise ValidationFailure("display: malformed") from error


def check_macos_display_dimensions(pair: dict[str, Any]) -> None:
    for key in ("width_pixels", "height_pixels"):
        item = pair[key]
        if item["source"] != "apple_api":
            raise ValidationFailure("display: field_source")
        if item["availability"] == "available":
            if (
                type(item["value"]) is not int
                or not 1 <= item["value"] <= 0xFFFFFFFF
                or type(item["observed_at"]) is not int
                or item["observed_at"] < 0
                or item["reason"] is not None
            ):
                raise ValidationFailure("display: dimension_metadata")
        elif (
            item["availability"] != "unavailable"
            or item["value"] is not None
            or item["observed_at"] is not None
            or item["reason"] not in ("invalid_data", "temporarily_unavailable")
        ):
            raise ValidationFailure("display: dimension_metadata")
    width, height = pair["width_pixels"], pair["height_pixels"]
    if any(width[k] != height[k] for k in ("availability", "reason", "observed_at")):
        raise ValidationFailure("display: partial_dimensions")


def check_macos_displays(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Active CG mode pixels; no names, IDs, physical-count or panel inference."""
    try:
        observed = snapshot["static_info"]["displays"]
        if observed["source"] != "apple_api" and not (
            observed["availability"] == "unsupported" and observed["source"] == "custom"
        ):
            raise ValidationFailure("display: collection_source")
        summary = {
            k: observed[k] for k in ("availability", "source", "reason", "observed_at")
        }
        if observed["availability"] != "available":
            allowed = {
                "unsupported": {"not_supported"},
                "unavailable": {
                    "invalid_data",
                    "temporarily_unavailable",
                    "not_present",
                    "unknown",
                },
            }
            if (
                observed["value"] is not None
                or observed["observed_at"] is not None
                or observed["reason"]
                not in allowed.get(observed["availability"], set())
            ):
                raise ValidationFailure("display: missing_metadata")
            return summary
        entries = observed["value"]
        if (
            not isinstance(entries, list)
            or len(entries) > 128
            or type(observed["observed_at"]) is not int
            or observed["observed_at"] < 0
            or observed["reason"] is not None
        ):
            raise ValidationFailure("display: collection_metadata")
        dimensions = []
        for entry in entries:
            name = entry["name"]
            expected = dict(
                value=None,
                availability="unsupported",
                source="apple_api",
                observed_at=None,
                reason="not_supported",
            )
            if any(name[k] != value for k, value in expected.items()):
                raise ValidationFailure("display: fabricated_name")
            pair = {k: entry[k] for k in ("width_pixels", "height_pixels")}
            check_macos_display_dimensions(pair)
            dimensions.append(pair)
        summary.update(
            entries=len(entries),
            names_available=0,
            dimensions_available=sum(
                p["width_pixels"]["availability"] == "available" for p in dimensions
            ),
            dimensions=dimensions,
        )
        return summary
    except (KeyError, TypeError) as error:
        raise ValidationFailure("display: malformed") from error


def check_windows_displays(snapshot: dict[str, Any]) -> dict[str, Any]:
    """CCD path metadata and pixel sizes, without product names or native IDs."""
    try:
        collection = snapshot["static_info"]["displays"]
        state = collection["availability"]
        if collection["source"] != "win32" and not (
            state == "unsupported" and collection["source"] == "custom"
        ):
            raise ValidationFailure("display: collection_source")
        allowed = {
            "restricted": {"permission_denied"},
            "unsupported": {"not_supported"},
            "unavailable": {
                "invalid_data",
                "timeout",
                "temporarily_unavailable",
                "unknown",
            },
        }

        def missing(item: dict[str, Any], field: bool = False) -> bool:
            reasons = allowed.get(item["availability"], set())
            if field and item["availability"] == "unavailable":
                reasons = reasons | {"not_present"}
            return (
                item["value"] is None
                and item["observed_at"] is None
                and item["reason"] in reasons
            )

        summary = {
            key: collection[key]
            for key in ("availability", "source", "reason", "observed_at")
        }
        if state != "available":
            if not missing(collection):
                raise ValidationFailure("display: missing_metadata")
            return summary
        entries = collection["value"]
        if (
            not isinstance(entries, list)
            or len(entries) > 128
            or type(collection["observed_at"]) is not int
            or collection["reason"] is not None
        ):
            raise ValidationFailure("display: collection_metadata")
        names = []
        dimensions = []
        for entry in entries:
            name = entry["name"]
            if name["source"] != "win32":
                raise ValidationFailure("display: field_source")
            if name["availability"] == "available":
                value = name["value"]
                if (
                    not isinstance(value, str)
                    or not value.strip()
                    or len(value.encode("utf-16-le")) > 126
                    or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value)
                    or type(name["observed_at"]) is not int
                    or name["reason"] is not None
                ):
                    raise ValidationFailure("display: name_metadata")
            elif not missing(name, True):
                raise ValidationFailure("display: name_metadata")
            names.append(
                {
                    key: name[key]
                    for key in ("availability", "source", "reason", "observed_at")
                }
            )
            pair = {key: entry[key] for key in ("width_pixels", "height_pixels")}
            for item in pair.values():
                if item["source"] != "win32":
                    raise ValidationFailure("display: field_source")
                if item["availability"] == "available":
                    if (
                        type(item["value"]) is not int
                        or not 1 <= item["value"] <= 0xFFFFFFFF
                        or type(item["observed_at"]) is not int
                        or item["reason"] is not None
                    ):
                        raise ValidationFailure("display: dimension_metadata")
                elif not missing(item, True):
                    raise ValidationFailure("display: dimension_metadata")
            w, h = pair.values()
            if any(
                w[key] != h[key] for key in ("availability", "reason", "observed_at")
            ):
                raise ValidationFailure("display: partial_dimensions")
            dimensions.append(pair)
        summary.update(
            entries=len(entries),
            names_available=sum(n["availability"] == "available" for n in names),
            name_metadata=names,
            dimensions=dimensions,
        )
        return summary
    except (KeyError, TypeError, UnicodeError) as error:
        raise ValidationFailure("display: malformed") from error


def check_windows_gpu(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Validate DXGI metadata, retaining counts/capacities but no product names."""
    try:
        observed = snapshot["static_info"]["gpus"]
        state = observed["availability"]
        source = observed["source"]
        if source != "dxgi" and not (state == "unsupported" and source == "custom"):
            raise ValidationFailure("gpu: source")
        summary: dict[str, Any] = {
            "availability": state,
            "source": source,
            "observed_at": observed["observed_at"],
            "reason": observed["reason"],
        }
        if state != "available":
            allowed = {
                "restricted": {"permission_denied"},
                "unsupported": {"not_supported"},
                "unavailable": {
                    "invalid_data",
                    "temporarily_unavailable",
                    "timeout",
                    "unknown",
                },
            }
            if (
                observed["value"] is not None
                or observed["observed_at"] is not None
                or observed["reason"] not in allowed.get(state, set())
            ):
                raise ValidationFailure("gpu: missing_metadata")
            return summary
        entries = observed["value"]
        if (
            not isinstance(entries, list)
            or len(entries) > 128
            or type(observed["observed_at"]) is not int
            or observed["reason"] is not None
        ):
            raise ValidationFailure("gpu: collection_metadata")
        name_count = 0
        capacities = []
        for entry in entries:
            name = entry["name"]
            memory = entry["dedicated_memory_bytes"]
            for field in (name, memory):
                if field["source"] != "dxgi":
                    raise ValidationFailure("gpu: field_source")
            if name["availability"] == "available":
                value = name["value"]
                if (
                    not isinstance(value, str)
                    or not value.strip()
                    or len(value.encode("utf-16-le")) > 254
                    or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
                    or type(name["observed_at"]) is not int
                    or name["reason"] is not None
                ):
                    raise ValidationFailure("gpu: name_metadata")
                name_count += 1
            elif (
                name["availability"] != "unavailable"
                or name["value"] is not None
                or name["observed_at"] is not None
                or name["reason"] != "invalid_data"
            ):
                raise ValidationFailure("gpu: name_metadata")
            value = memory["value"]
            if (
                memory["availability"] != "available"
                or type(value) is not int
                or not 0 <= value <= 2**64 - 1
                or type(memory["observed_at"]) is not int
                or memory["reason"] is not None
            ):
                raise ValidationFailure("gpu: memory_metadata")
            capacities.append(value)
        summary.update(
            entries=len(entries),
            names_available=name_count,
            dedicated_video_memory_bytes=capacities,
        )
        return summary
    except (KeyError, TypeError, UnicodeError) as error:
        raise ValidationFailure("gpu: malformed") from error


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
        collection_source = {"Win32": "Setupapi", "Sysfs": "Sysfs", "Iokit": "Iokit"}[
            expected_source
        ]
        header = (
            re.fullmatch(
                r"Storage: (\d+) entries \(" + collection_source + r"\)", lines[0]
            )
            if lines
            else None
        )
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
                != f"Name: Restricted ({expected_source}, PrivacyRedacted)"
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
                    + r", "
                    + TEXT_REASONS
                    + r"\)",
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


def check_display_text(data: bytes) -> dict[str, Any]:
    """Check stock default display text, storing counts/hash rather than names.

    This is an internal presentation regression guard, not a consumer text API.
    No comparison with another process's potentially different topology.
    """
    try:
        if len(data) > MAX_JSON_BYTES:
            raise ValidationFailure("display_text: output_limit")
        text = data.decode("utf-8")
        if not text.endswith("\n") or any(
            ord(char) < 32 and char not in "\r\n" for char in text
        ):
            raise ValidationFailure("display_text: malformed")
        lines = text.splitlines()
        missing_pattern = (
            r"("
            + TEXT_MISSING
            + r") \(("
            + TEXT_SOURCES
            + r"), ("
            + TEXT_REASONS
            + r")\)"
        )
        header = re.fullmatch(
            r"Displays: ([0-9]+) entries \((" + TEXT_SOURCES + r")\)", lines[0]
        )
        available = 0
        missing = 0
        count: int | None = None
        state = "Available"
        if header is None:
            absent = re.fullmatch(r"Displays: " + missing_pattern, lines[0])
            if len(lines) != 1 or absent is None:
                raise ValidationFailure("display_text: malformed")
            state = absent[1]
            missing = 1
        else:
            count = int(header[1])
            if count > 1024:
                raise ValidationFailure("display_text: malformed")
            if count == 0:
                if lines[1:] != ["No display entries visible to this backend."]:
                    raise ValidationFailure("display_text: malformed")
            else:
                if len(lines) != 3 + count * 4 or lines[-2:] != [
                    "Entries are OS display views, not a physical monitor count.",
                    "Pixel dimensions do not identify panel-native resolution.",
                ]:
                    raise ValidationFailure("display_text: malformed")
                for index in range(count):
                    pos = 1 + index * 4
                    if lines[pos] != f"Display entry {index + 1}":
                        raise ValidationFailure("display_text: malformed")
                    for offset, axis in enumerate(("Name", "width", "height"), 1):
                        label, value = lines[pos + offset].split(": ", 1)
                        absent = re.fullmatch(missing_pattern, value)
                        present = re.fullmatch(
                            r"(.+) \((" + TEXT_SOURCES + r")\)", value
                        )
                        if absent:
                            source = absent[2]
                            missing += 1
                        elif present:
                            source = present[2]
                            available += 1
                            if not present[1].strip():
                                raise ValidationFailure("display_text: invalid_value")
                        else:
                            raise ValidationFailure("display_text: malformed")
                        if axis == "Name":
                            expected = "Name"
                            if header[2] == "Drm" and not (
                                absent
                                and absent.groups()
                                == ("Restricted", "Sysfs", "PrivacyRedacted")
                            ):
                                raise ValidationFailure(
                                    "display_text: privacy_violation"
                                )
                            if header[2] == "AppleApi" and not (
                                absent
                                and absent.groups()
                                == ("Unsupported", "AppleApi", "NotSupported")
                            ):
                                raise ValidationFailure("display_text: malformed")
                        else:
                            prefix = {"Win32": "Signal ", "AppleApi": "Mode "}.get(
                                source, ""
                            )
                            expected = f"{prefix}{axis if prefix else axis.capitalize()} pixels"
                            if (
                                present
                                and not absent
                                and (
                                    re.fullmatch(r"[0-9]+", present[1]) is None
                                    or not 0 < int(present[1]) <= 2**32 - 1
                                )
                            ):
                                raise ValidationFailure("display_text: invalid_value")
                        if label != expected:
                            raise ValidationFailure("display_text: malformed")
        return {
            "available_fields": available,
            "missing_fields": missing,
            "entry_count": count,
            "collection_state": state,
            "output_sha256": hashlib.sha256(data).hexdigest(),
        }
    except (UnicodeError, ValueError, IndexError) as error:
        raise ValidationFailure("display_text: malformed") from error


def check_cli_text(command: str, data: bytes) -> dict[str, Any]:
    """Presentation guard for stock commands, not a stable/public text parser.

    Missing/empty device collections validate presentation, not device support.
    Each process is checked independently; no cross-process value comparison.
    """
    if command == "display":
        return check_display_text(data)
    try:
        if len(data) > MAX_JSON_BYTES:
            raise ValidationFailure("cli_text: output_limit")
        text = data.decode("utf-8")
        if not text.endswith("\n") or any(
            ord(char) < 32 and char not in "\r\n" for char in text
        ):
            raise ValidationFailure("cli_text: malformed")
        lines = text.splitlines()
        available = 0
        missing = 0

        def field(line: str, label: str) -> None:
            nonlocal available, missing
            if not line.startswith(label + ": "):
                raise ValidationFailure("cli_text: malformed")
            value = line[len(label) + 2 :]
            for special, source in (
                ("Physical total proxy bytes", "Sysctl"),
                ("Non-compressed estimate bytes", "AppleApi"),
            ):
                if (
                    label == special
                    and re.search(r"\(" + source + r"(?:\)|, )", value) is None
                ):
                    raise ValidationFailure("cli_text: memory_source")
            if re.fullmatch(
                TEXT_MISSING + r" \(" + TEXT_SOURCES + r", " + TEXT_REASONS + r"\)",
                value,
            ):
                missing += 1
                return
            observed = re.fullmatch(r"(.+) \((" + TEXT_SOURCES + r")\)", value)
            if observed is None:
                raise ValidationFailure("cli_text: missing_source")
            value = observed[1]
            if label in (
                "Received cumulative bytes",
                "Transmitted cumulative bytes",
                "OS usable total bytes",
                "Physical total proxy bytes",
                "Non-compressed estimate bytes",
                "Installed bytes",
                "Available bytes",
                "Dedicated memory bytes",
                "Uptime seconds",
                "Logical CPUs",
                "Physical cores",
            ):
                if re.fullmatch(r"[0-9]+", value) is None or int(value) > 2**64 - 1:
                    raise ValidationFailure("cli_text: invalid_value")
            elif label in ("Usage percent", "Charge percent", "Temperature Celsius"):
                number = float(value)
                if not math.isfinite(number) or (
                    label != "Temperature Celsius" and not 0 <= number <= 100
                ):
                    raise ValidationFailure("cli_text: invalid_value")
            elif label == "AC power" and value not in ("true", "false"):
                raise ValidationFailure("cli_text: invalid_value")
            elif not value.strip():
                raise ValidationFailure("cli_text: invalid_value")
            available += 1

        total_label = (
            "Physical total proxy bytes"
            if any(line.startswith("Physical total proxy bytes: ") for line in lines)
            else "OS usable total bytes"
        )
        available_label = (
            "Non-compressed estimate bytes"
            if any(line.startswith("Non-compressed estimate bytes: ") for line in lines)
            else "Available bytes"
        )
        scalar_fields = {
            "cpu": [
                "CPU",
                "Architecture",
                "Logical CPUs",
                "Physical cores",
                "Usage percent",
            ],
            "memory": [total_label, "Installed bytes", available_label],
            "system": [
                "OS",
                "OS version",
                "Kernel",
                "CPU",
                total_label,
                "Device model",
                "Uptime seconds",
            ],
        }
        entry_count: int | None = None
        collection_state: str | None = None
        if command in scalar_fields:
            labels = scalar_fields[command]
            if len(lines) != len(labels):
                raise ValidationFailure("cli_text: malformed")
            for line, label in zip(lines, labels, strict=True):
                field(line, label)
        elif command == "capabilities":
            if (
                not lines
                or len(lines) > 1024
                or any(
                    re.fullmatch(
                        r"[a-z_][a-z0-9_.]*: (?:Supported|Partial|Unsupported|Restricted|NotApplicable) \("
                        + TEXT_SOURCES
                        + r"(?:, "
                        + TEXT_REASONS
                        + r")?\)",
                        line,
                    )
                    is None
                    for line in lines
                )
            ):
                raise ValidationFailure("cli_text: malformed")
        else:
            collections = {
                "gpu": ("GPU", "GPU", ["Name", "Dedicated memory bytes"]),
                "network": (
                    "Network",
                    "Interface",
                    [
                        "Name",
                        "Received cumulative bytes",
                        "Transmitted cumulative bytes",
                    ],
                ),
                "battery": ("Batteries", "Battery", ["Charge percent", "AC power"]),
                "sensors": ("Sensors", "Sensor", ["Label", "Temperature Celsius"]),
            }
            header_label, entry_label, labels = collections[command]
            header = (
                re.fullmatch(
                    header_label + r": ([0-9]+) entries \(" + TEXT_SOURCES + r"\)",
                    lines[0],
                )
                if lines
                else None
            )
            if header is None:
                if len(lines) != 1:
                    raise ValidationFailure("cli_text: malformed")
                field(lines[0], header_label)
                if available:
                    raise ValidationFailure("cli_text: malformed")
                collection_state = lines[0].split(": ", 1)[1].split(" ", 1)[0]
            else:
                entry_count = int(header[1])
                if entry_count > 1024 or len(lines) != 1 + entry_count * (
                    1 + len(labels)
                ):
                    raise ValidationFailure("cli_text: malformed")
                collection_state = "Available"
                for index in range(entry_count):
                    position = 1 + index * (1 + len(labels))
                    if lines[position] != f"{entry_label} entry {index + 1}":
                        raise ValidationFailure("cli_text: malformed")
                    for offset, label in enumerate(labels, 1):
                        line = lines[position + offset]
                        if (command == "network" and label == "Name") or (
                            command == "sensors" and label == "Label"
                        ):
                            if (
                                re.fullmatch(
                                    label
                                    + r": Restricted \("
                                    + TEXT_SOURCES
                                    + r", PrivacyRedacted\)",
                                    line,
                                )
                                is None
                            ):
                                raise ValidationFailure("cli_text: privacy_violation")
                        field(line, label)
        return {
            "available_fields": available,
            "missing_fields": missing,
            "entry_count": entry_count,
            "collection_state": collection_state,
            "output_sha256": hashlib.sha256(data).hexdigest(),
        }
    except (UnicodeError, ValueError, KeyError, IndexError) as error:
        raise ValidationFailure("cli_text: malformed") from error


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            hasher.update(block)
    return hasher.hexdigest()


def collect_cli_text(cli: Path, report: dict[str, Any]) -> None:
    report["checks"]["cli_text"] = "running"
    observations: dict[str, Any] = {}
    report["observations"]["cli_text"] = observations
    for command in TEXT_COMMANDS:
        output = run([str(cli), command], f"cli_text_{command}", report["processes"])
        observations[command] = check_cli_text(command, output)
    report["checks"]["cli_text"] = "passed"


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
    processes = report["processes"]
    report["available_rustc"] = (
        run(["rustc", "-vV"], "rustc", processes).decode("utf-8").strip()
    )
    # No hostname/account/device UUID/path is written into the report.
    try:
        report["git_revision"] = (
            run(["git", "rev-parse", "HEAD"], "git_revision", processes)
            .decode()
            .strip()
        )
    except ValidationFailure:
        report["git_revision"] = None
    try:
        report["git_dirty"] = bool(
            run(["git", "status", "--porcelain"], "git_status", processes)
        )
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
        snapshot = decode(run(command, label, processes).strip())
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
            observations["static.gpu_summary"] = check_linux_gpu(snapshot)
            observations["static.display_summary"] = check_linux_displays(snapshot)
        elif platform.system() == "Windows":
            check_real_storage(observations, "win32")
            observations["static.gpu_summary"] = check_windows_gpu(snapshot)
            observations["static.display_summary"] = check_windows_displays(snapshot)
        elif platform.system() == "Darwin":
            check_real_storage(observations, "iokit")
            observations["static.gpu_summary"] = check_macos_gpu(snapshot)
            observations["static.display_summary"] = check_macos_displays(snapshot)
        report["observations"][label] = observations
        report["checks"][label] = "passed"
    report["checks"]["python_ffi"] = "running"
    run(
        [sys.executable, str(ROOT / "examples/collect.py"), str(library)],
        "python_ffi",
        processes,
    )
    report["checks"]["python_ffi"] = "passed"
    report["checks"]["storage_text"] = "running"
    source = {"Windows": "Win32", "Linux": "Sysfs", "Darwin": "Iokit"}[
        platform.system()
    ]
    report["observations"]["storage_text"] = check_storage_text(
        run([str(cli), "disk"], "storage_text", processes), source
    )
    report["checks"]["storage_text"] = "passed"
    collect_cli_text(cli, report)


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
            "cli_text": "not_run",
        },
        "observations": {},
        "processes": {label: {"status": "not_run"} for label in sorted(PROCESS_LABELS)},
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
        if isinstance(error, ProcessFailure):
            report["failure_detail"] = error.diagnostic
        for label, status in report["checks"].items():
            if status == "running":
                report["checks"][label] = "failed"
    finally:
        # Keep partial progress on interruption; the overall result stays incomplete.
        for process in report["processes"].values():
            if process["status"] == "running":
                process["status"] = "interrupted"
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    suffix = f" ({report['failure']})" if report["overall"] == "failed" else ""
    print(f"native smoke: {report['overall']}{suffix}")
    return 0 if report["overall"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
