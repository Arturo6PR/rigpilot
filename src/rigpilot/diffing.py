"""Compare two saved RigPilot JSON snapshots without collecting telemetry."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    packaged = resources.files("rigpilot").joinpath("snapshot.schema.json")
    try:
        schema_text = packaged.read_text(encoding="utf-8")
    except FileNotFoundError:
        schema_path = Path(__file__).parents[2] / "docs" / "snapshot.schema.json"
        schema_text = schema_path.read_text(encoding="utf-8")
    schema = json.loads(schema_text)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_snapshot(payload: Any, label: str = "snapshot") -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError(f"{label}: expected a JSON object")
    errors = sorted(
        _validator().iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = "$" + "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path
        )
        raise ValueError(f"{label}: invalid snapshot at {location}: {error.message}")
    return payload


def _read_snapshot_text(path: Path) -> str:
    data = path.read_bytes()
    try:
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            return data.decode("utf-16")
        if data.startswith(b"\xef\xbb\xbf"):
            return data.decode("utf-8-sig")
        return data.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{path}: unsupported text encoding") from exc


def load_snapshot(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(_read_snapshot_text(path))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON at line {exc.lineno}, column {exc.colno}") from None
    return validate_snapshot(payload, str(path))


def compare_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before = validate_snapshot(before, "before snapshot")
    after = validate_snapshot(after, "after snapshot")
    if before.get("schema_version") != after.get("schema_version"):
        raise ValueError("Snapshots use different schema versions")
    before_checks = before.get("checks")
    after_checks = after.get("checks")
    if not isinstance(before_checks, dict) or not isinstance(after_checks, dict):
        raise TypeError("Both snapshots must contain a checks object")

    changes = []
    for name in sorted(set(before_checks) | set(after_checks)):
        old = before_checks.get(name)
        new = after_checks.get(name)
        if old == new:
            continue
        old = old if isinstance(old, dict) else {}
        new = new if isinstance(new, dict) else {}
        change = {
            "check": name,
            "status_before": old.get("status"),
            "status_after": new.get("status"),
            "data_changed": old.get("data") != new.get("data"),
            "message_before": old.get("message"),
            "message_after": new.get("message"),
        }
        if any(
            (
                change["status_before"] != change["status_after"],
                change["data_changed"],
                change["message_before"] != change["message_after"],
            )
        ):
            changes.append(change)
    return {
        "schema_version": before["schema_version"],
        "before_collected_at_utc": before.get("collected_at_utc"),
        "after_collected_at_utc": after.get("collected_at_utc"),
        "hostname_changed": before.get("hostname") != after.get("hostname"),
        "changes": changes,
    }


def render_diff_human(diff: dict[str, Any]) -> str:
    lines = [
        "RigPilot snapshot comparison",
        f"Before: {diff.get('before_collected_at_utc') or 'Unknown'}",
        f"After: {diff.get('after_collected_at_utc') or 'Unknown'}",
    ]
    changes = diff["changes"]
    if diff["hostname_changed"]:
        lines.append("Hostname: changed (values hidden)")
    if not changes:
        lines.append(
            "No check changes detected."
            if diff["hostname_changed"]
            else "No inventory changes detected."
        )
        return "\n".join(lines)
    for change in changes:
        details = []
        if change["status_before"] != change["status_after"]:
            details.append(f"status {change['status_before']} -> {change['status_after']}")
        if change["data_changed"]:
            details.append("data changed")
        if change["message_before"] != change["message_after"]:
            details.append("message changed")
        lines.append(f"{change['check']}: {', '.join(details)}")
    return "\n".join(lines)
