from __future__ import annotations

import copy
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from tools import bootstrap_runtime
from tools.bootstrap_runtime import SENTINEL
from tools.runtime_manifest import load_runtime_manifest


class BootstrapRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.real_windows_acl = getattr(bootstrap_runtime, "_run_windows_acl", None)
        self.windows_acl_patcher = mock.patch.object(
            bootstrap_runtime,
            "_run_windows_acl",
            create=True,
        )
        self.mock_windows_acl = self.windows_acl_patcher.start()
        self.addCleanup(self.windows_acl_patcher.stop)
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.manifest = {
            "schema_version": 1,
            "services": [
                self.service("freqtrade", role="trading"),
                self.service("freqtrade-futures", role="trading"),
                self.service("freqtrade-research", role="research"),
            ],
        }
        for service in self.manifest["services"]:
            template = self.root / service["config_template"]
            template.parent.mkdir(parents=True, exist_ok=True)
            template.write_text(
                json.dumps(
                    {
                        "dry_run": True,
                        "exchange": {"name": "okx", "key": "", "secret": ""},
                        "api_server": {
                            "password": SENTINEL,
                            "jwt_secret_key": SENTINEL,
                            "ws_token": SENTINEL,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

    def service(self, name: str, role: str = "trading") -> dict[str, object]:
        suffix = name.removeprefix("freqtrade").strip("-") or "spot"
        return {
            "name": name,
            "role": role,
            "profile": "research" if role == "research" else "trading",
            "config_template": f"templates/{suffix}.example.json",
            "config_path": f"configs/{suffix}.json",
            "strategy": None if role == "research" else "SampleStrategy",
            "state_root": f"runtime/{name}",
            "legacy_database": None,
            "database_filename": None if role == "research" else "trades.sqlite",
        }

    def write_manifest(self, services: list[dict[str, object]]) -> Path:
        return self.write_manifest_data({"schema_version": 1, "services": services})

    def write_manifest_data(self, data: object) -> Path:
        path = self.root / "runtime-services.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def supported_manifest(self) -> dict[str, Any]:
        return copy.deepcopy(load_runtime_manifest())

    def read_all_secret_values(self) -> dict[str, list[str]]:
        return {
            service["name"]: [
                (
                    self.root
                    / "ft_userdata"
                    / "secrets"
                    / service["name"]
                    / filename
                )
                .read_text(encoding="utf-8")
                .strip()
                for filename in bootstrap_runtime.SECRET_SPECS
            ]
            for service in self.manifest["services"]
        }

    def test_load_manifest_rejects_duplicate_service_names(self) -> None:
        manifest = self.write_manifest(
            services=[self.service("freqtrade"), self.service("freqtrade")]
        )
        with self.assertRaisesRegex(ValueError, "duplicate runtime service"):
            load_runtime_manifest(manifest)

    def test_load_manifest_rejects_wrong_schema_version(self) -> None:
        manifest = self.write_manifest([self.service("freqtrade")])
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["schema_version"] = 2
        manifest.write_text(json.dumps(data), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "schema_version must be integer 1"):
            load_runtime_manifest(manifest)

    def test_load_manifest_rejects_boolean_schema_version(self) -> None:
        data = self.supported_manifest()
        data["schema_version"] = True

        with self.assertRaisesRegex(ValueError, "schema_version must be integer 1"):
            load_runtime_manifest(self.write_manifest_data(data))

    def test_load_manifest_rejects_non_object_top_level(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be an object"):
            load_runtime_manifest(self.write_manifest_data([]))

    def test_load_manifest_rejects_missing_service_keys(self) -> None:
        service = self.service("freqtrade")
        del service["state_root"]
        manifest = self.write_manifest([service])

        with self.assertRaisesRegex(ValueError, "missing keys: state_root"):
            load_runtime_manifest(manifest)

    def test_load_manifest_rejects_unsupported_role(self) -> None:
        data = self.supported_manifest()
        data["services"][0]["role"] = "admin"

        with self.assertRaisesRegex(ValueError, "unsupported runtime role"):
            load_runtime_manifest(self.write_manifest_data(data))

    def test_load_manifest_rejects_extra_service(self) -> None:
        data = self.supported_manifest()
        data["services"].append(self.service("freqtrade-extra"))

        with self.assertRaisesRegex(ValueError, "exactly the supported services"):
            load_runtime_manifest(self.write_manifest_data(data))

    def test_load_manifest_rejects_extra_service_key(self) -> None:
        data = self.supported_manifest()
        data["services"][0]["unexpected"] = "value"

        with self.assertRaisesRegex(ValueError, "unexpected keys"):
            load_runtime_manifest(self.write_manifest_data(data))

    def test_load_manifest_rejects_unsafe_or_non_string_paths(self) -> None:
        mutations = (
            ("config_path", "C:/outside/config.json"),
            ("state_root", "ft_userdata/runtime/../outside"),
            ("config_template", 123),
        )
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                data = self.supported_manifest()
                data["services"][0][field] = value
                with self.assertRaisesRegex(ValueError, "repository-relative path"):
                    load_runtime_manifest(self.write_manifest_data(data))

    def test_load_manifest_rejects_contract_value_drift(self) -> None:
        data = self.supported_manifest()
        data["services"][2]["strategy"] = "UnexpectedStrategy"

        with self.assertRaisesRegex(ValueError, "contract mismatch"):
            load_runtime_manifest(self.write_manifest_data(data))

    def test_default_manifest_has_exact_supported_services(self) -> None:
        manifest = load_runtime_manifest()

        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(
            [service["name"] for service in manifest["services"]],
            ["freqtrade", "freqtrade-futures", "freqtrade-research"],
        )

    def test_cli_can_run_as_a_direct_script(self) -> None:
        script = Path(__file__).resolve().parents[1] / "tools" / "bootstrap_runtime.py"

        completed = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            check=False,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Bootstrap isolated Freqtrade runtime state", completed.stdout)

    def test_init_creates_config_state_and_three_unique_secrets(self) -> None:
        bootstrap_runtime.init_runtime(self.root, self.manifest)

        for service in self.manifest["services"]:
            self.assertTrue((self.root / service["config_path"]).is_file())
            self.assertTrue((self.root / service["state_root"] / "logs").is_dir())
        research_root = self.root / "runtime/freqtrade-research"
        self.assertTrue((research_root / "data").is_dir())
        self.assertTrue((research_root / "backtest_results").is_dir())

        service_values = self.read_all_secret_values()
        all_values = [value for values in service_values.values() for value in values]
        self.assertTrue(all(len(values) == 3 for values in service_values.values()))
        self.assertTrue(all(len(values) == len(set(values)) for values in service_values.values()))
        self.assertEqual(len(all_values), len(set(all_values)))
        self.assertTrue(all(len(value) >= 32 for value in all_values))

    def test_init_creates_complete_state_layout_for_every_service(self) -> None:
        bootstrap_runtime.init_runtime(self.root, self.manifest)

        for service in self.manifest["services"]:
            with self.subTest(service=service["name"]):
                state_root = self.root / service["state_root"]
                for directory in ("home", "logs", "data", "backtest_results"):
                    self.assertTrue((state_root / directory).is_dir())

    def test_init_never_creates_state_strategy_directory(self) -> None:
        bootstrap_runtime.init_runtime(self.root, self.manifest)

        for service in self.manifest["services"]:
            with self.subTest(service=service["name"]):
                self.assertFalse(
                    (self.root / service["state_root"] / "strategies").exists()
                )

    def test_migrate_research_paths_updates_exact_legacy_values_atomically(self) -> None:
        config_path = self.root / "configs/research.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "marker": "preserved",
            "research_bots": [
                {
                    "data_source": {"root": "research_data/a_share"},
                    "market_data": {"meta_root": "research_data/a_share_meta"},
                    "side_data": {"root": "research_data/a_share_meta"},
                }
            ],
        }
        config_path.write_text(json.dumps(document), encoding="utf-8")
        self.manifest["services"][2]["config_path"] = "configs/research.json"
        migrate = getattr(bootstrap_runtime, "migrate_research_paths", None)
        self.assertIsNotNone(migrate)
        if migrate is None:
            return

        with mock.patch.object(
            bootstrap_runtime,
            "_atomic_write_text",
            wraps=bootstrap_runtime._atomic_write_text,
        ) as atomic_write:
            migrate(self.root, self.manifest)

        atomic_write.assert_called_once()
        self.assertEqual(atomic_write.call_args.args[0], config_path)
        migrated = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(migrated["marker"], "preserved")
        profile = migrated["research_bots"][0]
        self.assertEqual(
            profile["data_source"]["root"],
            "/freqtrade/user_data/research_data/a_share",
        )
        self.assertEqual(
            profile["market_data"]["meta_root"],
            "/freqtrade/user_data/research_data/a_share_meta",
        )
        self.assertEqual(
            profile["side_data"]["root"],
            "/freqtrade/user_data/research_data/a_share_meta",
        )

    def test_migrate_research_paths_is_idempotent_for_approved_values(self) -> None:
        config_path = self.root / "configs/research.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "research_bots": [
                {
                    "data_source": {
                        "root": "/freqtrade/user_data/research_data/a_share"
                    },
                    "market_data": {
                        "meta_root": "/freqtrade/user_data/research_data/a_share_meta"
                    },
                    "side_data": {
                        "root": "/freqtrade/user_data/research_data/a_share_meta"
                    },
                }
            ]
        }
        config_path.write_text(json.dumps(document), encoding="utf-8")
        before = config_path.read_bytes()
        self.manifest["services"][2]["config_path"] = "configs/research.json"
        migrate = getattr(bootstrap_runtime, "migrate_research_paths", None)
        self.assertIsNotNone(migrate)
        if migrate is None:
            return

        with mock.patch.object(bootstrap_runtime, "_atomic_write_text") as atomic_write:
            migrate(self.root, self.manifest)

        atomic_write.assert_not_called()
        self.assertEqual(config_path.read_bytes(), before)

    def test_migrate_research_paths_rejects_unknown_values_without_partial_write(self) -> None:
        mutations = (
            ("data_source", "root", "/custom/data"),
            ("market_data", "meta_root", "custom/meta"),
            ("side_data", "root", "/custom/side"),
        )
        for section, key, value in mutations:
            with self.subTest(section=section):
                config_path = self.root / "configs/research.json"
                config_path.parent.mkdir(parents=True, exist_ok=True)
                document = {
                    "research_bots": [
                        {
                            "data_source": {"root": "research_data/a_share"},
                            "market_data": {
                                "meta_root": "research_data/a_share_meta"
                            },
                            "side_data": {"root": "research_data/a_share_meta"},
                        }
                    ]
                }
                document["research_bots"][0][section][key] = value
                config_path.write_text(json.dumps(document), encoding="utf-8")
                before = config_path.read_bytes()
                self.manifest["services"][2]["config_path"] = "configs/research.json"
                migrate = getattr(bootstrap_runtime, "migrate_research_paths", None)
                self.assertIsNotNone(migrate)
                if migrate is None:
                    return

                with (
                    mock.patch.object(bootstrap_runtime, "_atomic_write_text") as atomic_write,
                    self.assertRaisesRegex(ValueError, "research path migration"),
                ):
                    migrate(self.root, self.manifest)

                atomic_write.assert_not_called()
                self.assertEqual(config_path.read_bytes(), before)

    def test_parser_exposes_explicit_research_path_migration_action(self) -> None:
        self.assertIn("migrate-research-paths", bootstrap_runtime.build_parser().format_help())

    def test_verify_requires_data_and_backtest_directories_for_every_service(self) -> None:
        bootstrap_runtime.init_runtime(self.root, self.manifest)

        for service in self.manifest["services"]:
            for directory in ("data", "backtest_results"):
                with self.subTest(service=service["name"], directory=directory):
                    path = self.root / service["state_root"] / directory
                    path.mkdir(exist_ok=True)
                    path.rmdir()
                    with self.assertRaisesRegex(
                        ValueError, "invalid runtime writable directory"
                    ):
                        bootstrap_runtime.verify_runtime(self.root, self.manifest)
                    path.mkdir()

    def test_posix_init_merges_runtime_identity_and_creates_service_homes(self) -> None:
        environment = self.root / ".env"
        environment.write_bytes(
            b"# user settings\r\nFT_UI_PORT=9000\r\nFREQTRADE_RUNTIME_UID=1001\r\n"
        )

        with (
            mock.patch.object(bootstrap_runtime, "_is_windows", return_value=False),
            mock.patch.object(bootstrap_runtime.os, "getuid", return_value=1001, create=True),
            mock.patch.object(bootstrap_runtime.os, "getgid", return_value=1002, create=True),
            mock.patch.object(bootstrap_runtime, "_harden_runtime_control_file"),
        ):
            bootstrap_runtime.init_runtime(self.root, self.manifest)

        self.assertEqual(
            environment.read_bytes(),
            b"# user settings\r\nFT_UI_PORT=9000\r\n"
            b"FREQTRADE_RUNTIME_UID=1001\r\nFREQTRADE_RUNTIME_GID=1002\r\n",
        )
        for service in self.manifest["services"]:
            self.assertTrue((self.root / service["state_root"] / "home").is_dir())
        override = json.loads(
            (self.root / "ft_userdata/runtime/compose.identity.yml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            override,
            {
                "services": {
                    service["name"]: {"user": "1001:1002"}
                    for service in self.manifest["services"]
                }
            },
        )

    def test_posix_init_rejects_root_runtime_identity(self) -> None:
        with (
            mock.patch.object(bootstrap_runtime, "_is_windows", return_value=False),
            mock.patch.object(bootstrap_runtime.os, "getuid", return_value=0, create=True),
            mock.patch.object(bootstrap_runtime.os, "getgid", return_value=0, create=True),
            self.assertRaisesRegex(ValueError, "non-root runtime identity"),
        ):
            bootstrap_runtime.init_runtime(self.root, self.manifest)
        self.assertFalse((self.root / ".env").exists())

    def test_init_rejects_conflicting_or_unknown_compose_identity_override(self) -> None:
        override = self.root / "ft_userdata/runtime/compose.identity.yml"
        override.parent.mkdir(parents=True)
        invalid_documents = (
            {"services": {"freqtrade": {"user": "999:999"}}},
            {
                "services": {
                    service["name"]: {"user": "1000:1000"}
                    for service in self.manifest["services"]
                },
                "unknown": {},
            },
        )
        for document in invalid_documents:
            with self.subTest(document=document):
                content = json.dumps(document) + "\n"
                override.write_text(content, encoding="utf-8")
                with (
                    mock.patch.object(
                        bootstrap_runtime, "_is_windows", return_value=True
                    ),
                    self.assertRaisesRegex(ValueError, "compose identity override"),
                ):
                    bootstrap_runtime.init_runtime(self.root, self.manifest)
                self.assertEqual(override.read_text(encoding="utf-8"), content)

    def test_windows_init_writes_container_identity_1000(self) -> None:
        with mock.patch.object(bootstrap_runtime, "_is_windows", return_value=True):
            bootstrap_runtime.init_runtime(self.root, self.manifest)

        self.assertEqual(
            (self.root / ".env").read_text(encoding="utf-8"),
            "FREQTRADE_RUNTIME_UID=1000\nFREQTRADE_RUNTIME_GID=1000\n",
        )

    def test_init_hardens_existing_runtime_control_files(self) -> None:
        environment = self.root / ".env"
        environment.write_text(
            "PORT=9000\nFREQTRADE_RUNTIME_UID=1001\n"
            "FREQTRADE_RUNTIME_GID=1002\n",
            encoding="utf-8",
        )
        override = self.root / "ft_userdata/runtime/compose.identity.yml"
        override.parent.mkdir(parents=True)
        override.write_text(
            json.dumps(
                {
                    "services": {
                        service["name"]: {"user": "1001:1002"}
                        for service in self.manifest["services"]
                    }
                }
            ),
            encoding="utf-8",
        )
        with (
            mock.patch.object(bootstrap_runtime, "_is_windows", return_value=False),
            mock.patch.object(bootstrap_runtime.os, "getuid", return_value=1001, create=True),
            mock.patch.object(bootstrap_runtime.os, "getgid", return_value=1002, create=True),
            mock.patch.object(bootstrap_runtime, "_harden_runtime_control_file") as harden,
        ):
            bootstrap_runtime.init_runtime(self.root, self.manifest)
        self.assertEqual(harden.call_args_list, [mock.call(environment, 1001), mock.call(override, 1001)])
        self.assertIn("PORT=9000", environment.read_text(encoding="utf-8"))

    def test_verify_rejects_insecure_runtime_control_file_metadata(self) -> None:
        control = self.root / ".env"
        control.write_text("identity", encoding="utf-8")
        cases = (
            SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=1001),
            SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=999),
        )
        for status in cases:
            with (
                self.subTest(status=status),
                mock.patch.object(bootstrap_runtime, "_is_windows", return_value=False),
                mock.patch.object(os, "lstat", return_value=status),
                self.assertRaisesRegex(ValueError, "runtime control file"),
            ):
                bootstrap_runtime._verify_runtime_control_file(control, 1001)

    def test_verify_rejects_runtime_control_file_symlink(self) -> None:
        control = self.root / ".env"
        with (
            mock.patch.object(Path, "is_symlink", return_value=True),
            self.assertRaisesRegex(ValueError, "runtime control file"),
        ):
            bootstrap_runtime._verify_runtime_control_file(control, 1001)

    def test_init_rejects_conflicting_or_duplicate_runtime_identity(self) -> None:
        invalid_contents = (
            "FREQTRADE_RUNTIME_UID=999\nFREQTRADE_RUNTIME_GID=1002\n",
            "FREQTRADE_RUNTIME_UID=1001\nFREQTRADE_RUNTIME_UID=1001\n"
            "FREQTRADE_RUNTIME_GID=1002\n",
        )
        for content in invalid_contents:
            with self.subTest(content=content):
                environment = self.root / ".env"
                environment.write_text(content, encoding="utf-8")
                with (
                    mock.patch.object(
                        bootstrap_runtime, "_is_windows", return_value=False
                    ),
                    mock.patch.object(
                        bootstrap_runtime.os, "getuid", return_value=1001, create=True
                    ),
                    mock.patch.object(
                        bootstrap_runtime.os, "getgid", return_value=1002, create=True
                    ),
                    self.assertRaisesRegex(ValueError, "runtime identity"),
                ):
                    bootstrap_runtime.init_runtime(self.root, self.manifest)
                self.assertEqual(environment.read_text(encoding="utf-8"), content)

    def test_verify_rejects_missing_duplicate_invalid_or_mismatched_identity(self) -> None:
        with mock.patch.object(bootstrap_runtime, "_is_windows", return_value=True):
            bootstrap_runtime.init_runtime(self.root, self.manifest)

        invalid_contents = (
            "FREQTRADE_RUNTIME_UID=1000\n",
            "FREQTRADE_RUNTIME_UID=1000\nFREQTRADE_RUNTIME_UID=1000\n"
            "FREQTRADE_RUNTIME_GID=1000\n",
            "FREQTRADE_RUNTIME_UID=-1\nFREQTRADE_RUNTIME_GID=1000\n",
            "FREQTRADE_RUNTIME_UID=1001\nFREQTRADE_RUNTIME_GID=1000\n",
        )
        for content in invalid_contents:
            with self.subTest(content=content):
                (self.root / ".env").write_text(content, encoding="utf-8")
                with (
                    mock.patch.object(
                        bootstrap_runtime, "_is_windows", return_value=True
                    ),
                    self.assertRaisesRegex(ValueError, "runtime identity"),
                ):
                    bootstrap_runtime.verify_runtime(self.root, self.manifest)

    def test_verify_rejects_invalid_ambient_runtime_identity(self) -> None:
        with mock.patch.object(bootstrap_runtime, "_is_windows", return_value=True):
            bootstrap_runtime.init_runtime(self.root, self.manifest)

        ambient_cases = (
            {"FREQTRADE_RUNTIME_UID": "1000"},
            {"FREQTRADE_RUNTIME_UID": "bad", "FREQTRADE_RUNTIME_GID": "1000"},
            {"FREQTRADE_RUNTIME_UID": "0", "FREQTRADE_RUNTIME_GID": "0"},
            {"FREQTRADE_RUNTIME_UID": "1001", "FREQTRADE_RUNTIME_GID": "1000"},
        )
        for ambient in ambient_cases:
            with self.subTest(ambient=ambient):
                with (
                    mock.patch.object(
                        bootstrap_runtime, "_is_windows", return_value=True
                    ),
                    mock.patch.dict(os.environ, ambient, clear=True),
                    self.assertRaisesRegex(ValueError, "ambient runtime identity"),
                ):
                    bootstrap_runtime.verify_runtime(self.root, self.manifest)

        with (
            mock.patch.object(bootstrap_runtime, "_is_windows", return_value=True),
            mock.patch.dict(
                os.environ,
                {
                    "FREQTRADE_RUNTIME_UID": "1000",
                    "FREQTRADE_RUNTIME_GID": "1000",
                },
                clear=True,
            ),
        ):
            bootstrap_runtime.verify_runtime(self.root, self.manifest)

    def test_verify_rejects_compose_override_drift(self) -> None:
        with mock.patch.object(bootstrap_runtime, "_is_windows", return_value=True):
            bootstrap_runtime.init_runtime(self.root, self.manifest)
        override = self.root / "ft_userdata/runtime/compose.identity.yml"
        document = json.loads(override.read_text(encoding="utf-8"))
        document["services"]["freqtrade"]["user"] = "1001:1000"
        override.write_text(json.dumps(document), encoding="utf-8")

        with (
            mock.patch.object(bootstrap_runtime, "_is_windows", return_value=True),
            self.assertRaisesRegex(ValueError, "compose identity override"),
        ):
            bootstrap_runtime.verify_runtime(self.root, self.manifest)

    def test_init_never_overwrites_existing_config_or_secret(self) -> None:
        config = self.root / "configs/spot.json"
        config.parent.mkdir(parents=True)
        config.write_text('{"marker": "keep"}\n', encoding="utf-8")
        secret = self.root / "ft_userdata/secrets/freqtrade/api_password"
        secret.parent.mkdir(parents=True)
        secret.write_text("existing-secret-value-that-is-long-enough\n", encoding="utf-8")

        bootstrap_runtime.init_runtime(self.root, self.manifest)

        self.assertEqual(config.read_text(encoding="utf-8"), '{"marker": "keep"}\n')
        self.assertEqual(
            secret.read_text(encoding="utf-8"),
            "existing-secret-value-that-is-long-enough\n",
        )
        if os.name == "nt":
            self.mock_windows_acl.assert_any_call("harden", secret)

    def test_posix_hardening_sets_mode_0600(self) -> None:
        secret = self.root / "secret"
        secret.write_text("not-a-real-secret\n", encoding="utf-8")

        with (
            mock.patch.object(bootstrap_runtime, "_is_windows", return_value=False),
            mock.patch.object(bootstrap_runtime.os, "chmod") as chmod,
        ):
            bootstrap_runtime._harden_secret_permissions(secret)

        chmod.assert_called_once_with(secret, 0o600)

    def test_posix_verify_rejects_group_or_other_permissions(self) -> None:
        secret = self.root / "secret"
        secret.write_text("not-a-real-secret\n", encoding="utf-8")

        with (
            mock.patch.object(bootstrap_runtime, "_is_windows", return_value=False),
            mock.patch.object(
                Path,
                "stat",
                return_value=SimpleNamespace(st_mode=stat.S_IFREG | 0o644),
            ),
            self.assertRaisesRegex(ValueError, "permissions must be 0600"),
        ):
            bootstrap_runtime._verify_secret_permissions(secret, runtime_uid=1001)

    def test_posix_verify_requires_runtime_uid_to_own_secret(self) -> None:
        secret = self.root / "secret"
        secret.write_text("not-a-real-secret\n", encoding="utf-8")

        with (
            mock.patch.object(bootstrap_runtime, "_is_windows", return_value=False),
            mock.patch.object(
                Path,
                "stat",
                return_value=SimpleNamespace(
                    st_mode=stat.S_IFREG | 0o600,
                    st_uid=1000,
                ),
            ),
            self.assertRaisesRegex(ValueError, "owned by runtime uid"),
        ):
            bootstrap_runtime._verify_secret_permissions(secret, runtime_uid=1001)

    def test_posix_directory_access_ignores_supplementary_groups(self) -> None:
        directory = self.root / "state"
        directory.mkdir()
        status = SimpleNamespace(
            st_mode=stat.S_IFDIR | 0o770,
            st_uid=2000,
            st_gid=2001,
        )
        with (
            mock.patch.object(Path, "stat", return_value=status),
            mock.patch.object(bootstrap_runtime.os, "getgroups", return_value=[2001], create=True),
            self.assertRaisesRegex(ValueError, "runtime writable directory permissions"),
        ):
            bootstrap_runtime._verify_posix_writable_directory(
                directory,
                runtime_uid=1001,
                runtime_gid=1002,
            )

    def test_verify_rejects_missing_or_symlinked_writable_directory(self) -> None:
        with mock.patch.object(bootstrap_runtime, "_is_windows", return_value=True):
            bootstrap_runtime.init_runtime(self.root, self.manifest)
        writable_directories = (
            self.root / "runtime/freqtrade/home",
            self.root / "runtime/freqtrade/logs",
            self.root / "runtime/freqtrade-research/data",
            self.root / "runtime/freqtrade-research/backtest_results",
        )
        for directory in writable_directories:
            with self.subTest(directory=directory):
                directory.rmdir()
                with (
                    mock.patch.object(
                        bootstrap_runtime, "_is_windows", return_value=True
                    ),
                    self.assertRaisesRegex(
                        ValueError, "runtime writable directory"
                    ),
                ):
                    bootstrap_runtime.verify_runtime(self.root, self.manifest)
                directory.mkdir()

        logs = self.root / "runtime/freqtrade/logs"
        original_is_symlink = Path.is_symlink

        def fake_is_symlink(path: Path) -> bool:
            return path == logs or original_is_symlink(path)

        with (
            mock.patch.object(bootstrap_runtime, "_is_windows", return_value=True),
            mock.patch.object(Path, "is_symlink", fake_is_symlink),
            self.assertRaisesRegex(ValueError, "runtime writable directory"),
        ):
            bootstrap_runtime.verify_runtime(self.root, self.manifest)

    def test_windows_permission_branches_use_acl_proof(self) -> None:
        secret = self.root / "secret with spaces"
        secret.write_text("not-a-real-secret\n", encoding="utf-8")

        with mock.patch.object(bootstrap_runtime, "_is_windows", return_value=True):
            bootstrap_runtime._harden_secret_permissions(secret)
            bootstrap_runtime._verify_secret_permissions(secret, runtime_uid=1000)

        self.assertEqual(
            self.mock_windows_acl.call_args_list,
            [mock.call("harden", secret), mock.call("verify", secret)],
        )

    def test_windows_acl_wrapper_uses_argument_array_and_path_environment(self) -> None:
        secret = self.root / "secret path with spaces"
        completed = subprocess.CompletedProcess([], 0, "runtime secret ACL: OK\n", "")

        with (
            mock.patch.object(
                bootstrap_runtime.shutil,
                "which",
                return_value="C:/Program Files/PowerShell/powershell.exe",
            ),
            mock.patch.object(bootstrap_runtime.subprocess, "run", return_value=completed) as run,
        ):
            self.real_windows_acl("verify", secret)

        command = run.call_args.args[0]
        options = run.call_args.kwargs
        self.assertIsInstance(command, list)
        self.assertEqual(command[0], "C:/Program Files/PowerShell/powershell.exe")
        self.assertNotIn(str(secret), command)
        self.assertNotIn("shell", options)
        self.assertEqual(options["env"]["FREQTRADE_RUNTIME_SECRET_PATH"], str(secret))

    def test_windows_acl_failure_is_secret_safe_and_fails_closed(self) -> None:
        secret_value = "secret-value-that-must-not-appear-in-errors"
        secret = self.root / "secret"
        secret.write_text(secret_value + "\n", encoding="utf-8")
        completed = subprocess.CompletedProcess([], 1, "", "ACL command failed")

        with (
            mock.patch.object(bootstrap_runtime.shutil, "which", return_value="powershell.exe"),
            mock.patch.object(bootstrap_runtime.subprocess, "run", return_value=completed),
            self.assertRaisesRegex(ValueError, "Windows runtime secret ACL") as raised,
        ):
            self.real_windows_acl("verify", secret)
        self.assertNotIn(secret_value, str(raised.exception))

    @unittest.skipUnless(os.name == "nt", "Windows ACL integration test")
    def test_windows_init_and_verify_with_real_acl(self) -> None:
        with mock.patch.object(
            bootstrap_runtime,
            "_run_windows_acl",
            new=self.real_windows_acl,
        ):
            bootstrap_runtime.init_runtime(self.root, self.manifest)
            bootstrap_runtime.verify_runtime(self.root, self.manifest)

    @unittest.skipIf(os.name == "nt", "POSIX mode integration test")
    def test_posix_init_existing_and_rotated_secrets_are_0600(self) -> None:
        existing = self.root / "ft_userdata/secrets/freqtrade/api_password"
        existing.parent.mkdir(parents=True)
        existing.write_text("existing-secret-value-that-is-long-enough\n", encoding="utf-8")
        os.chmod(existing, 0o644)

        bootstrap_runtime.init_runtime(self.root, self.manifest)
        self.assertEqual(stat.S_IMODE(existing.stat().st_mode), 0o600)
        bootstrap_runtime.rotate_secrets(self.root, self.manifest, {"freqtrade"})
        for filename in bootstrap_runtime.SECRET_SPECS:
            path = existing.parent / filename
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_verify_accepts_initialized_runtime(self) -> None:
        bootstrap_runtime.init_runtime(self.root, self.manifest)

        bootstrap_runtime.verify_runtime(self.root, self.manifest)

    def test_posix_verify_uses_env_uid_and_requires_accessible_state(self) -> None:
        with (
            mock.patch.object(bootstrap_runtime, "_is_windows", return_value=False),
            mock.patch.object(bootstrap_runtime.os, "getuid", return_value=1001, create=True),
            mock.patch.object(bootstrap_runtime.os, "getgid", return_value=1002, create=True),
            mock.patch.object(bootstrap_runtime, "_harden_runtime_control_file"),
        ):
            bootstrap_runtime.init_runtime(self.root, self.manifest)

        with (
            mock.patch.object(bootstrap_runtime, "_is_windows", return_value=False),
            mock.patch.object(bootstrap_runtime.os, "getuid", return_value=1001, create=True),
            mock.patch.object(bootstrap_runtime.os, "getgid", return_value=1002, create=True),
            mock.patch.object(bootstrap_runtime, "_verify_runtime_control_file"),
            mock.patch.object(
                bootstrap_runtime, "_verify_secret_permissions"
            ) as verify_secret,
            mock.patch.object(
                bootstrap_runtime, "_verify_posix_writable_directory"
            ) as verify_directory,
        ):
            bootstrap_runtime.verify_runtime(self.root, self.manifest)

        self.assertTrue(verify_secret.call_args_list)
        self.assertTrue(all(call.args[1] == 1001 for call in verify_secret.call_args_list))
        self.assertEqual(verify_directory.call_count, 15)
        self.assertTrue(
            all(
                call.args[1:] == (1001, 1002)
                for call in verify_directory.call_args_list
            )
        )

        with (
            mock.patch.object(bootstrap_runtime, "_is_windows", return_value=False),
            mock.patch.object(bootstrap_runtime.os, "getuid", return_value=1001, create=True),
            mock.patch.object(bootstrap_runtime.os, "getgid", return_value=1002, create=True),
            mock.patch.object(bootstrap_runtime, "_verify_runtime_control_file"),
            mock.patch.object(bootstrap_runtime, "_verify_secret_permissions"),
            mock.patch.object(
                bootstrap_runtime,
                "_verify_posix_writable_directory",
                side_effect=ValueError("runtime writable directory permissions"),
            ),
            self.assertRaisesRegex(ValueError, "runtime writable directory permissions"),
        ):
            bootstrap_runtime.verify_runtime(self.root, self.manifest)

    def test_verify_rejects_duplicate_secret_values_without_printing_them(self) -> None:
        bootstrap_runtime.init_runtime(self.root, self.manifest)
        repeated = "repeated-secret-value-that-must-not-be-logged"
        for name in ("api_password", "jwt_secret_key"):
            (self.root / f"ft_userdata/secrets/freqtrade/{name}").write_text(
                repeated + "\n", encoding="utf-8"
            )

        with self.assertRaisesRegex(ValueError, "runtime secrets must be unique") as raised:
            bootstrap_runtime.verify_runtime(self.root, self.manifest)
        self.assertNotIn(repeated, str(raised.exception))

    def test_verify_rejects_short_secret_without_printing_it(self) -> None:
        bootstrap_runtime.init_runtime(self.root, self.manifest)
        short_secret = "too-short"
        path = self.root / "ft_userdata/secrets/freqtrade/ws_token"
        path.write_text(short_secret + "\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "runtime secret policy failed") as raised:
            bootstrap_runtime.verify_runtime(self.root, self.manifest)
        self.assertNotIn(short_secret, str(raised.exception))

    def test_sanitize_changes_only_api_server_secret_fields(self) -> None:
        bootstrap_runtime.init_runtime(self.root, self.manifest)
        config_path = self.root / "configs/spot.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["api_server"].update(
            {"password": "old-password", "jwt_secret_key": "old-jwt", "ws_token": "old-ws"}
        )
        config["exchange"]["name"] = "okx"
        config["unchanged"] = {"nested": [1, 2, 3]}
        config_path.write_text(json.dumps(config), encoding="utf-8")
        expected = copy.deepcopy(config)
        for key in ("password", "jwt_secret_key", "ws_token"):
            expected["api_server"][key] = SENTINEL

        bootstrap_runtime.sanitize_api_configs(self.root, self.manifest)

        sanitized = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(sanitized, expected)

    def test_rotate_secrets_changes_only_the_requested_service(self) -> None:
        bootstrap_runtime.init_runtime(self.root, self.manifest)
        before = self.read_all_secret_values()

        bootstrap_runtime.rotate_secrets(
            self.root,
            self.manifest,
            service_names={"freqtrade"},
        )

        after = self.read_all_secret_values()
        self.assertNotEqual(before["freqtrade"], after["freqtrade"])
        self.assertEqual(before["freqtrade-futures"], after["freqtrade-futures"])
        self.assertEqual(before["freqtrade-research"], after["freqtrade-research"])
        self.assertEqual(len(after["freqtrade"]), len(set(after["freqtrade"])))
        self.assertTrue(all(len(value) >= 32 for value in after["freqtrade"]))

    def test_rotate_rejects_unknown_service_without_changing_files(self) -> None:
        bootstrap_runtime.init_runtime(self.root, self.manifest)
        before = self.read_all_secret_values()

        with self.assertRaisesRegex(ValueError, "unknown runtime service"):
            bootstrap_runtime.rotate_secrets(
                self.root,
                self.manifest,
                service_names={"freqtrade", "missing-bot"},
            )

        self.assertEqual(before, self.read_all_secret_values())


if __name__ == "__main__":
    unittest.main()
