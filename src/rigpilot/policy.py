"""Deterministic policy views over validated RigPilot reports."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from rigpilot.assessment import validate_assessment
from rigpilot.guidance import validate_guidance

SEVERITIES = ("critical", "warning", "info")
RULE_GROUPS_ORDER = ("probes", "storage", "hardware", "bios")
POLICY_CHECKS = (
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
)
_SEVERITY_RANK = {severity: index for index, severity in enumerate(SEVERITIES)}

RULE_GROUPS = MappingProxyType(
    {
        "probe.skipped": "probes",
        "probe.optional_unavailable": "probes",
        "probe.unavailable": "probes",
        "probe.failed": "probes",
        "storage.low_capacity": "storage",
        "storage.critically_low_capacity": "storage",
        "hardware.system_changed": "hardware",
        "hardware.cpu_changed": "hardware",
        "hardware.memory_changed": "hardware",
        "hardware.physical_disks_changed": "hardware",
        "hardware.nvidia_gpu_changed": "hardware",
        "bios.release_date_missing": "bios",
        "bios.release_date_future": "bios",
        "bios.release_date_stale": "bios",
    }
)

GROUP_CHECKS = MappingProxyType(
    {
        "probes": frozenset(POLICY_CHECKS),
        "storage": frozenset({"storage"}),
        "hardware": frozenset({"system", "cpu", "memory_modules", "physical_disks", "nvidia_gpu"}),
        "bios": frozenset({"bios"}),
    }
)


def _normalized_selector(
    values: tuple[str, ...] | None, canonical: tuple[str, ...], label: str
) -> tuple[str, ...] | None:
    if values is None:
        return None
    if not values:
        raise ValueError(f"{label} must not be empty")
    unknown = set(values) - set(canonical)
    if unknown:
        raise ValueError(f"unknown {label}: {', '.join(sorted(unknown))}")
    selected = set(values)
    return tuple(value for value in canonical if value in selected)


@dataclass(frozen=True)
class Policy:
    """Normalized policy selectors for a deterministic report view and decision."""

    minimum_severity: str | None = None
    rule_groups: tuple[str, ...] | None = None
    checks: tuple[str, ...] | None = None
    fail_on: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("minimum severity", self.minimum_severity),
            ("fail-on severity", self.fail_on),
        ):
            if value is not None and value not in _SEVERITY_RANK:
                raise ValueError(f"unknown {name}: {value}")
        object.__setattr__(
            self,
            "rule_groups",
            _normalized_selector(self.rule_groups, RULE_GROUPS_ORDER, "policy groups"),
        )
        object.__setattr__(
            self,
            "checks",
            _normalized_selector(self.checks, POLICY_CHECKS, "policy checks"),
        )
        if self.rule_groups is not None and self.checks is not None:
            possible_checks = set().union(*(GROUP_CHECKS[group] for group in self.rule_groups))
            if possible_checks.isdisjoint(self.checks):
                raise ValueError("policy groups and checks cannot match any finding")
        if (
            self.minimum_severity is not None
            and self.fail_on is not None
            and _SEVERITY_RANK[self.fail_on] > _SEVERITY_RANK[self.minimum_severity]
        ):
            raise ValueError("policy fail-on cannot be less severe than the display minimum")


def _source_report(report: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if "guidance_schema_version" in report:
        validated = validate_guidance(report)
        return "guidance", validated, validated["assessment"]
    if "assessment_schema_version" in report:
        validated = validate_assessment(report)
        return "assessment", validated, validated
    raise ValueError("policy source must be an assessment or guidance report")


def _matches(finding: dict[str, Any], policy: Policy) -> bool:
    if (
        policy.minimum_severity is not None
        and _SEVERITY_RANK[finding["severity"]] > _SEVERITY_RANK[policy.minimum_severity]
    ):
        return False
    if policy.rule_groups is not None and RULE_GROUPS[finding["rule_id"]] not in policy.rule_groups:
        return False
    return policy.checks is None or finding["check"] in policy.checks


def _policy_object(policy: Policy) -> dict[str, Any]:
    return {
        "minimum_severity": policy.minimum_severity,
        "rule_groups": list(policy.rule_groups) if policy.rule_groups is not None else None,
        "checks": list(policy.checks) if policy.checks is not None else None,
        "fail_on": policy.fail_on,
    }


def _build_unvalidated(report: dict[str, Any], policy: Policy) -> dict[str, Any]:
    report_kind, validated_report, assessment = _source_report(report)
    findings = assessment["findings"]
    visible = [index for index, finding in enumerate(findings) if _matches(finding, policy)]
    counts = {
        severity: sum(findings[index]["severity"] == severity for index in visible)
        for severity in ("info", "warning", "critical")
    }
    highest = next((severity for severity in SEVERITIES if counts[severity]), None)
    matching = (
        [
            index
            for index in visible
            if _SEVERITY_RANK[findings[index]["severity"]] <= _SEVERITY_RANK[policy.fail_on]
        ]
        if policy.fail_on is not None
        else []
    )
    triggered = bool(matching)
    return {
        "policy_schema_version": "1.0",
        "report_kind": report_kind,
        "report": copy.deepcopy(validated_report),
        "policy": _policy_object(policy),
        "view": {
            "finding_indices": visible,
            "summary": {
                "highest_severity": highest,
                "counts": counts,
                "displayed_count": len(visible),
                "hidden_count": len(findings) - len(visible),
            },
        },
        "decision": {
            "triggered": triggered,
            "matching_finding_indices": matching,
            "exit_code": 3 if triggered else 0,
        },
    }


def build_policy_report(report: dict[str, Any], policy: Policy) -> dict[str, Any]:
    """Build a policy view without filtering or mutating its canonical source report."""

    if not isinstance(policy, Policy):
        raise TypeError("policy: expected a Policy")
    result = _build_unvalidated(report, policy)
    validate_policy_report(result)
    return result


def _assessment_from_policy_report(payload: dict[str, Any]) -> dict[str, Any]:
    return (
        payload["report"]["assessment"]
        if payload["report_kind"] == "guidance"
        else payload["report"]
    )


def render_policy_human(payload: dict[str, Any]) -> str:
    """Render only the policy view while disclosing complete and hidden finding counts."""

    payload = validate_policy_report(payload)
    assessment = _assessment_from_policy_report(payload)
    policy = payload["policy"]
    summary = payload["view"]["summary"]
    selectors = (
        f"severity {policy['minimum_severity'] or 'all'}; "
        f"groups {','.join(policy['rule_groups']) if policy['rule_groups'] else 'all'}; "
        f"checks {','.join(policy['checks']) if policy['checks'] else 'all'}"
    )
    lines = [
        "RigPilot policy view",
        f"Snapshot: {assessment['subject_collected_at_utc']}",
        f"Policy: {selectors}",
        f"Canonical findings: {len(assessment['findings'])}",
        f"Displayed findings: {summary['displayed_count']} ({summary['hidden_count']} hidden)",
    ]
    guidance_by_index = (
        {entry["finding_index"]: entry for entry in payload["report"]["guidance"]}
        if payload["report_kind"] == "guidance"
        else {}
    )
    for severity in SEVERITIES:
        indices = [
            index
            for index in payload["view"]["finding_indices"]
            if assessment["findings"][index]["severity"] == severity
        ]
        if not indices:
            continue
        lines.append(f"{severity.title()} ({len(indices)})")
        for index in indices:
            finding = assessment["findings"][index]
            subject = f" [{finding['subject']}]" if finding["subject"] else ""
            lines.append(
                f"  {finding['rule_id']} ({finding['check']}){subject}: {finding['message']}"
            )
            guidance = guidance_by_index.get(index)
            if guidance is not None:
                lines.append(f"    What it means: {guidance['explanation']}")
                lines.append("    Safe next steps:")
                lines.extend(f"      - {action['text']}" for action in guidance["next_steps"])
    fail_on = policy["fail_on"]
    if payload["decision"]["triggered"]:
        lines.append(f"Decision: triggered at {fail_on} severity")
    elif fail_on is None:
        lines.append("Decision: no fail-on threshold configured")
    else:
        lines.append(f"Decision: not triggered at {fail_on} severity")
    return "\n".join(lines)


def _schema_text(name: str) -> str:
    packaged = resources.files("rigpilot").joinpath(name)
    try:
        return packaged.read_text(encoding="utf-8")
    except FileNotFoundError:
        return (Path(__file__).parents[2] / "docs" / name).read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _policy_validator() -> Draft202012Validator:
    schemas = {
        name: json.loads(_schema_text(name))
        for name in (
            "assessment.schema.json",
            "guidance.schema.json",
            "policy.schema.json",
        )
    }
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
    registry = Registry()
    for name in ("assessment.schema.json", "guidance.schema.json"):
        schema = schemas[name]
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return Draft202012Validator(
        schemas["policy.schema.json"], registry=registry, format_checker=FormatChecker()
    )


def validate_policy_report(payload: Any) -> dict[str, Any]:
    """Strictly validate policy structure and all deterministic relationships."""

    if not isinstance(payload, dict):
        raise TypeError("policy report: expected a JSON object")
    errors = sorted(
        _policy_validator().iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        raise ValueError(f"invalid policy report: {errors[0].message}")
    report_kind, _, _ = _source_report(payload["report"])
    if payload["report_kind"] != report_kind:
        raise ValueError("invalid policy report: report kind does not match source report")
    configured = payload["policy"]
    policy = Policy(
        minimum_severity=configured["minimum_severity"],
        rule_groups=(
            tuple(configured["rule_groups"]) if configured["rule_groups"] is not None else None
        ),
        checks=tuple(configured["checks"]) if configured["checks"] is not None else None,
        fail_on=configured["fail_on"],
    )
    expected = _build_unvalidated(payload["report"], policy)
    if payload != expected:
        raise ValueError("invalid policy report: derived view or decision does not match source")
    return payload
