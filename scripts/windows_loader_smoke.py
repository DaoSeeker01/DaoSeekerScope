"""Exercise missing and damaged SDK DLLs in an isolated Windows installation."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import platform
import re
import tempfile
from typing import Any

import jsonschema

from cli_bundle import ROOT, TARGET, digest, require, require_runtime_host, run
from cli_bundle_smoke import activate, install
from ffi_bundle_smoke import execute, probe_sdk
from native_smoke import check_snapshot


def source_state() -> tuple[str, str]:
    return run(["git", "rev-parse", "HEAD"]), run(["git", "status", "--porcelain"])


def collect(archive: Path) -> dict[str, Any]:
    require_runtime_host(TARGET)
    initial = source_state()
    require(
        not initial[1] and re.fullmatch(r"[0-9a-f]{40}", initial[0]) is not None,
        "loader_dirty_source",
    )
    with (archive.parent / "SHA256SUMS").open("rb") as source:
        sidecar = source.read(1025)
    match = re.fullmatch(
        rb"([0-9a-f]{64})  " + re.escape(archive.name.encode()) + rb"(?:\r?\n)?",
        sidecar,
    )
    require(match is not None, "loader_checksum_sidecar")
    assert match is not None
    checksum = match[1].decode()
    with tempfile.TemporaryDirectory(
        prefix="windows-loader-", dir=ROOT / "target"
    ) as folder:
        root = Path(folder)
        sdk = root / "a"
        payload = install(archive, checksum, sdk)
        manifest = json.loads(payload["manifest.json"])
        require(
            manifest["target"] == TARGET
            and manifest.get("product") == "ffi_sdk"
            and manifest["source_commit"] == initial[0]
            and not manifest["source_dirty"],
            "loader_candidate_source",
        )
        activate(root, "a", payload)
        baseline = probe_sdk(root, "a", TARGET)
        library = sdk / "bin/daoseeker_scope_ffi.dll"
        binary = sdk / "bin/c-example.exe"
        schema = json.loads(payload["schema/snapshot-v1.schema.json"])
        kernel = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
        kernel.GetErrorMode.argtypes = []
        kernel.GetErrorMode.restype = wintypes.UINT
        kernel.SetErrorMode.argtypes = [wintypes.UINT]
        kernel.SetErrorMode.restype = wintypes.UINT
        previous = kernel.GetErrorMode()
        # Only this diagnostic process and its children inherit these flags.
        # Prevent intentionally broken DLLs from opening blocking OS dialogs.
        kernel.SetErrorMode(previous | 0x0003)
        observed = []
        try:
            saved = root / "held.dll"
            library.replace(saved)
            try:
                for case, expected in (
                    ("missing", "c_windows_dependency_missing"),
                    ("damaged", "c_windows_invalid_image"),
                ):
                    if case == "damaged":
                        library.write_bytes(b"intentionally invalid DLL image\n")
                    try:
                        execute([str(binary)], sdk, "c", TARGET)
                    except ValueError as error:
                        require(str(error) == expected, "loader_unexpected_failure")
                        observed.append({"case": case, "observed_failure": str(error)})
                    else:
                        raise ValueError("loader_broken_library_accepted")
            finally:
                saved.replace(library)
            require(
                library.read_bytes() == payload["bin/daoseeker_scope_ffi.dll"],
                "loader_restore_hash",
            )
            snapshot = json.loads(execute([str(binary)], sdk, "c", TARGET))
            jsonschema.Draft202012Validator(schema).validate(snapshot)
            check_snapshot(snapshot)
        finally:
            kernel.SetErrorMode(previous)
        require(kernel.GetErrorMode() == previous, "loader_error_mode_restore")
        consumer_hash = digest(binary.read_bytes())
    require(source_state() == initial, "loader_source_changed")
    return {
        "format": 1,
        "overall": "passed",
        "source_commit": initial[0],
        "source_dirty": False,
        "target": TARGET,
        "host": {
            "system": platform.system(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "archive_sha256": checksum,
        "dll_sha256": digest(payload["bin/daoseeker_scope_ffi.dll"]),
        "consumer_sha256": consumer_hash,
        "consumer_import_verified": "daoseeker_scope_ffi.dll"
        in baseline["consumer"]["direct_imports"],
        "negative_controls": observed,
        "restored_consumer_schema_and_privacy_passed": True,
        "error_mode_restored": True,
        "runtime_path": "system32_and_windows",
        "published": False,
        "scope": "Isolated verified SDK C consumer; no minimum OS, clean-system runtime or missing-DLL identity claim.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdk", type=Path)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/windows-loader-evidence.json"
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"overall": "incomplete"}
    args.output.write_bytes((json.dumps(report) + "\n").encode())
    try:
        report = collect(args.sdk.resolve())
    except Exception:
        report = {"overall": "failed", "failure": "windows_loader_check_failed"}
        raise
    finally:
        args.output.write_bytes((json.dumps(report, indent=2) + "\n").encode())
    print("Windows SDK loader: missing/damaged DLL rejected, restored consumer passed.")


if __name__ == "__main__":
    main()
