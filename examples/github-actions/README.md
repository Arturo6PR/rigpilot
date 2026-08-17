# Deterministic GitHub Actions example

This repository-owned example demonstrates RigPilot's complete saved-snapshot CI path without
collecting data from the workstation or CI runner:

```text
Synthetic snapshot -> strict validation -> assessment -> policy -> JSON report -> CI exit
                                                        |
                                                        +-> Step Summary and Action outputs
```

## Files

| File | Purpose |
| --- | --- |
| `current.json` | Clean, synthetic snapshot that passes the policy. |
| `failing-current.json` | Synthetic failed-probe snapshot that triggers the policy. |
| `rigpilot-policy.json` | Reusable policy-config-schema-1.0 input. |
| `expected-report.json` | Exact policy-schema-1.0 report for the clean snapshot. |
| `Run-Demo.ps1` | Self-checking local proof for both policy outcomes and deterministic JSON. |
| `workflow.yml` | Copyable workflow using `Arturo6PR/rigpilot@v1`. |

All inventory values are deliberately synthetic. They are evidence for the software path, not a
claim about the machine running the example.

## Run locally

From the repository root after installing RigPilot:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\examples\github-actions\Run-Demo.ps1 -Python .\.venv\Scripts\python.exe
```

Expected output:

```text
RigPilot deterministic CI demo: PASS
Version: rigpilot 1.0.0
Passing policy: exit 0, policy schema 1.0
Failing policy: exit 3, 12 triggering findings, report emitted
Repeated JSON report: byte-for-byte identical
Live collection: not performed
```

The script writes only to a unique system temporary directory. It asserts that completed
output-file operations leave stdout and stderr empty, validates both exit decisions, compares
the clean result with `expected-report.json`, proves repeat output is byte-identical, and removes
the temporary directory.

The equivalent clean command is:

```powershell
rigpilot assess examples\github-actions\current.json --policy-file examples\github-actions\rigpilot-policy.json --format json --output rigpilot-assessment.json
```

RigPilot refuses to overwrite the report. Delete it before running that individual command again.

## Use in GitHub Actions

Copy `workflow.yml` to `.github/workflows/rigpilot.yml`, keeping the example files or updating the
paths to repository-owned equivalents. The important step is:

```yaml
- name: Apply RigPilot policy
  id: rigpilot
  uses: Arturo6PR/rigpilot@v1
  with:
    snapshot: examples/github-actions/current.json
    policy: examples/github-actions/rigpilot-policy.json
    report: rigpilot-assessment.json
```

The Action preserves the JSON report, adds a GitHub Step Summary, and exposes its status and
counts. A clean policy returns `0`. A triggered policy returns `3` and fails the step only after
the report, outputs, and summary have been produced. Operational errors return `1`; invalid
arguments, paths, snapshots, or policy input return `2`.

For a real workstation, create a privacy-conscious snapshot locally on Windows:

```powershell
rigpilot --json --no-hostname > current.json
```

Inspect it before committing or uploading it. Source snapshots can contain hardware identities,
volume labels, and executable paths even though later assessment findings are privacy constrained.
