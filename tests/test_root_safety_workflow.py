from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "root-safety.yml"
SETUP_COMPOSE_ACTION = (
    "docker/setup-compose-action@4eb059ff7f16592f9c84d5ca339c53cb7c5064e2"
)
BACKEND_INSTALL_COMMAND = (
    'uv pip install --python .venv/bin/python -e "./freqtrade[develop,hyperopt]"'
)
BACKEND_INSTALL_STEP = "Install backend development dependencies"


def named_step_run(workflow: str, step_name: str) -> str:
    workflow_data = yaml.safe_load(workflow)
    steps = workflow_data["jobs"]["safety"]["steps"]
    return next(step["run"] for step in steps if step.get("name") == step_name)


class RootSafetyWorkflowTests(unittest.TestCase):
    def test_installs_backend_test_runtime_dependencies(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        install_script = named_step_run(workflow, BACKEND_INSTALL_STEP)

        self.assertIn(BACKEND_INSTALL_COMMAND, install_script.splitlines())

    def test_rejects_backend_dependency_command_only_present_in_comment(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        mutated_workflow = workflow.replace(
            BACKEND_INSTALL_COMMAND,
            'uv pip install --python .venv/bin/python -e "./freqtrade[develop]"\n'
            f"          # {BACKEND_INSTALL_COMMAND}",
            1,
        )
        install_script = named_step_run(mutated_workflow, BACKEND_INSTALL_STEP)

        self.assertNotIn(BACKEND_INSTALL_COMMAND, install_script.splitlines())

    def test_pins_compatible_compose_before_first_compose_consumer(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        setup = (
            f"- uses: {SETUP_COMPOSE_ACTION} # v2.3.0\n"
            "        with:\n"
            "          version: v5.1.4"
        )

        self.assertIn(setup, workflow)
        self.assertLess(workflow.index(setup), workflow.index("Run root unit tests"))


if __name__ == "__main__":
    unittest.main()
