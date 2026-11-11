"""Read version-bound notice provenance from a checksum-verified Cargo archive."""

from __future__ import annotations

import gzip
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import tomllib
from typing import Any
from urllib.parse import quote

from cli_bundle import digest, read_notice, require, safe_name, unique_object

MAX_ARCHIVE = 64 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024
MAX_MEMBERS = 8192
MAX_TEXT = 1024 * 1024


def inspect(data: bytes, package: dict[str, Any]) -> dict[str, Any]:
    label = f"{package['name']}-{package['version']}"
    selected: dict[str, bytes] = {}
    names: set[str] = set()
    notices = []
    expanded = 0
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
        uncompressed = compressed.read(MAX_EXPANDED + 1)
    require(len(uncompressed) <= MAX_EXPANDED, "archive_limit")
    with tarfile.open(fileobj=io.BytesIO(uncompressed), mode="r:") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            require(
                len(names) < MAX_MEMBERS
                and len(member.name) <= 4096
                and member.name not in names
                and member.name.rstrip("/") == str(path)
                and not path.is_absolute()
                and ".." not in path.parts
                and path.parts[0] == label
                and (member.isfile() or member.isdir()),
                "invalid_archive_member",
            )
            names.add(member.name)
            expanded += member.size
            require(0 <= member.size and expanded <= MAX_EXPANDED, "archive_limit")
            if not member.isfile() or len(path.parts) != 2:
                continue
            name = path.name
            is_notice = name.upper().startswith(
                ("LICENSE", "COPYING", "COPYRIGHT", "NOTICE")
            )
            if not is_notice and name not in ("Cargo.toml", ".cargo_vcs_info.json"):
                continue
            require(
                safe_name(f"licenses/{label}/{name}") and 0 < member.size <= MAX_TEXT,
                "invalid_archive_text",
            )
            source = archive.extractfile(member)
            require(source is not None, "missing_archive_text")
            assert source is not None
            with source:
                content = source.read(MAX_TEXT + 1)
            require(len(content) == member.size, "truncated_archive_text")
            if is_notice:
                notices.append(
                    {"name": name, "bytes": len(content), "sha256": digest(content)}
                )
            else:
                selected[name] = content
    manifest = tomllib.loads(selected["Cargo.toml"].decode("utf-8"))["package"]
    require(
        isinstance(manifest, dict)
        and all(
            manifest.get(key) == package.get(key)
            for key in ("name", "version", "license")
        ),
        "archive_package_mismatch",
    )
    result: dict[str, Any] = {
        "status": "verified",
        "archive_sha256": digest(data),
        "archive_bytes": len(data),
        "archive_members": len(names),
        "root_notices": sorted(notices, key=lambda item: item["name"]),
        "vcs": None,
    }
    if ".cargo_vcs_info.json" in selected:
        vcs = json.loads(
            selected[".cargo_vcs_info.json"], object_pairs_hook=unique_object
        )
        require(
            isinstance(vcs, dict) and isinstance(vcs.get("git"), dict),
            "invalid_archive_vcs",
        )
        revision = vcs["git"]["sha1"]
        subdirectory = vcs["path_in_vcs"]
        require(
            isinstance(revision, str)
            and re.fullmatch(r"[0-9a-f]{40}", revision) is not None
            and isinstance(subdirectory, str)
            and len(subdirectory) <= 1024
            and not PurePosixPath(subdirectory).is_absolute()
            and ".." not in PurePosixPath(subdirectory).parts
            and "\\" not in subdirectory
            and (not subdirectory or safe_name(f"source/{subdirectory}"))
            and not any(ord(char) < 32 or ord(char) == 127 for char in subdirectory)
            and vcs["git"].get("dirty", False) is False,
            "invalid_archive_vcs",
        )
        result["vcs"] = {"revision": revision, "path_in_vcs": subdirectory}
        repository = manifest.get("repository")
        if (
            isinstance(repository, str)
            and len(repository) <= 2048
            and re.fullmatch(
                r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
            )
        ):
            result["vcs"]["source_url"] = (
                f"{repository.removesuffix('.git')}/tree/{revision}"
                + (f"/{quote(subdirectory, safe='/')}" if subdirectory else "")
            )
    return result


def provenance(package: dict[str, Any], checksum: str | None) -> dict[str, Any]:
    if not isinstance(checksum, str) or re.fullmatch(r"[0-9a-f]{64}", checksum) is None:
        return {"status": "unavailable", "reason": "missing_lock_checksum"}
    label = f"{package['name']}-{package['version']}"
    base = Path(package["manifest_path"]).parent
    if (
        not package["source"].startswith("registry+")
        or re.fullmatch(r"[A-Za-z0-9_-]+-[0-9][A-Za-z0-9.+_-]*", label) is None
        or base.name != label
        or base.parent.parent.name != "src"
    ):
        return {"status": "unavailable", "reason": "registry_cache_layout"}
    archive = base.parent.parent.parent / "cache" / base.parent.name / f"{label}.crate"
    try:
        data = read_notice(archive, MAX_ARCHIVE)
    except (OSError, ValueError):
        return {"status": "unavailable", "reason": "archive_read_failed"}
    if digest(data) != checksum:
        return {"status": "invalid", "reason": "archive_checksum_mismatch"}
    try:
        return inspect(data, package)
    except (
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        EOFError,
        OSError,
        OverflowError,
        RecursionError,
        tarfile.TarError,
    ):
        return {"status": "invalid", "reason": "archive_metadata_invalid"}
