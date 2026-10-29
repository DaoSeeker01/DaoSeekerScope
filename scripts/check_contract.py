"""Check the frozen v0.1 manifest, JSON Schema and native C/Rust ABI contract.

Run from a clean commit. This detects drift; it is not a full Rust semver audit.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import tempfile
import tomllib
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BASELINE = "docs/contracts/v0.1.json"


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(f"contract: {code}")


def canonical_hash(value: Any) -> str:
    """Include all Schema keywords, including annotations; ignore JSON formatting."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def manifest_contract(root: Path) -> dict[str, Any]:
    workspace = tomllib.loads((root / "Cargo.toml").read_text("utf-8"))["workspace"]
    crates = {}
    for path in sorted((root / "crates").glob("*/Cargo.toml")):
        data = tomllib.loads(path.read_text("utf-8"))
        crates[data["package"]["name"]] = {
            "features": data.get("features", {}),
            "crate_types": data.get("lib", {}).get(
                "crate-type", ["rlib"] if (path.parent / "src/lib.rs").is_file() else []
            ),
            "binaries": data.get("bin", []),
        }
    toolchain = tomllib.loads((root / "rust-toolchain.toml").read_text("utf-8"))
    return {"package": workspace["package"], "crates": crates, "toolchain": toolchain}


def check_static(root: Path, baseline: dict[str, Any]) -> None:
    require(manifest_contract(root) == baseline["manifests"], "manifest_drift")
    schema = json.loads((root / "docs/schema/snapshot-v1.schema.json").read_bytes())
    require(canonical_hash(schema) == baseline["schema_sha256"], "schema_drift")
    require(
        (root / "bindings/daoseeker_scope.h").read_bytes()
        == (root / "crates/daoseeker-scope-ffi/include/daoseeker_scope.h").read_bytes(),
        "header_copy_drift",
    )


def compare_probes(c: Any, rust: Any, baseline: dict[str, Any]) -> None:
    require(isinstance(c, dict) and isinstance(rust, dict), "probe_object")
    # Canonical JSON comparison rejects bool/float values masquerading as integers.
    c_layout = {key: value for key, value in c.items() if key != "status_codes"}
    rust_layout = {key: value for key, value in rust.items() if key != "schema_version"}
    expected = baseline["native_layout"]
    require(
        canonical_hash(c_layout) == canonical_hash(expected)
        and canonical_hash(rust_layout) == canonical_hash(expected),
        "native_layout_drift",
    )
    require(
        canonical_hash(c.get("status_codes"))
        == canonical_hash(baseline["status_codes"]),
        "status_code_drift",
    )
    require(
        type(rust.get("schema_version")) is int
        and rust["schema_version"] == baseline["schema_version"],
        "schema_version_drift",
    )


def run(arguments: list[str], timeout: int = 180) -> bytes:
    # Keep diagnostics local and bound captured output, including compiler output.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        result = subprocess.run(
            arguments, cwd=ROOT, stdout=stdout, stderr=stderr, timeout=timeout
        )
        require(
            result.returncode == 0,
            f"child_failed ({Path(arguments[0]).name}, exit {result.returncode})",
        )
        stdout.seek(0)
        output = stdout.read(2 * 1024 * 1024 + 1)
        require(len(output) <= 2 * 1024 * 1024, "output_limit")
        return output


def source_state() -> tuple[str, str]:
    return (
        run(["git", "rev-parse", "HEAD"], 10).decode().strip(),
        run(["git", "status", "--porcelain"], 10).decode().strip(),
    )


def verify_source(initial: tuple[str, str]) -> tuple[str, str]:
    final = source_state()
    require(final == initial, "source_changed")
    return final


def check_native() -> dict[str, Any]:
    initial = source_state()
    require(not initial[1], "dirty_checkout")
    baseline = json.loads((ROOT / BASELINE).read_bytes())
    check_static(ROOT, baseline)
    rustc = run(["rustc", "-vV"]).decode()
    host = next(
        line.removeprefix("host: ")
        for line in rustc.splitlines()
        if line.startswith("host: ")
    )
    require(host in baseline["native_targets"], "unreviewed_native_target")
    # Explicit native target and dedicated artifacts prevent accidental reuse of
    # a cross-compiled DLL or an unrelated target directory from the environment.
    build = ROOT / "target/contract-build"
    native = build / host / "debug"
    run(
        [
            "cargo",
            "build",
            "--locked",
            "--offline",
            "--target",
            host,
            "--target-dir",
            str(build),
            "-p",
            "daoseeker-scope-ffi",
            "--lib",
            "--example",
            "abi_contract",
        ],
        900,
    )
    windows = platform.system() == "Windows"
    suffix = ".exe" if windows else ""
    executable = native / f"abi-contract-probe{suffix}"
    if windows:
        compiler = (
            run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-File",
                    "scripts/build_c_example.ps1",
                    "-AbiContractProbe",
                    "-AbiContractDirectory",
                    str(native),
                ]
            )
            .decode()
            .strip()
            .splitlines()[-1]
        )
    else:
        compiler = run(["cc", "--version"]).decode().splitlines()[0]
        run(
            [
                "cc",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-std=c11",
                "docs/research/abi_contract_probe.c",
                f"-L{native}",
                "-ldaoseeker_scope_ffi",
                f"-Wl,-rpath,{native}",
                "-o",
                str(executable),
            ]
        )
    c = json.loads(run([str(executable)], 10))
    rust_exe = native / "examples" / f"abi_contract{suffix}"
    rust = json.loads(run([str(rust_exe)], 10))
    compare_probes(c, rust, baseline)
    library = native / (
        "daoseeker_scope_ffi.dll"
        if windows
        else (
            "libdaoseeker_scope_ffi.dylib"
            if platform.system() == "Darwin"
            else "libdaoseeker_scope_ffi.so"
        )
    )
    inputs = [
        BASELINE,
        "bindings/daoseeker_scope.h",
        "scripts/check_contract.py",
        "docs/research/abi_contract_probe.c",
        "crates/daoseeker-scope-ffi/examples/abi_contract.rs",
    ]
    report = {
        "format": 1,
        "overall": "passed",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source_before": {"revision": initial[0], "status": initial[1]},
        "target": host,
        "rustc": rustc.strip(),
        "c_compiler": compiler,
        "c": c,
        "rust": rust,
        "schema_sha256": baseline["schema_sha256"],
        "inputs_sha256_lf": {
            name: hashlib.sha256(
                (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
            ).hexdigest()
            for name in inputs
        },
        "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
        "limits": "native debug build; not a complete Rust semver or behavior audit",
    }
    final = verify_source(initial)
    report["source_after"] = {"revision": final[0], "status": final[1]}
    return report


def main() -> None:
    output = ROOT / "target/contract-evidence.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"overall": "incomplete", "failure": "not_completed"}
    output.write_bytes((json.dumps(report) + "\n").encode())
    try:
        report = check_native()
    except Exception:
        report = {"overall": "failed", "failure": "validation_failed"}
        raise
    finally:
        output.write_bytes(
            (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
        )


if __name__ == "__main__":
    main()
