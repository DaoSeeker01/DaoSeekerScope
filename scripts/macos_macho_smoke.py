"""Bounded thin Mach-O metadata checks; compare native builds with Apple tools.

Not a loader, signature check, minimum-OS acceptance or distribution approval.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import platform
import re
import struct
import subprocess
import tempfile
from typing import Any

from cli_bundle import ROOT, digest, read_notice, require

MAX_IMAGE = 64 * 1024 * 1024
MAX_COMMANDS = 4096
MAX_OUTPUT = 2 * 1024 * 1024
ARCHES = {0x100000C: "arm64", 0x1000007: "x86_64"}
DYLIBS = {
    0xC: "LC_LOAD_DYLIB",
    0xD: "LC_ID_DYLIB",
    0x80000018: "LC_LOAD_WEAK_DYLIB",
    0x8000001F: "LC_REEXPORT_DYLIB",
    0x80000023: "LC_LOAD_UPWARD_DYLIB",
}


def version(value: int) -> list[int]:
    return [value >> 16, (value >> 8) & 255, value & 255]


def command_string(data: bytes, minimum: int) -> str:
    require(len(data) >= minimum, "macho_string_header")
    offset = struct.unpack_from("<I", data, 8)[0]
    require(minimum <= offset < len(data), "macho_string_offset")
    end = data.find(b"\0", offset)
    require(offset < end <= offset + 4096, "macho_string_limit")
    require(not any(data[end + 1 :]), "macho_string_padding")
    try:
        result = data[offset:end].decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("macho_string_encoding") from None
    require(
        result == result.strip()
        and not any(ord(c) < 32 or ord(c) == 127 for c in result),
        "macho_string_value",
    )
    return result


def inspect(data: bytes, architecture: str, kind: str) -> dict[str, Any]:
    require(32 <= len(data) <= MAX_IMAGE, "macho_image_limit")
    magic, cpu, subtype, filetype, count, size, _, reserved = struct.unpack_from(
        "<8I", data
    )
    require(magic == 0xFEEDFACF, "macho_thin_little_endian_64_required")
    require(
        architecture in ARCHES.values() and ARCHES.get(cpu) == architecture,
        "macho_architecture",
    )
    require(subtype == (0 if architecture == "arm64" else 3), "macho_cpu_subtype")
    require(
        kind in ("executable", "dylib")
        and filetype == (2 if kind == "executable" else 6),
        "macho_filetype",
    )
    require(reserved == 0 and 1 <= count <= MAX_COMMANDS, "macho_header")
    require(
        count * 8 <= size <= 1024 * 1024 and 32 + size <= len(data),
        "macho_commands_limit",
    )
    offset, end = 32, 32 + size
    libraries: list[list[str]] = []
    rpaths: list[str] = []
    minimum_os = sdk = None
    for _ in range(count):
        require(offset + 8 <= end, "macho_command_header")
        command, length = struct.unpack_from("<II", data, offset)
        require(
            length >= 8 and length % 8 == 0 and offset + length <= end,
            "macho_command_size",
        )
        block = data[offset : offset + length]
        if command in DYLIBS:
            libraries.append([DYLIBS[command], command_string(block, 24)])
        elif command == 0x8000001C:
            rpaths.append(command_string(block, 12))
        elif command in (0x24, 0x32):
            require(minimum_os is None, "macho_duplicate_platform")
            if command == 0x32:
                require(length >= 24, "macho_build_version")
                target, minimum, linked, tools = struct.unpack_from("<4I", block, 8)
                require(target == 1, "macho_macos_required")
                require(tools <= 64 and length == 24 + tools * 8, "macho_build_tools")
            else:
                require(length == 16, "macho_version_min")
                minimum, linked = struct.unpack_from("<2I", block, 8)
            require(minimum > 0, "macho_minimum_version")
            minimum_os, sdk = version(minimum), version(linked) if linked else None
        elif command == 0x27:
            raise ValueError("macho_embedded_dyld_environment")
        offset += length
    require(offset == end and minimum_os is not None, "macho_commands_complete")
    require(
        sum(c == "LC_ID_DYLIB" for c, _ in libraries) == (kind == "dylib"),
        "macho_install_id",
    )
    return {
        "architecture": architecture,
        "kind": kind,
        "libraries": sorted(libraries),
        "rpaths": sorted(rpaths),
        "minimum_declared_os": minimum_os,
        "link_sdk": sdk,
    }


def text_version(value: str) -> list[int] | None:
    if value in ("n/a", "0.0", "0.0.0"):
        return None
    require(
        re.fullmatch(r"\d+\.\d+(?:\.\d+)?", value) is not None, "macho_tool_version"
    )
    parts = list(map(int, value.split(".")))
    if len(parts) == 2:
        parts.append(0)
    require(
        0 < parts[0] <= 65535 and all(0 <= n <= 255 for n in parts[1:]),
        "macho_tool_version",
    )
    return parts


def parse_otool(data: bytes) -> dict[str, Any]:
    require(len(data) <= MAX_OUTPUT, "macho_tool_limit")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("macho_tool_encoding") from None
    blocks = re.split(r"(?m)^Load command \d+\s*$", text)[1:]
    require(1 <= len(blocks) <= MAX_COMMANDS, "macho_tool_commands")
    libraries: list[list[str]] = []
    rpaths: list[str] = []
    minimum_os = sdk = None
    for block in blocks:

        def field(name: str) -> str:
            values = re.findall(r"(?m)^\s*" + re.escape(name) + r"\s+(.+?)\s*$", block)
            require(len(values) == 1, "macho_tool_field")
            return values[0]

        command = field("cmd")
        if command in DYLIBS.values() or command == "LC_RPATH":
            match = re.fullmatch(
                r"(.+) \(offset \d+\)",
                field("path" if command == "LC_RPATH" else "name"),
            )
            require(match is not None, "macho_tool_name")
            assert match is not None
            if command == "LC_RPATH":
                rpaths.append(match[1])
            else:
                libraries.append([command, match[1]])
        elif command in ("LC_BUILD_VERSION", "LC_VERSION_MIN_MACOSX"):
            require(minimum_os is None, "macho_tool_duplicate_platform")
            if command == "LC_BUILD_VERSION":
                require(
                    field("platform").upper() in ("1", "MACOS", "MACOSX"),
                    "macho_tool_platform",
                )
            minimum_os = text_version(
                field("minos" if command == "LC_BUILD_VERSION" else "version")
            )
            require(minimum_os is not None, "macho_tool_minimum")
            sdk = text_version(field("sdk"))
    require(minimum_os is not None, "macho_tool_minimum")
    return {
        "libraries": sorted(libraries),
        "rpaths": sorted(rpaths),
        "minimum_declared_os": minimum_os,
        "link_sdk": sdk,
    }


def path_kind(value: str) -> str:
    if (
        value.startswith(("/usr/lib/", "/System/Library/Frameworks/"))
        and ".." not in PurePosixPath(value).parts
    ):
        return "system"
    for prefix, kind in (
        ("@rpath/", "rpath"),
        ("@loader_path/", "loader"),
        ("@executable_path/", "executable"),
        ("/", "absolute"),
    ):
        if value.startswith(prefix):
            return kind
    return "relative"


def summary(metadata: dict[str, Any]) -> dict[str, Any]:
    # Keep public system install names; never persist build-directory paths.
    return {
        "architecture": metadata["architecture"],
        "kind": metadata["kind"],
        "minimum_declared_os": metadata["minimum_declared_os"],
        "link_sdk": metadata["link_sdk"],
        "libraries": [
            {
                "command": command,
                "path_kind": path_kind(name),
                "name": name if path_kind(name) == "system" else "<redacted>",
            }
            for command, name in metadata["libraries"]
        ],
        "rpath_kinds": [path_kind(name) for name in metadata["rpaths"]],
    }


def run(arguments: list[str]) -> bytes:
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        result = subprocess.run(
            arguments, cwd=ROOT, stdout=stdout, stderr=stderr, timeout=30
        )
        require(result.returncode == 0, "macho_child_exit")
        stdout.seek(0)
        data = stdout.read(MAX_OUTPUT + 1)
    require(len(data) <= MAX_OUTPUT, "macho_output_limit")
    return data


def source() -> dict[str, str]:
    return {
        "revision": run(["git", "rev-parse", "HEAD"]).decode().strip(),
        "status": run(["git", "status", "--porcelain"]).decode().strip(),
    }


def collect() -> dict[str, Any]:
    require(platform.system() == "Darwin", "macho_native_host")
    architecture = platform.machine().lower()
    require(architecture in ARCHES.values(), "macho_native_architecture")
    before = source()
    require(not before["status"], "macho_dirty_source")
    images = {}
    inputs = (
        ("cli", "dscope", "executable"),
        ("library", "libdaoseeker_scope_ffi.dylib", "dylib"),
    )
    paths = {role: ROOT / "target/debug" / filename for role, filename, _ in inputs}
    hashes = {
        role: digest(read_notice(path, MAX_IMAGE)) for role, path in paths.items()
    }
    for role, filename, kind in inputs:
        path = ROOT / "target/debug" / filename
        data = read_notice(path, MAX_IMAGE)
        require(digest(data) == hashes[role], "macho_image_changed")
        metadata = inspect(data, architecture, kind)
        oracle = parse_otool(run(["xcrun", "otool", "-l", str(path)]))
        require(
            all(metadata[key] == value for key, value in oracle.items()),
            "macho_otool_mismatch",
        )
        require(
            run(["xcrun", "lipo", "-archs", str(path)]).decode().strip()
            == architecture,
            "macho_lipo_mismatch",
        )
        require(
            digest(read_notice(path, MAX_IMAGE)) == digest(data), "macho_image_changed"
        )
        images[role] = {
            "sha256": digest(data),
            "otool_and_lipo_matched": True,
            "metadata": summary(metadata),
        }
    require(
        source() == before
        and all(
            digest(read_notice(path, MAX_IMAGE)) == hashes[role]
            for role, path in paths.items()
        ),
        "macho_source_changed",
    )
    return {
        "overall": "passed",
        "source_before": before,
        "source_after": before,
        "images": images,
        "images_executed": False,
        "minimum_macos_verified": False,
        "distribution_approved": False,
        "published": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/macos-macho-evidence.json"
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"overall": "incomplete"}
    args.output.write_text(json.dumps(report) + "\n", encoding="utf-8")
    try:
        report = collect()
    except Exception:
        report = {"overall": "failed", "failure": "macho_validation_failed"}
        raise SystemExit(
            "Mach-O validation failed; inspect the report and prerequisites."
        ) from None
    finally:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        "Mach-O metadata matches Apple tools; minimum OS and distribution remain unverified."
    )


if __name__ == "__main__":
    main()
