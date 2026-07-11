from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any

from tools.compose_runtime import render_compose
from tools.runtime_manifest import load_runtime_manifest


REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "ops" / "config" / "trading-safety.json"
POLICY_CONTAINER_PATH = "/freqtrade/config/trading-safety.json"
RUNTIME_CONFIG_PATH = "/freqtrade/config/runtime.json"
STATE_PATH = "/freqtrade/state"
STRATEGY_PATH = "/freqtrade/user_data/strategies"
RESEARCH_DATA_PATH = "/freqtrade/user_data/research_data"

SECRET_FILES = {
    "api_password": "api_password",
    "jwt_secret": "jwt_secret_key",
    "ws_token": "ws_token",
}


def command_tokens(service: dict[str, Any]) -> list[str]:
    command = service["command"]
    if isinstance(command, list):
        return command
    return shlex.split(command)


def volume_for(service: dict[str, Any], target: str) -> dict[str, Any]:
    matches = [
        volume
        for volume in service.get("volumes", [])
        if volume["target"] == target
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one {target} mount, found {len(matches)}")
    return matches[0]


def resolved_source(volume: dict[str, Any]) -> Path:
    return Path(volume["source"]).resolve()


class TradingConfigSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load_runtime_manifest()
        cls.compose = render_compose(root=REPO_ROOT)
        cls.entries = {entry["name"]: entry for entry in cls.manifest["services"]}
        cls.services = cls.compose["services"]

    def test_compose_contains_exactly_the_manifest_services(self) -> None:
        self.assertEqual(set(self.services), set(self.entries))
        for name, entry in self.entries.items():
            self.assertEqual(self.services[name]["profiles"], [entry["profile"]])

    def test_base_compose_cannot_render_ambient_root_identity(self) -> None:
        environment = os.environ.copy()
        environment["FREQTRADE_RUNTIME_UID"] = "0"
        environment["FREQTRADE_RUNTIME_GID"] = "0"
        result = subprocess.run(
            ["docker", "compose", "-f", "docker-compose.yml", "config", "--format", "json"],
            cwd=REPO_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=True,
        )
        base = json.loads(result.stdout)
        self.assertTrue(all("user" not in service for service in base["services"].values()))
        dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("USER ftuser", dockerfile)

    def test_services_use_bootstrapped_identity_and_private_home(self) -> None:
        identity = {}
        for line in (REPO_ROOT / ".env").read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key in {"FREQTRADE_RUNTIME_UID", "FREQTRADE_RUNTIME_GID"}:
                identity[key] = value
        expected_user = (
            f"{identity['FREQTRADE_RUNTIME_UID']}:"
            f"{identity['FREQTRADE_RUNTIME_GID']}"
        )
        for name, service in self.services.items():
            self.assertEqual(service["user"], expected_user, name)
            self.assertEqual(service["environment"]["HOME"], "/freqtrade/state/home", name)

    def test_trading_services_load_runtime_then_safety_config_last(self) -> None:
        for name, entry in self.entries.items():
            if entry["role"] != "trading":
                continue
            tokens = command_tokens(self.services[name])
            config_paths = [
                tokens[index + 1]
                for index, token in enumerate(tokens[:-1])
                if token == "--config"
            ]
            self.assertEqual(
                config_paths,
                [RUNTIME_CONFIG_PATH, POLICY_CONTAINER_PATH],
                name,
            )

    def test_policy_contains_only_the_two_safety_overrides(self) -> None:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            policy,
            {"dry_run": True, "ignore_buying_expired_candle_after": 60},
        )

    def test_each_service_has_a_unique_read_only_runtime_config(self) -> None:
        sources = []
        for name, entry in self.entries.items():
            volume = volume_for(self.services[name], RUNTIME_CONFIG_PATH)
            self.assertTrue(volume.get("read_only", False), name)
            self.assertEqual(
                resolved_source(volume),
                (REPO_ROOT / entry["config_path"]).resolve(),
                name,
            )
            sources.append(resolved_source(volume))
        self.assertEqual(len(sources), len(set(sources)))

    def test_trading_safety_overlay_is_read_only(self) -> None:
        for name, entry in self.entries.items():
            if entry["role"] != "trading":
                continue
            volume = volume_for(self.services[name], POLICY_CONTAINER_PATH)
            self.assertTrue(volume.get("read_only", False), name)
            self.assertEqual(resolved_source(volume), POLICY_PATH.resolve(), name)

    def test_each_service_has_a_unique_writable_state_source(self) -> None:
        state_sources = []
        for name, entry in self.entries.items():
            state = volume_for(self.services[name], STATE_PATH)
            self.assertFalse(state.get("read_only", False), name)
            self.assertEqual(
                resolved_source(state),
                (REPO_ROOT / entry["state_root"]).resolve(),
                name,
            )
            state_sources.append(resolved_source(state))
            self.assertFalse(
                any(
                    volume["target"] == "/freqtrade/user_data"
                    and not volume.get("read_only", False)
                    for volume in self.services[name].get("volumes", [])
                ),
                name,
            )
        self.assertEqual(len(state_sources), len(set(state_sources)))

    def test_only_declared_service_state_and_results_mounts_are_writable(self) -> None:
        expected_writable_targets = {
            "freqtrade": {STATE_PATH},
            "freqtrade-futures": {STATE_PATH},
            "freqtrade-research": {STATE_PATH},
        }
        for name, service in self.services.items():
            writable_targets = {
                volume["target"]
                for volume in service.get("volumes", [])
                if not volume.get("read_only", False)
            }
            self.assertEqual(writable_targets, expected_writable_targets[name], name)

    def test_strategy_and_research_source_mounts_are_read_only(self) -> None:
        for name, service in self.services.items():
            strategy = volume_for(service, STRATEGY_PATH)
            self.assertTrue(strategy.get("read_only", False), name)
        research_source = volume_for(
            self.services["freqtrade-research"], RESEARCH_DATA_PATH
        )
        self.assertTrue(research_source.get("read_only", False))
        self.assertEqual(
            resolved_source(research_source),
            (REPO_ROOT / "ft_userdata/user_data/research_data").resolve(),
        )

    def test_research_uses_only_its_own_state(self) -> None:
        research = self.services["freqtrade-research"]
        research_root = (
            REPO_ROOT / self.entries["freqtrade-research"]["state_root"]
        ).resolve()
        self.assertEqual(
            resolved_source(volume_for(research, STATE_PATH)),
            research_root,
        )

        trading_state_roots = {
            (REPO_ROOT / entry["state_root"]).resolve()
            for entry in self.entries.values()
            if entry["role"] == "trading"
        }
        self.assertTrue(
            all(
                resolved_source(volume) not in trading_state_roots
                for volume in research.get("volumes", [])
            )
        )
        tokens = command_tokens(research)
        self.assertNotIn("--strategy", tokens)
        self.assertNotIn("--db-url", tokens)

    @unittest.skipIf(sys.flags.no_site, "requires backend runtime dependencies")
    def test_actual_research_profile_paths_resolve_below_read_only_input(self) -> None:
        config = json.loads(
            (REPO_ROOT / "ft_userdata/user_data/config.research.example.json").read_text(
                encoding="utf-8"
            )
        )
        config["user_data_dir"] = STATE_PATH
        self.assertEqual(config.get("research_input_root"), RESEARCH_DATA_PATH)
        research_source = volume_for(
            self.services["freqtrade-research"], RESEARCH_DATA_PATH
        )
        self.assertTrue(research_source.get("read_only", False))
        config["research_input_root"] = str(resolved_source(research_source))

        sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
        try:
            load_research_profiles = import_module(
                "freqtrade.research.profiles"
            ).load_research_profiles
        finally:
            sys.path.pop(0)
        profile = load_research_profiles(config)[0]
        input_root = resolved_source(research_source)
        roots = (profile.data_root, profile.market_data_root, profile.side_data_root)
        self.assertEqual(
            roots,
            (
                input_root / "a_share",
                input_root / "a_share_meta",
                input_root / "a_share_meta",
            ),
        )
        for root in roots:
            self.assertIsNotNone(root)
            root.relative_to(input_root)

    def test_all_bind_mounts_refuse_to_create_missing_host_paths(self) -> None:
        for name, service in self.services.items():
            for volume in service.get("volumes", []):
                self.assertEqual(volume["type"], "bind", (name, volume["target"]))
                self.assertIs(
                    volume.get("bind", {}).get("create_host_path"),
                    False,
                    (name, volume["target"]),
                )

    def test_each_service_uses_only_its_three_secrets(self) -> None:
        expected_top_level = set()
        expected_secret_files = {}
        for name, service in self.services.items():
            prefix = name.replace("-", "_")
            expected_sources = {
                f"{prefix}_{secret_suffix}" for secret_suffix in SECRET_FILES
            }
            expected_top_level.update(expected_sources)
            expected_secret_files.update(
                {
                    f"{prefix}_{secret_suffix}": (
                        REPO_ROOT / "ft_userdata" / "secrets" / name / filename
                    ).resolve()
                    for secret_suffix, filename in SECRET_FILES.items()
                }
            )
            mounted = {secret["source"]: secret["target"] for secret in service["secrets"]}
            self.assertEqual(
                mounted,
                {
                    f"{prefix}_{secret_suffix}": target
                    for secret_suffix, target in SECRET_FILES.items()
                },
                name,
            )
            self.assertEqual(
                service["environment"],
                {
                    "FT_API_PASSWORD_FILE": "/run/secrets/api_password",
                    "FT_JWT_SECRET_FILE": "/run/secrets/jwt_secret_key",
                    "FT_WS_TOKEN_FILE": "/run/secrets/ws_token",
                    "HOME": "/freqtrade/state/home",
                },
                name,
            )

        self.assertEqual(set(self.compose["secrets"]), expected_top_level)
        self.assertEqual(len(expected_top_level), 9)
        for source in expected_top_level:
            secret_file = Path(self.compose["secrets"][source]["file"]).resolve()
            self.assertEqual(secret_file, expected_secret_files[source], source)

    def test_published_ports_are_unique_and_localhost_only(self) -> None:
        published = []
        for name, service in self.services.items():
            self.assertEqual(len(service["ports"]), 1, name)
            port = service["ports"][0]
            self.assertEqual(port["target"], 8080, name)
            self.assertEqual(port["host_ip"], "127.0.0.1", name)
            self.assertEqual(port["protocol"], "tcp", name)
            published.append(str(port["published"]))
        self.assertEqual(len(published), len(set(published)))

    def test_all_services_apply_the_container_security_baseline(self) -> None:
        for name, service in self.services.items():
            self.assertIs(service["init"], True, name)
            self.assertEqual(service["cap_drop"], ["ALL"], name)
            self.assertIn("no-new-privileges:true", service["security_opt"], name)

    def test_image_install_tree_is_readable_but_not_writable_by_runtime_users(self) -> None:
        dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("ENV PYTHONUSERBASE=/home/ftuser/.local", dockerfile)
        self.assertIn("chmod 0755 /home/ftuser", dockerfile)
        self.assertIn("chmod -R a+rX /home/ftuser/.local", dockerfile)
        self.assertNotIn("chmod -R a+w", dockerfile)


if __name__ == "__main__":
    unittest.main()
