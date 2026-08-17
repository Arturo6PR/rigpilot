"""Thin GitHub Actions policy gate over RigPilot's structured CLI report."""

from __future__ import annotations

import html
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rigpilot.policy import validate_policy_report

_DEFAULT_REPORT = "rigpilot-assessment.json"
_MAX_SUMMARY_FINDINGS = 20


class _ActionInputError(ValueError):
    """An invalid action input that is safe to report generically."""


class _ActionMetadataError(OSError):
    """GitHub metadata could not be written safely."""


@dataclass(frozen=True)
class ActionResult:
    """GitHub-native values derived only from a validated policy report."""

    status: str
    passed: bool
    warnings: int
    failed: int
    critical: int
    report: str
    exit_code: int
    summary: str


def _contains_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _required_value(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "")
    if not value or _contains_control_characters(value):
        raise _ActionInputError("required action input is missing or invalid")
    return value


def _workspace_path(workspace: Path, value: str, *, must_exist: bool) -> Path:
    if _contains_control_characters(value):
        raise _ActionInputError("action path input is invalid")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    try:
        resolved = candidate.resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        raise _ActionInputError("action path is unavailable") from exc
    if not resolved.is_relative_to(workspace):
        raise _ActionInputError("action paths must remain within the workspace")
    if must_exist and not resolved.is_file():
        raise _ActionInputError("action input path must name a file")
    return resolved


def _report_name(report_path: Path, workspace: Path) -> str:
    return report_path.relative_to(workspace).as_posix()


def _assessment(report: dict[str, Any]) -> dict[str, Any]:
    return (
        report["report"]["assessment"] if report["report_kind"] == "guidance" else report["report"]
    )


def _summary_findings(report: dict[str, Any], indices: Sequence[int], heading: str) -> list[str]:
    findings = _assessment(report)["findings"]
    lines = [f"## {heading}", ""]
    for index in indices[:_MAX_SUMMARY_FINDINGS]:
        finding = findings[index]
        subject = f" on `{finding['subject']}`" if finding["subject"] is not None else ""
        lines.append(
            f"- **`{finding['rule_id']}`** ({finding['severity']}, "
            f"{finding['check']}){subject}: {finding['message']}"
        )
    omitted = len(indices) - _MAX_SUMMARY_FINDINGS
    if omitted > 0:
        lines.extend(("", f"_{omitted} additional findings omitted from this summary._"))
    return lines


def build_action_result(report: dict[str, Any], report_name: str) -> ActionResult:
    """Build deterministic Action outputs and Markdown from a policy-schema-1.0 report."""

    report = validate_policy_report(report)
    view = report["view"]
    view_summary = view["summary"]
    decision = report["decision"]
    matching = decision["matching_finding_indices"]
    status = "fail" if decision["triggered"] else "pass"
    escaped_report = html.escape(report_name, quote=True)
    lines = [
        "# RigPilot Assessment",
        "",
        f"**Status:** {status.upper()}",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Policy passed | {'yes' if not decision['triggered'] else 'no'} |",
        f"| Displayed findings | {view_summary['displayed_count']} |",
        f"| Warnings | {view_summary['counts']['warning']} |",
        f"| Critical findings | {view_summary['counts']['critical']} |",
        f"| Policy-triggering findings | {len(matching)} |",
        f"| Hidden findings | {view_summary['hidden_count']} |",
        "",
        f"JSON report: <code>{escaped_report}</code>",
    ]
    if matching:
        lines.extend(("", *_summary_findings(report, matching, "Policy-triggering findings")))
    else:
        warning_indices = [
            index
            for index in view["finding_indices"]
            if _assessment(report)["findings"][index]["severity"] == "warning"
        ]
        if warning_indices:
            lines.extend(("", *_summary_findings(report, warning_indices, "Warnings")))
        else:
            lines.extend(("", "No policy-triggering findings."))
    return ActionResult(
        status=status,
        passed=not decision["triggered"],
        warnings=view_summary["counts"]["warning"],
        failed=len(matching),
        critical=view_summary["counts"]["critical"],
        report=report_name,
        exit_code=decision["exit_code"],
        summary="\n".join(lines) + "\n",
    )


def _error_result(exit_code: int, report_name: str) -> ActionResult:
    kind = "input or configuration" if exit_code == 2 else "internal processing"
    return ActionResult(
        status="error",
        passed=False,
        warnings=0,
        failed=0,
        critical=0,
        report=report_name,
        exit_code=exit_code,
        summary=(
            "# RigPilot Assessment\n\n"
            "**Status:** ERROR\n\n"
            f"RigPilot could not complete because of an {kind} error (exit code `{exit_code}`).\n"
        ),
    )


def _append_text(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def _write_github_metadata(result: ActionResult, *, output_path: Path, summary_path: Path) -> None:
    _append_text(summary_path, result.summary)
    outputs = {
        "status": result.status,
        "passed": str(result.passed).lower(),
        "warnings": str(result.warnings),
        "failed": str(result.failed),
        "critical": str(result.critical),
        "report": result.report,
        "exit_code": str(result.exit_code),
        "summary": "true",
    }
    _append_text(output_path, "".join(f"{name}={value}\n" for name, value in outputs.items()))


def _invoke_rigpilot(
    snapshot: Path, policy: Path, report: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "rigpilot",
            "assess",
            str(snapshot),
            "--policy-file",
            str(policy),
            "--format",
            "json",
            "--output",
            str(report),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _metadata_paths(environment: Mapping[str, str]) -> tuple[Path, Path]:
    return (
        Path(_required_value(environment, "GITHUB_OUTPUT")),
        Path(_required_value(environment, "GITHUB_STEP_SUMMARY")),
    )


def _emit_result(result: ActionResult, *, environment: Mapping[str, str], error_stream: Any) -> int:
    output_path, summary_path = _metadata_paths(environment)
    try:
        _write_github_metadata(result, output_path=output_path, summary_path=summary_path)
    except Exception as exc:  # Metadata failures must not expose runner paths.
        raise _ActionMetadataError("GitHub metadata write failed") from exc
    if result.status == "error":
        print(
            f"RigPilot policy gate could not complete (exit code {result.exit_code}).",
            file=error_stream,
        )
    else:
        print(f"RigPilot policy gate: {result.status.upper()}")
    return result.exit_code


def _run_action(environment: Mapping[str, str], error_stream: Any) -> int:
    workspace_value = _required_value(environment, "GITHUB_WORKSPACE")
    try:
        workspace = Path(workspace_value).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _ActionInputError("GitHub workspace is unavailable") from exc
    if not workspace.is_dir():
        raise _ActionInputError("GitHub workspace is unavailable")

    snapshot = _workspace_path(
        workspace, _required_value(environment, "RIGPILOT_ACTION_SNAPSHOT"), must_exist=True
    )
    policy = _workspace_path(
        workspace, _required_value(environment, "RIGPILOT_ACTION_POLICY"), must_exist=True
    )
    report_value = environment.get("RIGPILOT_ACTION_REPORT", _DEFAULT_REPORT) or _DEFAULT_REPORT
    report = _workspace_path(workspace, report_value, must_exist=False)
    if report.exists() or not report.parent.is_dir():
        raise _ActionInputError("report path must name a new file in an existing directory")
    report_name = _report_name(report, workspace)

    completed = _invoke_rigpilot(snapshot, policy, report)
    if completed.returncode not in (0, 3):
        return _emit_result(
            _error_result(2 if completed.returncode == 2 else 1, report_name),
            environment=environment,
            error_stream=error_stream,
        )
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
        result = build_action_result(payload, report_name)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        result = _error_result(1, report_name)
    if result.exit_code != completed.returncode:
        result = _error_result(1, report_name)
    return _emit_result(result, environment=environment, error_stream=error_stream)


def run_action(
    environment: Mapping[str, str] | None = None, *, error_stream: Any = sys.stderr
) -> int:
    """Run the GitHub policy gate without leaking input or exception details."""

    selected_environment = os.environ if environment is None else environment
    try:
        return _run_action(selected_environment, error_stream)
    except _ActionMetadataError:
        print("RigPilot policy gate could not initialize.", file=error_stream)
        return 1
    except _ActionInputError:
        try:
            return _emit_result(
                _error_result(2, _DEFAULT_REPORT),
                environment=selected_environment,
                error_stream=error_stream,
            )
        except Exception:  # noqa: BLE001 - GitHub metadata errors must remain private.
            print("RigPilot policy gate could not initialize.", file=error_stream)
            return 1
    except Exception:  # noqa: BLE001 - Action failures must not expose runner or input details.
        try:
            return _emit_result(
                _error_result(1, _DEFAULT_REPORT),
                environment=selected_environment,
                error_stream=error_stream,
            )
        except Exception:  # noqa: BLE001 - GitHub metadata errors must remain private.
            print("RigPilot policy gate could not initialize.", file=error_stream)
            return 1


def main() -> int:
    """CLI entry point used by the composite Action."""

    return run_action()


if __name__ == "__main__":
    raise SystemExit(main())
