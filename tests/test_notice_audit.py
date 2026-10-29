"""Notice inventory fixtures do not establish upstream licensing completeness."""

import json
from pathlib import Path
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import notice_audit as audit
from cli_bundle import dependency_payload, digest


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
