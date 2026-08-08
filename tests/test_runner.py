import subprocess
import unittest
from math import inf, nan
from unittest.mock import patch

from rigpilot.models import CheckStatus
from rigpilot.runner import run_command


class CommandRunnerTests(unittest.TestCase):
    @patch("rigpilot.runner.subprocess.run")
    def test_success(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(["tool"], 0, " output \n", "")

        result = run_command(["tool"], timeout=2)

        self.assertEqual(result.status, CheckStatus.SUCCESS)
        self.assertEqual(result.stdout, "output")
        self.assertFalse(run.call_args.kwargs["check"])
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(run.call_args.kwargs["timeout"], 2)

    @patch("rigpilot.runner.subprocess.run", side_effect=FileNotFoundError)
    def test_absent_command_is_unavailable(self, _run) -> None:
        result = run_command(["missing"])

        self.assertEqual(result.status, CheckStatus.UNAVAILABLE)
        self.assertIn("missing", result.message or "")

    @patch("rigpilot.runner.subprocess.run")
    def test_timeout_is_failed(self, run) -> None:
        run.side_effect = subprocess.TimeoutExpired(["slow"], 1)

        result = run_command(["slow"], timeout=1)

        self.assertEqual(result.status, CheckStatus.FAILED)
        self.assertIn("timed out", result.message or "")

    @patch("rigpilot.runner.subprocess.run")
    def test_nonzero_exit_is_failed(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(["bad"], 2, "", "problem")

        result = run_command(["bad"])

        self.assertEqual(result.status, CheckStatus.FAILED)
        self.assertIn("problem", result.message or "")

    @patch("rigpilot.runner.subprocess.run")
    def test_os_error_is_failed(self, run) -> None:
        run.side_effect = OSError("blocked")

        result = run_command(["tool"])

        self.assertEqual(result.status, CheckStatus.FAILED)
        self.assertIn("blocked", result.message or "")

    @patch("rigpilot.runner.subprocess.run")
    def test_invalid_timeouts_fail_without_starting_process(self, run) -> None:
        for timeout in (0, -1, nan, inf):
            with self.subTest(timeout=timeout):
                result = run_command(["tool"], timeout=timeout)
                self.assertEqual(result.status, CheckStatus.FAILED)
        run.assert_not_called()
