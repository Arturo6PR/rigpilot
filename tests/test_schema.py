import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from rigpilot.models import CheckResult, Snapshot

CHECK_NAMES = {
    "operating_system",
    "cpu",
    "memory",
    "storage",
    "python",
    "git",
    "nvidia_gpu",
    "system",
    "bios",
    "memory_modules",
    "physical_disks",
    "uptime",
}


def complete_snapshot(result: CheckResult) -> Snapshot:
    return Snapshot(
        operating_system=result,
        cpu=result,
        memory=result,
        storage=result,
        python=result,
        git=result,
        nvidia_gpu=result,
        system=result,
        bios=result,
        memory_modules=result,
        physical_disks=result,
        uptime=result,
        schema_version="1.0",
        collected_at_utc="2026-08-08T17:00:00+00:00",
        hostname="TEST-HOST",
    )


class SnapshotSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        schema_path = Path(__file__).parents[1] / "docs" / "snapshot.schema.json"
        cls.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        cls.validator = Draft202012Validator(cls.schema, format_checker=FormatChecker())

    def test_schema_is_valid_draft_2020_12(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.assertEqual(self.schema["$id"], "urn:rigpilot:schema:snapshot:1.0")

    def test_required_check_names_are_explicit(self) -> None:
        checks_schema = self.schema["properties"]["checks"]
        self.assertEqual(set(checks_schema["required"]), CHECK_NAMES)
        self.assertEqual(set(checks_schema["properties"]), CHECK_NAMES)
        self.assertFalse(checks_schema["additionalProperties"])

    def test_complete_success_snapshot_validates(self) -> None:
        snapshot = complete_snapshot(CheckResult.success({"sample": True}))
        self.validator.validate(snapshot.to_dict())

    def test_complete_failure_snapshot_validates(self) -> None:
        snapshot = complete_snapshot(CheckResult.failed("probe failed safely"))
        self.validator.validate(snapshot.to_dict())
