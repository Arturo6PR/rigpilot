"""Strict, read-only loading of reusable RigPilot policy configuration files."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from rigpilot.policy import Policy


def _schema_text() -> str:
    packaged = resources.files("rigpilot").joinpath("policy-config.schema.json")
    try:
        return packaged.read_text(encoding="utf-8")
    except FileNotFoundError:
        return (Path(__file__).parents[2] / "docs" / "policy-config.schema.json").read_text(
            encoding="utf-8"
        )


@lru_cache(maxsize=1)
def _policy_config_validator() -> Draft202012Validator:
    schema = json.loads(_schema_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_policy_config(payload: Any) -> Policy:
    """Validate configuration structure and return its normalized immutable policy."""

    if not isinstance(payload, dict):
        raise TypeError("policy configuration: expected a JSON object")
    errors = sorted(
        _policy_config_validator().iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = "$" + "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path
        )
        raise ValueError(f"invalid policy configuration at {location}: {error.message}")
    return Policy(
        minimum_severity=payload["minimum_severity"],
        rule_groups=(tuple(payload["rule_groups"]) if payload["rule_groups"] is not None else None),
        checks=tuple(payload["checks"]) if payload["checks"] is not None else None,
        fail_on=payload["fail_on"],
    )


def _read_policy_config_text(path: Path) -> str:
    data = path.read_bytes()
    try:
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            return data.decode("utf-16")
        if data.startswith(b"\xef\xbb\xbf"):
            return data.decode("utf-8-sig")
        return data.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{path}: unsupported text encoding") from exc


def load_policy_config(path: Path) -> Policy:
    """Load a policy configuration without modifying it or retaining its filename."""

    try:
        payload = json.loads(_read_policy_config_text(path))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON at line {exc.lineno}, column {exc.colno}") from None
    return validate_policy_config(payload)
