# RigPilot v0.1.0

RigPilot v0.1.0 establishes a trustworthy, read-only Windows workstation inventory CLI.

## Highlights

- Collects operating system, CPU, memory, storage, system, BIOS, physical memory, physical disks,
  uptime, Python, Git, and optional NVIDIA GPU information.
- Emits readable terminal output or schema-versioned JSON.
- Reports successful, unavailable, and failed probes independently.
- Runs external probes without a shell and with configurable finite timeouts.
- Includes optional GPU utilization and temperature when supported by `nvidia-smi`.
- Provides `--redact` and `--no-hostname` controls for safer snapshot sharing.

## Privacy and safety

RigPilot does not upload telemetry and does not modify drivers, firmware, services, registry,
startup entries, files outside the repository, or power settings. JSON output can contain a
hostname, volume labels, local executable paths, and hardware details; use `--redact` before
sharing and inspect the result.

## Compatibility

- Windows 11 and PowerShell are the primary supported environment.
- Python 3.11 or newer is required.
- JSON output conforms to RigPilot snapshot schema version 1.0.
