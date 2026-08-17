from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rigpilot.assessment import assess_snapshot
from rigpilot.github_action import build_action_result, run_action
from rigpilot.policy import Policy, build_policy_report, validate_policy_report

PROJECT_ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def read_outputs(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines())


class ActionWorkspace:
    def __init__(
        self,
        directory: str,
        *,
        snapshot: str = "snapshot-success-v1.json",
        policy: str = "policy-config-v1.json",
        spaced_paths: bool = False,
    ) -> None:
        self.root = Path(directory)
        inputs = self.root / ("inputs with spaces" if spaced_paths else "inputs")
        reports = self.root / ("reports with spaces" if spaced_paths else "reports")
        inputs.mkdir()
        reports.mkdir()
        snapshot_name = "current snapshot.json" if spaced_paths else "current.json"
        policy_name = "rigpilot policy.json" if spaced_paths else "policy.json"
        self.snapshot = inputs / snapshot_name
        self.policy = inputs / policy_name
        self.report = reports / ("assessment report.json" if spaced_paths else "assessment.json")
        self.output = self.root / "github-output.txt"
        self.summary = self.root / "step-summary.md"
        shutil.copy2(FIXTURES / snapshot, self.snapshot)
        shutil.copy2(FIXTURES / policy, self.policy)
        self.output.write_text("", encoding="utf-8")
        self.summary.write_text("", encoding="utf-8")

    def environment(self) -> dict[str, str]:
        return {
            "GITHUB_WORKSPACE": str(self.root),
            "GITHUB_OUTPUT": str(self.output),
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "RIGPILOT_ACTION_SNAPSHOT": str(self.snapshot.relative_to(self.root)),
            "RIGPILOT_ACTION_POLICY": str(self.policy.relative_to(self.root)),
            "RIGPILOT_ACTION_REPORT": str(self.report.relative_to(self.root)),
        }

    def run(self) -> tuple[int, str, str, dict[str, str], str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = run_action(self.environment(), error_stream=stderr)
        return (
            exit_code,
            stdout.getvalue(),
            stderr.getvalue(),
            read_outputs(self.output),
            self.summary.read_text(encoding="utf-8"),
        )


class GitHubActionResultTests(unittest.TestCase):
    def test_policy_report_drives_outputs_and_compact_failure_summary(self) -> None:
        report = load_fixture("policy-guidance-findings-v1.json")
        original = copy.deepcopy(report)

        first = build_action_result(report, "reports/assessment.json")
        second = build_action_result(copy.deepcopy(report), "reports/assessment.json")

        self.assertEqual(first, second)
        self.assertEqual(report, original)
        self.assertEqual(first.status, "fail")
        self.assertFalse(first.passed)
        self.assertEqual(first.warnings, 1)
        self.assertEqual(first.critical, 1)
        self.assertEqual(first.failed, 1)
        self.assertEqual(first.exit_code, 3)
        self.assertIn("**Status:** FAIL", first.summary)
        self.assertIn("storage.critically_low_capacity", first.summary)
        self.assertNotIn("bios.release_date_stale", first.summary)
        self.assertLessEqual(first.summary.count("- **`"), 20)

    def test_pass_with_warnings_lists_warning_rules_without_inventing_pass_counts(self) -> None:
        report = load_fixture("policy-guidance-findings-v1.json")
        report["policy"]["fail_on"] = None
        report["decision"] = {
            "triggered": False,
            "matching_finding_indices": [],
            "exit_code": 0,
        }
        report = validate_policy_report(report)

        result = build_action_result(report, "assessment.json")

        self.assertEqual(result.status, "pass")
        self.assertTrue(result.passed)
        self.assertIn("## Warnings", result.summary)
        self.assertIn("bios.release_date_stale", result.summary)
        self.assertNotIn("## Policy-triggering findings", result.summary)

    def test_report_path_is_html_escaped_in_summary(self) -> None:
        result = build_action_result(
            load_fixture("policy-clean-v1.json"), "reports/<unsafe>&report.json"
        )
        self.assertIn("reports/&lt;unsafe&gt;&amp;report.json", result.summary)
        self.assertNotIn("<unsafe>", result.summary)

    def test_large_failure_summary_is_capped_without_changing_report_counts(self) -> None:
        snapshot = load_fixture("snapshot-success-v1.json")
        snapshot["checks"]["storage"]["data"] = [
            {
                "DeviceID": f"{letter}:",
                "VolumeName": None,
                "Size": 1024**4,
                "FreeSpace": 4 * 1024**3,
            }
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        ]
        report = build_policy_report(
            assess_snapshot(snapshot), Policy(checks=("storage",), fail_on="critical")
        )

        result = build_action_result(report, "assessment.json")

        self.assertEqual(result.failed, 26)
        self.assertEqual(result.summary.count("- **`"), 20)
        self.assertIn("6 additional findings omitted", result.summary)


class GitHubActionRunnerTests(unittest.TestCase):
    def test_clean_policy_gate_passes_and_writes_schema_valid_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = ActionWorkspace(directory)
            exit_code, stdout, stderr, outputs, summary = workspace.run()
            report = json.loads(workspace.report.read_text(encoding="utf-8"))

        validate_policy_report(report)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, "RigPilot policy gate: PASS\n")
        self.assertEqual(stderr, "")
        self.assertEqual(outputs["status"], "pass")
        self.assertEqual(outputs["passed"], "true")
        self.assertEqual(outputs["warnings"], "0")
        self.assertEqual(outputs["failed"], "0")
        self.assertEqual(outputs["critical"], "0")
        self.assertEqual(outputs["report"], "reports/assessment.json")
        self.assertEqual(outputs["exit_code"], "0")
        self.assertEqual(outputs["summary"], "true")
        self.assertIn("**Status:** PASS", summary)
        self.assertIn("No policy-triggering findings.", summary)

    def test_warning_findings_can_pass_a_critical_only_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = ActionWorkspace(
                directory,
                snapshot="snapshot-failure-v1.json",
                policy="policy-config-critical-v1.json",
            )
            exit_code, _, stderr, outputs, summary = workspace.run()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(outputs["status"], "pass")
        self.assertEqual(outputs["passed"], "true")
        self.assertEqual(outputs["warnings"], "12")
        self.assertEqual(outputs["failed"], "0")
        self.assertIn("## Warnings", summary)
        self.assertIn("probe.failed", summary)

    def test_policy_failure_emits_report_summary_outputs_then_returns_three(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = ActionWorkspace(directory, snapshot="snapshot-failure-v1.json")
            exit_code, stdout, stderr, outputs, summary = workspace.run()
            report = json.loads(workspace.report.read_text(encoding="utf-8"))

        validate_policy_report(report)
        self.assertEqual(exit_code, 3)
        self.assertEqual(stdout, "RigPilot policy gate: FAIL\n")
        self.assertEqual(stderr, "")
        self.assertEqual(outputs["status"], "fail")
        self.assertEqual(outputs["passed"], "false")
        self.assertEqual(outputs["warnings"], "2")
        self.assertEqual(outputs["failed"], "2")
        self.assertEqual(outputs["exit_code"], "3")
        self.assertEqual(outputs["summary"], "true")
        self.assertIn("## Policy-triggering findings", summary)
        self.assertIn("probe.failed", summary)
        self.assertIn("(warning, bios)", summary)
        self.assertIn("(warning, storage)", summary)

    def test_paths_with_spaces_are_passed_without_shell_interpolation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rigpilot action ") as directory:
            workspace = ActionWorkspace(directory, spaced_paths=True)
            exit_code, _, stderr, outputs, _ = workspace.run()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(outputs["report"], "reports with spaces/assessment report.json")

    def test_malformed_snapshot_and_invalid_or_missing_policy_are_input_errors(self) -> None:
        cases = ("malformed-snapshot", "invalid-policy", "missing-policy")
        for case in cases:
            with tempfile.TemporaryDirectory() as directory:
                workspace = ActionWorkspace(directory)
                if case == "malformed-snapshot":
                    workspace.snapshot.write_text("{}", encoding="utf-8")
                elif case == "invalid-policy":
                    workspace.policy.write_text("{}", encoding="utf-8")
                else:
                    workspace.policy.unlink()
                with self.subTest(case=case):
                    exit_code, stdout, stderr, outputs, summary = workspace.run()
                    self.assertEqual(exit_code, 2)
                    self.assertEqual(stdout, "")
                    self.assertEqual(
                        stderr, "RigPilot policy gate could not complete (exit code 2).\n"
                    )
                    self.assertEqual(outputs["status"], "error")
                    self.assertEqual(outputs["exit_code"], "2")
                    self.assertIn("input or configuration error", summary)
                    self.assertFalse(workspace.report.exists())

    def test_missing_required_action_input_is_a_distinct_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = ActionWorkspace(directory)
            environment = workspace.environment()
            del environment["RIGPILOT_ACTION_SNAPSHOT"]
            stderr = io.StringIO()

            exit_code = run_action(environment, error_stream=stderr)
            outputs = read_outputs(workspace.output)

        self.assertEqual(exit_code, 2)
        self.assertEqual(outputs["status"], "error")
        self.assertEqual(outputs["exit_code"], "2")
        self.assertEqual(
            stderr.getvalue(), "RigPilot policy gate could not complete (exit code 2).\n"
        )

    def test_report_must_be_new_and_remain_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = ActionWorkspace(directory)
            workspace.report.write_text("KEEP", encoding="utf-8")
            exit_code, _, _, outputs, _ = workspace.run()
            self.assertEqual(exit_code, 2)
            self.assertEqual(outputs["status"], "error")
            self.assertEqual(workspace.report.read_text(encoding="utf-8"), "KEEP")

        with tempfile.TemporaryDirectory() as directory:
            workspace = ActionWorkspace(directory)
            environment = workspace.environment()
            environment["RIGPILOT_ACTION_REPORT"] = "../outside.json"
            exit_code = run_action(environment, error_stream=io.StringIO())
            self.assertEqual(exit_code, 2)
            self.assertFalse((workspace.root.parent / "outside.json").exists())

    def test_runs_are_deterministic_for_identical_relative_inputs(self) -> None:
        results = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as directory:
                workspace = ActionWorkspace(directory, snapshot="snapshot-failure-v1.json")
                exit_code, stdout, stderr, outputs, summary = workspace.run()
                report = workspace.report.read_text(encoding="utf-8")
                results.append((exit_code, stdout, stderr, outputs, summary, report))
        self.assertEqual(results[0], results[1])

    def test_unexpected_failures_are_private_and_process_control_propagates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = ActionWorkspace(directory)
            with patch(
                "rigpilot.github_action._invoke_rigpilot",
                side_effect=RuntimeError("SECRET RUNNER PATH"),
            ):
                stderr = io.StringIO()
                exit_code = run_action(workspace.environment(), error_stream=stderr)
            self.assertEqual(exit_code, 1)
            self.assertNotIn("SECRET", stderr.getvalue())
            self.assertEqual(read_outputs(workspace.output)["status"], "error")

        for exception in (KeyboardInterrupt(), SystemExit(9)):
            with tempfile.TemporaryDirectory() as directory:
                workspace = ActionWorkspace(directory)
                with (
                    self.subTest(exception=type(exception).__name__),
                    patch("rigpilot.github_action._invoke_rigpilot", side_effect=exception),
                    self.assertRaises(type(exception)),
                ):
                    run_action(workspace.environment(), error_stream=io.StringIO())

    def test_metadata_write_failure_is_private_and_does_not_duplicate_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = ActionWorkspace(directory)
            environment = workspace.environment()
            environment["GITHUB_OUTPUT"] = str(workspace.root / "missing" / "output.txt")
            stderr = io.StringIO()

            exit_code = run_action(environment, error_stream=stderr)
            summary = workspace.summary.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 1)
        self.assertEqual(stderr.getvalue(), "RigPilot policy gate could not initialize.\n")
        self.assertEqual(summary.count("# RigPilot Assessment"), 1)

    def test_sensitive_input_paths_and_cli_diagnostics_are_not_logged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = ActionWorkspace(directory)
            secret = "SECRET-SNAPSHOT-NAME"
            environment = workspace.environment()
            environment["RIGPILOT_ACTION_SNAPSHOT"] = f"{secret}.json"
            stderr = io.StringIO()
            exit_code = run_action(environment, error_stream=stderr)

        self.assertEqual(exit_code, 2)
        self.assertNotIn(secret, stderr.getvalue())

        with tempfile.TemporaryDirectory() as directory:
            workspace = ActionWorkspace(directory)
            workspace.policy.write_text(
                json.dumps(
                    {
                        "policy_config_schema_version": "1.0",
                        "minimum_severity": "SECRET-POLICY-VALUE",
                        "rule_groups": None,
                        "checks": None,
                        "fail_on": None,
                    }
                ),
                encoding="utf-8",
            )
            exit_code, stdout, stderr, outputs, summary = workspace.run()
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(outputs["status"], "error")
        self.assertNotIn("SECRET-POLICY-VALUE", stderr)
        self.assertNotIn("SECRET-POLICY-VALUE", summary)


class GitHubActionMetadataTests(unittest.TestCase):
    def test_action_metadata_has_small_secure_versioned_interface(self) -> None:
        metadata = (PROJECT_ROOT / "action.yml").read_text(encoding="utf-8")
        self.assertIn("using: composite", metadata)
        self.assertIn("snapshot:", metadata)
        self.assertIn("policy:", metadata)
        self.assertIn("default: rigpilot-assessment.json", metadata)
        for output in (
            "status",
            "passed",
            "warnings",
            "failed",
            "critical",
            "report",
            "exit_code",
            "summary",
        ):
            self.assertIn(f"  {output}:\n", metadata)
        self.assertIn("actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97", metadata)
        self.assertNotIn("github.token", metadata.lower())
        self.assertNotIn("secrets.", metadata.lower())
        self.assertIn("RIGPILOT_ACTION_SNAPSHOT: ${{ inputs.snapshot }}", metadata)
        self.assertNotIn("run: ${{ inputs.", metadata)

    def test_dogfood_and_released_workflows_are_non_recursive_and_least_privilege(self) -> None:
        ci = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        released = (PROJECT_ROOT / ".github" / "workflows" / "released-action-smoke.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("permissions:\n  contents: read", ci)
        self.assertIn("uses: ./", ci)
        self.assertIn("continue-on-error: true", ci)
        self.assertIn("workflow_dispatch:", released)
        self.assertNotIn("push:", released)
        self.assertNotIn("pull_request:", released)
        self.assertIn("uses: Arturo6PR/rigpilot@v0.9.0", released)
        self.assertIn("permissions:\n  contents: read", released)

    def test_both_policy_config_fixtures_are_strictly_valid(self) -> None:
        from rigpilot.policy_config import validate_policy_config

        for name in ("policy-config-v1.json", "policy-config-critical-v1.json"):
            with self.subTest(name=name):
                validate_policy_config(load_fixture(name))


if __name__ == "__main__":
    unittest.main()
