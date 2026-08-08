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
    if name == "nvidia_gpu":
        lines = []
        for index, gpu in enumerate(data, start=1):
            label = f"GPU {index}" if len(data) > 1 else "Adapter"
            lines.append(f"  {label}: {gpu['name']}")
            lines.append(f"    Driver: {gpu['driver_version']}")
            lines.append(f"    Memory: {gpu['memory_total_mib']} MiB")
        return lines or ["  No NVIDIA GPUs reported"]
    if isinstance(data, dict):
        return _format_fields(data, {})
    return [f"  {data}"]


def render_human(snapshot: Snapshot) -> str:
    lines = ["RigPilot system snapshot"]
    labels = {
        "operating_system": "Operating system",
        "cpu": "CPU",
        "memory": "Memory",
        "storage": "Storage",
        "python": "Python",
        "git": "Git",
        "nvidia_gpu": "NVIDIA GPU",
    }
    for name, result in snapshot.__dict__.items():
        assert isinstance(result, CheckResult)
        lines.append(f"{labels[name]} [{result.status}]")
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
