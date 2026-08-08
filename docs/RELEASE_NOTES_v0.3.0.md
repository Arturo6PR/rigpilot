# RigPilot v0.3.0

RigPilot v0.3.0 adds deterministic, privacy-safe assessment of saved workstation snapshots while
preserving the project's read-only behavior.

## Highlights

- Assess a saved snapshot with `rigpilot assess`, optionally comparing stable hardware identity
  with a saved baseline. Assessment never performs live collection or contacts a vendor.
- Report unavailable and failed probes, low fixed-volume capacity, stable hardware changes, and
  missing, future, or stale BIOS release dates with `info`, `warning`, or `critical` severity.
- Apply deterministic disk thresholds using integer comparisons. Critical capacity is below both
  5% and 10 GiB free; warning capacity is below both 10% and 20 GiB free. Equality does not cross
  a threshold, and zero-sized volumes do not produce capacity findings.
- Treat a BIOS release date as stale after five complete calendar years. A February 29
  anniversary falls on February 28 in a non-leap year.
- Normalize stable hardware identities for case and surrounding whitespace and compare component
  multisets without depending on collection order.
- Validate snapshots and assessment results strictly against versioned Draft 2020-12 JSON
  schemas, including semantic checks for severity counts and highest severity.

## Privacy and safety

Assessment output does not expose hostnames, volume labels, executable paths, raw probe errors,
or CPU, GPU, disk, and memory-module identity values. Hardware-change findings report only
component counts. Assessment is pure and deterministic: it reads saved snapshots without
mutating them, running system commands, modifying the workstation, or uploading telemetry.

## Compatibility

- Windows 11 and PowerShell remain the primary supported environment.
- Python 3.11 or newer is required.
- Snapshot and assessment outputs each retain schema version 1.0.
- Saved snapshots encoded as UTF-8, UTF-8 with a BOM, or UTF-16 with a little- or big-endian BOM
  are supported, including Windows PowerShell 5.1 redirected output.
- Both snapshot and assessment schemas are included in installed wheels.
