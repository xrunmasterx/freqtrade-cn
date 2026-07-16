from __future__ import annotations

import unittest

from tools.runtime_persisted_preparation import PersistedDriverAuthorityResolver
from tools.runtime_supervisor.assembly import (
    InternalSupervisorAssembly,
    InternalSupervisorAssemblyDependencies,
    assemble_internal_supervisor,
)
from tools.runtime_supervisor.database_gate import (
    SupervisorDatabaseAuthorityError,
    validate_supervisor_database_authority,
)
from tools.runtime_supervisor.daemon import RuntimeSupervisorDaemon
from tools.runtime_supervisor.reconciler import RuntimeSupervisorReconciler


class _Result:
    def __init__(self, row: tuple[object, ...]) -> None:
        self._row = row

    def one(self) -> tuple[object, ...]:
        return self._row


class _Connection:
    def __init__(self, row: tuple[object, ...] | None, error: Exception | None) -> None:
        self._row = row
        self._error = error

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def exec_driver_sql(self, statement: str) -> _Result:
        if self._error is not None:
            raise self._error
        assert self._row is not None
        return _Result(self._row)


class _Engine:
    def __init__(
        self,
        row: tuple[object, ...] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._row = row
        self._error = error

    def connect(self) -> _Connection:
        return _Connection(self._row, self._error)


class _Driver:
    def __init__(
        self,
        events: list[str],
        authority_resolver: PersistedDriverAuthorityResolver,
    ) -> None:
        self.events = events
        self.authority_resolver = authority_resolver

    def __getattr__(self, name: str) -> object:
        if name in {"inspect", "launch", "stop", "probe"}:
            raise AssertionError(f"assembly called driver method: {name}")
        raise AttributeError(name)


class InternalSupervisorAssemblyTests(unittest.TestCase):
    def dependencies(
        self,
        events: list[str],
        database_gate: object,
    ) -> InternalSupervisorAssemblyDependencies:
        repository = object()
        port = object()
        publisher = object()

        def repository_factory() -> object:
            events.append("repository")
            return repository

        def driver_factory(authority_resolver: object) -> object:
            self.assertIsInstance(
                authority_resolver,
                PersistedDriverAuthorityResolver,
            )
            events.append("driver")
            return _Driver(events, authority_resolver)

        def network_factory(driver: object) -> object:
            self.assertIsInstance(driver, _Driver)
            events.append("network")
            return object()

        return InternalSupervisorAssemblyDependencies(
            database_authority_gate=database_gate,  # type: ignore[arg-type]
            repository_factory=repository_factory,
            resolved_material_factory=lambda attempt: attempt,
            image_port=port,
            state_port=port,
            secret_port=port,
            material_port=port,
            driver_factory=driver_factory,
            access_network_gate_factory=network_factory,
            offline_identity_publisher=publisher,
        )

    def test_database_gate_precedes_repository_and_driver_construction(self) -> None:
        events: list[str] = []

        def gate() -> None:
            events.append("database")

        assembly = assemble_internal_supervisor(self.dependencies(events, gate))

        self.assertIsInstance(assembly, InternalSupervisorAssembly)
        self.assertIsInstance(assembly.reconciler, RuntimeSupervisorReconciler)
        self.assertIsInstance(assembly.daemon, RuntimeSupervisorDaemon)
        self.assertIs(
            assembly.driver.authority_resolver,
            assembly.preparation.driver_authority_resolver,
        )
        self.assertEqual(events, ["database", "repository", "driver", "network"])

    def test_schema_mismatch_constructs_neither_repository_nor_driver(self) -> None:
        events: list[str] = []
        engine = _Engine(("platform_supervisor", "platform", "stale", 1))

        with self.assertRaisesRegex(
            SupervisorDatabaseAuthorityError,
            "^supervisor_database_authority_invalid$",
        ):
            assemble_internal_supervisor(
                self.dependencies(
                    events,
                    lambda: validate_supervisor_database_authority(engine),
                )
            )

        self.assertEqual(events, [])

    def test_database_outage_is_redacted_and_constructs_no_driver(self) -> None:
        events: list[str] = []
        marker = "postgresql://platform_supervisor:password@host/platform"
        engine = _Engine(error=RuntimeError(marker))

        with self.assertRaisesRegex(
            SupervisorDatabaseAuthorityError,
            "^supervisor_database_authority_unavailable$",
        ) as caught:
            assemble_internal_supervisor(
                self.dependencies(
                    events,
                    lambda: validate_supervisor_database_authority(engine),
                )
            )

        self.assertNotIn(marker, str(caught.exception))
        self.assertEqual(events, [])

    def test_raw_mapping_dependencies_are_rejected_before_gate(self) -> None:
        events: list[str] = []
        with self.assertRaisesRegex(
            ValueError,
            "^invalid internal supervisor assembly dependencies$",
        ):
            InternalSupervisorAssemblyDependencies(  # type: ignore[arg-type]
                database_authority_gate=lambda: events.append("database"),
                repository_factory=lambda: object(),
                resolved_material_factory=lambda attempt: attempt,
                image_port={},
                state_port=object(),
                secret_port=object(),
                material_port=object(),
                driver_factory=lambda: object(),
                access_network_gate_factory=lambda driver: object(),
                offline_identity_publisher=object(),
            )
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
