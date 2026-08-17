# RigPilot GitHub Actions example

This canonical v1 example connects a deterministic saved snapshot to a reusable policy,
structured report, CI decision, and GitHub Step Summary without collecting live runner telemetry.

1. Inspect the included synthetic `current.json`. For a real workstation, create a
   privacy-conscious replacement locally:

   ```powershell
   rigpilot --json --no-hostname > current.json
   ```

2. Review `rigpilot-policy.json`. The example fails on displayed warning or critical findings.
3. From the repository root, run the local command below. With the included clean snapshot it
   returns `0` and reproduces `expected-report.json` exactly.
4. Copy `workflow.yml` to `.github/workflows/rigpilot.yml`. Its inputs reference the files in this
   example directory; update them if you store a real snapshot or policy elsewhere. Treat real
   source snapshots as potentially sensitive even though assessment findings are privacy
   constrained.

The Action writes `rigpilot-assessment.json`, adds a concise GitHub Step Summary, exposes policy
status and counts as step outputs, and returns RigPilot's policy exit code. Exit code `3` fails
the policy step after the report and summary are produced; exit codes `1` and `2` identify
internal and input/configuration errors.

The equivalent local command is:

```powershell
rigpilot assess examples/github-actions/current.json --policy-file examples/github-actions/rigpilot-policy.json --format json --output rigpilot-assessment.json
```

The report embeds assessment schema 1.0, applies policy schema 1.0, and remains available for
downstream parsing. A displayed warning or critical finding triggers this policy and returns `3`
only after the report and summary have been produced.
