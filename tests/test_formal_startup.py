from __future__ import annotations

import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tools import formal_startup


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_SAFETY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "root-safety.yml"


def local_image_available() -> bool:
    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", "freqtrade-cn:local"],
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


class FormalStartupUnitTests(unittest.TestCase):
    def test_root_safety_runs_formal_startup_after_image_build(self) -> None:
        workflow = ROOT_SAFETY_WORKFLOW.read_text(encoding="utf-8")
        step = (
            "      - name: Verify formal dynamic-UID startup\n"
            "        run: python tools/formal_startup.py verify-all --image freqtrade-cn:local"
        )
        self.assertEqual(workflow.count(step), 1)
        self.assertLess(
            workflow.index("      - name: Build integrated image"), workflow.index(step)
        )

    def test_formal_command_reads_rendered_production_argv(self) -> None:
        rendered = {
            "services": {
                "freqtrade": {
                    "command": [
                        "trade",
                        "--config",
                        "/freqtrade/config/runtime.json",
                        "--config",
                        "/freqtrade/config/trading-safety.json",
                    ]
                }
            }
        }

        self.assertEqual(
            formal_startup.formal_command(rendered, "freqtrade"),
            (
                "trade",
                "--config",
                "/freqtrade/config/runtime.json",
                "--config",
                "/freqtrade/config/trading-safety.json",
            ),
        )
        self.assertEqual(formal_startup.STARTUP_EXPECTATIONS["freqtrade"].command, ())

    def test_offline_command_uses_non_1000_uid_network_none_and_ephemeral_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            probe_root = Path(temporary_directory)
            expectation = replace(
                formal_startup.STARTUP_EXPECTATIONS["freqtrade"],
                command=("trade", "--config", "/freqtrade/config/runtime.json"),
            )
            command = formal_startup.build_offline_docker_command(
                image="freqtrade-cn:local",
                expectation=expectation,
                runtime_uid=12345,
                runtime_gid=12345,
                repo_root=REPO_ROOT,
                probe_root=probe_root,
            )

        self.assertEqual(command[:2], ["docker", "run"])
        self.assertNotIn("--rm", command)
        self.assertIn("--detach", command)
        self.assertIn("--network", command)
        self.assertEqual(command[command.index("--network") + 1], "none")
        self.assertEqual(command[command.index("--user") + 1], "12345:12345")
        self.assertIn("HOME=/freqtrade/state/home", command)
        mounts = [command[index + 1] for index, token in enumerate(command) if token == "--mount"]
        self.assertTrue(
            any(
                "target=/freqtrade/state" in mount and "readonly" not in mount
                for mount in mounts
            )
        )
        for target in (
            "/freqtrade/config/runtime.json",
            "/freqtrade/config/trading-safety.json",
            "/freqtrade/user_data/strategies",
            "/run/secrets/api_password",
            "/run/secrets/jwt_secret_key",
            "/run/secrets/ws_token",
        ):
            self.assertTrue(
                any(f"target={target}" in mount and "readonly" in mount for mount in mounts),
                target,
            )
        self.assertEqual(command[-len(expectation.command) :], list(expectation.command))

    def test_trading_rejects_userdata_strategy_secret_and_database_failures(self) -> None:
        expectation = formal_startup.STARTUP_EXPECTATIONS["freqtrade"]
        failures = (
            "fatal: FT_API_PASSWORD_FILE is required",
            "fatal: secret policy failed\n"
            "Could not load markets, therefore cannot start. Please investigate the above error",
            "Using user-data directory: /freqtrade/user_data ... Permission denied",
            "Impossible to load Strategy 'SampleStrategy'",
            "sqlalchemy.exc.OperationalError: unable to open database file",
        )

        for output in failures:
            with self.subTest(output=output):
                completed = subprocess.CompletedProcess([], 2, output, "")
                with self.assertRaisesRegex(RuntimeError, "formal startup verification failed"):
                    formal_startup.verify_startup_result(expectation, completed)

    def test_trading_accepts_only_the_named_external_network_boundary(self) -> None:
        expectation = formal_startup.STARTUP_EXPECTATIONS["freqtrade"]
        named_boundary = subprocess.CompletedProcess(
            [],
            2,
            "Could not load markets, therefore cannot start. Please investigate the above error",
            "",
        )
        formal_startup.verify_startup_result(expectation, named_boundary)

        for output in ("unexpected failure", "ExchangeNotAvailable", "Permission denied"):
            with self.subTest(output=output):
                completed = subprocess.CompletedProcess([], 2, output, "")
                with self.assertRaises(RuntimeError):
                    formal_startup.verify_startup_result(expectation, completed)

    def test_research_requires_ping_and_bounded_clean_stop(self) -> None:
        expectation = replace(
            formal_startup.STARTUP_EXPECTATIONS["freqtrade-research"],
            command=("webserver", "--config", "/freqtrade/config/runtime.json"),
        )
        self.assertTrue(expectation.requires_healthcheck)
        self.assertEqual(expectation.accepted_network_error_markers, ())
        with tempfile.TemporaryDirectory() as temporary_directory:
            command = formal_startup.build_offline_docker_command(
                image="freqtrade-cn:local",
                expectation=expectation,
                runtime_uid=12345,
                runtime_gid=12345,
                repo_root=REPO_ROOT,
                probe_root=Path(temporary_directory),
            )
        self.assertIn("--detach", command)
        self.assertIn("--cidfile", command)

    def test_failure_output_is_secret_and_row_safe(self) -> None:
        expectation = formal_startup.STARTUP_EXPECTATIONS["freqtrade"]
        secret = "private-jwt-value"
        row = "trade_id=17 pair=BTC/USDT amount=0.125"
        completed = subprocess.CompletedProcess([], 2, f"{secret}\n{row}", "")

        with self.assertRaises(RuntimeError) as caught:
            formal_startup.verify_startup_result(expectation, completed)

        message = str(caught.exception)
        self.assertEqual(message, "freqtrade formal startup verification failed")
        self.assertNotIn(secret, message)
        self.assertNotIn(row, message)


@unittest.skipUnless(local_image_available(), "freqtrade-cn:local is not built")
class FormalStartupDockerTests(unittest.TestCase):
    def test_all_formal_services_pass_dynamic_uid_contract(self) -> None:
        for service in formal_startup.STARTUP_EXPECTATIONS:
            with self.subTest(service=service):
                formal_startup.verify_formal_startup(
                    service,
                    image="freqtrade-cn:local",
                    repo_root=REPO_ROOT,
                )


if __name__ == "__main__":
    unittest.main()
