"""Rehearse a verified CLI candidate install, rejected update, and rollback locally."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import tempfile
from typing import Any

import jsonschema

from cli_bundle import (
    ROOT,
    TARGET,
    LINUX_TARGET,
    digest,
    executable_name,
    file_mode,
    require,
    require_runtime_host,
    verify_bundle,
)
from native_smoke import check_snapshot


def install(archive: Path, checksum: str, destination: Path) -> dict[str, bytes]:
    """A fresh isolated directory only; never overwrite an existing installation."""
    payload = verify_bundle(archive, checksum)
    manifest = json.loads(payload["manifest.json"])
    target = manifest["target"]
    require(target != LINUX_TARGET or os.name == "posix", "posix_permissions_required")
    destination.mkdir()
    for name, data in payload.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(data)
        if target == LINUX_TARGET:
            path.chmod(file_mode(name, target))
    return payload


def activate(root: Path, slot: str, payload: dict[str, bytes]) -> None:
    require(slot in ("a", "b"), "invalid_slot")
    target = json.loads(payload["manifest.json"])["target"]
    for name, data in payload.items():
        installed = root / slot / name
        require(stat.S_ISREG(installed.lstat().st_mode), "installed_file_type")
        require(installed.read_bytes() == data, "installed_corruption")
        if target == LINUX_TARGET:
            require(
                stat.S_IMODE(installed.stat().st_mode) == file_mode(name, target),
                "installed_permissions",
            )
    pending = root / "pending"
    pending.write_text(slot, encoding="ascii")
    os.replace(pending, root / "active")


def probe(binary: Path, version: str) -> None:
    for arguments in (["--version"], ["--json"]):
        # Spool child output to disk, then read a bounded amount; never log snapshots.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            result = subprocess.run(
                [str(binary), *arguments],
                cwd=binary.parent,
                stdout=stdout,
                stderr=stderr,
                timeout=30,
                check=True,
            )
            require(result.returncode == 0, "cli_exit")
            stdout.seek(0)
            data = stdout.read(1024 * 1024 + 1)
        require(len(data) <= 1024 * 1024, "cli_output_limit")
        if arguments == ["--version"]:
            require(data.decode().strip() == f"dscope {version}", "cli_version")
        else:
            snapshot = json.loads(data)
            schema = json.loads(
                (ROOT / "docs/schema/snapshot-v1.schema.json").read_bytes()
            )
            jsonschema.Draft202012Validator(schema).validate(snapshot)
            check_snapshot(snapshot)


def probe_selected(
    root: Path, expected_slot: str, version: str, target: str = TARGET
) -> None:
    slot = (root / "active").read_text(encoding="ascii")
    require(slot in ("a", "b") and slot == expected_slot, "active_selection")
    probe(root / slot / executable_name(target), version)


def rehearse(archive: Path, checksum: str) -> dict[str, Any]:
    payload = verify_bundle(archive, checksum)
    manifest = json.loads(payload["manifest.json"])
    target = manifest["target"]
    require_runtime_host(target)
    with tempfile.TemporaryDirectory(
        prefix="cli-install-", dir=ROOT / "target"
    ) as folder:
        root = Path(folder)
        install(archive, checksum, root / "a")
        activate(root, "a", payload)
        probe_selected(root, "a", manifest["version"], target)
        # Both slots contain the same real candidate: this tests directory selection,
        # not compatibility with an older published version (none exists yet).
        install(archive, checksum, root / "b")
        activate(root, "b", payload)
        probe_selected(root, "b", manifest["version"], target)
        corrupt = root / "corrupt.zip"
        raw = bytearray(archive.read_bytes())
        raw[len(raw) // 2] ^= 1
        corrupt.write_bytes(raw)
        rejected = False
        try:
            install(corrupt, checksum, root / "rejected")
        except ValueError:
            rejected = True
        require(
            rejected and not (root / "rejected").exists(), "corrupt_update_accepted"
        )
        require((root / "active").read_text() == "b", "active_changed_on_failure")
        activate(root, "a", payload)
        require((root / "active").read_text() == "a", "rollback_selection")
        probe_selected(root, "a", manifest["version"], target)
    return {
        "overall": "passed",
        "source_commit": manifest["source_commit"],
        "source_dirty": manifest["source_dirty"],
        "target": target,
        "host": {
            "system": platform.system(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "version": manifest["version"],
        "bundle_format": manifest["bundle_format"],
        "abi_version": 1,
        "schema_version": 1,
        "archive_sha256": checksum,
        "cli_sha256": digest(payload[executable_name(target)]),
        "payload_files": len(payload) - 1,
        "processes": 6,
        "minimum_read_and_default_privacy": True,
        "snapshot_schema_validated": True,
        "posix_modes_verified": target == LINUX_TARGET,
        "corrupt_update_rejected_before_install": True,
        "same_candidate_two_slot_rollback": True,
        "older_version_compatibility_tested": False,
        "published": False,
        "global_install_or_path_modified": False,
        "publisher_authenticated": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/cli-bundle-evidence.json"
    )
    options = parser.parse_args()
    report: dict[str, Any] = {"overall": "failed", "failure": "not_completed"}
    try:
        with (options.archive.parent / "SHA256SUMS").open("rb") as source:
            sidecar = source.read(1025)
        require(len(sidecar) <= 1024, "checksum_sidecar_limit")
        fields = sidecar.decode("ascii").split()
        require(
            len(fields) == 2 and fields[1] == options.archive.name, "checksum_sidecar"
        )
        report = rehearse(options.archive, fields[0])
    finally:
        # A failed rerun replaces a prior pass; never record raw OS errors or data.
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("CLI candidate install/rollback: passed")


if __name__ == "__main__":
    main()
