# RigPilot

RigPilot is a Windows-first workstation intelligence assistant. It provides a safe, read-only
system inventory covering the operating system, system model, BIOS, CPU, physical memory,
logical and physical storage, uptime, Python, Git, and NVIDIA GPUs.

## Five-minute quickstart

RigPilot requires Python 3.11 or newer. From a clone of this repository, create an isolated
environment and install the package:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\rigpilot.exe --version
.\.venv\Scripts\rigpilot.exe --help
```

Collect one local snapshot without a hostname, then assess the saved file without collecting
again:

```powershell
.\.venv\Scripts\rigpilot.exe --json --no-hostname > current.json
.\.venv\Scripts\rigpilot.exe assess current.json
```

Create `rigpilot-policy.json`:

```json
{
  "policy_config_schema_version": "1.0",
  "minimum_severity": "warning",
  "rule_groups": ["probes", "storage", "hardware", "bios"],
  "checks": null,
  "fail_on": "warning"
}
```

Produce the deterministic policy report. Exit code `3` means the report was written and the
configured policy threshold triggered:

```powershell
.\.venv\Scripts\rigpilot.exe assess current.json --policy-file rigpilot-policy.json --format json --output assessment.json
```

Use the same snapshot and policy in GitHub Actions:

```yaml
- uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
- uses: Arturo6PR/rigpilot@v1
  with:
    snapshot: current.json
    policy: rigpilot-policy.json
```

The Action creates `rigpilot-assessment.json`, writes a GitHub Step Summary, exposes structured
outputs, and fails the step when the policy triggers. The complete deterministic walkthrough is
in [`examples/github-actions`](examples/github-actions); the stable v1 interfaces and exit codes
are defined in [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md).

## Principles

- Native Windows execution in Warp/PowerShell.
- Read-only diagnostics first.
- Explicit approval before changes to drivers, services, startup, power settings, or hardware configuration.
- Deterministic structured output for scripts and CI policy gates.

## What it does

Each inventory check reports one of three explicit states:

- `success`: the check completed and includes structured data.
- `unavailable`: the required command is not installed or cannot be found.
- `failed`: the command timed out, returned an error, or produced malformed output.

External probes run without a command shell and have a five-second default timeout. The Windows
checks use read-only CIM queries. NVIDIA detection uses `nvidia-smi` when available; its absence
does not stop the rest of the snapshot.

## Development setup

With [uv](https://docs.astral.sh/uv/), install the development environment:

```powershell
uv sync --extra dev
```

The repository also includes `scripts\Enter-RigPilot.ps1` for its configured development
environment. The supported end-user installation path is shown in the quickstart above.

## Usage

Human-readable output:

```powershell
.\.venv\Scripts\python.exe -m rigpilot
```

Structured JSON output:

```powershell
.\.venv\Scripts\python.exe -m rigpilot --json
```

Redact the hostname, volume labels, and Python executable path before sharing:

```powershell
.\.venv\Scripts\python.exe -m rigpilot --json --redact
```

Use `--no-hostname` to emit a schema-compatible `null` hostname. These options change only the
rendered output; they do not mutate the collected snapshot or any workstation setting.

Change the per-command timeout when needed:

```powershell
.\.venv\Scripts\python.exe -m rigpilot --timeout 10
```

Run only selected checks, or skip expensive checks, with comma-separated names:

```powershell
.\.venv\Scripts\python.exe -m rigpilot --only cpu,memory,nvidia_gpu
.\.venv\Scripts\python.exe -m rigpilot --skip physical_disks,memory_modules
```

Excluded checks remain in schema 1.0 as `unavailable` and are marked “Skipped by selection.” Their
PowerShell or external commands are not executed.

Compare two saved JSON snapshots. Collection timestamps and probe durations are treated as noise:

```powershell
.\.venv\Scripts\python.exe -m rigpilot diff before.json after.json
.\.venv\Scripts\python.exe -m rigpilot diff before.json after.json --json
```

Both files are strictly validated against snapshot schema 1.0 before comparison. Hostname changes
are reported without showing either hostname. UTF-8, UTF-8 with BOM, and UTF-16 files with a
little- or big-endian BOM are supported, including output redirected by Windows PowerShell 5.1.

Assess a saved snapshot without collecting new telemetry:

```powershell
.\.venv\Scripts\python.exe -m rigpilot assess current.json
.\.venv\Scripts\python.exe -m rigpilot assess current.json --baseline previous.json
.\.venv\Scripts\python.exe -m rigpilot assess current.json --baseline previous.json --json
.\.venv\Scripts\python.exe -m rigpilot assess current.json --format json
```

Assessment output defaults to `text`. Use `--format text` explicitly when useful, or use
`--format json` for deterministic, versioned automation output. The legacy `--json` option remains
supported and produces the same bytes as `--format json`. The JSON schema depends on the requested
layers: assessment schema 1.0 by default, guidance schema 1.0 with `--guidance`, and policy schema
1.0 with a policy. For example, a clean assessment begins:

```json
{
  "assessment_schema_version": "1.0",
  "snapshot_schema_version": "1.0",
  "subject_collected_at_utc": "2026-08-08T17:00:00+00:00",
  "baseline_collected_at_utc": null,
  "summary": {
    "highest_severity": null,
    "counts": { "info": 0, "warning": 0, "critical": 0 }
  },
  "findings": []
}
```

Write the selected rendering to a new file with `--output`:

```powershell
.\.venv\Scripts\python.exe -m rigpilot assess current.json --format text --output assessment.txt
.\.venv\Scripts\python.exe -m rigpilot assess current.json --format json --output assessment.json
```

RigPilot creates the output as UTF-8 text with a final newline and refuses to overwrite an
existing path. When `--output` succeeds, stdout is empty. Operational diagnostics use stderr, so
JSON written to stdout is never mixed with error text.

Collect and assess one read-only snapshot in memory without writing it to disk:

```powershell
.\.venv\Scripts\python.exe -m rigpilot assess --live
.\.venv\Scripts\python.exe -m rigpilot assess --live --baseline previous.json
.\.venv\Scripts\python.exe -m rigpilot assess --live --timeout 10 --only storage,bios
.\.venv\Scripts\python.exe -m rigpilot assess --live --skip nvidia_gpu --json
```

`--timeout`, `--only`, and `--skip` apply only to live assessment. Live collection happens once,
is strictly validated in memory, and is passed to the same deterministic assessment rules used
for saved snapshots. The collected hostname is omitted before assessment, and neither the raw
snapshot nor sensitive inventory identities are printed. `--baseline` always names a saved
snapshot; checks excluded by `--only` or `--skip` appear as informational skipped findings.

Add deterministic explanations and safe next-step guidance with `--guidance`:

```powershell
.\.venv\Scripts\python.exe -m rigpilot assess current.json --guidance
.\.venv\Scripts\python.exe -m rigpilot assess --live --guidance --json
```

Without `--guidance`, assessment output remains schema 1.0 and keeps its existing shape. With
`--guidance --json`, RigPilot emits a guidance-schema-1.0 report containing the unchanged
assessment and a separate guidance entry for each finding. Guidance uses a static, versioned
catalog: it does not execute commands, delete files, download software, select a BIOS version, or
change workstation settings. It explains the limits of each finding and recommends only review,
verification, planning, or consultation.

Apply an opt-in deterministic policy view to select displayed findings and optionally make the
result usable as a CI decision:

```powershell
.\.venv\Scripts\python.exe -m rigpilot assess current.json --policy
.\.venv\Scripts\python.exe -m rigpilot assess current.json --policy --policy-min-severity warning
.\.venv\Scripts\python.exe -m rigpilot assess current.json --policy --policy-groups storage,bios
.\.venv\Scripts\python.exe -m rigpilot assess current.json --policy --policy-checks storage,bios
.\.venv\Scripts\python.exe -m rigpilot assess current.json --policy --policy-fail-on critical --json
.\.venv\Scripts\python.exe -m rigpilot assess --live --guidance --policy --policy-fail-on warning
```

Store the same selectors in a reusable strict policy configuration:

```json
{
  "policy_config_schema_version": "1.0",
  "minimum_severity": "warning",
  "rule_groups": ["probes", "storage", "bios"],
  "checks": ["storage", "bios"],
  "fail_on": "warning"
}
```

```powershell
.\.venv\Scripts\python.exe -m rigpilot assess current.json --policy-file rigpilot-policy.json --format json
.\.venv\Scripts\python.exe -m rigpilot assess current.json --policy-file rigpilot-policy.json --format json --output assessment.json
```

`--policy-file` accepts UTF-8, UTF-8 with BOM, and BOM-marked UTF-16 JSON. It implies policy
output and cannot be combined with `--policy` or inline `--policy-*` options. The file is strictly
validated against policy-configuration schema 1.0 before a saved snapshot is loaded or live
collection can start.

Policy groups are `probes`, `storage`, `hardware`, and `bios`. Values within a group or check
selector are ORed; severity, group, and check selectors are combined with AND. A minimum severity
includes that severity and more severe findings. Omitted selectors mean all. User order and
duplicates are normalized, while displayed findings retain canonical assessment order.

All `--policy-*` options require `--policy`. `--only` and `--skip` still select which live probes
execute; `--policy-checks` only selects findings after assessment and is never sent to collectors.
Impossible group/check intersections are rejected before input is loaded or live collection can
start. A fail-on threshold cannot be less severe than the display minimum, so a hidden finding
cannot trigger the decision.

Policy JSON uses schema 1.0 and embeds the complete, unchanged assessment or guidance report. Its
view refers to findings by canonical index instead of copying them. Human output always states
the canonical, displayed, and hidden finding counts. Findings alone still return exit code `0`;
`--policy-fail-on` returns `3` only after output is emitted when a displayed finding reaches the
threshold. Invalid arguments or saved inputs return `2`, and unexpected policy failures return
`1` with a concise error. These exit codes are unchanged by `--format` or `--output`; a successful
file write happens before the final policy decision code is returned. The policy layer is pure
and read-only: it does not collect data, execute commands, contact vendors, or change the source
report or workstation.

Assessment reports incomplete probe coverage, low fixed-volume capacity, stable hardware identity
changes, and missing, future, or five-year-old BIOS release dates. Both files are strictly
validated before assessment. Findings use `info`, `warning`, and `critical` severity and avoid
hostnames, volume labels, executable paths, raw probe errors, and hardware identity values.
Saved-snapshot assessment does not execute system probes or contact vendors. Live assessment runs
the same timeout-bounded, read-only probes used by inventory and does not contact vendors.

A fixed volume is `critical` when free space is below both 5% and 10 GiB. It is a `warning` when
free space is below both 10% and 20 GiB; equality at either boundary does not satisfy that
threshold. Zero-sized volumes do not produce capacity findings. A BIOS release date becomes stale
after five complete calendar years. For this calculation, a February 29 anniversary falls on
February 28 in a non-leap year.

The installed console entry point is also named `rigpilot`.

Human-readable output converts memory and storage sizes to binary units such as GiB and TiB.
JSON preserves the source units for automation: Windows memory fields are KiB, storage sizes are
bytes, and `memory_total_mib` from NVIDIA is MiB. CPU data is always an array because Windows can
report more than one physical processor.

JSON snapshots use schema version `1.0` and include the UTC collection timestamp, hostname, and
per-check duration. The schema is published at `docs/snapshot.schema.json`; assessment output has
its own version `1.0` schema at `docs/assessment.schema.json`, and opt-in guidance reports use
`docs/guidance.schema.json`. Opt-in policy reports use `docs/policy.schema.json`, and reusable
policy input uses `docs/policy-config.schema.json`. Hostnames, hardware
serial-like identifiers, filesystem labels, and executable paths can be sensitive; inspect JSON
before sharing it. RigPilot keeps snapshots local unless the user explicitly redirects or uploads
the output.

## GitHub Actions policy gate

RigPilot can apply a saved-snapshot policy as a native GitHub Actions step:

```yaml
name: RigPilot

on:
  pull_request:
  push:

permissions:
  contents: read

jobs:
  rigpilot:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
      - name: Apply RigPilot policy
        id: rigpilot
        uses: Arturo6PR/rigpilot@v1
        with:
          snapshot: current.json
          policy: .rigpilot/rigpilot-policy.json
          report: rigpilot-assessment.json
```

The Action accepts these inputs:

| Input | Required | Default | Purpose |
| --- | --- | --- | --- |
| `snapshot` | yes | — | Saved snapshot JSON inside the checked-out workspace. |
| `policy` | yes | — | Policy-configuration-schema-1.0 JSON inside the workspace. |
| `report` | no | `rigpilot-assessment.json` | New workspace-relative JSON report path. |
| `python-version` | no | `3.12` | Python version used to run RigPilot. |

It exposes `status`, `passed`, `warnings`, `failed`, `critical`, `report`, `exit_code`, and
`summary` outputs. `failed` is the number of canonical findings referenced by the policy
decision; `passed` is a Boolean policy-gate result rather than an invented count of rules that
the assessment report does not claim to have evaluated.

`@v1` follows compatible v1 releases. Use `@v1.0.0` to select the exact first stable release, or
pin the verified full release commit SHA when your workflow requires an immutable reference.

The Action uses the unchanged policy-schema-1.0 report from v0.8.0 as its source of truth. It
writes the complete deterministic JSON report before returning the policy decision, adds a
compact GitHub Step Summary with counts and policy-triggering rule IDs, and keeps the report in
the workspace for downstream parsing or an optional official artifact-upload step. A successful
gate returns `0`; a triggered policy returns `3` and fails the step after its report and summary
are written. Input/configuration errors return `2`, and unexpected internal failures return `1`.

Inputs are passed through environment variables and Python argument arrays rather than shell
interpolation. Snapshot, policy, and report paths must remain inside `GITHUB_WORKSPACE`; the
report parent must already exist, and RigPilot refuses to overwrite an existing path. The Action
does not require user-provided secrets or broader token permissions, collect runner telemetry,
contact a RigPilot service, or change the runner. The caller only needs `contents: read` for
checkout and the official Python setup step.

The local equivalent is:

```powershell
rigpilot assess current.json --policy-file .rigpilot/rigpilot-policy.json --format json --output rigpilot-assessment.json
```

See [`examples/github-actions`](examples/github-actions) for a copyable workflow, policy, and
snapshot-origin guidance.

## Stable v1 contracts and exit codes

RigPilot v1 treats its documented CLI commands/options, exit codes, schema-1.0 files, and GitHub
Action inputs/outputs as public compatibility contracts. Existing v0.7-era policy files, v0.8
structured reports, and v0.9 workflows require no migration.

| Exit code | Meaning |
| ---: | --- |
| `0` | The operation completed; findings alone do not fail an assessment. |
| `1` | An unexpected operational or internal error prevented completion. |
| `2` | Arguments, inputs, paths, encodings, JSON, or policy configuration were invalid. |
| `3` | A policy report was emitted and its configured `fail_on` threshold triggered. |

See [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md) for the authoritative contract, exact option
and schema lists, deterministic report invariants, and privacy boundary.

## Project references

- [Stable v1 compatibility contract](docs/COMPATIBILITY.md)
- [Canonical end-to-end GitHub Actions example](examples/github-actions)
- [Changelog](CHANGELOG.md) and versioned [release notes](docs)
- [Security reporting guidance](SECURITY.md)

## Development checks

Run the standard-library unit tests, Ruff, and package import check:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-RigPilot.ps1
```

Tests cover parsers, missing commands, invalid and expired timeouts, operating-system errors,
nonzero exits, malformed output, multiple CPUs and GPUs, safe command construction, snapshot
assembly, collector selection, snapshot comparison, deterministic assessment rules, privacy,
schema validation, deterministic guidance and policy views, policy decisions, and output modes.
The suite also verifies the GitHub Action summary, outputs, path isolation, error distinctions,
and pass, warning, and fail policy behavior against deterministic fixtures.

## Current limitations

- Windows 11 and PowerShell are the primary supported environment.
- Disk `Status` is the value exposed by Windows CIM, not a complete SMART health assessment.
- The snapshot is local and point-in-time; RigPilot does not send telemetry anywhere.
- Inventory only reports information. It does not optimize settings or modify drivers, firmware,
  the registry, services, startup items, or power plans.
