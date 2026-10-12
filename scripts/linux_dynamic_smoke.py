"""Refresh one production Hardware across changing, read-only proc/stat fixtures.

Only the host mutates its own synthetic file; the nonroot container cannot write it.
Reports retain CPU observations, not full hardware snapshots or identifiers.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import platform
import select
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from linux_container_smoke import IMAGE, check_config
from native_smoke import MAX_JSON_BYTES, ROOT, ValidationFailure, decode, digest, run


def stat(user: int, idle: int) -> bytes:
    return f"cpu {user} 0 0 {idle} 0 0 0 0 0 0\ncpu0 {user} 0 0 {idle} 0 0 0 0 0 0\n".encode()


def verify(
    snapshot: dict[str, Any], state: str, reason: str | None, value: float | None
) -> dict[str, Any]:
    import jsonschema

    schema = json.loads(
        (ROOT / "docs/schema/snapshot-v1.schema.json").read_text("utf-8")
    )
    try:
        jsonschema.Draft202012Validator(schema).validate(snapshot)
        item = snapshot["dynamic"]["cpu_usage_percent"]
        if (
            item["availability"] != state
            or item["reason"] != reason
            or item["value"] != value
            or (state == "available" and type(item["observed_at"]) is not int)
            or (state != "available" and item["observed_at"] is not None)
        ):
            raise ValidationFailure("cpu: unexpected_observation")
        # Baseline failure evidence also accepts sysinfo provenance; the repaired
        # production path is separately required to report procfs below.
        if item["source"] not in ("sysinfo", "procfs"):
            raise ValidationFailure("cpu: unexpected_source")
        cap = next(
            cap
            for cap in snapshot["capabilities"]
            if cap["field"] == "cpu_usage_percent"
        )
        if cap["source"] != item["source"] or cap["reason"] != reason:
            raise ValidationFailure("cpu: capability_metadata")
        if state == "restricted" and cap["level"] != "restricted":
            raise ValidationFailure("cpu: capability_restriction")
        if (
            item["source"] == "procfs"
            and state != "restricted"
            and cap["level"] != "supported"
        ):
            raise ValidationFailure("cpu: capability_recovery")
        serial = snapshot["static_info"]["system"]["device"]["serial_number"]
        if serial["value"] is not None or serial["reason"] != "privacy_redacted":
            raise ValidationFailure("snapshot: privacy")
        memory = snapshot["dynamic"]["memory_available_bytes"]
        if memory["availability"] != "available" or type(memory["value"]) is not int:
            raise ValidationFailure("snapshot: healthy_memory")
        if snapshot["issues"]:
            raise ValidationFailure("snapshot: backend_issue")
        return {
            "cpu": item,
            "capability": cap,
            "healthy_memory": True,
            "schema_validated": True,
        }
    except (KeyError, TypeError, StopIteration, jsonschema.ValidationError) as error:
        raise ValidationFailure("snapshot: malformed") from error


def receive(process: subprocess.Popen[bytes]) -> dict[str, Any]:
    if process.stdout is None or not select.select([process.stdout], [], [], 10)[0]:
        raise ValidationFailure("probe: response_timeout")
    # The probe flushes one JSON line. A partial line also has a hard timeout:
    # read individual bytes only while select says data is present.
    data = bytearray()
    deadline = time.monotonic() + 10
    while len(data) <= MAX_JSON_BYTES:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
            raise ValidationFailure("probe: response_timeout")
        byte = process.stdout.read(1)
        if byte == b"\n":
            return decode(bytes(data))
        if not byte:
            raise ValidationFailure("probe: unexpected_eof")
        data.extend(byte)
    raise ValidationFailure("probe: output_limit")


def execute(
    probe: Path,
    report: dict[str, Any],
    *,
    inputs: dict[str, bytes] | None = None,
    observe: Callable[[subprocess.Popen[bytes], dict[str, Path], dict[str, Any]], None]
    | None = None,
    power_supply: bool = False,
    hwmon: bool = False,
    storage: bool = False,
) -> None:
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        raise ValidationFailure("platform: linux_amd64_required")
    if not probe.is_file():
        raise ValidationFailure("probe: artifact_missing")
    report["git_revision"] = run(["git", "rev-parse", "HEAD"], "git").decode().strip()
    report["git_dirty"] = bool(run(["git", "status", "--porcelain"], "git"))
    report["artifact_sha256"] = {
        "probe": digest(probe),
        "cargo_lock": digest(ROOT / "Cargo.lock"),
    }
    report["docker_version"] = (
        run(["docker", "version", "--format", "{{.Server.Version}}"], "docker")
        .decode()
        .strip()
    )
    run(["docker", "pull", IMAGE], "image_pull")
    report["image_id"] = (
        run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE],
            "image_inspect",
        )
        .decode()
        .strip()
    )
    name = "dscope-dynamic-" + uuid.uuid4().hex
    process = None
    with tempfile.TemporaryDirectory(prefix="dscope-dynamic-") as temporary:
        root = Path(temporary)
        root.chmod(0o755)
        paths = {}
        for file, payload in (inputs or {"stat": stat(100, 100)}).items():
            if file not in ("stat", "meminfo", "uptime"):
                raise ValidationFailure("fixture: unsupported_path")
            paths[file] = root / file
            paths[file].write_bytes(payload)
            paths[file].chmod(0o644)
        if power_supply:
            paths["power_supply"] = root / "sys/class/power_supply"
            paths["power_supply"].mkdir(parents=True, mode=0o755)
        if hwmon:
            paths["hwmon"] = root / "sys/class/hwmon"
            paths["hwmon"].mkdir(parents=True, mode=0o755)
        if storage:
            paths["block"] = root / "sys/block"
            paths["block"].mkdir(parents=True, mode=0o755)
        command = [
            "docker",
            "create",
            "--interactive",
            "--name",
            name,
            "--user",
            "65534:65534",
            "--read-only",
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges=true",
            "--memory",
            "256m",
            "--memory-swap",
            "256m",
            "--pids-limit",
            "32",
            "--cpus",
            "1",
            "--ulimit",
            "nofile=64:64",
            "--mount",
            f"type=bind,source={probe},target=/opt/probe,readonly",
        ]
        if power_supply or hwmon or storage:
            command.extend(
                ["--mount", f"type=bind,source={root / 'sys'},target=/sys,readonly"]
            )
        for file, path in paths.items():
            if file in ("power_supply", "hwmon", "block"):
                continue
            command.extend(
                ["--mount", f"type=bind,source={path},target=/proc/{file},readonly"]
            )
        command.extend([IMAGE, "/opt/probe"])
        try:
            run(command, "container_create")
            config = decode(
                run(
                    [
                        "docker",
                        "inspect",
                        "--format",
                        '{"user":{{json .Config.User}},"host":{{json .HostConfig}},"mounts":{{json .Mounts}}}',
                        name,
                    ],
                    "container_inspect",
                )
            )
            report["configuration"] = check_config(config)
            process = subprocess.Popen(
                ["docker", "start", "--attach", "--interactive", name],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )

            if observe is not None:
                observe(process, paths, report)
            else:
                path = paths["stat"]

                def sample(
                    label: str,
                    state: str,
                    reason: str | None,
                    value: float | None,
                    payload: bytes | None = None,
                    mode: int = 0o644,
                ) -> None:
                    if payload is not None:
                        path.chmod(0o644)
                        # Preserve the bind-mounted inode; do not rename a new file.
                        path.write_bytes(payload)
                        path.chmod(mode)
                        time.sleep(0.35)
                        if process is None or process.stdin is None:
                            raise ValidationFailure("probe: missing_stdin")
                        process.stdin.write(b"refresh\n")
                        process.stdin.flush()
                    snapshot = receive(process)
                    item = {
                        "status": "failed",
                        "cpu": snapshot["dynamic"]["cpu_usage_percent"],
                    }
                    report["samples"][label] = item
                    item.update(verify(snapshot, state, reason, value))
                    item["status"] = "passed"

                sample("initial", "unavailable", "temporarily_unavailable", None)
                sample("ready", "available", None, 50.0, stat(150, 150))
                sample("empty", "unavailable", "invalid_data", None, b"")
                sample(
                    "recovery_baseline",
                    "unavailable",
                    "temporarily_unavailable",
                    None,
                    stat(200, 200),
                )
                sample("recovery_ready", "available", None, 50.0, stat(250, 250))
                sample(
                    "permission_denied",
                    "restricted",
                    "permission_denied",
                    None,
                    stat(300, 300),
                    0,
                )
                sample(
                    "permission_recovery",
                    "unavailable",
                    "temporarily_unavailable",
                    None,
                    stat(350, 350),
                )
                sample("permission_ready", "available", None, 50.0, stat(400, 400))
                sample(
                    "unchanged",
                    "unavailable",
                    "temporarily_unavailable",
                    None,
                    stat(400, 400),
                )
                sample(
                    "counter_reset", "unavailable", "invalid_data", None, stat(100, 100)
                )
                sample("reset_ready", "available", None, 50.0, stat(150, 150))
                sample(
                    "invalid_utf8", "unavailable", "invalid_data", None, b"cpu \xff\n"
                )
                sample("oversize", "unavailable", "invalid_data", None, b"x" * 4097)
                sample(
                    "final_baseline",
                    "unavailable",
                    "temporarily_unavailable",
                    None,
                    stat(200, 200),
                )
                sample("genuine_zero", "available", None, 0.0, stat(200, 300))
                if any(
                    item["cpu"]["source"] != "procfs"
                    for item in report["samples"].values()
                ):
                    raise ValidationFailure("cpu: repaired_source_required")
            if process.stdin is None:
                raise ValidationFailure("probe: missing_stdin")
            process.stdin.write(b"quit\n")
            process.stdin.flush()
            process.stdin.close()
            report["docker_exit_code"] = process.wait(timeout=10)
            state = decode(
                run(
                    ["docker", "inspect", "--format", "{{json .State}}", name],
                    "container_state",
                )
            )
            report["process_exit_code"] = state["ExitCode"]
            report["process_started"] = not state["StartedAt"].startswith("0001-")
            if (
                process.returncode != 0
                or state["ExitCode"] != 0
                or state["Running"]
                or state["OOMKilled"]
                or not report["process_started"]
            ):
                raise ValidationFailure("probe: process_failed")
        finally:
            try:
                for file, path in paths.items():
                    if path.exists():
                        path.chmod(
                            0o755 if file in ("power_supply", "hwmon") else 0o644
                        )
            finally:
                try:
                    cleanup = subprocess.run(
                        ["docker", "rm", "--force", name],
                        capture_output=True,
                        check=False,
                        timeout=15,
                    )
                    if cleanup.returncode != 0:
                        raise ValidationFailure("container: cleanup_failed")
                finally:
                    if process is not None:
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=10)
                        for pipe in [process.stdin, process.stdout]:
                            if pipe is not None:
                                pipe.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe", type=Path, default=ROOT / "target/debug/examples/dynamic_probe"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/linux-dynamic-evidence.json"
    )
    args = parser.parse_args()
    report: dict[str, Any] = {
        "report_version": 1,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "overall": "incomplete",
        "image_reference": IMAGE,
        "synthetic_cpu_counters": True,
        "samples": {},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        execute(args.probe.resolve(), report)
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
    print(f"Linux dynamic smoke: {report['overall']}")
    return 0 if report["overall"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
