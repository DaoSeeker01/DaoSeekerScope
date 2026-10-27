"""Inventory GNU ELF dependencies and required symbol versions without loading it."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

MAX_OUTPUT = 1024 * 1024


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def linux_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Isolate child loader overrides and readelf locale; leave the parent alone."""
    result = {
        key: value
        for key, value in environment.items()
        if not key.startswith("LD_") and key != "GLIBC_TUNABLES"
    }
    result["LC_ALL"] = "C"
    return result


def needed_libraries(output: bytes, *, consumer: bool) -> list[str]:
    """Keep the existing SDK RUNPATH policy; CLI and libraries have no RUNPATH."""
    require(len(output) <= MAX_OUTPUT, "elf_output_limit")
    text = output.decode("ascii")
    needed = re.findall(r"\(NEEDED\)[^\r\n]*\[([^\]\r\n]+)\]", text)
    runpath = re.findall(r"\(RUNPATH\)[^\r\n]*\[([^\]\r\n]*)\]", text)
    require(
        0 < len(needed) <= 64
        and len(set(needed)) == len(needed)
        and all(re.fullmatch(r"[A-Za-z0-9_.+\-]+", name) for name in needed),
        "elf_needed",
    )
    require("(RPATH)" not in text, "elf_rpath")
    require(runpath == (["$ORIGIN/../lib"] if consumer else []), "elf_runpath")
    if consumer:
        require(needed.count("libdaoseeker_scope_ffi.so") == 1, "elf_sdk_dependency")
    return needed


def version_requirements(output: bytes, needed: list[str]) -> dict[str, dict[str, str]]:
    """Read only version needs, never version definitions or provided symbols."""
    require(len(output) <= MAX_OUTPUT, "elf_output_limit")
    text = output.decode("ascii")
    headers = list(
        re.finditer(
            r"(?m)^Version needs section '[^'\r\n]+' contains (\d+) entr(?:y|ies):\s*$",
            text,
        )
    )
    require(len(headers) == 1, "elf_version_section")
    declared = int(headers[0][1])
    require(1 <= declared <= 64, "elf_version_file_limit")
    section = re.split(
        r"(?m)^Version (?:symbols|definition|needs) section ",
        text[headers[0].end() :],
        maxsplit=1,
    )[0]
    result: dict[str, dict[str, str]] = {}
    current: str | None = None
    expected = 0
    total = 0
    for line in section.splitlines():
        if not line.strip() or re.fullmatch(r"\s*Addr:.*Offset:.*Link:.*", line):
            continue
        entry = re.fullmatch(
            r"\s*(?:0x)?[0-9a-fA-F]+:\s+Version:\s+1\s+File:\s+(\S+)\s+Cnt:\s+(\d+)\s*",
            line,
        )
        if entry:
            require(
                current is None or len(result[current]) == expected, "elf_version_count"
            )
            current = entry[1]
            expected = int(entry[2])
            require(current in needed and current not in result, "elf_version_file")
            require(1 <= expected <= 256, "elf_version_count")
            result[current] = {}
            continue
        version = re.fullmatch(
            r"\s*(?:0x)?[0-9a-fA-F]+:\s+Name:\s+([A-Za-z0-9_.+\-]{1,128})\s+Flags:\s+(\S+)\s+Version:\s+\d+\s*",
            line,
        )
        require(version is not None and current is not None, "elf_version_entry")
        assert version is not None and current is not None
        name = version[1]
        flags = version[2]
        require(flags in ("none", "WEAK"), "elf_version_flags")
        require(name != "GLIBC_PRIVATE", "elf_private_glibc")
        require(name not in result[current], "elf_version_duplicate")
        result[current][name] = flags
        total += 1
        require(total <= 1024 and len(result[current]) <= expected, "elf_version_count")
    require(
        len(result) == declared
        and current is not None
        and len(result[current]) == expected,
        "elf_version_count",
    )
    return {
        library: dict(sorted(names.items()))
        for library, names in sorted(result.items())
    }


def inspect_elf(output: bytes, *, consumer: bool = False) -> dict[str, Any]:
    """Inventory requirements; a numeric maximum is not an OS compatibility proof."""
    needed = needed_libraries(output, consumer=consumer)
    entries = version_requirements(output, needed)
    versions = {
        library: [name for name, flags in names.items() if flags == "none"]
        for library, names in entries.items()
    }
    weak = {
        library: [name for name, flags in names.items() if flags == "WEAK"]
        for library, names in entries.items()
        if "WEAK" in names.values()
    }
    glibc = {
        name
        for names in versions.values()
        for name in names
        if re.fullmatch(r"GLIBC_\d{1,8}(?:\.\d{1,8}){1,3}", name)
    }
    highest = max(
        glibc,
        key=lambda name: tuple(map(int, name.removeprefix("GLIBC_").split("."))),
        default=None,
    )
    return {
        "direct_dependencies": needed,
        "required_symbol_versions": versions,
        "weak_symbol_versions": weak,
        "direct_dependencies_without_version_entries": sorted(
            set(needed) - versions.keys()
        ),
        "highest_glibc_numeric_requirement": highest,
        "minimum_glibc_or_distribution_verified": False,
        "transitive_or_runtime_loads_inspected": False,
    }


def inspect_file(path: Path) -> dict[str, Any]:
    """Use GNU readelf in a bounded child process; never run the inspected file."""
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        result = subprocess.run(
            ["readelf", "--wide", "--dynamic", "--version-info", str(path)],
            cwd=path.parent,
            env=linux_environment(os.environ),
            stdout=stdout,
            stderr=stderr,
            timeout=30,
        )
        require(result.returncode == 0, "elf_exit")
        stdout.seek(0)
        output = stdout.read(MAX_OUTPUT + 1)
    return inspect_elf(output)
