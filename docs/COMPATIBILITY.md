# RigPilot v1 public compatibility contract

This document defines the supported public surface for the RigPilot v1 series. Existing v0.7-era
policy configurations, v0.8 structured reports, and v0.9 GitHub Action workflows remain valid in
v1.0.0. Incompatible changes to the contracts below require a future major release unless a
security or correctness defect makes a narrowly scoped change unavoidable.

Undocumented Python modules, helper functions, rendered prose beyond the guarantees below, and
repository test fixtures are not public APIs.

## CLI

The installed command is `rigpilot`; `python -m rigpilot` is equivalent. The stable commands are:

- `rigpilot` collects one read-only system snapshot.
- `rigpilot diff BEFORE AFTER` compares two saved snapshot-schema-1.0 files.
- `rigpilot assess CURRENT` assesses a saved snapshot.
- `rigpilot assess --live` collects and assesses one snapshot in memory.
- `rigpilot --version` prints `rigpilot MAJOR.MINOR.PATCH` to stdout and exits successfully.

The inventory options are `--json`, `--redact`, `--no-hostname`, `--only`, `--skip`, and
`--timeout`. The `diff` option is `--json`. The assessment options are `--live`, `--baseline`,
`--json`, `--format text|json`, `--output`, `--guidance`, `--policy`, `--policy-file`,
`--policy-min-severity`, `--policy-groups`, `--policy-checks`, `--policy-fail-on`, `--only`,
`--skip`, and `--timeout`.

Valid check names are `operating_system`, `cpu`, `memory`, `storage`, `python`, `git`,
`nvidia_gpu`, `system`, `bios`, `memory_modules`, `physical_disks`, and `uptime`. Policy severity
values are `critical`, `warning`, and `info`; policy groups are `probes`, `storage`, `hardware`,
and `bios`.

Text is the default assessment format. The legacy assessment `--json` option remains equivalent
to `--format json`. A successful `--output PATH` creates a new UTF-8 file with one final newline,
never overwrites an existing path, and leaves stdout empty. Machine-readable stdout contains JSON
only; user and operational errors go to stderr.

### Exit codes

| Code | Meaning |
| ---: | --- |
| `0` | The requested operation completed. Assessment findings alone do not change this code. |
| `1` | An unexpected operational or internal failure prevented completion. |
| `2` | Arguments, paths, encodings, JSON, snapshots, or policy configuration were invalid. |
| `3` | A policy was evaluated, its report was emitted, and its configured `fail_on` threshold triggered. |

Argument parsing uses the conventional code `2`. `--format` and `--output` do not alter these
semantics.

## Versioned JSON contracts

RigPilot uses strict Draft 2020-12 schemas. Each schema rejects unknown fields. A new field or an
incompatible field change therefore requires a new schema version; consumers should select the
version they support instead of assuming a later schema has the same shape.

| Contract | Version field | Stable version | Schema |
| --- | --- | --- | --- |
| Snapshot | `schema_version` | `1.0` | [`snapshot.schema.json`](snapshot.schema.json) |
| Assessment | `assessment_schema_version` | `1.0` | [`assessment.schema.json`](assessment.schema.json) |
| Guidance | `guidance_schema_version` | `1.0` | [`guidance.schema.json`](guidance.schema.json) |
| Policy report | `policy_schema_version` | `1.0` | [`policy.schema.json`](policy.schema.json) |
| Policy configuration | `policy_config_schema_version` | `1.0` | [`policy-config.schema.json`](policy-config.schema.json) |

Assessment findings remain in canonical deterministic order. `summary.counts` equals the finding
array's severity counts, and `summary.highest_severity` is derived from those findings. Missing
subjects and baselines serialize as JSON `null`. A policy report embeds the complete unchanged
assessment or guidance report, refers to displayed and matching findings by canonical index, and
derives its counts and decision from those indices.

Policy configuration requires all five fields. `null` selectors mean no filtering, and a `null`
`fail_on` disables policy failure. Selector values normalize deterministically; unknown fields and
impossible selector combinations are rejected. The accepted severities are `critical`, `warning`,
and `info`; groups are `probes`, `storage`, `hardware`, and `bios`.

## GitHub Action

Workflows written for v0.9 remain compatible with v1. The Action accepts exactly these inputs:

| Input | Required | Default |
| --- | --- | --- |
| `snapshot` | yes | none |
| `policy` | yes | none |
| `report` | no | `rigpilot-assessment.json` |
| `python-version` | no | `3.12` |

Its outputs are:

| Output | Meaning |
| --- | --- |
| `status` | `pass`, `fail`, or `error`. |
| `passed` | `true` only when the policy decision did not trigger. |
| `warnings` | Number of displayed warning findings. |
| `failed` | Number of canonical findings referenced by the policy decision. |
| `critical` | Number of displayed critical findings. |
| `report` | Workspace-relative JSON report path. |
| `exit_code` | RigPilot's `0`, `1`, `2`, or `3` result. |
| `summary` | `true` when the GitHub Step Summary was written successfully. |

The outputs and Step Summary are derived only from the validated policy-schema-1.0 report. A
passing policy returns `0`; a triggered policy writes its JSON report, outputs, and Step Summary
before returning `3`; input/configuration errors return `2`; and internal errors return `1`.

`Arturo6PR/rigpilot@v1` follows compatible v1 Action releases. Use `@v1.0.0` to select this exact
release, or a verified full commit SHA when an immutable source reference is required.

## Privacy and security

RigPilot sends no telemetry and has no cloud service. Saved-snapshot assessment never runs system
probes. Live collection must be requested explicitly and omits the hostname before assessment.
Assessment, guidance, policy, and Action summaries exclude hostnames, volume labels, executable
paths, raw probe errors, and hardware identity values.

The Action accepts only workspace-contained snapshot, policy, and new report paths. It passes
inputs through environment variables and Python argument arrays, not shell interpolation, and
requires no user secret or permission broader than `contents: read` for checkout.
