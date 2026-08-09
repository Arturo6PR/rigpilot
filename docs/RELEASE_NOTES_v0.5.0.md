# RigPilot v0.5.0

RigPilot v0.5.0 adds opt-in, deterministic guidance for assessment findings while preserving the
existing read-only inventory and assessment behavior.

## Highlights

- Add safe explanations and next steps to saved or live assessments with `--guidance`.
- Keep default human and JSON assessment output unchanged when guidance is not requested.
- Emit a separately versioned guidance-schema-1.0 envelope with `--guidance --json`; the nested
  assessment remains an unchanged assessment-schema-1.0 object.
- Cover every assessment rule with a static catalog of review, verification, planning, or
  consultation actions.
- Validate guidance against both Draft 2020-12 JSON Schema and cross-object invariants, including
  finding indexes, rule IDs, ordering, completeness, and exact catalog wording.
- Package snapshot, assessment, and guidance schemas in installed wheels.

## Determinism and privacy

Guidance is generated only from a validated assessment and a fixed catalog. It does not inspect
the workstation, access the network, generate dynamic prose, create findings, or change finding
severity. Identical assessments therefore produce identical guidance in deterministic finding
order.

Guidance does not copy hostnames, volume labels, file or executable paths, raw probe messages,
hardware identities, BIOS versions, snapshot filenames, or before-and-after inventory values. It
avoids diagnostic claims and does not instruct users to run commands, delete files, download
software, choose firmware versions, or modify drivers, the registry, services, startup items, or
power settings.

## Errors and compatibility

Guidance construction, validation, serialization, and rendering failures return concise,
privacy-safe errors without exception details. Keyboard interrupts and process exits continue to
propagate normally. Findings and successfully generated guidance retain exit code 0.

- Windows 11 and PowerShell remain the primary supported environment.
- Python 3.11 or newer is required.
- Snapshot, assessment, and guidance schemas are independently versioned at 1.0.
- Saved snapshots retain UTF-8 and PowerShell 5.1 UTF-16/BOM input support.
- Live guidance retains timeout, selective collection, baseline validation, and exactly-once
  collection behavior.
- Inventory and assessment remain read-only and do not change workstation settings.
