from __future__ import annotations

import ast
from pathlib import Path
import unittest

from tools.runtime_supervisor.database_gate import (
    EXPECTED_PLATFORM_SCHEMA_REVISION,
    SupervisorDatabaseAuthorityError,
    validate_supervisor_database_authority,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "freqtrade" / "platform_migrations" / "versions"


class _Result:
    def __init__(self, row: object) -> None:
        self._row = row

    def one(self) -> object:
        if isinstance(self._row, BaseException):
            raise self._row
        return self._row


class _Connection:
    def __init__(self, engine: "_Engine") -> None:
        self._engine = engine

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_exception: object) -> None:
        self._engine.closed += 1

    def exec_driver_sql(self, statement: str) -> _Result:
        self._engine.statements.append(statement)
        if isinstance(self._engine.row, BaseException):
            raise self._engine.row
        return _Result(self._engine.row)


class _Engine:
    def __init__(self, row: object) -> None:
        self.row = row
        self.connect_calls = 0
        self.closed = 0
        self.statements: list[str] = []

    def connect(self) -> _Connection:
        self.connect_calls += 1
        return _Connection(self)


def _migration_value(path: Path, name: str) -> str | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for statement in tree.body:
        if not isinstance(statement, ast.AnnAssign):
            continue
        if not isinstance(statement.target, ast.Name) or statement.target.id != name:
            continue
        if isinstance(statement.value, ast.Constant):
            value = statement.value.value
            if value is None or type(value) is str:
                return value
    raise AssertionError(f"migration {path.name} has no literal {name}")


class SupervisorDatabaseAuthorityGateTests(unittest.TestCase):
    def test_accepts_only_exact_role_database_and_unique_schema_head(self) -> None:
        engine = _Engine(
            ("platform_supervisor", "platform", EXPECTED_PLATFORM_SCHEMA_REVISION, 1)
        )

        validate_supervisor_database_authority(engine)

        self.assertEqual(engine.connect_calls, 1)
        self.assertEqual(engine.closed, 1)
        self.assertEqual(len(engine.statements), 1)
        statement = " ".join(engine.statements[0].split()).lower()
        self.assertIn("current_user", statement)
        self.assertIn("current_database()", statement)
        self.assertIn("public.alembic_version", statement)

    def test_rejects_wrong_identity_or_schema_before_returning(self) -> None:
        invalid_rows = (
            ("platform_operator", "platform", EXPECTED_PLATFORM_SCHEMA_REVISION, 1),
            ("platform_supervisor", "postgres", EXPECTED_PLATFORM_SCHEMA_REVISION, 1),
            ("platform_supervisor", "platform", "stale-revision", 1),
            ("platform_supervisor", "platform", EXPECTED_PLATFORM_SCHEMA_REVISION, 0),
            ("platform_supervisor", "platform", EXPECTED_PLATFORM_SCHEMA_REVISION, 2),
            ("platform_supervisor", "platform", EXPECTED_PLATFORM_SCHEMA_REVISION, True),
        )
        for row in invalid_rows:
            with self.subTest(row=row):
                engine = _Engine(row)
                with self.assertRaisesRegex(
                    SupervisorDatabaseAuthorityError,
                    r"^supervisor_database_authority_invalid$",
                ):
                    validate_supervisor_database_authority(engine)
                self.assertEqual(engine.closed, 1)

    def test_database_transport_failure_is_stable_and_redacted(self) -> None:
        engine = _Engine(RuntimeError("postgresql://operator:secret@private-host/db"))

        with self.assertRaisesRegex(
            SupervisorDatabaseAuthorityError,
            r"^supervisor_database_authority_unavailable$",
        ) as raised:
            validate_supervisor_database_authority(engine)

        self.assertNotIn("secret", str(raised.exception))
        self.assertEqual(engine.closed, 1)

    def test_expected_revision_is_the_backend_unique_migration_head(self) -> None:
        revisions: set[str] = set()
        parents: set[str] = set()
        for path in MIGRATIONS.glob("*.py"):
            revision = _migration_value(path, "revision")
            parent = _migration_value(path, "down_revision")
            self.assertIsInstance(revision, str)
            revisions.add(revision)
            if parent is not None:
                parents.add(parent)

        self.assertEqual(revisions - parents, {EXPECTED_PLATFORM_SCHEMA_REVISION})


if __name__ == "__main__":
    unittest.main()
