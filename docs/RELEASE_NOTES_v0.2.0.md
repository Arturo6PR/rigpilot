# RigPilot v0.2.0

RigPilot v0.2.0 adds focused inventory collection and safe comparison of saved snapshots while
preserving the project's read-only behavior.

## Highlights

- Run only selected inventory checks with `--only`, or exclude checks with `--skip`. Checks that
  are not selected are not executed and remain schema-compatible as `unavailable` results.
- Compare two saved schema-1.0 snapshots with `rigpilot diff` in human-readable or JSON form.
- Strictly validate both snapshots before comparison and report malformed or incompatible input
  without a traceback.
- Report hostname changes without exposing either hostname value in comparison output.
- Read snapshot files encoded as UTF-8, UTF-8 with a BOM, or UTF-16 with a little- or big-endian
  BOM, including output redirected by Windows PowerShell 5.1.
- Exercise the Windows test suite across Python 3.11-3.13 using both Windows PowerShell 5.1 and
  PowerShell 7 in CI.

## Privacy and safety

RigPilot remains read-only. It does not change drivers, firmware, services, registry, startup
entries, files outside the repository, or power settings, and it does not upload telemetry.
Snapshot JSON can contain sensitive workstation details; use `--redact` or `--no-hostname` as
appropriate and inspect saved output before sharing it.

## Compatibility

- Windows 11 and PowerShell remain the primary supported environment.
- Python 3.11 or newer is required.
- Snapshot output continues to use schema version 1.0.
