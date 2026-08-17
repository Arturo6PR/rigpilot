# RigPilot CLI reference

The installed entry point is `rigpilot`; `python -m rigpilot` is equivalent. Text is the default
unless a command explicitly requests JSON.

## Install and inspect

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\rigpilot.exe --version
.\.venv\Scripts\rigpilot.exe --help
```

RigPilot supports Python 3.11-3.13. The development environment uses `uv sync --extra dev`.

## Inventory

Collect a human-readable snapshot or schema-1.0 JSON:

```powershell
rigpilot
rigpilot --json
rigpilot --json --no-hostname
rigpilot --json --redact
rigpilot --timeout 10
rigpilot --only cpu,memory,nvidia_gpu
rigpilot --skip physical_disks,memory_modules
```

Valid check names are `operating_system`, `cpu`, `memory`, `storage`, `python`, `git`,
`nvidia_gpu`, `system`, `bios`, `memory_modules`, `physical_disks`, and `uptime`. Excluded checks
remain schema-compatible `unavailable` entries and their commands do not run.

`--no-hostname` records `null`. `--redact` also removes volume labels and the Python executable
path from rendered output. Neither option mutates the collected object or workstation.

## Compare saved snapshots

```powershell
rigpilot diff before.json after.json
rigpilot diff before.json after.json --json
```

Both files are strictly validated first. Collection timestamps and probe durations are ignored.
Hostname changes are reported without showing either hostname. UTF-8, UTF-8 BOM, and UTF-16 with
a little- or big-endian BOM are supported, including Windows PowerShell 5.1 redirected output.

## Assess a saved snapshot

```powershell
rigpilot assess current.json
rigpilot assess current.json --baseline previous.json
rigpilot assess current.json --format text
rigpilot assess current.json --format json
rigpilot assess current.json --json
```

`--json` is the byte-compatible legacy spelling of `--format json`. The current and optional
baseline snapshots are strictly validated before assessment. Saved assessment never executes a
probe or contacts a vendor.

Write the selected rendering to a new file:

```powershell
rigpilot assess current.json --format text --output assessment.txt
rigpilot assess current.json --format json --output assessment.json
```

Output is UTF-8 with one final newline. RigPilot refuses to overwrite a path, requires its parent
to exist, and leaves stdout empty after a successful write. Errors use stderr, so stdout JSON is
never mixed with diagnostic prose.

## Assess one live snapshot

Live assessment is an explicit read-only collection followed by the saved-snapshot pipeline:

```powershell
rigpilot assess --live
rigpilot assess --live --baseline previous.json
rigpilot assess --live --timeout 10 --only storage,bios
rigpilot assess --live --skip nvidia_gpu --format json
```

`--timeout`, `--only`, and `--skip` apply only in live mode. Collection happens exactly once in
memory, the hostname is omitted, and the result is strictly validated before assessment. An
invalid baseline prevents collection. The raw snapshot is not written unless the user separately
runs inventory and redirects it.

## Assessment rules

Assessment covers:

- selected checks skipped (`info`), optional NVIDIA unavailable (`info`), other unavailable
  probes (`warning`), and failed probes (`warning`);
- fixed-volume free capacity below both 10% and 20 GiB (`warning`), or below both 5% and 10 GiB
  (`critical`); equality at either boundary does not match and zero-sized volumes are ignored;
- normalized stable hardware identity multiset changes (`warning`) without exposing identities;
- missing BIOS date (`info`), future BIOS date (`warning`), and at least five complete calendar
  years old (`warning`). A February 29 anniversary is February 28 in a non-leap year.

Findings exclude hostnames, volume labels, executable paths, raw probe errors, and hardware
identity values.

## Optional guidance

```powershell
rigpilot assess current.json --guidance
rigpilot assess current.json --guidance --format json
```

Guidance schema 1.0 wraps the complete unchanged assessment and adds one static catalog entry per
finding. Guidance may recommend review, verification, planning, or consultation. It never runs a
command, deletes a file, downloads software, chooses a BIOS version, or changes a setting.

## Inline policy

```powershell
rigpilot assess current.json --policy
rigpilot assess current.json --policy --policy-min-severity warning
rigpilot assess current.json --policy --policy-groups storage,bios
rigpilot assess current.json --policy --policy-checks storage,bios
rigpilot assess current.json --policy --policy-fail-on critical --format json
```

All `--policy-*` options require `--policy`. Policy groups are `probes`, `storage`, `hardware`,
and `bios`. Values inside a group/check selector are ORed; severity, group, and check selectors
combine with AND. Displayed findings retain canonical assessment order.

Impossible group/check intersections fail before a snapshot is loaded or live collection runs.
A `fail_on` threshold cannot be less severe than the display minimum, preventing a hidden finding
from triggering a decision.

## Reusable policy file

Policy configuration schema 1.0 requires all five fields:

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
rigpilot assess current.json --policy-file rigpilot-policy.json --format json
rigpilot assess current.json --policy-file rigpilot-policy.json --format json --output assessment.json
```

`--policy-file` implies policy output and cannot be combined with `--policy` or inline policy
options. It supports the same UTF-8/UTF-16 encodings as snapshots and is validated before a saved
snapshot is loaded or live collection starts. `null` selectors mean all; `fail_on: null` disables
policy failure.

Policy schema 1.0 embeds the complete assessment or guidance report. Its view uses canonical
finding indices and never alters or duplicates source findings.

## JSON contracts

| Output | Version field | Schema |
| --- | --- | --- |
| Inventory snapshot | `schema_version` | [`snapshot.schema.json`](snapshot.schema.json) |
| Assessment | `assessment_schema_version` | [`assessment.schema.json`](assessment.schema.json) |
| Guidance | `guidance_schema_version` | [`guidance.schema.json`](guidance.schema.json) |
| Policy report | `policy_schema_version` | [`policy.schema.json`](policy.schema.json) |
| Policy input | `policy_config_schema_version` | [`policy-config.schema.json`](policy-config.schema.json) |

Each current schema version is `1.0`, uses JSON Schema Draft 2020-12, and rejects unknown fields.
JSON snapshot memory values from Windows are KiB, storage is bytes, NVIDIA `memory_total_mib` is
MiB, and CPU data is always an array.

## Exit codes

| Code | Meaning |
| ---: | --- |
| `0` | Completed successfully; assessment findings alone do not fail. |
| `1` | Unexpected operational or internal failure. |
| `2` | Invalid arguments, file, path, encoding, JSON, schema, or policy configuration. |
| `3` | Policy report emitted and configured threshold triggered. |

Formats and output destinations do not change these values. See the
[v1 compatibility contract](COMPATIBILITY.md) for the stable public surface.
