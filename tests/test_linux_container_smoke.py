"""Evidence validator unit fixtures; no Docker/native execution is claimed here."""

import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import linux_container_smoke as smoke


def observed(state="available", reason=None, source="sysfs", value=None):
    return {
        "availability": state,
        "reason": reason,
        "source": source,
        "value": value,
        "observed_at": 1000 if state == "available" else None,
    }


def snapshot(scenario):
    result = json.loads(
        (smoke.ROOT / "tests/fixtures/snapshot-v1.json").read_text("utf-8")
    )
    system = result["static_info"]["system"]
    for field, name in smoke.DMI_FIELDS.items():
        group, key = field.split(".")[1:]
        state, reason, value = "available", None, smoke.FIXTURE_VALUES[name]
        if scenario == "missing_dmi":
            state, reason, value = "unavailable", "not_present", None
        elif scenario == "denied_dmi":
            state, reason, value = "restricted", "permission_denied", None
        elif scenario == "mixed_dmi":
            state, reason, value = {
                "product_name": ("unavailable", "invalid_data", None),
                "sys_vendor": ("restricted", "permission_denied", None),
                "board_vendor": ("available", None, smoke.FIXTURE_VALUES[name]),
                "board_name": ("unavailable", "not_present", None),
                "bios_vendor": ("unavailable", "invalid_data", None),
                "bios_version": ("unavailable", "invalid_data", None),
            }[name]
        system[group][key] = observed(state, reason, value=value)
    system["device"]["serial_number"] = (
        observed(value=smoke.FIXTURE_SERIAL)
        if scenario == "authorized_serial"
        else observed("restricted", "permission_denied")
        if scenario == "denied_serial"
        else observed("restricted", "privacy_redacted", "custom")
    )
    for field, value in {
        "system.os.name": "Unit Ubuntu",
        "system.cpu.brand": "Unit CPU",
        "system.cpu.logical_count": 4,
        "system.memory.total_usable_bytes": 8589934592,
        "memory_available_bytes": 4294967296,
    }.items():
        node = (
            result["static_info"] if field.startswith("system.") else result["dynamic"]
        )
        parts = field.split(".")
        for part in parts[:-1]:
            node = node[part]
        memory = field in ("system.memory.total_usable_bytes", "memory_available_bytes")
        source = "procfs" if memory else "sysinfo"
        node[parts[-1]] = (
            observed("unavailable", "invalid_data" if memory else "unknown", source)
            if scenario == "empty_proc_inputs" and field != "system.os.name"
            else observed(source=source, value=value)
        )
    fields = [
        *smoke.DMI_FIELDS,
        "system.device.serial_number",
        "system.os.name",
        "system.cpu.brand",
        "system.cpu.logical_count",
        "system.memory.total_usable_bytes",
        "memory_available_bytes",
    ]
    for cap in result["capabilities"]:
        if cap["field"] in fields:
            item = smoke.observation(result, cap["field"])
            cap.update(
                source=item["source"],
                reason=item["reason"],
                level="restricted"
                if item["availability"] == "restricted"
                else "partial"
                if item["source"] == "sysinfo"
                else "supported",
            )
    return result


class ContainerEvidenceGuards(unittest.TestCase):
    def test_all_scenarios_preserve_metadata_without_serial_values(self):
        for scenario in smoke.SCENARIOS:
            with self.subTest(scenario=scenario):
                result = smoke.validate_snapshot(snapshot(scenario), scenario)
                self.assertTrue(result["schema_validated"])
                self.assertNotIn(smoke.FIXTURE_SERIAL, json.dumps(result))
                self.assertNotIn(
                    "value", result["observations"]["system.device.serial_number"]
                )

    def test_permissions_absence_and_invalid_data_cannot_be_interchanged(self):
        for scenario, wrong in [
            ("missing_dmi", "permission_denied"),
            ("denied_dmi", "not_present"),
            ("mixed_dmi", "unknown"),
        ]:
            bad = snapshot(scenario)
            bad["static_info"]["system"]["device"]["model"]["reason"] = wrong
            with self.assertRaises(smoke.ValidationFailure):
                smoke.validate_snapshot(bad, scenario)

    def test_capability_and_single_bad_field_are_checked(self):
        bad = snapshot("mixed_dmi")
        self.assertEqual(
            smoke.validate_snapshot(bad, "mixed_dmi")["observations"][
                "system.motherboard.vendor"
            ]["availability"],
            "available",
        )
        for cap in bad["capabilities"]:
            if cap["field"] == "system.device.vendor":
                cap["level"] = "supported"
        with self.assertRaises(smoke.ValidationFailure):
            smoke.validate_snapshot(bad, "mixed_dmi")

    def test_empty_proc_never_accepts_available_zero_or_fake_positive(self):
        for value in [0, 4096]:
            bad = snapshot("empty_proc_inputs")
            bad["static_info"]["system"]["memory"]["total_usable_bytes"] = observed(
                source="sysinfo", value=value
            )
            with self.assertRaises(smoke.ValidationFailure):
                smoke.validate_snapshot(bad, "empty_proc_inputs")

    def test_sensitive_authorization_checks_exact_fixture_and_os_permission(self):
        bad = snapshot("authorized_serial")
        bad["static_info"]["system"]["device"]["serial_number"]["value"] = "Wrong"
        with self.assertRaises(smoke.ValidationFailure):
            smoke.validate_snapshot(bad, "authorized_serial")
        with self.assertRaises(smoke.ValidationFailure):
            smoke.validate_snapshot(snapshot("authorized_serial"), "denied_serial")

    def test_container_configuration_requires_no_privilege_and_resource_limits(self):
        config = {
            "user": "65534:65534",
            "mounts": [{"RW": False}],
            "host": {
                "ReadonlyRootfs": True,
                "NetworkMode": "none",
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges=true"],
                "Memory": 268435456,
                "MemorySwap": 268435456,
                "PidsLimit": 32,
                "NanoCpus": 1000000000,
                "Ulimits": [{"Name": "nofile", "Soft": 64, "Hard": 64}],
            },
        }
        smoke.check_config(config)
        for field, value in [
            ("ReadonlyRootfs", False),
            ("CapDrop", []),
            ("NetworkMode", "default"),
            ("Memory", 0),
            ("PidsLimit", 0),
            ("NanoCpus", 0),
        ]:
            bad = copy.deepcopy(config)
            bad["host"][field] = value
            with self.assertRaises(smoke.ValidationFailure):
                smoke.check_config(bad)

    def test_failure_and_incomplete_execution_cannot_reuse_success(self):
        for error in [smoke.ValidationFailure("container: cli_failed"), None]:
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "report.json"
                output.write_text('{"overall":"passed"}', encoding="utf-8")
                with (
                    patch.object(sys, "argv", ["smoke", "--output", str(output)]),
                    patch.object(smoke, "execute", side_effect=error),
                    patch.object(sys, "stdout", io.StringIO()),
                ):
                    self.assertEqual(smoke.main(), 1)
                result = json.loads(output.read_text("utf-8"))
                self.assertEqual(result["overall"], "failed")
                self.assertTrue(
                    all(
                        item["status"] == "not_run"
                        for item in result["scenarios"].values()
                    )
                )

    def test_interruption_replaces_stale_pass_with_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            output.write_text('{"overall":"passed"}', encoding="utf-8")
            with (
                patch.object(sys, "argv", ["smoke", "--output", str(output)]),
                patch.object(smoke, "execute", side_effect=KeyboardInterrupt),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    smoke.main()
            self.assertEqual(
                json.loads(output.read_text("utf-8"))["overall"], "incomplete"
            )


if __name__ == "__main__":
    unittest.main()
