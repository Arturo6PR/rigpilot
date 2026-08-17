# RigPilot v1.0.0

RigPilot v1.0.0 is the first stable release of its read-only workstation inventory, deterministic
assessment, policy-as-code, structured reporting, and GitHub Actions policy-gate workflow. This
is a stabilization release: it preserves the established behavior while documenting and testing
the interfaces that automation can rely on throughout the v1 series.

## Stable public contracts

- The `rigpilot`, `rigpilot diff`, and `rigpilot assess` commands retain their established names,
  options, default text behavior, clean machine-readable stdout, and concise stderr errors.
- Exit codes are locked: `0` for completion, `1` for an internal/operational failure, `2` for
  invalid arguments or inputs, and `3` after a successfully emitted policy report triggers its
  configured threshold.
- Snapshot, assessment, guidance, policy-report, and policy-configuration schemas remain strict
  Draft 2020-12 schema version 1.0.
- GitHub Action inputs, outputs, report behavior, Step Summary, and policy failure semantics remain
  compatible with v0.9 workflows.

## Onboarding and automation

- `rigpilot --version` reports the package version from the authoritative package source.
- A five-minute quickstart covers installation, snapshot collection, saved assessment, reusable
  policy configuration, deterministic JSON, and GitHub Actions.
- A canonical synthetic example connects a snapshot, policy, assessment, structured report, CI
  decision, and Step Summary without machine-specific live data.
- `Arturo6PR/rigpilot@v1` provides the compatible v1 Action line; `@v1.0.0` selects this exact
  release, and a verified full commit SHA remains the immutable-reference option.

## Compatibility and safety

No migration is required from v0.9.0. Existing reusable policy files, schema-1.0 structured
reports, CLI scripts, and GitHub Action inputs and outputs retain their behavior. The Action still
invokes RigPilot's real CLI, validates the policy report, writes the report and Step Summary before
propagating a policy failure, and does not duplicate assessment or policy logic.

This release does not change collectors, assessment rules or thresholds, guidance catalog text,
policy semantics, or any JSON schema. RigPilot remains local and read-only: it sends no telemetry,
uses no RigPilot cloud service, performs no live collection in the Action, and does not modify
drivers, firmware, registry, services, startup, power settings, or workstation configuration.
