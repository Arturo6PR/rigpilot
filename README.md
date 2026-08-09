# RigPilot

RigPilot is a Windows-first workstation intelligence assistant. It provides a safe, read-only
system inventory covering the operating system, system model, BIOS, CPU, physical memory,
logical and physical storage, uptime, Python, Git, and NVIDIA GPUs.

## Principles

- Native Windows execution in Warp/PowerShell.
- Read-only diagnostics first.
- Explicit approval before changes to drivers, services, startup, power settings, or hardware configuration.
- Structured output suitable for future automation.

## What it does

Each inventory check reports one of three explicit states:

- `success`: the check completed and includes structured data.
- `unavailable`: the required command is not installed or cannot be found.
- `failed`: the command timed out, returned an error, or produced malformed output.

External probes run without a command shell and have a five-second default timeout. The Windows
checks use read-only CIM queries. NVIDIA detection uses `nvidia-smi` when available; its absence
does not stop the rest of the snapshot.

## Setup

RigPilot requires Python 3.11 or newer. With [uv](https://docs.astral.sh/uv/):

```powershell
uv sync --extra dev
```

The repository also includes `scripts\Enter-RigPilot.ps1` for its configured local environment.

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
```

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
`docs/guidance.schema.json`. Hostnames, hardware
serial-like identifiers, filesystem labels, and executable paths can be sensitive; inspect JSON
before sharing it. RigPilot keeps snapshots local unless the user explicitly redirects or uploads
the output.

## Development checks

Run the standard-library unit tests, Ruff, and package import check:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-RigPilot.ps1
```

Tests cover parsers, missing commands, invalid and expired timeouts, operating-system errors,
nonzero exits, malformed output, multiple CPUs and GPUs, safe command construction, snapshot
assembly, collector selection, snapshot comparison, deterministic assessment rules, privacy,
schema validation, and output modes.

## Current limitations

- Windows 11 and PowerShell are the primary supported environment.
- Disk `Status` is the value exposed by Windows CIM, not a complete SMART health assessment.
- The snapshot is local and point-in-time; RigPilot does not send telemetry anywhere.
- Inventory only reports information. It does not optimize settings or modify drivers, firmware,
  the registry, services, startup items, or power plans.
