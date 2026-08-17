# RigPilot v0.8.0

RigPilot v0.8.0 adds deterministic structured assessment output for scripts and CI systems while
preserving the existing read-only assessment, guidance, and policy semantics.

## Highlights

- Select assessment rendering explicitly with `--format text|json`; text remains the default,
  and the existing `--json` option remains byte-compatible.
- Write either rendering to a new UTF-8 file with `--output PATH`. RigPilot refuses to overwrite
  an existing path, leaves stdout empty after a successful file write, and sends operational
  diagnostics to stderr.
- Reuse strict JSON policy configurations with `--policy-file`. Configuration schema 1.0 is
  validated before saved snapshot loading or live collection, and selectors normalize through
  the existing deterministic policy engine.
- Consume the existing stable, versioned result contracts: assessment schema 1.0 by default,
  guidance schema 1.0 with guidance, and policy schema 1.0 when a policy is active.
- Retain existing exit semantics: findings alone return `0`, invalid arguments or inputs return
  `2`, unexpected processing failures return `1`, and a triggered policy returns `3` only after
  its report has been emitted successfully.

## Compatibility and safety

Existing assessment commands produce the same output when the new options are absent. Structured
output is assembled from RigPilot's canonical in-memory reports rather than parsed from human
text, so counts, finding order, policy decisions, and JSON serialization remain deterministic.

The wheel includes all five strict Draft 2020-12 schemas, including the new policy-configuration
schema. This release does not change collectors, assessment rules or thresholds, guidance text,
policy behavior, or the snapshot, assessment, guidance, and policy report schemas.

RigPilot remains local and read-only. It does not send telemetry, contact cloud services, execute
guidance, modify input snapshots, change workstation settings, or expose additional inventory
data through these output controls.
