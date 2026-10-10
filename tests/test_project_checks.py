"""Regression checks for repository data and documentation validation."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from check_project import check_file


class ProjectChecks(unittest.TestCase):
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
