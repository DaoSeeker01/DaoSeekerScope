"""Exercise the production CLI against kernel-enforced Linux filesystem failures.

DMI contents are synthetic fixtures mounted at the real backend path. CPU/memory
come from the container environment, except in the deliberately empty /proc case.
Requires a local Docker daemon; never starts services or collects real identifiers.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from native_smoke import ROOT, ValidationFailure, decode, digest, run

# Official Ubuntu 24.04 linux/amd64 manifest, resolved from the registry on 2026-10-09.
IMAGE = "ubuntu@sha256:f610ab94648195aa356059f5b41d6085c9d4d903c072430cdd1af7bdb646106b"
FIXTURE_SERIAL = "Synthetic-DMI-Serial"
DMI_FIELDS = {
    "system.device.model": "product_name",
    "system.device.vendor": "sys_vendor",
    "system.motherboard.vendor": "board_vendor",
    "system.motherboard.model": "board_name",
    "system.firmware.vendor": "bios_vendor",
    "system.firmware.version": "bios_version",
}
FIXTURE_VALUES = {name: f"Fixture-{name}" for name in DMI_FIELDS.values()}
SCENARIOS = (
    "readable_dmi",
    "missing_dmi",
    "denied_dmi",
    "mixed_dmi",
    "authorized_serial",
    "denied_serial",
    "empty_proc_inputs",
)


def observation(snapshot: dict[str, Any], field: str) -> dict[str, Any]:
    node = (
        snapshot["static_info"] if field.startswith("system.") else snapshot["dynamic"]
    )
    for part in field.split("."):
        node = node[part]
    if not isinstance(node, dict):
        raise ValidationFailure("snapshot: malformed")
    return node


def expect(
    snapshot: dict[str, Any],
    field: str,
    availability: str,
    reason: str | None,
    source: str,
    value: Any = None,
) -> None:
    observed = observation(snapshot, field)
    if (
        observed["availability"] != availability
        or observed["reason"] != reason
        or observed["source"] != source
        or observed["value"] != value
        or (
            availability == "available"
            and (
                type(observed["observed_at"]) is not int or observed["observed_at"] <= 0
            )
        )
        or (availability != "available" and observed["observed_at"] is not None)
    ):
        raise ValidationFailure(f"snapshot: unexpected_observation:{field}")
    cap = next((cap for cap in snapshot["capabilities"] if cap["field"] == field), None)
    expected_level = "restricted" if availability == "restricted" else "supported"
    if not cap or (
        cap["level"] != expected_level
        or cap["reason"] != reason
        or cap["source"] != source
    ):
        raise ValidationFailure(f"snapshot: unexpected_capability:{field}")


def validate_snapshot(snapshot: dict[str, Any], scenario: str) -> dict[str, Any]:
    """Strict expectations, independent of whether a failed read returns exit 0."""
    import jsonschema

    schema = json.loads(
        (ROOT / "docs/schema/snapshot-v1.schema.json").read_text("utf-8")
    )
    try:
        jsonschema.Draft202012Validator(schema).validate(snapshot)
        if snapshot["schema_version"] != 1 or snapshot["issues"]:
            raise ValidationFailure("snapshot: backend_failure")
        for field, name in DMI_FIELDS.items():
            state = "available"
            reason: str | None = None
            expected_value: str | None = FIXTURE_VALUES[name]
            if scenario == "missing_dmi":
                state, reason, expected_value = "unavailable", "not_present", None
            elif scenario == "denied_dmi":
                state, reason, expected_value = "restricted", "permission_denied", None
            elif scenario == "mixed_dmi":
                state, reason, expected_value = {
                    "product_name": ("unavailable", "invalid_data", None),
                    "sys_vendor": ("restricted", "permission_denied", None),
                    "board_vendor": ("available", None, FIXTURE_VALUES[name]),
                    "board_name": ("unavailable", "not_present", None),
                    "bios_vendor": ("unavailable", "invalid_data", None),
                    "bios_version": ("unavailable", "invalid_data", None),
                }[name]
            expect(snapshot, field, state, reason, "sysfs", expected_value)
        serial_field = "system.device.serial_number"
        if scenario == "authorized_serial":
            expect(snapshot, serial_field, "available", None, "sysfs", FIXTURE_SERIAL)
        elif scenario == "denied_serial":
            expect(snapshot, serial_field, "restricted", "permission_denied", "sysfs")
        else:
            expect(snapshot, serial_field, "restricted", "privacy_redacted", "custom")
        core_fields = (
            "system.os.name",
            "system.cpu.brand",
            "system.cpu.logical_count",
            "system.memory.total_usable_bytes",
            "memory_available_bytes",
        )
        for field in core_fields:
            observed = observation(snapshot, field)
            memory = field in (
                "system.memory.total_usable_bytes",
                "memory_available_bytes",
            )
            source = "procfs" if memory else "sysinfo"
            reason = "invalid_data" if memory else "unknown"
            if (
                scenario in ("empty_proc", "empty_proc_inputs")
                and field != "system.os.name"
            ):
                if (
                    observed["availability"] != "unavailable"
                    or observed["value"] is not None
                    or observed["reason"] != reason
                    or observed["source"] != source
                    or observed["observed_at"] is not None
                ):
                    raise ValidationFailure(f"snapshot: fabricated_proc_value:{field}")
            else:
                value = observed["value"]
                valid = (
                    isinstance(value, str) and bool(value.strip())
                    if field in ("system.os.name", "system.cpu.brand")
                    else type(value) is int and value > 0
                )
                if observed["availability"] != "available" or not valid:
                    raise ValidationFailure(f"snapshot: core_read_failed:{field}")
            core_cap = next(
                (cap for cap in snapshot["capabilities"] if cap["field"] == field), None
            )
            if not core_cap or (
                core_cap["level"] != ("supported" if memory else "partial")
                or core_cap["source"] != source
                or core_cap["reason"] != observed["reason"]
            ):
                raise ValidationFailure(f"snapshot: unexpected_capability:{field}")
        selected = {
            field: observation(snapshot, field) for field in (*DMI_FIELDS, *core_fields)
        }
        # Even the synthetic serial is never written to evidence or diagnostics.
        selected[serial_field] = {
            key: value
            for key, value in observation(snapshot, serial_field).items()
            if key != "value"
        }
        selected[serial_field]["value_recorded"] = False
        return {
            "observations": selected,
            "capabilities": [
                cap for cap in snapshot["capabilities"] if cap["field"] in selected
            ],
            "schema_validated": True,
            "synthetic_dmi": True,
        }
    except (KeyError, TypeError, StopIteration, jsonschema.ValidationError) as error:
        raise ValidationFailure("snapshot: malformed_or_schema_invalid") from error


def fixture(root: Path, scenario: str) -> Path:
    root.chmod(0o755)
    dmi = root / "class/dmi/id"
    if scenario == "missing_dmi":
        return dmi
    dmi.mkdir(parents=True)
    for name, value in {**FIXTURE_VALUES, "product_serial": FIXTURE_SERIAL}.items():
        path = dmi / name
        path.write_text(value + "\n", encoding="utf-8")
        path.chmod(0o644)
    if scenario == "denied_dmi":
        dmi.chmod(0)
    elif scenario == "mixed_dmi":
        (dmi / "product_name").write_bytes(b"\xff")
        (dmi / "sys_vendor").chmod(0)
        (dmi / "board_name").unlink()
        (dmi / "bios_vendor").write_text("To Be Filled By O.E.M.\n", encoding="utf-8")
        (dmi / "bios_version").write_bytes(b"x" * 4097)
    elif scenario == "denied_serial":
        (dmi / "product_serial").chmod(0)
    return dmi


def check_config(config: dict[str, Any]) -> dict[str, Any]:
    """Verify the daemon configuration, without saving bind paths or container IDs."""
    host = config["host"]
    if (
        config["user"] != "65534:65534"
        or not host["ReadonlyRootfs"]
        or host["NetworkMode"] != "none"
        or "ALL" not in host["CapDrop"]
        or "no-new-privileges=true" not in host["SecurityOpt"]
        or host["Memory"] != 256 * 1024 * 1024
        or host["MemorySwap"] != host["Memory"]
        or host["PidsLimit"] != 32
        or host["NanoCpus"] != 1_000_000_000
        or not any(
            limit["Name"] == "nofile" and limit["Soft"] == 64 and limit["Hard"] == 64
            for limit in host["Ulimits"]
        )
        or any(mount["RW"] for mount in config["mounts"])
    ):
        raise ValidationFailure("container: unexpected_configuration")
    return {
        "user": config["user"],
        **{
            key: host[key]
            for key in (
                "ReadonlyRootfs",
                "NetworkMode",
                "CapDrop",
                "SecurityOpt",
                "Memory",
                "MemorySwap",
                "PidsLimit",
                "NanoCpus",
            )
        },
    }


def execute(cli: Path, report: dict[str, Any]) -> None:
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        raise ValidationFailure("platform: linux_amd64_required")
    if not cli.is_file():
        raise ValidationFailure("cli: artifact_missing")
    report["artifact_sha256"] = {
        "cli": digest(cli),
        "cargo_lock": digest(ROOT / "Cargo.lock"),
    }
    report["git_revision"] = run(["git", "rev-parse", "HEAD"], "git").decode().strip()
    report["git_dirty"] = bool(run(["git", "status", "--porcelain"], "git"))
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
    for scenario in (*SCENARIOS, "empty_proc"):
        item: dict[str, Any] = {"status": "running"}
        if scenario == "empty_proc":
            report["runtime_probes"][scenario] = item
        else:
            report["scenarios"][scenario] = item
        name = "dscope-negative-" + uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix="dscope-container-") as temporary:
            sys_root = Path(temporary) / "sys"
            sys_root.mkdir()
            dmi = fixture(sys_root, scenario)
            command = [
                "docker",
                "create",
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
                f"type=bind,source={cli},target=/opt/dscope,readonly",
                "--mount",
                f"type=bind,source={sys_root},target=/sys,readonly",
            ]
            if scenario == "empty_proc":
                proc_root = Path(temporary) / "proc"
                proc_root.mkdir(mode=0o755)
                command.extend(
                    ["--mount", f"type=bind,source={proc_root},target=/proc,readonly"]
                )
            elif scenario == "empty_proc_inputs":
                empty_file = Path(temporary) / "empty"
                empty_file.write_bytes(b"")
                empty_file.chmod(0o644)
                for proc_file in ("stat", "cpuinfo", "meminfo"):
                    command.extend(
                        [
                            "--mount",
                            f"type=bind,source={empty_file},target=/proc/{proc_file},readonly",
                        ]
                    )
            command.extend([IMAGE, "/opt/dscope", "--json"])
            if scenario in ("authorized_serial", "denied_serial"):
                command.extend(["--include-sensitive", "--authorized"])
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
                item["configuration"] = check_config(config)
                started = subprocess.run(
                    ["docker", "start", "--attach", name],
                    capture_output=True,
                    check=False,
                    timeout=60,
                )
                # docker start's own exit status is not the container process status.
                state = decode(
                    run(
                        ["docker", "inspect", "--format", "{{json .State}}", name],
                        "container_state",
                    )
                )
                item["exit_code"] = state["ExitCode"]
                item["docker_start_exit_code"] = started.returncode
                item["process_started"] = not state["StartedAt"].startswith("0001-")
                if (
                    started.returncode != 0
                    or state["Running"]
                    or state["OOMKilled"]
                    or state["ExitCode"] != 0
                ):
                    diagnostic = (
                        started.stderr.lower() + str(state["Error"]).lower().encode()
                    )
                    item["failure_category"] = next(
                        (
                            category
                            for text, category in [
                                (b"error mounting", "runtime_mount_error"),
                                (b"oci runtime", "oci_runtime_error"),
                                (b"stack", "process_stack_error"),
                                (b"panicked", "process_panic"),
                                (b"collection error", "collection_error"),
                            ]
                            if text in diagnostic
                        ),
                        "process_error",
                    )
                    if (
                        scenario == "empty_proc"
                        and not item["process_started"]
                        and item["failure_category"] == "runtime_mount_error"
                    ):
                        # The CLI never started: this is a Docker boundary observation,
                        # explicitly excluded from successful backend-read scenarios.
                        item["status"] = "not_run"
                        item["probe_result"] = "runtime_rejected_mount"
                        continue
                    raise ValidationFailure("container: cli_failed")
                item.update(validate_snapshot(decode(started.stdout.strip()), scenario))
                item["status"] = "passed"
            finally:
                # Restore fixture access even when Docker removal itself times out.
                if scenario == "denied_dmi":
                    dmi.chmod(0o755)
                cleanup = subprocess.run(
                    ["docker", "rm", "--force", name],
                    capture_output=True,
                    check=False,
                    timeout=15,
                )
                if cleanup.returncode != 0:
                    raise ValidationFailure("container: cleanup_failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, default=ROOT / "target/debug/dscope")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/linux-container-evidence.json"
    )
    args = parser.parse_args()
    report: dict[str, Any] = {
        "report_version": 1,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "execution_platform": {
            "os": platform.system(),
            "architecture": platform.machine(),
        },
        "overall": "incomplete",
        "image_reference": IMAGE,
        "scenarios": {scenario: {"status": "not_run"} for scenario in SCENARIOS},
        "runtime_probes": {},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        execute(args.cli.resolve(), report)
        if any(item["status"] != "passed" for item in report["scenarios"].values()):
            raise ValidationFailure("scenarios: incomplete")
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
        for item in report["scenarios"].values():
            if item["status"] == "running":
                item["status"] = "failed"
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Linux container smoke: {report['overall']}")
    return 0 if report["overall"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
