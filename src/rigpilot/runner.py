"""Bounded, shell-free execution for read-only system probes."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

from rigpilot.models import CheckStatus


@dataclass(frozen=True)
class CommandResult:
    status: CheckStatus
    stdout: str = ""
    message: str | None = None


def run_command(command: Sequence[str], timeout: float = 5.0) -> CommandResult:
    """Run a command without a shell and convert expected failures into data."""

    if not isfinite(timeout) or timeout <= 0:
        return CommandResult(
            CheckStatus.FAILED, message="Command timeout must be finite and positive"
        )

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
        return CommandResult(CheckStatus.UNAVAILABLE, message=f"Command not found: {command[0]}")
    except subprocess.TimeoutExpired:
        return CommandResult(CheckStatus.FAILED, message=f"Command timed out after {timeout:g}s")
    except OSError as exc:
        return CommandResult(CheckStatus.FAILED, message=f"Could not run command: {exc}")

    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit code {completed.returncode}"
        return CommandResult(CheckStatus.FAILED, message=f"Command failed: {detail}")
    return CommandResult(CheckStatus.SUCCESS, stdout=completed.stdout.strip())
