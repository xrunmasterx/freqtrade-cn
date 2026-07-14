from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]

POLICY_DOCUMENTS = {
    "ops/runtime-policies/image-policies.json": {
        "policy_ids": ["freqtrade-reviewed-image-v1"],
        "schema_version": 1,
    },
    "ops/runtime-policies/command-policies.json": {
        "policy_ids": [
            "freqtrade-futures-migration-v1",
            "freqtrade-spot-migration-v1",
            "freqtrade-spot-paper-v1",
            "research-worker-migration-v1",
        ],
        "schema_version": 1,
    },
    "ops/runtime-policies/mount-policies.json": {
        "policy_ids": [
            "api-secrets-ro-v1",
            "managed-state-rw-v1",
            "runtime-config-ro-v1",
            "strategy-ro-v1",
        ],
        "schema_version": 1,
    },
    "ops/runtime-policies/network-policies.json": {
        "policy_ids": [
            "isolated-digital-asset-execution-v1",
            "isolated-public-market-data-v1",
        ],
        "schema_version": 1,
    },
    "ops/runtime-policies/health-profiles.json": {
        "policy_ids": ["freqtrade-ping-v1"],
        "schema_version": 1,
    },
    "ops/runtime-policies/resource-profiles.json": {
        "policy_ids": ["freqtrade-small-v1"],
        "schema_version": 1,
    },
    "ops/runtime-policies/state-layouts.json": {
        "policy_ids": ["freqtrade-state-v1"],
        "schema_version": 1,
    },
}

COMMON_TEMPLATE = {
    "schema_version": 1,
    "semantic_version": "1.0.0",
    "image_policy_id": "freqtrade-reviewed-image-v1",
    "mount_policy_ids": [
        "runtime-config-ro-v1",
        "strategy-ro-v1",
        "managed-state-rw-v1",
        "api-secrets-ro-v1",
    ],
    "health_profile_id": "freqtrade-ping-v1",
    "resource_profile_id": "freqtrade-small-v1",
    "secret_classes": ["api_password", "jwt_secret", "ws_token"],
    "state_layout_id": "freqtrade-state-v1",
}

TEMPLATE_DOCUMENTS = {
    "freqtrade-spot-migration-v1": {
        **COMMON_TEMPLATE,
        "template_id": "freqtrade-spot-migration-v1",
        "allowed_instance_kinds": ["freqtrade"],
        "allowed_owner_kinds": ["migration_bot"],
        "allowed_environments": ["paper", "live"],
        "command_policy_id": "freqtrade-spot-migration-v1",
        "network_policy_id": "isolated-digital-asset-execution-v1",
    },
    "freqtrade-futures-migration-v1": {
        **COMMON_TEMPLATE,
        "template_id": "freqtrade-futures-migration-v1",
        "allowed_instance_kinds": ["freqtrade"],
        "allowed_owner_kinds": ["migration_bot"],
        "allowed_environments": ["paper", "live"],
        "command_policy_id": "freqtrade-futures-migration-v1",
        "network_policy_id": "isolated-digital-asset-execution-v1",
    },
    "research-worker-migration-v1": {
        **COMMON_TEMPLATE,
        "template_id": "research-worker-migration-v1",
        "allowed_instance_kinds": ["research_worker"],
        "allowed_owner_kinds": ["workspace_worker"],
        "allowed_environments": ["paper"],
        "command_policy_id": "research-worker-migration-v1",
        "network_policy_id": "isolated-public-market-data-v1",
    },
    "freqtrade-paper-probe-v1": {
        **COMMON_TEMPLATE,
        "template_id": "freqtrade-paper-probe-v1",
        "allowed_instance_kinds": ["freqtrade"],
        "allowed_owner_kinds": ["paper_probe"],
        "allowed_environments": ["paper"],
        "command_policy_id": "freqtrade-spot-paper-v1",
        "network_policy_id": "isolated-public-market-data-v1",
    },
}


def canonical_json(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def git(repository: Path, *arguments: str, input_bytes: bytes | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        input=input_bytes,
        check=True,
        capture_output=True,
    )
    return result.stdout.decode("ascii").strip()


class GitFixture:
    def __init__(self, parent: Path) -> None:
        self.root = parent / "repository"
        self.root.mkdir()
        git(self.root, "init", "--quiet")
        git(self.root, "config", "user.email", "runtime-templates@example.invalid")
        git(self.root, "config", "user.name", "Runtime Template Tests")
        git(self.root, "config", "core.autocrlf", "false")
        git(self.root, "config", "core.filemode", "false")
        git(self.root, "config", "core.symlinks", "false")
        for path, payload in POLICY_DOCUMENTS.items():
            self.write_bytes(path, canonical_json(payload))
        self.write_template(
            "freqtrade-paper-probe-v1",
            TEMPLATE_DOCUMENTS["freqtrade-paper-probe-v1"],
        )
        self.commit = self.create_commit("initial artifacts")

    def write_bytes(self, relative_path: str, contents: bytes) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    def write_json(self, relative_path: str, payload: object) -> None:
        self.write_bytes(relative_path, canonical_json(payload))

    def write_template(self, template_id: str, payload: object) -> None:
        self.write_json(f"ops/adapter-templates/{template_id}.json", payload)

    def create_commit(self, message: str) -> str:
        git(self.root, "add", "--all", "--", ".")
        return self.create_index_commit(message)

    def create_index_commit(self, message: str) -> str:
        git(self.root, "commit", "--quiet", "-m", message)
        return git(self.root, "rev-parse", "HEAD")


try:
    from tools.committed_git import CommittedGitStore
    import tools.runtime_templates as runtime_templates_module
    from tools.runtime_templates import (
        git_blob,
        load_closed_policy_registry,
        read_committed_template,
        validate_template,
    )
except ModuleNotFoundError as error:
    RUNTIME_TEMPLATES_IMPORT_ERROR: ModuleNotFoundError | None = error
else:
    RUNTIME_TEMPLATES_IMPORT_ERROR = None


class RuntimeTemplatesAvailabilityTests(unittest.TestCase):
    def test_runtime_templates_module_exists(self) -> None:
        self.assertIsNone(
            RUNTIME_TEMPLATES_IMPORT_ERROR,
            "tools.runtime_templates must exist before the contract can pass",
        )

    @unittest.skipIf(RUNTIME_TEMPLATES_IMPORT_ERROR is not None, "runtime_templates is missing")
    def test_required_public_api_is_exposed(self) -> None:
        self.assertTrue(callable(read_committed_template))
        self.assertTrue(callable(load_closed_policy_registry))
        self.assertTrue(callable(validate_template))
        self.assertTrue(callable(git_blob))

    @unittest.skipIf(RUNTIME_TEMPLATES_IMPORT_ERROR is not None, "runtime_templates is missing")
    def test_uses_the_shared_committed_git_store(self) -> None:
        self.assertIs(runtime_templates_module.CommittedGitStore, CommittedGitStore)


@unittest.skipIf(RUNTIME_TEMPLATES_IMPORT_ERROR is not None, "runtime_templates is missing")
class RuntimeTemplateArtifactTests(unittest.TestCase):
    def test_exact_root_artifacts_are_canonical(self) -> None:
        expected = {
            **POLICY_DOCUMENTS,
            **{
                f"ops/adapter-templates/{template_id}.json": payload
                for template_id, payload in TEMPLATE_DOCUMENTS.items()
            },
        }
        for relative_path, payload in expected.items():
            with self.subTest(path=relative_path):
                self.assertEqual((ROOT / relative_path).read_bytes(), canonical_json(payload))

    def test_fixed_paper_probe_security_identity(self) -> None:
        paper_probe = TEMPLATE_DOCUMENTS["freqtrade-paper-probe-v1"]
        self.assertEqual(paper_probe["allowed_instance_kinds"], ["freqtrade"])
        self.assertEqual(paper_probe["allowed_owner_kinds"], ["paper_probe"])
        self.assertEqual(paper_probe["allowed_environments"], ["paper"])
        self.assertEqual(paper_probe["command_policy_id"], "freqtrade-spot-paper-v1")
        self.assertEqual(
            paper_probe["network_policy_id"], "isolated-public-market-data-v1"
        )


@unittest.skipIf(RUNTIME_TEMPLATES_IMPORT_ERROR is not None, "runtime_templates is missing")
class RuntimeTemplateGitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.fixture = GitFixture(Path(self.temporary_directory.name))

    def test_reads_exact_committed_template_and_digest(self) -> None:
        template = read_committed_template(
            self.fixture.root,
            "freqtrade-paper-probe-v1",
            self.fixture.commit,
        )
        expected = canonical_json(TEMPLATE_DOCUMENTS["freqtrade-paper-probe-v1"])
        expected_payload = {
            key: tuple(value) if isinstance(value, list) else value
            for key, value in TEMPLATE_DOCUMENTS["freqtrade-paper-probe-v1"].items()
        }
        self.assertEqual(dict(template.payload), expected_payload)
        self.assertEqual(template.canonical_json, expected.decode("utf-8"))
        self.assertEqual(template.digest, hashlib.sha256(expected).hexdigest())
        self.assertEqual(
            template.source_path,
            "ops/adapter-templates/freqtrade-paper-probe-v1.json",
        )
        self.assertEqual(template.source_commit, self.fixture.commit)

    def test_relevant_staged_unstaged_and_untracked_changes_fail(self) -> None:
        mutations = ("staged", "unstaged", "untracked")
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with tempfile.TemporaryDirectory() as directory:
                    fixture = GitFixture(Path(directory))
                    if mutation == "untracked":
                        fixture.write_bytes("ops/runtime-policies/untracked.json", b"{}\n")
                    else:
                        fixture.write_template(
                            "freqtrade-paper-probe-v1",
                            {**TEMPLATE_DOCUMENTS["freqtrade-paper-probe-v1"], "schema_version": 2},
                        )
                        if mutation == "staged":
                            git(
                                fixture.root,
                                "add",
                                "--",
                                "ops/adapter-templates/freqtrade-paper-probe-v1.json",
                            )
                    with self.assertRaisesRegex(
                        ValueError, "template checkout must be clean"
                    ):
                        read_committed_template(
                            fixture.root, "freqtrade-paper-probe-v1", fixture.commit
                        )

    def test_unrelated_dirty_path_does_not_become_publication_input(self) -> None:
        self.fixture.write_bytes("unrelated.txt", b"not trusted\n")
        template = read_committed_template(
            self.fixture.root, "freqtrade-paper-probe-v1", self.fixture.commit
        )
        self.assertEqual(template.payload["template_id"], "freqtrade-paper-probe-v1")

    def test_returned_template_stays_committed_after_worktree_replacement(self) -> None:
        template = read_committed_template(
            self.fixture.root, "freqtrade-paper-probe-v1", self.fixture.commit
        )
        self.fixture.write_template(
            "freqtrade-paper-probe-v1",
            {**TEMPLATE_DOCUMENTS["freqtrade-paper-probe-v1"], "image": "arbitrary"},
        )
        self.assertEqual(template.payload["image_policy_id"], "freqtrade-reviewed-image-v1")
        self.assertNotIn("image", template.payload)

    def test_publication_does_not_use_path_content_reads(self) -> None:
        with (
            patch.object(Path, "read_bytes", side_effect=AssertionError("worktree read")),
            patch.object(Path, "read_text", side_effect=AssertionError("worktree read")),
            patch.object(Path, "open", side_effect=AssertionError("worktree read")),
        ):
            template = read_committed_template(
                self.fixture.root, "freqtrade-paper-probe-v1", self.fixture.commit
            )
        self.assertEqual(template.source_commit, self.fixture.commit)

    def test_unknown_command_policy_is_rejected(self) -> None:
        registry = load_closed_policy_registry(self.fixture.root, self.fixture.commit)
        payload = {
            **TEMPLATE_DOCUMENTS["freqtrade-paper-probe-v1"],
            "command_policy_id": "unknown-command",
        }
        with self.assertRaisesRegex(ValueError, "unknown command policy"):
            validate_template(payload, registry)

    def test_payload_and_registry_sets_are_immutable(self) -> None:
        registry = load_closed_policy_registry(self.fixture.root, self.fixture.commit)
        template = read_committed_template(
            self.fixture.root, "freqtrade-paper-probe-v1", self.fixture.commit
        )
        with self.assertRaises(TypeError):
            template.payload["template_id"] = "changed"
        with self.assertRaises(TypeError):
            template.payload["mount_policy_ids"][0] = "changed"
        with self.assertRaises(AttributeError):
            registry.image_policy_ids.add("changed")

    def test_git_blob_rejects_arbitrary_paths(self) -> None:
        self.fixture.write_bytes("unrelated.txt", b"untrusted\n")
        with self.assertRaisesRegex(ValueError, "artifact path"):
            git_blob(self.fixture.root, self.fixture.commit, "unrelated.txt")

    def test_root_must_be_exact_git_toplevel(self) -> None:
        with self.assertRaisesRegex(ValueError, "exact Git toplevel"):
            read_committed_template(
                self.fixture.root / "ops",
                "freqtrade-paper-probe-v1",
                self.fixture.commit,
            )

    def test_commit_must_be_full_lowercase_identity(self) -> None:
        invalid_identities = (
            self.fixture.commit[:12],
            self.fixture.commit.upper(),
            "g" * 40,
        )
        for identity in invalid_identities:
            with self.subTest(identity=identity):
                with self.assertRaisesRegex(ValueError, "full lowercase"):
                    read_committed_template(
                        self.fixture.root, "freqtrade-paper-probe-v1", identity
                    )

    def test_commit_identity_must_name_commit_object(self) -> None:
        blob = git(
            self.fixture.root,
            "hash-object",
            "-w",
            "--stdin",
            input_bytes=b"not a commit\n",
        )
        with self.assertRaisesRegex(ValueError, "commit object"):
            read_committed_template(
                self.fixture.root, "freqtrade-paper-probe-v1", blob
            )

    def test_commit_must_be_ancestor_of_current_head(self) -> None:
        tree = git(self.fixture.root, "write-tree")
        unrelated_commit = git(
            self.fixture.root, "commit-tree", tree, "-m", "unrelated commit"
        )
        with self.assertRaisesRegex(ValueError, "ancestor of HEAD"):
            read_committed_template(
                self.fixture.root, "freqtrade-paper-probe-v1", unrelated_commit
            )

    def test_executable_artifact_mode_is_rejected(self) -> None:
        path = "ops/adapter-templates/freqtrade-paper-probe-v1.json"
        git(self.fixture.root, "update-index", "--chmod=+x", "--", path)
        commit = self.fixture.create_index_commit("executable template")
        with self.assertRaisesRegex(ValueError, "regular 100644"):
            read_committed_template(
                self.fixture.root, "freqtrade-paper-probe-v1", commit
            )

    def test_symlink_artifact_mode_is_rejected(self) -> None:
        path = "ops/adapter-templates/freqtrade-paper-probe-v1.json"
        blob = git(
            self.fixture.root,
            "hash-object",
            "-w",
            "--stdin",
            input_bytes=b"arbitrary-target\n",
        )
        git(self.fixture.root, "update-index", "--cacheinfo", "120000", blob, path)
        commit = self.fixture.create_index_commit("symlink template")
        self.fixture.write_bytes(path, b"arbitrary-target\n")
        with self.assertRaisesRegex(ValueError, "regular 100644"):
            read_committed_template(
                self.fixture.root, "freqtrade-paper-probe-v1", commit
            )

    def test_missing_policy_artifact_is_rejected(self) -> None:
        (self.fixture.root / "ops/runtime-policies/image-policies.json").unlink()
        commit = self.fixture.create_commit("remove image policies")
        with self.assertRaisesRegex(ValueError, "required artifact"):
            read_committed_template(
                self.fixture.root, "freqtrade-paper-probe-v1", commit
            )

    def test_future_worktree_policy_cannot_substitute_for_source_commit(self) -> None:
        future_command = "future-reviewed-command-v1"
        template = {
            **TEMPLATE_DOCUMENTS["freqtrade-paper-probe-v1"],
            "template_id": "future-template-v1",
            "command_policy_id": future_command,
        }
        self.fixture.write_template("future-template-v1", template)
        inconsistent_commit = self.fixture.create_commit("template before policy")

        commands = POLICY_DOCUMENTS["ops/runtime-policies/command-policies.json"]
        self.fixture.write_json(
            "ops/runtime-policies/command-policies.json",
            {
                **commands,
                "policy_ids": sorted([*commands["policy_ids"], future_command]),
            },
        )
        self.fixture.create_commit("future policy")

        with self.assertRaisesRegex(ValueError, "unknown command policy"):
            read_committed_template(
                self.fixture.root, "future-template-v1", inconsistent_commit
            )

    def test_replacement_object_cannot_substitute_for_source_commit(self) -> None:
        template_id = "replacement-test-v1"
        original_payload = {
            **TEMPLATE_DOCUMENTS["freqtrade-paper-probe-v1"],
            "template_id": template_id,
        }
        original_document = canonical_json(original_payload)
        self.fixture.write_template(template_id, original_payload)
        source_commit = self.fixture.create_commit("replacement source")

        self.fixture.write_template(
            template_id,
            {**original_payload, "semantic_version": "2.0.0"},
        )
        replacement_material = self.fixture.create_commit("replacement material")
        replacement_tree = git(
            self.fixture.root,
            "rev-parse",
            f"{replacement_material}^{{tree}}",
        )
        replacement_commit = git(
            self.fixture.root,
            "commit-tree",
            replacement_tree,
            "-m",
            "replacement object",
        )

        self.fixture.write_template(template_id, original_payload)
        self.fixture.create_commit("restore worktree content")
        git(self.fixture.root, "replace", source_commit, replacement_commit)

        template = read_committed_template(
            self.fixture.root,
            template_id,
            source_commit,
        )
        self.assertEqual(template.canonical_json, original_document.decode("utf-8"))
        self.assertEqual(template.digest, hashlib.sha256(original_document).hexdigest())
        self.assertEqual(template.source_commit, source_commit)

    def test_assume_unchanged_trusted_entry_fails_clean_gate(self) -> None:
        path = "ops/adapter-templates/freqtrade-paper-probe-v1.json"
        git(self.fixture.root, "update-index", "--assume-unchanged", "--", path)
        self.fixture.write_bytes(path, b"hidden worktree replacement\n")

        with self.assertRaisesRegex(ValueError, "template checkout must be clean"):
            read_committed_template(
                self.fixture.root,
                "freqtrade-paper-probe-v1",
                self.fixture.commit,
            )

    def test_skip_worktree_trusted_entry_fails_clean_gate(self) -> None:
        path = "ops/adapter-templates/freqtrade-paper-probe-v1.json"
        git(self.fixture.root, "update-index", "--skip-worktree", "--", path)
        self.fixture.write_bytes(path, b"hidden worktree replacement\n")

        with self.assertRaisesRegex(ValueError, "template checkout must be clean"):
            read_committed_template(
                self.fixture.root,
                "freqtrade-paper-probe-v1",
                self.fixture.commit,
            )

    def test_ignored_untracked_trusted_entry_fails_clean_gate(self) -> None:
        self.fixture.write_bytes(
            ".git/info/exclude",
            b"/ops/runtime-policies/ignored-policy.json\n",
        )
        self.fixture.write_bytes(
            "ops/runtime-policies/ignored-policy.json",
            b"ignored but still inside the trusted path\n",
        )

        with self.assertRaisesRegex(ValueError, "template checkout must be clean"):
            read_committed_template(
                self.fixture.root,
                "freqtrade-paper-probe-v1",
                self.fixture.commit,
            )

    def test_duplicate_json_key_is_rejected(self) -> None:
        self.fixture.write_bytes(
            "ops/runtime-policies/image-policies.json",
            b'{"policy_ids":["first"],"policy_ids":["second"],"schema_version":1}\n',
        )
        commit = self.fixture.create_commit("duplicate policy key")
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            load_closed_policy_registry(self.fixture.root, commit)

    def test_invalid_utf8_and_bom_are_rejected(self) -> None:
        variants = (
            ("invalid utf8", b'{"policy_ids":["valid-id"],"schema_version":1}\xff\n'),
            (
                "bom",
                b'\xef\xbb\xbf{"policy_ids":["valid-id"],"schema_version":1}\n',
            ),
        )
        for label, contents in variants:
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as directory:
                    fixture = GitFixture(Path(directory))
                    fixture.write_bytes(
                        "ops/runtime-policies/image-policies.json", contents
                    )
                    commit = fixture.create_commit(label)
                    with self.assertRaisesRegex(ValueError, "UTF-8|BOM"):
                        load_closed_policy_registry(fixture.root, commit)

    def test_noncanonical_json_bytes_are_rejected(self) -> None:
        canonical = canonical_json(
            POLICY_DOCUMENTS["ops/runtime-policies/image-policies.json"]
        )
        variants = (
            ("missing newline", canonical.rstrip(b"\n")),
            ("extra newline", canonical + b"\n"),
            (
                "pretty JSON",
                b'{\n  "policy_ids": ["freqtrade-reviewed-image-v1"],\n'
                b'  "schema_version": 1\n}\n',
            ),
        )
        for label, contents in variants:
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as directory:
                    fixture = GitFixture(Path(directory))
                    fixture.write_bytes(
                        "ops/runtime-policies/image-policies.json", contents
                    )
                    commit = fixture.create_commit(label)
                    with self.assertRaisesRegex(ValueError, "canonical JSON"):
                        load_closed_policy_registry(fixture.root, commit)

    def test_registry_schema_and_policy_ids_are_closed(self) -> None:
        valid = POLICY_DOCUMENTS["ops/runtime-policies/image-policies.json"]
        invalid_documents = (
            ("non-object", ["valid-id"], "JSON object"),
            ("unknown key", {**valid, "image": "raw"}, "unknown keys"),
            ("wrong version", {**valid, "schema_version": 2}, "schema_version"),
            ("bool version", {**valid, "schema_version": True}, "schema_version"),
            ("not a list", {**valid, "policy_ids": "valid-id"}, "policy_ids"),
            ("empty", {**valid, "policy_ids": []}, "non-empty"),
            (
                "duplicate",
                {**valid, "policy_ids": ["valid-id", "valid-id"]},
                "unique",
            ),
            ("invalid", {**valid, "policy_ids": ["Invalid"]}, "identifier"),
            (
                "unsorted",
                {**valid, "policy_ids": ["valid-z", "valid-a"]},
                "sorted",
            ),
        )
        for label, payload, message in invalid_documents:
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as directory:
                    fixture = GitFixture(Path(directory))
                    fixture.write_json(
                        "ops/runtime-policies/image-policies.json", payload
                    )
                    commit = fixture.create_commit(label)
                    with self.assertRaisesRegex(ValueError, message):
                        load_closed_policy_registry(fixture.root, commit)

    def test_template_schema_and_array_invariants_are_rejected(self) -> None:
        registry = load_closed_policy_registry(self.fixture.root, self.fixture.commit)
        valid = TEMPLATE_DOCUMENTS["freqtrade-paper-probe-v1"]
        invalid_payloads = (
            ("non-object", [], "JSON object"),
            ("unknown key", {**valid, "surprise": True}, "unknown keys"),
            (
                "missing key",
                {key: value for key, value in valid.items() if key != "template_id"},
                "missing keys",
            ),
            ("wrong version", {**valid, "schema_version": 2}, "schema_version"),
            ("bool version", {**valid, "schema_version": True}, "schema_version"),
            ("bad semantic version", {**valid, "semantic_version": "01.0.0"}, "semantic_version"),
            (
                "array as string",
                {**valid, "allowed_environments": "paper"},
                "array of strings",
            ),
            (
                "duplicate array",
                {**valid, "secret_classes": ["api_password", "api_password"]},
                "duplicate",
            ),
            (
                "invalid identifier",
                {**valid, "allowed_instance_kinds": ["Invalid"]},
                "identifier",
            ),
            (
                "bad owner",
                {**valid, "allowed_owner_kinds": ["operator"]},
                "owner kind",
            ),
            (
                "bad environment",
                {**valid, "allowed_environments": ["staging"]},
                "environment",
            ),
        )
        for label, payload, message in invalid_payloads:
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError, message):
                    validate_template(payload, registry)

    def test_all_raw_template_powers_fail_before_policy_lookup(self) -> None:
        registry = load_closed_policy_registry(self.fixture.root, self.fixture.commit)
        raw_power_keys = (
            "image",
            "command",
            "host_path",
            "mount",
            "mount_source",
            "port",
            "network",
            "device",
            "capability",
            "privileged",
            "compose",
            "project",
            "service",
            "container",
            "environment",
            "env",
            "env_file",
            "environment_passthrough",
            "secret",
            "secret_value",
            "secret_path",
            "credential",
        )
        for key in raw_power_keys:
            with self.subTest(key=key):
                payload = {
                    **TEMPLATE_DOCUMENTS["freqtrade-paper-probe-v1"],
                    "command_policy_id": "unknown-command",
                    key: "raw-power",
                }
                with self.assertRaisesRegex(ValueError, "forbidden raw power"):
                    validate_template(payload, registry)

    def test_every_policy_reference_uses_category_specific_error(self) -> None:
        registry = load_closed_policy_registry(self.fixture.root, self.fixture.commit)
        valid = {
            **TEMPLATE_DOCUMENTS["freqtrade-paper-probe-v1"],
            "template_id": "generic-template-v1",
        }
        mutations = (
            ("image_policy_id", "unknown", "unknown image policy"),
            ("command_policy_id", "unknown", "unknown command policy"),
            ("mount_policy_ids", ["unknown"], "unknown mount policy"),
            ("network_policy_id", "unknown", "unknown network policy"),
            ("health_profile_id", "unknown", "unknown health profile"),
            ("resource_profile_id", "unknown", "unknown resource profile"),
            ("state_layout_id", "unknown", "unknown state layout"),
        )
        for field, value, message in mutations:
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, message):
                    validate_template({**valid, field: value}, registry)

    def test_paper_probe_identity_drift_is_rejected_by_validator(self) -> None:
        registry = load_closed_policy_registry(self.fixture.root, self.fixture.commit)
        paper_probe = TEMPLATE_DOCUMENTS["freqtrade-paper-probe-v1"]
        drifts = (
            ("semantic_version", "1.0.1"),
            ("allowed_instance_kinds", ["research_worker"]),
            ("allowed_owner_kinds", ["migration_bot"]),
            ("allowed_environments", ["paper", "live"]),
            ("command_policy_id", "freqtrade-spot-migration-v1"),
            ("mount_policy_ids", list(reversed(paper_probe["mount_policy_ids"]))),
            ("network_policy_id", "isolated-digital-asset-execution-v1"),
            ("secret_classes", ["api_password"]),
        )
        for field, value in drifts:
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "paper probe identity"):
                    validate_template({**paper_probe, field: value}, registry)


if __name__ == "__main__":
    unittest.main()
