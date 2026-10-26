"""Validate a Windows FFI SDK via its packaged C and Python consumers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from typing import Any

import jsonschema

from cli_bundle import (
    ROOT,
    TARGET,
    digest,
    require,
    require_runtime_host,
    verify_bundle,
)
from cli_bundle_smoke import activate, install
from native_smoke import check_snapshot


def execute(arguments: list[str], directory: Path, label: str) -> bytes:
    require(label in ("compile", "c", "python"), "invalid_process_label")
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        result = subprocess.run(
            arguments, cwd=directory, stdout=stdout, stderr=stderr, timeout=90
        )
        require(result.returncode == 0, f"{label}_exit")
        stdout.seek(0)
        data = stdout.read(1024 * 1024 + 1)
    require(len(data) <= 1024 * 1024, "output_limit")
    return data


def probe_sdk(root: Path, expected_slot: str) -> None:
    slot = (root / "active").read_text(encoding="ascii")
    require(slot in ("a", "b") and slot == expected_slot, "active_selection")
    sdk = root / slot
    execute(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(ROOT / "scripts/build_c_example.ps1"),
            "-SdkDirectory",
            str(sdk),
        ],
        sdk,
        "compile",
    )
    data = execute([str(sdk / "bin/c-example.exe")], sdk, "c")
    snapshot = json.loads(data)
    schema = json.loads((sdk / "schema/snapshot-v1.schema.json").read_bytes())
    jsonschema.Draft202012Validator(schema).validate(snapshot)
    check_snapshot(snapshot)
    output = execute(
        [
            sys.executable,
            str(sdk / "examples/collect.py"),
            str(sdk / "bin/daoseeker_scope_ffi.dll"),
        ],
        sdk,
        "python",
    )
    require(
        output.strip()
        == b"ctypes: 100 real collect/free cycles, stale copy rejection, privacy and schema passed",
        "python_contract",
    )


def rehearse(archive: Path, checksum: str) -> dict[str, Any]:
    payload = verify_bundle(archive, checksum)
    manifest = json.loads(payload["manifest.json"])
    require(
        manifest.get("product") == "ffi_sdk" and manifest["bundle_format"] == 3,
        "unsupported_product",
    )
    require_runtime_host(manifest["target"])
    with tempfile.TemporaryDirectory(
        prefix="ffi-sdk-install-", dir=ROOT / "target"
    ) as folder:
        root = Path(folder)
        install(archive, checksum, root / "a")
        activate(root, "a", payload)
        probe_sdk(root, "a")
        install(archive, checksum, root / "b")
        activate(root, "b", payload)
        probe_sdk(root, "b")
        raw = bytearray(archive.read_bytes())
        raw[len(raw) // 2] ^= 1
        corrupt = root / "corrupt.zip"
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
        probe_sdk(root, "a")
    return {
        "overall": "passed",
        "source_commit": manifest["source_commit"],
        "source_dirty": manifest["source_dirty"],
        "product": "ffi_sdk",
        "target": TARGET,
        "host": {
            "system": platform.system(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "bundle_format": 3,
        "abi_version": 1,
        "schema_version": 1,
        "archive_sha256": checksum,
        "dll_sha256": digest(payload["bin/daoseeker_scope_ffi.dll"]),
        "header_sha256": digest(payload["bindings/daoseeker_scope.h"]),
        "import_library_sha256": digest(payload["lib/daoseeker_scope_ffi.dll.lib"]),
        "payload_files": len(payload) - 1,
        "processes": 9,
        "c_compile_and_runs": 3,
        "python_collect_free_cycles": 300,
        "snapshot_schema_validated": True,
        "minimum_read_and_default_privacy": True,
        "stale_copy_and_empty_free": True,
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
        "--output", type=Path, default=ROOT / "target/ffi-bundle-evidence.json"
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
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("FFI SDK candidate C/Python install and rollback: passed")


if __name__ == "__main__":
    main()
