import unittest
from unittest.mock import patch

from rigpilot.collectors import (
    _powershell_executable,
    collect_snapshot,
    normalize_bios_date,
    parse_bios,
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

    def test_bios_normalizes_legacy_powershell_date(self) -> None:
        output = '{"Manufacturer":"Maker","ReleaseDate":"/Date(1782691200000)/"}'
        self.assertEqual(parse_bios(output)["ReleaseDate"], "2026-06-29")

    def test_bios_normalizes_iso_date_times(self) -> None:
        cases = {
            "2026-06-29T04:30:00Z": "2026-06-29",
            "2026-06-29T23:30:00-04:00": "2026-06-29",
            "2026-06-29T04:30:00+00:00": "2026-06-29",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(normalize_bios_date(value), expected)

    def test_bios_preserves_date_only_and_null_values(self) -> None:
        self.assertEqual(normalize_bios_date("2026-06-29"), "2026-06-29")
        self.assertIsNone(normalize_bios_date(None))
        self.assertIsNone(normalize_bios_date(""))

    def test_bios_rejects_malformed_nonempty_dates(self) -> None:
        for value in ("not-a-date", "2026-13-40", "2026-06-29T04:30:00"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_bios_date(value)

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
        parsed = parse_nvidia_csv("GeForce RTX 4090, 590.00, 24564, 12, 45")
        self.assertEqual(parsed[0]["memory_total_mib"], 24564)
        self.assertEqual(parsed[0]["temperature_celsius"], 45)

    def test_nvidia_csv_supports_empty_and_multiple_results(self) -> None:
        self.assertEqual(parse_nvidia_csv(""), [])
        parsed = parse_nvidia_csv(
            "GPU 1, 590.00, 1000, 10, 40\nGPU 2, 590.00, 2000, [N/A], [Not Supported]"
        )
        self.assertEqual([gpu["name"] for gpu in parsed], ["GPU 1", "GPU 2"])
        self.assertIsNone(parsed[1]["utilization_gpu_percent"])

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
                '{"Manufacturer":"Maker","Model":"Model"}',
                '{"Manufacturer":"BIOS Maker","SMBIOSBIOSVersion":"1.0"}',
                '[{"Manufacturer":"RAM Maker","PartNumber":"RAM","Capacity":1024}]',
                '[{"Model":"Disk","Size":100,"Status":"OK"}]',
                '{"UptimeSeconds":3600}',
                "git version 2.51.0",
                "GPU, 590.00, 24564, 10, 45",
            ]
        )

        def runner(command: list[str], timeout: float) -> CommandResult:
            commands.append((command, timeout))
            return CommandResult(CheckStatus.SUCCESS, stdout=next(outputs))

        snapshot = collect_snapshot(runner=runner, timeout=1)

        self.assertTrue(
            all(item["status"] == "success" for item in snapshot.to_dict()["checks"].values())
        )
        self.assertEqual(snapshot.cpu.data, [{"Name": "CPU"}])
        self.assertEqual(snapshot.nvidia_gpu.data[0]["name"], "GPU")
        self.assertEqual(len(commands), 11)
        self.assertTrue(all(timeout == 1 for _command, timeout in commands))
        for command, _timeout in commands[:9]:
            self.assertEqual(
                command[:4], ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
            )
            expression = command[4]
            self.assertIn("Get-CimInstance", expression)
            self.assertNotRegex(
                expression,
                r"\b(Set|Remove|Restart|Stop|Start|Enable|Disable|Update|Install)-",
            )
        self.assertEqual(commands[9][0], ["git", "--version"])
        self.assertEqual(
            commands[10][0],
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
        )
        payload = snapshot.to_dict()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertTrue(payload["collected_at_utc"].endswith("+00:00"))
        self.assertIn("system", payload["checks"])

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
