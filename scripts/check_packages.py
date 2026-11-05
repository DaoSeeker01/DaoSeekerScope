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
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        timeout=900,
    )
    if result.returncode != 0:
        print((result.stdout + result.stderr)[-8192:])
        result.check_returncode()
    return result.stdout


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def source_state() -> tuple[str, str]:
    return run(["git", "rev-parse", "HEAD"]).strip(), run(
        ["git", "status", "--porcelain"]
    )


def verify_source(initial: tuple[str, str]) -> None:
    require(
        source_state() == initial, "source checkout changed during package verification"
    )


def third_party_lock_entries(data: bytes) -> set[tuple[str, str, str, str | None]]:
    return {
        (p["name"], p["version"], p["source"], p.get("checksum"))
        for p in tomllib.loads(data.decode("utf-8"))["package"]
        if p.get("source") is not None
    }


def check_consumer_core_features(
    metadata: dict[str, Any], *, serde_enabled: bool, schema_enabled: bool
) -> list[str]:
    require(
        len(metadata["workspace_members"]) == 1, "consumer workspace is not isolated"
    )
    core = [p for p in metadata["packages"] if p["name"] == "daoseeker-scope-core"]
    require(len(core) == 1, "consumer core dependency is ambiguous")
    node = next(n for n in metadata["resolve"]["nodes"] if n["id"] == core[0]["id"])
    features = set(node["features"])
    expected = set()
    if serde_enabled:
        expected.add("serde")
    if schema_enabled:
        expected.add("schema")
    require(features - {"default"} == expected, "consumer core features changed")
    if not serde_enabled:
        require(
            not any(
                kind["kind"] != "dev"
                for edge in node["deps"]
                for kind in edge["dep_kinds"]
            ),
            "bare core has a dependency",
        )
    return sorted(features)


CONSUMER_SOURCE = """
use scope::*;

struct Fixture;

impl Backend for Fixture {
    fn name(&self) -> &'static str {
        "consumer_fixture"
    }

    fn capabilities(&self) -> Capabilities {
        ["system.cpu.brand", "runtime.uptime_seconds"]
            .into_iter()
            .map(|field| Capability::new(field, CapabilityLevel::Supported, Source::Custom))
            .collect()
    }

    fn collect_static(
        &mut self,
        context: &CollectContext,
    ) -> Result<StaticSnapshot, ScopeError> {
        context.check()?;
        let mut result = StaticSnapshot::default();
        result.system.cpu.brand =
            Observed::available("fixture CPU".to_owned(), Source::Custom, Timestamp::now()?);
        Ok(result)
    }

    fn refresh_dynamic(
        &mut self,
        context: &CollectContext,
    ) -> Result<DynamicSnapshot, ScopeError> {
        context.check()?;
        let mut result = DynamicSnapshot::default();
        result.runtime.uptime_seconds =
            Observed::available(7, Source::Custom, Timestamp::now()?);
        Ok(result)
    }
}

fn main() -> Result<(), ScopeError> {
    let hardware = HardwareBuilder::default()
        .with_backend(100, Fixture)
        .build()?;
    let snapshot = hardware.collect()?;
    assert_eq!(
        snapshot.static_info.system.cpu.brand.value().map(String::as_str),
        Some("fixture CPU"),
    );
    assert_eq!(
        hardware.refresh_dynamic()?.runtime.uptime_seconds.value(),
        Some(&7),
    );
    let cancelled = CancelToken::default();
    cancelled.cancel();
    assert_eq!(
        hardware.collect_with(cancelled).expect_err("cancelled").code,
        ErrorCode::Cancelled,
    );
    hardware.shutdown()?;
"""


def check_consumers(
    stage: Path,
    package_names: list[tuple[str, str]],
    lock_before: bytes,
    offline: list[str],
) -> list[dict[str, Any]]:
    """Run independent public API clients against extracted archives and exact features."""
    consumer = stage / "consumer"
    (consumer / "src").mkdir(parents=True)
    versions = {
        p["name"]: p["version"]
        for p in tomllib.loads(lock_before.decode("utf-8"))["package"]
    }
    host = next(
        line[6:]
        for line in run(["rustc", "-vV"]).splitlines()
        if line.startswith("host: ")
    )
    locked = third_party_lock_entries(lock_before)
    packaged_roots = dict(package_names)
    reports = []
    profiles = [
        ("default", True, []),
        ("bare", False, []),
        ("serde", False, ["serde"]),
        ("schema", False, ["schema"]),
    ]
    for package in ("daoseeker-scope-core", "daoseeker-scope"):
        for label, defaults, features in profiles:
            schema_enabled = label == "schema"
            serde_enabled = label in ("serde", "schema") or (
                defaults and package == "daoseeker-scope"
            )
            manifest = [
                "[workspace]",
                'resolver = "3"',
                "[package]",
                'name = "daoseeker-scope-package-consumer"',
                'version = "0.0.0"',
                'edition = "2024"',
                "publish = false",
                "[dependencies]",
                f'scope = {{ package = "{package}", version = "={versions[package]}", '
                f"default-features = {str(defaults).lower()}, features = {json.dumps(features)} }}",
            ]
            source = CONSUMER_SOURCE
            if serde_enabled:
                manifest.append(f'serde_json = "={versions["serde_json"]}"')
                if package == "daoseeker-scope":
                    source += """
    let encoded = scope::to_json(&snapshot).expect("encode");
    assert_eq!(scope::from_json(encoded.as_bytes()).expect("decode"), snapshot);
"""
                else:
                    source += """
    let encoded = serde_json::to_vec(&snapshot).expect("encode");
    let decoded: Snapshot = serde_json::from_slice(&encoded).expect("decode");
    assert_eq!(decoded, snapshot);
"""
            if schema_enabled:
                manifest.append(f'schemars = "={versions["schemars"]}"')
                source += """
    let schema = serde_json::to_value(schemars::schema_for!(Snapshot)).expect("schema");
    assert_eq!(schema["title"], "Snapshot");
"""
            if package == "daoseeker-scope":
                source += """
    let native = scope::Hardware::new()?;
    assert_eq!(native.collect()?.schema_version, SCHEMA_VERSION);
    native.shutdown()?;
"""
            source += '    println!("consumer passed");\n    Ok(())\n}\n'
            manifest += [
                "[patch.crates-io]",
                *[
                    f'{name} = {{ path = "../{prefix}" }}'
                    for name, prefix in package_names
                ],
            ]
            (consumer / "Cargo.toml").write_text(
                "\n".join(manifest) + "\n", encoding="utf-8"
            )
            (consumer / "src/main.rs").write_text(source, encoding="utf-8")
            (consumer / "Cargo.lock").write_bytes(lock_before)
            # Add the new application to its own lock, retaining seeded dependency versions.
            metadata = json.loads(
                run(
                    [
                        "cargo",
                        "metadata",
                        "--format-version",
                        "1",
                        "--filter-platform",
                        host,
                        *offline,
                    ],
                    consumer,
                )
            )
            require(
                third_party_lock_entries((consumer / "Cargo.lock").read_bytes())
                <= locked,
                "consumer third-party lock changed",
            )
            for item in metadata["packages"]:
                if item["name"] in packaged_roots:
                    require(
                        Path(item["manifest_path"]).parent.resolve()
                        == (stage / packaged_roots[item["name"]]).resolve(),
                        "consumer did not use the extracted archive",
                    )
                elif item["source"] is None:
                    require(
                        item["id"] == metadata["resolve"]["root"],
                        "consumer has an unarchived path dependency",
                    )
            resolved = check_consumer_core_features(
                metadata, serde_enabled=serde_enabled, schema_enabled=schema_enabled
            )
            output = run(
                [
                    "cargo",
                    "run",
                    "--locked",
                    "--target",
                    host,
                    "--target-dir",
                    str(stage / "target"),
                    *offline,
                ],
                consumer,
            )
            require(output.strip() == "consumer passed", "consumer did not complete")
            reports.append(
                {
                    "package": package,
                    "profile": label,
                    "target": host,
                    "default_features": defaults,
                    "requested_features": features,
                    "resolved_core_features": resolved,
                    "executed": True,
                    "third_party_lock_preserved": True,
                    "archive_paths_verified": True,
                }
            )
    return reports


def check_packages(options: argparse.Namespace) -> dict[str, Any]:
    """Build actual archives and return evidence only after every check passes."""
    initial = source_state()
    require(
        not initial[1] or options.allow_dirty,
        "dirty checkout; commit changes or use --allow-dirty",
    )
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
        consumers = check_consumers(stage, package_names, lock_before, offline)
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
    verify_source(initial)
    report = {
        "overall": "passed",
        "git_revision": initial[0],
        "git_dirty": bool(initial[1]),
        "verification": "native Cargo package + archive contents + isolated tests + independent Rust feature consumers + CLI install",
        "native_cargo_verification": True,
        "registry_publication_verified": False,
        "unpublished_siblings": "local patches to extracted archives",
        "third_party_lock_unchanged": True,
        "independent_rust_consumers": consumers,
        "installed_cli_version": cli_version,
        "snapshot_schema_validated": True,
        "minimum_read_and_default_privacy": True,
        "rust_tests_including_doctests": sum(
            map(int, re.findall(r"test result: ok\. (\d+) passed", test_output))
        ),
        "archives": archives,
    }
    print(
        f"package checks passed: {len(archives)} archives; {len(consumers)} consumers; {cli_version}"
    )
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
