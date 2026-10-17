"""Compare separate SDK/CLI/C observations, preserving missing states and no IDs."""

from __future__ import annotations
import json
from pathlib import Path
import subprocess
from typing import Any
from native_smoke import (
    ROOT,
    MAX_JSON_BYTES,
    ValidationFailure,
    check_macos_display_dimensions,
)


def error(code: int) -> tuple[str, str]:
    if code in (-1, 1001, 1007, 1008):
        return "unavailable", "invalid_data"
    if code in (-2, 1002, 1003, 1004, 1010):
        return "unavailable", "temporarily_unavailable"
    if code == 1006:
        return "unsupported", "not_supported"
    if code == 1011:
        return "unavailable", "not_present"
    return "unavailable", "unknown"


def compare(probe: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    try:
        if (
            set(probe) != {"status", "entries", "dimensions"}
            or type(probe["status"]) is not int
        ):
            raise ValidationFailure("sdk: malformed")
        if report["overall"] != "passed" or report["git_dirty"] is not False:
            raise ValidationFailure("sdk: native_incomplete")
        rows = []
        if probe["status"] == 0:
            if (
                type(probe["entries"]) is not int
                or not 0 <= probe["entries"] <= 128
                or not isinstance(probe["dimensions"], list)
                or len(probe["dimensions"]) != probe["entries"]
            ):
                raise ValidationFailure("sdk: count")
            for pair in probe["dimensions"]:
                if set(pair) != {"width", "height", "reason"}:
                    raise ValidationFailure("sdk: dimensions")
                if pair["reason"] is None:
                    if any(
                        type(pair[k]) is not int or not 1 <= pair[k] <= 0xFFFFFFFF
                        for k in ("width", "height")
                    ):
                        raise ValidationFailure("sdk: dimensions")
                elif (
                    pair["reason"] not in ("temporarily_unavailable", "invalid_data")
                    or pair["width"] is not None
                    or pair["height"] is not None
                ):
                    raise ValidationFailure("sdk: missing_dimensions")
                rows.append(
                    (pair["reason"] or "", pair["width"] or 0, pair["height"] or 0)
                )
        elif probe["entries"] is not None or probe["dimensions"] is not None:
            raise ValidationFailure("sdk: error_with_values")
        for label in ("cli", "c_abi"):
            observed = report["observations"][label]["static.display_summary"]
            if observed["source"] != "apple_api":
                raise ValidationFailure("sdk: source")
            if probe["status"] != 0:
                if (
                    (observed["availability"], observed["reason"])
                    != error(probe["status"])
                    or observed["observed_at"] is not None
                    or "entries" in observed
                ):
                    raise ValidationFailure("sdk: missing_state_mismatch")
                continue
            if (
                observed["availability"] != "available"
                or type(observed["entries"]) is not int
                or observed["entries"] != probe["entries"]
                or type(observed["observed_at"]) is not int
                or observed["observed_at"] < 0
                or observed["reason"] is not None
                or type(observed["names_available"]) is not int
                or observed["names_available"] != 0
                or not isinstance(observed["dimensions"], list)
                or len(observed["dimensions"]) != probe["entries"]
            ):
                raise ValidationFailure("sdk: enumeration_mismatch")
            actual = []
            for pair in observed["dimensions"]:
                check_macos_display_dimensions(pair)
                w, h = pair["width_pixels"], pair["height_pixels"]
                actual.append((w["reason"] or "", w["value"] or 0, h["value"] or 0))
            if sorted(actual) != sorted(rows):
                raise ValidationFailure("sdk: pixel_or_state_mismatch")
            if type(observed["dimensions_available"]) is not int or observed[
                "dimensions_available"
            ] != sum(not reason for reason, _, _ in actual):
                raise ValidationFailure("sdk: dimensions_count")
        return dict(
            status="passed",
            source_commit=report["git_revision"],
            sdk_status=probe["status"],
            entries=probe["entries"],
            dimensions=probe["dimensions"],
            comparison="separate SDK/CLI/C active-view counts and mode-pixel/state multisets match; sequential calls, not atomic topology proof",
        )
    except (KeyError, TypeError) as exc:
        raise ValidationFailure("sdk: malformed") from exc


def read(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        data = file.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise ValidationFailure("sdk: input_limit")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValidationFailure("sdk: malformed")
    return value


def main() -> int:
    output = ROOT / "target/macos-display-comparison.json"
    result: dict[str, Any] = dict(status="incomplete")
    output.write_text(json.dumps(result) + "\n", "utf-8")
    try:
        report = read(ROOT / "target/native-evidence.json")
        source = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        if report["git_revision"] != source:
            raise ValidationFailure("sdk: source_commit")
        result = compare(read(ROOT / "target/macos-display-probe.json"), report)
    except (
        ValidationFailure,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        result = dict(
            status="failed",
            failure=str(exc)
            if isinstance(exc, ValidationFailure)
            else "prerequisite_or_input_failed",
        )
    output.write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    print("macOS display SDK comparison: " + result["status"])
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
