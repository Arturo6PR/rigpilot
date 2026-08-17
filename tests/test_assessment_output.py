from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from rigpilot.assessment import validate_assessment
from rigpilot.cli import main
from rigpilot.policy import (
    POLICY_CHECKS,
    RULE_GROUPS_ORDER,
    SEVERITIES,
    validate_policy_report,
)
from rigpilot.policy_config import load_policy_config, validate_policy_config

FIXTURES = Path(__file__).parent / "fixtures"
PROJECT_ROOT = Path(__file__).parents[1]
GIB = 1024**3


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def run_cli(arguments: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = main(arguments)
    return result, stdout.getvalue(), stderr.getvalue()


class PolicyConfigTests(unittest.TestCase):
    def test_schema_is_valid_and_fixture_normalizes_deterministically(self) -> None:
        schema = json.loads(
            (PROJECT_ROOT / "docs" / "policy-config.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)
        properties = schema["properties"]
        self.assertEqual(
            tuple(value for value in properties["minimum_severity"]["enum"] if value),
            SEVERITIES,
        )
        self.assertEqual(
            tuple(value for value in properties["fail_on"]["enum"] if value), SEVERITIES
        )
        self.assertEqual(
            tuple(properties["rule_groups"]["oneOf"][1]["items"]["enum"]),
            RULE_GROUPS_ORDER,
        )
        self.assertEqual(tuple(properties["checks"]["oneOf"][1]["items"]["enum"]), POLICY_CHECKS)
        payload = load_fixture("policy-config-v1.json")

        first = validate_policy_config(payload)
        second = validate_policy_config(copy.deepcopy(payload))

        self.assertEqual(first, second)
        self.assertEqual(first.rule_groups, ("probes", "storage", "bios"))
        self.assertEqual(first.checks, ("storage", "bios"))
        self.assertEqual(first.minimum_severity, "warning")
        self.assertEqual(first.fail_on, "warning")

    def test_loader_supports_existing_snapshot_text_encodings(self) -> None:
        text = json.dumps(load_fixture("policy-config-v1.json"))
        cases = {
            "utf8.json": text.encode("utf-8"),
            "utf8-bom.json": text.encode("utf-8-sig"),
            "utf16.json": text.encode("utf-16"),
        }
        with tempfile.TemporaryDirectory() as directory:
            for name, data in cases.items():
                path = Path(directory) / name
                path.write_bytes(data)
                with self.subTest(name=name):
                    self.assertEqual(
                        load_policy_config(path).rule_groups, ("probes", "storage", "bios")
                    )

    def test_strict_schema_and_policy_semantics_reject_invalid_configs(self) -> None:
        original = load_fixture("policy-config-v1.json")
        mutations = (
            lambda value: value.update(policy_config_schema_version="2.0"),
            lambda value: value.update(extra="not allowed"),
            lambda value: value.update(rule_groups=[]),
            lambda value: value.update(checks=["unknown"]),
            lambda value: value.update(rule_groups=["storage"], checks=["bios"]),
            lambda value: value.update(minimum_severity="warning", fail_on="info"),
        )
        for mutate in mutations:
            payload = copy.deepcopy(original)
            mutate(payload)
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate_policy_config(payload)


class AssessmentOutputCliTests(unittest.TestCase):
    def test_default_and_explicit_text_are_byte_compatible(self) -> None:
        path = str(FIXTURES / "snapshot-success-v1.json")
        default = run_cli(["assess", path])
        explicit = run_cli(["assess", path, "--format", "text"])

        self.assertEqual(default, explicit)
        self.assertEqual(default[0], 0)
        self.assertTrue(default[1].startswith("RigPilot assessment\n"))
        self.assertEqual(default[2], "")

    def test_format_json_serializes_pass_warning_critical_and_multiple_results(self) -> None:
        clean = load_fixture("snapshot-success-v1.json")
        warning = copy.deepcopy(clean)
        warning["checks"]["storage"]["data"][0]["FreeSpace"] = 15 * GIB
        critical = copy.deepcopy(clean)
        critical["checks"]["storage"]["data"][0]["FreeSpace"] = 4 * GIB
        multiple = load_fixture("snapshot-failure-v1.json")
        cases = (
            ("pass", clean, None, {"info": 0, "warning": 0, "critical": 0}, 0),
            ("warning", warning, "warning", {"info": 0, "warning": 1, "critical": 0}, 1),
            ("critical", critical, "critical", {"info": 0, "warning": 0, "critical": 1}, 1),
            ("multiple", multiple, "warning", {"info": 0, "warning": 12, "critical": 0}, 12),
        )
        with tempfile.TemporaryDirectory() as directory:
            for name, snapshot, highest, counts, result_count in cases:
                path = Path(directory) / f"{name}.json"
                path.write_text(json.dumps(snapshot), encoding="utf-8")
                with self.subTest(name=name):
                    result, stdout, stderr = run_cli(["assess", str(path), "--format", "json"])
                    payload = json.loads(stdout)
                    validate_assessment(payload)
                    self.assertEqual(result, 0)
                    self.assertEqual(stderr, "")
                    self.assertEqual(payload["assessment_schema_version"], "1.0")
                    self.assertEqual(payload["summary"]["highest_severity"], highest)
                    self.assertEqual(payload["summary"]["counts"], counts)
                    self.assertEqual(len(payload["findings"]), result_count)

    def test_json_output_is_deterministic(self) -> None:
        path = str(FIXTURES / "snapshot-failure-v1.json")
        first = run_cli(["assess", path, "--format", "json"])
        second = run_cli(["assess", path, "--format", "json"])

        self.assertEqual(first, second)
        self.assertEqual(first[0], 0)
        json.loads(first[1])

    def test_policy_file_and_json_emit_versioned_policy_report_and_exit_three(self) -> None:
        policy_file = FIXTURES / "policy-config-v1.json"
        result, stdout, stderr = run_cli(
            [
                "assess",
                str(FIXTURES / "snapshot-failure-v1.json"),
                "--policy-file",
                str(policy_file),
                "--format",
                "json",
            ]
        )
        payload = json.loads(stdout)

        validate_policy_report(payload)
        self.assertEqual(result, 3)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["policy_schema_version"], "1.0")
        self.assertEqual(payload["decision"]["exit_code"], 3)
        self.assertNotIn(str(policy_file), stdout)
        self.assertEqual(
            payload["view"]["summary"]["counts"],
            {"info": 0, "warning": 2, "critical": 0},
        )

    def test_policy_file_with_guidance_preserves_nested_versioned_reports(self) -> None:
        result, stdout, stderr = run_cli(
            [
                "assess",
                str(FIXTURES / "snapshot-failure-v1.json"),
                "--policy-file",
                str(FIXTURES / "policy-config-v1.json"),
                "--guidance",
                "--format",
                "json",
            ]
        )
        payload = json.loads(stdout)

        validate_policy_report(payload)
        self.assertEqual(result, 3)
        self.assertEqual(stderr, "")
        self.assertEqual(payload["report_kind"], "guidance")
        self.assertEqual(payload["report"]["guidance_schema_version"], "1.0")
        self.assertEqual(payload["report"]["assessment"]["assessment_schema_version"], "1.0")

    def test_output_writes_text_or_json_to_new_file_and_leaves_stdout_empty(self) -> None:
        snapshot = str(FIXTURES / "snapshot-failure-v1.json")
        with tempfile.TemporaryDirectory() as directory:
            for output_format in ("text", "json"):
                output = Path(directory) / f"assessment.{output_format}"
                with self.subTest(output_format=output_format):
                    result, stdout, stderr = run_cli(
                        [
                            "assess",
                            snapshot,
                            "--format",
                            output_format,
                            "--output",
                            str(output),
                        ]
                    )
                    self.assertEqual(result, 0)
                    self.assertEqual(stdout, "")
                    self.assertEqual(stderr, "")
                    data = output.read_text(encoding="utf-8")
                    self.assertTrue(data.endswith("\n"))
                    if output_format == "json":
                        validate_assessment(json.loads(data))
                    else:
                        self.assertTrue(data.startswith("RigPilot assessment\n"))

    def test_policy_json_output_is_written_before_exit_three(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "assessment.json"
            result, stdout, stderr = run_cli(
                [
                    "assess",
                    str(FIXTURES / "snapshot-failure-v1.json"),
                    "--policy-file",
                    str(FIXTURES / "policy-config-v1.json"),
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(result, 3)
            self.assertEqual(stdout, "")
            self.assertEqual(stderr, "")
            validate_policy_report(json.loads(output.read_text(encoding="utf-8")))

    def test_output_never_overwrites_existing_file_or_creates_missing_parent(self) -> None:
        snapshot = str(FIXTURES / "snapshot-success-v1.json")
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "existing.json"
            existing.write_text("KEEP", encoding="utf-8")
            missing = Path(directory) / "missing" / "assessment.json"
            for output in (existing, missing):
                with self.subTest(output=output):
                    result, stdout, stderr = run_cli(
                        ["assess", snapshot, "--format", "json", "--output", str(output)]
                    )
                    self.assertEqual(result, 2)
                    self.assertEqual(stdout, "")
                    self.assertTrue(stderr.startswith("rigpilot assess: "))
            self.assertEqual(existing.read_text(encoding="utf-8"), "KEEP")
            self.assertFalse(missing.exists())

    def test_invalid_format_and_conflicting_legacy_json_are_argument_errors(self) -> None:
        snapshot = str(FIXTURES / "snapshot-success-v1.json")
        cases = (
            ["assess", snapshot, "--format", "yaml"],
            ["assess", snapshot, "--json", "--format", "text"],
        )
        for arguments in cases:
            with (
                self.subTest(arguments=arguments),
                contextlib.redirect_stdout(stdout := io.StringIO()),
                contextlib.redirect_stderr(stderr := io.StringIO()),
                self.assertRaises(SystemExit) as raised,
            ):
                main(arguments)
            self.assertEqual(raised.exception.code, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("rigpilot assess:", stderr.getvalue())

    def test_policy_file_errors_precede_snapshot_loading_and_live_collection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid-policy.json"
            invalid.write_text(
                json.dumps(
                    {
                        "policy_config_schema_version": "1.0",
                        "minimum_severity": "warning",
                        "rule_groups": ["storage"],
                        "checks": ["bios"],
                        "fail_on": None,
                    }
                ),
                encoding="utf-8",
            )
            cases = (
                ["assess", "missing-snapshot.json", "--policy-file", str(invalid)],
                ["assess", "--live", "--policy-file", str(invalid)],
            )
            for arguments in cases:
                with (
                    self.subTest(arguments=arguments),
                    patch("rigpilot.cli.load_snapshot") as load,
                    patch("rigpilot.cli._collect_assessment_snapshot") as collect,
                ):
                    result, stdout, stderr = run_cli(arguments)
                self.assertEqual(result, 2)
                self.assertEqual(stdout, "")
                self.assertTrue(stderr.startswith("rigpilot assess: "))
                load.assert_not_called()
                collect.assert_not_called()

    def test_unexpected_policy_and_json_rendering_errors_are_private(self) -> None:
        snapshot = str(FIXTURES / "snapshot-success-v1.json")
        with patch(
            "rigpilot.cli.load_policy_config", side_effect=RuntimeError("SECRET POLICY ERROR")
        ):
            result, stdout, stderr = run_cli(
                ["assess", snapshot, "--policy-file", "policy.json", "--format", "json"]
            )
        self.assertEqual((result, stdout), (1, ""))
        self.assertEqual(stderr, "rigpilot assess: policy failed\n")
        self.assertNotIn("SECRET", stderr)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "never-created.json"
            with patch("rigpilot.cli.json.dumps", side_effect=RuntimeError("SECRET JSON ERROR")):
                result, stdout, stderr = run_cli(
                    [
                        "assess",
                        snapshot,
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual((result, stdout), (1, ""))
            self.assertEqual(stderr, "rigpilot assess: output failed\n")
            self.assertNotIn("SECRET", stderr)
            self.assertFalse(output.exists())

    def test_mocked_live_policy_file_collects_once_and_emits_json_only(self) -> None:
        snapshot = load_fixture("snapshot-success-v1.json")
        with patch("rigpilot.cli._collect_assessment_snapshot", return_value=snapshot) as collect:
            result, stdout, stderr = run_cli(
                [
                    "assess",
                    "--live",
                    "--policy-file",
                    str(FIXTURES / "policy-config-v1.json"),
                    "--format",
                    "json",
                ]
            )

        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        validate_policy_report(json.loads(stdout))
        collect.assert_called_once_with(timeout=5.0, only=None, skip=None)

    def test_legacy_json_and_existing_commands_remain_compatible(self) -> None:
        snapshot = str(FIXTURES / "snapshot-success-v1.json")
        legacy = run_cli(["assess", snapshot, "--json"])
        formatted = run_cli(["assess", snapshot, "--format", "json"])

        self.assertEqual(legacy, formatted)
        self.assertEqual(legacy[0], 0)
        validate_assessment(json.loads(legacy[1]))


if __name__ == "__main__":
    unittest.main()
