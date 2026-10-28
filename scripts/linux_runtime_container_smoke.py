"""Run the same verified Linux CLI/SDK candidates in pinned older userlands."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import uuid

import jsonschema

from cli_bundle import (
    ROOT,
    LINUX_TARGET,
    digest,
    require,
    require_runtime_host,
    verify_bundle,
)
from cli_bundle_smoke import install
from elf_inspect import inspect_elf, linux_environment
from native_smoke import check_snapshot

PROFILES = {
    "bookworm": {
        "image": "python@sha256:f576b530293e74140ea91d262232648d5c4f45640a95ec447757701bfcacf034",
        "config_digest": "sha256:2e6b5bbf5b2f372ef9b208e7c7c300675be97a6dc1bbe7e3ac0b9c20035fd70e",
        "glibc": "2.36",
        "debian": "12",
        "python": "3.13.13",
        "expected": "runs",
    },
    "bullseye": {
        "image": "python@sha256:4ea2e567da526afcd5655339f71295ca6ef72271ff6123bb5c7144ae8fdc1692",
        "config_digest": "sha256:932831e2e7dc0aebbabca90d6c78087538e5c3ecf38151069ab418d1ec4532d2",
        "glibc": "2.31",
        "debian": "11",
        "python": "3.13.5",
        "expected": "loader_rejects",
    },
}
WORK_BYTES = 64 * 1024 * 1024
WORK_RESERVE = 16 * 1024 * 1024


def installation_budget(
    file_sizes: Sequence[int], directories: int, block_bytes: int = 4096
) -> dict[str, int]:
    """Budget rounded file allocations and directories, retaining workspace reserve."""
    require(
        0 < len(file_sizes) <= 2048
        and type(directories) is int
        and 0 <= directories <= 2048
        and type(block_bytes) is int
        and 512 <= block_bytes <= 65536
        and block_bytes & (block_bytes - 1) == 0
        and all(type(size) is int and size >= 0 for size in file_sizes),
        "runtime_install_sizes",
    )
    allocated = sum(
        (size + block_bytes - 1) // block_bytes * block_bytes for size in file_sizes
    )
    allocated += directories * block_bytes
    require(allocated <= WORK_BYTES - WORK_RESERVE, "runtime_install_capacity")
    return {
        "capacity_bytes": WORK_BYTES,
        "reserve_bytes": WORK_RESERVE,
        "logical_bytes": sum(file_sizes),
        "estimated_copy_bytes": allocated,
        "allocation_block_bytes": block_bytes,
        "files": len(file_sizes),
        "directories": directories,
    }


def run(arguments: list[str], *, timeout: int = 60) -> bytes:
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        result = subprocess.run(
            arguments,
            cwd=ROOT,
            stdout=stdout,
            stderr=stderr,
            env=linux_environment(os.environ),
            timeout=timeout,
        )
        require(result.returncode == 0, "runtime_tool_failed")
        stdout.seek(0)
        output = stdout.read(4 * 1024 * 1024 + 1)
    require(len(output) <= 4 * 1024 * 1024, "runtime_output_limit")
    return output


def checksum(archive: Path) -> str:
    with (archive.parent / "SHA256SUMS").open("rb") as source:
        data = source.read(1025)
    require(len(data) <= 1024, "checksum_limit")
    fields = data.decode("ascii").split()
    require(len(fields) == 2 and fields[1] == archive.name, "checksum_sidecar")
    return fields[0]


def container_arguments(
    name: str, stage: Path, profile: dict[str, str], label: str
) -> list[str]:
    require("," not in str(stage), "unsupported_bind_path")
    return [
        "docker",
        "create",
        "--name",
        name,
        "--platform",
        "linux/amd64",
        "--user",
        "65534:65534",
        "--read-only",
        "--env",
        "LC_ALL=C",
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
        "--tmpfs",
        "/work:rw,exec,nosuid,nodev,size=64m,uid=65534,gid=65534,mode=0700",
        "--mount",
        f"type=bind,source={stage},target=/input,readonly",
        profile["image"],
        "python",
        "-B",
        "/input/probe.py",
        f"/input/{label}.json",
    ]


def validate_config(value: dict[str, Any]) -> dict[str, Any]:
    host = value["HostConfig"]
    require(
        value["Config"]["User"] == "65534:65534"
        and not host["Privileged"]
        and host["ReadonlyRootfs"]
        and host["NetworkMode"] == "none",
        "runtime_container_configuration",
    )
    require(
        "ALL" in host["CapDrop"] and "no-new-privileges=true" in host["SecurityOpt"],
        "runtime_container_privileges",
    )
    require(
        host["Memory"] == host["MemorySwap"] == 256 * 1024 * 1024
        and host["PidsLimit"] == 32
        and host["NanoCpus"] == 1_000_000_000,
        "runtime_container_resources",
    )
    require(
        any(
            item["Name"] == "nofile" and item["Soft"] == item["Hard"] == 64
            for item in host["Ulimits"]
        ),
        "runtime_container_resources",
    )
    tmpfs = host["Tmpfs"]
    require(
        set(tmpfs) == {"/work"}
        and set(tmpfs["/work"].split(","))
        == {
            "rw",
            "exec",
            "nosuid",
            "nodev",
            "size=64m",
            "uid=65534",
            "gid=65534",
            "mode=0700",
        },
        "runtime_container_tmpfs",
    )
    binds = [mount for mount in value["Mounts"] if mount["Type"] == "bind"]
    require(
        len(binds) == 1
        and binds[0]["Destination"] == "/input"
        and not binds[0]["RW"]
        and all(
            (m["Type"] == "bind" and m["Destination"] == "/input" and not m["RW"])
            or (m["Type"] == "tmpfs" and m["Destination"] == "/work")
            for m in value["Mounts"]
        ),
        "runtime_container_mounts",
    )
    return {
        "user": value["Config"]["User"],
        "network": "none",
        "readonly_root": True,
        "readonly_candidate_mount": True,
        "writable_tmpfs": "/work",
        "memory_bytes": host["Memory"],
        "pids": 32,
        "cpus": 1,
    }


def validate_result(
    value: dict[str, Any], profile: dict[str, str], hashes: dict[str, str], version: str
) -> dict[str, Any]:
    require(
        value["overall"] == "passed"
        and value["expected"] == profile["expected"]
        and not value["rebuilt_in_container"],
        "runtime_probe_contract",
    )
    runtime = value["runtime"]
    require(
        all(runtime[key] == profile[key] for key in ("glibc", "debian", "python"))
        and runtime["machine"] == "x86_64"
        and runtime["uid"] == 65534,
        "runtime_identity",
    )
    require(value["binary_sha256"] == hashes, "runtime_binary_changed")
    require(
        not runtime["cargo_available"] and not runtime["rustc_available"],
        "runtime_build_toolchain_present",
    )
    calls = value["calls"]
    storage = value["installation_storage"]
    require(
        storage["capacity_bytes"] == WORK_BYTES
        and storage["reserve_bytes"] == WORK_RESERVE
        and WORK_RESERVE
        <= storage["available_after_copy_bytes"]
        <= storage["available_before_copy_bytes"]
        <= WORK_BYTES,
        "runtime_install_storage",
    )
    result: dict[str, Any] = {
        "status": "passed",
        "expected": profile["expected"],
        "runtime": runtime,
        "binary_sha256": hashes,
        "installed_payload_files": value["installed_payload_files"],
        "rebuilt_in_container": False,
        "installation_storage": storage,
    }
    if profile["expected"] == "runs":
        require(
            set(calls) == {"cli_version", "cli_json", "c", "python"}, "runtime_calls"
        )
        require(
            all(
                item["exit_code"] == 0 and item["stderr_bytes"] == 0
                for item in calls.values()
            ),
            "runtime_child_failed",
        )
        require(
            calls["cli_version"]["stdout"].strip() == f"dscope {version}",
            "runtime_cli_version",
        )
        require(
            calls["python"]["stdout"].strip()
            == "ctypes: 100 real collect/free cycles, stale copy rejection, privacy and schema passed",
            "runtime_python_contract",
        )
        schema = json.loads((ROOT / "docs/schema/snapshot-v1.schema.json").read_bytes())
        for label in ("cli_json", "c"):
            snapshot = json.loads(calls[label]["stdout"])
            jsonschema.Draft202012Validator(schema).validate(snapshot)
            check_snapshot(snapshot)
        result.update(
            snapshot_schema_and_default_privacy=True,
            python_collect_free_cycles=100,
            child_processes=4,
            output_sha256={
                label: digest(item["stdout"].encode()) for label, item in calls.items()
            },
        )
    else:
        require(
            set(calls) == {"cli", "c", "ctypes_load"}
            and value["collection_started"] is False,
            "runtime_negative_contract",
        )
        for label in ("cli", "c"):
            require(
                calls[label]["exit_code"] > 0
                and bool(calls[label]["missing_glibc_versions"]),
                "runtime_loader_failure_required",
            )
        require(
            calls["ctypes_load"]["rejected"]
            and bool(calls["ctypes_load"]["missing_glibc_versions"]),
            "runtime_loader_failure_required",
        )
        for item in calls.values():
            versions = item["missing_glibc_versions"]
            require(
                isinstance(versions, list) and 0 < len(versions) <= 64,
                "runtime_loader_versions",
            )
            for name in versions:
                require(
                    isinstance(name, str)
                    and len(name) <= 128
                    and re.fullmatch(r"GLIBC_[0-9]+(?:\.[0-9]+)+", name) is not None,
                    "runtime_loader_versions",
                )
                require(
                    tuple(map(int, name.removeprefix("GLIBC_").split(".")))
                    > tuple(map(int, profile["glibc"].split("."))),
                    "runtime_loader_versions",
                )
        result.update(
            collection_started=False,
            child_processes=2,
            missing_glibc_versions={
                label: item["missing_glibc_versions"] for label, item in calls.items()
            },
        )
    return result


def validate_loader_requirements(
    calls: dict[str, Any], requirements: dict[str, Any]
) -> None:
    """Allow only the inspected candidate and its known packaged SDK dependency."""
    closure = {
        "cli": ("cli",),
        "c": ("consumer", "library"),
        "ctypes_load": ("library",),
    }
    for call, binaries in closure.items():
        declared = {
            version
            for binary in binaries
            for versions in requirements[binary]["required_symbol_versions"].values()
            for version in versions
        }
        require(
            set(calls[call]["missing_glibc_versions"]) <= declared,
            "runtime_unexpected_loader_version",
        )


def run_profile(
    stage: Path,
    label: str,
    hashes: dict[str, str],
    version: str,
    requirements: dict[str, Any],
    item: dict[str, Any],
) -> None:
    """Own one named container and remove it even after timeout or validation failure."""
    profile = PROFILES[label]
    run(
        ["docker", "pull", "--platform", "linux/amd64", profile["image"]],
        timeout=180,
    )
    image = json.loads(run(["docker", "image", "inspect", profile["image"]]))[0]
    require(
        image["Id"] == profile["config_digest"]
        and image["Architecture"] == "amd64"
        and image["Os"] == "linux",
        "runtime_image_identity",
    )
    item["image_id"] = image["Id"]
    name = "dscope-runtime-" + uuid.uuid4().hex
    created = False
    try:
        item["phase"] = "create"
        run(container_arguments(name, stage, profile, label))
        created = True
        item["phase"] = "configuration"
        inspected = json.loads(run(["docker", "inspect", name]))[0]
        item["configuration"] = validate_config(inspected)
        item["phase"] = "start"
        raw = run(["docker", "start", "--attach", name], timeout=300)
        state = json.loads(
            run(["docker", "inspect", "--format", "{{json .State}}", name])
        )
        require(
            not state["Running"]
            and not state["OOMKilled"]
            and state["ExitCode"] == 0
            and not state["StartedAt"].startswith("0001-"),
            "runtime_container_state",
        )
        item["phase"] = "result"
        probe_result = json.loads(raw)
        if probe_result.get("overall") != "passed":
            item["probe_failure"] = probe_result.get("failure", "runtime_probe_failed")
        item.update(validate_result(probe_result, profile, hashes, version))
        if profile["expected"] == "loader_rejects":
            validate_loader_requirements(probe_result["calls"], requirements)
        item["phase"] = "complete"
    except Exception:
        item["status"] = "failed"
        raise
    finally:
        try:
            run(["docker", "rm", "--force", name], timeout=15)
            item["container_removed"] = True
        except (ValueError, OSError, subprocess.TimeoutExpired):
            item["container_removed"] = False
            if created:
                item["status"] = "failed"
                raise ValueError("runtime_cleanup_failed") from None


def execute(cli_archive: Path, sdk_archive: Path, report: dict[str, Any]) -> None:
    require_runtime_host(LINUX_TARGET)
    source = run(["git", "rev-parse", "HEAD"]).decode().strip()
    require(not run(["git", "status", "--porcelain"]), "dirty_checkout")
    report["source_commit"] = source
    report["source_dirty"] = False
    endpoint = (
        run(["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"])
        .decode()
        .strip()
    )
    require(
        endpoint.startswith("unix://")
        and (
            not os.environ.get("DOCKER_HOST")
            or os.environ["DOCKER_HOST"].startswith("unix://")
        ),
        "local_docker_required",
    )
    report["docker_version"] = (
        run(["docker", "version", "--format", "{{.Server.Version}}"]).decode().strip()
    )
    payloads = {
        "cli": verify_bundle(cli_archive, checksum(cli_archive)),
        "sdk": verify_bundle(sdk_archive, checksum(sdk_archive)),
    }
    manifests = {
        key: json.loads(value["manifest.json"]) for key, value in payloads.items()
    }
    require(
        all(
            m["source_commit"] == source
            and not m["source_dirty"]
            and m["target"] == LINUX_TARGET
            for m in manifests.values()
        ),
        "runtime_candidate_source",
    )
    require(
        manifests["cli"].get("product", "cli") == "cli"
        and manifests["sdk"]["product"] == "ffi_sdk"
        and manifests["cli"]["version"] == manifests["sdk"]["version"],
        "runtime_candidate_product",
    )
    report["payload_bytes"] = {
        product: sum(map(len, files.values())) for product, files in payloads.items()
    }
    with tempfile.TemporaryDirectory(
        prefix="runtime-candidates-", dir=ROOT / "target"
    ) as folder:
        stage = Path(folder)
        install(cli_archive, checksum(cli_archive), stage / "cli")
        install(sdk_archive, checksum(sdk_archive), stage / "sdk")
        sdk = stage / "sdk"
        (sdk / "bin").mkdir()
        consumer = sdk / "bin/c-example"
        run(
            [
                "cc",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-std=c11",
                str(sdk / "examples/collect.c"),
                "-L" + str(sdk / "lib"),
                "-ldaoseeker_scope_ffi",
                "-Wl,--enable-new-dtags",
                "-Wl,-rpath,$ORIGIN/../lib",
                "-o",
                str(consumer),
            ]
        )
        binaries = {
            "cli": stage / "cli/bin/dscope",
            "library": sdk / "lib/libdaoseeker_scope_ffi.so",
            "consumer": consumer,
        }
        hashes = {key: digest(path.read_bytes()) for key, path in binaries.items()}
        report["binary_sha256"] = hashes
        report["archive_sha256"] = {
            "cli": checksum(cli_archive),
            "sdk": checksum(sdk_archive),
        }
        report["elf_requirements"] = {
            key: inspect_elf(
                run(["readelf", "--wide", "--dynamic", "--version-info", str(path)]),
                consumer=key == "consumer",
            )
            for key, path in binaries.items()
        }
        shutil.copyfile(
            ROOT / "scripts/linux_runtime_container_probe.py", stage / "probe.py"
        )
        installed_paths = [
            path
            for product in ("cli", "sdk")
            for path in [stage / product, *(stage / product).rglob("*")]
        ]
        budget = installation_budget(
            [path.stat().st_size for path in installed_paths if path.is_file()],
            sum(path.is_dir() for path in installed_paths),
            getattr(os, "sysconf")("SC_PAGESIZE"),
        )
        report["work_budget"] = budget
        for label, profile in PROFILES.items():
            config = {
                **profile,
                "work_budget": budget,
                "binary_sha256": hashes,
                "manifests": {
                    key: digest(files["manifest.json"])
                    for key, files in payloads.items()
                },
            }
            (stage / f"{label}.json").write_text(json.dumps(config), encoding="utf-8")
        stage.chmod(0o755)
        for path in stage.rglob("*"):
            if path.is_dir():
                path.chmod(0o755)
            elif path.name not in ("dscope", "c-example"):
                path.chmod(0o644)
        consumer.chmod(0o755)
        for label, profile in PROFILES.items():
            item: dict[str, Any] = {
                "status": "running",
                "image": profile["image"],
                "phase": "pull",
            }
            report["profiles"][label] = item
            run_profile(
                stage,
                label,
                hashes,
                manifests["cli"]["version"],
                report["elf_requirements"],
                item,
            )
    require(
        run(["git", "rev-parse", "HEAD"]).decode().strip() == source
        and not run(["git", "status", "--porcelain"]),
        "runtime_source_changed",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cli_archive", type=Path)
    parser.add_argument("sdk_archive", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "target/linux-runtime-container-evidence.json",
    )
    options = parser.parse_args()
    report: dict[str, Any] = {
        "report_version": 1,
        "overall": "incomplete",
        "profiles": {},
        "physical_device_validation": False,
        "minimum_kernel_or_distribution_verified": False,
        "published": False,
    }
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(report) + "\n", encoding="utf-8")
    try:
        execute(options.cli_archive.resolve(), options.sdk_archive.resolve(), report)
        report["overall"] = "passed"
    except Exception as error:
        report["overall"] = "failed"
        code = (
            str(error) if isinstance(error, ValueError) else "runtime_validation_failed"
        )
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) is None:
            code = "runtime_validation_failed"
        report["failure"] = code
        for item in report["profiles"].values():
            if item["status"] == "running":
                item["status"] = "failed"
        print(
            f"Linux runtime validation failed: {code}; see the evidence report",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    finally:
        options.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Linux candidate older-userland runtime checks: passed")


if __name__ == "__main__":
    main()
