# RigPilot project brief

## Purpose

Help the user understand and eventually optimize a Windows AI workstation through transparent, safe diagnostics.

## First milestone

A tested, read-only CLI system snapshot with human-readable and JSON output.

## Non-goals for milestone one

- Automatic optimization
- Driver or firmware changes
- Registry, service, startup, or power-plan changes
- Remote telemetry or cloud accounts

## Success criteria

- Works from PowerShell in Warp.
- Missing NVIDIA tooling does not crash the program.
- Output distinguishes known, unavailable, and failed checks.
- Unit tests cover parsing and failure paths.

## Current implementation

The first milestone is implemented as a Python CLI with human-readable and JSON output. Every
probe is independently marked as successful, unavailable, or failed. External commands are
shell-free and bounded by a configurable timeout, and NVIDIA tooling is optional.
Schema version 1.0 adds collection metadata, per-check durations, hardware identity, BIOS,
physical memory, physical disks, uptime, and optional live NVIDIA utilization and temperature.
