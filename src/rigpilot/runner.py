"""Bounded, shell-free execution for read-only system probes."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from time import perf_counter

from rigpilot.models import CheckStatus


@dataclass(frozen=True)
class CommandResult:
    status: CheckStatus
    stdout: str = ""
    message: str | None = None
    duration_ms: float = 0.0


def run_command(command: Sequence[str], timeout: float = 5.0) -> CommandResult:
    """Run a command without a shell and convert expected failures into data."""

    if not isfinite(timeout) or timeout <= 0:
        return CommandResult(
            CheckStatus.FAILED, message="Command timeout must be finite and positive"
        )

    started = perf_counter()
    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
    except FileNotFoundError:
        return CommandResult(
            CheckStatus.UNAVAILABLE,
            message=f"Command not found: {command[0]}",
            duration_ms=(perf_counter() - started) * 1000,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            CheckStatus.FAILED,
            message=f"Command timed out after {timeout:g}s",
            duration_ms=(perf_counter() - started) * 1000,
        )
    except OSError as exc:
        return CommandResult(
            CheckStatus.FAILED,
            message=f"Could not run command: {exc}",
            duration_ms=(perf_counter() - started) * 1000,
        )

    duration_ms = (perf_counter() - started) * 1000
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit code {completed.returncode}"
        return CommandResult(
            CheckStatus.FAILED, message=f"Command failed: {detail}", duration_ms=duration_ms
        )
    return CommandResult(
        CheckStatus.SUCCESS, stdout=completed.stdout.strip(), duration_ms=duration_ms
    )
