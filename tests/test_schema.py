import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from rigpilot.collectors import collect_snapshot

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


class SnapshotSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        schema_path = Path(__file__).parents[1] / "docs" / "snapshot.schema.json"
        cls.fixtures_path = Path(__file__).parent / "fixtures"
        cls.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        cls.validator = Draft202012Validator(cls.schema, format_checker=FormatChecker())

    def load_fixture(self, name: str) -> dict:
        return json.loads((self.fixtures_path / name).read_text(encoding="utf-8"))

    def test_schema_is_valid_draft_2020_12(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.assertEqual(self.schema["$id"], "urn:rigpilot:schema:snapshot:1.0")

    def test_required_check_names_are_explicit(self) -> None:
        checks_schema = self.schema["properties"]["checks"]
        self.assertEqual(set(checks_schema["required"]), CHECK_NAMES)
        self.assertEqual(set(checks_schema["properties"]), CHECK_NAMES)
        self.assertFalse(checks_schema["additionalProperties"])

    def test_complete_success_snapshot_validates(self) -> None:
        payload = self.load_fixture("snapshot-success-v1.json")
        self.validator.validate(payload)
        self.assertEqual(set(payload["checks"]), CHECK_NAMES)

    def test_complete_failure_snapshot_validates(self) -> None:
        payload = self.load_fixture("snapshot-failure-v1.json")
        self.validator.validate(payload)
        self.assertTrue(all(check["status"] == "failed" for check in payload["checks"].values()))

    def test_success_payload_shape_is_enforced(self) -> None:
        payload = self.load_fixture("snapshot-success-v1.json")
        del payload["checks"]["cpu"]["data"][0]["NumberOfCores"]
        self.assertFalse(self.validator.is_valid(payload))

    def test_selective_snapshot_remains_schema_compatible(self) -> None:
        payload = collect_snapshot(only={"python"}).to_dict()
        self.validator.validate(payload)
        self.assertEqual(payload["checks"]["python"]["status"], "success")
        self.assertEqual(payload["checks"]["cpu"]["status"], "unavailable")

    def test_failed_and_unavailable_results_reject_non_null_data(self) -> None:
        for status in ("failed", "unavailable"):
            with self.subTest(status=status):
                payload = self.load_fixture("snapshot-failure-v1.json")
                payload["checks"]["cpu"]["status"] = status
                payload["checks"]["cpu"]["data"] = {"unexpected": True}
                self.assertFalse(self.validator.is_valid(payload))

    def test_failed_and_unavailable_results_reject_empty_messages(self) -> None:
        for status in ("failed", "unavailable"):
            with self.subTest(status=status):
                payload = self.load_fixture("snapshot-failure-v1.json")
                payload["checks"]["cpu"]["status"] = status
                payload["checks"]["cpu"]["message"] = ""
                self.assertFalse(self.validator.is_valid(payload))
