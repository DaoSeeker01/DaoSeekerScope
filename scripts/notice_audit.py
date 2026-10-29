"""Inventory missing crate notices without building or approving a binary bundle.

Exit zero means the audit completed, including when it found packaging blockers.
The report is not a legal review or a declaration of platform runtime support.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

from cli_bundle import (
    ROOT,
    MAX_FILE,
    dependency_packages,
    digest,
    notice_files,
    safe_name,
    require,
    run,
)

TARGETS = ("x86_64-pc-windows-msvc", "x86_64-unknown-linux-gnu", "aarch64-apple-darwin")


def inventory(metadata: dict[str, Any], root_package: str) -> dict[str, Any]:
    """Report all closure blockers; never replace or invent upstream notices."""
    packages = []
    for package in dependency_packages(metadata, root_package):
        errors = []
        if not package["source"].startswith("registry+"):
            errors.append("non_registry_dependency")
        if not package["license"]:
            errors.append("missing_spdx")
        files = notice_files(package)
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
            with path.open("rb") as source:
                data = source.read(MAX_FILE + 1)
            if not 0 < len(data) <= MAX_FILE:
                errors.append("notice_limit")
            else:
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


def audit(target: str, *, offline: bool = False) -> dict[str, Any]:
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
    products = {
        name: inventory(metadata, root)
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
        "limitations": "SPDX and discovered files do not establish complete attribution or legal clearance; no online fallback or inferred copyright holder",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=TARGETS)
    parser.add_argument("--offline", action="store_true")
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
        report = audit(target, offline=options.offline)
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
