from __future__ import annotations

import ast
from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_LOCAL_FILE_SECRET_PROVIDER = "local-file-v1"


def _assigned_string(path: Path, name: str) -> str:
    module = ast.parse(path.read_text(encoding="utf-8"))
    for statement in module.body:
        target = None
        value = None
        if isinstance(statement, ast.AnnAssign):
            target = statement.target
            value = statement.value
        elif isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            value = statement.value
        if (
            isinstance(target, ast.Name)
            and target.id == name
            and isinstance(value, ast.Constant)
            and type(value.value) is str
        ):
            return value.value
    raise AssertionError(f"missing string assignment: {name}")


def _class_field_literal(path: Path, class_name: str, field_name: str) -> str:
    module = ast.parse(path.read_text(encoding="utf-8"))
    for statement in module.body:
        if not isinstance(statement, ast.ClassDef) or statement.name != class_name:
            continue
        for field in statement.body:
            if (
                isinstance(field, ast.AnnAssign)
                and isinstance(field.target, ast.Name)
                and field.target.id == field_name
                and isinstance(field.annotation, ast.Subscript)
                and isinstance(field.annotation.value, ast.Name)
                and field.annotation.value.id == "Literal"
            ):
                value = ast.literal_eval(field.annotation.slice)
                if type(value) is str:
                    return value
        break
    raise AssertionError(f"missing literal field: {class_name}.{field_name}")


def _class_string_constants(path: Path, class_name: str) -> frozenset[str]:
    module = ast.parse(path.read_text(encoding="utf-8"))
    for statement in module.body:
        if isinstance(statement, ast.ClassDef) and statement.name == class_name:
            return frozenset(
                node.value
                for node in ast.walk(statement)
                if isinstance(node, ast.Constant) and type(node.value) is str
            )
    raise AssertionError(f"missing class: {class_name}")


def _provider_keyword_values(path: Path) -> frozenset[str]:
    module = ast.parse(path.read_text(encoding="utf-8"))
    return frozenset(
        keyword.value.value
        for keyword in ast.walk(module)
        if isinstance(keyword, ast.keyword)
        and keyword.arg == "provider_id"
        and isinstance(keyword.value, ast.Constant)
        and type(keyword.value.value) is str
        and keyword.value.value.startswith("local-file")
    )


class RuntimeProviderContractTests(unittest.TestCase):
    def test_secret_provider_identity_is_exact_across_root_and_backend(self) -> None:
        root_provider = _assigned_string(
            REPOSITORY_ROOT / "tools" / "runtime_secrets.py",
            "_PROVIDER_ID",
        )
        snapshot_provider = _assigned_string(
            REPOSITORY_ROOT / "tools" / "runtime_snapshot.py",
            "_SECRET_PROVIDER_ID",
        )
        backend_domain = (
            REPOSITORY_ROOT
            / "freqtrade"
            / "freqtrade"
            / "platform"
            / "template_domain.py"
        )
        backend_models = (
            REPOSITORY_ROOT
            / "freqtrade"
            / "freqtrade"
            / "platform"
            / "template_models.py"
        )
        backend_migration = (
            REPOSITORY_ROOT
            / "freqtrade"
            / "platform_migrations"
            / "versions"
            / "20260712_0002_templates_specs.py"
        )
        backend_registration = (
            REPOSITORY_ROOT
            / "freqtrade"
            / "freqtrade"
            / "platform"
            / "runtime_registration_repository.py"
        )

        self.assertEqual(root_provider, EXPECTED_LOCAL_FILE_SECRET_PROVIDER)
        self.assertEqual(snapshot_provider, EXPECTED_LOCAL_FILE_SECRET_PROVIDER)
        self.assertEqual(
            _class_field_literal(
                backend_domain,
                "SecretReference",
                "provider_id",
            ),
            EXPECTED_LOCAL_FILE_SECRET_PROVIDER,
        )
        self.assertIn(
            "provider_id = 'local-file-v1'",
            _class_string_constants(
                backend_models,
                "SecretReferenceRecord",
            ),
        )
        self.assertIn(
            "provider_id = 'local-file-v1'",
            frozenset(
                node.value
                for node in ast.walk(
                    ast.parse(backend_migration.read_text(encoding="utf-8"))
                )
                if isinstance(node, ast.Constant) and type(node.value) is str
            ),
        )
        self.assertEqual(
            _provider_keyword_values(backend_registration),
            {EXPECTED_LOCAL_FILE_SECRET_PROVIDER},
        )


if __name__ == "__main__":
    unittest.main()
