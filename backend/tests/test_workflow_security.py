import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _shell_run_blocks(workflow: str) -> list[str]:
    blocks: list[str] = []
    active_lines: list[str] | None = None
    run_indent = 0
    for line in workflow.splitlines():
        if re.match(r"^\s*run:\s*\|\s*$", line):
            active_lines = []
            run_indent = len(line) - len(line.lstrip())
            continue
        if active_lines is not None:
            indent = len(line) - len(line.lstrip())
            if line.strip() and indent <= run_indent:
                blocks.append("\n".join(active_lines))
                active_lines = None
            else:
                active_lines.append(line)
    if active_lines is not None:
        blocks.append("\n".join(active_lines))
    return blocks


class TestWorkflowSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scanner_workflow = (ROOT / ".github" / "workflows" / "scanner.yml").read_text(
            encoding="utf-8"
        )
        cls.ci_workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

    def test_scanner_inputs_are_environment_values_not_shell_source(self) -> None:
        self.assertNotIn("github.event.inputs.", self.scanner_workflow)
        self.assertIn("SCANNER_FORCE_DAYS: ${{ inputs.force_days }}", self.scanner_workflow)
        self.assertIn("SCANNER_AUDIT_DAYS: ${{ inputs.audit_days }}", self.scanner_workflow)
        self.assertIn("SCANNER_MODE: ${{ inputs.mode }}", self.scanner_workflow)
        self.assertIn("SCANNER_PROPOSAL_ID: ${{ inputs.proposal_id }}", self.scanner_workflow)
        self.assertIn("SCANNER_REJECT_PROPOSAL: ${{ inputs.reject_proposal }}", self.scanner_workflow)
        for block in _shell_run_blocks(self.scanner_workflow):
            self.assertNotIn("${{", block)

    def test_scanner_validates_inputs_and_uses_a_shell_array(self) -> None:
        self.assertIn("[[ \"$force_days\" =~ ^[0-9]+$ ]]", self.scanner_workflow)
        self.assertIn("[[ \"$audit_days\" =~ ^[0-9]+$ ]]", self.scanner_workflow)
        self.assertIn("[[ \"$proposal_id\" =~ ^[a-zA-Z0-9_-]+$ ]]", self.scanner_workflow)
        self.assertIn("case \"$mode\"", self.scanner_workflow)
        self.assertIn("scanner_args=(", self.scanner_workflow)
        self.assertIn('python -m movies_feed.cli "${scanner_args[@]}"', self.scanner_workflow)
        self.assertNotIn("EXTRA_ARGS", self.scanner_workflow)

    def test_scanner_actions_are_pinned_to_commits(self) -> None:
        self.assertRegex(
            self.scanner_workflow,
            r"uses: actions/checkout@[0-9a-f]{40}",
        )
        self.assertRegex(
            self.scanner_workflow,
            r"uses: actions/setup-python@[0-9a-f]{40}",
        )

    def test_ci_emulators_use_the_demo_project(self) -> None:
        self.assertIn(
            'firebase emulators:exec --project demo-mediadock "python -m unittest',
            self.ci_workflow,
        )
        self.assertIn(
            'firebase emulators:exec --project demo-mediadock "npx vitest',
            self.ci_workflow,
        )


if __name__ == "__main__":
    unittest.main()