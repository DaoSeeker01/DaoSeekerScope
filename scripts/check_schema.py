"""Verify generated schema/golden drift and observation invariants (jsonschema dev dependency)."""

import copy
import json
import pathlib
import subprocess
import sys
import jsonschema

root = pathlib.Path(__file__).resolve().parent.parent
schema = json.loads(
    (root / "docs/schema/snapshot-v1.schema.json").read_text(encoding="utf-8")
)
fixture = json.loads(
    (root / "tests/fixtures/snapshot-v1.json").read_text(encoding="utf-8")
)
jsonschema.Draft202012Validator.check_schema(schema)
validator = jsonschema.Draft202012Validator(schema)
validator.validate(fixture)
for width, height in ((0, 1080), (1920, 0), (0, 0), (1920, 1080)):

    def observed(value: object) -> dict[str, object]:
        return dict(
            value=value,
            availability="available",
            source="custom",
            observed_at=1,
            reason=None,
        )

    display = copy.deepcopy(fixture)
    display["static_info"]["displays"] = observed(
        [dict(width_pixels=observed(width), height_pixels=observed(height))]
    )
    if bool(list(validator.iter_errors(display))) != (width == 0 or height == 0):
        raise ValueError("display extent schema mismatch")
for args, expected in [
    (["--example", "schema", "--features", "schema"], schema),
    (["--example", "golden"], fixture),
]:
    output = subprocess.check_output(
        ["cargo", "run", "--locked", "--quiet", "-p", "daoseeker-scope", *args],
        cwd=root,
    )
    if json.loads(output) != expected:
        raise ValueError(f"generated artifact drift: {args}")
for field, value in [
    ("availability", "available"),
    ("value", "fake"),
    ("observed_at", 1),
    ("reason", None),
]:
    bad = copy.deepcopy(fixture)
    bad["static_info"]["system"]["device"]["serial_number"][field] = value
    if not list(validator.iter_errors(bad)):
        raise ValueError(f"schema accepted inconsistent observation: {field}")
future = copy.deepcopy(fixture)
future["unknown_future_field"] = True
validator.validate(future)
wrong_version = copy.deepcopy(fixture)
wrong_version["schema_version"] = 2
if not list(validator.iter_errors(wrong_version)):
    raise ValueError("schema accepted wrong version")
if len(sys.argv) > 1:
    validator.validate(
        json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    )
print(
    "schema: golden/generated drift, observation invariants, unknown fields and version passed"
)
