"""Check actual crate archives and build them in an isolated local workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
from typing import Any

import jsonschema

from native_smoke import check_snapshot

ROOT = Path(__file__).resolve().parent.parent


def run(arguments: list[str], directory: Path = ROOT) -> str:
    result = subprocess.run(
        arguments,
        cwd=directory,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        timeout=900,
    )
    if result.returncode != 0:
        print(result.stdout[-8192:])
        result.check_returncode()
    return result.stdout


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def check_packages(options: argparse.Namespace) -> dict[str, Any]:
    """Build actual archives and return evidence only after every check passes."""
    offline = ["--offline"] if options.offline else []
    metadata = json.loads(
        run(
            [
                "cargo",
                "metadata",
                "--locked",
                "--no-deps",
                "--format-version",
                "1",
                *offline,
            ]
        )
    )
    members = [
        package
        for package in metadata["packages"]
        if package["id"] in metadata["workspace_members"]
    ]
    lock_before = (ROOT / "Cargo.lock").read_bytes()
    license_bytes = (ROOT / "LICENSE-MIT").read_bytes()
    header_bytes = (ROOT / "bindings/daoseeker_scope.h").read_bytes()
    archives = []
    target = ROOT / "target"
    with tempfile.TemporaryDirectory(prefix="package-check-", dir=target) as folder:
        stage = Path(folder).resolve()
        require(stage.is_relative_to(target.resolve()), "unexpected staging path")
        native_output = stage / "native"
        run(
            [
                "cargo",
                "package",
                "--locked",
                "--workspace",
                "--all-features",
                "--target-dir",
                str(native_output),
                *offline,
                *(["--allow-dirty"] if options.allow_dirty else []),
            ]
        )
        archive_output = ROOT / "target/package"
        archive_output.mkdir(parents=True, exist_ok=True)
        package_names = []
        for package in members:
            name = package["name"]
            prefix = f"{name}-{package['version']}"
            archive = archive_output / f"{prefix}.crate"
            shutil.copyfile(native_output / "package" / archive.name, archive)
            require(package["license"] == "MIT", f"license mismatch: {name}")
            with tarfile.open(archive, "r:gz") as bundle:
                entries = bundle.getmembers()
                for entry in entries:
                    path = Path(entry.name)
                    require(
                        not path.is_absolute()
                        and ".." not in path.parts
                        and path.parts[0] == prefix
                        and (entry.isfile() or entry.isdir()),
                        f"unsafe archive entry: {name}",
                    )
                bundle.extractall(stage, filter="data")
            package_root = stage / prefix
            require(
                (package_root / "LICENSE-MIT").read_bytes() == license_bytes,
                f"missing or incorrect packaged license: {name}",
            )
            manifest = tomllib.loads((package_root / "Cargo.toml").read_text())
            require(
                manifest["package"]["license"] == "MIT",
                f"normalized license mismatch: {name}",
            )
            if name == "daoseeker-scope-ffi":
                require(
                    (package_root / "include/daoseeker_scope.h").read_bytes()
                    == header_bytes,
                    "missing or incorrect packaged C header",
                )
            package_names.append((name, prefix))
            archives.append(
                {
                    "name": name,
                    "version": package["version"],
                    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "files": sum(entry.isfile() for entry in entries),
                }
            )
        # Normalized archives use registry dependencies. Local patches supply
        # unpublished siblings while preserving all third-party lock entries.
        manifest_lines = [
            "[workspace]",
            'resolver = "3"',
            "members = " + json.dumps([prefix for _, prefix in package_names]),
            "[patch.crates-io]",
            *[f'{name} = {{ path = "{prefix}" }}' for name, prefix in package_names],
        ]
        (stage / "Cargo.toml").write_text("\n".join(manifest_lines) + "\n")
        (stage / "Cargo.lock").write_bytes(lock_before)
        test_output = run(
            [
                "cargo",
                "test",
                "--locked",
                "--workspace",
                "--all-features",
                *offline,
                "--",
                "--test-threads=1",
            ],
            stage,
        )
        install_root = stage / "install"
        cli = next(prefix for name, prefix in package_names if name.endswith("-cli"))
        run(
            [
                "cargo",
                "install",
                "--locked",
                "--path",
                str(stage / cli),
                "--root",
                str(install_root),
                *offline,
            ],
            stage,
        )
        executable = install_root / "bin/dscope"
        if not executable.is_file():
            executable = executable.with_suffix(".exe")
        cli_version = run([str(executable), "--version"], stage).strip()
        snapshot = json.loads(run([str(executable), "--json"], stage))
        expected_version = next(
            package["version"]
            for package in members
            if package["name"] == "daoseeker-scope-cli"
        )
        require(
            cli_version == f"dscope {expected_version}",
            "installed CLI version mismatch",
        )
        schema = json.loads((ROOT / "docs/schema/snapshot-v1.schema.json").read_bytes())
        jsonschema.Draft202012Validator(schema).validate(snapshot)
        check_snapshot(snapshot)
        require(
            (stage / "Cargo.lock").read_bytes() == lock_before,
            "isolated dependency lock changed",
        )
    require((ROOT / "Cargo.lock").read_bytes() == lock_before, "source lock changed")
    report = {
        "overall": "passed",
        "git_revision": run(["git", "rev-parse", "HEAD"]).strip(),
        "git_dirty": bool(run(["git", "status", "--porcelain"]).strip()),
        "verification": "native Cargo package + archive contents + isolated workspace tests + CLI install",
        "native_cargo_verification": True,
        "registry_publication_verified": False,
        "unpublished_siblings": "local patches to extracted archives",
        "third_party_lock_unchanged": True,
        "installed_cli_version": cli_version,
        "snapshot_schema_validated": True,
        "minimum_read_and_default_privacy": True,
        "rust_tests_including_doctests": sum(
            map(int, re.findall(r"test result: ok\. (\d+) passed", test_output))
        ),
        "archives": archives,
    }
    print(f"package checks passed: {len(archives)} archives; {cli_version}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    options = parser.parse_args()
    output = ROOT / "target/package-evidence.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    # Invalidate an earlier pass before starting work, including on interruption.
    report: dict[str, Any] = {"overall": "incomplete", "failure": "not_completed"}
    output.write_text(json.dumps(report) + "\n", encoding="utf-8")
    try:
        report = check_packages(options)
    except Exception:
        report = {"overall": "failed", "failure": "validation_failed"}
        raise
    finally:
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
