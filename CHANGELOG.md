# Changelog

All notable changes to RigPilot will be documented in this file. The project follows Semantic
Versioning, and dates use ISO 8601.

## [Unreleased]

## [1.0.0] - 2026-08-17

### Added

- An explicit v1 public compatibility contract covering CLI commands and options, exit codes,
  all schema-1.0 formats, and the GitHub Action input/output and failure interface.
- A package-backed `rigpilot --version` command, five-minute quickstart, canonical deterministic
  snapshot-to-CI example, and security reporting guidance.
- Behavioral compatibility tests for pre-v1 policy files, v0.8 structured reports, v0.9 Action
  workflows, deterministic output, and exact public interface names.

### Changed

- Package metadata now derives its version from the package's single authoritative version
  source and includes README and project links.
- GitHub Action documentation uses the compatible `v1` major alias while retaining an exact
  `v1.0.0` option and immutable commit-SHA guidance.

## [0.9.0] - 2026-08-17

### Added

- Native composite GitHub Action for saved-snapshot policy gates, including deterministic JSON
  reports, GitHub Step Summaries, structured outputs, and exact policy exit propagation.
- Deterministic CI dogfood and a manual released-tag smoke workflow covering passing, warning,
  and failing policy behavior without live collection.

## [0.8.0] - 2026-08-17

### Added

- Deterministic `--format text|json` assessment rendering and safe `--output` file delivery for
  scripts and CI systems, while preserving legacy output and exit codes.
- Strict reusable policy configuration files through `--policy-file`, with schema validation
  before snapshot loading or live collection.

## [0.6.0] - 2026-08-09

### Added

- Opt-in deterministic policy views and fail-on decisions for assessment findings, with strict
  schema validation, canonical source preservation, and separate severity, group, and check
  selectors.

## [0.5.0] - 2026-08-09

### Added

- Opt-in deterministic guidance for assessment findings, with a separately versioned strict
  schema and static privacy-safe next-step catalog.

## [0.4.0] - 2026-08-09

### Added

- In-memory read-only assessment with `rigpilot assess --live`, including timeout and collector
  selection controls.

## [0.3.0] - 2026-08-08

### Added

- Deterministic, privacy-safe assessment of saved snapshots with probe coverage, disk capacity,
  hardware-change, and BIOS-age findings.
- Versioned assessment schema with human-readable and JSON output.

## [0.2.0] - 2026-08-08

### Added

- Selective inventory through `--only` and `--skip` without executing excluded probes.
- Read-only comparison of saved schema-1.0 snapshots with `rigpilot diff`.
- Strict pre-comparison validation, privacy-safe hostname change reporting, and PowerShell 5.1
  UTF-16 snapshot support.
- Windows CI coverage across Python 3.11-3.13 and Windows PowerShell 5.1/PowerShell 7.

## [0.1.0] - 2026-08-08

### Added

- Read-only Windows inventory for the operating system, CPU, memory, storage, system model, BIOS,
  physical memory modules, physical disks, uptime, Python, Git, and NVIDIA GPUs.
- Human-readable and JSON output with explicit success, unavailable, and failed states.
- Shell-free, timeout-bounded external command execution.
- Schema version 1.0 metadata and per-check durations.
- Windows GitHub Actions CI, parser/error tests, and Draft 2020-12 schema validation.
- Strict per-check JSON Schema definitions for schema version 1.0.
- `--redact` and `--no-hostname` privacy controls.
- Golden success and failure snapshot fixtures for compatibility testing.

[Unreleased]: https://github.com/Arturo6PR/rigpilot/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Arturo6PR/rigpilot/compare/v0.9.0...v1.0.0
[0.9.0]: https://github.com/Arturo6PR/rigpilot/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/Arturo6PR/rigpilot/compare/v0.6.0...v0.8.0
[0.6.0]: https://github.com/Arturo6PR/rigpilot/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Arturo6PR/rigpilot/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Arturo6PR/rigpilot/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Arturo6PR/rigpilot/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Arturo6PR/rigpilot/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Arturo6PR/rigpilot/releases/tag/v0.1.0
