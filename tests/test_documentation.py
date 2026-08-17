from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]


def _local_markdown_links(path: Path) -> list[Path]:
    text = path.read_text(encoding="utf-8")
    links: list[Path] = []
    for target in re.findall(r"(?<!!)\[[^]]+\]\(([^)]+)\)", text):
        clean_target = target.split("#", 1)[0]
        if not clean_target or "://" in clean_target or clean_target.startswith("mailto:"):
            continue
        links.append((path.parent / clean_target).resolve())
    return links


class DocumentationPresentationTests(unittest.TestCase):
    def test_readme_presents_proof_architecture_action_and_project_map(self) -> None:
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("actions/workflows/ci.yml/badge.svg", readme)
        self.assertIn("license-Apache--2.0", readme)
        self.assertLess(
            readme.index("## Five-minute quickstart"), readme.index("## How it fits together")
        )
        self.assertIn("```mermaid", readme)
        self.assertIn("Arturo6PR/rigpilot@v1", readme)
        self.assertIn("examples\\github-actions\\Run-Demo.ps1", readme)
        self.assertIn("## Repository map", readme)
        self.assertIn("## License", readme)

    def test_all_repository_documentation_links_resolve(self) -> None:
        markdown_files = [
            PROJECT_ROOT / "README.md",
            PROJECT_ROOT / "CHANGELOG.md",
            PROJECT_ROOT / "SECURITY.md",
            *sorted((PROJECT_ROOT / "docs").glob("*.md")),
            PROJECT_ROOT / "examples" / "github-actions" / "README.md",
        ]

        for markdown_file in markdown_files:
            for target in _local_markdown_links(markdown_file):
                with self.subTest(source=markdown_file.name, target=target):
                    self.assertTrue(target.exists(), f"broken local link: {target}")

    def test_demo_is_deterministic_fixture_only_and_runs_in_ci(self) -> None:
        script = (PROJECT_ROOT / "examples" / "github-actions" / "Run-Demo.ps1").read_text(
            encoding="utf-8"
        )
        workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        self.assertNotIn("--live", script)
        self.assertNotIn("--redact", script)
        self.assertNotIn("Get-ChildItem Env", script)
        self.assertIn("byte-for-byte identical", script)
        self.assertTrue(script.rstrip().endswith("exit 0"))
        self.assertIn("Run-Demo.ps1 -Python python", workflow)
        for name in (
            "current.json",
            "failing-current.json",
            "rigpilot-policy.json",
            "expected-report.json",
        ):
            self.assertTrue((PROJECT_ROOT / "examples" / "github-actions" / name).is_file())

    def test_copyable_workflow_uses_stable_action_and_safe_output_interpolation(self) -> None:
        workflow = (PROJECT_ROOT / "examples" / "github-actions" / "workflow.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("uses: Arturo6PR/rigpilot@v1", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("RIGPILOT_STATUS: ${{ steps.rigpilot.outputs.status }}", workflow)
        run_blocks = re.findall(r"(?m)^        run: \|\n((?:          .*\n?)*)", workflow)
        self.assertTrue(run_blocks)
        for run_block in run_blocks:
            self.assertNotIn("${{", run_block, "Action outputs must not be inlined in shell")


if __name__ == "__main__":
    unittest.main()
