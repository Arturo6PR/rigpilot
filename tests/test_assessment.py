import contextlib
import copy
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from math import inf, nan
from pathlib import Path
from unittest.mock import Mock, patch

from jsonschema import Draft202012Validator, FormatChecker

from rigpilot.assessment import (
    HARDWARE_RULES,
    assess_snapshot,
    render_assessment_human,
    validate_assessment,
)
from rigpilot.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
GIB = 1024**3


def load_fixture(name: str = "snapshot-success-v1.json") -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def finding_ids(result: dict) -> list[str]:
    return [finding["rule_id"] for finding in result["findings"]]


def live_snapshot_model(payload: dict | None = None) -> Mock:
    source = load_fixture() if payload is None else payload
    snapshot = Mock()

    def to_dict(*, include_hostname: bool = True) -> dict:
        result = copy.deepcopy(source)
        if not include_hostname:
            result["hostname"] = None
        return result

    snapshot.to_dict.side_effect = to_dict
    return snapshot


class AssessmentRuleTests(unittest.TestCase):
    def test_clean_snapshot_matches_golden_fixture(self) -> None:
        expected = load_fixture("assessment-clean-v1.json")
        self.assertEqual(assess_snapshot(load_fixture()), expected)
        self.assertIn("No findings detected", render_assessment_human(expected))

    def test_probe_states_are_distinct_and_raw_messages_are_private(self) -> None:
        snapshot = load_fixture()
        snapshot["checks"]["cpu"] = {
            "status": "failed",
            "data": None,
            "message": "secret failure C:\\Private\\tool.exe",
            "duration_ms": 1.0,
        }
        snapshot["checks"]["git"] = {
            "status": "unavailable",
            "data": None,
            "message": "Skipped by selection: git",
            "duration_ms": 0.0,
        }
        snapshot["checks"]["nvidia_gpu"] = {
            "status": "unavailable",
            "data": None,
            "message": "Command not found: nvidia-smi",
            "duration_ms": 1.0,
        }
        snapshot["checks"]["uptime"] = {
            "status": "unavailable",
            "data": None,
            "message": "PowerShell is not available",
            "duration_ms": 1.0,
        }

        result = assess_snapshot(snapshot)

        self.assertEqual(
            finding_ids(result),
            ["probe.failed", "probe.unavailable", "probe.optional_unavailable", "probe.skipped"],
        )
        self.assertNotIn("secret failure", json.dumps(result))
        severities = {item["rule_id"]: item["severity"] for item in result["findings"]}
        self.assertEqual(severities["probe.failed"], "warning")
        self.assertEqual(severities["probe.unavailable"], "warning")
        self.assertEqual(severities["probe.optional_unavailable"], "info")
        self.assertEqual(severities["probe.skipped"], "info")

    def test_failed_storage_and_bios_suppress_dependent_rules(self) -> None:
        snapshot = load_fixture("snapshot-failure-v1.json")
        ids = finding_ids(assess_snapshot(snapshot))
        self.assertNotIn("storage.low_capacity", ids)
        self.assertNotIn("storage.critically_low_capacity", ids)
        self.assertFalse(any(rule.startswith("bios.release_date") for rule in ids))

    def test_disk_threshold_boundaries_use_strict_integer_comparisons(self) -> None:
        cases = [
            (100 * GIB, 5 * GIB - 1, "storage.critically_low_capacity"),
            (100 * GIB, 5 * GIB, "storage.low_capacity"),
            (400 * GIB, 10 * GIB, "storage.low_capacity"),
            (200 * GIB, 20 * GIB, None),
            (200 * GIB, 20 * GIB - 1, "storage.low_capacity"),
            (0, 0, None),
        ]
        for total, free, expected in cases:
            with self.subTest(total=total, free=free):
                snapshot = load_fixture()
                snapshot["checks"]["storage"]["data"] = [
                    {"DeviceID": "C:", "VolumeName": "SECRET", "Size": total, "FreeSpace": free}
                ]
                storage_ids = [
                    item["rule_id"]
                    for item in assess_snapshot(snapshot)["findings"]
                    if item["check"] == "storage"
                ]
                self.assertEqual(storage_ids, [] if expected is None else [expected])

    def test_multiple_volumes_are_deterministic_and_do_not_expose_labels(self) -> None:
        snapshot = load_fixture()
        snapshot["checks"]["storage"]["data"] = [
            {"DeviceID": "D:", "VolumeName": "PRIVATE-D", "Size": 100 * GIB, "FreeSpace": GIB},
            {"DeviceID": "C:", "VolumeName": "PRIVATE-C", "Size": 100 * GIB, "FreeSpace": GIB},
        ]
        result = assess_snapshot(snapshot)
        subjects = [item["subject"] for item in result["findings"]]
        self.assertEqual(subjects, ["C:", "D:"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_each_stable_hardware_category_detects_change(self) -> None:
        mutations = {
            "system": lambda data: data.update({"Model": "Different"}),
            "cpu": lambda data: data[0].update({"NumberOfCores": 9}),
            "memory_modules": lambda data: data[0].update({"Capacity": 1}),
            "physical_disks": lambda data: data[0].update({"Size": 2}),
            "nvidia_gpu": lambda data: data[0].update({"memory_total_mib": 1}),
        }
        expected = {
            "system": "hardware.system_changed",
            "cpu": "hardware.cpu_changed",
            "memory_modules": "hardware.memory_changed",
            "physical_disks": "hardware.physical_disks_changed",
            "nvidia_gpu": "hardware.nvidia_gpu_changed",
        }
        baseline = load_fixture()
        for check, mutate in mutations.items():
            with self.subTest(check=check):
                current = copy.deepcopy(baseline)
                mutate(current["checks"][check]["data"])
                hardware_ids = [
                    item["rule_id"]
                    for item in assess_snapshot(current, baseline)["findings"]
                    if item["rule_id"].startswith("hardware.")
                ]
                self.assertEqual(hardware_ids, [expected[check]])

    def test_hardware_order_and_volatile_fields_are_ignored(self) -> None:
        baseline = load_fixture()
        for check in ("cpu", "memory_modules", "physical_disks", "nvidia_gpu"):
            baseline["checks"][check]["data"] *= 2
        current = copy.deepcopy(baseline)
        for check in ("cpu", "memory_modules", "physical_disks", "nvidia_gpu"):
            current["checks"][check]["data"].reverse()
        current["checks"]["nvidia_gpu"]["data"][0].update(
            {"driver_version": "999", "utilization_gpu_percent": 99, "temperature_celsius": 90}
        )
        current["checks"]["physical_disks"]["data"][0]["Status"] = "Changed"
        for result in current["checks"].values():
            result["duration_ms"] = 999
        current["collected_at_utc"] = "2026-08-09T17:00:00+00:00"

        ids = finding_ids(assess_snapshot(current, baseline))
        self.assertFalse(any(rule.startswith("hardware.") for rule in ids))

    def test_unavailable_baseline_does_not_claim_hardware_change(self) -> None:
        baseline = load_fixture()
        baseline["checks"]["cpu"] = {
            "status": "failed",
            "data": None,
            "message": "failed",
            "duration_ms": 1.0,
        }
        current = load_fixture()
        current["checks"]["cpu"]["data"][0]["Name"] = "Changed"
        self.assertNotIn("hardware.cpu_changed", finding_ids(assess_snapshot(current, baseline)))

    def test_bios_date_rules_and_complete_year_boundary(self) -> None:
        cases = [
            (None, "bios.release_date_missing"),
            ("2026-08-09", "bios.release_date_future"),
            ("2021-08-08", "bios.release_date_stale"),
            ("2021-08-09", None),
            ("2020-02-29", "bios.release_date_stale"),
        ]
        for release_date, expected in cases:
            with self.subTest(release_date=release_date):
                snapshot = load_fixture()
                snapshot["checks"]["bios"]["data"]["ReleaseDate"] = release_date
                bios_ids = [
                    item["rule_id"]
                    for item in assess_snapshot(snapshot)["findings"]
                    if item["check"] == "bios"
                ]
                self.assertEqual(bios_ids, [] if expected is None else [expected])

    def test_february_29_five_year_anniversary_clamps_to_february_28(self) -> None:
        cases = [
            ("2025-02-27T23:59:59Z", None),
            ("2025-02-28T00:00:00Z", "bios.release_date_stale"),
            ("2025-03-01T00:00:00Z", "bios.release_date_stale"),
        ]
        for collected_at, expected in cases:
            with self.subTest(collected_at=collected_at):
                snapshot = load_fixture()
                snapshot["collected_at_utc"] = collected_at
                snapshot["checks"]["bios"]["data"]["ReleaseDate"] = "2020-02-29"
                bios_ids = [
                    item["rule_id"]
                    for item in assess_snapshot(snapshot)["findings"]
                    if item["check"] == "bios"
                ]
                self.assertEqual(bios_ids, [] if expected is None else [expected])

    def test_schema_valid_rfc3339_variants_are_accepted_and_normalized_to_utc(self) -> None:
        cases = [
            "2026-08-08t17:00:00z",
            "2026-08-08T17:00:00.123456Z",
            "2026-08-08T19:00:00+02:00",
            "2026-08-08T12:00:00-05:00",
        ]
        for collected_at in cases:
            with self.subTest(collected_at=collected_at):
                snapshot = load_fixture()
                snapshot["collected_at_utc"] = collected_at
                self.assertEqual(assess_snapshot(snapshot)["findings"], [])

    def test_assessment_is_deterministic_and_does_not_mutate_inputs(self) -> None:
        current = load_fixture()
        baseline = load_fixture()
        original_current = copy.deepcopy(current)
        original_baseline = copy.deepcopy(baseline)
        first = assess_snapshot(current, baseline)
        second = assess_snapshot(current, baseline)
        self.assertEqual(first, second)
        self.assertEqual(current, original_current)
        self.assertEqual(baseline, original_baseline)
        counts = first["summary"]["counts"]
        self.assertEqual(sum(counts.values()), len(first["findings"]))

    def test_hardware_identity_ignores_outer_whitespace_and_case_only(self) -> None:
        baseline = load_fixture()
        current = copy.deepcopy(baseline)
        for check in ("cpu", "memory_modules", "physical_disks", "nvidia_gpu"):
            for item in current["checks"][check]["data"]:
                for key, value in item.items():
                    if isinstance(value, str):
                        item[key] = f"  {value.swapcase()}  "
        for key, value in current["checks"]["system"]["data"].items():
            if isinstance(value, str):
                current["checks"]["system"]["data"][key] = f" {value.swapcase()} "
        self.assertFalse(
            any(
                item["rule_id"].startswith("hardware.")
                for item in assess_snapshot(current, baseline)["findings"]
            )
        )

        current = copy.deepcopy(baseline)
        baseline["checks"]["system"]["data"]["Model"] = "Model  With Internal Gap"
        current["checks"]["system"]["data"]["Model"] = "model with internal gap"
        self.assertIn("hardware.system_changed", finding_ids(assess_snapshot(current, baseline)))

    def test_failed_current_hardware_probe_suppresses_every_hardware_rule(self) -> None:
        for check, rule_id, _fields, _normalizer in HARDWARE_RULES:
            with self.subTest(check=check):
                baseline = load_fixture()
                current = load_fixture()
                current["checks"][check] = {
                    "status": "failed",
                    "data": None,
                    "message": "PRIVATE HARDWARE PROBE ERROR",
                    "duration_ms": 1.0,
                }
                result = assess_snapshot(current, baseline)
                self.assertNotIn(rule_id, finding_ids(result))
                self.assertIn("probe.failed", finding_ids(result))
                self.assertNotIn("PRIVATE HARDWARE PROBE ERROR", json.dumps(result))

    def test_generated_hardware_findings_do_not_leak_sensitive_identities(self) -> None:
        baseline = load_fixture()
        current = copy.deepcopy(baseline)
        sensitive_values = [
            "SECRET CPU ALPHA",
            "SECRET RAM PART ALPHA",
            "SECRET DISK ALPHA",
            "SECRET GPU ALPHA",
            "SECRET SYSTEM ALPHA",
            "SECRET CPU BETA",
            "SECRET RAM PART BETA",
            "SECRET DISK BETA",
            "SECRET GPU BETA",
            "SECRET SYSTEM BETA",
        ]
        baseline["checks"]["cpu"]["data"][0]["Name"] = sensitive_values[0]
        baseline["checks"]["memory_modules"]["data"][0]["PartNumber"] = sensitive_values[1]
        baseline["checks"]["physical_disks"]["data"][0]["Model"] = sensitive_values[2]
        baseline["checks"]["nvidia_gpu"]["data"][0]["name"] = sensitive_values[3]
        baseline["checks"]["system"]["data"]["Model"] = sensitive_values[4]
        current["checks"]["cpu"]["data"][0]["Name"] = sensitive_values[5]
        current["checks"]["memory_modules"]["data"][0]["PartNumber"] = sensitive_values[6]
        current["checks"]["physical_disks"]["data"][0]["Model"] = sensitive_values[7]
        current["checks"]["nvidia_gpu"]["data"][0]["name"] = sensitive_values[8]
        current["checks"]["system"]["data"]["Model"] = sensitive_values[9]
        serialized = json.dumps(assess_snapshot(current, baseline))
        self.assertEqual(serialized.count("hardware."), 5)
        for secret in sensitive_values:
            self.assertNotIn(secret, serialized)

    def test_findings_fixture_is_schema_valid_and_privacy_safe(self) -> None:
        payload = load_fixture("assessment-findings-v1.json")
        validate_assessment(payload)
        serialized = json.dumps(payload)
        for secret in (
            "TEST-HOST",
            "System",
            "C:\\Python\\python.exe",
            "Test CPU",
            "Test GPU",
            "Test SSD",
            "RAM-1",
            "probe failed safely",
        ):
            self.assertNotIn(secret, serialized)

    def test_generated_findings_match_golden_and_counts(self) -> None:
        snapshot = load_fixture()
        snapshot["checks"]["storage"]["data"][0]["FreeSpace"] = 4 * GIB
        snapshot["checks"]["bios"]["data"]["ReleaseDate"] = "2020-01-01"
        snapshot["checks"]["cpu"] = {
            "status": "failed",
            "data": None,
            "message": "private raw failure",
            "duration_ms": 1.0,
        }
        snapshot["checks"]["nvidia_gpu"] = {
            "status": "unavailable",
            "data": None,
            "message": "Command not found: nvidia-smi",
            "duration_ms": 1.0,
        }
        result = assess_snapshot(snapshot)
        self.assertEqual(result, load_fixture("assessment-findings-v1.json"))
        self.assertEqual(sum(result["summary"]["counts"].values()), len(result["findings"]))


class AssessmentSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        schema = json.loads(
            (Path(__file__).parents[1] / "docs" / "assessment.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def test_golden_fixtures_validate(self) -> None:
        for name in ("assessment-clean-v1.json", "assessment-findings-v1.json"):
            with self.subTest(name=name):
                self.validator.validate(load_fixture(name))

    def test_per_rule_evidence_rejects_sensitive_extra_fields(self) -> None:
        payload = load_fixture("assessment-findings-v1.json")
        payload["findings"][0]["evidence"]["volume_label"] = "SECRET"
        self.assertFalse(self.validator.is_valid(payload))

    def test_schema_enforces_rule_severity_and_privacy_safe_subject(self) -> None:
        payload = load_fixture("assessment-findings-v1.json")
        payload["findings"][0]["severity"] = "info"
        self.assertFalse(self.validator.is_valid(payload))

        payload = load_fixture("assessment-findings-v1.json")
        payload["findings"][0]["subject"] = "C: (PRIVATE LABEL)"
        self.assertFalse(self.validator.is_valid(payload))

    def test_schema_couples_each_hardware_rule_to_its_check(self) -> None:
        baseline = load_fixture()
        current = copy.deepcopy(baseline)
        current["checks"]["cpu"]["data"][0]["NumberOfCores"] += 1
        payload = assess_snapshot(current, baseline)
        self.validator.validate(payload)
        payload["findings"][0]["check"] = "system"
        self.assertFalse(self.validator.is_valid(payload))

    def test_semantic_validator_rejects_incorrect_counts_and_highest_severity(self) -> None:
        for field in ("counts", "highest_severity"):
            with self.subTest(field=field):
                payload = load_fixture("assessment-findings-v1.json")
                if field == "counts":
                    payload["summary"]["counts"]["critical"] = 99
                else:
                    payload["summary"]["highest_severity"] = "info"
                with self.assertRaisesRegex(ValueError, field.replace("_", " ")):
                    validate_assessment(payload)


class AssessmentCliTests(unittest.TestCase):
    def test_human_and_json_output(self) -> None:
        path = FIXTURES / "snapshot-success-v1.json"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["assess", str(path)]), 0)
        self.assertIn("No findings detected", stdout.getvalue())

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["assess", str(path), "--baseline", str(path), "--json"]), 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["assessment_schema_version"], "1.0")
        self.assertEqual(payload["baseline_collected_at_utc"], "2026-08-08T17:00:00+00:00")

    def test_supported_encodings(self) -> None:
        text = (FIXTURES / "snapshot-success-v1.json").read_text(encoding="utf-8")
        encodings = {
            "utf8.json": text.encode("utf-8"),
            "utf8-bom.json": text.encode("utf-8-sig"),
            "utf16-le.json": text.encode("utf-16"),
            "utf16-be.json": b"\xfe\xff" + text.encode("utf-16-be"),
        }
        with tempfile.TemporaryDirectory() as directory:
            for name, content in encodings.items():
                with self.subTest(name=name):
                    path = Path(directory) / name
                    path.write_bytes(content)
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(main(["assess", str(path)]), 0)

    def test_cli_accepts_lowercase_rfc3339_timestamp(self) -> None:
        snapshot = load_fixture()
        snapshot["collected_at_utc"] = "2026-08-08t17:00:00z"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lowercase-rfc3339.json"
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["assess", str(path), "--json"]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["findings"], [])

    def test_input_errors_return_two_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            malformed = Path(directory) / "private-malformed-name.json"
            malformed.write_text("{not json", encoding="utf-8")
            unsupported = Path(directory) / "unsupported.json"
            unsupported.write_bytes(b"\x80\x81")
            cases = [
                FIXTURES / "missing.json",
                FIXTURES / "assessment-clean-v1.json",
                malformed,
                unsupported,
            ]
            for path in cases:
                with self.subTest(path=path):
                    stderr = io.StringIO()
                    with contextlib.redirect_stderr(stderr):
                        self.assertEqual(main(["assess", str(path)]), 2)
                    self.assertIn("rigpilot assess:", stderr.getvalue())
                    self.assertNotIn("Traceback", stderr.getvalue())

    def test_successful_json_does_not_include_input_filename(self) -> None:
        text = (FIXTURES / "snapshot-success-v1.json").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "PRIVATE-SNAPSHOT-NAME.json"
            path.write_text(text, encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["assess", str(path), "--json"]), 0)
        self.assertNotIn("PRIVATE-SNAPSHOT-NAME", stdout.getvalue())

    @patch("rigpilot.cli.collect_snapshot")
    def test_live_human_collects_once_with_defaults_and_omits_hostname(self, collect) -> None:
        snapshot = live_snapshot_model()
        collect.return_value = snapshot
        stdout = io.StringIO()

        with (
            patch("rigpilot.cli.assess_snapshot", wraps=assess_snapshot) as assess,
            contextlib.redirect_stdout(stdout),
        ):
            result = main(["assess", "--live"])

        self.assertEqual(result, 0)
        self.assertIn("No findings detected", stdout.getvalue())
        collect.assert_called_once_with(timeout=5.0, only=None, skip=None)
        snapshot.to_dict.assert_called_once_with(include_hostname=False)
        assess.assert_called_once()
        self.assertIsNone(assess.call_args.args[0]["hostname"])

    @patch("rigpilot.cli.collect_snapshot")
    def test_live_json_is_schema_valid_and_findings_return_zero(self, collect) -> None:
        current = load_fixture()
        current["checks"]["storage"]["data"][0]["FreeSpace"] = 4 * GIB
        collect.return_value = live_snapshot_model(current)
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            result = main(["assess", "--live", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(result, 0)
        validate_assessment(payload)
        self.assertIn("storage.critically_low_capacity", finding_ids(payload))
        collect.assert_called_once()

    @patch("rigpilot.cli.collect_snapshot")
    def test_live_baseline_loads_once_and_enables_hardware_comparison(self, collect) -> None:
        baseline = load_fixture()
        current = copy.deepcopy(baseline)
        current["checks"]["cpu"]["data"][0]["NumberOfCores"] += 1
        collect.return_value = live_snapshot_model(current)
        stdout = io.StringIO()

        with (
            patch("rigpilot.cli.load_snapshot", return_value=baseline) as load,
            contextlib.redirect_stdout(stdout),
        ):
            result = main(["assess", "--live", "--baseline", "previous.json", "--json"])

        self.assertEqual(result, 0)
        self.assertIn("hardware.cpu_changed", finding_ids(json.loads(stdout.getvalue())))
        load.assert_called_once_with(Path("previous.json"))
        collect.assert_called_once()

    def test_live_collection_options_are_forwarded_exactly(self) -> None:
        cases = [
            (
                ["--timeout", "10", "--only", "storage,bios"],
                {"timeout": 10.0, "only": {"storage", "bios"}, "skip": None},
            ),
            (
                ["--skip", "nvidia_gpu"],
                {"timeout": 5.0, "only": None, "skip": {"nvidia_gpu"}},
            ),
        ]
        for arguments, expected in cases:
            with (
                self.subTest(arguments=arguments),
                patch(
                    "rigpilot.cli.collect_snapshot", return_value=live_snapshot_model()
                ) as collect,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["assess", "--live", *arguments]), 0)
                collect.assert_called_once_with(**expected)

    @patch("rigpilot.cli.collect_snapshot")
    def test_invalid_live_arguments_fail_before_collection(self, collect) -> None:
        path = str(FIXTURES / "snapshot-success-v1.json")
        cases = [
            ["assess"],
            ["assess", "--live", path],
            ["assess", path, "--timeout", "1"],
            ["assess", path, "--only", "cpu"],
            ["assess", path, "--skip", "cpu"],
            ["assess", "--live", "--only", "cpu", "--skip", "memory"],
            ["assess", "--live", "--only", ""],
            ["assess", "--live", "--only", "registry"],
        ]
        cases.extend(
            ["assess", "--live", "--timeout", str(timeout)] for timeout in (0, -1, nan, inf)
        )
        for arguments in cases:
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    main(arguments)
                self.assertEqual(raised.exception.code, 2)
        collect.assert_not_called()

    @patch("rigpilot.cli.collect_snapshot")
    def test_invalid_live_baseline_prevents_collection(self, collect) -> None:
        with tempfile.TemporaryDirectory() as directory:
            malformed = Path(directory) / "malformed.json"
            malformed.write_text("{not json", encoding="utf-8")
            schema_invalid = Path(directory) / "schema-invalid.json"
            invalid_payload = load_fixture()
            del invalid_payload["checks"]["bios"]
            schema_invalid.write_text(json.dumps(invalid_payload), encoding="utf-8")
            for baseline in (Path(directory) / "missing.json", malformed, schema_invalid):
                with self.subTest(baseline=baseline):
                    stderr = io.StringIO()
                    with contextlib.redirect_stderr(stderr):
                        result = main(["assess", "--live", "--baseline", str(baseline)])
                    self.assertEqual(result, 2)
                    self.assertIn("rigpilot assess:", stderr.getvalue())
                    self.assertNotIn("Traceback", stderr.getvalue())
        collect.assert_not_called()

    @patch("rigpilot.cli.collect_snapshot")
    def test_invalid_collected_snapshot_fails_concisely(self, collect) -> None:
        collect.return_value = live_snapshot_model({"private": "SECRET INTERNAL VALUE"})
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            result = main(["assess", "--live"])

        self.assertEqual(result, 1)
        self.assertEqual(stderr.getvalue(), "rigpilot assess: live assessment failed\n")
        self.assertNotIn("SECRET", stderr.getvalue())
        collect.assert_called_once()

    @patch("rigpilot.cli.collect_snapshot", side_effect=RuntimeError("SECRET COLLECTOR ERROR"))
    def test_live_collection_error_fails_concisely(self, collect) -> None:
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            result = main(["assess", "--live"])

        self.assertEqual(result, 1)
        self.assertEqual(stderr.getvalue(), "rigpilot assess: live assessment failed\n")
        self.assertNotIn("SECRET", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
        collect.assert_called_once()

    @patch("rigpilot.cli.collect_snapshot", return_value=live_snapshot_model())
    def test_unexpected_assessment_error_is_private(self, collect) -> None:
        stderr = io.StringIO()

        with (
            patch(
                "rigpilot.cli.assess_snapshot",
                side_effect=AttributeError("SECRET ASSESSMENT FAILURE"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = main(["assess", "--live"])

        self.assertEqual(result, 1)
        self.assertEqual(stderr.getvalue(), "rigpilot assess: live assessment failed\n")
        self.assertNotIn("SECRET", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
        collect.assert_called_once()

    @patch("rigpilot.cli.collect_snapshot", return_value=live_snapshot_model())
    def test_unexpected_rendering_error_is_private(self, collect) -> None:
        stderr = io.StringIO()

        with (
            patch(
                "rigpilot.cli.render_assessment_human",
                side_effect=KeyError("SECRET RENDERING FAILURE"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = main(["assess", "--live"])

        self.assertEqual(result, 1)
        self.assertEqual(stderr.getvalue(), "rigpilot assess: live assessment failed\n")
        self.assertNotIn("SECRET", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
        collect.assert_called_once()

    @patch("rigpilot.cli.collect_snapshot", return_value=live_snapshot_model())
    def test_live_does_not_catch_process_control_exceptions(self, collect) -> None:
        for exception in (KeyboardInterrupt(), SystemExit(9)):
            with (
                self.subTest(exception=type(exception).__name__),
                patch("rigpilot.cli.assess_snapshot", side_effect=exception),
                self.assertRaises(type(exception)),
            ):
                main(["assess", "--live"])
        self.assertEqual(collect.call_count, 2)

    def test_saved_mode_loads_current_before_baseline(self) -> None:
        current = Path("current-invalid.json")
        baseline = Path("baseline-invalid.json")
        stderr = io.StringIO()

        with (
            patch("rigpilot.cli.load_snapshot", side_effect=ValueError("current failed")) as load,
            contextlib.redirect_stderr(stderr),
        ):
            result = main(["assess", str(current), "--baseline", str(baseline)])

        self.assertEqual(result, 2)
        load.assert_called_once_with(current)
        self.assertIn("current failed", stderr.getvalue())

    @patch("rigpilot.cli.collect_snapshot")
    def test_live_output_excludes_sensitive_inventory_values(self, collect) -> None:
        current = load_fixture()
        current["hostname"] = "SECRET-LIVE-HOST"
        current["checks"]["storage"]["data"][0]["VolumeName"] = "SECRET VOLUME"
        current["checks"]["python"]["data"]["executable"] = "C:\\SECRET\\python.exe"
        current["checks"]["git"] = {
            "status": "failed",
            "data": None,
            "message": "SECRET RAW PROBE ERROR",
            "duration_ms": 1.0,
        }
        current["checks"]["cpu"]["data"][0]["Name"] = "SECRET CPU"
        current["checks"]["memory_modules"]["data"][0]["PartNumber"] = "SECRET RAM"
        current["checks"]["physical_disks"]["data"][0]["Model"] = "SECRET DISK"
        current["checks"]["nvidia_gpu"]["data"][0]["name"] = "SECRET GPU"
        current["checks"]["system"]["data"]["Model"] = "SECRET SYSTEM"
        secrets = (
            "SECRET-LIVE-HOST",
            "SECRET VOLUME",
            "C:\\SECRET\\python.exe",
            "SECRET RAW PROBE ERROR",
            "SECRET CPU",
            "SECRET RAM",
            "SECRET DISK",
            "SECRET GPU",
            "SECRET SYSTEM",
        )
        for output_arguments in ([], ["--json"]):
            with self.subTest(output_arguments=output_arguments):
                collect.return_value = live_snapshot_model(current)
                collect.reset_mock()
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    result = main(
                        [
                            "assess",
                            "--live",
                            "--baseline",
                            str(FIXTURES / "snapshot-success-v1.json"),
                            *output_arguments,
                        ]
                    )

                self.assertEqual(result, 0)
                collect.assert_called_once()
                for secret in secrets:
                    self.assertNotIn(secret, stdout.getvalue())


class InstalledPackageTests(unittest.TestCase):
    def test_wheel_contains_and_loads_both_packaged_schemas(self) -> None:
        project_root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            wheel_directory = temporary / "wheel"
            target_directory = temporary / "installed"
            wheel_directory.mkdir()
            environment = os.environ.copy()
            environment.pop("PYTHONPATH", None)
            if importlib.util.find_spec("pip") is not None:
                build_command = [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    str(project_root),
                    "--no-deps",
                    "--wheel-dir",
                    str(wheel_directory),
                ]
            else:
                uv = shutil.which("uv")
                self.assertIsNotNone(uv, "wheel test requires pip or uv")
                build_command = [
                    uv,
                    "build",
                    "--wheel",
                    "--out-dir",
                    str(wheel_directory),
                    "--no-create-gitignore",
                    str(project_root),
                ]
            subprocess.run(
                build_command,
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            wheels = list(wheel_directory.glob("rigpilot-*.whl"))
            self.assertEqual(len(wheels), 1)
            with zipfile.ZipFile(wheels[0]) as archive:
                names = set(archive.namelist())
            self.assertIn("rigpilot/snapshot.schema.json", names)
            self.assertIn("rigpilot/assessment.schema.json", names)
            with zipfile.ZipFile(wheels[0]) as archive:
                archive.extractall(target_directory)
            smoke_code = f"""
import sys
sys.path.insert(0, {str(target_directory)!r})
from importlib import resources
from rigpilot.assessment import _assessment_validator
from rigpilot.diffing import _validator
package = resources.files('rigpilot')
assert package.joinpath('snapshot.schema.json').is_file()
assert package.joinpath('assessment.schema.json').is_file()
_validator()
_assessment_validator()
print('installed_schema_smoke=PASS')
"""
            completed = subprocess.run(
                [sys.executable, "-I", "-c", smoke_code],
                cwd=temporary,
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(completed.stdout.strip(), "installed_schema_smoke=PASS")


if __name__ == "__main__":
    unittest.main()
