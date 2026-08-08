---
name: system-snapshot
description: Extend or verify RigPilot's read-only Windows workstation inventory safely.
---

# RigPilot System Snapshot

1. Read the root `AGENTS.md` and current project brief.
2. Keep every system probe read-only, isolated behind a small wrapper, and bounded by a timeout.
3. Represent successful, unavailable, and failed checks distinctly.
4. Do not change drivers, firmware, registry, services, startup, power settings, or files outside the repository.
5. Add standard-library unit tests for parsers and error paths before adding dependencies.
6. Run `scripts\Test-RigPilot.ps1` and report the exact result.
