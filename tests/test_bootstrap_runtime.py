from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tools import bootstrap_runtime
from tools.bootstrap_runtime import SENTINEL
from tools.runtime_manifest import load_runtime_manifest


class BootstrapRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
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
        path = self.root / "runtime-services.json"
        path.write_text(
            json.dumps({"schema_version": 1, "services": services}),
            encoding="utf-8",
        )
        return path

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

        with self.assertRaisesRegex(ValueError, "schema_version must be 1"):
            load_runtime_manifest(manifest)

    def test_load_manifest_rejects_missing_service_keys(self) -> None:
        service = self.service("freqtrade")
        del service["state_root"]
        manifest = self.write_manifest([service])

        with self.assertRaisesRegex(ValueError, "missing keys: state_root"):
            load_runtime_manifest(manifest)

    def test_load_manifest_rejects_unsupported_role(self) -> None:
        manifest = self.write_manifest([self.service("freqtrade", role="admin")])

        with self.assertRaisesRegex(ValueError, "unsupported runtime role"):
            load_runtime_manifest(manifest)

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

    def test_verify_accepts_initialized_runtime(self) -> None:
        bootstrap_runtime.init_runtime(self.root, self.manifest)

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
