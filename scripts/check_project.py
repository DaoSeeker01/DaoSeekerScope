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

import yaml

ROOT = Path(__file__).resolve().parent.parent


class UniqueYamlLoader(yaml.SafeLoader):
    """Repository configuration must not silently override duplicate keys."""


def yaml_mapping(
    loader: UniqueYamlLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[object, object]:
    loader.flatten_mapping(node)
    result: dict[object, object] = {}
    for key, value in loader.construct_pairs(node, deep=deep):
        if key in result:
            raise ValueError("duplicate YAML key")
        result[key] = value
    return result


UniqueYamlLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, yaml_mapping
)


def check_versions(root: Path) -> list[str]:
    """Catch internal crate/version drift without changing historical evidence."""
    workspace = tomllib.loads((root / "Cargo.toml").read_text(encoding="utf-8"))[
        "workspace"
    ]
    version = workspace["package"]["version"]
    failures = []
    for name, dependency in workspace.get("dependencies", {}).items():
        if (
            isinstance(dependency, dict)
            and "path" in dependency
            and dependency.get("version") != version
        ):
            failures.append(f"workspace dependency version drift: {name}")
    for path in sorted((root / "crates").glob("*/Cargo.toml")):
        package = tomllib.loads(path.read_text(encoding="utf-8"))["package"]
        if package.get("version") != {"workspace": True}:
            failures.append(f"crate version must inherit workspace: {path.parent.name}")
    if f"## 未发布 · {version}" not in (root / "CHANGELOG.md").read_text(
        encoding="utf-8"
    ):
        failures.append("current version missing from unreleased changelog")
    return failures


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
    elif path.suffix in (".yml", ".yaml"):
        yaml.load(data.decode("utf-8"), Loader=UniqueYamlLoader)
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
        except (OSError, ValueError, SyntaxError, yaml.YAMLError) as error:
            failures.append(f"{name}: {error}")
    try:
        failures.extend(check_versions(ROOT))
    except (OSError, ValueError, KeyError, TypeError) as error:
        failures.append(f"version configuration: {error}")
    for copy in [
        "crates/daoseeker-scope/tests/fixtures/snapshot-v1.json",
        "fuzz/corpus/snapshot_json/valid-v1.json",
    ]:
        if (ROOT / copy).read_bytes() != (
            ROOT / "tests/fixtures/snapshot-v1.json"
        ).read_bytes():
            failures.append(f"golden fixture drift: {copy}")
    for manifest in (ROOT / "crates").glob("*/Cargo.toml"):
        license_copy = manifest.parent / "LICENSE-MIT"
        if (
            not license_copy.is_file()
            or license_copy.read_bytes() != (ROOT / "LICENSE-MIT").read_bytes()
        ):
            failures.append(f"package license drift: {manifest.parent.name}")
    if (ROOT / "bindings/daoseeker_scope.h").read_bytes() != (
        ROOT / "crates/daoseeker-scope-ffi/include/daoseeker_scope.h"
    ).read_bytes():
        failures.append("packaged C header drift")
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
