import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from rigpilot.cli import main
from rigpilot.diffing import compare_snapshots, load_snapshot, render_diff_human

FIXTURES = Path(__file__).parent / "fixtures"


class SnapshotDiffTests(unittest.TestCase):
    def test_identical_snapshots_ignore_timing_noise(self) -> None:
        before = load_snapshot(FIXTURES / "snapshot-success-v1.json")
        after = json.loads(json.dumps(before))
        after["collected_at_utc"] = "2026-08-08T18:00:00+00:00"
        after["checks"]["cpu"]["duration_ms"] = 999

        diff = compare_snapshots(before, after)

        self.assertEqual(diff["changes"], [])
        self.assertIn("No inventory changes", render_diff_human(diff))

    def test_status_and_data_changes_are_reported(self) -> None:
        before = load_snapshot(FIXTURES / "snapshot-success-v1.json")
        after = load_snapshot(FIXTURES / "snapshot-failure-v1.json")

        diff = compare_snapshots(before, after)

        self.assertEqual(len(diff["changes"]), 12)
        cpu = next(change for change in diff["changes"] if change["check"] == "cpu")
        self.assertEqual(cpu["status_before"], "success")
        self.assertEqual(cpu["status_after"], "failed")
        self.assertTrue(cpu["data_changed"])

    def test_hostname_only_change_is_reported_without_values(self) -> None:
        before = load_snapshot(FIXTURES / "snapshot-success-v1.json")
        after = json.loads(json.dumps(before))
        after["hostname"] = "DIFFERENT-SECRET-HOST"

        diff = compare_snapshots(before, after)
        rendered = render_diff_human(diff)

        self.assertTrue(diff["hostname_changed"])
        self.assertEqual(diff["changes"], [])
        self.assertIn("Hostname: changed (values hidden)", rendered)
        self.assertNotIn("TEST-HOST", json.dumps(diff))
        self.assertNotIn("DIFFERENT-SECRET-HOST", rendered)

    def test_malformed_json_structures_are_rejected(self) -> None:
        valid = load_snapshot(FIXTURES / "snapshot-success-v1.json")
        cases = {}

        missing_checks = json.loads(json.dumps(valid))
        del missing_checks["checks"]
        cases["missing checks"] = missing_checks

        invalid_result = json.loads(json.dumps(valid))
        invalid_result["checks"]["cpu"] = "invalid"
        cases["invalid result"] = invalid_result

        missing_field = json.loads(json.dumps(valid))
        del missing_field["checks"]["cpu"]["status"]
        cases["missing result field"] = missing_field

        unknown_check = json.loads(json.dumps(valid))
        unknown_check["checks"]["registry"] = unknown_check["checks"]["git"]
        cases["unknown check"] = unknown_check

        incompatible_data = json.loads(json.dumps(valid))
        incompatible_data["checks"]["cpu"]["data"] = {"cores": 8}
        cases["schema-incompatible data"] = incompatible_data

        for label, payload in cases.items():
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, "invalid snapshot"):
                compare_snapshots(payload, valid)

    def test_supported_powershell_file_encodings(self) -> None:
        text = (FIXTURES / "snapshot-success-v1.json").read_text(encoding="utf-8")
        encodings = {
            "utf8.json": text.encode("utf-8"),
            "utf8-bom.json": text.encode("utf-8-sig"),
            "utf16-le-bom.json": text.encode("utf-16"),
            "utf16-be-bom.json": b"\xfe\xff" + text.encode("utf-16-be"),
        }
        with tempfile.TemporaryDirectory() as directory:
            for name, content in encodings.items():
                with self.subTest(name=name):
                    path = Path(directory) / name
                    path.write_bytes(content)
                    self.assertEqual(load_snapshot(path)["schema_version"], "1.0")

    def test_cli_json_diff(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = main(
                [
                    "diff",
                    str(FIXTURES / "snapshot-success-v1.json"),
                    str(FIXTURES / "snapshot-failure-v1.json"),
                    "--json",
                ]
            )

        self.assertEqual(result, 0)
        self.assertEqual(len(json.loads(stdout.getvalue())["changes"]), 12)

    def test_cli_reports_malformed_snapshot_without_traceback(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = main(["diff", str(FIXTURES / "missing.json"), "other.json"])

        self.assertEqual(result, 2)
        self.assertIn("rigpilot diff:", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_cli_reports_schema_error_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text('{"schema_version":"1.0"}', encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = main(["diff", str(path), str(FIXTURES / "snapshot-success-v1.json")])

        self.assertEqual(result, 2)
        self.assertIn("invalid snapshot", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
