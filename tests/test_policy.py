from __future__ import annotations

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
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from rigpilot.assessment import assess_snapshot, render_assessment_human
from rigpilot.cli import main
from rigpilot.guidance import build_guidance, render_guidance_human
from rigpilot.policy import (
    POLICY_CHECKS,
    RULE_GROUPS,
    RULE_GROUPS_ORDER,
    SEVERITIES,
    Policy,
    build_policy_report,
    render_policy_human,
    validate_policy_report,
)

FIXTURES = Path(__file__).parent / "fixtures"
GIB = 1024**3


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_schema(name: str) -> dict:
    return json.loads((Path(__file__).parents[1] / "docs" / name).read_text(encoding="utf-8"))


def schema_rule_ids(schema: dict) -> set[str]:
    rule_ids: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict):
                rule_constraint = properties.get("rule_id")
                if isinstance(rule_constraint, dict):
                    if "const" in rule_constraint:
                        rule_ids.add(rule_constraint["const"])
                    enum = rule_constraint.get("enum")
                    if isinstance(enum, list):
                        rule_ids.update(enum)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    return rule_ids


class PolicyTests(unittest.TestCase):
    def test_every_assessment_rule_maps_to_exactly_one_known_group(self) -> None:
        assessment_rules = schema_rule_ids(load_schema("assessment.schema.json"))
        self.assertEqual(set(RULE_GROUPS), assessment_rules)
        self.assertEqual(set(RULE_GROUPS.values()), {"probes", "storage", "hardware", "bios"})

    def test_policy_constants_match_schema_enums_exactly(self) -> None:
        policy_properties = load_schema("policy.schema.json")["properties"]["policy"]["properties"]

        self.assertEqual(
            tuple(value for value in policy_properties["minimum_severity"]["enum"] if value),
            SEVERITIES,
        )
        self.assertEqual(
            tuple(value for value in policy_properties["fail_on"]["enum"] if value), SEVERITIES
        )
        self.assertEqual(
            tuple(policy_properties["rule_groups"]["oneOf"][1]["items"]["enum"]),
            RULE_GROUPS_ORDER,
        )
        self.assertEqual(
            tuple(policy_properties["checks"]["oneOf"][1]["items"]["enum"]), POLICY_CHECKS
        )

    def test_clean_and_guidance_reports_match_golden_fixtures(self) -> None:
        clean = build_policy_report(load_fixture("assessment-clean-v1.json"), Policy())
        self.assertEqual(clean, load_fixture("policy-clean-v1.json"))

        guidance = load_fixture("guidance-findings-v1.json")
        configured = Policy(
            minimum_severity="warning",
            rule_groups=("bios", "storage", "storage"),
            fail_on="critical",
        )
        self.assertEqual(
            build_policy_report(guidance, configured),
            load_fixture("policy-guidance-findings-v1.json"),
        )

    def test_source_is_complete_deep_copied_deterministic_and_unmutated(self) -> None:
        source = load_fixture("guidance-findings-v1.json")
        original = copy.deepcopy(source)
        policy = Policy(minimum_severity="warning", rule_groups=("storage", "bios"))
        first = build_policy_report(source, policy)
        second = build_policy_report(source, policy)

        self.assertEqual(first, second)
        self.assertEqual(source, original)
        self.assertEqual(first["report"], source)
        self.assertIsNot(first["report"], source)
        self.assertEqual(len(first["report"]["assessment"]["findings"]), 4)
        self.assertEqual(len(first["report"]["guidance"]), 4)

    def test_group_check_severity_and_combined_selection(self) -> None:
        assessment = load_fixture("assessment-findings-v1.json")
        cases = (
            (Policy(minimum_severity="critical"), [0]),
            (Policy(rule_groups=("probes",)), [2, 3]),
            (Policy(checks=("storage", "bios")), [0, 1]),
            (
                Policy(
                    minimum_severity="warning",
                    rule_groups=("bios", "probes"),
                    checks=("bios", "cpu", "nvidia_gpu"),
                ),
                [1, 2],
            ),
        )
        for policy, expected in cases:
            with self.subTest(policy=policy):
                report = build_policy_report(assessment, policy)
                self.assertEqual(report["view"]["finding_indices"], expected)

    def test_policy_normalizes_order_and_duplicates(self) -> None:
        policy = Policy(
            rule_groups=("bios", "storage", "bios", "probes"),
            checks=("bios", "storage", "cpu", "bios"),
        )
        self.assertEqual(policy.rule_groups, ("probes", "storage", "bios"))
        self.assertEqual(policy.checks, ("cpu", "storage", "bios"))

    def test_multiple_volumes_use_unique_increasing_canonical_indices(self) -> None:
        snapshot = load_fixture("snapshot-success-v1.json")
        snapshot["checks"]["storage"]["data"] = [
            {"DeviceID": "E:", "VolumeName": None, "Size": 1024**4, "FreeSpace": 15 * GIB},
            {"DeviceID": "D:", "VolumeName": None, "Size": 1024**4, "FreeSpace": 4 * GIB},
            {"DeviceID": "C:", "VolumeName": None, "Size": 1024**4, "FreeSpace": 4 * GIB},
        ]
        assessment = assess_snapshot(snapshot)
        report = build_policy_report(assessment, Policy(checks=("storage",)))
        indices = report["view"]["finding_indices"]

        self.assertEqual(indices, [0, 1, 2])
        self.assertEqual(
            [assessment["findings"][index]["subject"] for index in indices],
            ["C:", "D:", "E:"],
        )

    def test_hidden_failed_and_unavailable_probes_remain_canonical(self) -> None:
        assessment = load_fixture("assessment-findings-v1.json")
        report = build_policy_report(assessment, Policy(rule_groups=("storage", "bios")))
        self.assertEqual(report["view"]["finding_indices"], [0, 1])
        self.assertEqual(
            [finding["rule_id"] for finding in report["report"]["findings"]],
            [
                "storage.critically_low_capacity",
                "bios.release_date_stale",
                "probe.failed",
                "probe.optional_unavailable",
            ],
        )

    def test_view_summary_and_decision_are_exact(self) -> None:
        report = build_policy_report(
            load_fixture("assessment-findings-v1.json"),
            Policy(minimum_severity="warning", fail_on="warning"),
        )
        self.assertEqual(
            report["view"]["summary"],
            {
                "highest_severity": "critical",
                "counts": {"info": 0, "warning": 2, "critical": 1},
                "displayed_count": 3,
                "hidden_count": 1,
            },
        )
        self.assertEqual(
            report["decision"],
            {"triggered": True, "matching_finding_indices": [0, 1, 2], "exit_code": 3},
        )

    def test_no_fail_on_returns_zero_even_with_findings(self) -> None:
        report = build_policy_report(load_fixture("assessment-findings-v1.json"), Policy())
        self.assertEqual(report["decision"]["exit_code"], 0)
        self.assertFalse(report["decision"]["triggered"])

    def test_invalid_policy_combinations_are_rejected(self) -> None:
        cases = (
            {"rule_groups": ()},
            {"checks": ()},
            {"rule_groups": ("unknown",)},
            {"checks": ("unknown",)},
            {"rule_groups": ("storage",), "checks": ("bios",)},
            {"minimum_severity": "warning", "fail_on": "info"},
        )
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                Policy(**arguments)

    def test_schema_and_semantic_validation_reject_tampering(self) -> None:
        original = load_fixture("policy-guidance-findings-v1.json")
        mutations = (
            lambda value: value["view"].update(finding_indices=[1, 0]),
            lambda value: value["view"]["summary"]["counts"].update(warning=2),
            lambda value: value["view"]["summary"].update(highest_severity="warning"),
            lambda value: value["view"]["summary"].update(displayed_count=1),
            lambda value: value["view"]["summary"].update(hidden_count=1),
            lambda value: value["decision"].update(triggered=False),
            lambda value: value["decision"].update(matching_finding_indices=[1]),
            lambda value: value["decision"].update(exit_code=0),
            lambda value: value.update(report_kind="assessment"),
            lambda value: value["report"]["assessment"]["summary"]["counts"].update(info=0),
            lambda value: value["report"]["guidance"][0].update(finding_index=1),
            lambda value: value["policy"].update(rule_groups=["bios", "storage"]),
        )
        for mutate in mutations:
            payload = copy.deepcopy(original)
            mutate(payload)
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate_policy_report(payload)

    def test_privacy_safe_source_view_decision_and_human_renderer(self) -> None:
        snapshot = load_fixture("snapshot-success-v1.json")
        baseline = copy.deepcopy(snapshot)
        secrets = (
            "SECRET-HOST",
            "SECRET LABEL",
            "C:\\SECRET\\python.exe",
            "SECRET RAW ERROR",
            "SECRET CPU",
            "SECRET RAM",
            "SECRET DISK",
            "SECRET GPU",
            "SECRET SYSTEM",
        )
        snapshot["hostname"] = secrets[0]
        snapshot["checks"]["storage"]["data"][0]["VolumeName"] = secrets[1]
        snapshot["checks"]["python"]["data"]["executable"] = secrets[2]
        snapshot["checks"]["git"] = {
            "status": "failed",
            "data": None,
            "message": secrets[3],
            "duration_ms": 1.0,
        }
        snapshot["checks"]["cpu"]["data"][0]["Name"] = secrets[4]
        snapshot["checks"]["memory_modules"]["data"][0]["PartNumber"] = secrets[5]
        snapshot["checks"]["physical_disks"]["data"][0]["Model"] = secrets[6]
        snapshot["checks"]["nvidia_gpu"]["data"][0]["name"] = secrets[7]
        snapshot["checks"]["system"]["data"]["Model"] = secrets[8]

        report = build_policy_report(build_guidance(assess_snapshot(snapshot, baseline)), Policy())
        outputs = (json.dumps(report), render_policy_human(report))
        for secret in secrets:
            for output in outputs:
                self.assertNotIn(secret, output)

    def test_human_guidance_is_rendered_only_for_displayed_indices(self) -> None:
        report = load_fixture("policy-guidance-findings-v1.json")
        output = render_policy_human(report)
        self.assertIn("Canonical findings: 4", output)
        self.assertIn("Displayed findings: 2 (2 hidden)", output)
        self.assertIn("Available capacity is below", output)
        self.assertIn("reported BIOS release date", output)
        self.assertNotIn("This inventory check did not complete", output)
        self.assertNotIn("optional NVIDIA inventory check", output)

    def test_human_renderer_preserves_interleaved_canonical_order(self) -> None:
        assessment = load_fixture("assessment-findings-v1.json")
        assessment["findings"] = [
            assessment["findings"][1],
            assessment["findings"][0],
            assessment["findings"][2],
            assessment["findings"][3],
        ]
        report = build_policy_report(assessment, Policy())
        output = render_policy_human(report)
        rule_ids = [finding["rule_id"] for finding in assessment["findings"]]

        self.assertEqual(report["view"]["finding_indices"], [0, 1, 2, 3])
        self.assertEqual(
            [output.index(rule_id) for rule_id in rule_ids],
            sorted(output.index(rule_id) for rule_id in rule_ids),
        )
        for finding in assessment["findings"]:
            self.assertIn(f"{finding['severity'].title()}: {finding['rule_id']}", output)


class PolicyCliTests(unittest.TestCase):
    def test_default_saved_and_mocked_live_outputs_are_byte_compatible(self) -> None:
        snapshot = load_fixture("snapshot-success-v1.json")
        assessment = assess_snapshot(snapshot)
        path = FIXTURES / "snapshot-success-v1.json"
        cases = (
            (
                ["assess", str(path), "--json"],
                f"{json.dumps(assessment, indent=2, ensure_ascii=False)}\n",
            ),
            (["assess", str(path)], f"{render_assessment_human(assessment)}\n"),
        )
        for arguments, expected in cases:
            with (
                self.subTest(arguments=arguments),
                contextlib.redirect_stdout(stdout := io.StringIO()),
            ):
                self.assertEqual(main(arguments), 0)
                self.assertEqual(stdout.getvalue(), expected)

        for suffix, expected in (
            (["--json"], f"{json.dumps(assessment, indent=2, ensure_ascii=False)}\n"),
            ([], f"{render_assessment_human(assessment)}\n"),
        ):
            with (
                self.subTest(suffix=suffix),
                patch(
                    "rigpilot.cli._collect_assessment_snapshot", return_value=snapshot
                ) as collect,
                contextlib.redirect_stdout(stdout := io.StringIO()),
            ):
                self.assertEqual(main(["assess", "--live", *suffix]), 0)
                self.assertEqual(stdout.getvalue(), expected)
                collect.assert_called_once_with(timeout=5.0, only=None, skip=None)

    def test_default_saved_and_mocked_live_guidance_outputs_are_byte_compatible(self) -> None:
        snapshot = load_fixture("snapshot-success-v1.json")
        assessment = assess_snapshot(snapshot)
        guidance = build_guidance(assessment)
        path = FIXTURES / "snapshot-success-v1.json"
        cases = (
            (
                ["--json"],
                f"{json.dumps(guidance, indent=2, ensure_ascii=False)}\n",
            ),
            (
                [],
                f"{render_assessment_human(assessment)}\n\n{render_guidance_human(guidance)}\n",
            ),
        )
        for suffix, expected in cases:
            with (
                self.subTest(mode="saved", suffix=suffix),
                contextlib.redirect_stdout(stdout := io.StringIO()),
            ):
                self.assertEqual(main(["assess", str(path), "--guidance", *suffix]), 0)
                self.assertEqual(stdout.getvalue(), expected)
            with (
                self.subTest(mode="live", suffix=suffix),
                patch(
                    "rigpilot.cli._collect_assessment_snapshot", return_value=snapshot
                ) as collect,
                contextlib.redirect_stdout(stdout := io.StringIO()),
            ):
                self.assertEqual(main(["assess", "--live", "--guidance", *suffix]), 0)
                self.assertEqual(stdout.getvalue(), expected)
                collect.assert_called_once_with(timeout=5.0, only=None, skip=None)

    def test_saved_json_policy_emits_before_exit_three(self) -> None:
        path = FIXTURES / "snapshot-failure-v1.json"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = main(
                ["assess", str(path), "--policy", "--policy-fail-on", "warning", "--json"]
            )
        self.assertEqual(result, 3)
        self.assertTrue(stdout.getvalue())
        report = json.loads(stdout.getvalue())
        validate_policy_report(report)
        self.assertEqual(result, report["decision"]["exit_code"])

    def test_saved_and_mocked_live_human_and_json_with_optional_guidance(self) -> None:
        path = FIXTURES / "snapshot-success-v1.json"
        for guidance in (False, True):
            flags = ["--guidance"] if guidance else []
            with (
                self.subTest(mode="saved-human", guidance=guidance),
                contextlib.redirect_stdout(stdout := io.StringIO()),
            ):
                self.assertEqual(main(["assess", str(path), "--policy", *flags]), 0)
                self.assertIn("RigPilot policy view", stdout.getvalue())

            with (
                self.subTest(mode="saved-json", guidance=guidance),
                contextlib.redirect_stdout(stdout := io.StringIO()),
            ):
                self.assertEqual(main(["assess", str(path), "--policy", *flags, "--json"]), 0)
                report = json.loads(stdout.getvalue())
                validate_policy_report(report)
                self.assertEqual(report["report_kind"], "guidance" if guidance else "assessment")

        snapshot = load_fixture("snapshot-success-v1.json")
        with (
            patch("rigpilot.cli._collect_assessment_snapshot", return_value=snapshot) as collect,
            contextlib.redirect_stdout(stdout := io.StringIO()),
        ):
            self.assertEqual(
                main(
                    [
                        "assess",
                        "--live",
                        "--only",
                        "storage,bios",
                        "--guidance",
                        "--policy",
                        "--policy-checks",
                        "storage,bios",
                        "--json",
                    ]
                ),
                0,
            )
            validate_policy_report(json.loads(stdout.getvalue()))
            collect.assert_called_once_with(timeout=5.0, only={"storage", "bios"}, skip=None)

    def test_invalid_policy_arguments_prevent_loading_and_collection(self) -> None:
        saved = str(FIXTURES / "snapshot-success-v1.json")
        cases = (
            ["assess", saved, "--policy-min-severity", "warning"],
            ["assess", saved, "--policy", "--policy-groups", ","],
            ["assess", saved, "--policy", "--policy-checks", "unknown"],
            [
                "assess",
                saved,
                "--policy",
                "--policy-groups",
                "storage",
                "--policy-checks",
                "bios",
            ],
            [
                "assess",
                "--live",
                "--policy",
                "--policy-min-severity",
                "warning",
                "--policy-fail-on",
                "info",
            ],
        )
        for arguments in cases:
            with (
                self.subTest(arguments=arguments),
                patch("rigpilot.cli.load_snapshot") as load,
                patch("rigpilot.cli._collect_assessment_snapshot") as collect,
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as raised,
            ):
                main(arguments)
            self.assertEqual(raised.exception.code, 2)
            load.assert_not_called()
            collect.assert_not_called()

    def test_exit_codes_zero_one_two_and_three(self) -> None:
        clean = str(FIXTURES / "snapshot-success-v1.json")
        findings = str(FIXTURES / "snapshot-failure-v1.json")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["assess", clean, "--policy"]), 0)
            self.assertEqual(
                main(["assess", findings, "--policy", "--policy-fail-on", "warning"]), 3
            )
        with (
            patch("rigpilot.cli.build_policy_report", side_effect=RuntimeError("SECRET")),
            contextlib.redirect_stderr(stderr := io.StringIO()),
        ):
            self.assertEqual(main(["assess", clean, "--policy"]), 1)
        self.assertEqual(stderr.getvalue(), "rigpilot assess: policy failed\n")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["assess", "missing.json", "--policy"]), 2)

    def test_saved_policy_serialization_and_rendering_failures_are_private(self) -> None:
        path = str(FIXTURES / "snapshot-success-v1.json")
        for target, arguments in (
            ("rigpilot.cli.json.dumps", ["--json"]),
            ("rigpilot.cli.render_policy_human", []),
        ):
            with (
                self.subTest(target=target),
                patch(target, side_effect=RuntimeError("SECRET POLICY FAILURE")),
                contextlib.redirect_stderr(stderr := io.StringIO()),
            ):
                self.assertEqual(main(["assess", path, "--policy", *arguments]), 1)
            self.assertEqual(stderr.getvalue(), "rigpilot assess: policy failed\n")

    def test_live_policy_failures_use_existing_private_boundary(self) -> None:
        snapshot = load_fixture("snapshot-success-v1.json")
        with (
            patch("rigpilot.cli._collect_assessment_snapshot", return_value=snapshot),
            patch("rigpilot.cli.build_policy_report", side_effect=RuntimeError("SECRET")),
            contextlib.redirect_stderr(stderr := io.StringIO()),
        ):
            self.assertEqual(main(["assess", "--live", "--policy"]), 1)
        self.assertEqual(stderr.getvalue(), "rigpilot assess: live assessment failed\n")

    def test_policy_construction_failures_are_private_and_precede_input_work(self) -> None:
        path = str(FIXTURES / "snapshot-success-v1.json")
        cases = (
            (["assess", path, "--policy"], "rigpilot assess: policy failed\n"),
            (["assess", "--live", "--policy"], "rigpilot assess: live assessment failed\n"),
        )
        for arguments, expected_error in cases:
            with (
                self.subTest(arguments=arguments),
                patch(
                    "rigpilot.cli._policy_from_args",
                    side_effect=RuntimeError("SECRET CONSTRUCTION FAILURE"),
                ),
                patch("rigpilot.cli.load_snapshot") as load,
                patch("rigpilot.cli._collect_assessment_snapshot") as collect,
                contextlib.redirect_stderr(stderr := io.StringIO()),
            ):
                self.assertEqual(main(arguments), 1)
            self.assertEqual(stderr.getvalue(), expected_error)
            load.assert_not_called()
            collect.assert_not_called()

    def test_live_policy_serialization_and_rendering_failures_are_private(self) -> None:
        snapshot = load_fixture("snapshot-success-v1.json")
        for target, arguments in (
            ("rigpilot.cli.json.dumps", ["--json"]),
            ("rigpilot.cli.render_policy_human", []),
        ):
            with (
                self.subTest(target=target),
                patch("rigpilot.cli._collect_assessment_snapshot", return_value=snapshot),
                patch(target, side_effect=RuntimeError("SECRET LIVE POLICY FAILURE")),
                contextlib.redirect_stderr(stderr := io.StringIO()),
            ):
                self.assertEqual(main(["assess", "--live", "--policy", *arguments]), 1)
            self.assertEqual(stderr.getvalue(), "rigpilot assess: live assessment failed\n")

    def test_mocked_live_policy_emits_before_exit_three(self) -> None:
        snapshot = load_fixture("snapshot-failure-v1.json")
        with (
            patch("rigpilot.cli._collect_assessment_snapshot", return_value=snapshot) as collect,
            contextlib.redirect_stdout(stdout := io.StringIO()),
            contextlib.redirect_stderr(stderr := io.StringIO()),
        ):
            result = main(["assess", "--live", "--policy", "--policy-fail-on", "warning", "--json"])
        report = json.loads(stdout.getvalue())

        self.assertEqual(result, 3)
        self.assertEqual(result, report["decision"]["exit_code"])
        self.assertEqual(stderr.getvalue(), "")
        validate_policy_report(report)
        collect.assert_called_once_with(timeout=5.0, only=None, skip=None)

    def test_process_control_exceptions_propagate_in_saved_and_live_modes(self) -> None:
        path = str(FIXTURES / "snapshot-success-v1.json")
        snapshot = load_fixture("snapshot-success-v1.json")
        for exception in (KeyboardInterrupt(), SystemExit(9)):
            with (
                self.subTest(mode="saved", exception=type(exception).__name__),
                patch("rigpilot.cli.build_policy_report", side_effect=exception),
                self.assertRaises(type(exception)),
            ):
                main(["assess", path, "--policy"])
            with (
                self.subTest(mode="live", exception=type(exception).__name__),
                patch("rigpilot.cli._collect_assessment_snapshot", return_value=snapshot),
                patch("rigpilot.cli.build_policy_report", side_effect=exception),
                self.assertRaises(type(exception)),
            ):
                main(["assess", "--live", "--policy"])

    def test_policy_construction_process_control_exceptions_propagate(self) -> None:
        path = str(FIXTURES / "snapshot-success-v1.json")
        for arguments in (["assess", path, "--policy"], ["assess", "--live", "--policy"]):
            for exception in (KeyboardInterrupt(), SystemExit(10)):
                with (
                    self.subTest(arguments=arguments, exception=type(exception).__name__),
                    patch("rigpilot.cli._policy_from_args", side_effect=exception),
                    patch("rigpilot.cli.load_snapshot") as load,
                    patch("rigpilot.cli._collect_assessment_snapshot") as collect,
                    self.assertRaises(type(exception)),
                ):
                    main(arguments)
                load.assert_not_called()
                collect.assert_not_called()


class PolicySchemaTests(unittest.TestCase):
    def test_schema_is_valid_draft_2020_12_and_golden_fixtures_validate(self) -> None:
        schema = load_schema("policy.schema.json")
        Draft202012Validator.check_schema(schema)
        for name in ("policy-clean-v1.json", "policy-guidance-findings-v1.json"):
            with self.subTest(name=name):
                validate_policy_report(load_fixture(name))

    def test_wheel_contains_and_loads_all_five_packaged_schemas(self) -> None:
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
                build_command, check=True, capture_output=True, text=True, env=environment
            )
            wheels = list(wheel_directory.glob("rigpilot-*.whl"))
            self.assertEqual(len(wheels), 1)
            with zipfile.ZipFile(wheels[0]) as archive:
                names = set(archive.namelist())
                metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
                license_name = next(
                    name for name in names if name.endswith(".dist-info/licenses/LICENSE")
                )
                metadata_lines = archive.read(metadata_name).decode("utf-8").splitlines()
                packaged_license = archive.read(license_name)
                archive.extractall(target_directory)
            self.assertIn("License-Expression: Apache-2.0", metadata_lines)
            self.assertIn("License-File: LICENSE", metadata_lines)
            self.assertEqual(packaged_license, (project_root / "LICENSE").read_bytes())
            for name in (
                "rigpilot/snapshot.schema.json",
                "rigpilot/assessment.schema.json",
                "rigpilot/guidance.schema.json",
                "rigpilot/policy.schema.json",
                "rigpilot/policy-config.schema.json",
            ):
                self.assertIn(name, names)
            smoke_code = f"""
import sys
sys.path.insert(0, {str(target_directory)!r})
from importlib import resources
from rigpilot.github_action import build_action_result
from rigpilot.policy import _policy_validator
from rigpilot.policy_config import _policy_config_validator
package = resources.files('rigpilot')
for name in ('snapshot.schema.json', 'assessment.schema.json', 'guidance.schema.json', 'policy.schema.json', 'policy-config.schema.json'):
    assert package.joinpath(name).is_file()
_policy_validator()
_policy_config_validator()
assert callable(build_action_result)
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
