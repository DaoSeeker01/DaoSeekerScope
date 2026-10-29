"""Standard-library-only runner inside an isolated candidate runtime container."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

MAX_OUTPUT = 1024 * 1024


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def file_hash(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def missing_glibc_versions(message: bytes) -> list[str]:
    """Accept loader version diagnostics, not arbitrary nonzero process exits."""
    require(len(message) <= MAX_OUTPUT, "diagnostic_limit")
    return sorted(
        set(
            match.decode("ascii")
            for match in re.findall(
                rb"version [`'](GLIBC_[0-9]+(?:\.[0-9]+)+)['`] not found", message
            )
        )
    )


def command(arguments: list[str]) -> dict[str, Any]:
    with (
        tempfile.TemporaryFile(dir="/work") as stdout,
        tempfile.TemporaryFile(dir="/work") as stderr,
    ):
        process = subprocess.run(arguments, stdout=stdout, stderr=stderr, timeout=60)
        stdout.seek(0)
        stderr.seek(0)
        output, error = stdout.read(MAX_OUTPUT + 1), stderr.read(MAX_OUTPUT + 1)
    require(
        len(output) <= MAX_OUTPUT and len(error) <= MAX_OUTPUT, "child_output_limit"
    )
    return {
        "exit_code": process.returncode,
        "stdout": output.decode("utf-8"),
        "stderr_bytes": len(error),
        "missing_glibc_versions": missing_glibc_versions(error),
    }


def install_candidate(source: Path, destination: Path, expected_manifest: str) -> int:
    """Copy verified candidate files into the writable container installation."""
    require(
        file_hash(source / "manifest.json") == expected_manifest, "manifest_changed"
    )
    shutil.copytree(source, destination)
    manifest = json.loads((destination / "manifest.json").read_bytes())
    for name, entry in manifest["files"].items():
        path = destination / name
        require(
            path.is_file() and file_hash(path) == entry["sha256"],
            "installed_payload_changed",
        )
        require(path.stat().st_size == entry["size"], "installed_payload_size")
        require(path.stat().st_mode & 0o7777 == entry["mode"], "installed_payload_mode")
    return len(manifest["files"])


def work_space(work: Path, budget: dict[str, int], required: int) -> dict[str, int]:
    """Verify actual tmpfs capacity and free space, not only daemon configuration."""
    usage = getattr(os, "statvfs")(work)
    capacity = usage.f_blocks * usage.f_frsize
    available = usage.f_bavail * usage.f_frsize
    require(
        capacity == budget["capacity_bytes"]
        and available >= required + budget["reserve_bytes"],
        "runtime_work_space",
    )
    return {"capacity_bytes": capacity, "available_bytes": available}


def distribution(release: bytes) -> dict[str, str]:
    """Read only ID and VERSION_ID, without evaluating os-release as shell code."""
    require(len(release) <= 4096, "runtime_distribution_limit")
    values: dict[str, str] = {}
    for line in release.decode("utf-8").splitlines():
        if not line.startswith(("ID=", "VERSION_ID=")):
            continue
        match = re.fullmatch(
            r'(ID|VERSION_ID)=(?:"([a-zA-Z0-9_.-]+)"|([a-zA-Z0-9_.-]+))', line
        )
        require(match is not None, "runtime_distribution")
        assert match is not None
        key = match[1]
        require(key not in values, "runtime_distribution_duplicate")
        values[key] = match[2] or match[3]
    require(set(values) == {"ID", "VERSION_ID"}, "runtime_distribution")
    return {"id": values["ID"], "version_id": values["VERSION_ID"]}


def validate_identity(runtime: dict[str, Any], config: dict[str, Any]) -> None:
    """Keep exact legacy versions; the pinned UBI image records full patch versions."""
    require(runtime["glibc"] == config["glibc"], "runtime_glibc")
    distro = runtime["distribution"]
    if "debian" in config:
        require(
            distro == {"id": "debian", "version_id": config["debian"]}
            and runtime.get("debian") == config["debian"],
            "runtime_distribution",
        )
        require(runtime["python"] == config["python"], "runtime_python")
    else:
        require(
            distro["id"] == config["distribution_id"]
            and re.fullmatch(
                re.escape(config["distribution_major"]) + r"(?:\.[0-9]+)*",
                distro["version_id"],
            )
            is not None,
            "runtime_distribution",
        )
        require(
            re.fullmatch(
                re.escape(config["python_minor"]) + r"\.[0-9]+", runtime["python"]
            )
            is not None,
            "runtime_python",
        )


def execute(root: Path, work: Path, config: dict[str, Any]) -> dict[str, Any]:
    uid = getattr(os, "geteuid", lambda: -1)()
    gid = getattr(os, "getegid", lambda: -1)()
    require(uid == 65534 and gid == 65534, "runtime_user")
    require(platform.machine() == "x86_64", "runtime_architecture")
    glibc = getattr(os, "confstr", lambda _key: None)("CS_GNU_LIBC_VERSION")
    require(isinstance(glibc, str) and glibc.startswith("glibc "), "runtime_glibc")
    assert isinstance(glibc, str)
    with Path("/etc/os-release").open("rb") as source:
        distro = distribution(source.read(4097))
    identity = {
        "glibc": glibc.removeprefix("glibc "),
        "distribution": distro,
        "python": platform.python_version(),
    }
    if "debian" in config:
        identity["debian"] = distro["version_id"]
    validate_identity(identity, config)
    require(
        not any(key.startswith("LD_") or key == "GLIBC_TUNABLES" for key in os.environ),
        "runtime_loader_override",
    )
    budget = config["work_budget"]
    before = work_space(work, budget, budget["estimated_copy_bytes"])
    installed = {}
    for name in ("cli", "sdk"):
        installed[name] = install_candidate(
            root / name, work / name, config["manifests"][name]
        )
    cli = work / "cli/bin/dscope"
    sdk = work / "sdk"
    library = sdk / "lib/libdaoseeker_scope_ffi.so"
    consumer = sdk / "bin/c-example"
    hashes = {
        "cli": file_hash(cli),
        "library": file_hash(library),
        "consumer": file_hash(consumer),
    }
    require(hashes == config["binary_sha256"], "runtime_binary_changed")
    after = work_space(work, budget, 0)
    result: dict[str, Any] = {
        "overall": "passed",
        "expected": config["expected"],
        "runtime": {
            **identity,
            "kernel": platform.release(),
            "machine": platform.machine(),
            "uid": uid,
            "cargo_available": shutil.which("cargo") is not None,
            "rustc_available": shutil.which("rustc") is not None,
        },
        "installed_payload_files": installed,
        "binary_sha256": hashes,
        "calls": {},
        "rebuilt_in_container": False,
        "installation_storage": {
            "capacity_bytes": after["capacity_bytes"],
            "reserve_bytes": budget["reserve_bytes"],
            "available_before_copy_bytes": before["available_bytes"],
            "available_after_copy_bytes": after["available_bytes"],
        },
    }
    if config["expected"] == "runs":
        jobs = {
            "cli_version": [str(cli), "--version"],
            "cli_json": [str(cli), "--json"],
            "c": [str(consumer)],
            "python": [sys.executable, str(sdk / "examples/collect.py"), str(library)],
        }
        for label, arguments in jobs.items():
            item = command(arguments)
            require(
                item["exit_code"] == 0 and item["stderr_bytes"] == 0,
                "runtime_child_failed",
            )
            result["calls"][label] = item
    else:
        for label, arguments in {
            "cli": [str(cli), "--version"],
            "c": [str(consumer)],
        }.items():
            item = command(arguments)
            require(
                item["exit_code"] > 0 and bool(item["missing_glibc_versions"]),
                "expected_loader_rejection_missing",
            )
            item["stdout"] = ""
            result["calls"][label] = item
        diagnostic = b""
        try:
            ctypes.CDLL(str(library))
        except OSError as error:
            diagnostic = str(error).encode("utf-8")
        versions = missing_glibc_versions(diagnostic)
        require(bool(versions), "expected_ctypes_rejection_missing")
        result["calls"]["ctypes_load"] = {
            "rejected": True,
            "missing_glibc_versions": versions,
        }
        result["collection_started"] = False
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    options = parser.parse_args()
    config = json.loads(options.config.read_bytes())
    try:
        result = execute(Path("/input"), Path("/work"), config)
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) else "runtime_probe_failed"
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) is None:
            code = "runtime_probe_failed"
        result = {"overall": "failed", "failure": code}
    # The host validates then discards raw default-redacted snapshots; no Docker logs
    # or hardware snapshots are copied into the public evidence report.
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
