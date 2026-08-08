import contextlib
import io
import json
import unittest
from math import inf, nan
from unittest.mock import patch

from rigpilot.cli import main, render_human
from rigpilot.models import CheckResult, Snapshot


def sample_snapshot() -> Snapshot:
    return Snapshot(
        operating_system=CheckResult.success({"Caption": "Windows 11"}),
        cpu=CheckResult.success(
            [{"Name": "Test CPU", "NumberOfCores": 8, "NumberOfLogicalProcessors": 16}]
        ),
        memory=CheckResult.success(
            {"TotalVisibleMemorySize": 33_554_432, "FreePhysicalMemory": 16_777_216}
        ),
        storage=CheckResult.success(
            [
                {
                    "DeviceID": "C:",
                    "VolumeName": "System",
                    "Size": 1024**4,
                    "FreeSpace": 512 * 1024**3,
                }
            ]
        ),
        python=CheckResult.success({"version": "3.12.0"}),
        git=CheckResult.success({"version": "2.51.0"}),
        nvidia_gpu=CheckResult.unavailable("Command not found: nvidia-smi"),
    )


class CliTests(unittest.TestCase):
    def test_human_output_shows_statuses(self) -> None:
        output = render_human(sample_snapshot())

        self.assertIn("Operating system [success]", output)
        self.assertIn("NVIDIA GPU [unavailable]", output)
        self.assertIn("Total: 32.0 GiB", output)
        self.assertIn("Total: 1.0 TiB", output)
        self.assertIn("C: (System)", output)
        self.assertNotIn("TotalVisibleMemorySize", output)

    @patch("rigpilot.cli.collect_snapshot", return_value=sample_snapshot())
    def test_json_output_is_structured(self, collect) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(["--json", "--timeout", "2"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["operating_system"]["status"], "success")
        collect.assert_called_once_with(timeout=2.0)

    @patch("rigpilot.cli.collect_snapshot")
    def test_invalid_timeouts_are_rejected_before_collection(self, collect) -> None:
        for timeout in ("0", "-1", str(nan), str(inf)):
            with self.subTest(timeout=timeout):
                with (
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as raised,
                ):
                    main(["--timeout", timeout])
                self.assertEqual(raised.exception.code, 2)
        collect.assert_not_called()
