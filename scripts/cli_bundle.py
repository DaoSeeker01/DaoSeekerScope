"""Build and verify unpublished Windows/Linux x64 CLI and FFI SDK candidates.

No upload, global install, PATH change, or binary distribution is performed.
Checksums detect corruption; they do not authenticate the publisher.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import subprocess
import tempfile
import tomllib
from typing import Any
import zipfile

ROOT = Path(__file__).resolve().parent.parent
TARGET = "x86_64-pc-windows-msvc"
LINUX_TARGET = "x86_64-unknown-linux-gnu"
SUPPORTED_TARGETS = frozenset({TARGET, LINUX_TARGET})
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
MAX_ENTRIES = 512
MAX_MANIFEST = 256 * 1024
FFI_FILES = frozenset(
    {
        "bin/daoseeker_scope_ffi.dll",
        "lib/daoseeker_scope_ffi.dll.lib",
        "bindings/daoseeker_scope.h",
        "examples/collect.c",
        "examples/collect.py",
        "schema/snapshot-v1.schema.json",
    }
)
LINUX_FFI_FILES = (
    FFI_FILES - {"bin/daoseeker_scope_ffi.dll", "lib/daoseeker_scope_ffi.dll.lib"}
) | {"lib/libdaoseeker_scope_ffi.so"}


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bundle_format(target: str, product: str) -> int:
    require(
        target in SUPPORTED_TARGETS and product in ("cli", "ffi_sdk"),
        "unsupported_product",
    )
    if product == "ffi_sdk":
        return 4 if target == LINUX_TARGET else 3
    return 2 if target == LINUX_TARGET else 1


def executable_name(target: str) -> str:
    require(target in SUPPORTED_TARGETS, "unsupported_target")
    return "bin/dscope" if target == LINUX_TARGET else "bin/dscope.exe"


def ffi_files(target: str) -> frozenset[str]:
    """Return the complete SDK contract for a supported native target."""
    require(target in SUPPORTED_TARGETS, "unsupported_target")
    return LINUX_FFI_FILES if target == LINUX_TARGET else FFI_FILES


def file_mode(name: str, target: str) -> int:
    return (
        0o755 if target == LINUX_TARGET and name == executable_name(target) else 0o644
    )


def require_runtime_host(
    target: str, system: str | None = None, machine: str | None = None
) -> None:
    require(target in SUPPORTED_TARGETS, "unsupported_target")
    system = platform.system() if system is None else system
    machine = platform.machine() if machine is None else machine
    expected = "Linux" if target == LINUX_TARGET else "Windows"
    require(
        system == expected and machine.lower() in ("amd64", "x86_64"),
        "unsupported_host",
    )


def native_target(rustc: str) -> str:
    hosts = [
        match.group(1) for match in re.finditer(r"^host: ([^\r\n]+)\r?$", rustc, re.M)
    ]
    require(len(hosts) == 1 and hosts[0] in SUPPORTED_TARGETS, "unsupported_host")
    require_runtime_host(hosts[0])
    return hosts[0]


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
        modes: dict[str, tuple[int, int]] = {}
        total = 0
        for entry in entries:
            name = entry.filename
            require(safe_name(name) and name.lower() not in names, "unsafe_member")
            names.add(name.lower())
            modes[name] = (entry.create_system, entry.external_attr >> 16)
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
    target = manifest.get("target")
    require(isinstance(target, str) and target in SUPPORTED_TARGETS, "manifest_version")
    product = manifest.get("product", "cli")
    require(isinstance(product, str), "manifest_version")
    expected_format = bundle_format(target, product)
    require(
        all(
            type(manifest.get(key)) is int and manifest[key] == 1
            for key in ("abi_version", "schema_version")
        )
        and type(manifest.get("bundle_format")) is int
        and manifest["bundle_format"] == expected_format
        and type(manifest.get("source_dirty")) is bool
        and isinstance(manifest.get("source_commit"), str)
        and re.fullmatch(r"[0-9a-f]{40}", manifest["source_commit"]) is not None
        and isinstance(manifest.get("version"), str),
        "manifest_version",
    )
    files = manifest.get("files")
    require(isinstance(files, dict) and set(files) == set(payload), "manifest_files")
    required = (
        set(ffi_files(target)) if product == "ffi_sdk" else {executable_name(target)}
    )
    required.update({"LICENSE-MIT", "THIRD_PARTY.md", "README.txt"})
    require(required <= set(payload), "missing_required_file")
    if target == LINUX_TARGET:
        require(
            modes["manifest.json"] == (3, stat.S_IFREG | 0o644), "archive_permissions"
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
        if target == LINUX_TARGET:
            expected_mode = file_mode(name, target)
            require(
                type(record.get("mode")) is int and record["mode"] == expected_mode,
                "manifest_permissions",
            )
            require(
                modes[name] == (3, stat.S_IFREG | expected_mode), "archive_permissions"
            )
    payload["manifest.json"] = manifest_bytes
    return payload


def run(arguments: list[str]) -> str:
    result = subprocess.run(
        arguments, cwd=ROOT, capture_output=True, timeout=900, check=True
    )
    return result.stdout.decode("utf-8").strip()


def dependency_payload(
    metadata: dict[str, Any], root_package: str = "daoseeker-scope-cli"
) -> dict[str, bytes]:
    """Target product dependency closure, including build but excluding dev edges."""
    packages = {p["id"]: p for p in metadata["packages"]}
    nodes = {n["id"]: n for n in metadata["resolve"]["nodes"]}
    pending = [p["id"] for p in packages.values() if p["name"] == root_package]
    require(len(pending) == 1, "root_package")
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
        f"Target-filtered {'CLI' if root_package == 'daoseeker-scope-cli' else 'FFI SDK'} closure; includes build dependencies conservatively.",
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
    path: Path,
    payload: dict[str, bytes],
    provenance: dict[str, Any],
    target: str = TARGET,
    product: str = "cli",
) -> str:
    version = bundle_format(target, product)
    require("product" not in provenance, "reserved_product")
    require("manifest.json" not in payload, "reserved_manifest")
    require(len(payload) + 1 <= MAX_ENTRIES, "entry_limit")
    require(all(safe_name(name) for name in payload), "unsafe_member")
    require(len({name.lower() for name in payload}) == len(payload), "duplicate_member")
    require(all(0 < len(data) <= MAX_FILE for data in payload.values()), "file_limit")
    require(sum(map(len, payload.values())) <= MAX_TOTAL - MAX_MANIFEST, "total_limit")
    manifest = {
        **provenance,
        "bundle_format": version,
        "target": target,
        **({"product": product} if product == "ffi_sdk" else {}),
        "abi_version": 1,
        "schema_version": 1,
        "files": {
            name: {
                "size": len(data),
                "sha256": digest(data),
                **({"mode": file_mode(name, target)} if target == LINUX_TARGET else {}),
            }
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
            info.external_attr = (stat.S_IFREG | file_mode(name, target)) << 16
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
    parser.add_argument("--product", choices=("cli", "ffi_sdk"), default="cli")
    options = parser.parse_args()
    rustc = run(["rustc", "-vV"])
    target = native_target(rustc)
    product = options.product
    bundle_format(target, product)
    package = "daoseeker-scope-ffi" if product == "ffi_sdk" else "daoseeker-scope-cli"
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
                target,
                *offline,
            ]
        )
    )
    payload = dependency_payload(metadata, root_package=package)
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
                target,
                "--target-dir",
                str(build),
                "-p",
                package,
                *offline,
            ]
        )
        release = build / target / "release"
        if product == "ffi_sdk":
            binaries = {
                "bin/daoseeker_scope_ffi.dll": "daoseeker_scope_ffi.dll",
                "lib/daoseeker_scope_ffi.dll.lib": "daoseeker_scope_ffi.dll.lib",
            }
            if target == LINUX_TARGET:
                binaries = {
                    "lib/libdaoseeker_scope_ffi.so": "libdaoseeker_scope_ffi.so"
                }
        else:
            binaries = {executable_name(target): Path(executable_name(target)).name}
        for name, filename in binaries.items():
            with (release / filename).open("rb") as source:
                payload[name] = source.read(MAX_FILE + 1)
    if product == "ffi_sdk":
        for name, filename in {
            "bindings/daoseeker_scope.h": "bindings/daoseeker_scope.h",
            "examples/collect.c": "examples/collect.c",
            "examples/collect.py": "examples/collect.py",
            "schema/snapshot-v1.schema.json": "docs/schema/snapshot-v1.schema.json",
        }.items():
            with (ROOT / filename).open("rb") as source:
                payload[name] = source.read(MAX_FILE + 1)
    payload["LICENSE-MIT"] = (ROOT / "LICENSE-MIT").read_bytes()
    windows_readme = (
        "DaoSeekerScope unpublished Windows x64 CLI candidate\n"
        "Unzip into a new directory. Run bin\\dscope.exe --help or --json.\n"
        "Keep LICENSE-MIT, THIRD_PARTY.md and licenses/ with the executable.\n"
        "No administrator install or PATH change is required. Sensitive data is hidden by default.\n"
        "Windows runtime components remain system prerequisites; this is not a static OS image.\n"
        "SHA-256 detects corruption, not publisher identity. No code signature is supplied.\n"
        "For rollback retain the complete old directory and select its executable again.\n"
    ).encode()
    linux_readme = (
        "DaoSeekerScope unpublished GNU/Linux x86_64 CLI candidate\n"
        "Verify SHA256SUMS with sha256sum -c, then extract into a new directory.\n"
        "Set bin/dscope to mode 0755 and regular data files to 0644; some ZIP tools discard permissions.\n"
        "Run bin/dscope --help or --json. Retain the complete old directory for rollback.\n"
        "Keep LICENSE-MIT, THIRD_PARTY.md and licenses/ with the executable.\n"
        "No root install or PATH change is required. Sensitive data is hidden by default.\n"
        "A compatible GNU/Linux runtime linker and system libraries are prerequisites.\n"
        "A native build/runner test does not establish a minimum glibc or distribution compatibility floor.\n"
        "SHA-256 detects corruption, not publisher identity. No signature is supplied.\n"
    ).encode()
    payload["README.txt"] = linux_readme if target == LINUX_TARGET else windows_readme
    if product == "ffi_sdk":
        payload["README.txt"] = (
            "DaoSeekerScope unpublished Windows x64 FFI SDK candidate; ABI 1 / snapshot Schema 1\n"
            "Verify SHA256SUMS before extracting into a fresh directory. Keep all notices with the DLL.\n"
            "In an x64 MSVC developer shell:\n"
            "cl /nologo /W4 /WX /std:c11 /Febin\\collect.exe /Fobin\\collect.obj examples\\collect.c lib\\daoseeker_scope_ffi.dll.lib\n"
            "bin\\collect.exe\n"
            "python examples\\collect.py <absolute-path-to-bin\\daoseeker_scope_ffi.dll>\n"
            "Use the included header and import library with this DLL. Free library buffers using dsc_buffer_free.\n"
            "Python's example requires only the standard library. C builds require MSVC and Windows SDK.\n"
            "Keep the previous complete SDK directory for rollback; no PATH or global install is needed.\n"
            "System runtime prerequisites, signing and old-version compatibility are not established.\n"
            "SHA-256 detects corruption, not publisher identity. No binary distribution has occurred.\n"
        ).encode()
        if target == LINUX_TARGET:
            payload["README.txt"] = (
                "DaoSeekerScope unpublished GNU/Linux x86_64 FFI SDK; ABI 1 / snapshot Schema 1\n"
                "Verify SHA256SUMS before extracting into a fresh directory. Keep all notices with the .so.\n"
                "All archived SDK files use mode 0644; directories need normal search permissions.\n"
                "From the extracted SDK root, with a GNU-compatible C compiler/linker:\n"
                "mkdir -p bin\n"
                "cc -Wall -Wextra -Werror -std=c11 examples/collect.c -Llib -ldaoseeker_scope_ffi "
                "-Wl,--enable-new-dtags '-Wl,-rpath,$ORIGIN/../lib' -o bin/collect\n"
                "bin/collect\n"
                'python3 examples/collect.py "$(pwd)/lib/libdaoseeker_scope_ffi.so"\n'
                "Use the packaged header with this library; release buffers with dsc_buffer_free.\n"
                "Python requires only the standard library. The validator additionally needs readelf and jsonschema.\n"
                "The rehearsal removes LD_* and GLIBC_TUNABLES from child environments only.\n"
                "System loader configuration and runtime libraries remain prerequisites; no minimum glibc is established.\n"
                "Keep the complete old SDK directory for rollback; no root, global PATH or loader changes are needed.\n"
                "SHA-256 detects corruption, not publisher identity. Signing and older-release compatibility are pending.\n"
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
    prefix = "daoseeker-scope-ffi-sdk" if product == "ffi_sdk" else "dscope"
    archive = stage / f"{prefix}-{version}-{target}.zip"
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
        target=target,
        product=product,
    )
    (stage / "SHA256SUMS").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    print(archive.relative_to(ROOT))


if __name__ == "__main__":
    main()
