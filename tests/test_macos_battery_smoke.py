"""Anonymous SDK fixtures are not physical battery observations."""

import copy
import json
from pathlib import Path
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import macos_battery_smoke as smoke


def sdk_row(**changes: int) -> dict[str, int]:
    return (
        dict(
            type=1,
            present=1,
            current_kind=1,
            current=50,
            maximum_kind=1,
            maximum=200,
            power=1,
        )
        | changes
    )


def sdk(*rows: dict[str, int]) -> dict[str, object]:
    return {"status": "ok", "source_count": len(rows), "records": list(rows)}


def observed(state: str, reason: str | None, value: object) -> dict[str, object]:
    return {
        "value": value,
        "availability": state,
        "reason": reason,
        "source": "iokit",
        "observed_at": 1 if state == "available" else None,
    }


class MacosBatterySmokeTests(unittest.TestCase):
    def test_clean_git_status_can_have_empty_output(self) -> None:
        self.assertEqual(smoke.run([sys.executable, "-c", "pass"]), b"")

    def test_sdk_percent_zero_scaled_and_power_states(self) -> None:
        for current, maximum, percent in (
            (0, 100, 0.0),
            (50, 200, 25.0),
            (100, 100, 100.0),
        ):
            self.assertEqual(
                smoke.expected(sdk(sdk_row(current=current, maximum=maximum)))[2],
                [("available", None, percent, "available", None, True)],
            )
        self.assertEqual(
            smoke.expected(sdk(sdk_row(power=2)))[2],
            [("available", None, 25.0, "available", None, False)],
        )
        self.assertEqual(
            smoke.expected(sdk(sdk_row(power=3)))[2],
            [("available", None, 25.0, "unavailable", "temporarily_unavailable", None)],
        )
        for changes, reason in (
            ({"current": -1}, "invalid_data"),
            ({"maximum": 0}, "invalid_data"),
            ({"current_kind": 0}, "not_present"),
            ({"maximum_kind": 2}, "invalid_data"),
        ):
            self.assertEqual(
                smoke.expected(sdk(sdk_row(**changes)))[2],
                [("unavailable", reason, None, "available", None, True)],
            )

    def test_sdk_filter_empty_unknown_and_invalid_shape(self) -> None:
        self.assertEqual(
            smoke.expected(sdk(sdk_row(type=0), sdk_row(present=0))),
            ("available", None, []),
        )
        for kind, state, reason in (
            (-2, "unavailable", "unknown"),
            (-1, "unavailable", "invalid_data"),
            (2, "unsupported", "not_supported"),
        ):
            self.assertEqual(
                smoke.expected(sdk(sdk_row(type=kind))), (state, reason, None)
            )
        for data in (
            sdk(sdk_row(type=99)),
            sdk(sdk_row(current=True)),
            dict(sdk(), source_count=1),
            dict(sdk(), status="invalid_count"),
            dict(sdk(sdk_row()), records=[dict(sdk_row(), private="PRIVATE")]),
        ):
            with self.subTest(data=data), self.assertRaises(ValueError):
                smoke.expected(data)

    def test_public_fields_comparison_and_default_privacy(self) -> None:
        before = sdk(sdk_row())
        snapshot: dict[str, Any] = {
            "capabilities": [
                {"field": "batteries", "level": "partial", "source": "iokit"}
            ],
            "dynamic": {
                "batteries": observed(
                    "available",
                    None,
                    [
                        {
                            "charge_percent": observed("available", None, 25.0),
                            "on_ac_power": observed("available", None, True),
                        }
                    ],
                )
            },
        }
        with patch.object(smoke, "check_snapshot"):
            self.assertEqual(smoke.check(snapshot, before), 1)
            for key, value in (
                ("charge_percent", observed("available", None, 50.0)),
                ("on_ac_power", observed("available", None, False)),
                ("private_id", "PRIVATE"),
            ):
                bad = copy.deepcopy(snapshot)
                bad["dynamic"]["batteries"]["value"][0][key] = value
                with self.subTest(key=key), self.assertRaises(ValueError):
                    smoke.check(bad, before)
            bad = copy.deepcopy(snapshot)
            bad["dynamic"]["batteries"]["value"][0]["charge_percent"]["source"] = (
                "sysinfo"
            )
            with self.assertRaises(ValueError):
                smoke.check(bad, before)

    def test_failed_and_interrupted_runs_do_not_keep_old_success(self) -> None:
        for error, state in (
            (ValueError("PRIVATE"), "failed"),
            (KeyboardInterrupt(), "incomplete"),
        ):
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "report.json"
                output.write_text('{"overall":"passed"}', encoding="ascii")
                with (
                    patch.object(sys, "argv", ["battery", "--output", str(output)]),
                    patch.object(smoke, "collect", side_effect=error),
                ):
                    with self.assertRaises(type(error)):
                        smoke.main()
                report = json.loads(output.read_bytes())
                self.assertEqual(report["overall"], state)
                self.assertNotIn("PRIVATE", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
