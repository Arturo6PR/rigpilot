# RigPilot project brief

## Purpose

Help users understand a Windows AI workstation through transparent, deterministic, read-only
inventory and assessment.

## Stable v1 scope

RigPilot provides:

- timeout-bounded Windows inventory with explicit successful, unavailable, and failed probes;
- strict saved-snapshot comparison and deterministic assessment;
- reusable policy files and versioned JSON reports for local automation;
- safe, opt-in guidance that never executes its recommendations; and
- a thin GitHub Action that applies the same CLI policy gate to repository-owned snapshots.

The v1 public contracts are the documented CLI, exit codes, schema-1.0 formats, and GitHub Action
interface. See [`COMPATIBILITY.md`](COMPATIBILITY.md) for their exact stability boundary.

## Safety boundaries

- No automatic optimization or remediation.
- No driver, firmware, registry, service, startup, or power-plan changes.
- No remote telemetry, RigPilot cloud account, or vendor contact.
- Live collection is explicit, read-only, independently bounded, and never used by the GitHub
  Action.

## Supported environment

Windows 11 and PowerShell are the primary inventory environment. The saved-snapshot assessment
and composite GitHub Action are also exercised on GitHub's Ubuntu runner. CI covers Python
3.11-3.13, Windows PowerShell 5.1, and PowerShell 7.
