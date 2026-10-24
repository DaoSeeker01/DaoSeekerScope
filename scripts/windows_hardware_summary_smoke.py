"""Compare six public static fields with an independent fixed-whitelist C SDK probe."""

from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time
from typing import Any
from windows_cpu_smoke import read_json, send

ROOT = Path(__file__).resolve().parent.parent
FIELDS = (
    "system.device.vendor",
    "system.device.model",
    "system.motherboard.vendor",
    "system.motherboard.model",
    "system.firmware.vendor",
    "system.firmware.version",
)
PLACEHOLDERS = {
    "to be filled by o.e.m.",
    "default string",
    "unknown",
    "none",
    "not specified",
    "not applicable",
    "n/a",
    "unspecified",
    "system product name",
    "system manufacturer",
    "base board product name",
    "baseboard product name",
}


def require(condition: bool) -> None:
    if not condition:
        raise ValueError("hardware_summary_probe: invalid_observation")


def expected(item: dict[str, Any]) -> tuple[str, str | None, str | None]:
    code = item["code"]
    require(type(code) is int and 0 <= code <= 2**32 - 1)
    if code:
        require(
            item["kind"] is None and item["bytes"] is None and item["value"] is None
        )
        if code in (2, 3):
            return "unavailable", None, "not_present"
        if code in (5, 1314):
            return "restricted", None, "permission_denied"
        if code in (50, 120):
            return "unsupported", None, "not_supported"
        if code in (13, 87, 234, 1630):
            return "unavailable", None, "invalid_data"
        return (
            "unavailable",
            None,
            (
                "temporarily_unavailable"
                if code in (8, 14, 170, 1018, 1237)
                else "unknown"
            ),
        )
    kind, length, value = item["kind"], item["bytes"], item["value"]
    require(type(kind) is int and type(length) is int and 0 <= length <= 2**32 - 1)
    valid = (
        kind == 1 and 2 <= length <= 4096 and length % 2 == 0 and isinstance(value, str)
    )
    if valid:
        try:
            valid = (
                len(value.encode("utf-16-le")) + 2 == length
                and len(value.encode("utf-8")) <= 4096
                and not any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in value)
                and bool(value.strip())
                and not (
                    value.strip().isascii() and value.strip().lower() in PLACEHOLDERS
                )
            )
        except UnicodeError:
            valid = False
    return (
        ("available", value.strip(), None)
        if valid
        else ("unavailable", None, "invalid_data")
    )


def check_sdk(sdk: dict[str, Any], calls: int) -> None:
    require(
        sdk["status"] == "passed"
        and type(sdk["calls"]) is int
        and sdk["calls"] == calls
    )
    require(type(sdk["queries"]) is int and sdk["queries"] == calls * 6)
    require(type(sdk["buffer_bytes"]) is int and sdk["buffer_bytes"] == 4096)
    require(sdk["token_elevated"] is None or type(sdk["token_elevated"]) is bool)
    require(isinstance(sdk["fields"], dict) and set(sdk["fields"]) == set(FIELDS))
    for item in sdk["fields"].values():
        expected(item)


def observations(snapshot: dict[str, Any]) -> dict[str, Any]:
    require(snapshot["schema_version"] == 1)
    result = {}
    for path in FIELDS:
        field = snapshot["static_info"]
        for key in path.split("."):
            field = field[key]
        result[path] = field
    return result


def compare(snapshot: dict[str, Any], sdk: dict[str, Any]) -> dict[str, Any]:
    fields = observations(snapshot)
    for path, field in fields.items():
        state, value, reason = expected(sdk["fields"][path])
        require(
            (field["availability"], field["value"], field["reason"])
            == (state, value, reason)
        )
        require(
            field["source"] == "win32"
            or (state == "unsupported" and field["source"] == "custom")
        )
        if state == "available":
            require(type(field["observed_at"]) is int and field["observed_at"] >= 0)
        else:
            require(field["observed_at"] is None)
    caps = {cap["field"]: cap for cap in snapshot["capabilities"]}
    for path in FIELDS:
        require(caps[path]["level"] == "partial" and caps[path]["source"] == "win32")
    serial = snapshot["static_info"]["system"]["device"]["serial_number"]
    require(serial["value"] is None and serial["observed_at"] is None)
    require(
        serial["availability"] == "restricted"
        and serial["reason"] == "privacy_redacted"
    )
    return fields


def collect(report: dict[str, Any]) -> None:
    require(platform.system() == "Windows")
    report["git_revision"] = (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, timeout=5)
        .decode()
        .strip()
    )
    report["git_dirty"] = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, timeout=5
        ).strip()
    )
    paths = (
        ROOT / "target/debug/examples/dynamic_probe.exe",
        ROOT / "target/hardware-summary-probe.exe",
    )
    report["artifact_sha256"] = {
        label: hashlib.sha256(path.read_bytes()).hexdigest()
        for label, path in zip(("rust_probe", "c_sdk_probe"), paths)
    }
    processes: list[subprocess.Popen[bytes]] = []
    try:
        for path in paths:
            processes.append(
                subprocess.Popen(
                    [str(path)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    cwd=ROOT,
                )
            )
        rust, sdk = processes
        first = read_json(rust)
        direct = read_json(sdk)
        check_sdk(direct, 1)
        fields = compare(first, direct)
        report["initial"] = {"fields": fields, "sdk": direct}
        report["available_fields"] = sum(
            field["availability"] == "available" for field in fields.values()
        )
        report["sdk_token_elevated"] = direct["token_elevated"]
        report["ordinary_user_read_verified"] = direct[
            "token_elevated"
        ] is False and report["available_fields"] == len(FIELDS)
        refreshes: list[dict[str, bool]] = []
        report["refreshes"] = refreshes
        for _ in range(3):
            time.sleep(0.03)
            send(rust, b"refresh\n")
            current = read_json(rust)
            require(current["static_info"] == first["static_info"])
            require(compare(current, direct) == fields)
            refreshes.append({"static_fields_unchanged": True})
        send(sdk, b"sample\n")
        after = read_json(sdk)
        check_sdk(after, 2)
        send(rust, b"rebuild\n")
        rebuilt = read_json(rust)
        report["rebuilt"] = {"fields": compare(rebuilt, after), "sdk": after}
        for process in processes:
            send(process, b"quit\n")
        for process in processes:
            require(process.wait(timeout=5) == 0)
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()


def run(output: Path) -> int:
    report: dict[str, Any] = {
        "status": "failed",
        "platform": platform.system(),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "limitations": [
            "Six OS registry summaries, not firmware authenticity or a raw SMBIOS table",
            "Token elevation recorded; elevated access does not prove ordinary-user access",
            "No real ACL, missing BIOS key, UWP sandbox or simultaneous registry mutation experiment",
            "Sequential SDK and Rust reads are not an atomic snapshot; OEM text may be inaccurate or identifying",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    code = 1
    try:
        collect(report)
        report["status"] = "passed"
        code = 0
    except KeyboardInterrupt:
        report["error"] = "interrupted"
        code = 130
    except Exception:
        report["error"] = "validation_failed"
    finally:
        output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print(f"Windows hardware summary SDK and cache: {report['status']}")
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "target/windows-hardware-summary-evidence.json",
    )
    return run(parser.parse_args().output)


if __name__ == "__main__":
    raise SystemExit(main())
