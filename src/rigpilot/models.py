"""Structured results for RigPilot inventory checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
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
    duration_ms: float = 0.0

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
    system: CheckResult = field(default_factory=lambda: CheckResult.unavailable("Not collected"))
    bios: CheckResult = field(default_factory=lambda: CheckResult.unavailable("Not collected"))
    memory_modules: CheckResult = field(
        default_factory=lambda: CheckResult.unavailable("Not collected")
    )
    physical_disks: CheckResult = field(
        default_factory=lambda: CheckResult.unavailable("Not collected")
    )
    uptime: CheckResult = field(default_factory=lambda: CheckResult.unavailable("Not collected"))
    schema_version: str = "1.0"
    collected_at_utc: str = ""
    hostname: str = ""

    def checks(self) -> dict[str, CheckResult]:
        return {
            field.name: getattr(self, field.name)
            for field in fields(self)
            if isinstance(getattr(self, field.name), CheckResult)
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "collected_at_utc": self.collected_at_utc,
            "hostname": self.hostname,
            "checks": {name: result.to_dict() for name, result in self.checks().items()},
        }
