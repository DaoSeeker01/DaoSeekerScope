"""Compare candidate import symbols with Microsoft DUMPBIN without running images."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

from cli_bundle import ROOT, TARGET, digest, require, require_runtime_host
from cli_bundle_smoke import install
from pe_inspect import (
    MAX_IMAGE,
    MAX_IMPORTS,
    MAX_SYMBOLS,
    MAX_TOTAL_SYMBOLS,
    MAX_SYMBOL_NAME,
    inspect_pe,
)

MAX_OUTPUT = 2 * 1024 * 1024


def run(arguments: list[str], timeout: int = 90) -> bytes:
    environment = os.environ.copy()
    environment["VSLANG"] = "1033"
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        result = subprocess.run(
            arguments,
            cwd=ROOT,
            stdout=stdout,
            stderr=stderr,
            timeout=timeout,
            env=environment,
        )
        require(result.returncode == 0, "pe_oracle_child_exit")
        stdout.seek(0)
        data = stdout.read(MAX_OUTPUT + 1)
    require(len(data) <= MAX_OUTPUT, "pe_oracle_output_limit")
    return data


def source_state() -> dict[str, str]:
    return {
        "revision": run(["git", "rev-parse", "HEAD"]).decode().strip(),
        "status": run(["git", "status", "--porcelain"]).decode().strip(),
    }


def parse_dumpbin(data: bytes) -> dict[str, Any]:
    """Parse the English /IMPORTS subset observed on fresh MSVC images."""
    require(len(data) <= MAX_OUTPUT, "pe_oracle_output_limit")
    result: dict[str, dict[str, tuple[set[str], set[int]]]] = {
        "direct_symbols": {},
        "delay_symbols": {},
    }
    mode: str | None = None
    module: str | None = None
    ready = False
    seen_normal = False
    complete = False
    blocks = {"direct_symbols": 0, "delay_symbols": 0}
    total = count = 0
    # Paths in the ignored heading can use a local code page; symbols must be ASCII.
    for raw in data.decode("ascii", errors="replace").splitlines():
        line = raw.strip()
        header = re.fullmatch(
            r"(?:Section contains|Image has) the following (delay load )?imports:", line
        )
        if header:
            require(module is None or ready, "pe_dumpbin_metadata")
            mode = "delay_symbols" if header[1] else "direct_symbols"
            seen_normal |= mode == "direct_symbols"
            module, ready = None, False
            continue
        if line == "Summary":
            require(module is None or ready, "pe_dumpbin_metadata")
            complete = True
            break
        if mode is None or not line:
            continue
        if re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.\-]*\.dll", line, re.I):
            require(module is None or ready, "pe_dumpbin_metadata")
            module, ready, count = line.lower(), False, 0
            blocks[mode] += 1
            require(blocks[mode] <= MAX_IMPORTS, "pe_import_limit")
            result[mode].setdefault(module, (set(), set()))
            continue
        require(module is not None, "pe_dumpbin_module")
        assert module is not None
        if not ready:
            labels = (
                "Import Address Table",
                "Import Name Table",
                "Bound Import Name Table",
                "Unload Import Name Table",
                "time date stamp",
                "Index of first forwarder reference",
                "Characteristics",
                "Address of HMODULE",
            )
            require(
                any(
                    re.fullmatch(r"[0-9A-Fa-f]+\s+" + re.escape(label), line)
                    for label in labels
                ),
                "pe_dumpbin_metadata",
            )
            ready = line.endswith(
                "time date stamp"
                if mode == "delay_symbols"
                else "Index of first forwarder reference"
            )
            continue
        ordinal = re.fullmatch(r"(?:[0-9A-Fa-f]{8,16}\s+)?Ordinal\s+([0-9]{1,5})", line)
        named = re.fullmatch(
            r"(?:[0-9A-Fa-f]{8,16}\s+)?[0-9A-Fa-f]{1,4}\s+([\x21-\x7e]+)", line
        )
        count += 1
        total += 1
        require(count <= MAX_SYMBOLS and total <= MAX_TOTAL_SYMBOLS, "pe_symbol_limit")
        names, ordinals = result[mode][module]
        if ordinal:
            require(int(ordinal[1]) <= 65535, "pe_symbol_ordinal")
            ordinals.add(int(ordinal[1]))
        else:
            require(
                named is not None and len(named[1]) <= MAX_SYMBOL_NAME,
                "pe_dumpbin_symbol",
            )
            assert named is not None
            names.add(named[1])
    require(
        seen_normal and complete and (module is None or ready), "pe_dumpbin_incomplete"
    )
    return {
        mode: {
            module: {"names": sorted(values[0]), "ordinals": sorted(values[1])}
            for module, values in sorted(entries.items())
        }
        for mode, entries in result.items()
    }


def image_bytes(path: Path) -> bytes:
    with path.open("rb") as source:
        raw = source.read(MAX_IMAGE + 1)
    require(0 < len(raw) <= MAX_IMAGE, "pe_size")
    return raw


def compare(path: Path, tool: Path, *, dll: bool) -> dict[str, Any]:
    raw = image_bytes(path)
    pe = inspect_pe(raw, dll=dll)
    output = run([str(tool), "/nologo", "/imports", str(path)])
    oracle = parse_dumpbin(output)
    require(
        all(pe[key] == oracle[key] for key in ("direct_symbols", "delay_symbols")),
        "pe_symbol_oracle_mismatch",
    )
    require(image_bytes(path) == raw, "pe_oracle_image_changed")
    return {
        "sha256": digest(raw),
        "pe": pe,
        "dumpbin": oracle,
        "dumpbin_output_sha256": digest(output),
        "matched": True,
    }


def collect(cli: Path, sdk: Path) -> dict[str, Any]:
    require_runtime_host(TARGET)
    initial = source_state()
    require(
        not initial["status"]
        and re.fullmatch(r"[0-9a-f]{40}", initial["revision"]) is not None,
        "pe_oracle_dirty_source",
    )
    archives = {}
    images = {}
    with tempfile.TemporaryDirectory(
        prefix="pe-imports-", dir=ROOT / "target"
    ) as folder:
        temp = Path(folder)
        for product, archive in (("cli", cli), ("ffi_sdk", sdk)):
            with (archive.parent / "SHA256SUMS").open("rb") as sums:
                text = sums.read(1025)
            match = re.fullmatch(
                rb"([0-9a-f]{64})  "
                + re.escape(archive.name.encode())
                + rb"(?:\r?\n)?",
                text,
            )
            require(match is not None, "pe_oracle_checksum_file")
            assert match is not None
            checksum = match[1].decode()
            destination = temp / product
            payload = install(archive, checksum, destination)
            manifest = json.loads(payload["manifest.json"])
            require(
                manifest["target"] == TARGET
                and manifest.get("product", "cli") == product
                and manifest["source_commit"] == initial["revision"]
                and not manifest["source_dirty"],
                "pe_oracle_candidate_source",
            )
            archives[product] = checksum
        run(
            [
                "pwsh",
                "-NoProfile",
                "-File",
                str(ROOT / "scripts/build_c_example.ps1"),
                "-SdkDirectory",
                str(temp / "ffi_sdk"),
            ]
        )
        metadata = json.loads(
            run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-File",
                    str(ROOT / "scripts/build_c_example.ps1"),
                    "-PeImportsProbe",
                    "-PeImportsDirectory",
                    str(temp),
                ]
            )
            .decode("utf-8")
            .splitlines()[-1]
        )
        tool = Path(metadata["dumpbin"])
        tool_hash = digest(image_bytes(tool))
        for label, path, dll in (
            ("cli", temp / "cli/bin/dscope.exe", False),
            ("library", temp / "ffi_sdk/bin/daoseeker_scope_ffi.dll", True),
            ("consumer", temp / "ffi_sdk/bin/c-example.exe", False),
            ("delay_probe", temp / "delay-import-probe.exe", False),
        ):
            images[label] = compare(path, tool, dll=dll)
        require(
            "GetSystemMetrics"
            in images["delay_probe"]["pe"]["delay_symbols"]
            .get("user32.dll", {})
            .get("names", []),
            "pe_oracle_delay_missing",
        )
        require(digest(image_bytes(tool)) == tool_hash, "pe_oracle_tool_changed")
    final = source_state()
    require(final == initial, "pe_oracle_source_changed")
    return {
        "overall": "passed",
        "source_before": initial,
        "source_after": final,
        "archives": archives,
        "images": images,
        "compiler_version": metadata["compiler_version"],
        "dumpbin_sha256": tool_hash,
        "oracle": "Microsoft DUMPBIN /IMPORTS",
        "images_executed": False,
        "delay_probe_synthetic_consumer": True,
        "minimum_windows_verified": False,
        "transitive_or_dynamic_loads_inspected": False,
        "published": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cli", type=Path)
    parser.add_argument("sdk", type=Path)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/windows-imports-evidence.json"
    )
    args = parser.parse_args()
    report: dict[str, Any] = {"overall": "incomplete"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes((json.dumps(report) + "\n").encode())
    try:
        report = collect(args.cli.resolve(), args.sdk.resolve())
    except Exception:
        report = {"overall": "failed", "failure": "windows_imports_failed"}
        raise
    finally:
        args.output.write_bytes((json.dumps(report, indent=2) + "\n").encode())
    print("Windows import symbols match DUMPBIN; no minimum-OS claim.")


if __name__ == "__main__":
    main()
