# RigPilot GitHub Actions example

This example applies a saved-snapshot policy gate without collecting live runner telemetry.

1. Create a privacy-conscious snapshot on the workstation you intend to evaluate:

   ```powershell
   rigpilot --json --no-hostname > current.json
   ```

2. Copy `rigpilot-policy.json` to `.rigpilot/rigpilot-policy.json` in the repository and review
   its selectors. The example fails on displayed warning or critical findings.
3. Copy `workflow.yml` to `.github/workflows/rigpilot.yml`.
4. Commit or otherwise provide `current.json` in the workflow workspace. Treat source snapshots
   as potentially sensitive even though assessment findings are privacy constrained.

The Action writes `rigpilot-assessment.json`, adds a concise GitHub Step Summary, exposes policy
status and counts as step outputs, and returns RigPilot's policy exit code. Exit code `3` fails
the policy step after the report and summary are produced; exit codes `1` and `2` identify
internal and input/configuration errors.

The equivalent local command is:

```powershell
rigpilot assess current.json --policy-file .rigpilot/rigpilot-policy.json --format json --output rigpilot-assessment.json
```
