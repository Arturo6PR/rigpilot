# RigPilot Agent Instructions

## Mission

Build a trustworthy, Windows-first workstation intelligence assistant, beginning with read-only inventory and diagnostics.

## Boundaries

- Target Windows 11 and PowerShell first.
- Prefer Python with a `src/` layout and `pytest` for tests.
- Treat commands and APIs that change drivers, firmware, services, registry, startup, power settings, or files outside this repository as privileged actions requiring explicit approval.
- Never claim telemetry was collected unless the command actually ran and its result was inspected.
- Never push, merge, publish, deploy, or rewrite Git history without explicit approval.

## Engineering workflow

1. Inspect Git status and existing code.
2. Plan the smallest vertical slice.
3. Keep system-command wrappers isolated and mockable.
4. Add tests for parsers, absent commands, timeouts, and malformed output.
5. Run tests and a safe local smoke check.
6. Document behavior and hand off with evidence.

## Definition of done

The requested behavior works, failures degrade safely, relevant tests pass, documentation is current, and no unapproved external action occurred.
