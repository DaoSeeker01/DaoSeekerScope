"""Build and verify an unpublished Windows x64 portable CLI candidate.

No upload, global install, PATH change, or library/FFI distribution is performed.
Checksums detect corruption; they do not authenticate the publisher.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import tomllib
from typing import Any
import zipfile

ROOT = Path(__file__).resolve().parent.parent
TARGET = "x86_64-pc-windows-msvc"
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
MAX_ENTRIES = 512
MAX_MANIFEST = 256 * 1024


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(name: str) -> bool:
    """Portable, relative, case-stable names; reject Windows special names too."""
    return (
        len(name) <= 240
        and re.fullmatch(r"[A-Za-z0-9_.\-/]+", name) is not None
        and str(PurePosixPath(name)) == name
        and not name.startswith("/")
        and all(
            part not in (".", "..")
            and not part.endswith(".")
            and part.split(".")[0].upper()
            not in {"CON", "PRN", "AUX", "NUL"}
            | {f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(1, 10)}
            for part in name.split("/")
        )
    )


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def verify_bundle(archive: Path, expected_sha256: str) -> dict[str, bytes]:
    """Verify before extraction or execution; return bounded verified payloads."""
    require(re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None, "bad_digest")
    with archive.open("rb") as source:
        raw = source.read(MAX_TOTAL + 1)
    require(len(raw) <= MAX_TOTAL, "archive_limit")
    require(digest(raw) == expected_sha256, "archive_checksum")
    # Use the exact checked bytes, not a second path read susceptible to replacement.
    import io

    with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
        entries = bundle.infolist()
        require(0 < len(entries) <= MAX_ENTRIES, "entry_limit")
        names: set[str] = set()
        payload: dict[str, bytes] = {}
        total = 0
        for entry in entries:
            name = entry.filename
            require(safe_name(name) and name.lower() not in names, "unsafe_member")
            names.add(name.lower())
            require(not entry.is_dir(), "directory_member")
            require(
                stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG),
                "special_member",
            )
            require(not entry.flag_bits & 1, "encrypted_member")
            limit = MAX_MANIFEST if name == "manifest.json" else MAX_FILE
            require(0 <= entry.file_size <= limit, "file_limit")
            total += entry.file_size
            require(total <= MAX_TOTAL, "total_limit")
            with bundle.open(entry) as member:
                data = member.read(limit + 1)
            require(len(data) == entry.file_size, "file_size")
            payload[name] = data
        for name in names:
            require(
                all(str(parent) not in names for parent in PurePosixPath(name).parents),
                "member_path_conflict",
            )
    require("manifest.json" in payload, "missing_manifest")
    manifest_bytes = payload.pop("manifest.json")
    manifest = json.loads(manifest_bytes, object_pairs_hook=unique_object)
    require(isinstance(manifest, dict), "manifest_shape")
    require(
        all(
            type(manifest.get(key)) is int and manifest[key] == 1
            for key in ("bundle_format", "abi_version", "schema_version")
        )
        and manifest.get("target") == TARGET
        and type(manifest.get("source_dirty")) is bool
        and isinstance(manifest.get("source_commit"), str)
        and re.fullmatch(r"[0-9a-f]{40}", manifest["source_commit"]) is not None
        and isinstance(manifest.get("version"), str),
        "manifest_version",
    )
    files = manifest.get("files")
    require(isinstance(files, dict) and set(files) == set(payload), "manifest_files")
    require(
        {"bin/dscope.exe", "LICENSE-MIT", "THIRD_PARTY.md", "README.txt"}
        <= set(payload),
        "missing_required_file",
    )
    for name, data in payload.items():
        record = files[name]
        require(
            isinstance(record, dict)
            and type(record.get("size")) is int
            and record["size"] == len(data)
            and record.get("sha256") == digest(data),
            "payload_checksum",
        )
    payload["manifest.json"] = manifest_bytes
    return payload


def run(arguments: list[str]) -> str:
    result = subprocess.run(
        arguments, cwd=ROOT, capture_output=True, timeout=900, check=True
    )
    return result.stdout.decode("utf-8").strip()


def dependency_payload(metadata: dict[str, Any]) -> dict[str, bytes]:
    """Conservative CLI dependency closure, including build but excluding dev edges."""
    packages = {p["id"]: p for p in metadata["packages"]}
    nodes = {n["id"]: n for n in metadata["resolve"]["nodes"]}
    pending = [p["id"] for p in packages.values() if p["name"] == "daoseeker-scope-cli"]
    require(len(pending) == 1, "cli_package")
    seen: set[str] = set()
    while pending:
        identifier = pending.pop()
        if identifier in seen:
            continue
        seen.add(identifier)
        pending.extend(
            edge["pkg"]
            for edge in nodes[identifier]["deps"]
            if any(kind["kind"] != "dev" for kind in edge["dep_kinds"])
        )
    payload: dict[str, bytes] = {}
    inventory = [
        "# Third-party crate notices",
        "",
        "Target-filtered CLI closure; includes build dependencies conservatively.",
        "All discovered root license/copyright/notice files are retained verbatim.",
        "SPDX expressions describe upstream choices, not a relicensing by this project.",
        "Rust toolchain notices are also included under licenses/rust/.",
        "",
    ]
    for identifier in sorted(seen):
        package = packages[identifier]
        if package["source"] is None:
            continue
        require(package["source"].startswith("registry+"), "non_registry_dependency")
        require(bool(package["license"]), "missing_spdx")
        base = Path(package["manifest_path"]).parent
        notices = sorted(
            path
            for path in base.iterdir()
            if path.is_file()
            and path.name.upper().startswith(
                ("LICENSE", "COPYING", "COPYRIGHT", "NOTICE")
            )
        )
        require(bool(notices), "missing_dependency_notice")
        require(
            any(
                path.name.upper().startswith(("LICENSE", "COPYING")) for path in notices
            ),
            "missing_dependency_license",
        )
        label = f"{package['name']}-{package['version']}"
        inventory.append(f"- {label}: {package['license']}")
        for path in notices:
            name = f"licenses/{label}/{path.name}"
            require(safe_name(name), "unsafe_notice_name")
            with path.open("rb") as source:
                data = source.read(MAX_FILE + 1)
            require(0 < len(data) <= MAX_FILE, "notice_limit")
            payload[name] = data
    payload["THIRD_PARTY.md"] = ("\n".join(inventory) + "\n").encode()
    return payload


def write_bundle(
    path: Path, payload: dict[str, bytes], provenance: dict[str, Any]
) -> str:
    require("manifest.json" not in payload, "reserved_manifest")
    require(len(payload) + 1 <= MAX_ENTRIES, "entry_limit")
    require(all(safe_name(name) for name in payload), "unsafe_member")
    require(len({name.lower() for name in payload}) == len(payload), "duplicate_member")
    require(all(0 < len(data) <= MAX_FILE for data in payload.values()), "file_limit")
    require(sum(map(len, payload.values())) <= MAX_TOTAL - MAX_MANIFEST, "total_limit")
    manifest = {
        **provenance,
        "bundle_format": 1,
        "target": TARGET,
        "abi_version": 1,
        "schema_version": 1,
        "files": {
            name: {"size": len(data), "sha256": digest(data)}
            for name, data in sorted(payload.items())
        },
    }
    contents = {
        **payload,
        "manifest.json": (
            json.dumps(manifest, sort_keys=True, indent=2) + "\n"
        ).encode(),
    }
    require(len(contents["manifest.json"]) <= MAX_MANIFEST, "manifest_limit")
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in sorted(contents.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, data)
    require(path.stat().st_size <= MAX_TOTAL, "archive_limit")
    checksum = digest(path.read_bytes())
    verify_bundle(path, checksum)
    return checksum


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    options = parser.parse_args()
    rustc = run(["rustc", "-vV"])
    require(f"host: {TARGET}" in rustc.splitlines(), "unsupported_host")
    checkout_status = run(["git", "status", "--porcelain"])
    dirty = bool(checkout_status)
    require(not dirty or options.allow_dirty, "dirty_checkout")
    revision = run(["git", "rev-parse", "HEAD"])
    require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None, "bad_revision")
    lock = (ROOT / "Cargo.lock").read_bytes()
    offline = ["--offline"] if options.offline else []
    metadata = json.loads(
        run(
            [
                "cargo",
                "metadata",
                "--locked",
                "--format-version",
                "1",
                "--filter-platform",
                TARGET,
                *offline,
            ]
        )
    )
    payload = dependency_payload(metadata)
    sysroot = Path(run(["rustc", "--print", "sysroot"])) / "share/doc/rust"
    rust_notices = [sysroot / "COPYRIGHT.html", sysroot / "COPYRIGHT-library.html"]
    rust_notices.extend(sorted((sysroot / "licenses").glob("*")))
    require(len(rust_notices) > 2, "missing_rust_notices")
    for path in rust_notices:
        require(path.is_file() and not path.is_symlink(), "missing_rust_notice")
        with path.open("rb") as source:
            data = source.read(MAX_FILE + 1)
        require(0 < len(data) <= MAX_FILE, "notice_limit")
        payload[f"licenses/rust/{path.name}"] = data
    # A fresh explicit target-dir prevents a redirected Cargo output directory or
    # an old executable from being mistaken for this build's successful output.
    with tempfile.TemporaryDirectory(
        prefix="cli-build-", dir=ROOT / "target"
    ) as folder:
        build = Path(folder)
        run(
            [
                "cargo",
                "build",
                "--locked",
                "--release",
                "--target",
                TARGET,
                "--target-dir",
                str(build),
                "-p",
                "daoseeker-scope-cli",
                *offline,
            ]
        )
        binary = build / TARGET / "release/dscope.exe"
        with binary.open("rb") as source:
            payload["bin/dscope.exe"] = source.read(MAX_FILE + 1)
    payload["LICENSE-MIT"] = (ROOT / "LICENSE-MIT").read_bytes()
    payload["README.txt"] = (
        "DaoSeekerScope unpublished Windows x64 CLI candidate\n"
        "Unzip into a new directory. Run bin\\dscope.exe --help or --json.\n"
        "Keep LICENSE-MIT, THIRD_PARTY.md and licenses/ with the executable.\n"
        "No administrator install or PATH change is required. Sensitive data is hidden by default.\n"
        "Windows runtime components remain system prerequisites; this is not a static OS image.\n"
        "SHA-256 detects corruption, not publisher identity. No code signature is supplied.\n"
        "For rollback retain the complete old directory and select its executable again.\n"
    ).encode()
    require((ROOT / "Cargo.lock").read_bytes() == lock, "lock_changed")
    require(run(["git", "rev-parse", "HEAD"]) == revision, "revision_changed")
    require(
        run(["git", "status", "--porcelain"]) == checkout_status, "checkout_changed"
    )
    version = tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"]["package"][
        "version"
    ]
    stage_root = ROOT / "target/cli-bundles"
    stage_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="candidate-", dir=stage_root))
    archive = stage / f"dscope-{version}-{TARGET}.zip"
    checksum = write_bundle(
        archive,
        payload,
        {
            "version": version,
            "source_commit": revision,
            "source_dirty": dirty,
            "cargo_lock_sha256": digest(lock),
            "rustc": rustc,
            "published": False,
        },
    )
    (stage / "SHA256SUMS").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    print(archive.relative_to(ROOT))


if __name__ == "__main__":
    main()
