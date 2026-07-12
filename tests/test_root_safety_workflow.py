from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "root-safety.yml"
PLATFORM_RUNBOOK_PATH = REPO_ROOT / "docs" / "operations" / "platform-control.md"
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
MARKET_CATALOG_BACKEND_SELECTORS = (
    "tests/markets/test_catalog.py",
    "tests/platform/test_catalog_repository.py",
    "tests/rpc/test_api_catalog.py",
    "tests/research/test_profiles.py",
)
RUNTIME_ROOT_STEP = "Run runtime-dependent root selector"
RUNTIME_ROOT_COMMAND = (
    "python -m unittest "
    "tests.test_trading_config_safety.TradingConfigSafetyTests."
    "test_actual_research_profile_paths_resolve_below_read_only_input -v"
)
BUILD_IMAGE_STEP = "Build integrated image"
PLATFORM_CI_STEPS = (
    "Start platform PostgreSQL",
    "Upgrade platform schema",
    "Run platform PostgreSQL integration tests",
    "Run Phase 2A backend regressions",
    "Verify platform-control least privilege",
    "Clean platform control plane",
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


def active_step_text(step: str) -> str:
    return "\n".join(
        line for line in step.splitlines() if not line.lstrip().startswith("#")
    )


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

    def test_backend_regressions_execute_market_catalog_selectors(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = named_workflow_step(workflow, BACKEND_REGRESSION_STEP)
        pytest_command, separator, _ = step.partition("          ruff check \\\n")

        self.assertTrue(separator)

        for selector in MARKET_CATALOG_BACKEND_SELECTORS:
            with self.subTest(selector=selector):
                self.assertIn(f"            {selector} \\\n", pytest_command)

    def test_rejects_market_catalog_selector_only_present_in_comment(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        selector = MARKET_CATALOG_BACKEND_SELECTORS[0]
        mutated = workflow.replace(
            f"            {selector} \\\n",
            f"            # {selector} \\\n",
            1,
        )
        step = named_workflow_step(mutated, BACKEND_REGRESSION_STEP)
        pytest_command, separator, _ = step.partition("          ruff check \\\n")

        self.assertTrue(separator)
        self.assertNotIn(f"            {selector} \\\n", pytest_command)

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

    def test_platform_ci_steps_are_unique_and_follow_the_image_build_in_order(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        previous_position = workflow.index(named_workflow_step(workflow, BUILD_IMAGE_STEP))

        for step_name in PLATFORM_CI_STEPS:
            with self.subTest(step=step_name):
                step = named_workflow_step(workflow, step_name)
                position = workflow.index(step)
                self.assertLess(previous_position, position)
                previous_position = position

    def test_platform_ci_cleanup_is_unconditional(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cleanup = named_workflow_step(workflow, PLATFORM_CI_STEPS[-1])

        self.assertTrue(step_has_exact_line(cleanup, "        if: always()"))

    def test_platform_postgres_step_is_file_secreted_loopback_and_volume_free(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = active_step_text(named_workflow_step(workflow, PLATFORM_CI_STEPS[0]))
        required = (
            'platform_ci_dir="${RUNNER_TEMP}/platform-control-ci"',
            'install -d -m 0700 "${platform_ci_dir}"',
            "postgres_admin_password \\",
            "platform_control_db_password \\",
            "platform_supervisor_db_password \\",
            "api_password \\",
            "jwt_secret_key",
            '"ft_userdata/secrets/platform/${secret_name}"',
            'docker volume ls --quiet | sort > "${platform_ci_dir}/volumes.before"',
            "docker network create --internal freqtrade-platform-ci",
            "--name platform-postgres-ci",
            "--publish 127.0.0.1:55432:5432",
            "--tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,size=512m",
            "POSTGRES_PASSWORD_FILE=/run/secrets/postgres_admin_password",
            "postgres:17.10-alpine",
            "docker network connect freqtrade-platform-ci platform-postgres-ci",
            "for attempt in $(seq 1 60); do",
            "CREATE DATABASE platform_test_ci",
            'PGPASSFILE=${platform_ci_dir}/pgpass',
            "PLATFORM_TEST_POSTGRES_URL=postgresql+psycopg://postgres@127.0.0.1:55432/platform_test_ci",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, step)
        self.assertNotIn("POSTGRES_PASSWORD=", step)
        self.assertNotIn("docker compose", step)
        self.assertNotIn("docker network disconnect bridge platform-postgres-ci", step)

    def test_platform_upgrade_and_backend_selectors_are_executable(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        upgrade = active_step_text(named_workflow_step(workflow, PLATFORM_CI_STEPS[1]))
        postgres = active_step_text(named_workflow_step(workflow, PLATFORM_CI_STEPS[2]))
        regressions = active_step_text(named_workflow_step(workflow, PLATFORM_CI_STEPS[3]))

        for fragment in (
            "PlatformDatabaseSettings",
            "settings.sqlalchemy_url()",
            'command.upgrade(config, "head")',
            "ScriptDirectory.from_config(config).get_current_head()",
            "SqlCatalogRepository",
            "default_catalog_snapshot",
            "docker exec platform-postgres-ci sh /docker-entrypoint-initdb.d/init-platform-roles.sh",
        ):
            self.assertIn(fragment, upgrade)
        for selector in (
            "tests/platform/test_platform_migrations.py",
            "tests/platform/test_runtime_repository.py",
        ):
            self.assertIn(selector, postgres)
        for selector in (
            "tests/markets/test_catalog.py",
            "tests/platform/test_database.py",
            "tests/platform/test_catalog_repository.py",
            "tests/platform/test_runtime_domain.py",
            "tests/platform/test_runtime_service.py",
            "tests/platform_control",
            "tests/rpc/test_api_catalog.py",
        ):
            self.assertIn(selector, regressions)
        self.assertIn("ruff check \\", regressions)

    def test_least_privilege_step_reconciles_roles_and_probes_hardened_http(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = active_step_text(named_workflow_step(workflow, PLATFORM_CI_STEPS[4]))
        required = (
            "ALTER ROLE platform_control WITH SUPERUSER CREATEDB CREATEROLE INHERIT REPLICATION BYPASSRLS",
            "ALTER ROLE platform_supervisor WITH SUPERUSER CREATEDB CREATEROLE INHERIT REPLICATION BYPASSRLS",
            "column_grantor_role.rolname",
            "ORDER BY column_grantor_role.rolname",
            "permission denied for table runtime_instances",
            "docker network disconnect bridge platform-postgres-ci",
            'test "${database_networks}" = "freqtrade-platform-ci"',
            "--name platform-control-ci",
            "--user 1000:1000",
            "--read-only",
            "--init",
            "--cap-drop ALL",
            "--security-opt no-new-privileges:true",
            "--network freqtrade-platform-ci",
            "--publish 127.0.0.1:8090:8090",
            "--netrc-file",
            '"http://127.0.0.1:8090/api/v2/ping"',
            '"http://127.0.0.1:8090/api/v2/catalog"',
            '"http://127.0.0.1:8090/api/v2/runtime-instances"',
            '"/openapi.json"',
            '"/docs"',
            '"/api/v2/runtime-instances/ci-instance/start"',
            '"/api/v2/runtime-access/ci-instance"',
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, step)
        self.assertLess(
            step.index("SET ROLE platform_ci_delegate"),
            step.index("ALTER ROLE platform_control WITH SUPERUSER"),
        )
        self.assertLess(
            step.index("GRANT UPDATE (desired_state) ON TABLE public.runtime_instances\n"
                       "            TO platform_ci_downstream"),
            step.index("ALTER ROLE platform_control WITH SUPERUSER"),
        )
        for forbidden in ("docker.sock", "ft_userdata/runtime", "docker compose"):
            self.assertNotIn(forbidden, step)

    def test_platform_cleanup_removes_exact_resources_and_asserts_no_volume_drift(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cleanup = active_step_text(named_workflow_step(workflow, PLATFORM_CI_STEPS[5]))

        for fragment in (
            "docker rm -f platform-control-ci platform-postgres-ci",
            "docker network rm freqtrade-platform-ci",
            'docker volume ls --quiet | sort > "${platform_ci_dir}/volumes.after"',
            'cmp "${platform_ci_dir}/volumes.before" "${platform_ci_dir}/volumes.after"',
            'rm -rf "${platform_ci_dir}"',
        ):
            self.assertIn(fragment, cleanup)

    def test_platform_contract_text_in_comments_or_unrelated_steps_is_rejected(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        marker = "--security-opt no-new-privileges:true"
        mutated = workflow.replace(marker, f"# {marker}", 1)
        mutated += f"\n      - name: Unrelated platform text\n        run: echo '{marker}'\n"
        least_privilege = active_step_text(
            named_workflow_step(mutated, PLATFORM_CI_STEPS[4])
        )

        self.assertNotIn(marker, least_privilege)

    def test_platform_runbook_keeps_production_start_fail_closed(self) -> None:
        self.assertTrue(PLATFORM_RUNBOOK_PATH.is_file())
        runbook = PLATFORM_RUNBOOK_PATH.read_text(encoding="utf-8")

        for statement in (
            "Production platform start/stop is not exposed in Phase 2A.",
            "Raw `docker compose up` is unsupported and bypasses review gates.",
            "`compose_runtime` remains platform config-only.",
            "A Supervisor or dedicated infrastructure launcher must land before production use.",
        ):
            self.assertIn(statement, runbook)


if __name__ == "__main__":
    unittest.main()
