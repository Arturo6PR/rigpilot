"""Deterministic, privacy-safe guidance for validated RigPilot assessments."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from rigpilot.assessment import validate_assessment


@dataclass(frozen=True)
class GuidanceAction:
    action_id: str
    kind: str
    text: str


@dataclass(frozen=True)
class GuidanceTemplate:
    explanation: str
    next_steps: tuple[GuidanceAction, ...]


def _action(action_id: str, kind: str, text: str) -> GuidanceAction:
    return GuidanceAction(action_id, kind, text)


_HARDWARE_TEMPLATE = GuidanceTemplate(
    "Stable inventory fields differ from the baseline; this does not establish failure or "
    "tampering.",
    (
        _action(
            "compare_change_records",
            "verify",
            "Compare the finding with intentional upgrades, maintenance, and configuration "
            "records.",
        ),
        _action(
            "investigate_unexpected_change",
            "consult",
            "If the change is unexpected, inspect the workstation or consult qualified support "
            "before taking corrective action.",
        ),
    ),
)


GUIDANCE_CATALOG = MappingProxyType(
    {
        "probe.skipped": GuidanceTemplate(
            "This inventory check was intentionally excluded, so its results were not assessed.",
            (
                _action(
                    "include_check_if_needed",
                    "review",
                    "No action is required; include this check in a future assessment if its "
                    "coverage is needed.",
                ),
            ),
        ),
        "probe.optional_unavailable": GuidanceTemplate(
            "The optional NVIDIA inventory check was unavailable; this does not indicate a GPU "
            "problem.",
            (
                _action(
                    "confirm_nvidia_coverage_needed",
                    "review",
                    "No action is required when NVIDIA hardware is not expected.",
                ),
                _action(
                    "verify_nvidia_local_support",
                    "verify",
                    "If NVIDIA coverage is expected, verify that supported NVIDIA hardware and "
                    "locally installed management tooling are available.",
                ),
            ),
        ),
        "probe.unavailable": GuidanceTemplate(
            "This inventory check could not run, so assessment coverage for it is incomplete.",
            (
                _action(
                    "verify_local_inventory_support",
                    "verify",
                    "Verify that the local software required for this inventory check is installed "
                    "and available.",
                ),
                _action(
                    "repeat_after_local_review",
                    "review",
                    "Repeat the assessment after reviewing the local software and configured "
                    "timeout.",
                ),
            ),
        ),
        "probe.failed": GuidanceTemplate(
            "This inventory check did not complete successfully, so related assessment coverage "
            "is incomplete.",
            (
                _action(
                    "repeat_assessment_once",
                    "verify",
                    "Repeat the assessment once to determine whether the failure persists.",
                ),
                _action(
                    "consult_persistent_probe_failure",
                    "consult",
                    "If it persists, note which check was affected and consult qualified support; "
                    "do not infer a hardware fault from this finding alone.",
                ),
            ),
        ),
        "storage.low_capacity": GuidanceTemplate(
            "Available capacity is below RigPilot's warning thresholds.",
            (
                _action(
                    "review_storage_usage",
                    "review",
                    "Review storage usage and identify data that could be moved to approved "
                    "storage.",
                ),
                _action(
                    "plan_storage_capacity",
                    "plan",
                    "Plan additional capacity if expected workloads require more space.",
                ),
            ),
        ),
        "storage.critically_low_capacity": GuidanceTemplate(
            "Available capacity is below both of RigPilot's critical thresholds.",
            (
                _action(
                    "protect_important_data",
                    "verify",
                    "Confirm that important data is protected before making storage changes.",
                ),
                _action(
                    "avoid_large_new_writes",
                    "plan",
                    "Avoid unnecessary large new writes while capacity remains critically low.",
                ),
                _action(
                    "plan_additional_capacity",
                    "plan",
                    "Plan additional capacity promptly.",
                ),
            ),
        ),
        "hardware.system_changed": _HARDWARE_TEMPLATE,
        "hardware.cpu_changed": _HARDWARE_TEMPLATE,
        "hardware.memory_changed": _HARDWARE_TEMPLATE,
        "hardware.physical_disks_changed": _HARDWARE_TEMPLATE,
        "hardware.nvidia_gpu_changed": _HARDWARE_TEMPLATE,
        "bios.release_date_missing": GuidanceTemplate(
            "RigPilot cannot evaluate BIOS age because no release date was reported.",
            (
                _action(
                    "review_official_bios_information",
                    "consult",
                    "Consult the system manufacturer's official support information if BIOS "
                    "currency matters.",
                ),
            ),
        ),
        "bios.release_date_future": GuidanceTemplate(
            "The reported BIOS date is later than the snapshot collection date; this may reflect "
            "clock or firmware metadata.",
            (
                _action(
                    "verify_system_time",
                    "verify",
                    "Verify that the workstation date and time are correct.",
                ),
                _action(
                    "review_official_bios_information",
                    "consult",
                    "Consult the system manufacturer's official support information if the date "
                    "remains unexpected.",
                ),
            ),
        ),
        "bios.release_date_stale": GuidanceTemplate(
            "The reported BIOS release date is at least five complete calendar years old; age "
            "alone does not establish a vulnerability.",
            (
                _action(
                    "review_official_bios_guidance",
                    "consult",
                    "Review the system manufacturer's official guidance for the exact system.",
                ),
                _action(
                    "avoid_unverified_firmware",
                    "verify",
                    "Do not install firmware solely because of this finding, and do not select a "
                    "BIOS version without verified manufacturer guidance.",
                ),
            ),
        ),
    }
)


def _guidance_entries(assessment: dict[str, Any]) -> list[dict[str, Any]]:
    entries = []
    for index, finding in enumerate(assessment["findings"]):
        template = GUIDANCE_CATALOG[finding["rule_id"]]
        entries.append(
            {
                "finding_index": index,
                "rule_id": finding["rule_id"],
                "explanation": template.explanation,
                "next_steps": [asdict(action) for action in template.next_steps],
            }
        )
    return entries


def build_guidance(assessment: dict[str, Any]) -> dict[str, Any]:
    """Build deterministic guidance without collecting data or mutating the assessment."""

    assessment = validate_assessment(assessment)
    report = {
        "guidance_schema_version": "1.0",
        "assessment": copy.deepcopy(assessment),
        "guidance": _guidance_entries(assessment),
    }
    validate_guidance(report)
    return report


def render_guidance_human(report: dict[str, Any]) -> str:
    report = validate_guidance(report)
    lines = ["Guidance"]
    if not report["guidance"]:
        lines.append("No findings require guidance.")
        return "\n".join(lines)
    for entry in report["guidance"]:
        lines.append(entry["rule_id"])
        lines.append(f"  What it means: {entry['explanation']}")
        lines.append("  Safe next steps:")
        lines.extend(f"    - {action['text']}" for action in entry["next_steps"])
    return "\n".join(lines)


def _schema_text(name: str) -> str:
    packaged = resources.files("rigpilot").joinpath(name)
    try:
        return packaged.read_text(encoding="utf-8")
    except FileNotFoundError:
        return (Path(__file__).parents[2] / "docs" / name).read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _guidance_validator() -> Draft202012Validator:
    schema = json.loads(_schema_text("guidance.schema.json"))
    assessment_schema = json.loads(_schema_text("assessment.schema.json"))
    Draft202012Validator.check_schema(schema)
    registry = Registry().with_resource(
        assessment_schema["$id"], Resource.from_contents(assessment_schema)
    )
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


def validate_guidance(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("guidance: expected a JSON object")
    errors = sorted(
        _guidance_validator().iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        raise ValueError(f"invalid guidance: {errors[0].message}")
    assessment = validate_assessment(payload["assessment"])
    if payload["guidance"] != _guidance_entries(assessment):
        raise ValueError("invalid guidance: entries do not match assessment findings")
    return payload
