"""Inspect bounded x64 PE candidates without loading them or resolving DLLs.

This records direct imports and header declarations, not a minimum Windows
version, a complete dependency closure, or a Windows loader security verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import struct
from typing import Any

MAX_IMAGE = 64 * 1024 * 1024
MAX_IMPORTS = 128
MAX_SYMBOLS = 8192
MAX_TOTAL_SYMBOLS = 16384
MAX_SYMBOL_NAME = 1024


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


@dataclass(frozen=True)
class Section:
    """Only file-backed RVA ranges are readable by this inspector."""

    rva: int
    virtual_size: int
    offset: int
    size: int


class Image:
    """Read the header and section ranges needed for import inventories."""

    def __init__(self, data: bytes, *, dll: bool) -> None:
        require(64 <= len(data) <= MAX_IMAGE, "pe_size")
        self.data = data
        self.symbol_count = 0
        require(data[:2] == b"MZ", "pe_dos_signature")
        pe = self.uint(60, 4)
        require(pe >= 64 and self.span(pe, 4) == b"PE\0\0", "pe_signature")
        require(self.uint(pe + 4, 2) == 0x8664, "pe_machine")
        count = self.uint(pe + 6, 2)
        require(1 <= count <= 96, "pe_sections")
        optional_size = self.uint(pe + 20, 2)
        flags = self.uint(pe + 22, 2)
        require(bool(flags & 0x2000) == dll and bool(flags & 2), "pe_image_kind")
        self.optional = pe + 24
        self.span(self.optional, optional_size)
        require(optional_size >= 112, "pe_optional_size")
        require(self.uint(self.optional, 2) == 0x20B, "pe_optional_magic")
        self.headers = self.uint(self.optional + 60, 4)
        directories = self.uint(self.optional + 108, 4)
        require(
            directories <= 16 and 112 + directories * 8 <= optional_size,
            "pe_directories",
        )
        self.directories = directories
        table = self.optional + optional_size
        require(table + count * 40 <= self.headers <= len(data), "pe_headers")
        self.sections: list[Section] = []
        for index in range(count):
            entry = table + index * 40
            virtual_size, rva, size, offset = struct.unpack(
                "<4I", self.span(entry + 8, 16)
            )
            require(
                rva >= self.headers and rva + max(virtual_size, size) <= 2**32,
                "pe_section_rva",
            )
            if size:
                require(offset >= self.headers, "pe_section_offset")
                self.span(offset, size)
            section = Section(rva, virtual_size, offset, size)
            for previous in self.sections:
                require(
                    rva + max(virtual_size, size) <= previous.rva
                    or previous.rva + max(previous.virtual_size, previous.size) <= rva,
                    "pe_overlapping_rva",
                )
                if size and previous.size:
                    require(
                        offset + size <= previous.offset
                        or previous.offset + previous.size <= offset,
                        "pe_overlapping_file_range",
                    )
            self.sections.append(section)

    def span(self, offset: int, size: int) -> bytes:
        require(0 <= offset <= offset + size <= len(self.data), "pe_truncated")
        return self.data[offset : offset + size]

    def uint(self, offset: int, size: int) -> int:
        return int.from_bytes(self.span(offset, size), "little")

    def file_range(self, rva: int, size: int) -> tuple[int, int]:
        """Return offset and readable end; never map zero-filled virtual tails."""
        require(rva > 0 and size > 0 and rva + size <= 2**32, "pe_rva")
        if rva + size <= self.headers:
            return rva, self.headers
        for section in self.sections:
            delta = rva - section.rva
            if 0 <= delta and delta + size <= section.size:
                return section.offset + delta, section.offset + section.size
        raise ValueError("pe_unmapped_rva")

    def module_name(self, rva: int) -> str:
        offset, end = self.file_range(rva, 1)
        terminator = self.data.find(b"\0", offset, min(end, offset + 261))
        require(terminator != -1, "pe_module_terminator")
        name = self.data[offset:terminator]
        require(
            re.fullmatch(rb"[A-Za-z0-9_][A-Za-z0-9_.\-]*\.dll", name, re.I) is not None,
            "pe_module_name",
        )
        return name.decode("ascii").lower()

    def symbol_name(self, rva: int) -> str:
        offset, end = self.file_range(rva, 3)  # Two-byte hint, then the name.
        start = offset + 2
        terminator = self.data.find(b"\0", start, min(end, start + MAX_SYMBOL_NAME + 1))
        require(terminator != -1, "pe_symbol_name_terminator")
        name = self.data[start:terminator]
        require(
            bool(name) and all(0x21 <= byte <= 0x7E for byte in name),
            "pe_symbol_name",
        )
        return name.decode("ascii")  # Import names are case-sensitive.

    def symbols(self, rva: int) -> tuple[set[str], set[int]]:
        offset, end = self.file_range(rva, 8)
        names: set[str] = set()
        ordinals: set[int] = set()
        for position in range(min((end - offset) // 8, MAX_SYMBOLS + 1)):
            value = self.uint(offset + position * 8, 8)
            if value == 0:
                return names, ordinals
            self.symbol_count += 1
            require(
                position < MAX_SYMBOLS and self.symbol_count <= MAX_TOTAL_SYMBOLS,
                "pe_symbol_limit",
            )
            if value & (1 << 63):
                require(value & ~((1 << 63) | 0xFFFF) == 0, "pe_symbol_ordinal")
                ordinals.add(value & 0xFFFF)
            else:
                require(value < (1 << 31), "pe_symbol_name_rva")
                names.add(self.symbol_name(value))
        raise ValueError("pe_symbol_terminator")

    def import_symbols(self, lookups: list[tuple[str, int]]) -> dict[str, Any]:
        gathered: dict[str, tuple[set[str], set[int]]] = {}
        for name, rva in lookups:
            names, ordinals = self.symbols(rva)
            target = gathered.setdefault(name, (set(), set()))
            target[0].update(names)
            target[1].update(ordinals)
        return {
            name: {"names": sorted(values[0]), "ordinals": sorted(values[1])}
            for name, values in sorted(gathered.items())
        }

    def imports(
        self, index: int, *, delay: bool = False
    ) -> tuple[list[str], dict[str, Any]]:
        if index >= self.directories:
            return [], {}
        directory = self.optional + 112 + index * 8
        rva, size = struct.unpack("<2I", self.span(directory, 8))
        if rva == size == 0:
            return [], {}
        stride = 32 if delay else 20
        require(
            rva > 0 and stride <= size <= stride * (MAX_IMPORTS + 1),
            "pe_import_limit",
        )
        offset, _ = self.file_range(rva, size)
        lookups: list[tuple[str, int]] = []
        for position in range(size // stride):
            descriptor = self.span(offset + position * stride, stride)
            if not any(descriptor):
                symbols = self.import_symbols(lookups)
                return sorted(symbols), symbols
            if delay:
                # The old VA-based format is outside our x64 candidate contract.
                require(int.from_bytes(descriptor[:4], "little") == 1, "pe_delay_mode")
            name_offset = 4 if delay else 12
            name_rva = int.from_bytes(
                descriptor[name_offset : name_offset + 4], "little"
            )
            require(position < MAX_IMPORTS, "pe_import_limit")
            lookup_offset = 16 if delay else 0
            lookup = int.from_bytes(
                descriptor[lookup_offset : lookup_offset + 4], "little"
            )
            if not delay and lookup == 0:
                # Only an unbound IAT still contains name/ordinal lookup entries.
                require(not any(descriptor[4:8]), "pe_bound_import_lookup")
                lookup = int.from_bytes(descriptor[16:20], "little")
            lookups.append((self.module_name(name_rva), lookup))
        raise ValueError("pe_import_terminator")


def inspect_pe(data: bytes, *, dll: bool) -> dict[str, Any]:
    """Validate this project's x64 PE subset and inventory declared DLL imports."""
    image = Image(data, dll=dll)
    imports, direct_symbols = image.imports(1)
    delayed, delay_symbols = image.imports(13, delay=True)
    require(bool(imports) and len(imports) + len(delayed) <= MAX_IMPORTS, "pe_imports")
    require(
        not any(
            re.fullmatch(r"(?:vcruntime[0-9_]+d|msvcp[0-9_]+d|ucrtbased)\.dll", name)
            for name in imports + delayed
        ),
        "pe_debug_runtime",
    )
    subsystem = image.uint(image.optional + 68, 2)
    require(subsystem in (2, 3) if dll else subsystem == 3, "pe_subsystem")
    return {
        "format": "PE32+",
        "machine": "x86_64",
        "kind": "dll" if dll else "exe",
        "subsystem": "windows_gui" if subsystem == 2 else "windows_cui",
        "declared_os_version": [
            image.uint(image.optional + 40, 2),
            image.uint(image.optional + 42, 2),
        ],
        "declared_subsystem_version": [
            image.uint(image.optional + 48, 2),
            image.uint(image.optional + 50, 2),
        ],
        "direct_imports": imports,
        "delay_imports": delayed,
        "direct_symbols": direct_symbols,
        "delay_symbols": delay_symbols,
        "minimum_windows_verified": False,
        "transitive_or_dynamic_loads_inspected": False,
    }


def inspect_file(path: Path, *, dll: bool) -> dict[str, Any]:
    """Bound reads of compiler-produced files before interpreting any offsets."""
    with path.open("rb") as source:
        data = source.read(MAX_IMAGE + 1)
    return inspect_pe(data, dll=dll)
