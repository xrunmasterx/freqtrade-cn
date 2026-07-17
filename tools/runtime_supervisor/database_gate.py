from __future__ import annotations

from typing import ContextManager, Protocol


EXPECTED_PLATFORM_SCHEMA_REVISION = "20260717_0008"
_EXPECTED_ROLE = "platform_supervisor"
_EXPECTED_DATABASE = "platform"
_AUTHORITY_QUERY = """
SELECT
    current_user,
    current_database(),
    (SELECT min(version_num) FROM public.alembic_version),
    (SELECT count(*) FROM public.alembic_version)
"""


class SupervisorDatabaseAuthorityError(RuntimeError):
    pass


class _Result(Protocol):
    def one(self) -> object: ...


class _Connection(Protocol):
    def exec_driver_sql(self, statement: str) -> _Result: ...


class SupervisorDatabaseEngine(Protocol):
    def connect(self) -> ContextManager[_Connection]: ...


def validate_supervisor_database_authority(
    engine: SupervisorDatabaseEngine,
) -> None:
    try:
        with engine.connect() as connection:
            row = connection.exec_driver_sql(_AUTHORITY_QUERY).one()
        values = tuple(row)  # type: ignore[arg-type]
    except Exception:
        raise SupervisorDatabaseAuthorityError(
            "supervisor_database_authority_unavailable"
        ) from None

    if (
        len(values) != 4
        or type(values[0]) is not str
        or values[0] != _EXPECTED_ROLE
        or type(values[1]) is not str
        or values[1] != _EXPECTED_DATABASE
        or type(values[2]) is not str
        or values[2] != EXPECTED_PLATFORM_SCHEMA_REVISION
        or type(values[3]) is not int
        or values[3] != 1
    ):
        raise SupervisorDatabaseAuthorityError(
            "supervisor_database_authority_invalid"
        )
