from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "root-safety.yml"
SETUP_COMPOSE_ACTION = (
    "docker/setup-compose-action@4eb059ff7f16592f9c84d5ca339c53cb7c5064e2"
)
SETUP_PNPM_ACTION = (
    "pnpm/action-setup@0ebf47130e4866e96fce0953f49152a61190b271"
)
SETUP_PNPM_ACTION_LINE = f"        uses: {SETUP_PNPM_ACTION} # v6.0.9"
PNPM_SETUP_STEP = "Install pnpm"
PNPM_VERSION = "11.9.0"
BACKEND_INSTALL_COMMAND = (
    'uv pip install --python .venv/bin/python -e "./freqtrade[develop,hyperopt]"'
)
BACKEND_INSTALL_STEP = "Install backend development dependencies"
ROOT_UNIT_STEP = "Run standard-library root unit tests"
ROOT_UNIT_COMMAND = 'python -S -m unittest discover -s tests -p "test_*.py" -v'
BOOTSTRAP_STEP = "Bootstrap ephemeral runtime"
FULL_RUNTIME_STEP = "Enforce full runtime contract"
BOOTSTRAPPED_RUNTIME_STEP = "Run bootstrapped runtime root tests"
BOOTSTRAPPED_RUNTIME_COMMAND = (
    "python -S -m unittest "
    "tests.test_trading_config_safety.TradingConfigSafetyTests -v"
)
RUNTIME_READY_ENV_LINE = '          ROOT_RUNTIME_TEST_READY: "1"'
RUNTIME_NOT_READY_ENV_LINE = '          ROOT_RUNTIME_TEST_READY: "0"'
FRONTEND_INSTALL_STEP = "Install FreqUI dependencies"
BACKEND_REGRESSION_STEP = "Run backend P0 regressions"
RUNTIME_ROOT_STEP = "Run runtime-dependent root selector"
RUNTIME_ROOT_COMMAND = (
    "python -m unittest "
    "tests.test_trading_config_safety.TradingConfigSafetyTests."
    "test_actual_research_profile_paths_resolve_below_read_only_input -v"
)


def named_workflow_step(workflow: str, step_name: str) -> str:
    """Return exactly one six-space-indented GitHub Actions step block."""
    marker = f"      - name: {step_name}"
    lines = workflow.splitlines(keepends=True)
    matches = [
        index
        for index, line in enumerate(lines)
        if line.rstrip("\r\n") == marker
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"expected exactly one workflow step named {step_name!r}, found {len(matches)}"
        )
    start = matches[0]
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("      - ")
        ),
        len(lines),
    )
    return "".join(lines[start:end])


def step_has_exact_line(step: str, line: str) -> bool:
    return line in step.splitlines()


class RootSafetyWorkflowTests(unittest.TestCase):
    @unittest.skipIf(
        os.environ.get("ROOT_STDLIB_CHILD") == "1",
        "avoid recursively spawning the isolated import check",
    )
    def test_workflow_test_module_imports_with_standard_library_only(self) -> None:
        environment = os.environ.copy()
        environment["ROOT_STDLIB_CHILD"] = "1"
        result = subprocess.run(
            [
                sys.executable,
                "-S",
                "-m",
                "unittest",
                "tests.test_root_safety_workflow",
                "-v",
            ],
            cwd=REPO_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_named_workflow_step_requires_exactly_one_peer_marker(self) -> None:
        workflow = (
            "steps:\n"
            "      - name: Target\n"
            "        run: python target.py\n"
            "\n"
            "      - name: Peer\n"
            "        run: python peer.py\n"
        )

        self.assertEqual(
            named_workflow_step(workflow, "Target"),
            "      - name: Target\n        run: python target.py\n\n",
        )
        with self.assertRaisesRegex(AssertionError, "found 0"):
            named_workflow_step(workflow, "Missing")
        with self.assertRaisesRegex(AssertionError, "found 2"):
            named_workflow_step(workflow + workflow, "Target")

    def test_root_unit_gate_precedes_bootstrap_and_all_dependency_installs(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        root_unit_step = named_workflow_step(workflow, ROOT_UNIT_STEP)

        self.assertTrue(
            step_has_exact_line(root_unit_step, f"        run: {ROOT_UNIT_COMMAND}")
        )
        self.assertTrue(step_has_exact_line(root_unit_step, RUNTIME_NOT_READY_ENV_LINE))
        root_unit_index = workflow.index(root_unit_step)
        for later_step_name in (
            BOOTSTRAP_STEP,
            BACKEND_INSTALL_STEP,
            PNPM_SETUP_STEP,
            FRONTEND_INSTALL_STEP,
        ):
            with self.subTest(later_step=later_step_name):
                later_step = named_workflow_step(workflow, later_step_name)
                self.assertLess(root_unit_index, workflow.index(later_step))

    def test_rejects_root_gate_command_in_comment_or_unrelated_step(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        mutated_workflow = workflow.replace(
            f"        run: {ROOT_UNIT_COMMAND}",
            "        run: python -m unittest tests.test_root_safety_workflow -v\n"
            f"        # run: {ROOT_UNIT_COMMAND}\n\n"
            "      - name: Unrelated root tests\n"
            f"        run: {ROOT_UNIT_COMMAND}",
            1,
        )
        root_unit_step = named_workflow_step(mutated_workflow, ROOT_UNIT_STEP)

        self.assertFalse(
            step_has_exact_line(root_unit_step, f"        run: {ROOT_UNIT_COMMAND}")
        )

    def test_runtime_dependent_selector_follows_backend_regressions(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        full_runtime = named_workflow_step(workflow, FULL_RUNTIME_STEP)
        install = named_workflow_step(workflow, BACKEND_INSTALL_STEP)
        regressions = named_workflow_step(workflow, BACKEND_REGRESSION_STEP)
        runtime_selector = named_workflow_step(workflow, RUNTIME_ROOT_STEP)
        frontend_setup = named_workflow_step(workflow, PNPM_SETUP_STEP)

        self.assertTrue(
            step_has_exact_line(
                runtime_selector,
                f"        run: {RUNTIME_ROOT_COMMAND}",
            )
        )
        self.assertTrue(step_has_exact_line(runtime_selector, RUNTIME_READY_ENV_LINE))
        self.assertLess(workflow.index(full_runtime), workflow.index(install))
        self.assertLess(workflow.index(install), workflow.index(regressions))
        self.assertLess(workflow.index(regressions), workflow.index(runtime_selector))
        self.assertLess(workflow.index(runtime_selector), workflow.index(frontend_setup))

    def test_bootstrapped_runtime_class_runs_before_backend_install(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        bootstrap = named_workflow_step(workflow, BOOTSTRAP_STEP)
        full_runtime = named_workflow_step(workflow, FULL_RUNTIME_STEP)
        runtime_class = named_workflow_step(workflow, BOOTSTRAPPED_RUNTIME_STEP)
        install = named_workflow_step(workflow, BACKEND_INSTALL_STEP)

        self.assertTrue(
            step_has_exact_line(
                runtime_class,
                f"        run: {BOOTSTRAPPED_RUNTIME_COMMAND}",
            )
        )
        self.assertTrue(step_has_exact_line(runtime_class, RUNTIME_READY_ENV_LINE))
        self.assertLess(workflow.index(bootstrap), workflow.index(full_runtime))
        self.assertLess(workflow.index(full_runtime), workflow.index(runtime_class))
        self.assertLess(workflow.index(runtime_class), workflow.index(install))

    def test_installs_backend_test_runtime_dependencies(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        install_step = named_workflow_step(workflow, BACKEND_INSTALL_STEP)

        self.assertTrue(
            step_has_exact_line(install_step, f"          {BACKEND_INSTALL_COMMAND}")
        )

    def test_rejects_backend_dependency_command_only_present_in_comment(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        mutated_workflow = workflow.replace(
            BACKEND_INSTALL_COMMAND,
            'uv pip install --python .venv/bin/python -e "./freqtrade[develop]"\n'
            f"          # {BACKEND_INSTALL_COMMAND}",
            1,
        )
        install_step = named_workflow_step(mutated_workflow, BACKEND_INSTALL_STEP)

        self.assertFalse(
            step_has_exact_line(install_step, f"          {BACKEND_INSTALL_COMMAND}")
        )

    def test_pins_compatible_compose_before_first_compose_consumer(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        setup = (
            f"- uses: {SETUP_COMPOSE_ACTION} # v2.3.0\n"
            "        with:\n"
            "          version: v5.1.4"
        )

        self.assertIn(setup, workflow)
        self.assertLess(workflow.index(setup), workflow.index(ROOT_UNIT_STEP))

    def test_installs_declared_pnpm_with_pinned_action(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        setup = named_workflow_step(workflow, PNPM_SETUP_STEP)

        self.assertTrue(step_has_exact_line(setup, SETUP_PNPM_ACTION_LINE))
        self.assertTrue(step_has_exact_line(setup, f"          version: {PNPM_VERSION}"))

    def test_rejects_pnpm_version_only_present_in_comment(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        mutated_workflow = workflow.replace(
            f"          version: {PNPM_VERSION}",
            "          version: 10.32.1\n"
            f"          # version: {PNPM_VERSION}",
            1,
        )
        setup = named_workflow_step(mutated_workflow, PNPM_SETUP_STEP)

        self.assertFalse(
            step_has_exact_line(setup, f"          version: {PNPM_VERSION}")
        )

    def test_rejects_pinned_action_only_present_in_unrelated_step(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        mutated_workflow = workflow.replace(
            f"      - name: {PNPM_SETUP_STEP}\n"
            f"{SETUP_PNPM_ACTION_LINE}",
            "      - name: Unrelated pnpm setup\n"
            f"{SETUP_PNPM_ACTION_LINE}\n"
            "        with:\n"
            f"          version: {PNPM_VERSION}\n\n"
            f"      - name: {PNPM_SETUP_STEP}\n"
            "        uses: pnpm/action-setup@unpinned # v6.0.9",
            1,
        )
        setup = named_workflow_step(mutated_workflow, PNPM_SETUP_STEP)

        self.assertFalse(step_has_exact_line(setup, SETUP_PNPM_ACTION_LINE))


if __name__ == "__main__":
    unittest.main()
