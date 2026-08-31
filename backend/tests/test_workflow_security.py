import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATHS = (
    Path(".github/workflows/ci.yml"),
    Path(".github/workflows/pages.yml"),
    Path(".github/workflows/scanner.yml"),
)


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


def _active_action_references(workflow: str) -> list[str]:
    return [
        match.group(1).strip("'\"")
        for line in workflow.splitlines()
        if (match := re.match(r"^\s*(?:-\s*)?uses:\s*(\S+)\s*$", line))
    ]


class TestWorkflowSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflows = {
            path: (ROOT / path).read_text(encoding="utf-8")
            for path in WORKFLOW_PATHS
        }
        cls.scanner_workflow = cls.workflows[Path(".github/workflows/scanner.yml")]
        cls.ci_workflow = cls.workflows[Path(".github/workflows/ci.yml")]

    def test_scanner_inputs_are_environment_values_not_shell_source(self) -> None:
        self.assertNotIn("github.event.inputs.", self.scanner_workflow)
        self.assertIn("SCANNER_FORCE_DAYS: ${{ inputs.force_days }}", self.scanner_workflow)
        self.assertIn("SCANNER_AUDIT_DAYS: ${{ inputs.audit_days }}", self.scanner_workflow)
        self.assertIn("SCANNER_MODE: ${{ inputs.mode }}", self.scanner_workflow)
        for block in _shell_run_blocks(self.scanner_workflow):
            self.assertNotIn("${{", block)

    def test_scanner_validates_inputs_and_uses_a_shell_array(self) -> None:
        self.assertIn("[[ \"$force_days\" =~ ^[0-9]+$ ]]", self.scanner_workflow)
        self.assertIn("[[ \"$audit_days\" =~ ^[0-9]+$ ]]", self.scanner_workflow)
        self.assertIn("case \"$mode\"", self.scanner_workflow)
        self.assertIn("scanner_args=(", self.scanner_workflow)
        self.assertIn('python -m movies_feed.cli "${scanner_args[@]}"', self.scanner_workflow)
        self.assertNotIn("EXTRA_ARGS", self.scanner_workflow)

    def test_scanner_workflow_has_no_proposal_application_inputs(self) -> None:
        self.assertNotIn("apply-proposals", self.scanner_workflow)
        self.assertNotIn("proposal_id", self.scanner_workflow)
        self.assertNotIn("reject_proposal", self.scanner_workflow)
        self.assertNotIn("--proposal-id", self.scanner_workflow)
        self.assertNotIn("--reject-proposal", self.scanner_workflow)

    def test_external_actions_are_pinned_to_commits(self) -> None:
        for path, workflow in self.workflows.items():
            for reference in _active_action_references(workflow):
                if reference.startswith("./"):
                    continue
                with self.subTest(workflow=str(path), action=reference):
                    self.assertRegex(reference, r"^[^@\s]+@[0-9a-fA-F]{40}$")

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