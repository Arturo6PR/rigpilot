# RigPilot v0.6.0

RigPilot v0.6.0 adds an opt-in, deterministic policy layer for controlling how assessment
findings are displayed and how automation reacts to them. The canonical assessment facts and
guidance remain complete and unchanged.

## Policy views and decisions

- Apply policy views to saved or live assessments with `--policy`.
- Select a minimum displayed severity or select findings by the `probes`, `storage`, `hardware`,
  and `bios` rule groups and by individual checks.
- Normalize selector order and duplicates deterministically. Values within group and check
  selectors are ORed, while severity, group, and check selectors are combined with AND.
- Reject invalid or contradictory selector combinations before saved input is loaded or live
  collection begins.
- Preserve the complete canonical assessment or guidance report in policy JSON. Views reference
  findings using their exact canonical indices and report exact severity counts, displayed and
  hidden counts, matching indices, and the resulting decision.
- Optionally use `--policy-fail-on` for scripting and CI. When a displayed finding reaches the
  configured threshold, RigPilot emits the complete successful output before returning exit code
  `3`.

## Schemas and compatibility

Policy JSON uses the strict, independently versioned policy schema 1.0. Snapshot, assessment,
guidance, and policy schemas are all packaged in the installed wheel and remain independently
versioned.

Policy works with assessments produced from saved snapshots or in-memory live collection,
optional baselines, and optional deterministic guidance. Existing timeout and live
collector-selection behavior is unchanged. When `--policy` is absent, existing human and JSON
assessment and guidance output remains byte-for-byte compatible.

## Privacy and safety

Policy output does not introduce workstation identities, filenames, raw probe messages, or other
sensitive values beyond the already validated canonical source report. Unexpected policy
construction, validation, serialization, or rendering failures return concise privacy-safe errors
without exception details.

The policy layer is pure and read-only. It filters only the displayed view and decision; it does
not change assessment rules or thresholds, suppress canonical findings, modify snapshots, select
live probes, execute commands, contact vendors, collect additional telemetry, or change files,
drivers, firmware, registry settings, services, startup items, power settings, or any other
workstation configuration.
