from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Callable, Protocol

from tools.runtime_driver import RuntimeAccessNetworkGate, RuntimeDriver
from tools.runtime_persisted_preparation import (
    ImagePort,
    MaterialPort,
    PersistedAuthorityPreparation,
    PersistedDriverAuthorityResolver,
    RepositoryPort as PersistedPreparationRepositoryPort,
    ResolvedMaterialFactory,
    SecretPort,
    StatePort,
)
from tools.runtime_supervisor.daemon import (
    RuntimeSupervisorDaemon,
    SupervisorRepositoryPort,
)
from tools.runtime_supervisor.reconciler import (
    OfflineIdentityPublisher,
    RepositoryPort as ReconcilerRepositoryPort,
    RuntimeSupervisorReconciler,
)


class SupervisorRuntimeRepository(
    SupervisorRepositoryPort,
    ReconcilerRepositoryPort,
    PersistedPreparationRepositoryPort,
    Protocol,
):
    pass


class RepositoryFactory(Protocol):
    def __call__(self) -> SupervisorRuntimeRepository: ...


class DriverFactory(Protocol):
    def __call__(
        self,
        authority_resolver: PersistedDriverAuthorityResolver,
    ) -> RuntimeDriver: ...


class AccessNetworkGateFactory(Protocol):
    def __call__(self, driver: RuntimeDriver) -> RuntimeAccessNetworkGate: ...


@dataclass(frozen=True, slots=True)
class InternalSupervisorAssemblyDependencies:
    database_authority_gate: Callable[[], None]
    repository_factory: RepositoryFactory
    resolved_material_factory: ResolvedMaterialFactory
    image_port: ImagePort
    state_port: StatePort
    secret_port: SecretPort
    material_port: MaterialPort
    driver_factory: DriverFactory
    access_network_gate_factory: AccessNetworkGateFactory
    offline_identity_publisher: OfflineIdentityPublisher

    def __post_init__(self) -> None:
        callables = (
            self.database_authority_gate,
            self.repository_factory,
            self.resolved_material_factory,
            self.driver_factory,
            self.access_network_gate_factory,
        )
        dependencies = (
            self.image_port,
            self.state_port,
            self.secret_port,
            self.material_port,
            self.offline_identity_publisher,
        )
        if any(not callable(value) for value in callables) or any(
            value is None or isinstance(value, Mapping) for value in dependencies
        ):
            raise ValueError("invalid internal supervisor assembly dependencies")


@dataclass(frozen=True, slots=True)
class InternalSupervisorAssembly:
    repository: SupervisorRuntimeRepository
    preparation: PersistedAuthorityPreparation
    driver: RuntimeDriver
    access_network_gate: RuntimeAccessNetworkGate
    reconciler: RuntimeSupervisorReconciler
    daemon: RuntimeSupervisorDaemon


def assemble_internal_supervisor(
    dependencies: InternalSupervisorAssemblyDependencies,
) -> InternalSupervisorAssembly:
    if type(dependencies) is not InternalSupervisorAssemblyDependencies:
        raise ValueError("invalid internal supervisor assembly dependencies")

    dependencies.database_authority_gate()
    repository = dependencies.repository_factory()
    if repository is None or isinstance(repository, Mapping):
        raise ValueError("invalid internal supervisor repository")
    preparation = PersistedAuthorityPreparation(
        repository,
        dependencies.resolved_material_factory,
        dependencies.image_port,
        dependencies.state_port,
        dependencies.secret_port,
        dependencies.material_port,
    )
    driver = dependencies.driver_factory(preparation.driver_authority_resolver)
    if driver is None or isinstance(driver, Mapping):
        raise ValueError("invalid internal supervisor driver")
    access_network_gate = dependencies.access_network_gate_factory(driver)
    if access_network_gate is None or isinstance(access_network_gate, Mapping):
        raise ValueError("invalid internal supervisor access network gate")
    reconciler = RuntimeSupervisorReconciler(
        repository,
        preparation,
        driver,
        access_network_gate,
        dependencies.offline_identity_publisher,
    )
    daemon = RuntimeSupervisorDaemon(repository, reconciler)
    return InternalSupervisorAssembly(
        repository=repository,
        preparation=preparation,
        driver=driver,
        access_network_gate=access_network_gate,
        reconciler=reconciler,
        daemon=daemon,
    )
