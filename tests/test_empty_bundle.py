"""Empty-member fixtures are ZIP data only; their synthetic images never run."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from cli_bundle import (
    TARGET,
    LINUX_TARGET,
    digest,
    executable_name,
    ffi_files,
    verify_bundle,
    write_bundle,
)
from cli_bundle_smoke import install


class EmptyBundleTests(unittest.TestCase):
    def test_self_consistent_empty_members_fail_before_installation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for target in (TARGET, LINUX_TARGET):
                for product in ("cli", "ffi_sdk"):
                    required = (
                        set(ffi_files(target))
                        if product == "ffi_sdk"
                        else {executable_name(target)}
                    )
                    payload = {
                        name: b"synthetic, never executed"
                        for name in required
                        | {
                            "LICENSE-MIT",
                            "THIRD_PARTY.md",
                            "README.txt",
                            "licenses/fixture/LICENSE-MIT",
                        }
                    }
                    archive = root / f"{target}-{product}.zip"
                    checksum = write_bundle(
                        archive,
                        payload,
                        {
                            "version": "0.1.0",
                            "source_commit": "a" * 40,
                            "source_dirty": False,
                        },
                        target=target,
                        product=product,
                    )
                    files = verify_bundle(archive, checksum)
                    for index, empty in enumerate(files):
                        with self.subTest(target=target, product=product, empty=empty):
                            changed = {**files, empty: b""}
                            if empty != "manifest.json":
                                manifest = json.loads(changed["manifest.json"])
                                manifest["files"][empty].update(
                                    size=0, sha256=digest(b"")
                                )
                                changed["manifest.json"] = json.dumps(manifest).encode()
                            invalid = root / "empty.zip"
                            # Preserve modes: zero length is the only invalid property.
                            with (
                                zipfile.ZipFile(archive) as original,
                                zipfile.ZipFile(invalid, "w") as output,
                            ):
                                for info in original.infolist():
                                    output.writestr(info, changed[info.filename])
                            destination = root / f"install-{target}-{product}-{index}"
                            with self.assertRaisesRegex(ValueError, "^file_limit$"):
                                install(
                                    invalid, digest(invalid.read_bytes()), destination
                                )
                            self.assertFalse(destination.exists())

    def test_builder_also_rejects_empty_payload_before_creating_archive(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "empty.zip"
            with self.assertRaisesRegex(ValueError, "^file_limit$"):
                write_bundle(
                    archive,
                    {"LICENSE-MIT": b""},
                    {
                        "version": "0.1.0",
                        "source_commit": "a" * 40,
                        "source_dirty": False,
                    },
                )
            self.assertFalse(archive.exists())


if __name__ == "__main__":
    unittest.main()
