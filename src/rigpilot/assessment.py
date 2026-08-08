"""Deterministic, privacy-safe assessment of validated RigPilot snapshots."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from rigpilot.diffing import validate_snapshot

GIB = 1024**3
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def _finding(
    rule_id: str,
    severity: str,
    check: str,
    message: str,
    evidence: dict[str, Any],
    subject: str | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "check": check,
        "subject": subject,
        "message": message,
        "evidence": evidence,
    }


def _probe_findings(checks: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for name, result in checks.items():
        status = result["status"]
        if status == "failed":
            findings.append(
                _finding(
                    "probe.failed",
                    "warning",
                    name,
                    "Inventory probe failed; assessment coverage is incomplete.",
                    {"status": status},
                )
            )
        elif status == "unavailable":
            message = result["message"]
            if message.startswith("Skipped by selection:"):
                rule_id = "probe.skipped"
                severity = "info"
                text = "Inventory probe was intentionally skipped."
            elif name == "nvidia_gpu":
                rule_id = "probe.optional_unavailable"
                severity = "info"
                text = "Optional NVIDIA inventory is unavailable."
            else:
                rule_id = "probe.unavailable"
                severity = "warning"
                text = "Inventory probe is unavailable; assessment coverage is incomplete."
            findings.append(_finding(rule_id, severity, name, text, {"status": status}))
    return findings


def _storage_findings(storage: dict[str, Any]) -> list[dict[str, Any]]:
    if storage["status"] != "success":
        return []
    findings = []
    for volume in storage["data"]:
        total = int(volume["Size"])
        free = int(volume["FreeSpace"])
        if total == 0:
            continue
        evidence = {
            "free_bytes": free,
            "total_bytes": total,
            "free_percent": round(free * 100 / total, 1),
        }
        subject = volume["DeviceID"]
        if free * 100 < total * 5 and free < 10 * GIB:
            findings.append(
                _finding(
                    "storage.critically_low_capacity",
                    "critical",
                    "storage",
                    "Fixed volume has critically low free capacity.",
                    evidence,
                    subject,
                )
            )
        elif free * 100 < total * 10 and free < 20 * GIB:
            findings.append(
                _finding(
                    "storage.low_capacity",
                    "warning",
                    "storage",
                    "Fixed volume has limited free capacity.",
                    evidence,
                    subject,
                )
            )
    return findings


def _normalized_multiset(items: list[dict[str, Any]], fields: tuple[str, ...]) -> Counter:
    return Counter(
        tuple(_normalize_identity_value(item.get(field)) for field in fields) for item in items
    )


def _normalize_identity_value(value: Any) -> Any:
    return value.strip().casefold() if isinstance(value, str) else value


def _system_identity(data: dict[str, Any]) -> Counter:
    return Counter(
        [
            (
                _normalize_identity_value(data.get("Manufacturer")),
                _normalize_identity_value(data.get("Model")),
            )
        ]
    )


HARDWARE_RULES: tuple[
    tuple[str, str, tuple[str, ...] | None, Callable[[dict[str, Any]], Counter] | None], ...
] = (
    ("system", "hardware.system_changed", None, _system_identity),
    (
        "cpu",
        "hardware.cpu_changed",
        ("Name", "NumberOfCores", "NumberOfLogicalProcessors"),
        None,
    ),
    (
        "memory_modules",
        "hardware.memory_changed",
        ("Manufacturer", "PartNumber", "Capacity", "Speed", "ConfiguredClockSpeed"),
        None,
    ),
    (
        "physical_disks",
        "hardware.physical_disks_changed",
        ("Model", "InterfaceType", "MediaType", "Size"),
        None,
    ),
    ("nvidia_gpu", "hardware.nvidia_gpu_changed", ("name", "memory_total_mib"), None),
)


def _hardware_findings(
    current_checks: dict[str, Any], baseline_checks: dict[str, Any]
) -> list[dict[str, Any]]:
    findings = []
    for check, rule_id, fields, normalizer in HARDWARE_RULES:
        current = current_checks[check]
        baseline = baseline_checks[check]
        if current["status"] != "success" or baseline["status"] != "success":
            continue
        current_data = current["data"]
        baseline_data = baseline["data"]
        if normalizer is not None:
            current_identity = normalizer(current_data)
            baseline_identity = normalizer(baseline_data)
            current_count = baseline_count = 1
        else:
            current_identity = _normalized_multiset(current_data, fields or ())
            baseline_identity = _normalized_multiset(baseline_data, fields or ())
            current_count = len(current_data)
            baseline_count = len(baseline_data)
        if current_identity != baseline_identity:
            findings.append(
                _finding(
                    rule_id,
                    "warning",
                    check,
                    "Hardware configuration changed from the baseline snapshot.",
                    {"baseline_count": baseline_count, "current_count": current_count},
                )
            )
    return findings


def _complete_years(earlier: date, later: date) -> int:
    years = later.year - earlier.year
    return years - (later < _calendar_anniversary(earlier, later.year))


def _calendar_anniversary(original: date, year: int) -> date:
    try:
        return original.replace(year=year)
    except ValueError:
        # February 29 anniversaries fall on February 28 in non-leap years.
        return date(year, 2, 28)


def _rfc3339_date(value: str) -> date:
    normalized = f"{value[:-1]}Z" if value.endswith("z") else value
    parsed = datetime.fromisoformat(normalized)
    return parsed.astimezone(UTC).date()


def _bios_findings(bios: dict[str, Any], collected_at: str) -> list[dict[str, Any]]:
    if bios["status"] != "success":
        return []
    release_value = bios["data"]["ReleaseDate"]
    if release_value is None:
        return [
            _finding(
                "bios.release_date_missing",
                "info",
                "bios",
                "BIOS release date was not reported.",
                {},
            )
        ]
    release_date = date.fromisoformat(release_value)
    reference_date = _rfc3339_date(collected_at)
    if release_date > reference_date:
        return [
            _finding(
                "bios.release_date_future",
                "warning",
                "bios",
                "BIOS release date is later than the snapshot collection date.",
                {"release_date": release_value},
            )
        ]
    age_years = _complete_years(release_date, reference_date)
    if age_years >= 5:
        return [
            _finding(
                "bios.release_date_stale",
                "warning",
                "bios",
                "BIOS release date is at least five years old; review manufacturer guidance.",
                {"release_date": release_value, "age_years": age_years},
            )
        ]
    return []


def assess_snapshot(
    current: dict[str, Any], baseline: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Assess validated snapshot data without collecting telemetry or mutating input."""

    current = validate_snapshot(current, "current snapshot")
    if baseline is not None:
        baseline = validate_snapshot(baseline, "baseline snapshot")
        if current["schema_version"] != baseline["schema_version"]:
            raise ValueError("Snapshots use different schema versions")

    findings = _probe_findings(current["checks"])
    findings.extend(_storage_findings(current["checks"]["storage"]))
    findings.extend(_bios_findings(current["checks"]["bios"], current["collected_at_utc"]))
    if baseline is not None:
        findings.extend(_hardware_findings(current["checks"], baseline["checks"]))
    findings.sort(
        key=lambda finding: (
            SEVERITY_ORDER[finding["severity"]],
            finding["rule_id"],
            finding["check"],
            finding["subject"] or "",
        )
    )
    counts = {
        severity: sum(finding["severity"] == severity for finding in findings)
        for severity in ("info", "warning", "critical")
    }
    highest = next(
        (severity for severity in ("critical", "warning", "info") if counts[severity]), None
    )
    result = {
        "assessment_schema_version": "1.0",
        "snapshot_schema_version": current["schema_version"],
        "subject_collected_at_utc": current["collected_at_utc"],
        "baseline_collected_at_utc": baseline["collected_at_utc"] if baseline else None,
        "summary": {"highest_severity": highest, "counts": counts},
        "findings": findings,
    }
    validate_assessment(result)
    return result


def render_assessment_human(assessment: dict[str, Any]) -> str:
    lines = [
        "RigPilot assessment",
        f"Snapshot: {assessment['subject_collected_at_utc']}",
    ]
    if assessment["baseline_collected_at_utc"] is not None:
        lines.append(f"Baseline: {assessment['baseline_collected_at_utc']}")
    if not assessment["findings"]:
        lines.append("No findings detected by the enabled rules.")
        return "\n".join(lines)
    for severity in ("critical", "warning", "info"):
        selected = [item for item in assessment["findings"] if item["severity"] == severity]
        if not selected:
            continue
        lines.append(f"{severity.title()} ({len(selected)})")
        for finding in selected:
            subject = f" [{finding['subject']}]" if finding["subject"] else ""
            lines.append(
                f"  {finding['rule_id']} ({finding['check']}){subject}: {finding['message']}"
            )
    return "\n".join(lines)


@lru_cache(maxsize=1)
def _assessment_validator() -> Draft202012Validator:
    packaged = resources.files("rigpilot").joinpath("assessment.schema.json")
    try:
        schema_text = packaged.read_text(encoding="utf-8")
    except FileNotFoundError:
        schema_path = Path(__file__).parents[2] / "docs" / "assessment.schema.json"
        schema_text = schema_path.read_text(encoding="utf-8")
    schema = json.loads(schema_text)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_assessment(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("assessment: expected a JSON object")
    errors = sorted(
        _assessment_validator().iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        raise ValueError(f"invalid assessment: {errors[0].message}")
    findings = payload["findings"]
    actual_counts = {
        severity: sum(finding["severity"] == severity for finding in findings)
        for severity in ("info", "warning", "critical")
    }
    if payload["summary"]["counts"] != actual_counts:
        raise ValueError("invalid assessment: severity counts do not match findings")
    actual_highest = next(
        (severity for severity in ("critical", "warning", "info") if actual_counts[severity]),
        None,
    )
    if payload["summary"]["highest_severity"] != actual_highest:
        raise ValueError("invalid assessment: highest severity does not match findings")
    return payload
