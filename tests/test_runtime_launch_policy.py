from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path, PurePosixPath

from tests.test_runtime_templates import (
    GitFixture,
    LAUNCH_POLICY_CATALOG,
    TEMPLATE_DOCUMENTS,
    canonical_json,
    git,
)


try:
    from tools.runtime_launch_policy import (
        CommandToken,
        CommandTokenKind,
        EnvironmentBindingKind,
        MaterialKind,
        MaterialMountPolicy,
        NetworkIdentitySource,
        NetworkNameDerivation,
        NetworkRule,
        ResolvedLaunchPolicyBundle,
        load_resolved_launch_policy_bundle,
    )
except ModuleNotFoundError as error:
    RUNTIME_LAUNCH_POLICY_IMPORT_ERROR: ModuleNotFoundError | None = error
else:
    RUNTIME_LAUNCH_POLICY_IMPORT_ERROR = None


class RuntimeLaunchPolicyAvailabilityTests(unittest.TestCase):
    def test_runtime_launch_policy_module_exists(self) -> None:
        self.assertIsNone(RUNTIME_LAUNCH_POLICY_IMPORT_ERROR)

    def test_import_under_python_s_performs_no_io(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                "import tools.runtime_launch_policy; print('ok')",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "ok\n")


@unittest.skipIf(
    RUNTIME_LAUNCH_POLICY_IMPORT_ERROR is not None,
    "runtime_launch_policy is missing",
)
class RuntimeLaunchPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.fixture = GitFixture(Path(self.temporary_directory.name))

    def load(self) -> ResolvedLaunchPolicyBundle:
        return load_resolved_launch_policy_bundle(
            self.fixture.root,
            "freqtrade-paper-probe-v1",
            self.fixture.commit,
        )

    def commit_catalog(self, payload: object) -> None:
        self.fixture.write_json(
            "ops/runtime-policies/launch-policy-catalog.json",
            payload,
        )
        self.fixture.commit = self.fixture.create_commit("mutated catalog")

    def test_loads_exact_committed_typed_bundle_and_digests(self) -> None:
        bundle = self.load()
        template_document = canonical_json(
            TEMPLATE_DOCUMENTS["freqtrade-paper-probe-v1"]
        )
        policy = LAUNCH_POLICY_CATALOG["policies"][0]

        self.assertIsInstance(bundle, ResolvedLaunchPolicyBundle)
        self.assertEqual(bundle.template_id, "freqtrade-paper-probe-v1")
        self.assertEqual(bundle.source_commit, self.fixture.commit)
        self.assertEqual(
            bundle.catalog_source_path,
            "ops/runtime-policies/launch-policy-catalog.json",
        )
        self.assertEqual(
            bundle.catalog_blob_id,
            git(
                self.fixture.root,
                "rev-parse",
                f"{self.fixture.commit}:ops/runtime-policies/launch-policy-catalog.json",
            ),
        )
        self.assertEqual(
            bundle.template_digest,
            hashlib.sha256(template_document).hexdigest(),
        )
        self.assertEqual(
            bundle.catalog_digest,
            hashlib.sha256(canonical_json(LAUNCH_POLICY_CATALOG)).hexdigest(),
        )
        self.assertEqual(
            bundle.policy_digest,
            hashlib.sha256(
                json.dumps(
                    policy,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
        )
        self.assertEqual(
            bundle.command_tokens[-1].kind, CommandTokenKind.STRATEGY_CLASS_NAME
        )
        self.assertEqual(
            bundle.environment_bindings[0].kind,
            EnvironmentBindingKind.SECRET_MOUNT_TARGET,
        )
        self.assertEqual(
            bundle.material_mounts[0].target,
            PurePosixPath("/freqtrade/config/runtime.json"),
        )
        self.assertEqual(bundle.secret_mounts[-1].secret_class, "ws_token")
        self.assertEqual(bundle.internal_ports, (8080,))
        self.assertEqual(bundle.runtime_user.uid, 12345)
        self.assertEqual(bundle.health_profile.probe_argv[0], "curl")
        self.assertEqual(bundle.resource_limits.memory_bytes, 536870912)
        self.assertEqual(len(bundle.network_rules), 1)
        network = bundle.network_rules[0]
        self.assertEqual(network.identity_source, NetworkIdentitySource.INSTANCE_ID)
        self.assertEqual(network.derivation, NetworkNameDerivation.SHA256_PREFIX_V1)
        self.assertEqual(
            (network.prefix, network.digest_characters, network.suffix),
            ("runtime-", 24, "-access"),
        )
        self.assertFalse(network.internal)
        self.assertTrue(network.requires_upstream_access)
        self.assertTrue(network.requires_platform_control)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            bundle.catalog_digest = "f" * 64

    def test_catalog_must_be_present_regular_and_non_executable(self) -> None:
        path = "ops/runtime-policies/launch-policy-catalog.json"

        with tempfile.TemporaryDirectory() as directory:
            self.fixture = GitFixture(Path(directory))
            (self.fixture.root / path).unlink()
            self.fixture.commit = self.fixture.create_commit("missing catalog")
            with self.assertRaisesRegex(
                ValueError, "launch policy checkout must be clean"
            ):
                self.load()

        with tempfile.TemporaryDirectory() as directory:
            self.fixture = GitFixture(Path(directory))
            git(self.fixture.root, "update-index", "--chmod=+x", "--", path)
            self.fixture.commit = self.fixture.create_index_commit("executable catalog")
            with self.assertRaisesRegex(ValueError, "regular 100644"):
                self.load()

        with tempfile.TemporaryDirectory() as directory:
            self.fixture = GitFixture(Path(directory))
            blob = git(
                self.fixture.root,
                "hash-object",
                "-w",
                "--stdin",
                input_bytes=b"arbitrary-target\n",
            )
            git(self.fixture.root, "update-index", "--cacheinfo", "120000", blob, path)
            self.fixture.commit = self.fixture.create_index_commit("symlink catalog")
            self.fixture.write_bytes(path, b"arbitrary-target\n")
            with self.assertRaisesRegex(ValueError, "regular 100644"):
                self.load()

    def test_rejects_dirty_catalog_and_noncanonical_committed_blob(self) -> None:
        self.fixture.write_json(
            "ops/runtime-policies/launch-policy-catalog.json",
            {**LAUNCH_POLICY_CATALOG, "schema_version": 2},
        )
        with self.assertRaisesRegex(
            ValueError, "^launch policy checkout must be clean$"
        ):
            self.load()

        self.fixture.write_bytes(
            "ops/runtime-policies/launch-policy-catalog.json",
            json.dumps(LAUNCH_POLICY_CATALOG, indent=2).encode("utf-8"),
        )
        self.fixture.commit = self.fixture.create_commit("noncanonical catalog")
        with self.assertRaisesRegex(
            ValueError,
            "^artifact must use canonical JSON with one trailing newline$",
        ):
            self.load()

    def test_rejects_unknown_missing_and_duplicate_catalog_structure(self) -> None:
        mutations = []
        unknown = deepcopy(LAUNCH_POLICY_CATALOG)
        unknown["host_port"] = 8081
        mutations.append(unknown)
        missing = deepcopy(LAUNCH_POLICY_CATALOG)
        del missing["schema_version"]
        mutations.append(missing)
        duplicate = deepcopy(LAUNCH_POLICY_CATALOG)
        duplicate["policies"].append(deepcopy(duplicate["policies"][0]))
        mutations.append(duplicate)

        for payload in mutations:
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as directory:
                    self.fixture = GitFixture(Path(directory))
                    self.commit_catalog(payload)
                    with self.assertRaises(ValueError):
                        self.load()

    def test_rejects_policy_template_and_allowlist_mismatch(self) -> None:
        fields = (
            ("image_policy", "policy_id", "unknown-image"),
            ("command_policy", "policy_id", "unknown-command"),
            ("network_policy", "policy_id", "unknown-network"),
            ("health_profile", "profile_id", "unknown-health"),
            ("resource_profile", "profile_id", "unknown-resource"),
            ("state_layout", "layout_id", "unknown-layout"),
        )
        for section, field, value in fields:
            with self.subTest(section=section):
                with tempfile.TemporaryDirectory() as directory:
                    self.fixture = GitFixture(Path(directory))
                    payload = deepcopy(LAUNCH_POLICY_CATALOG)
                    payload["policies"][0][section][field] = value
                    self.commit_catalog(payload)
                    with self.assertRaises(ValueError):
                        self.load()

    def test_rejects_shell_escape_raw_power_and_unclosed_bindings(self) -> None:
        mutations = []
        shell = deepcopy(LAUNCH_POLICY_CATALOG)
        shell["policies"][0]["command_policy"]["entrypoint_argv"] = ["sh", "-c"]
        mutations.append(shell)
        raw_port = deepcopy(LAUNCH_POLICY_CATALOG)
        raw_port["policies"][0]["published_ports"] = [8081]
        mutations.append(raw_port)
        raw_mount = deepcopy(LAUNCH_POLICY_CATALOG)
        raw_mount["policies"][0]["material_mounts"][0]["source"] = "/host/config"
        mutations.append(raw_mount)
        escaped_target = deepcopy(LAUNCH_POLICY_CATALOG)
        escaped_target["policies"][0]["material_mounts"][0]["target"] = (
            "/freqtrade/../host"
        )
        mutations.append(escaped_target)
        unknown_token = deepcopy(LAUNCH_POLICY_CATALOG)
        unknown_token["policies"][0]["command_policy"]["argument_tokens"][0] = {
            "kind": "caller_value",
            "value": "trade",
        }
        mutations.append(unknown_token)
        unknown_binding = deepcopy(LAUNCH_POLICY_CATALOG)
        unknown_binding["policies"][0]["environment_bindings"][0]["value"] = "missing"
        mutations.append(unknown_binding)

        for payload in mutations:
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as directory:
                    self.fixture = GitFixture(Path(directory))
                    self.commit_catalog(payload)
                    with self.assertRaises(ValueError):
                        self.load()

    def test_typed_policy_values_reject_credential_and_path_bypasses(self) -> None:
        with self.assertRaises(ValueError):
            CommandToken(CommandTokenKind.LITERAL, "--password")
        with self.assertRaises(ValueError):
            EnvironmentBindingKind("literal")
        with self.assertRaises(ValueError):
            MaterialMountPolicy(
                policy_id="runtime-config-ro-v1",
                role="runtime_config",
                material_kind=MaterialKind.RUNTIME_CONFIG,
                target=PurePosixPath("//freqtrade/state/config.json"),
            )
        with self.assertRaises(ValueError):
            NetworkRule(
                role="access",
                identity_source=NetworkIdentitySource.INSTANCE_ID,
                derivation=NetworkNameDerivation.SHA256_PREFIX_V1,
                prefix="runtime-",
                digest_characters=24,
                suffix="-access",
                internal=True,
                requires_upstream_access=True,
                requires_platform_control=True,
            )

    def test_paper_probe_policy_is_exact_and_arrays_are_canonical(self) -> None:
        mutations = []
        changed_resource = deepcopy(LAUNCH_POLICY_CATALOG)
        changed_resource["policies"][0]["resource_profile"]["cpu_millis"] = 2000
        mutations.append(changed_resource)
        reversed_mounts = deepcopy(LAUNCH_POLICY_CATALOG)
        reversed_mounts["policies"][0]["material_mounts"].reverse()
        mutations.append(reversed_mounts)
        boolean_limit = deepcopy(LAUNCH_POLICY_CATALOG)
        boolean_limit["policies"][0]["resource_profile"]["pids_limit"] = True
        mutations.append(boolean_limit)

        for payload in mutations:
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as directory:
                    self.fixture = GitFixture(Path(directory))
                    self.commit_catalog(payload)
                    with self.assertRaises(ValueError):
                        self.load()

    def test_rejects_every_additional_or_migration_policy_entry(self) -> None:
        additional = deepcopy(LAUNCH_POLICY_CATALOG["policies"][0])
        additional["template_id"] = "freqtrade-spot-migration-v1"
        self.commit_catalog(
            {
                "policies": [
                    deepcopy(LAUNCH_POLICY_CATALOG["policies"][0]),
                    additional,
                ],
                "schema_version": 1,
            }
        )
        with self.assertRaisesRegex(ValueError, "only the approved paper probe"):
            self.load()

        self.commit_catalog(deepcopy(LAUNCH_POLICY_CATALOG))
        with self.assertRaisesRegex(ValueError, "not approved"):
            load_resolved_launch_policy_bundle(
                self.fixture.root,
                "freqtrade-spot-migration-v1",
                self.fixture.commit,
            )
