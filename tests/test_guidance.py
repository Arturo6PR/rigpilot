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
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from rigpilot.assessment import assess_snapshot, render_assessment_human, validate_assessment
from rigpilot.cli import main
from rigpilot.guidance import (
    GUIDANCE_CATALOG,
    build_guidance,
    render_guidance_human,
    validate_guidance,
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


def guidance_schema_catalog(schema: dict) -> dict[str, dict]:
    entries = {}
    for name, definition in schema["$defs"].items():
        if name == "guidanceEntry":
            continue
        properties = definition["properties"]
        rule_constraint = properties["rule_id"]
        rule_ids = (
            [rule_constraint["const"]] if "const" in rule_constraint else rule_constraint["enum"]
        )
        expected = {
            "explanation": properties["explanation"]["const"],
            "next_steps": properties["next_steps"]["const"],
        }
        entries.update({rule_id: expected for rule_id in rule_ids})
    return entries


def reachable_assessments() -> dict[str, dict]:
    probe_snapshot = load_fixture("snapshot-success-v1.json")
    probe_snapshot["checks"]["python"] = {
        "status": "unavailable",
        "data": None,
        "message": "Skipped by selection: python",
        "duration_ms": 0.0,
    }
    probe_snapshot["checks"]["nvidia_gpu"] = {
        "status": "unavailable",
        "data": None,
        "message": "Optional tooling unavailable",
        "duration_ms": 1.0,
    }
    probe_snapshot["checks"]["uptime"] = {
        "status": "unavailable",
        "data": None,
        "message": "Local support unavailable",
        "duration_ms": 1.0,
    }
    probe_snapshot["checks"]["git"] = {
        "status": "failed",
        "data": None,
        "message": "Probe failed safely",
        "duration_ms": 1.0,
    }

    storage_snapshot = load_fixture("snapshot-success-v1.json")
    storage_snapshot["checks"]["storage"]["data"] = [
        {"DeviceID": "D:", "VolumeName": None, "Size": 1024**4, "FreeSpace": 4 * GIB},
        {"DeviceID": "E:", "VolumeName": None, "Size": 1024**4, "FreeSpace": 15 * GIB},
    ]

    baseline = load_fixture("snapshot-success-v1.json")
    hardware_snapshot = copy.deepcopy(baseline)
    hardware_snapshot["checks"]["system"]["data"]["Model"] = "Changed system"
    hardware_snapshot["checks"]["cpu"]["data"][0]["Name"] = "Changed CPU"
    hardware_snapshot["checks"]["memory_modules"]["data"][0]["PartNumber"] = "Changed RAM"
    hardware_snapshot["checks"]["physical_disks"]["data"][0]["Model"] = "Changed disk"
    hardware_snapshot["checks"]["nvidia_gpu"]["data"][0]["name"] = "Changed GPU"

    bios_assessments = {}
    for label, release_date in (
        ("bios_missing", None),
        ("bios_future", "2027-01-01"),
        ("bios_stale", "2020-01-01"),
    ):
        snapshot = load_fixture("snapshot-success-v1.json")
        snapshot["checks"]["bios"]["data"]["ReleaseDate"] = release_date
        bios_assessments[label] = assess_snapshot(snapshot)

    return {
        "probe": assess_snapshot(probe_snapshot),
        "storage": assess_snapshot(storage_snapshot),
        "hardware": assess_snapshot(hardware_snapshot, baseline),
        **bios_assessments,
    }


class GuidanceTests(unittest.TestCase):
    def test_assessment_catalog_and_guidance_schema_rules_and_text_agree(self) -> None:
        assessment_rules = schema_rule_ids(load_schema("assessment.schema.json"))
        guidance_schema = load_schema("guidance.schema.json")
        guidance_rules = schema_rule_ids(guidance_schema)
        catalog = {
            rule_id: {
                "explanation": template.explanation,
                "next_steps": [asdict(action) for action in template.next_steps],
            }
            for rule_id, template in GUIDANCE_CATALOG.items()
        }

        self.assertEqual(set(catalog), assessment_rules)
        self.assertEqual(guidance_rules, assessment_rules)
        self.assertEqual(catalog, guidance_schema_catalog(guidance_schema))

    def test_every_catalog_rule_is_reachable_from_a_valid_assessment_finding(self) -> None:
        represented = set()
        for name, assessment in reachable_assessments().items():
            with self.subTest(name=name):
                validate_assessment(assessment)
                represented.update(finding["rule_id"] for finding in assessment["findings"])
        self.assertEqual(represented, set(GUIDANCE_CATALOG))

    def test_clean_and_findings_reports_match_golden_fixtures(self) -> None:
        cases = (
            ("assessment-clean-v1.json", "guidance-clean-v1.json"),
            ("assessment-findings-v1.json", "guidance-findings-v1.json"),
        )
        for assessment_name, guidance_name in cases:
            with self.subTest(assessment=assessment_name):
                self.assertEqual(
                    build_guidance(load_fixture(assessment_name)), load_fixture(guidance_name)
                )

    def test_output_is_deterministic_and_does_not_mutate_input(self) -> None:
        assessment = load_fixture("assessment-findings-v1.json")
        original = copy.deepcopy(assessment)
        first = build_guidance(assessment)
        second = build_guidance(assessment)
        self.assertEqual(first, second)
        self.assertEqual(assessment, original)
        self.assertIsNot(first["assessment"], assessment)
        self.assertEqual(
            [entry["finding_index"] for entry in first["guidance"]],
            list(range(len(assessment["findings"]))),
        )

    def test_multiple_volume_findings_retain_distinct_ordered_indexes(self) -> None:
        assessment = reachable_assessments()["storage"]
        report = build_guidance(assessment)

        self.assertEqual(
            [entry["rule_id"] for entry in report["guidance"]],
            ["storage.critically_low_capacity", "storage.low_capacity"],
        )
        self.assertEqual([entry["finding_index"] for entry in report["guidance"]], [0, 1])

    def test_clean_human_guidance_is_explicit(self) -> None:
        output = render_guidance_human(load_fixture("guidance-clean-v1.json"))
        self.assertEqual(output, "Guidance\nNo findings require guidance.")

    def test_schema_and_semantic_validation_reject_tampering(self) -> None:
        original = load_fixture("guidance-findings-v1.json")
        mutations = []
        for mutate in (
            lambda payload: payload["guidance"][0].update(finding_index=1),
            lambda payload: payload["guidance"][0].update(rule_id="probe.failed"),
            lambda payload: payload["guidance"][0].update(explanation="Changed wording"),
            lambda payload: payload["guidance"][0]["next_steps"][0].update(text="Changed wording"),
            lambda payload: payload["guidance"].append(copy.deepcopy(payload["guidance"][0])),
            lambda payload: payload["guidance"].reverse(),
        ):
            payload = copy.deepcopy(original)
            mutate(payload)
            mutations.append(payload)
        for payload in mutations:
            with self.subTest(payload=payload["guidance"]), self.assertRaises(ValueError):
                validate_guidance(payload)

    def test_static_catalog_contains_no_executable_or_prohibited_advice(self) -> None:
        serialized = json.dumps(
            {
                rule_id: {
                    "explanation": template.explanation,
                    "next_steps": [action.__dict__ for action in template.next_steps],
                }
                for rule_id, template in GUIDANCE_CATALOG.items()
            }
        ).casefold()
        for prohibited in (
            "powershell",
            "cmd.exe",
            "winget",
            "curl ",
            "http://",
            "https://",
            "delete ",
            "download ",
            "registry",
            "service",
            "startup item",
            "power plan",
            "rigpilot troubleshooting",
            "rigpilot's supported local prerequisites",
            "is failing",
            "was tampered",
            "is vulnerable",
            "is compromised",
        ):
            self.assertNotIn(prohibited, serialized)
        self.assertNotRegex(serialized, r"(?:bios|firmware) version v?\d")
        for template in GUIDANCE_CATALOG.values():
            for action in template.next_steps:
                self.assertIn(action.kind, {"review", "verify", "plan", "consult"})

    def test_guidance_entries_do_not_copy_sensitive_snapshot_values(self) -> None:
        snapshot = load_fixture("snapshot-success-v1.json")
        secrets = (
            "SECRET-HOST",
            "SECRET VOLUME",
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
        report = build_guidance(assess_snapshot(snapshot))
        serialized_report = json.dumps(report)
        rendered = (
            f"{render_assessment_human(report['assessment'])}\n\n{render_guidance_human(report)}"
        )
        for secret in secrets:
            self.assertNotIn(secret, serialized_report)
            self.assertNotIn(secret, rendered)


class GuidanceCliTests(unittest.TestCase):
    def test_default_output_is_byte_for_byte_unchanged(self) -> None:
        assessment = load_fixture("assessment-clean-v1.json")
        expected = f"{json.dumps(assessment, indent=2, ensure_ascii=False)}\n"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(
                main(["assess", str(FIXTURES / "snapshot-success-v1.json"), "--json"]), 0
            )
        self.assertEqual(stdout.getvalue(), expected)

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["assess", str(FIXTURES / "snapshot-success-v1.json")]), 0)
        self.assertEqual(stdout.getvalue(), f"{render_assessment_human(assessment)}\n")

    def test_default_mocked_live_output_is_byte_for_byte_unchanged(self) -> None:
        snapshot = load_fixture("snapshot-success-v1.json")
        assessment = assess_snapshot(snapshot)
        cases = (
            (["--json"], f"{json.dumps(assessment, indent=2, ensure_ascii=False)}\n"),
            ([], f"{render_assessment_human(assessment)}\n"),
        )
        for arguments, expected in cases:
            with (
                self.subTest(arguments=arguments),
                patch(
                    "rigpilot.cli._collect_assessment_snapshot", return_value=snapshot
                ) as collect,
                contextlib.redirect_stdout(stdout := io.StringIO()),
            ):
                self.assertEqual(main(["assess", "--live", *arguments]), 0)
                self.assertEqual(stdout.getvalue(), expected)
                collect.assert_called_once_with(timeout=5.0, only=None, skip=None)

    def test_saved_human_and_json_guidance(self) -> None:
        path = FIXTURES / "snapshot-success-v1.json"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["assess", str(path), "--guidance"]), 0)
        self.assertIn("RigPilot assessment\n", stdout.getvalue())
        self.assertIn("\n\nGuidance\nNo findings require guidance.", stdout.getvalue())

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["assess", str(path), "--guidance", "--json"]), 0)
        validate_guidance(json.loads(stdout.getvalue()))

    def test_mocked_live_human_and_json_guidance_collect_once(self) -> None:
        snapshot = load_fixture("snapshot-success-v1.json")
        for arguments in (["--json"], []):
            with (
                self.subTest(arguments=arguments),
                patch(
                    "rigpilot.cli._collect_assessment_snapshot", return_value=snapshot
                ) as collect,
                contextlib.redirect_stdout(stdout := io.StringIO()),
            ):
                self.assertEqual(main(["assess", "--live", "--guidance", *arguments]), 0)
                if arguments:
                    validate_guidance(json.loads(stdout.getvalue()))
                else:
                    self.assertIn("\n\nGuidance\nNo findings require guidance.", stdout.getvalue())
                collect.assert_called_once_with(timeout=5.0, only=None, skip=None)

    def test_saved_guidance_failure_is_concise_and_private(self) -> None:
        stderr = io.StringIO()
        with (
            patch("rigpilot.cli.build_guidance", side_effect=RuntimeError("SECRET DETAIL")),
            contextlib.redirect_stderr(stderr),
        ):
            result = main(["assess", str(FIXTURES / "snapshot-success-v1.json"), "--guidance"])
        self.assertEqual(result, 1)
        self.assertEqual(stderr.getvalue(), "rigpilot assess: guidance failed\n")

    def test_saved_guidance_serialization_and_rendering_failures_are_private(self) -> None:
        cases = (
            ("rigpilot.cli.json.dumps", ["--json"]),
            ("rigpilot.cli.render_guidance_human", []),
        )
        for target, arguments in cases:
            stderr = io.StringIO()
            with (
                self.subTest(target=target),
                patch(target, side_effect=AttributeError("SECRET GUIDANCE FAILURE")),
                contextlib.redirect_stderr(stderr),
            ):
                result = main(
                    [
                        "assess",
                        str(FIXTURES / "snapshot-success-v1.json"),
                        "--guidance",
                        *arguments,
                    ]
                )
            self.assertEqual(result, 1)
            self.assertEqual(stderr.getvalue(), "rigpilot assess: guidance failed\n")

    @patch("rigpilot.cli._collect_assessment_snapshot")
    def test_live_guidance_failure_uses_existing_private_boundary(self, collect) -> None:
        collect.return_value = load_fixture("snapshot-success-v1.json")
        stderr = io.StringIO()
        with (
            patch("rigpilot.cli.build_guidance", side_effect=RuntimeError("SECRET DETAIL")),
            contextlib.redirect_stderr(stderr),
        ):
            result = main(["assess", "--live", "--guidance"])
        self.assertEqual(result, 1)
        self.assertEqual(stderr.getvalue(), "rigpilot assess: live assessment failed\n")

    def test_process_control_exceptions_propagate(self) -> None:
        for exception in (KeyboardInterrupt(), SystemExit(7)):
            with (
                self.subTest(exception=type(exception).__name__),
                patch("rigpilot.cli.build_guidance", side_effect=exception),
                self.assertRaises(type(exception)),
            ):
                main(["assess", str(FIXTURES / "snapshot-success-v1.json"), "--guidance"])

    @patch("rigpilot.cli._collect_assessment_snapshot")
    def test_live_guidance_process_control_exceptions_propagate(self, collect) -> None:
        collect.return_value = load_fixture("snapshot-success-v1.json")
        for exception in (KeyboardInterrupt(), SystemExit(8)):
            with (
                self.subTest(exception=type(exception).__name__),
                patch("rigpilot.cli.build_guidance", side_effect=exception),
                self.assertRaises(type(exception)),
            ):
                main(["assess", "--live", "--guidance"])
        self.assertEqual(collect.call_count, 2)


class GuidanceSchemaTests(unittest.TestCase):
    def test_schema_is_valid_draft_2020_12_and_golden_fixtures_validate(self) -> None:
        schema = json.loads(
            (Path(__file__).parents[1] / "docs" / "guidance.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)
        for name in ("guidance-clean-v1.json", "guidance-findings-v1.json"):
            validate_guidance(load_fixture(name))

    def test_wheel_contains_and_loads_all_three_packaged_schemas(self) -> None:
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
                metadata = archive.read(metadata_name).decode("utf-8")
                archive.extractall(target_directory)
            for name in (
                "rigpilot/snapshot.schema.json",
                "rigpilot/assessment.schema.json",
                "rigpilot/guidance.schema.json",
            ):
                self.assertIn(name, names)
            self.assertIn("Requires-Dist: referencing>=0.28.4", metadata)
            smoke_code = f"""
import sys
sys.path.insert(0, {str(target_directory)!r})
from importlib import resources
from rigpilot.guidance import _guidance_validator
package = resources.files('rigpilot')
for name in ('snapshot.schema.json', 'assessment.schema.json', 'guidance.schema.json'):
    assert package.joinpath(name).is_file()
_guidance_validator()
print('installed_guidance_schema_smoke=PASS')
"""
            completed = subprocess.run(
                [sys.executable, "-I", "-c", smoke_code],
                cwd=temporary,
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(completed.stdout.strip(), "installed_guidance_schema_smoke=PASS")


if __name__ == "__main__":
    unittest.main()
