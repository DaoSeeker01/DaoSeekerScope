"""Check tracked project files, structured data and local Markdown links."""

from __future__ import annotations

import ast
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import tomllib
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent


def check_file(path: Path) -> int:
    """Return checked local links; raw fuzz seeds are deliberately arbitrary bytes."""
    data = path.read_bytes()
    if path.suffix == ".json":

        def invalid_constant(value: str) -> None:
            raise ValueError(f"non-JSON constant: {value}")

        json.loads(data, parse_constant=invalid_constant)
    elif path.suffix == ".toml" or path.name == "Cargo.lock":
        tomllib.loads(data.decode("utf-8"))
    elif path.suffix == ".py":
        ast.parse(data.decode("utf-8"), filename=path.name)
    elif path.suffix == ".md":
        # Fenced examples may show illustrative links rather than actual links.
        text = re.sub(r"```.*?```", "", data.decode("utf-8"), flags=re.S)
        checked = 0
        for target in re.findall(r"\[[^\]\n]*\]\(([^)\n]+)\)", text):
            target = target.strip().split(" ", 1)[0].strip("<>")
            url = urlsplit(target)
            if url.scheme or url.netloc or not url.path:
                continue
            resolved = (path.parent / unquote(url.path)).resolve()
            if not resolved.exists():
                raise ValueError(f"missing local link: {target}")
            checked += 1
        return checked
    return 0


def main() -> None:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    )
    files = sorted(set(output.decode("utf-8").strip("\0").split("\0")))
    counts: Counter[str] = Counter()
    links = 0
    failures = []
    for name in files:
        path = ROOT / name
        counts[path.suffix or "no_extension"] += 1
        try:
            links += check_file(path)
        except (OSError, ValueError, SyntaxError) as error:
            failures.append(f"{name}: {error}")
    for copy in [
        "crates/daoseeker-scope/tests/fixtures/snapshot-v1.json",
        "fuzz/corpus/snapshot_json/valid-v1.json",
    ]:
        if (ROOT / copy).read_bytes() != (
            ROOT / "tests/fixtures/snapshot-v1.json"
        ).read_bytes():
            failures.append(f"golden fixture drift: {copy}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(
        json.dumps(
            {
                "files_read": len(files),
                "local_links_checked": links,
                "extensions": dict(sorted(counts.items())),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
