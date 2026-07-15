from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


CONFIG_PATH = "ft_userdata/user_data/config.example.json"
STRATEGY_PATH = "ft_userdata/user_data/strategies/sample_strategy.py"
SAFETY_PATH = "ops/config/trading-safety.json"
COMPONENTS = {
    "freqtrade": "1" * 40,
    "frequi": "2" * 40,
    "freqtrade-strategies": "3" * 40,
}
VALID_CONFIG = {
    "dry_run": True,
    "trading_mode": "spot",
    "exchange": {
        "name": "bitget",
        "key": "",
        "secret": "",
        "password": "",
    },
}
VALID_SAFETY = {"dry_run": True, "ignore_buying_expired_candle_after": 60}
VALID_STRATEGY = b"import module_that_must_not_be_imported\nclass SampleStrategy: pass\n"
EXCHANGE_SENSITIVE_ALIASES = (
    "key",
    "api_key",
    "apiKey",
    "secret",
    "password",
    "uid",
    "account_id",
    "accountId",
    "wallet_address",
    "walletAddress",
    "private_key",
    "privateKey",
)
CCXT_CONFIG_BAGS = ("ccxt_config", "ccxt_sync_config", "ccxt_async_config")


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
    )
    return result.stdout.decode("ascii").strip()


class RuntimeArtifactFixture:
    def __init__(self, parent: Path) -> None:
        self.root = parent / "repository"
        self.root.mkdir()
        git(self.root, "init", "--quiet")
        git(self.root, "config", "user.email", "runtime-artifacts@example.invalid")
        git(self.root, "config", "user.name", "Runtime Artifact Tests")
        git(self.root, "config", "core.autocrlf", "false")
        git(self.root, "config", "core.filemode", "false")
        git(self.root, "config", "core.symlinks", "false")
        self.write_json(CONFIG_PATH, VALID_CONFIG)
        self.write_bytes(STRATEGY_PATH, VALID_STRATEGY)
        self.write_json(SAFETY_PATH, VALID_SAFETY)
        git(self.root, "add", "--all", "--", ".")
        for path, commit in COMPONENTS.items():
            git(self.root, "update-index", "--add", "--cacheinfo", "160000", commit, path)
        self.commit = self.create_index_commit("initial artifacts")

    def write_bytes(self, relative_path: str, contents: bytes) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    def write_json(self, relative_path: str, payload: object) -> None:
        self.write_bytes(relative_path, json.dumps(payload).encode("utf-8") + b"\n")

    def create_index_commit(self, message: str) -> str:
        git(self.root, "commit", "--quiet", "-m", message)
        return git(self.root, "rev-parse", "HEAD")

    def commit_bytes(self, path: str, contents: bytes, message: str) -> str:
        self.write_bytes(path, contents)
        git(self.root, "add", "--", path)
        return self.create_index_commit(message)

    def commit_json(self, path: str, payload: object, message: str) -> str:
        self.write_json(path, payload)
        git(self.root, "add", "--", path)
        return self.create_index_commit(message)


try:
    from tools.runtime_artifacts import (
        CommittedPaperProbeArtifacts,
        read_committed_paper_probe_artifacts,
    )
except ModuleNotFoundError as error:
    RUNTIME_ARTIFACTS_IMPORT_ERROR: ModuleNotFoundError | None = error
else:
    RUNTIME_ARTIFACTS_IMPORT_ERROR = None


class RuntimeArtifactsAvailabilityTests(unittest.TestCase):
    def test_runtime_artifacts_module_exists(self) -> None:
        self.assertIsNone(RUNTIME_ARTIFACTS_IMPORT_ERROR)


@unittest.skipIf(RUNTIME_ARTIFACTS_IMPORT_ERROR is not None, "runtime_artifacts is missing")
class RuntimeArtifactsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.fixture = RuntimeArtifactFixture(Path(self.temporary_directory.name))

    def read(self, commit: str | None = None) -> CommittedPaperProbeArtifacts:
        return read_committed_paper_probe_artifacts(
            self.fixture.root,
            self.fixture.commit if commit is None else commit,
        )

    def test_api_accepts_only_object_store_and_commit(self) -> None:
        signature = inspect.signature(read_committed_paper_probe_artifacts)
        self.assertEqual(tuple(signature.parameters), ("root", "commit"))

    def test_returns_only_frozen_serialization_safe_committed_identities(self) -> None:
        artifacts = self.read()
        expected = {
            "root_commit": self.fixture.commit,
            "backend_commit": COMPONENTS["freqtrade"],
            "frontend_commit": COMPONENTS["frequi"],
            "strategies_commit": COMPONENTS["freqtrade-strategies"],
            "config_sha256": hashlib.sha256(
                (self.fixture.root / CONFIG_PATH).read_bytes()
            ).hexdigest(),
            "strategy_sha256": hashlib.sha256(VALID_STRATEGY).hexdigest(),
            "safety_sha256": hashlib.sha256(
                (self.fixture.root / SAFETY_PATH).read_bytes()
            ).hexdigest(),
            "strategy_class_name": "SampleStrategy",
        }
        self.assertEqual(dataclasses.asdict(artifacts), expected)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            artifacts.root_commit = "changed"
        rendered = repr(artifacts)
        self.assertNotIn(str(self.fixture.root), rendered)
        self.assertNotIn("module_that_must_not_be_imported", rendered)

    def test_hashes_committed_raw_bytes_and_rechecks_dirty_worktree_next_time(self) -> None:
        artifacts = self.read()
        self.fixture.write_bytes(CONFIG_PATH, b'credential-secret-marker\n')
        self.assertEqual(
            artifacts.config_sha256,
            hashlib.sha256(json.dumps(VALID_CONFIG).encode("utf-8") + b"\n").hexdigest(),
        )
        with self.assertRaisesRegex(ValueError, "checkout must be clean") as caught:
            self.read()
        self.assertNotIn("credential-secret-marker", str(caught.exception))
        self.assertNotIn(str(self.fixture.root), repr(caught.exception))

    def test_config_requires_exact_paper_spot_bitget_and_empty_write_credentials(self) -> None:
        variants = (
            ({**VALID_CONFIG, "dry_run": 1}, "dry_run"),
            ({**VALID_CONFIG, "dry_run": False}, "dry_run"),
            ({**VALID_CONFIG, "trading_mode": "futures"}, "trading_mode"),
            (
                {**VALID_CONFIG, "exchange": {**VALID_CONFIG["exchange"], "name": "binance"}},
                "exchange",
            ),
            *(
                (
                    {
                        **VALID_CONFIG,
                        "exchange": {
                            **VALID_CONFIG["exchange"],
                            field: "credential-secret-marker",
                        },
                    },
                    "credential",
                )
                for field in ("key", "secret", "password")
            ),
        )
        for payload, message in variants:
            with self.subTest(message=message):
                with tempfile.TemporaryDirectory() as directory:
                    fixture = RuntimeArtifactFixture(Path(directory))
                    commit = fixture.commit_json(CONFIG_PATH, payload, message)
                    with self.assertRaisesRegex(ValueError, message) as caught:
                        read_committed_paper_probe_artifacts(fixture.root, commit)
                    self.assertNotIn("credential-secret-marker", str(caught.exception))

    def test_all_exchange_sensitive_aliases_allow_none_or_empty_string(self) -> None:
        exchange = {
            **VALID_CONFIG["exchange"],
            **{
                alias: None if index % 2 else ""
                for index, alias in enumerate(EXCHANGE_SENSITIVE_ALIASES)
            },
        }
        allowed_commit = self.fixture.commit_json(
            CONFIG_PATH,
            {**VALID_CONFIG, "exchange": exchange},
            "allowed empty credential aliases",
        )
        try:
            self.read(allowed_commit)
        except ValueError:
            self.fail("empty exchange credential alias was rejected")

    def test_all_exchange_sensitive_aliases_reject_nonempty_values(self) -> None:
        marker = "top-level-credential-secret-marker"
        for alias in EXCHANGE_SENSITIVE_ALIASES:
            with self.subTest(alias=alias):
                commit = self.fixture.commit_json(
                    CONFIG_PATH,
                    {
                        **VALID_CONFIG,
                        "exchange": {**VALID_CONFIG["exchange"], alias: marker},
                    },
                    f"nonempty top-level {alias}",
                )
                with self.assertRaisesRegex(ValueError, "credential") as caught:
                    self.read(commit)
                self.assertNotIn(marker, str(caught.exception))
                self.assertNotIn(marker, repr(caught.exception))

    def test_nested_ccxt_sensitive_aliases_allow_only_empty_values(self) -> None:
        empty_aliases = {
            alias: None if index % 2 else ""
            for index, alias in enumerate(EXCHANGE_SENSITIVE_ALIASES)
        }
        allowed_exchange = {
            **VALID_CONFIG["exchange"],
            **{
                bag: {"options": {"credentials": empty_aliases}}
                for bag in CCXT_CONFIG_BAGS
            },
        }
        allowed_commit = self.fixture.commit_json(
            CONFIG_PATH,
            {**VALID_CONFIG, "exchange": allowed_exchange},
            "allowed nested empty credentials",
        )
        self.read(allowed_commit)

        marker = "nested-credential-secret-marker"
        for bag in CCXT_CONFIG_BAGS:
            for alias in EXCHANGE_SENSITIVE_ALIASES:
                with self.subTest(bag=bag, alias=alias):
                    exchange = {
                        **VALID_CONFIG["exchange"],
                        bag: {"options": {"credentials": {alias: marker}}},
                    }
                    commit = self.fixture.commit_json(
                        CONFIG_PATH,
                        {**VALID_CONFIG, "exchange": exchange},
                        f"nonempty nested {bag} {alias}",
                    )
                    with self.assertRaisesRegex(ValueError, "credential") as caught:
                        self.read(commit)
                    self.assertNotIn(marker, str(caught.exception))
                    self.assertNotIn(marker, repr(caught.exception))

    def test_ccxt_product_overrides_are_closed_to_spot(self) -> None:
        allowed_exchange = {
            **VALID_CONFIG["exchange"],
            "ccxt_config": {
                "defaultType": "spot",
                "options": {"fetchMarkets": {"types": ["spot"]}},
            },
            "ccxt_sync_config": {"options": {"default_type": "spot"}},
            "ccxt_async_config": {"nested": {"defaultType": "spot"}},
        }
        allowed_commit = self.fixture.commit_json(
            CONFIG_PATH,
            {**VALID_CONFIG, "exchange": allowed_exchange},
            "allowed spot ccxt overrides",
        )
        self.read(allowed_commit)

        invalid_overrides = (
            {"defaultType": "swap"},
            {"options": {"default_type": "future"}},
            {"options": {"fetchMarkets": {"types": ["spot", "swap"]}}},
            {"options": {"fetchMarkets": "product-secret-marker"}},
        )
        marker = "product-secret-marker"
        for bag in CCXT_CONFIG_BAGS:
            for index, override in enumerate(invalid_overrides):
                with self.subTest(bag=bag, index=index):
                    exchange = {**VALID_CONFIG["exchange"], bag: override, "marker": marker}
                    commit = self.fixture.commit_json(
                        CONFIG_PATH,
                        {**VALID_CONFIG, "exchange": exchange},
                        f"invalid product override {bag} {index}",
                    )
                    with self.assertRaisesRegex(ValueError, "CCXT product") as caught:
                        self.read(commit)
                    self.assertNotIn(marker, str(caught.exception))
                    self.assertNotIn(marker, repr(caught.exception))

    def test_config_and_safety_reject_duplicate_keys_and_nonfinite_numbers(self) -> None:
        variants = (
            (CONFIG_PATH, b'{"dry_run":true,"dry_run":true}\n', "duplicate"),
            (CONFIG_PATH, b'{"dry_run":true,"value":NaN}\n', "non-finite"),
            (CONFIG_PATH, b'{"dry_run":true,"value":1e9999}\n', "non-finite"),
            (SAFETY_PATH, b'{"dry_run":true,"dry_run":true}\n', "duplicate"),
            (SAFETY_PATH, b'{"dry_run":true,"value":Infinity}\n', "non-finite"),
            (SAFETY_PATH, b'{"dry_run":true,"value":-1e9999}\n', "non-finite"),
        )
        for path, contents, message in variants:
            with self.subTest(path=path, message=message):
                with tempfile.TemporaryDirectory() as directory:
                    fixture = RuntimeArtifactFixture(Path(directory))
                    commit = fixture.commit_bytes(path, contents, message)
                    with self.assertRaisesRegex(ValueError, message):
                        read_committed_paper_probe_artifacts(fixture.root, commit)

    def test_safety_requires_exact_boolean_dry_run(self) -> None:
        for value in (False, 1, "true", None):
            with self.subTest(value=value):
                with tempfile.TemporaryDirectory() as directory:
                    fixture = RuntimeArtifactFixture(Path(directory))
                    commit = fixture.commit_json(SAFETY_PATH, {"dry_run": value}, "unsafe")
                    with self.assertRaisesRegex(ValueError, "dry_run"):
                        read_committed_paper_probe_artifacts(fixture.root, commit)

    def test_strategy_is_parsed_without_import_or_execution(self) -> None:
        strategy = b"raise RuntimeError('must not execute')\nclass SampleStrategy: pass\n"
        commit = self.fixture.commit_bytes(STRATEGY_PATH, strategy, "nonexecuted strategy")
        artifacts = self.read(commit)
        self.assertEqual(artifacts.strategy_class_name, "SampleStrategy")

    def test_strategy_requires_exactly_one_fixed_class(self) -> None:
        variants = (
            (b"class DifferentStrategy: pass\n", "SampleStrategy"),
            (b"class SampleStrategy: pass\nclass Other: pass\n", "exactly one"),
            (b"class SampleStrategy(:\n", "syntax"),
        )
        for contents, message in variants:
            with self.subTest(message=message):
                with tempfile.TemporaryDirectory() as directory:
                    fixture = RuntimeArtifactFixture(Path(directory))
                    commit = fixture.commit_bytes(STRATEGY_PATH, contents, message)
                    with self.assertRaisesRegex(ValueError, message):
                        read_committed_paper_probe_artifacts(fixture.root, commit)

    def test_component_positions_require_exact_gitlinks(self) -> None:
        object_id = subprocess.run(
            ["git", "-C", str(self.fixture.root), "hash-object", "-w", "--stdin"],
            input=b"ordinary blob\n",
            check=True,
            capture_output=True,
        ).stdout.decode("ascii").strip()
        git(self.fixture.root, "update-index", "--cacheinfo", "100644", object_id, "freqtrade")
        commit = self.fixture.create_index_commit("ordinary blob component")
        with self.assertRaisesRegex(ValueError, "160000 commit"):
            self.read(commit)


if __name__ == "__main__":
    unittest.main()
