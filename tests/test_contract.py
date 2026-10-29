"""Contract drift guards; native compiler measurements run separately in CI."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_contract as contract


class ContractChecks(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = json.loads((contract.ROOT / contract.BASELINE).read_bytes())
        self.rust = deepcopy(self.baseline["native_layout"])
        self.rust["schema_version"] = self.baseline["schema_version"]
        self.c = deepcopy(self.baseline["native_layout"])
        self.c["status_codes"] = self.baseline["status_codes"].copy()

    def test_reviewed_contract_matches_checkout(self) -> None:
        contract.check_static(contract.ROOT, self.baseline)
        contract.compare_probes(self.c, self.rust, self.baseline)

    def test_schema_formatting_is_ignored_but_annotations_are_reviewed(self) -> None:
        self.assertEqual(
            contract.canonical_hash({"type": "object", "title": "A"}),
            contract.canonical_hash(json.loads('{"title":"A","type":"object"}')),
        )
        self.assertNotEqual(
            contract.canonical_hash({"title": "A"}),
            contract.canonical_hash({"title": "B"}),
        )

    def test_manifest_version_feature_and_license_drift_require_review(self) -> None:
        for key, value in (("version", "0.2.0"), ("license", "Apache-2.0")):
            with self.subTest(key=key):
                baseline = deepcopy(self.baseline)
                baseline["manifests"]["package"][key] = value
                with self.assertRaisesRegex(ValueError, "manifest_drift"):
                    contract.check_static(contract.ROOT, baseline)
        baseline = deepcopy(self.baseline)
        baseline["manifests"]["crates"]["daoseeker-scope"]["features"]["default"] = []
        with self.assertRaisesRegex(ValueError, "manifest_drift"):
            contract.check_static(contract.ROOT, baseline)

    def test_changed_schema_fails_even_when_generated_schema_also_changes(self) -> None:
        baseline = deepcopy(self.baseline)
        baseline["schema_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "schema_drift"):
            contract.check_static(contract.ROOT, baseline)

    def test_each_native_layout_dimension_is_checked(self) -> None:
        for side in ("c", "rust"):
            for field in ("size", "alignment", "offsets"):
                with self.subTest(side=side, field=field):
                    c, rust = deepcopy(self.c), deepcopy(self.rust)
                    probe = c if side == "c" else rust
                    probe["buffer"][field] = [0, 16, 8] if field == "offsets" else 32
                    with self.assertRaisesRegex(ValueError, "native_layout_drift"):
                        contract.compare_probes(c, rust, self.baseline)

    def test_both_compilers_agreeing_on_wrong_layout_is_still_rejected(self) -> None:
        self.c["options"]["size"] = self.rust["options"]["size"] = 24
        with self.assertRaisesRegex(ValueError, "native_layout_drift"):
            contract.compare_probes(self.c, self.rust, self.baseline)

    def test_wrong_versions_status_codes_and_types_are_rejected(self) -> None:
        for kind in ("abi", "schema", "status", "bool", "float", "extra"):
            with self.subTest(kind=kind):
                c, rust = deepcopy(self.c), deepcopy(self.rust)
                if kind == "abi":
                    c["abi_version"] = 2
                elif kind == "schema":
                    rust["schema_version"] = 2
                elif kind == "status":
                    c["status_codes"][9] = 8
                elif kind == "bool":
                    c["abi_version"] = True
                elif kind == "float":
                    rust["pointer_bytes"] = 8.0
                else:
                    c["unreviewed"] = 1
                with self.assertRaises(ValueError):
                    contract.compare_probes(c, rust, self.baseline)

    def test_malformed_probe_is_rejected(self) -> None:
        malformed: list[Any] = [[], None, "{}", {}]
        for bad in malformed:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                contract.compare_probes(bad, self.rust, self.baseline)

    def test_source_revision_and_dirty_state_must_remain_identical(self) -> None:
        initial = ("a" * 40, "")
        for changed in (("b" * 40, ""), (initial[0], " M Cargo.toml")):
            with patch.object(contract, "source_state", return_value=changed):
                with self.assertRaisesRegex(ValueError, "source_changed"):
                    contract.verify_source(initial)

    def test_dirty_source_is_rejected_before_build(self) -> None:
        with patch.object(contract, "source_state", return_value=("a" * 40, "dirty")):
            with patch.object(contract, "run") as run:
                with self.assertRaisesRegex(ValueError, "dirty_checkout"):
                    contract.check_native()
                run.assert_not_called()

    def test_unreviewed_native_target_is_rejected(self) -> None:
        with patch.object(contract, "source_state", return_value=("a" * 40, "")):
            with patch.object(
                contract, "run", return_value=b"host: wasm32-unknown-unknown\n"
            ):
                with self.assertRaisesRegex(ValueError, "unreviewed_native_target"):
                    contract.check_native()

    def test_source_state_normalizes_git_newlines(self) -> None:
        with patch.object(contract, "run", side_effect=[b"abc\r\n", b"\r\n"]):
            self.assertEqual(contract.source_state(), ("abc", ""))

    def test_failed_and_interrupted_runs_invalidate_old_success(self) -> None:
        for failure, expected in (
            (ValueError("test"), "failed"),
            (KeyboardInterrupt(), "incomplete"),
        ):
            with (
                self.subTest(failure=type(failure).__name__),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                output = root / "target/contract-evidence.json"
                output.parent.mkdir()
                output.write_text('{"overall":"passed"}', encoding="utf-8")
                with patch.object(contract, "ROOT", root):
                    with patch.object(contract, "check_native", side_effect=failure):
                        with self.assertRaises(type(failure)):
                            contract.main()
                self.assertEqual(json.loads(output.read_bytes())["overall"], expected)

    def test_child_failure_timeout_and_output_bound(self) -> None:
        with patch.object(contract.subprocess, "run", return_value=Mock(returncode=1)):
            with self.assertRaisesRegex(ValueError, "child_failed"):
                contract.run(["test"])
        with patch.object(
            contract.subprocess, "run", side_effect=subprocess.TimeoutExpired("test", 1)
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                contract.run(["test"], timeout=1)

        def too_much(*args: Any, **kwargs: Any) -> Mock:
            kwargs["stdout"].write(b"x" * (2 * 1024 * 1024 + 1))
            return Mock(returncode=0)

        with patch.object(contract.subprocess, "run", side_effect=too_much):
            with self.assertRaisesRegex(ValueError, "output_limit"):
                contract.run(["test"])


if __name__ == "__main__":
    unittest.main()
