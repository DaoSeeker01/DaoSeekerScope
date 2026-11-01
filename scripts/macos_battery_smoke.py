"""Compare anonymous IOPowerSources SDK views with the public Rust snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import subprocess
import tempfile
from typing import Any

import jsonschema

from cli_bundle import ROOT, digest, require
from native_smoke import check_snapshot

LIMIT = 1024 * 1024
KEYS = {
    "type",
    "present",
    "current_kind",
    "current",
    "maximum_kind",
    "maximum",
    "power",
}


def expected(
    sdk: dict[str, Any],
) -> tuple[str, str | None, list[tuple[Any, ...]] | None]:
    require(set(sdk) == {"status", "source_count", "records"}, "battery_sdk_shape")
    count, rows = sdk["source_count"], sdk["records"]
    require(type(count) is int and isinstance(rows, list), "battery_sdk_shape")
    if sdk["status"] in ("unavailable", "invalid_count"):
        require(not rows, "battery_sdk_shape")
        require(
            count == 0 if sdk["status"] == "unavailable" else not 0 <= count <= 256,
            "battery_sdk_count",
        )
        return (
            "unavailable",
            "unknown" if sdk["status"] == "unavailable" else "invalid_data",
            None,
        )
    require(
        sdk["status"] == "ok" and 0 <= count <= 256 and count == len(rows),
        "battery_sdk_count",
    )
    result = []
    for row in rows:
        require(
            isinstance(row, dict)
            and set(row) == KEYS
            and all(type(v) is int and -(2**63) <= v < 2**63 for v in row.values()),
            "battery_sdk_row",
        )
        kind, present = row["type"], row["present"]
        require(
            kind in (-2, -1, 0, 1, 2) and present in (-2, -1, 0, 1), "battery_sdk_row"
        )
        if kind == -2:
            return "unavailable", "unknown", None
        if kind == -1:
            return "unavailable", "invalid_data", None
        if kind == 2:
            return "unsupported", "not_supported", None
        if kind == 0:
            continue
        if present < 0:
            return "unavailable", "invalid_data", None
        if present == 0:
            continue
        require(
            row["current_kind"] in (0, 1, 2)
            and row["maximum_kind"] in (0, 1, 2)
            and row["power"] in (0, 1, 2, 3, 4),
            "battery_sdk_row",
        )
        charge: tuple[Any, ...]
        if row["current_kind"] != 1 or row["maximum_kind"] != 1:
            failed = (
                row["current_kind"] if row["current_kind"] != 1 else row["maximum_kind"]
            )
            charge = (
                "unavailable",
                "not_present" if failed == 0 else "invalid_data",
                None,
            )
        elif row["maximum"] <= 0 or not 0 <= row["current"] <= row["maximum"]:
            charge = ("unavailable", "invalid_data", None)
        else:
            charge = ("available", None, row["current"] / row["maximum"] * 100.0)
        power = row["power"]
        ac = (
            ("available", None, power == 1)
            if power in (1, 2)
            else (
                "unavailable",
                {0: "not_present", 3: "temporarily_unavailable", 4: "invalid_data"}[
                    power
                ],
                None,
            )
        )
        result.append((*charge, *ac))
    return "available", None, result


def canonical(rows: list[tuple[Any, ...]]) -> list[str]:
    return sorted(json.dumps(row, separators=(",", ":")) for row in rows)


def check(snapshot: dict[str, Any], sdk: dict[str, Any]) -> int:
    check_snapshot(snapshot)
    cap = next(c for c in snapshot["capabilities"] if c["field"] == "batteries")
    require(
        cap["level"] == "partial" and cap["source"] == "iokit", "battery_capability"
    )
    field = snapshot["dynamic"]["batteries"]
    state, reason, rows = expected(sdk)
    require(
        field["source"] == "iokit"
        and field["availability"] == state
        and field["reason"] == reason,
        "battery_collection",
    )
    if rows is None:
        require(
            field["value"] is None and field["observed_at"] is None,
            "battery_collection",
        )
        return 0
    require(
        isinstance(field["value"], list) and type(field["observed_at"]) is int,
        "battery_collection",
    )
    actual = []
    for entry in field["value"]:
        require(set(entry) == {"charge_percent", "on_ac_power"}, "battery_privacy")
        parts: list[Any] = []
        for key in ("charge_percent", "on_ac_power"):
            observed = entry[key]
            require(observed["source"] == "iokit", "battery_field_source")
            value = observed["value"]
            if observed["availability"] == "available":
                require(
                    type(observed["observed_at"]) is int and observed["reason"] is None,
                    "battery_field",
                )
                require(
                    (type(value) in (float, int) and 0 <= value <= 100)
                    if key == "charge_percent"
                    else type(value) is bool,
                    "battery_value",
                )
                if key == "charge_percent":
                    value = float(value)
            else:
                require(
                    value is None and observed["observed_at"] is None, "battery_missing"
                )
            parts.extend((observed["availability"], observed["reason"], value))
        actual.append(tuple(parts))
    require(canonical(actual) == canonical(rows), "battery_sdk_mismatch")
    return len(actual)


def run(arguments: list[str]) -> bytes:
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.run(
            arguments, cwd=ROOT, stdout=stdout, stderr=stderr, timeout=15
        )
        require(process.returncode == 0, "battery_child_exit")
        stdout.seek(0)
        data = stdout.read(LIMIT + 1)
    # A clean `git status --porcelain` legitimately produces no output.
    require(len(data) <= LIMIT, "battery_output_limit")
    return data


def source() -> dict[str, str]:
    return {
        "revision": run(["git", "rev-parse", "HEAD"]).decode().strip(),
        "status": run(["git", "status", "--porcelain"]).decode().strip(),
    }


def collect() -> dict[str, Any]:
    require(platform.system() == "Darwin", "battery_native_host")
    before = source()
    require(not before["status"], "battery_dirty_source")
    paths = {
        "sdk": ROOT / "target/macos-battery-probe",
        "cli": ROOT / "target/debug/dscope",
    }
    hashes = {name: digest(path.read_bytes()) for name, path in paths.items()}
    schema = json.loads((ROOT / "docs/schema/snapshot-v1.schema.json").read_bytes())
    observations = []
    for attempt in range(3):
        first = json.loads(run([str(paths["sdk"])]))
        snapshot = json.loads(run([str(paths["cli"]), "battery", "--json"]))
        last = json.loads(run([str(paths["sdk"])]))
        jsonschema.Draft202012Validator(schema).validate(snapshot)
        start_view, end_view = expected(first), expected(last)
        stable = start_view[:2] == end_view[:2] and canonical(
            start_view[2] or []
        ) == canonical(end_view[2] or [])
        observations.append(
            {"sdk_before": first, "sdk_after": last, "stable_anonymous_view": stable}
        )
        if stable:
            count = check(snapshot, first)
            require(
                source() == before
                and all(
                    digest(path.read_bytes()) == hashes[name]
                    for name, path in paths.items()
                ),
                "battery_source_changed",
            )
            return {
                "overall": "passed",
                "source_before": before,
                "source_after": before,
                "artifact_sha256": hashes,
                "observations": observations,
                "entries_compared": count,
                "battery_fields": snapshot["dynamic"]["batteries"],
                "snapshot_schema_and_privacy": True,
                "physical_battery_verified": False,
                "published": False,
            }
    raise ValueError("battery_unstable_view")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/macos-battery-evidence.json"
    )
    args = parser.parse_args()
    report: dict[str, Any] = {"overall": "incomplete"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes((json.dumps(report) + "\n").encode())
    try:
        report = collect()
    except Exception:
        report = {"overall": "failed", "failure": "macos_battery_failed"}
        raise
    finally:
        args.output.write_bytes((json.dumps(report, indent=2) + "\n").encode())
    print("macOS battery SDK comparison passed; inspect entry count and device limits.")


if __name__ == "__main__":
    main()
