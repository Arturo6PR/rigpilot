import unittest
from unittest.mock import patch

from rigpilot.collectors import (
    _powershell_executable,
    collect_snapshot,
    parse_git_version,
    parse_json_object,
    parse_json_objects,
    parse_nvidia_csv,
    parse_storage,
)
from rigpilot.models import CheckStatus
from rigpilot.runner import CommandResult


class ParserTests(unittest.TestCase):
    def test_json_object(self) -> None:
        self.assertEqual(parse_json_object('{"Caption":"Windows 11"}')["Caption"], "Windows 11")

    def test_json_object_rejects_array(self) -> None:
        with self.assertRaises(TypeError):
            parse_json_object("[]")

    def test_storage_normalizes_single_object(self) -> None:
        self.assertEqual(parse_storage('{"DeviceID":"C:"}'), [{"DeviceID": "C:"}])

    def test_json_objects_supports_multiple_cpus(self) -> None:
        output = '[{"Name":"CPU 1"},{"Name":"CPU 2"}]'
        self.assertEqual(parse_json_objects(output), [{"Name": "CPU 1"}, {"Name": "CPU 2"}])

    def test_storage_rejects_scalar(self) -> None:
        with self.assertRaises(ValueError):
            parse_storage("42")

    def test_git_version(self) -> None:
        self.assertEqual(
            parse_git_version("git version 2.51.0.windows.1"), {"version": "2.51.0.windows.1"}
        )

    def test_git_version_rejects_malformed_output(self) -> None:
        with self.assertRaises(ValueError):
            parse_git_version("unknown")

    def test_nvidia_csv(self) -> None:
        parsed = parse_nvidia_csv("GeForce RTX 4090, 590.00, 24564")
        self.assertEqual(parsed[0]["memory_total_mib"], 24564)

    def test_nvidia_csv_supports_empty_and_multiple_results(self) -> None:
        self.assertEqual(parse_nvidia_csv(""), [])
        parsed = parse_nvidia_csv("GPU 1, 590.00, 1000\nGPU 2, 590.00, 2000")
        self.assertEqual([gpu["name"] for gpu in parsed], ["GPU 1", "GPU 2"])

    def test_nvidia_csv_rejects_malformed_output(self) -> None:
        with self.assertRaises(ValueError):
            parse_nvidia_csv("GPU, driver")


class SnapshotTests(unittest.TestCase):
    @patch("rigpilot.collectors._powershell_executable", return_value="powershell.exe")
    def test_collects_every_check(self, _powershell) -> None:
        commands: list[tuple[list[str], float]] = []
        outputs = iter(
            [
                '{"Caption":"Windows 11"}',
                '{"Name":"CPU"}',
                '{"TotalVisibleMemorySize":1024,"FreePhysicalMemory":512}',
                '[{"DeviceID":"C:","Size":100,"FreeSpace":50}]',
                "git version 2.51.0",
                "GPU, 590.00, 24564",
            ]
        )

        def runner(command: list[str], timeout: float) -> CommandResult:
            commands.append((command, timeout))
            return CommandResult(CheckStatus.SUCCESS, stdout=next(outputs))

        snapshot = collect_snapshot(runner=runner, timeout=1)

        self.assertTrue(all(item["status"] == "success" for item in snapshot.to_dict().values()))
        self.assertEqual(snapshot.cpu.data, [{"Name": "CPU"}])
        self.assertEqual(snapshot.nvidia_gpu.data[0]["name"], "GPU")
        self.assertEqual(len(commands), 6)
        self.assertTrue(all(timeout == 1 for _command, timeout in commands))
        for command, _timeout in commands[:4]:
            self.assertEqual(
                command[:4], ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
            )
            expression = command[4]
            self.assertIn("Get-CimInstance", expression)
            self.assertNotRegex(
                expression,
                r"\b(Set|Remove|Restart|Stop|Start|Enable|Disable|Update|Install)-",
            )
        self.assertEqual(commands[4][0], ["git", "--version"])
        self.assertEqual(
            commands[5][0],
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ],
        )

    @patch("rigpilot.collectors._powershell_executable", return_value="powershell.exe")
    def test_malformed_output_degrades_to_failed(self, _powershell) -> None:
        def runner(_command: list[str], _timeout: float) -> CommandResult:
            return CommandResult(CheckStatus.SUCCESS, stdout="not valid output")

        snapshot = collect_snapshot(runner=runner)

        self.assertEqual(snapshot.operating_system.status, CheckStatus.FAILED)
        self.assertEqual(snapshot.git.status, CheckStatus.FAILED)
        self.assertEqual(snapshot.nvidia_gpu.status, CheckStatus.FAILED)

    @patch("rigpilot.collectors._powershell_executable", return_value=None)
    def test_absent_powershell_is_unavailable(self, _powershell) -> None:
        def runner(_command: list[str], _timeout: float) -> CommandResult:
            return CommandResult(CheckStatus.UNAVAILABLE, message="not found")

        snapshot = collect_snapshot(runner=runner)

        self.assertEqual(snapshot.operating_system.status, CheckStatus.UNAVAILABLE)
        self.assertEqual(snapshot.nvidia_gpu.status, CheckStatus.UNAVAILABLE)

    @patch("rigpilot.collectors.shutil.which", side_effect=[None, "C:\\Tools\\pwsh.exe"])
    def test_powershell_discovery_falls_back_to_pwsh(self, which) -> None:
        self.assertEqual(_powershell_executable(), "C:\\Tools\\pwsh.exe")
        self.assertEqual(which.call_args_list[0].args, ("powershell.exe",))
        self.assertEqual(which.call_args_list[1].args, ("pwsh",))
