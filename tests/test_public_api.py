"""Public API baseline checks use synthetic signatures, not platform evidence."""

import io
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_public_api as api


class PublicApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / "target").mkdir()
        self.baseline = self.root / "baseline"
        self.outputs = {
            name: f"pub mod {package.replace('-', '_')}\npub fn value() -> u32\n".encode()
            for package, _, name in api.cases()
        }
        api.update_baseline(self.baseline, self.outputs)
        self.addCleanup(patch.stopall)
        patch.object(api, "ROOT", self.root).start()
        patch.object(api, "BASELINE", self.baseline).start()

    def test_all_feature_cases_have_fixed_settings_and_independent_files(self) -> None:
        self.assertEqual(len(api.cases()), 8)
        self.assertEqual(api.read_baseline(self.baseline), self.outputs)
        self.assertEqual(api.PROFILES["bare"], ["--no-default-features"])
        self.assertEqual(
            api.PROFILES["serde"], ["--no-default-features", "--features", "serde"]
        )
        self.assertEqual(
            api.PROFILES["schema"], ["--no-default-features", "--features", "schema"]
        )
        self.assertEqual(api.settings()["omitted_items"], ["blanket-impls"])

    def test_added_removed_and_changed_signatures_produce_diffs_without_acceptance(
        self,
    ) -> None:
        name = api.cases()[0][2]
        for contents in (
            self.outputs[name] + b"pub fn added()\n",
            self.outputs[name].split(b"pub fn")[0],
            self.outputs[name].replace(b"u32", b"u64"),
        ):
            with self.subTest(contents=contents):
                outputs = {**self.outputs, name: contents}
                result = api.compare(self.outputs, outputs, self.root / "diffs")
                self.assertEqual(sum(not item["matches"] for item in result), 1)
                diff = self.root / "diffs" / f"{name}.diff"
                self.assertTrue(diff.read_text().startswith("--- baseline/"))
                self.assertEqual(api.read_baseline(self.baseline), self.outputs)
        api.compare(self.outputs, self.outputs, self.root / "diffs")
        self.assertFalse((self.root / "diffs" / f"{name}.diff").exists())

    def test_changed_settings_missing_cases_or_tampered_snapshot_are_rejected(
        self,
    ) -> None:
        index = self.baseline / "index.json"
        original = index.read_bytes()
        manifest = json.loads(original)
        manifest["settings"]["tool"] = "different"
        index.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "baseline_settings"):
            api.read_baseline(self.baseline)
        manifest = json.loads(original)
        del manifest["files"][api.cases()[0][2]]
        index.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "baseline_cases"):
            api.read_baseline(self.baseline)
        index.write_bytes(original)
        (self.baseline / api.cases()[0][2]).write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "baseline_hash"):
            api.read_baseline(self.baseline)

    def test_incomplete_or_interrupted_update_cannot_pass_hash_validation(self) -> None:
        before = (self.baseline / "index.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "incomplete_generation"):
            api.update_baseline(self.baseline, {})
        self.assertEqual((self.baseline / "index.json").read_bytes(), before)
        write = api.atomic_write
        outputs = {
            name: data.replace(b"u32", b"u64") for name, data in self.outputs.items()
        }
        calls = 0

        def interrupted(path: Path, data: bytes) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated interruption")
            write(path, data)

        with patch.object(api, "atomic_write", side_effect=interrupted):
            with self.assertRaises(OSError):
                api.update_baseline(self.baseline, outputs)
        self.assertEqual((self.baseline / "index.json").read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "baseline_hash"):
            api.read_baseline(self.baseline)
        api.update_baseline(self.baseline, outputs)
        self.assertEqual(api.read_baseline(self.baseline), outputs)

    def test_failed_atomic_replace_closes_and_removes_temporary_file(self) -> None:
        path = self.root / "original"
        path.write_bytes(b"old")
        with patch.object(Path, "replace", side_effect=OSError("replacement failed")):
            with self.assertRaises(OSError):
                api.atomic_write(path, b"new")
        self.assertEqual(path.read_bytes(), b"old")
        self.assertEqual(list(self.root.glob(".api-*")), [])

    def test_normalization_keeps_signatures_and_rejects_wrong_crate_or_color(
        self,
    ) -> None:
        package = api.PACKAGES[0]
        sample = self.outputs[api.cases()[0][2]]
        self.assertEqual(api.normalize(sample.replace(b"\n", b"\r\n"), package), sample)
        for invalid in (b"", b"pub mod other\n", sample + b"\x1b[0m"):
            with self.assertRaises(ValueError):
                api.normalize(invalid, package)

    def test_collect_uses_locked_explicit_target_and_correct_feature_flags(
        self,
    ) -> None:
        commands = []

        def run(arguments: list[str], timeout: int = 240) -> bytes:
            commands.append(arguments)
            if arguments[0] == "rustup":
                package = arguments[arguments.index("-p") + 1]
                build = Path(arguments[arguments.index("--target-dir") + 1])
                path = build / "native-target/doc" / f"{package.replace('-', '_')}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}")
                return b""
            path = Path(arguments[arguments.index("--rustdoc-json") + 1])
            return f"pub mod {path.stem}\n".encode()

        with patch.object(api, "run", side_effect=run):
            outputs = api.collect(Path("tool"), "native-target", offline=True)
        self.assertEqual(len(outputs), 8)
        builds = commands[::2]
        self.assertEqual(len(builds), 8)
        for arguments, (_, profile, _) in zip(builds, api.cases(), strict=True):
            for flag in ("--locked", "--offline", "--lib", "--target", "--target-dir"):
                self.assertIn(flag, arguments)
            self.assertEqual("--no-default-features" in arguments, profile != "default")
            self.assertEqual(arguments[2], api.TOOLCHAIN)
        self.assertEqual(list((self.root / "target").iterdir()), [])

    def test_dirty_or_changed_source_never_generates_a_new_baseline(self) -> None:
        with (
            patch.object(api, "source_state", return_value=("a" * 40, "dirty")),
            patch.object(api, "run") as run,
        ):
            with self.assertRaisesRegex(ValueError, "dirty_checkout"):
                api.check(Path("tool"), offline=True, update=False)
        run.assert_not_called()
        responses = [
            f"cargo-public-api {api.TOOL_VERSION}".encode(),
            b"rustc pinned\nhost: x86_64-pc-windows-msvc\n",
        ]
        with (
            patch.object(
                api, "source_state", side_effect=[("a" * 40, ""), ("b" * 40, "")]
            ),
            patch.object(api, "run", side_effect=responses),
            patch.object(api, "collect", return_value=self.outputs),
        ):
            with self.assertRaisesRegex(ValueError, "source_changed"):
                api.check(Path("tool"), offline=True, update=True)
        self.assertEqual(api.read_baseline(self.baseline), self.outputs)

    def test_child_output_bounds_and_compiler_environment_are_local(self) -> None:
        def child(arguments: list[str], **kwargs: Any) -> Any:
            self.assertNotIn("RUSTC", kwargs["env"])
            self.assertEqual(kwargs["env"]["CARGO_ENCODED_RUSTFLAGS"], "")
            kwargs["stdout"].write(b"x" * 17)
            return type("Status", (), {"returncode": 0})()

        with (
            patch.dict(
                os.environ, {"RUSTC": "custom", "CARGO_ENCODED_RUSTFLAGS": "custom"}
            ),
            patch.object(api, "MAX_OUTPUT", 16),
            patch.object(api.subprocess, "run", side_effect=child),
        ):
            with self.assertRaisesRegex(ValueError, "output_limit"):
                api.run(["tool"])
            self.assertEqual(os.environ["RUSTC"], "custom")
            self.assertEqual(os.environ["CARGO_ENCODED_RUSTFLAGS"], "custom")

    def test_failure_or_interrupt_invalidates_previous_successful_report(self) -> None:
        output = self.root / "report.json"
        for error, state in (
            (ValueError("PRIVATE"), "failed"),
            (KeyboardInterrupt(), "incomplete"),
        ):
            output.write_text('{"overall":"passed"}')
            with (
                patch.object(
                    sys, "argv", ["check_public_api", "--output", str(output)]
                ),
                patch.object(api, "check", side_effect=error),
                patch.object(sys, "stdout", io.StringIO()),
            ):
                with self.assertRaises(type(error)):
                    api.main()
            report = json.loads(output.read_bytes())
            self.assertEqual(report["overall"], state)
            self.assertNotIn("PRIVATE", str(report))


if __name__ == "__main__":
    unittest.main()
