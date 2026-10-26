"""Regression checks for repository data and documentation validation."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from check_project import check_file, check_versions


class ProjectChecks(unittest.TestCase):
    def test_yaml_syntax_and_duplicate_keys(self) -> None:
        import yaml

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yml"
            path.write_text("permissions:\n  contents: read\n", encoding="utf-8")
            self.assertEqual(check_file(path), 0)
            for invalid in (
                "name: [",
                "permissions: read\npermissions: write\n",
                "outer:\n  key: a\n  key: b\n",
            ):
                path.write_text(invalid, encoding="utf-8")
                with self.assertRaises((ValueError, yaml.YAMLError)):
                    check_file(path)

    def test_internal_version_and_changelog_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = '[workspace.package]\nversion="0.1.0"\n[workspace.dependencies]\nexample={path="crates/example",version="0.1.0"}\n'
            (root / "Cargo.toml").write_text(manifest, encoding="utf-8")
            (root / "CHANGELOG.md").write_text(
                "## 未发布 · 0.1.0 开发中\n", encoding="utf-8"
            )
            crate = root / "crates/example"
            crate.mkdir(parents=True)
            (crate / "Cargo.toml").write_text(
                "[package]\nversion.workspace=true\n", encoding="utf-8"
            )
            self.assertEqual(check_versions(root), [])
            (root / "Cargo.toml").write_text(
                manifest.replace('version="0.1.0"}', 'version="0.2.0"}'),
                encoding="utf-8",
            )
            self.assertIn(
                "workspace dependency version drift: example", check_versions(root)
            )
            (crate / "Cargo.toml").write_text(
                '[package]\nversion="0.1.0"\n', encoding="utf-8"
            )
            self.assertIn(
                "crate version must inherit workspace: example", check_versions(root)
            )
            (root / "CHANGELOG.md").write_text("## 未发布\n", encoding="utf-8")
            self.assertIn(
                "current version missing from unreleased changelog",
                check_versions(root),
            )

    def test_structured_data_and_python_syntax(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for name, content in [
                ("bad.json", "{broken}"),
                ("nan.json", "NaN"),
                ("bad.toml", "["),
                ("bad.py", "def broken(:"),
            ]:
                item = path / name
                item.write_text(content, encoding="utf-8")
                with self.assertRaises((ValueError, SyntaxError)):
                    check_file(item)

    def test_missing_local_link_and_external_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "README.md"
            path.write_text(
                "[external](https://example.com) [anchor](#title)", encoding="utf-8"
            )
            self.assertEqual(check_file(path), 0)
            path.write_text("[missing](missing.md)", encoding="utf-8")
            with self.assertRaises(ValueError):
                check_file(path)
            (path.parent / "present.md").write_text("present", encoding="utf-8")
            path.write_text("[present](present.md#title)", encoding="utf-8")
            self.assertEqual(check_file(path), 1)


if __name__ == "__main__":
    unittest.main()
