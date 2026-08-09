# RigPilot v0.4.0

RigPilot v0.4.0 adds in-memory live assessment while preserving the deterministic saved-snapshot
workflow and the project's read-only behavior.

## Highlights

- Collect and assess one workstation snapshot in memory with `rigpilot assess --live`, without
  writing the raw snapshot to disk.
- Optionally compare the live snapshot with a strictly validated saved baseline using
  `--baseline`.
- Apply the existing per-command timeout and selective collection controls with `--timeout`,
  `--only`, and `--skip`.
- Collect exactly once per live assessment and strictly validate the in-memory snapshot before
  running the same schema-backed rules used for saved snapshots.
- Preserve saved assessment commands and snapshot encoding support without changing snapshot or
  assessment schema version 1.0.

## Errors and findings

Normal failed or unavailable probes remain assessment findings and do not make a completed
assessment fail. Invalid arguments and invalid saved inputs return a concise input error. An
unexpected live-pipeline failure returns a generic privacy-safe error without exposing internal
details, while process-control interrupts continue to propagate normally.

## Privacy and safety

Live assessment omits the collected hostname before validation and never prints the raw snapshot.
Assessment output excludes hostnames, volume labels, executable paths, raw probe errors, and
hardware identity values. Every system probe remains read-only, shell-free where external commands
are used, and bounded by the configured timeout. RigPilot does not change drivers, firmware,
registry settings, services, startup items, power plans, or other workstation settings.

## Compatibility

- Windows 11 and PowerShell remain the primary supported environment.
- Python 3.11 or newer is required.
- Snapshot and assessment outputs retain schema version 1.0.
- Saved-snapshot assessment and optional baseline comparison remain fully supported.
- Both JSON schemas remain included in installed wheels.
