"""Inventory missing crate notices without building or approving a binary bundle.

Exit zero means the audit completed, including when it found packaging blockers.
The report is not a legal review or a declaration of platform runtime support.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import tomllib
from typing import Any

from notice_archive import provenance
from cli_bundle import (
    ROOT,
    MAX_FILE,
    dependency_packages,
    digest,
    notice_files,
    read_notice,
    safe_name,
    require,
    run,
)

TARGETS = (
    "x86_64-pc-windows-msvc",
    "x86_64-unknown-linux-gnu",
    "aarch64-apple-darwin",
    "x86_64-apple-darwin",
)


def inventory(
    metadata: dict[str, Any],
    root_package: str,
    *,
    archive_checksums: dict[tuple[str, str, str], str] | None = None,
) -> dict[str, Any]:
    """Report all closure blockers; never replace or invent upstream notices."""
    packages = []
    for package in dependency_packages(metadata, root_package):
        errors = []
        if not package["source"].startswith("registry+"):
            errors.append("non_registry_dependency")
        if not package["license"]:
            errors.append("missing_spdx")
        try:
            files = notice_files(package)
        except ValueError as error:
            files = []
            errors.append(
                "duplicate_notice_name"
                if str(error) == "duplicate_notice_name"
                else "unsafe_notice_file"
            )
        except OSError:
            files = []
            errors.append("notice_read_failed")
        else:
            if not files:
                errors.append("missing_dependency_notice")
            elif not any(
                path.name.upper().startswith(("LICENSE", "COPYING")) for path in files
            ):
                errors.append("missing_dependency_license")
        notices = []
        for path in files:
            if not safe_name(
                f"licenses/{package['name']}-{package['version']}/{path.name}"
            ):
                errors.append("unsafe_notice_name")
                continue
            try:
                data = read_notice(path, MAX_FILE)
            except ValueError as error:
                errors.append(str(error))
                continue
            notices.append(
                {"name": path.name, "bytes": len(data), "sha256": digest(data)}
            )
        packages.append(
            {
                "name": package["name"],
                "version": package["version"],
                "spdx": package["license"],
                "notices": notices,
                "errors": sorted(set(errors)),
            }
        )
        if errors and archive_checksums is not None:
            checksum = archive_checksums.get(
                (package["name"], package["version"], package["source"])
            )
            packages[-1]["archive_provenance"] = provenance(package, checksum)
    return {
        "root_package": root_package,
        "packager_notice_gate": "blocked"
        if any(p["errors"] for p in packages)
        else "satisfied",
        "packages": packages,
        "blocking_packages": sum(bool(p["errors"]) for p in packages),
        "legal_review": "not_performed",
    }


def source_state() -> tuple[str, str]:
    return run(["git", "rev-parse", "HEAD"]).strip(), run(
        ["git", "status", "--porcelain"]
    ).strip()


def audit(
    target: str, *, offline: bool = False, verify_archives: bool = False
) -> dict[str, Any]:
    require(target in TARGETS, "unsupported_audit_target")
    initial = source_state()
    require(
        not initial[1] and re.fullmatch(r"[0-9a-f]{40}", initial[0]) is not None,
        "dirty_or_invalid_source",
    )
    lock = (ROOT / "Cargo.lock").read_bytes()
    metadata = json.loads(
        run(
            [
                "cargo",
                "metadata",
                "--locked",
                "--format-version",
                "1",
                "--filter-platform",
                target,
                *(["--offline"] if offline else []),
            ]
        )
    )
    checksums = None
    if verify_archives:
        checksums = {
            (entry["name"], entry["version"], entry["source"]): entry["checksum"]
            for entry in tomllib.loads(lock.decode("utf-8"))["package"]
            if entry.get("source") is not None and entry.get("checksum") is not None
        }
    products = {
        name: inventory(metadata, root, archive_checksums=checksums)
        for name, root in (
            ("cli", "daoseeker-scope-cli"),
            ("ffi_sdk", "daoseeker-scope-ffi"),
        )
    }
    require(
        (ROOT / "Cargo.lock").read_bytes() == lock and source_state() == initial,
        "audit_source_changed",
    )
    return {
        "format": 1,
        "overall": "completed",
        "target": target,
        "source_before": {"revision": initial[0], "status": initial[1]},
        "source_after": {"revision": initial[0], "status": initial[1]},
        "cargo_lock_sha256": digest(lock),
        "products": products,
        "scope": "target-filtered Cargo closure including build edges, excluding dev edges; root notice file presence and bounded contents only",
        "platform_executed": False,
        "binary_built": False,
        "published": False,
        "archive_verification_requested": verify_archives,
        "limitations": "SPDX and discovered files do not establish complete attribution or legal clearance; no online fallback or inferred copyright holder",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=TARGETS)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument(
        "--verify-archives",
        action="store_true",
        help="Verify cached crate archives for packages with missing or invalid notices.",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/notice-audit-evidence.json"
    )
    options = parser.parse_args()
    report: dict[str, Any] = {"overall": "incomplete"}
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_bytes((json.dumps(report) + "\n").encode())
    try:
        target = options.target
        if target is None:
            hosts = re.findall(r"^host: ([^\r\n]+)", run(["rustc", "-vV"]), re.M)
            require(len(hosts) == 1, "invalid_host")
            target = hosts[0]
        report = audit(
            target, offline=options.offline, verify_archives=options.verify_archives
        )
    except Exception:
        report = {"overall": "failed", "failure": "notice_audit_failed"}
        raise
    finally:
        options.output.write_bytes(
            (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
        )
    print(
        "Notice audit completed; inspect products.*.packager_notice_gate and errors. This does not approve distribution."
    )


if __name__ == "__main__":
    main()
