from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest import mock

from tools.runtime_supervisor import offline_acceptance


IMAGE_ID = f"sha256:{'8' * 64}"


class RuntimeSupervisorOfflineAcceptanceTests(unittest.TestCase):
    def test_input_contract_accepts_sha1_and_sha256_object_ids(self) -> None:
        for length in (40, 64):
            with self.subTest(length=length):
                self.assertIsNotNone(
                    offline_acceptance._COMMIT.fullmatch("a" * length)
                )
        for invalid in ("a" * 39, "a" * 41, "a" * 63, "A" * 64):
            with self.subTest(invalid=invalid):
                self.assertIsNone(offline_acceptance._COMMIT.fullmatch(invalid))

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.commit = subprocess.check_output(
            ("git", "rev-parse", "HEAD"),
            cwd=cls.root,
            text=True,
        ).strip()

    @unittest.skipIf(
        os.name == "nt",
        "committed material evidence requires a byte-exact checkout",
    )
    def test_compiles_exact_committed_paper_probe_without_runtime_action(self) -> None:
        receipt = offline_acceptance.verify_offline_paper_probe(
            self.root,
            self.commit,
            IMAGE_ID,
        )

        self.assertEqual(receipt.root_commit, self.commit)
        self.assertEqual(receipt.image_id, IMAGE_ID)
        self.assertTrue(receipt.dry_run)
        self.assertEqual(receipt.exchange, "bitget")
        self.assertEqual(receipt.product, "spot")
        self.assertEqual(receipt.strategy, "SampleStrategy")
        self.assertFalse(receipt.runtime_action_executed)
        self.assertEqual(receipt.published_ports, 0)
        self.assertEqual(receipt.writable_mounts, 1)
        self.assertEqual(receipt.secret_mounts, 3)
        self.assertFalse(receipt.secret_runtime_readability_verified)
        rendered = receipt.to_json()
        document = json.loads(rendered)
        self.assertEqual(
            set(document),
            {
                "dry_run",
                "exchange",
                "image_id",
                "launch_authority_digest",
                "policy_digest",
                "product",
                "published_ports",
                "root_commit",
                "runtime_action_executed",
                "secret_mounts",
                "secret_runtime_readability_verified",
                "strategy",
                "template_digest",
                "writable_mounts",
            },
        )
        self.assertEqual(document["root_commit"], self.commit)
        for forbidden in (
            "secret-phase2",
            "platform_supervisor_db_password",
            "postgresql://",
            "runtime-supervisor-offline-",
            "source_path",
            "credential",
            "private_key",
            "password",
            "token",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_module_has_no_runtime_mutation_or_private_provider_capability(self) -> None:
        source = Path(offline_acceptance.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        self.assertTrue(
            imported.isdisjoint(
                {
                    "subprocess",
                    "socket",
                    "tools.compose_runtime",
                    "tools.safe_compose_driver",
                }
            )
        )
        forbidden_calls = {"launch", "stop", "Popen", "run"}
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        called.update(
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        )
        self.assertTrue(called.isdisjoint(forbidden_calls))
        self.assertFalse(
            {
                node.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute) and node.attr.startswith("_")
            }
        )

    def test_rejects_unreviewed_identity_before_reading_repository(self) -> None:
        invalid = (
            ("main", IMAGE_ID),
            (self.commit, "freqtrade-cn:latest"),
            (self.commit.upper(), IMAGE_ID),
        )
        with mock.patch.object(
            offline_acceptance,
            "read_committed_paper_probe_artifacts",
        ) as read_artifacts:
            for commit, image_id in invalid:
                with self.subTest(commit=commit, image_id=image_id):
                    with self.assertRaisesRegex(
                        ValueError,
                        "^offline paper probe input invalid$",
                    ):
                        offline_acceptance.verify_offline_paper_probe(
                            self.root,
                            commit,
                            image_id,
                        )
        read_artifacts.assert_not_called()

    def test_cli_failure_is_stable_and_does_not_expose_exception(self) -> None:
        with mock.patch.object(
            offline_acceptance,
            "verify_offline_paper_probe",
            side_effect=RuntimeError("sensitive-path"),
        ):
            with mock.patch("sys.stderr.write") as stderr:
                result = offline_acceptance.main(
                    ("--root-commit", self.commit, "--image-id", IMAGE_ID)
                )
        self.assertEqual(result, 1)
        stderr.assert_called_once_with("offline_paper_probe_failed\n")


if __name__ == "__main__":
    unittest.main()
