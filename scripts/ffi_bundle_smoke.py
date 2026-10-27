"""Validate a native Windows/Linux FFI SDK via its packaged C/Python consumers."""

from __future__ import annotations

import argparse
import json
import os
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
    LINUX_TARGET,
    bundle_format,
    digest,
    require,
    require_runtime_host,
    verify_bundle,
)
from cli_bundle_smoke import activate, install
from native_smoke import check_snapshot
from elf_inspect import inspect_elf, linux_environment, needed_libraries
from pe_inspect import inspect_file, inspect_pe


def execute(
    arguments: list[str], directory: Path, label: str, target: str = TARGET
) -> bytes:
    require(label in ("compile", "c", "python", "elf"), "invalid_process_label")
    environment = os.environ.copy()
    if target == LINUX_TARGET:
        # Do not inherit developer loader overrides or mutate the parent's environment.
        environment = linux_environment(environment)
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        result = subprocess.run(
            arguments,
            cwd=directory,
            stdout=stdout,
            stderr=stderr,
            timeout=90,
            env=environment,
        )
        require(result.returncode == 0, f"{label}_exit")
        stdout.seek(0)
        data = stdout.read(1024 * 1024 + 1)
    require(len(data) <= 1024 * 1024, "output_limit")
    return data


def elf_dependencies(output: bytes, *, consumer: bool) -> list[str]:
    """Compatibility helper for the existing SDK dynamic-tag regression tests."""
    return needed_libraries(output, consumer=consumer)


def probe_sdk(root: Path, expected_slot: str, target: str = TARGET) -> dict[str, Any]:
    slot = (root / "active").read_text(encoding="ascii")
    require(slot in ("a", "b") and slot == expected_slot, "active_selection")
    sdk = root / slot
    dependencies: dict[str, Any] = {}
    if target == LINUX_TARGET:
        (sdk / "bin").mkdir(exist_ok=True)
        binary = sdk / "bin/c-example"
        library = sdk / "lib/libdaoseeker_scope_ffi.so"
        execute(
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
                str(binary),
            ],
            sdk,
            "compile",
            target,
        )
        for label, path in (("consumer", binary), ("library", library)):
            dependencies[label] = inspect_elf(
                execute(
                    ["readelf", "--wide", "--dynamic", "--version-info", str(path)],
                    sdk,
                    "elf",
                    target,
                ),
                consumer=label == "consumer",
            )
    else:
        binary = sdk / "bin/c-example.exe"
        library = sdk / "bin/daoseeker_scope_ffi.dll"
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
            target,
        )
        dependencies = {
            "consumer": inspect_file(binary, dll=False),
            "library": inspect_file(library, dll=True),
        }
        require(
            "daoseeker_scope_ffi.dll" in dependencies["consumer"]["direct_imports"],
            "pe_sdk_dependency",
        )
    data = execute([str(binary)], sdk, "c", target)
    snapshot = json.loads(data)
    schema = json.loads((sdk / "schema/snapshot-v1.schema.json").read_bytes())
    jsonschema.Draft202012Validator(schema).validate(snapshot)
    check_snapshot(snapshot)
    output = execute(
        [
            sys.executable,
            str(sdk / "examples/collect.py"),
            str(library),
        ],
        sdk,
        "python",
        target,
    )
    require(
        output.strip()
        == b"ctypes: 100 real collect/free cycles, stale copy rejection, privacy and schema passed",
        "python_contract",
    )
    return dependencies


def rehearse(archive: Path, checksum: str) -> dict[str, Any]:
    payload = verify_bundle(archive, checksum)
    manifest = json.loads(payload["manifest.json"])
    target = manifest["target"]
    require(
        manifest.get("product") == "ffi_sdk"
        and manifest["bundle_format"] == bundle_format(target, "ffi_sdk"),
        "unsupported_product",
    )
    require_runtime_host(target)
    if target == TARGET:
        inspect_pe(payload["bin/daoseeker_scope_ffi.dll"], dll=True)
    dependencies = []
    with tempfile.TemporaryDirectory(
        prefix="ffi-sdk-install-", dir=ROOT / "target"
    ) as folder:
        root = Path(folder)
        install(archive, checksum, root / "a")
        activate(root, "a", payload)
        dependencies.append(probe_sdk(root, "a", target))
        install(archive, checksum, root / "b")
        activate(root, "b", payload)
        dependencies.append(probe_sdk(root, "b", target))
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
        dependencies.append(probe_sdk(root, "a", target))
    linux = target == LINUX_TARGET
    report = {
        "overall": "passed",
        "source_commit": manifest["source_commit"],
        "source_dirty": manifest["source_dirty"],
        "product": "ffi_sdk",
        "target": target,
        "host": {
            "system": platform.system(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "bundle_format": manifest["bundle_format"],
        "abi_version": 1,
        "schema_version": 1,
        "archive_sha256": checksum,
        "header_sha256": digest(payload["bindings/daoseeker_scope.h"]),
        "payload_files": len(payload) - 1,
        "processes": 15 if linux else 9,
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
    if linux:
        require(dependencies[0] == dependencies[1] == dependencies[2], "elf_changed")
        report.update(
            library_sha256=digest(payload["lib/libdaoseeker_scope_ffi.so"]),
            elf_inspections=6,
            elf_needed={
                role: item["direct_dependencies"]
                for role, item in dependencies[0].items()
            },
            elf_images=dependencies[0],
            consumer_runpath="$ORIGIN/../lib",
            child_loader_overrides_cleared=True,
            posix_modes_verified=True,
            minimum_glibc_or_distribution_verified=False,
        )
    else:
        require(dependencies[0] == dependencies[1] == dependencies[2], "pe_changed")
        report.update(
            dll_sha256=digest(payload["bin/daoseeker_scope_ffi.dll"]),
            import_library_sha256=digest(payload["lib/daoseeker_scope_ffi.dll.lib"]),
            pe_archive_inspections=1,
            pe_installed_inspections=6,
            pe_images=dependencies[0],
        )
    return report


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
