from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

import rigpilot
from rigpilot.assessment import assess_snapshot, validate_assessment
from rigpilot.cli import build_assess_parser, build_diff_parser, build_parser, main
from rigpilot.diffing import load_snapshot
from rigpilot.policy import build_policy_report, validate_policy_report
from rigpilot.policy_config import load_policy_config

PROJECT_ROOT = Path(__file__).parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
EXAMPLE = PROJECT_ROOT / "examples" / "github-actions"


def _option_strings(parser) -> set[str]:
    return {option for action in parser._actions for option in action.option_strings}


def _top_level_mapping_keys(text: str, section: str) -> tuple[str, ...]:
    lines = text.splitlines()
    start = lines.index(f"{section}:") + 1
    keys: list[str] = []
    for line in lines[start:]:
        if line and not line.startswith(" "):
            break
        match = re.fullmatch(r"  ([a-z][a-z0-9_-]*):", line)
        if match:
            keys.append(match.group(1))
    return tuple(keys)


def _run_cli(arguments: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = main(arguments)
    return result, stdout.getvalue(), stderr.getvalue()


class V1CliContractTests(unittest.TestCase):
    def test_public_command_option_names_are_locked(self) -> None:
        self.assertEqual(
            _option_strings(build_parser()),
            {
                "-h",
                "--help",
                "--version",
                "--json",
                "--redact",
                "--no-hostname",
                "--only",
                "--skip",
                "--timeout",
            },
        )
        self.assertEqual(_option_strings(build_diff_parser()), {"-h", "--help", "--json"})
        self.assertEqual(
            _option_strings(build_assess_parser()),
            {
                "-h",
                "--help",
                "--live",
                "--baseline",
                "--json",
                "--format",
                "--output",
                "--guidance",
                "--policy",
                "--policy-file",
                "--policy-min-severity",
                "--policy-groups",
                "--policy-checks",
                "--policy-fail-on",
                "--only",
                "--skip",
                "--timeout",
            },
        )
        help_text = build_parser().format_help()
        self.assertTrue(help_text.startswith("usage: rigpilot "))
        self.assertIn("rigpilot diff BEFORE AFTER", help_text)
        self.assertIn("rigpilot assess [CURRENT]", help_text)
        self.assertIn("Valid checks: bios, cpu, git", help_text)
        assess_help = build_assess_parser().format_help()
        self.assertIn("Policy groups: probes, storage, hardware, bios.", assess_help)
        self.assertIn("Policy severities: critical, warning, info.", assess_help)

    @patch("rigpilot.cli.collect_snapshot")
    def test_version_comes_from_package_without_collection(self, collect) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            main(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(stdout.getvalue(), f"rigpilot {rigpilot.__version__}\n")
        collect.assert_not_called()

    def test_exit_code_contract_zero_one_two_and_three(self) -> None:
        clean = str(FIXTURES / "snapshot-success-v1.json")
        failure = str(FIXTURES / "snapshot-failure-v1.json")
        policy = str(FIXTURES / "policy-config-v1.json")

        self.assertEqual(_run_cli(["assess", clean])[0], 0)
        invalid = _run_cli(["assess", str(FIXTURES / "missing.json")])
        self.assertEqual(invalid[0], 2)
        self.assertEqual(invalid[1], "")
        with patch("rigpilot.cli.render_assessment_human", side_effect=RuntimeError("private")):
            internal = _run_cli(["assess", clean])
        self.assertEqual(internal, (1, "", "rigpilot assess: output failed\n"))
        triggered = _run_cli(["assess", failure, "--policy-file", policy, "--format", "json"])
        self.assertEqual(triggered[0], 3)
        self.assertEqual(triggered[2], "")
        validate_policy_report(json.loads(triggered[1]))

    def test_default_text_and_v08_json_contract_remain_deterministic(self) -> None:
        snapshot = str(FIXTURES / "snapshot-failure-v1.json")
        default = _run_cli(["assess", snapshot])
        explicit = _run_cli(["assess", snapshot, "--format", "text"])
        legacy = _run_cli(["assess", snapshot, "--json"])
        current = _run_cli(["assess", snapshot, "--format", "json"])

        self.assertEqual(default, explicit)
        self.assertEqual(legacy, current)
        self.assertEqual(current, _run_cli(["assess", snapshot, "--format", "json"]))
        self.assertEqual(current[0], 0)
        self.assertEqual(current[2], "")
        validate_assessment(json.loads(current[1]))


class V1SchemaAndPolicyContractTests(unittest.TestCase):
    def test_all_versioned_schema_identifiers_and_version_fields_are_locked(self) -> None:
        contracts = (
            ("snapshot.schema.json", "urn:rigpilot:schema:snapshot:1.0", "schema_version"),
            (
                "assessment.schema.json",
                "urn:rigpilot:schema:assessment:1.0",
                "assessment_schema_version",
            ),
            (
                "guidance.schema.json",
                "urn:rigpilot:schema:guidance:1.0",
                "guidance_schema_version",
            ),
            ("policy.schema.json", "urn:rigpilot:schema:policy:1.0", "policy_schema_version"),
            (
                "policy-config.schema.json",
                "urn:rigpilot:schema:policy-config:1.0",
                "policy_config_schema_version",
            ),
        )
        for filename, schema_id, version_field in contracts:
            with self.subTest(filename=filename):
                schema = json.loads((PROJECT_ROOT / "docs" / filename).read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(schema)
                self.assertEqual(schema["$id"], schema_id)
                self.assertEqual(schema["properties"][version_field]["const"], "1.0")
                self.assertFalse(schema["additionalProperties"])

    def test_existing_policy_file_and_structured_report_remain_compatible(self) -> None:
        policy = load_policy_config(FIXTURES / "policy-config-v1.json")
        snapshot = load_snapshot(FIXTURES / "snapshot-success-v1.json")
        assessment = assess_snapshot(snapshot)
        report = build_policy_report(assessment, policy)

        validate_policy_report(report)
        self.assertEqual(policy.minimum_severity, "warning")
        self.assertEqual(policy.rule_groups, ("probes", "storage", "bios"))
        self.assertEqual(policy.checks, ("storage", "bios"))
        self.assertEqual(report["policy_schema_version"], "1.0")
        self.assertEqual(report["report"]["assessment_schema_version"], "1.0")

    def test_canonical_example_reproduces_its_report_byte_for_byte(self) -> None:
        snapshot = load_snapshot(EXAMPLE / "current.json")
        policy = load_policy_config(EXAMPLE / "rigpilot-policy.json")
        report = build_policy_report(assess_snapshot(snapshot), policy)
        expected_text = (EXAMPLE / "expected-report.json").read_text(encoding="utf-8")

        validate_policy_report(report)
        rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        self.assertEqual(rendered, expected_text)
        self.assertEqual(
            report["decision"],
            {
                "triggered": False,
                "matching_finding_indices": [],
                "exit_code": 0,
            },
        )


class V1ActionAndPackagingContractTests(unittest.TestCase):
    def test_action_input_output_names_and_defaults_are_locked(self) -> None:
        metadata = (PROJECT_ROOT / "action.yml").read_text(encoding="utf-8")
        self.assertEqual(
            _top_level_mapping_keys(metadata, "inputs"),
            ("snapshot", "policy", "report", "python-version"),
        )
        self.assertEqual(
            _top_level_mapping_keys(metadata, "outputs"),
            (
                "status",
                "passed",
                "warnings",
                "failed",
                "critical",
                "report",
                "exit_code",
                "summary",
            ),
        )
        self.assertRegex(metadata, r"(?s)  report:.*?default: rigpilot-assessment\.json")
        self.assertRegex(metadata, r'(?s)  python-version:.*?default: "3\.12"')

    def test_released_workflow_covers_exact_and_major_v1_references(self) -> None:
        workflow = (PROJECT_ROOT / ".github" / "workflows" / "released-action-smoke.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("uses: Arturo6PR/rigpilot@v1.0.0", workflow)
        self.assertIn("uses: Arturo6PR/rigpilot@v1", workflow)
        self.assertIn("continue-on-error: true", workflow)
        self.assertIn("policy_schema_version", workflow)

    def test_package_version_has_one_authoritative_source(self) -> None:
        project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertNotIn("version", project["project"])
        self.assertEqual(project["project"]["dynamic"], ["version"])
        self.assertEqual(project["tool"]["hatch"]["version"]["path"], "src/rigpilot/__init__.py")

    def test_repository_and_package_metadata_declare_exact_apache_license(self) -> None:
        project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        license_text = (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")

        self.assertEqual(project["project"]["license"], "Apache-2.0")
        self.assertEqual(project["project"]["license-files"], ["LICENSE"])
        self.assertEqual(
            project["project"]["urls"]["License"],
            "https://github.com/Arturo6PR/rigpilot/blob/main/LICENSE",
        )
        self.assertEqual(
            hashlib.sha256(license_text.encode("utf-8")).hexdigest(),
            "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
        )


if __name__ == "__main__":
    unittest.main()
