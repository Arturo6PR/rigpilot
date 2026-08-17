# RigPilot verification

RigPilot provides executable evidence instead of a checked-in screenshot that can become stale.
The same deterministic demo runs locally and in the repository's required CI workflow.

## One-command product proof

After installing the package from the repository:

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

The script validates, rather than merely prints, that:

- a clean synthetic snapshot produces exit `0`;
- its policy report semantically matches `expected-report.json`;
- two executions produce byte-for-byte identical report files;
- a synthetic failed-probe snapshot produces a schema-1.0 report before exit `3`;
- output-file mode leaves stdout and stderr empty for completed policy decisions; and
- all temporary reports are removed and no live probe runs.

## Complete local checks

Install development dependencies, then run the repository entry point:

```powershell
uv sync --extra dev
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-RigPilot.ps1
```

The suite covers collectors through mocked process boundaries, strict schema validation, ten
golden fixtures, assessment boundaries, deterministic guidance and policy views, privacy,
packaged-schema loading, CLI compatibility, and GitHub Action behavior.

The individual checks are also reproducible:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
uv lock --check
git diff --check
```

## CI evidence

The [required CI workflow](https://github.com/Arturo6PR/rigpilot/actions/workflows/ci.yml) runs:

- Python 3.11, 3.12, and 3.13 on Windows;
- Windows PowerShell 5.1 and PowerShell 7 for every Python version;
- the composite GitHub Action on Ubuntu with passing, warning, failing, and invalid inputs; and
- the deterministic documentation demo above.

The v1 release was independently exercised from its published tag in the
[released-Action smoke workflow](https://github.com/Arturo6PR/rigpilot/actions/workflows/released-action-smoke.yml).
That workflow tests both `@v1.0.0` and `@v1` against controlled repository fixtures without live
collection.

## What is and is not proved

Tests and CI prove the documented deterministic transformation and integration behavior. Windows
collectors are tested through isolated, mockable process wrappers and the Windows matrix. The
demo intentionally does not claim that it inspected the current workstation. Run live inventory
only when you explicitly intend to collect and inspect that machine's local state.
