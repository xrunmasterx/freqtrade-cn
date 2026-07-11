from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "root-safety.yml"
SETUP_COMPOSE_ACTION = (
    "docker/setup-compose-action@4eb059ff7f16592f9c84d5ca339c53cb7c5064e2"
)


class RootSafetyWorkflowTests(unittest.TestCase):
    def test_installs_backend_test_runtime_dependencies(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn('-e "./freqtrade[develop,hyperopt]"', workflow)

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
