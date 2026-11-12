"""Compare compiled Core and facade APIs with the reviewed feature baselines."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import difflib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

from cli_bundle import ROOT, digest, unique_object

TOOL_VERSION = "0.52.0"
TOOLCHAIN = "nightly-2026-10-08"
BASELINE = ROOT / "docs/contracts/public-api"
OUTPUT = ROOT / "target/public-api-evidence.json"
MAX_OUTPUT = 4 * 1024 * 1024
PACKAGES = ("daoseeker-scope-core", "daoseeker-scope")
PROFILES = {
    "default": [],
    "bare": ["--no-default-features"],
    "serde": ["--no-default-features", "--features", "serde"],
    "schema": ["--no-default-features", "--features", "schema"],
}
TARGETS = {
    "x86_64-pc-windows-msvc",
    "x86_64-unknown-linux-gnu",
    "aarch64-apple-darwin",
    "x86_64-apple-darwin",
}


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(f"public_api: {code}")


def run(arguments: list[str], timeout: int = 240) -> bytes:
    environment = os.environ.copy()
    for key in ("RUSTC", "RUSTDOC", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER"):
        environment.pop(key, None)
    environment.update(
        CARGO_INCREMENTAL="0", CARGO_ENCODED_RUSTFLAGS="", CARGO_ENCODED_RUSTDOCFLAGS=""
    )
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        result = subprocess.run(
            arguments,
            cwd=ROOT,
            env=environment,
            stdout=stdout,
            stderr=stderr,
            timeout=timeout,
        )
        require(result.returncode == 0, "child_exit")
        require(
            stdout.tell() <= MAX_OUTPUT and stderr.tell() <= MAX_OUTPUT, "output_limit"
        )
        stdout.seek(0)
        return stdout.read(MAX_OUTPUT + 1)


def source_state() -> tuple[str, str]:
    return (
        run(["git", "rev-parse", "HEAD"], 60).decode().strip(),
        run(["git", "status", "--porcelain"], 60).decode().strip(),
    )


def cases() -> list[tuple[str, str, str]]:
    return [
        (package, profile, f"{package}-{profile}.txt")
        for package in PACKAGES
        for profile in PROFILES
    ]


def settings() -> dict[str, Any]:
    return {
        "format": 1,
        "tool": f"cargo-public-api {TOOL_VERSION}",
        "toolchain": TOOLCHAIN,
        "omitted_items": ["blanket-impls"],
        "profiles": PROFILES,
        "packages": list(PACKAGES),
    }


def normalize(data: bytes, package: str) -> bytes:
    require(len(data) <= MAX_OUTPUT, "api_output_limit")
    text = data.decode("utf-8").replace("\r\n", "\n")
    require(
        text.startswith(f"pub mod {package.replace('-', '_')}\n")
        and "\x1b" not in text
        and "\r" not in text,
        "api_output_invalid",
    )
    return text.encode("utf-8")


def collect(tool: Path, target: str, *, offline: bool) -> dict[str, bytes]:
    outputs = {}
    with tempfile.TemporaryDirectory(
        prefix="public-api-", dir=ROOT / "target"
    ) as folder:
        build = Path(folder)
        for package, profile, name in cases():
            rustdoc = build / target / "doc" / f"{package.replace('-', '_')}.json"
            rustdoc.unlink(missing_ok=True)
            run(
                [
                    "rustup",
                    "run",
                    TOOLCHAIN,
                    "cargo",
                    "rustdoc",
                    "--locked",
                    "--lib",
                    "-p",
                    package,
                    "--target",
                    target,
                    "--target-dir",
                    str(build),
                    *PROFILES[profile],
                    *(["--offline"] if offline else []),
                    "--",
                    "-Z",
                    "unstable-options",
                    "--output-format",
                    "json",
                ]
            )
            require(rustdoc.is_file(), "missing_rustdoc_json")
            outputs[name] = normalize(
                run(
                    [
                        str(tool),
                        "public-api",
                        "--rustdoc-json",
                        str(rustdoc),
                        "--omit",
                        "blanket-impls",
                        "--color",
                        "never",
                    ]
                ),
                package,
            )
    return outputs


def read_baseline(folder: Path) -> dict[str, bytes]:
    manifest = json.loads(
        (folder / "index.json").read_bytes(), object_pairs_hook=unique_object
    )
    require(manifest["settings"] == settings(), "baseline_settings")
    expected = {name for _, _, name in cases()}
    require(set(manifest["files"]) == expected, "baseline_cases")
    snapshots = {}
    for name in sorted(expected):
        data = (folder / name).read_bytes()
        require(
            len(data) <= MAX_OUTPUT and digest(data) == manifest["files"][name],
            "baseline_hash",
        )
        snapshots[name] = data
    return snapshots


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".api-", dir=path.parent, delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(data)
            output.flush()
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def update_baseline(folder: Path, outputs: dict[str, bytes]) -> None:
    require(set(outputs) == {name for _, _, name in cases()}, "incomplete_generation")
    for name, data in outputs.items():
        atomic_write(folder / name, data)
    # The index is committed last. An interrupted update fails hash validation.
    atomic_write(
        folder / "index.json",
        (
            json.dumps(
                {
                    "settings": settings(),
                    "files": {
                        name: digest(data) for name, data in sorted(outputs.items())
                    },
                },
                indent=2,
            )
            + "\n"
        ).encode(),
    )


def compare(
    baseline: dict[str, bytes],
    outputs: dict[str, bytes],
    diffs: Path,
) -> list[dict[str, Any]]:
    require(set(baseline) == set(outputs), "api_cases")
    results = []
    for package, profile, name in cases():
        before, after = baseline[name], outputs[name]
        diff_path = diffs / f"{name}.diff"
        diff_path.unlink(missing_ok=True)
        if before != after:
            text = "".join(
                difflib.unified_diff(
                    before.decode().splitlines(keepends=True),
                    after.decode().splitlines(keepends=True),
                    fromfile=f"baseline/{name}",
                    tofile=f"actual/{name}",
                )
            )
            atomic_write(diff_path, text.encode())
        results.append(
            {
                "package": package,
                "profile": profile,
                "matches": before == after,
                "baseline_sha256": digest(before),
                "actual_sha256": digest(after),
                "api_lines": len(after.splitlines()),
            }
        )
    return results


def check(tool: Path, *, offline: bool, update: bool) -> dict[str, Any]:
    initial = source_state()
    require(re.fullmatch(r"[0-9a-f]{40}", initial[0]) is not None, "source_revision")
    require(update or not initial[1], "dirty_checkout")
    baseline = None if update else read_baseline(BASELINE)
    version = run([str(tool), "public-api", "--version"], 60).decode().strip()
    require(version == f"cargo-public-api {TOOL_VERSION}", "tool_version")
    rustc = run(["rustup", "run", TOOLCHAIN, "rustc", "-vV"], 60).decode()
    hosts = re.findall(r"^host: (.+)$", rustc, re.M)
    require(len(hosts) == 1 and hosts[0].strip() in TARGETS, "native_target")
    outputs = collect(tool, hosts[0].strip(), offline=offline)
    require(source_state() == initial, "source_changed")
    if update:
        update_baseline(BASELINE, outputs)
        results = []
    else:
        assert baseline is not None
        results = compare(baseline, outputs, ROOT / "target/public-api-diffs")
        require(source_state() == initial, "source_changed")
    return {
        "format": 1,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "overall": "updated"
        if update
        else ("passed" if all(item["matches"] for item in results) else "failed"),
        "source_commit": initial[0],
        "source_dirty": bool(initial[1]),
        "target": hosts[0].strip(),
        "rustc": rustc,
        "settings": settings(),
        "cases": results,
        "generated_cases": len(outputs),
        "scope": "Core and facade APIs printed by the pinned tool; blanket implementations omitted",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument(
        "--update", action="store_true", help="Regenerate all baselines for review."
    )
    parser.add_argument(
        "--tool",
        type=Path,
        default=ROOT
        / "target/public-api-tools/bin"
        / ("cargo-public-api.exe" if os.name == "nt" else "cargo-public-api"),
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    options = parser.parse_args()
    report: dict[str, Any] = {"overall": "incomplete"}
    atomic_write(options.output, (json.dumps(report) + "\n").encode())
    try:
        report = check(
            options.tool.resolve(), offline=options.offline, update=options.update
        )
    except Exception:
        report = {"overall": "failed", "failure": "public_api_check_failed"}
        raise
    finally:
        atomic_write(options.output, (json.dumps(report, indent=2) + "\n").encode())
    require(report["overall"] != "failed", "api_drift")
    print(
        f"Rust public API: {report['overall']} ({report['generated_cases']} configurations)"
    )


if __name__ == "__main__":
    main()
