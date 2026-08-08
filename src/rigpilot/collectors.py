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
from datetime import UTC, date, datetime
from typing import Any

from rigpilot.models import CheckResult, CheckStatus, Snapshot
from rigpilot.runner import CommandResult, run_command

Runner = Callable[[list[str], float], CommandResult]
CHECK_NAMES = frozenset(
    {
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
)


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


def parse_bios(output: str) -> dict[str, Any]:
    data = parse_json_object(output)
    data["ReleaseDate"] = normalize_bios_date(data.get("ReleaseDate"))
    return data


def normalize_bios_date(value: Any) -> str | None:
    """Normalize CIM/PowerShell BIOS dates to an ISO calendar date."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("BIOS release date must be a string or null")
    value = value.strip()
    if not value:
        return None

    legacy_match = re.fullmatch(r"/Date\((-?\d+)(?:[+-]\d{4})?\)/", value)
    if legacy_match:
        try:
            timestamp = int(legacy_match.group(1)) / 1000
            return datetime.fromtimestamp(timestamp, UTC).date().isoformat()
        except (OSError, OverflowError, ValueError) as exc:
            raise ValueError("invalid legacy BIOS release date") from exc

    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value).isoformat()
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("ISO BIOS date-time must include an offset or Z")
        return parsed.date().isoformat()
    except ValueError as exc:
        raise ValueError("invalid BIOS release date") from exc


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
        if len(row) != 5:
            raise ValueError("expected five NVIDIA fields")
        name, driver, memory, utilization, temperature = (part.strip() for part in row)
        try:
            memory_mib = int(memory)
        except ValueError as exc:
            raise ValueError("invalid NVIDIA memory value") from exc
        gpus.append(
            {
                "name": name,
                "driver_version": driver,
                "memory_total_mib": memory_mib,
                "utilization_gpu_percent": _parse_optional_integer(utilization),
                "temperature_celsius": _parse_optional_integer(temperature),
            }
        )
    return gpus


def _parse_optional_integer(value: str) -> int | None:
    if value.lower() in {"n/a", "[n/a]", "not supported", "[not supported]"}:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"invalid numeric value: {value}") from exc


def _powershell_executable() -> str | None:
    return shutil.which("powershell.exe") or shutil.which("pwsh")


def _collect_command(
    command: list[str], parser: Callable[[str], Any], runner: Runner, timeout: float
) -> CheckResult:
    result = runner(command, timeout)
    if result.status is CheckStatus.UNAVAILABLE:
        return CheckResult(
            CheckStatus.UNAVAILABLE,
            message=result.message or "Command unavailable",
            duration_ms=result.duration_ms,
        )
    if result.status is CheckStatus.FAILED:
        return CheckResult(
            CheckStatus.FAILED,
            message=result.message or "Command failed",
            duration_ms=result.duration_ms,
        )
    try:
        return CheckResult(
            CheckStatus.SUCCESS, data=parser(result.stdout), duration_ms=result.duration_ms
        )
    except (csv.Error, TypeError, ValueError) as exc:
        return CheckResult(
            CheckStatus.FAILED,
            message=f"Could not parse command output: {exc}",
            duration_ms=result.duration_ms,
        )


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


def collect_snapshot(
    runner: Runner = run_command,
    timeout: float = 5.0,
    only: set[str] | None = None,
    skip: set[str] | None = None,
) -> Snapshot:
    """Collect a read-only snapshot, preserving the outcome of every check."""

    skip = skip or set()
    requested = CHECK_NAMES if only is None else frozenset(only)
    unknown = (requested | skip) - CHECK_NAMES
    if unknown:
        raise ValueError(f"Unknown checks: {', '.join(sorted(unknown))}")
    enabled = requested - skip

    def omitted(name: str) -> CheckResult:
        return CheckResult.unavailable(f"Skipped by selection: {name}")

    operating_system = (
        _collect_cim(
            "Win32_OperatingSystem",
            ["Caption", "Version", "BuildNumber", "OSArchitecture"],
            parse_json_object,
            runner,
            timeout,
        )
        if "operating_system" in enabled
        else omitted("operating_system")
    )
    cpu = (
        _collect_cim(
            "Win32_Processor",
            ["Name", "NumberOfCores", "NumberOfLogicalProcessors"],
            parse_json_objects,
            runner,
            timeout,
        )
        if "cpu" in enabled
        else omitted("cpu")
    )
    memory = (
        _collect_cim(
            "Win32_OperatingSystem",
            ["TotalVisibleMemorySize", "FreePhysicalMemory"],
            parse_json_object,
            runner,
            timeout,
        )
        if "memory" in enabled
        else omitted("memory")
    )
    storage = (
        _collect_cim(
            "Win32_LogicalDisk",
            ["DeviceID", "VolumeName", "Size", "FreeSpace"],
            parse_storage,
            runner,
            timeout,
            filter_expression="DriveType=3",
        )
        if "storage" in enabled
        else omitted("storage")
    )
    system = (
        _collect_cim(
            "Win32_ComputerSystem",
            ["Manufacturer", "Model"],
            parse_json_object,
            runner,
            timeout,
        )
        if "system" in enabled
        else omitted("system")
    )
    bios = (
        _collect_cim(
            "Win32_BIOS",
            ["Manufacturer", "SMBIOSBIOSVersion", "ReleaseDate"],
            parse_bios,
            runner,
            timeout,
        )
        if "bios" in enabled
        else omitted("bios")
    )
    memory_modules = (
        _collect_cim(
            "Win32_PhysicalMemory",
            ["Manufacturer", "PartNumber", "Capacity", "Speed", "ConfiguredClockSpeed"],
            parse_json_objects,
            runner,
            timeout,
        )
        if "memory_modules" in enabled
        else omitted("memory_modules")
    )
    physical_disks = (
        _collect_cim(
            "Win32_DiskDrive",
            ["Model", "InterfaceType", "MediaType", "Size", "Status"],
            parse_json_objects,
            runner,
            timeout,
        )
        if "physical_disks" in enabled
        else omitted("physical_disks")
    )
    powershell = _powershell_executable() if "uptime" in enabled else None
    if "uptime" not in enabled:
        uptime = omitted("uptime")
    elif powershell is None:
        uptime = CheckResult.unavailable("PowerShell is not available")
    else:
        uptime_expression = (
            "Get-CimInstance -ClassName Win32_OperatingSystem | "
            "Select-Object @{Name='UptimeSeconds';Expression={"
            "[int64]((Get-Date)-$_.LastBootUpTime).TotalSeconds}} | ConvertTo-Json -Compress"
        )
        uptime = _collect_command(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", uptime_expression],
            parse_json_object,
            runner,
            timeout,
        )
    python_result = (
        CheckResult.success(
            {
                "version": platform.python_version(),
                "implementation": platform.python_implementation(),
                "executable": sys.executable,
            }
        )
        if "python" in enabled
        else omitted("python")
    )
    git_result = (
        _collect_command(["git", "--version"], parse_git_version, runner, timeout)
        if "git" in enabled
        else omitted("git")
    )
    nvidia_result = (
        _collect_command(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            parse_nvidia_csv,
            runner,
            timeout,
        )
        if "nvidia_gpu" in enabled
        else omitted("nvidia_gpu")
    )
    return Snapshot(
        operating_system=operating_system,
        cpu=cpu,
        memory=memory,
        storage=storage,
        python=python_result,
        git=git_result,
        nvidia_gpu=nvidia_result,
        system=system,
        bios=bios,
        memory_modules=memory_modules,
        physical_disks=physical_disks,
        uptime=uptime,
        schema_version="1.0",
        collected_at_utc=datetime.now(UTC).isoformat(),
        hostname=platform.node(),
    )
