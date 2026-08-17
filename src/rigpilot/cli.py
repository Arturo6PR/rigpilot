"""Command-line interface for RigPilot."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from math import isfinite
from pathlib import Path
from typing import Any

from rigpilot.assessment import assess_snapshot, render_assessment_human
from rigpilot.collectors import CHECK_NAMES, collect_snapshot
from rigpilot.diffing import compare_snapshots, load_snapshot, render_diff_human, validate_snapshot
from rigpilot.guidance import build_guidance, render_guidance_human
from rigpilot.models import CheckResult, CheckStatus, Snapshot
from rigpilot.policy import (
    POLICY_CHECKS,
    RULE_GROUPS_ORDER,
    Policy,
    build_policy_report,
    render_policy_human,
)
from rigpilot.policy_config import load_policy_config


class _OutputError(Exception):
    """A concise user-facing output destination error."""


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


def render_human(snapshot: Snapshot, *, redact: bool = False, include_hostname: bool = True) -> str:
    payload = snapshot.to_dict(redact=redact, include_hostname=include_hostname)
    lines = [
        "RigPilot system snapshot",
        f"Schema: {snapshot.schema_version}",
        f"Collected: {snapshot.collected_at_utc or 'Unknown'}",
        f"Host: {payload['hostname'] if payload['hostname'] is not None else 'Not included'}",
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
            lines.extend(_format_success(name, payload["checks"][name]["data"]))
        else:
            lines.append(f"  {result.message or 'No details'}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect a read-only Windows system snapshot.")
    parser.add_argument("--json", action="store_true", help="emit structured JSON output")
    parser.add_argument(
        "--redact",
        action="store_true",
        help="redact hostname, volume labels, and the Python executable path",
    )
    parser.add_argument(
        "--no-hostname", action="store_true", help="omit the hostname value from output"
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--only",
        type=_parse_check_names,
        metavar="CHECKS",
        help="run only comma-separated checks",
    )
    selection.add_argument(
        "--skip",
        type=_parse_check_names,
        metavar="CHECKS",
        help="skip comma-separated checks",
    )
    parser.add_argument(
        "--timeout", type=float, default=5.0, help="per-command timeout in seconds (default: 5)"
    )
    return parser


def _parse_check_names(value: str) -> set[str]:
    names = {part.strip() for part in value.split(",") if part.strip()}
    if not names:
        raise argparse.ArgumentTypeError("at least one check name is required")
    unknown = names - CHECK_NAMES
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown checks: {', '.join(sorted(unknown))}")
    return names


def _parse_policy_selector(value: str, *, allowed: tuple[str, ...], label: str) -> tuple[str, ...]:
    values = tuple(part.strip() for part in value.split(",") if part.strip())
    if not values:
        raise argparse.ArgumentTypeError(f"at least one {label} is required")
    unknown = set(values) - set(allowed)
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown {label}: {', '.join(sorted(unknown))}")
    return values


def _parse_policy_groups(value: str) -> tuple[str, ...]:
    return _parse_policy_selector(value, allowed=RULE_GROUPS_ORDER, label="policy group")


def _parse_policy_checks(value: str) -> tuple[str, ...]:
    return _parse_policy_selector(value, allowed=POLICY_CHECKS, label="policy check")


def build_diff_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rigpilot diff", description="Compare two JSON snapshots."
    )
    parser.add_argument("before", type=Path, help="earlier snapshot JSON file")
    parser.add_argument("after", type=Path, help="later snapshot JSON file")
    parser.add_argument("--json", action="store_true", help="emit structured JSON output")
    return parser


def _run_diff(argv: Sequence[str]) -> int:
    args = build_diff_parser().parse_args(argv)
    try:
        diff = compare_snapshots(load_snapshot(args.before), load_snapshot(args.after))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"rigpilot diff: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(diff, indent=2, ensure_ascii=False))
    else:
        print(render_diff_human(diff))
    return 0


def build_assess_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rigpilot assess", description="Assess a saved or live system snapshot."
    )
    parser.add_argument("current", nargs="?", type=Path, help="saved snapshot JSON file to assess")
    parser.add_argument(
        "--live", action="store_true", help="collect and assess one read-only snapshot in memory"
    )
    parser.add_argument("--baseline", type=Path, help="earlier snapshot for hardware comparison")
    parser.add_argument("--json", action="store_true", help="emit structured JSON output")
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=("text", "json"),
        help="assessment output format (default: text)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        metavar="PATH",
        help="write assessment output to a new file instead of stdout",
    )
    parser.add_argument(
        "--guidance", action="store_true", help="include deterministic safe next-step guidance"
    )
    parser.add_argument(
        "--policy", action="store_true", help="apply a deterministic finding view and decision"
    )
    parser.add_argument(
        "--policy-file",
        type=Path,
        metavar="PATH",
        help="load a strict reusable policy configuration file",
    )
    parser.add_argument(
        "--policy-min-severity",
        choices=("critical", "warning", "info"),
        help="display findings at or above this severity",
    )
    parser.add_argument(
        "--policy-groups",
        type=_parse_policy_groups,
        metavar="GROUPS",
        help="display comma-separated probes, storage, hardware, or bios groups",
    )
    parser.add_argument(
        "--policy-checks",
        type=_parse_policy_checks,
        metavar="CHECKS",
        help="display findings from comma-separated checks",
    )
    parser.add_argument(
        "--policy-fail-on",
        choices=("critical", "warning", "info"),
        help="return 3 when a displayed finding reaches this severity",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--only",
        type=_parse_check_names,
        metavar="CHECKS",
        help="in live mode, run only comma-separated checks",
    )
    selection.add_argument(
        "--skip",
        type=_parse_check_names,
        metavar="CHECKS",
        help="in live mode, skip comma-separated checks",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        help="in live mode, per-command timeout in seconds (default: 5)",
    )
    return parser


def _collect_assessment_snapshot(
    *, timeout: float, only: set[str] | None, skip: set[str] | None
) -> dict[str, Any]:
    snapshot = collect_snapshot(timeout=timeout, only=only, skip=skip)
    payload = snapshot.to_dict(include_hostname=False)
    return validate_snapshot(payload, "live snapshot")


def _policy_from_args(args: argparse.Namespace) -> Policy:
    return Policy(
        minimum_severity=args.policy_min_severity,
        rule_groups=args.policy_groups,
        checks=args.policy_checks,
        fail_on=args.policy_fail_on,
    )


def _render_assessment_output(
    assessment: dict[str, Any],
    *,
    policy: Policy | None,
    include_guidance: bool,
    as_json: bool,
) -> tuple[str, int]:
    if policy is not None:
        source = build_guidance(assessment) if include_guidance else assessment
        report = build_policy_report(source, policy)
        rendered = (
            json.dumps(report, indent=2, ensure_ascii=False)
            if as_json
            else render_policy_human(report)
        )
        return rendered, report["decision"]["exit_code"]
    if include_guidance:
        report = build_guidance(assessment)
        rendered = (
            json.dumps(report, indent=2, ensure_ascii=False)
            if as_json
            else f"{render_assessment_human(assessment)}\n\n{render_guidance_human(report)}"
        )
        return rendered, 0
    if as_json:
        return json.dumps(assessment, indent=2, ensure_ascii=False), 0
    return render_assessment_human(assessment), 0


def _validate_output_path(path: Path) -> None:
    try:
        if path.exists():
            raise _OutputError(f"{path}: output path already exists")
        if not path.parent.exists() or not path.parent.is_dir():
            raise _OutputError(f"{path}: output directory does not exist")
    except OSError as exc:
        raise _OutputError(f"{path}: invalid output path") from exc


def _write_output_file(path: Path, rendered: str) -> None:
    created = False
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            created = True
            stream.write(rendered)
            stream.write("\n")
    except OSError as exc:
        if created:
            try:
                path.unlink()
            except OSError:
                pass
        raise _OutputError(f"{path}: could not write output") from exc


def _deliver_assessment_output(rendered: str, output: Path | None) -> None:
    if output is None:
        print(rendered)
    else:
        _write_output_file(output, rendered)


def _run_assess(argv: Sequence[str]) -> int:
    parser = build_assess_parser()
    args = parser.parse_args(argv)
    if args.live and args.current is not None:
        parser.error("a current snapshot path cannot be used with --live")
    if not args.live and args.current is None:
        parser.error("a current snapshot path is required unless --live is used")
    if not args.live and any(value is not None for value in (args.timeout, args.only, args.skip)):
        parser.error("--timeout, --only, and --skip require --live")
    if args.json and args.output_format == "text":
        parser.error("--json cannot be used with --format text")
    as_json = args.json or args.output_format == "json"
    policy_options = (
        args.policy_min_severity,
        args.policy_groups,
        args.policy_checks,
        args.policy_fail_on,
    )
    if args.policy_file is not None and (
        args.policy or any(value is not None for value in policy_options)
    ):
        parser.error("--policy-file cannot be combined with --policy or --policy-* options")
    if (
        args.policy_file is None
        and not args.policy
        and any(value is not None for value in policy_options)
    ):
        parser.error("--policy-* options require --policy")
    if args.output is not None:
        try:
            _validate_output_path(args.output)
        except _OutputError as exc:
            print(f"rigpilot assess: {exc}", file=sys.stderr)
            return 2
    try:
        if args.policy_file is not None:
            policy = load_policy_config(args.policy_file)
        else:
            policy = _policy_from_args(args) if args.policy else None
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if args.policy_file is None:
            parser.error(str(exc))
        print(f"rigpilot assess: {exc}", file=sys.stderr)
        return 2
    except Exception:  # noqa: BLE001 - Policy failures must not expose private details.
        if args.live:
            print("rigpilot assess: live assessment failed", file=sys.stderr)
        else:
            print("rigpilot assess: policy failed", file=sys.stderr)
        return 1

    timeout = 5.0 if args.timeout is None else args.timeout
    if args.live and (not isfinite(timeout) or timeout <= 0):
        parser.error("--timeout must be finite and greater than zero")

    if args.live:
        try:
            baseline = load_snapshot(args.baseline) if args.baseline is not None else None
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            print(f"rigpilot assess: {exc}", file=sys.stderr)
            return 2
        try:
            current = _collect_assessment_snapshot(timeout=timeout, only=args.only, skip=args.skip)
            assessment = assess_snapshot(current, baseline)
            rendered, exit_code = _render_assessment_output(
                assessment,
                policy=policy,
                include_guidance=args.guidance,
                as_json=as_json,
            )
            _deliver_assessment_output(rendered, args.output)
        except _OutputError as exc:
            print(f"rigpilot assess: {exc}", file=sys.stderr)
            return 2
        except Exception:  # noqa: BLE001 - Prevent sensitive live failure details from leaking.
            print("rigpilot assess: live assessment failed", file=sys.stderr)
            return 1
        return exit_code
    else:
        try:
            current = load_snapshot(args.current)
            baseline = load_snapshot(args.baseline) if args.baseline is not None else None
            assessment = assess_snapshot(current, baseline)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            print(f"rigpilot assess: {exc}", file=sys.stderr)
            return 2

    try:
        rendered, exit_code = _render_assessment_output(
            assessment,
            policy=policy,
            include_guidance=args.guidance,
            as_json=as_json,
        )
        _deliver_assessment_output(rendered, args.output)
    except _OutputError as exc:
        print(f"rigpilot assess: {exc}", file=sys.stderr)
        return 2
    except Exception:  # noqa: BLE001 - Output failures must not expose private details.
        if policy is not None:
            print("rigpilot assess: policy failed", file=sys.stderr)
        elif args.guidance:
            print("rigpilot assess: guidance failed", file=sys.stderr)
        else:
            print("rigpilot assess: output failed", file=sys.stderr)
        return 1
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["diff"]:
        return _run_diff(arguments[1:])
    if arguments[:1] == ["assess"]:
        return _run_assess(arguments[1:])
    args = build_parser().parse_args(arguments)
    if not isfinite(args.timeout) or args.timeout <= 0:
        build_parser().error("--timeout must be finite and greater than zero")
    snapshot = collect_snapshot(timeout=args.timeout, only=args.only, skip=args.skip)
    if args.json:
        print(
            json.dumps(
                snapshot.to_dict(redact=args.redact, include_hostname=not args.no_hostname),
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(render_human(snapshot, redact=args.redact, include_hostname=not args.no_hostname))
    return 0
