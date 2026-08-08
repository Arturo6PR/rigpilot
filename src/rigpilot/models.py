"""Structured results for RigPilot inventory checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from enum import StrEnum
from typing import Any


class CheckStatus(StrEnum):
    """Possible outcomes for one inventory check."""

    SUCCESS = "success"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True)
class CheckResult:
    """The outcome and optional payload for one inventory check."""

    status: CheckStatus
    data: Any = None
    message: str | None = None

    @classmethod
    def success(cls, data: Any) -> CheckResult:
        return cls(CheckStatus.SUCCESS, data=data)

    @classmethod
    def unavailable(cls, message: str) -> CheckResult:
        return cls(CheckStatus.UNAVAILABLE, message=message)

    @classmethod
    def failed(cls, message: str) -> CheckResult:
        return cls(CheckStatus.FAILED, message=message)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Snapshot:
    """A complete local workstation snapshot."""

    operating_system: CheckResult
    cpu: CheckResult
    memory: CheckResult
    storage: CheckResult
    python: CheckResult
    git: CheckResult
    nvidia_gpu: CheckResult

    def to_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name).to_dict() for field in fields(self)}
