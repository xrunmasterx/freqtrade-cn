from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


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
VALID_STRATEGY = (
    b"import module_that_must_not_be_imported\nclass SampleStrategy: pass\n"
)
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
            git(
                self.root,
                "update-index",
                "--add",
                "--cacheinfo",
                "160000",
                commit,
                path,
            )
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
    from tools import bootstrap_runtime, runtime_artifacts
    from tools.runtime_artifacts import (
        CommittedPaperProbeMaterialProvider,
        CommittedPaperProbeArtifacts,
        VerifiedReadOnlyMaterial,
        VerifiedReadOnlyMaterialLease,
        read_committed_paper_probe_artifacts,
    )
except ModuleNotFoundError as error:
    RUNTIME_ARTIFACTS_IMPORT_ERROR: ModuleNotFoundError | None = error
else:
    RUNTIME_ARTIFACTS_IMPORT_ERROR = None


class RuntimeArtifactsAvailabilityTests(unittest.TestCase):
    def test_runtime_artifacts_module_exists(self) -> None:
        self.assertIsNone(RUNTIME_ARTIFACTS_IMPORT_ERROR)


@unittest.skipIf(
    RUNTIME_ARTIFACTS_IMPORT_ERROR is not None, "runtime_artifacts is missing"
)
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

    def test_hashes_committed_raw_bytes_and_rechecks_dirty_worktree_next_time(
        self,
    ) -> None:
        artifacts = self.read()
        self.fixture.write_bytes(CONFIG_PATH, b"credential-secret-marker\n")
        self.assertEqual(
            artifacts.config_sha256,
            hashlib.sha256(
                json.dumps(VALID_CONFIG).encode("utf-8") + b"\n"
            ).hexdigest(),
        )
        with self.assertRaisesRegex(ValueError, "checkout must be clean") as caught:
            self.read()
        self.assertNotIn("credential-secret-marker", str(caught.exception))
        self.assertNotIn(str(self.fixture.root), repr(caught.exception))

    def test_config_requires_exact_paper_spot_bitget_and_empty_write_credentials(
        self,
    ) -> None:
        variants = (
            ({**VALID_CONFIG, "dry_run": 1}, "dry_run"),
            ({**VALID_CONFIG, "dry_run": False}, "dry_run"),
            ({**VALID_CONFIG, "trading_mode": "futures"}, "trading_mode"),
            (
                {
                    **VALID_CONFIG,
                    "exchange": {**VALID_CONFIG["exchange"], "name": "binance"},
                },
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
                    exchange = {
                        **VALID_CONFIG["exchange"],
                        bag: override,
                        "marker": marker,
                    }
                    commit = self.fixture.commit_json(
                        CONFIG_PATH,
                        {**VALID_CONFIG, "exchange": exchange},
                        f"invalid product override {bag} {index}",
                    )
                    with self.assertRaisesRegex(ValueError, "CCXT product") as caught:
                        self.read(commit)
                    self.assertNotIn(marker, str(caught.exception))
                    self.assertNotIn(marker, repr(caught.exception))

    def test_config_and_safety_reject_duplicate_keys_and_nonfinite_numbers(
        self,
    ) -> None:
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
                    commit = fixture.commit_json(
                        SAFETY_PATH, {"dry_run": value}, "unsafe"
                    )
                    with self.assertRaisesRegex(ValueError, "dry_run"):
                        read_committed_paper_probe_artifacts(fixture.root, commit)

    def test_strategy_is_parsed_without_import_or_execution(self) -> None:
        strategy = (
            b"raise RuntimeError('must not execute')\nclass SampleStrategy: pass\n"
        )
        commit = self.fixture.commit_bytes(
            STRATEGY_PATH, strategy, "nonexecuted strategy"
        )
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
        object_id = (
            subprocess.run(
                ["git", "-C", str(self.fixture.root), "hash-object", "-w", "--stdin"],
                input=b"ordinary blob\n",
                check=True,
                capture_output=True,
            )
            .stdout.decode("ascii")
            .strip()
        )
        git(
            self.fixture.root,
            "update-index",
            "--cacheinfo",
            "100644",
            object_id,
            "freqtrade",
        )
        commit = self.fixture.create_index_commit("ordinary blob component")
        with self.assertRaisesRegex(ValueError, "160000 commit"):
            self.read(commit)


@unittest.skipIf(
    RUNTIME_ARTIFACTS_IMPORT_ERROR is not None, "runtime_artifacts is missing"
)
class CommittedPaperProbeMaterialProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.fixture = RuntimeArtifactFixture(Path(self.temporary_directory.name))
        self.permissions_patcher = None
        if os.name == "nt":
            self.permissions_patcher = mock.patch.object(
                runtime_artifacts,
                "_verify_material_source_chain_permissions",
            )
            self.permissions_patcher.start()
            self.addCleanup(self.permissions_patcher.stop)
        self.provider = CommittedPaperProbeMaterialProvider(
            self.fixture.root,
            self.fixture.commit,
        )
        self.addCleanup(self.provider.close)

    def test_mints_exact_frozen_attempt_scoped_materials_in_closed_order(self) -> None:
        lease = self.provider.mint_lease("attempt-1")
        self.addCleanup(lease.close)

        self.assertIsInstance(lease, VerifiedReadOnlyMaterialLease)
        self.assertEqual(lease.attempt_id, "attempt-1")
        self.assertEqual(
            lease.provider_id,
            "committed-paper-probe-material-v1",
        )
        self.assertEqual(
            tuple(material.role for material in lease.materials),
            ("runtime_config", "safety_policy", "strategy"),
        )
        expected_paths = (CONFIG_PATH, SAFETY_PATH, STRATEGY_PATH)
        for material, relative_path in zip(
            lease.materials, expected_paths, strict=True
        ):
            self.assertIsInstance(material, VerifiedReadOnlyMaterial)
            self.assertEqual(material.attempt_id, "attempt-1")
            self.assertEqual(material.provider_id, lease.provider_id)
            self.assertEqual(material.root_commit, self.fixture.commit)
            self.assertEqual(material.repository_relative_path, relative_path)
            self.assertEqual(
                material.source_path,
                (self.fixture.root / relative_path).resolve(strict=True),
            )
            self.assertEqual(
                material.blob_sha256,
                hashlib.sha256(
                    (self.fixture.root / relative_path).read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(
                material.strategy_class_name,
                "SampleStrategy" if material.role == "strategy" else None,
            )
            self.assertNotIn(str(self.fixture.root), repr(material))
            with self.assertRaises(dataclasses.FrozenInstanceError):
                material.role = "changed"

        self.assertIsNone(lease.revalidate_sources())
        self.assertNotIn(str(self.fixture.root), repr(lease))

    def test_context_close_is_idempotent_and_revalidation_after_close_is_invalid(
        self,
    ) -> None:
        with self.provider.mint_lease("attempt-context") as lease:
            self.assertIsNone(lease.revalidate_sources())
        lease.close()
        with self.assertRaisesRegex(ValueError, "^material_lease_invalid$") as caught:
            lease.revalidate_sources()
        with self.assertRaisesRegex(ValueError, "^material_lease_invalid$"):
            _ = lease.materials
        self.assertNotIn(str(self.fixture.root), repr(caught.exception))

    def test_replaced_strategy_attestation_invalidates_registry_without_disclosure(
        self,
    ) -> None:
        lease = self.provider.mint_lease("attempt-attestation")
        self.addCleanup(lease.close)
        record = self.provider._leases[lease._token]
        marker = "ForgedStrategySecretMarker"
        record.materials = tuple(
            dataclasses.replace(
                material,
                strategy_class_name=(marker if material.role == "strategy" else None),
            )
            for material in record.materials
        )

        for action in (lambda: lease.materials, lease.revalidate_sources):
            with self.subTest(action=action):
                with self.assertRaisesRegex(
                    ValueError,
                    "^material_lease_invalid$",
                ) as caught:
                    action()
                self.assertNotIn(marker, str(caught.exception))
                self.assertNotIn(marker, repr(caught.exception))
        self.assertNotIn(marker, repr(lease))

    def test_attempt_identity_uses_closed_lowercase_grammar(self) -> None:
        for attempt_id in ("Attempt-1", "attempt.1", "attempt/1", "", "a" * 129):
            with self.subTest(attempt_id=attempt_id):
                with self.assertRaisesRegex(ValueError, "^material_lease_invalid$"):
                    self.provider.mint_lease(attempt_id)

    def test_forged_or_retagged_lease_fails_closed(self) -> None:
        lease = self.provider.mint_lease("attempt-real")
        self.addCleanup(lease.close)

        forged = object.__new__(VerifiedReadOnlyMaterialLease)
        for name, value in (
            ("_provider", self.provider),
            ("_token", object()),
            ("_closed", False),
        ):
            object.__setattr__(forged, name, value)
        for action in (
            lambda: forged.materials,
            forged.__enter__,
            forged.revalidate_sources,
            forged.close,
        ):
            with self.assertRaisesRegex(ValueError, "^material_lease_invalid$"):
                action()

        with self.assertRaises(AttributeError):
            object.__setattr__(lease, "_attempt_id", "attempt-other")
        issued_material = lease.materials[0]
        object.__setattr__(issued_material, "role", "forged_role")
        for action in (lambda: lease.materials, lease.revalidate_sources):
            with self.assertRaisesRegex(ValueError, "^material_lease_invalid$"):
                action()
        lease.close()

    def test_holds_private_descriptors_until_close_and_closes_each_once(self) -> None:
        lease = self.provider.mint_lease("attempt-descriptors")
        materials = lease.materials
        with mock.patch("tools.runtime_artifacts.os.close", wraps=os.close) as close:
            lease.close()
            lease.close()
        self.assertEqual(close.call_count, 3)
        self.assertFalse(any(hasattr(material, "descriptor") for material in materials))

    def test_close_attempts_every_descriptor_before_control_error(self) -> None:
        opened: list[int] = []
        real_open = runtime_artifacts._open_nofollow_read
        real_close = os.close

        def recording_open(path: Path) -> int:
            descriptor = real_open(path)
            opened.append(descriptor)
            return descriptor

        with mock.patch.object(
            runtime_artifacts,
            "_open_nofollow_read",
            side_effect=recording_open,
        ):
            lease = self.provider.mint_lease("attempt-close-interrupted")

        attempted: list[int] = []

        def interrupt_first_close(descriptor: int) -> None:
            attempted.append(descriptor)
            if len(attempted) == 1:
                raise KeyboardInterrupt
            real_close(descriptor)

        with (
            mock.patch.object(
                runtime_artifacts.os,
                "close",
                side_effect=interrupt_first_close,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            lease.close()

        self.assertEqual(attempted, [opened[0], opened[0], *opened[1:]])
        self.assertFalse(lease._closed)
        self.assertEqual(len(self.provider._leases), 1)
        for descriptor in opened:
            with self.assertRaises(OSError):
                os.fstat(descriptor)
        lease.close()
        self.assertTrue(lease._closed)
        self.assertFalse(self.provider._leases)

    def test_ancestor_commit_with_different_clean_head_bytes_is_rejected(self) -> None:
        ancestor = self.fixture.commit
        self.fixture.commit_json(
            CONFIG_PATH,
            {**VALID_CONFIG, "stake_currency": "USDC"},
            "new clean head config",
        )
        provider = CommittedPaperProbeMaterialProvider(self.fixture.root, ancestor)
        self.addCleanup(provider.close)
        with self.assertRaisesRegex(
            ValueError,
            "^material_source_verification_failed$",
        ):
            provider.mint_lease("attempt-ancestor")

    def test_leaf_content_drift_invalidates_live_lease_without_disclosure(self) -> None:
        lease = self.provider.mint_lease("attempt-content")
        self.addCleanup(lease.close)
        marker = "material-content-secret-marker"
        with (
            mock.patch(
                "tools.runtime_artifacts._descriptor_sha256",
                return_value=hashlib.sha256(marker.encode()).hexdigest(),
            ),
            self.assertRaisesRegex(
                ValueError,
                "^material_source_verification_failed$",
            ) as caught,
        ):
            lease.revalidate_sources()
        self.assertNotIn(marker, str(caught.exception))
        self.assertNotIn(str(self.fixture.root), repr(caught.exception))

    def test_leaf_hardlink_is_rejected_even_when_checkout_bytes_are_clean(self) -> None:
        peer = Path(self.temporary_directory.name) / "strategy-hardlink-peer"
        os.link(self.fixture.root / STRATEGY_PATH, peer)
        with self.assertRaisesRegex(
            ValueError,
            "^material_source_verification_failed$",
        ):
            self.provider.mint_lease("attempt-hardlink")

    def test_link_or_reparse_component_is_rejected_before_open(self) -> None:
        real_lstat = os.lstat
        rejected_path = self.fixture.root / "ft_userdata" / "user_data"

        def reparse_component(path: Path) -> os.stat_result | SimpleNamespace:
            status = real_lstat(path)
            if Path(path) != rejected_path:
                return status
            return SimpleNamespace(
                st_mode=status.st_mode,
                st_dev=status.st_dev,
                st_ino=status.st_ino,
                st_nlink=status.st_nlink,
                st_size=status.st_size,
                st_mtime_ns=status.st_mtime_ns,
                st_ctime_ns=status.st_ctime_ns,
                st_file_attributes=getattr(status, "st_file_attributes", 0)
                | getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
            )

        with (
            mock.patch(
                "tools.runtime_artifacts.os.lstat", side_effect=reparse_component
            ),
            mock.patch("tools.runtime_artifacts._open_nofollow_read") as opened,
            self.assertRaisesRegex(
                ValueError,
                "^material_source_verification_failed$",
            ),
        ):
            self.provider.mint_lease("attempt-reparse")
        opened.assert_not_called()

    def test_unsafe_material_source_permissions_are_rejected(self) -> None:
        rejected_path = self.fixture.root / "ft_userdata" / "user_data"
        real_verify = runtime_artifacts._verify_material_source_chain_permissions

        def reject_directory(
            components: tuple[tuple[Path, os.stat_result], ...],
        ) -> None:
            if any(Path(path) == rejected_path for path, _ in components):
                raise ValueError("untrusted writer")
            real_verify(components)

        with (
            mock.patch.object(
                runtime_artifacts,
                "_verify_material_source_chain_permissions",
                side_effect=reject_directory,
            ),
            self.assertRaisesRegex(
                ValueError,
                "^material_source_verification_failed$",
            ),
        ):
            self.provider.mint_lease("attempt-permissions")

    @unittest.skipUnless(os.name == "nt", "Windows ACL integration test")
    def test_windows_hardened_checkout_sources_mint_and_revalidate_real_lease(
        self,
    ) -> None:
        assert self.permissions_patcher is not None
        self.permissions_patcher.stop()
        bootstrap_runtime._harden_windows_trusted_directory_permissions(
            self.fixture.root
        )

        with self.provider.mint_lease("attempt-windows-real-acl") as lease:
            self.assertIsNone(lease.revalidate_sources())

    @unittest.skipIf(os.name == "nt", "POSIX permission semantics only")
    def test_posix_group_writable_source_ancestor_is_rejected(self) -> None:
        ancestor = self.fixture.root / "ft_userdata" / "user_data"
        original_mode = stat.S_IMODE(os.lstat(ancestor).st_mode)
        os.chmod(ancestor, original_mode | 0o020)
        self.addCleanup(os.chmod, ancestor, original_mode)

        with self.assertRaisesRegex(
            ValueError,
            "^material_source_verification_failed$",
        ):
            self.provider.mint_lease("attempt-posix-permissions")

    def test_ancestor_identity_replacement_invalidates_live_lease(self) -> None:
        lease = self.provider.mint_lease("attempt-parent")
        self.addCleanup(lease.close)
        real_lstat = os.lstat
        replaced_path = self.fixture.root / "ft_userdata" / "user_data"

        def replaced_component(path: Path) -> os.stat_result | SimpleNamespace:
            status = real_lstat(path)
            if Path(path) != replaced_path:
                return status
            return SimpleNamespace(
                st_mode=status.st_mode,
                st_dev=status.st_dev,
                st_ino=status.st_ino + 1,
                st_nlink=status.st_nlink,
                st_size=status.st_size,
                st_mtime_ns=status.st_mtime_ns,
                st_ctime_ns=status.st_ctime_ns,
                st_file_attributes=getattr(status, "st_file_attributes", 0),
            )

        with (
            mock.patch(
                "tools.runtime_artifacts.os.lstat", side_effect=replaced_component
            ),
            self.assertRaisesRegex(
                ValueError,
                "^material_source_verification_failed$",
            ),
        ):
            lease.revalidate_sources()


if __name__ == "__main__":
    unittest.main()
