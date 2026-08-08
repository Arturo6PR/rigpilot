"""Read-only collectors and parsers for the RigPilot snapshot."""

from __future__ import annotations

import csv
import io
import json
import platform
import re
import shutil
import sys
from collections.abc import Callable
from typing import Any

from rigpilot.models import CheckResult, CheckStatus, Snapshot
from rigpilot.runner import CommandResult, run_command

Runner = Callable[[list[str], float], CommandResult]


def parse_json_object(output: str) -> dict[str, Any]:
    value = json.loads(output)
    if not isinstance(value, dict):
        raise TypeError("expected a JSON object")
    return value


def parse_json_objects(output: str) -> list[dict[str, Any]]:
    """Normalize a JSON object or array of objects to a list."""

    value = json.loads(output)
    items = value if isinstance(value, list) else [value]
    if not all(isinstance(item, dict) for item in items):
        raise ValueError("expected a JSON object or array of objects")
    return items


def parse_storage(output: str) -> list[dict[str, Any]]:
    return parse_json_objects(output)


def parse_git_version(output: str) -> dict[str, str]:
    match = re.fullmatch(r"git version (\S+)", output.strip())
    if not match:
        raise ValueError("unexpected git version output")
    return {"version": match.group(1)}


def parse_nvidia_csv(output: str) -> list[dict[str, Any]]:
    if not output.strip():
        return []
    rows = csv.reader(io.StringIO(output))
    gpus = []
    for row in rows:
        if len(row) != 3:
            raise ValueError("expected three NVIDIA fields")
        name, driver, memory = (part.strip() for part in row)
        try:
            memory_mib = int(memory)
        except ValueError as exc:
            raise ValueError("invalid NVIDIA memory value") from exc
        gpus.append({"name": name, "driver_version": driver, "memory_total_mib": memory_mib})
    return gpus


def _powershell_executable() -> str | None:
    return shutil.which("powershell.exe") or shutil.which("pwsh")


def _collect_command(
    command: list[str], parser: Callable[[str], Any], runner: Runner, timeout: float
) -> CheckResult:
    result = runner(command, timeout)
    if result.status is CheckStatus.UNAVAILABLE:
        return CheckResult.unavailable(result.message or "Command unavailable")
    if result.status is CheckStatus.FAILED:
        return CheckResult.failed(result.message or "Command failed")
    try:
        return CheckResult.success(parser(result.stdout))
    except (csv.Error, TypeError, ValueError) as exc:
        return CheckResult.failed(f"Could not parse command output: {exc}")


def _collect_cim(
    class_name: str,
    properties: list[str],
    parser: Callable[[str], Any],
    runner: Runner,
    timeout: float,
    filter_expression: str | None = None,
) -> CheckResult:
    powershell = _powershell_executable()
    if powershell is None:
        return CheckResult.unavailable("PowerShell is not available")
    filter_part = f" -Filter '{filter_expression}'" if filter_expression else ""
    expression = (
        f"Get-CimInstance -ClassName {class_name}{filter_part} | "
        f"Select-Object {','.join(properties)} | ConvertTo-Json -Compress"
    )
    return _collect_command(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", expression],
        parser,
        runner,
        timeout,
    )


def collect_snapshot(runner: Runner = run_command, timeout: float = 5.0) -> Snapshot:
    """Collect a read-only snapshot, preserving the outcome of every check."""

    operating_system = _collect_cim(
        "Win32_OperatingSystem",
        ["Caption", "Version", "BuildNumber", "OSArchitecture"],
        parse_json_object,
        runner,
        timeout,
    )
    cpu = _collect_cim(
        "Win32_Processor",
        ["Name", "NumberOfCores", "NumberOfLogicalProcessors"],
        parse_json_objects,
        runner,
        timeout,
    )
    memory = _collect_cim(
        "Win32_OperatingSystem",
        ["TotalVisibleMemorySize", "FreePhysicalMemory"],
        parse_json_object,
        runner,
        timeout,
    )
    storage = _collect_cim(
        "Win32_LogicalDisk",
        ["DeviceID", "VolumeName", "Size", "FreeSpace"],
        parse_storage,
        runner,
        timeout,
        filter_expression="DriveType=3",
    )
    python_result = CheckResult.success(
        {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        }
    )
    git_result = _collect_command(["git", "--version"], parse_git_version, runner, timeout)
    nvidia_result = _collect_command(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        ],
        parse_nvidia_csv,
        runner,
        timeout,
    )
    return Snapshot(
        operating_system=operating_system,
        cpu=cpu,
        memory=memory,
        storage=storage,
        python=python_result,
        git=git_result,
        nvidia_gpu=nvidia_result,
    )
