"""Notice inventory fixtures do not establish upstream licensing completeness."""

import json
import os
import stat
import sys
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import cli_bundle as bundle
import notice_audit as audit
from cli_bundle import dependency_payload, digest, notice_files


def metadata(root: Path) -> dict[str, Any]:
    packages: list[dict[str, Any]] = [
        {"id": "cli", "name": "daoseeker-scope-cli", "source": None}
    ]
    nodes: list[dict[str, Any]] = [{"id": "cli", "deps": []}]
    for name, kind in (("a", None), ("b", "build"), ("c", "dev")):
        folder = root / name
        folder.mkdir()
        packages.append(
            {
                "id": name,
                "name": name,
                "version": "1",
                "source": "registry+test",
                "license": "MIT",
                "manifest_path": str(folder / "Cargo.toml"),
            }
        )
        nodes[0]["deps"].append({"pkg": name, "dep_kinds": [{"kind": kind}]})
        nodes.append({"id": name, "deps": []})
    return {"packages": packages, "resolve": {"nodes": nodes}}


class NoticeAuditTests(unittest.TestCase):
    def test_case_colliding_notice_names_block_preflight_and_packaging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = metadata(root)
            first = root / "a/LICENSE"
            second = root / "a/license"
            first.write_bytes(b"upstream notice")
            if not second.exists():
                second.write_bytes(b"second upstream notice")
            (root / "b/LICENSE").write_bytes(b"another valid notice")
            iterdir = Path.iterdir

            def list_entries(path: Path) -> Iterator[Path]:
                # Represent the same case-sensitive listing on Windows as on Unix.
                if path == first.parent:
                    return iter((first, second))
                return iterdir(path)

            with patch.object(Path, "iterdir", list_entries):
                report = audit.inventory(value, "daoseeker-scope-cli")
                self.assertEqual(report["packager_notice_gate"], "blocked")
                self.assertEqual(report["blocking_packages"], 1)
                self.assertEqual(
                    report["packages"][0]["errors"], ["duplicate_notice_name"]
                )
                self.assertEqual(report["packages"][0]["notices"], [])
                self.assertTrue(report["packages"][1]["notices"])
                with self.assertRaisesRegex(ValueError, "^duplicate_notice_name$"):
                    dependency_payload(value)

    def test_notice_directories_are_not_recursed_into(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = metadata(root)
            (root / "a/LICENSE").write_bytes(b"synthetic notice")
            (root / "a/LICENSES").mkdir()
            (root / "a/LICENSES/nested").write_bytes(b"not a root notice")
            self.assertEqual(notice_files(value["packages"][1]), [root / "a/LICENSE"])

    def test_changed_opened_identity_is_rejected_before_read_and_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "LICENSE"
            path.write_bytes(b"synthetic notice")
            other = root / "outside"
            other.write_bytes(b"synthetic private content")
            descriptor = os.open(other, os.O_RDONLY)
            with (
                patch.object(bundle.os, "open", return_value=descriptor),
                patch.object(bundle.os, "fdopen") as read,
            ):
                with self.assertRaisesRegex(ValueError, "unsafe_notice_file"):
                    bundle.read_notice(path, 1024)
                read.assert_not_called()
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_read_error_closes_descriptor_and_scan_errors_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = metadata(root)
            for name in ("a", "b"):
                (root / name / "LICENSE").write_bytes(b"synthetic notice")
            path = root / "a/LICENSE"
            descriptor = os.open(path, os.O_RDONLY)
            with (
                patch.object(bundle.os, "open", return_value=descriptor),
                patch.object(bundle.os, "fdopen", side_effect=OSError("PRIVATE")),
            ):
                with self.assertRaisesRegex(ValueError, "^notice_read_failed$"):
                    bundle.read_notice(path, 1024)
            with self.assertRaises(OSError):
                os.fstat(descriptor)
            with patch.object(
                audit,
                "notice_files",
                side_effect=[PermissionError("PRIVATE"), [root / "b/LICENSE"]],
            ):
                report = audit.inventory(value, "daoseeker-scope-cli")
            self.assertEqual(report["packages"][0]["errors"], ["notice_read_failed"])
            self.assertTrue(report["packages"][1]["notices"])
            self.assertNotIn("PRIVATE", json.dumps(report))

    def test_symlink_notices_block_even_with_another_valid_license(self) -> None:
        for target in ("outside.txt", "missing.txt", "outside-dir"):
            with (
                self.subTest(target=target),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                value = metadata(root)
                (root / "outside.txt").write_bytes(b"synthetic private content")
                (root / "outside-dir").mkdir()
                for name in ("a", "b"):
                    (root / name / "LICENSE-MIT").write_bytes(b"synthetic notice")
                try:
                    (root / "a/NOTICE").symlink_to(
                        root / target, target_is_directory=target == "outside-dir"
                    )
                except OSError as error:
                    if os.name == "nt" and getattr(error, "winerror", None) == 1314:
                        self.skipTest("Windows account cannot create symbolic links")
                    raise
                with self.assertRaisesRegex(ValueError, "unsafe_notice_file"):
                    dependency_payload(value)
                report = audit.inventory(value, "daoseeker-scope-cli")
                self.assertEqual(report["blocking_packages"], 1)
                self.assertEqual(
                    report["packages"][0]["errors"], ["unsafe_notice_file"]
                )
                self.assertTrue(report["packages"][1]["notices"])
                self.assertNotIn("synthetic private content", json.dumps(report))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO required")
    def test_fifo_notice_blocks_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = metadata(root)
            for name in ("a", "b"):
                (root / name / "LICENSE").write_bytes(b"synthetic notice")
            getattr(os, "mkfifo")(root / "a/NOTICE")
            with patch.object(
                Path, "open", side_effect=AssertionError("must not open")
            ):
                with self.assertRaisesRegex(ValueError, "unsafe_notice_file"):
                    notice_files(value["packages"][1])
            report = audit.inventory(value, "daoseeker-scope-cli")
            self.assertEqual(report["packages"][0]["errors"], ["unsafe_notice_file"])

    def test_reparse_metadata_is_rejected_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            value = metadata(Path(directory))
            (Path(directory) / "a/LICENSE").write_bytes(b"synthetic notice")
            info = SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)
            with (
                patch.object(Path, "lstat", return_value=info),
                patch.object(Path, "open", side_effect=AssertionError("must not open")),
            ):
                with self.assertRaisesRegex(ValueError, "unsafe_notice_file"):
                    notice_files(value["packages"][1])

    def test_all_missing_build_and_normal_notices_reported_without_dev(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            value = metadata(Path(directory))
            report = audit.inventory(value, "daoseeker-scope-cli")
            self.assertEqual(report["blocking_packages"], 2)
            self.assertEqual([p["name"] for p in report["packages"]], ["a", "b"])
            self.assertEqual(report["packager_notice_gate"], "blocked")
            with self.assertRaisesRegex(ValueError, "missing_dependency_notice"):
                dependency_payload(value)

    def test_notice_alone_and_missing_spdx_have_distinct_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = metadata(root)
            (root / "a/NOTICE").write_bytes(b"upstream notice")
            value["packages"][2]["license"] = None
            report = audit.inventory(value, "daoseeker-scope-cli")
            self.assertEqual(
                report["packages"][0]["errors"], ["missing_dependency_license"]
            )
            self.assertEqual(
                report["packages"][1]["errors"],
                ["missing_dependency_notice", "missing_spdx"],
            )

    def test_report_hashes_match_unmodified_packaged_bytes_without_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = metadata(root)
            for name in ("a", "b"):
                (root / name / "LICENSE-MIT").write_bytes(b"synthetic text\n")
            report = audit.inventory(value, "daoseeker-scope-cli")
            self.assertEqual(report["packager_notice_gate"], "satisfied")
            self.assertEqual(report["legal_review"], "not_performed")
            self.assertNotIn(directory, json.dumps(report))
            payload = dependency_payload(value)
            for package in report["packages"]:
                notice = package["notices"][0]
                self.assertEqual(
                    notice["sha256"],
                    digest(payload[f"licenses/{package['name']}-1/LICENSE-MIT"]),
                )

    def test_invalid_notice_names_empty_and_oversized_contents_stay_blocked(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = metadata(root)
            (root / "a/LICENSE bad").write_bytes(b"text")
            (root / "a/LICENSE-empty").write_bytes(b"")
            (root / "b/LICENSE").write_bytes(b"x" * 9)
            with patch.object(audit, "MAX_FILE", 8):
                report = audit.inventory(value, "daoseeker-scope-cli")
            self.assertEqual(report["blocking_packages"], 2)
            self.assertEqual(
                report["packages"][0]["errors"], ["notice_limit", "unsafe_notice_name"]
            )
            self.assertEqual(report["packages"][1]["errors"], ["notice_limit"])

    def test_cycle_is_bounded_and_non_registry_source_is_not_approved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            value = metadata(Path(directory))
            value["resolve"]["nodes"][1]["deps"] = [
                {"pkg": "a", "dep_kinds": [{"kind": None}]}
            ]
            value["packages"][1]["source"] = "git+https://example.invalid/repo"
            report = audit.inventory(value, "daoseeker-scope-cli")
            self.assertEqual(len(report["packages"]), 2)
            self.assertIn("non_registry_dependency", report["packages"][0]["errors"])

    def test_invalid_target_and_dirty_source_do_not_invoke_metadata(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported_audit_target"):
            audit.audit("wasm32-unknown-unknown")
        with (
            patch.object(audit, "source_state", return_value=("a" * 40, "dirty")),
            patch.object(audit, "run") as run,
        ):
            with self.assertRaisesRegex(ValueError, "dirty_or_invalid_source"):
                audit.audit(audit.TARGETS[0])
            run.assert_not_called()

    def test_source_and_lock_changes_reject_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Cargo.lock").write_bytes(b"lock")
            initial = ("a" * 40, "")
            with (
                patch.object(audit, "ROOT", root),
                patch.object(audit, "inventory", return_value={}),
            ):
                with (
                    patch.object(
                        audit, "source_state", side_effect=[initial, ("b" * 40, "")]
                    ),
                    patch.object(audit, "run", return_value="{}"),
                ):
                    with self.assertRaisesRegex(ValueError, "audit_source_changed"):
                        audit.audit(audit.TARGETS[0])

                def changed(*args: Any) -> str:
                    (root / "Cargo.lock").write_bytes(b"changed")
                    return "{}"

                with (
                    patch.object(audit, "source_state", return_value=initial),
                    patch.object(audit, "run", side_effect=changed),
                ):
                    with self.assertRaisesRegex(ValueError, "audit_source_changed"):
                        audit.audit(audit.TARGETS[0])

    def test_failed_or_interrupted_audit_invalidates_previous_completion(self) -> None:
        for failure, state in (
            (ValueError("test"), "failed"),
            (KeyboardInterrupt(), "incomplete"),
        ):
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "report.json"
                output.write_text('{"overall":"completed"}', encoding="utf-8")
                with (
                    patch.object(
                        sys,
                        "argv",
                        [
                            "notice_audit",
                            "--target",
                            audit.TARGETS[0],
                            "--output",
                            str(output),
                        ],
                    ),
                    patch.object(audit, "audit", side_effect=failure),
                ):
                    with self.assertRaises(type(failure)):
                        audit.main()
                self.assertEqual(json.loads(output.read_bytes())["overall"], state)


if __name__ == "__main__":
    unittest.main()
