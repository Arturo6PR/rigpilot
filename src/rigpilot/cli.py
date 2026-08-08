"""Command-line interface for RigPilot."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from math import isfinite
from typing import Any

from rigpilot.collectors import collect_snapshot
from rigpilot.models import CheckResult, CheckStatus, Snapshot


def _format_binary_size(byte_count: float) -> str:
    value = float(byte_count)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def _format_fields(data: dict[str, Any], labels: dict[str, str]) -> list[str]:
    return [f"  {labels.get(key, key)}: {value}" for key, value in data.items()]


def _format_success(name: str, data: Any) -> list[str]:
    if name == "operating_system":
        return _format_fields(
            data,
            {
                "Caption": "Name",
                "Version": "Version",
                "BuildNumber": "Build",
                "OSArchitecture": "Architecture",
            },
        )
    if name == "bios":
        return _format_fields(
            data,
            {
                "Manufacturer": "Manufacturer",
                "SMBIOSBIOSVersion": "Version",
                "ReleaseDate": "Release date",
            },
        )
    if name == "cpu":
        lines = []
        for index, cpu in enumerate(data, start=1):
            label = f"CPU {index}" if len(data) > 1 else "Processor"
            lines.append(f"  {label}: {str(cpu.get('Name', 'Unknown')).strip()}")
            lines.append(f"    Cores: {cpu.get('NumberOfCores', 'Unknown')}")
            lines.append(
                f"    Logical processors: {cpu.get('NumberOfLogicalProcessors', 'Unknown')}"
            )
        return lines or ["  No processors reported"]
    if name == "memory":
        total_bytes = int(data["TotalVisibleMemorySize"]) * 1024
        free_bytes = int(data["FreePhysicalMemory"]) * 1024
        return [
            f"  Total: {_format_binary_size(total_bytes)}",
            f"  Available: {_format_binary_size(free_bytes)}",
        ]
    if name == "storage":
        lines = []
        for disk in data:
            volume = f" ({disk['VolumeName']})" if disk.get("VolumeName") else ""
            lines.append(f"  {disk.get('DeviceID', 'Unknown')}{volume}")
            lines.append(f"    Total: {_format_binary_size(int(disk['Size']))}")
            lines.append(f"    Free: {_format_binary_size(int(disk['FreeSpace']))}")
        return lines or ["  No fixed disks reported"]
    if name == "memory_modules":
        lines = []
        for index, module in enumerate(data, start=1):
            lines.append(f"  Module {index}: {str(module.get('PartNumber', 'Unknown')).strip()}")
            lines.append(f"    Manufacturer: {str(module.get('Manufacturer', 'Unknown')).strip()}")
            lines.append(f"    Capacity: {_format_binary_size(int(module['Capacity']))}")
            lines.append(
                f"    Speed: {module.get('ConfiguredClockSpeed') or module.get('Speed')} MT/s"
            )
        return lines or ["  No physical memory modules reported"]
    if name == "physical_disks":
        lines = []
        for index, disk in enumerate(data, start=1):
            lines.append(f"  Disk {index}: {str(disk.get('Model', 'Unknown')).strip()}")
            lines.append(f"    Interface: {disk.get('InterfaceType', 'Unknown')}")
            lines.append(f"    Capacity: {_format_binary_size(int(disk['Size']))}")
            lines.append(f"    Reported status: {disk.get('Status', 'Unknown')}")
        return lines or ["  No physical disks reported"]
    if name == "uptime":
        seconds = int(data["UptimeSeconds"])
        days, remainder = divmod(seconds, 86_400)
        hours, remainder = divmod(remainder, 3_600)
        minutes = remainder // 60
        return [f"  {days}d {hours}h {minutes}m"]
    if name == "nvidia_gpu":
        lines = []
        for index, gpu in enumerate(data, start=1):
            label = f"GPU {index}" if len(data) > 1 else "Adapter"
            lines.append(f"  {label}: {gpu['name']}")
            lines.append(f"    Driver: {gpu['driver_version']}")
            lines.append(f"    Memory: {gpu['memory_total_mib']} MiB")
            utilization = gpu.get("utilization_gpu_percent")
            temperature = gpu.get("temperature_celsius")
            lines.append(
                f"    Utilization: {utilization}%"
                if utilization is not None
                else "    Utilization: unavailable"
            )
            lines.append(
                f"    Temperature: {temperature} °C"
                if temperature is not None
                else "    Temperature: unavailable"
            )
        return lines or ["  No NVIDIA GPUs reported"]
    if isinstance(data, dict):
        return _format_fields(data, {})
    return [f"  {data}"]


def render_human(snapshot: Snapshot) -> str:
    lines = [
        "RigPilot system snapshot",
        f"Schema: {snapshot.schema_version}",
        f"Collected: {snapshot.collected_at_utc or 'Unknown'}",
        f"Host: {snapshot.hostname or 'Unknown'}",
    ]
    labels = {
        "operating_system": "Operating system",
        "cpu": "CPU",
        "memory": "Memory",
        "storage": "Storage",
        "python": "Python",
        "git": "Git",
        "nvidia_gpu": "NVIDIA GPU",
        "system": "System",
        "bios": "BIOS",
        "memory_modules": "Memory modules",
        "physical_disks": "Physical disks",
        "uptime": "Uptime",
    }
    for name, result in snapshot.checks().items():
        assert isinstance(result, CheckResult)
        lines.append(f"{labels[name]} [{result.status}] ({result.duration_ms:.1f} ms)")
        if result.status is CheckStatus.SUCCESS:
            lines.extend(_format_success(name, result.data))
        else:
            lines.append(f"  {result.message or 'No details'}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect a read-only Windows system snapshot.")
    parser.add_argument("--json", action="store_true", help="emit structured JSON output")
    parser.add_argument(
        "--timeout", type=float, default=5.0, help="per-command timeout in seconds (default: 5)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not isfinite(args.timeout) or args.timeout <= 0:
        build_parser().error("--timeout must be finite and greater than zero")
    snapshot = collect_snapshot(timeout=args.timeout)
    if args.json:
        print(json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(render_human(snapshot))
    return 0
