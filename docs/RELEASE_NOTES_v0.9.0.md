# RigPilot v0.9.0

RigPilot v0.9.0 adds a native GitHub Actions policy gate for deterministic saved-snapshot
assessment in CI.

## Highlights

- Run `Arturo6PR/rigpilot@v0.9.0` with a saved snapshot and reusable RigPilot policy file.
- Preserve the complete policy-schema-1.0 JSON report at a predictable workspace-relative path
  for later steps or optional artifact upload.
- See a concise GitHub Step Summary with the overall gate status, displayed warning and critical
  counts, hidden findings, and policy-triggering rule IDs.
- Consume structured Action outputs for status, pass/fail state, warning, critical, and failing
  finding counts, report path, RigPilot exit code, and summary completion.
- Propagate RigPilot's decision exactly: passing policies return `0`, policy failures return `3`
  after reporting, input/configuration errors return `2`, and internal failures return `1`.

## Compatibility and safety

The composite Action invokes the existing RigPilot CLI and derives its summary and outputs only
from the strictly validated v0.8.0 structured policy report. It does not parse human-readable
terminal text, duplicate assessment logic, or change policy semantics, assessment thresholds, or
any snapshot, assessment, guidance, policy, or policy-configuration schema.

Action inputs are passed through environment variables and Python argument arrays rather than
shell interpolation. Snapshot, policy, and report paths must resolve inside `GITHUB_WORKSPACE`,
and report files are never overwritten. Official setup and checkout Actions are pinned to their
immutable v7.0.0 commits, and the example workflows require only `contents: read`.

CI dogfood covers clean passing, warning-containing passing, and intentionally failing policy
fixtures. A separate manual workflow verifies the published `Arturo6PR/rigpilot@v0.9.0` tag after
release without leaving the required release CI red.

RigPilot remains local and read-only. The Action does not collect live runner telemetry, use a
RigPilot cloud service, dump environment variables or secrets, modify system settings, or publish
reports to external storage.
