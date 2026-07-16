from __future__ import annotations

import errno
import os
import re
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from tools.bootstrap_runtime import (
    _harden_managed_state_directory,
    _harden_managed_state_identity_file,
    _is_windows,
    _verify_managed_state_directory,
    _verify_managed_state_identity_file,
)


DEFAULT_STATE_ROOT = Path("ft_userdata/runtime/instances")

DurabilityLevel = Literal["atomic-process-crash", "power-loss-posix"]

_IDENTIFIER_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
_PROVIDER_ID: Final = "managed-local-v1"
_LAYOUT_ID: Final = "freqtrade-state-v1"
_LAYOUT_DIRECTORIES: Final = ("home", "logs", "data")

_RESERVATION_ERROR: Final = "state_reservation_invalid"
_ROOT_ERROR: Final = "state_root_invalid"
_EXISTS_ERROR: Final = "state_allocation_exists"
_PROVISION_ERROR: Final = "state_provision_failed"
_QUARANTINE_ERROR: Final = "state_quarantine_failed"
_EXISTING_ERROR: Final = "state_existing_invalid"
_VERIFY_EXISTING_ERROR: Final = "state_existing_verification_failed"
_PROVISIONING_ERROR: Final = "state_provisioning_invalid"
_PROVISIONING_PARTIAL_ERROR: Final = "state_provisioning_partial"
_PROVISIONING_FOREIGN_ERROR: Final = "state_provisioning_foreign"
_PROVISIONING_QUARANTINED_ERROR: Final = "state_provisioning_quarantined"
_VERIFY_PROVISIONING_ERROR: Final = "state_provisioning_verification_failed"
_LEASE_ERROR: Final = "state_lease_invalid"
_LEASE_VERIFICATION_ERROR: Final = "state_lease_verification_failed"


class StateProvisionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StateAllocationReservation:
    state_allocation_id: str
    instance_id: str
    layout_id: str
    provider_id: str
    relative_path: str
    kind: str
    status: str
    generation: int
    restore_source_bundle_id: str | None


@dataclass(frozen=True, slots=True)
class ExistingStateAllocation:
    state_allocation_id: str
    instance_id: str
    layout_id: str
    provider_id: str
    relative_path: str
    kind: str
    status: str
    generation: int
    restore_source_bundle_id: str | None


@dataclass(frozen=True, slots=True)
class ProvisioningStateAllocation:
    state_allocation_id: str
    instance_id: str
    layout_id: str
    provider_id: str
    relative_path: str
    kind: str
    status: str
    generation: int
    restore_source_bundle_id: str | None


@dataclass(frozen=True, slots=True)
class ProvisionedState:
    state_allocation_id: str
    instance_id: str
    layout_id: str
    provider_id: str
    generation: int
    relative_path: str
    durability: DurabilityLevel


@dataclass(frozen=True, slots=True)
class VerifiedStateMount:
    attempt_id: str
    state_allocation_id: str
    instance_id: str
    layout_id: str
    provider_id: str
    generation: int
    relative_path: str
    source: Path = field(repr=False)
    runtime_uid: int
    durability: DurabilityLevel

    def __post_init__(self) -> None:
        identifiers = (
            self.attempt_id,
            self.state_allocation_id,
            self.instance_id,
            self.layout_id,
            self.provider_id,
        )
        expected_relative_path = f"ft_userdata/runtime/instances/{self.instance_id}"
        try:
            normalized_source = Path(os.path.abspath(os.fspath(self.source)))
        except (OSError, TypeError, ValueError):
            raise StateProvisionError(_LEASE_ERROR) from None
        if (
            not all(
                isinstance(value, str) and _IDENTIFIER_PATTERN.fullmatch(value)
                for value in identifiers
            )
            or self.layout_id != _LAYOUT_ID
            or self.provider_id != _PROVIDER_ID
            or type(self.generation) is not int
            or self.generation < 1
            or self.relative_path != expected_relative_path
            or not isinstance(self.source, Path)
            or self.source != normalized_source
            or type(self.runtime_uid) is not int
            or self.runtime_uid < 0
            or self.durability not in ("atomic-process-crash", "power-loss-posix")
        ):
            raise StateProvisionError(_LEASE_ERROR)


@dataclass(frozen=True, slots=True)
class _VerifiedStateLayout:
    source: Path
    root_ancestry: tuple[os.stat_result, ...]
    allocation_status: os.stat_result
    component_statuses: tuple[tuple[str, os.stat_result], ...]
    identity_status: os.stat_result


@dataclass(frozen=True, slots=True)
class _IssuedStateProof:
    state: ProvisionedState
    layout: _VerifiedStateLayout


@dataclass(frozen=True, slots=True)
class _IssuedStateMountIdentity:
    attempt_id: str
    state_allocation_id: str
    instance_id: str
    layout_id: str
    provider_id: str
    generation: int
    relative_path: str
    source: Path
    runtime_uid: int
    durability: DurabilityLevel


@dataclass(frozen=True, slots=True)
class _ActiveStateLease:
    lease: VerifiedStateMountLease
    mount: VerifiedStateMount
    identity: _IssuedStateMountIdentity
    layout: _VerifiedStateLayout


class VerifiedStateMountLease:
    __slots__ = ("_closed", "_lease_id", "_provider")

    def __init__(self, provider: ManagedStateProvider, lease_id: str) -> None:
        self._provider = provider
        self._lease_id = lease_id
        self._closed = False

    @property
    def mount(self) -> VerifiedStateMount:
        return self._provider._mount_for_lease(self)

    def revalidate_source(self) -> Path:
        return self._provider.revalidate_source(self)

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._provider._close_mount_lease(self)
        finally:
            self._closed = True

    def __enter__(self) -> VerifiedStateMountLease:
        self._provider._mount_for_lease(self)
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def __repr__(self) -> str:
        state = "closed" if self._closed else "open"
        return f"<VerifiedStateMountLease {state}>"


class ManagedStateProvider:
    __slots__ = (
        "_active_leases",
        "_issued_proofs",
        "_reservation",
        "_runtime_uid",
        "_state_root",
    )

    def __init__(
        self,
        reservation: (
            StateAllocationReservation
            | ExistingStateAllocation
            | ProvisioningStateAllocation
        ),
        *,
        runtime_uid: int,
        state_root: Path = DEFAULT_STATE_ROOT,
    ) -> None:
        self._reservation = reservation
        self._runtime_uid = runtime_uid
        self._active_leases: dict[str, _ActiveStateLease] = {}
        self._issued_proofs: list[_IssuedStateProof] = []
        try:
            self._state_root = Path(os.path.abspath(os.fspath(state_root)))
        except (OSError, TypeError, ValueError):
            raise StateProvisionError(_ROOT_ERROR) from None

    def provision(
        self,
        instance_id: str,
        allocation_id: str,
        layout_id: str,
    ) -> ProvisionedState:
        reservation = self._reservation
        if not _reservation_is_valid(
            reservation,
            self._runtime_uid,
            instance_id,
            allocation_id,
            layout_id,
        ):
            raise StateProvisionError(_RESERVATION_ERROR)

        root_status = _validate_root(self._state_root, self._runtime_uid)
        return self._provision_missing(
            reservation,
            root_status,
            instance_id,
            allocation_id,
            layout_id,
        )

    def _provision_missing(
        self,
        allocation_record: StateAllocationReservation | ProvisioningStateAllocation,
        root_status: os.stat_result,
        instance_id: str,
        allocation_id: str,
        layout_id: str,
    ) -> ProvisionedState:
        allocation = self._state_root / instance_id
        quarantine = self._state_root / f".{allocation_id}.quarantine"
        if os.path.lexists(allocation) or os.path.lexists(quarantine):
            raise StateProvisionError(_EXISTS_ERROR)
        try:
            os.mkdir(allocation, 0o700)
        except FileExistsError:
            raise StateProvisionError(_EXISTS_ERROR) from None
        except OSError:
            raise StateProvisionError(_PROVISION_ERROR) from None

        allocation_status: os.stat_result | None = None
        try:
            allocation_status = os.lstat(allocation)
            _require_directory(allocation_status)
            _harden_managed_state_directory(allocation, self._runtime_uid)
            allocation_status = _validated_directory_status(
                allocation,
                self._runtime_uid,
            )
            _require_root_identity(self._state_root, root_status, self._runtime_uid)
            component_statuses = _create_layout(
                allocation,
                allocation_id,
                self._runtime_uid,
            )
            _validate_final_layout(
                self._state_root,
                root_status,
                allocation,
                allocation_status,
                allocation_id,
                component_statuses,
                self._runtime_uid,
            )
            root_barrier_status = _validated_directory_status(
                self._state_root,
                self._runtime_uid,
            )
            if not _same_identity(root_status, root_barrier_status):
                raise OSError
            _sync_directory(self._state_root, root_barrier_status)
            _require_root_identity(self._state_root, root_status, self._runtime_uid)
            final_allocation_status = _validated_directory_status(
                allocation,
                self._runtime_uid,
            )
            if not _same_directory_identity(
                allocation_status,
                final_allocation_status,
            ):
                raise OSError
            verified_layout = _verify_existing_layout(
                self._state_root,
                root_status,
                instance_id,
                allocation_id,
                self._runtime_uid,
            )
        except Exception:
            if _quarantine_owned_allocation(
                self._state_root,
                root_status,
                allocation,
                allocation_status,
                allocation_id,
                instance_id,
                self._runtime_uid,
            ):
                raise StateProvisionError(_PROVISION_ERROR) from None
            raise StateProvisionError(_QUARANTINE_ERROR) from None

        state = ProvisionedState(
            state_allocation_id=allocation_id,
            instance_id=instance_id,
            layout_id=layout_id,
            provider_id=allocation_record.provider_id,
            generation=allocation_record.generation,
            relative_path=allocation_record.relative_path,
            durability=(
                "atomic-process-crash" if _is_windows() else "power-loss-posix"
            ),
        )
        return self._remember_proof(state, verified_layout)

    def resume_provisioning(
        self,
        instance_id: str,
        allocation_id: str,
        layout_id: str,
    ) -> ProvisionedState:
        allocation_record = self._reservation
        if not _provisioning_is_valid(
            allocation_record,
            self._runtime_uid,
            instance_id,
            allocation_id,
            layout_id,
        ):
            raise StateProvisionError(_PROVISIONING_ERROR)

        try:
            root_status = _validate_root(self._state_root, self._runtime_uid)
        except StateProvisionError:
            raise StateProvisionError(_VERIFY_PROVISIONING_ERROR) from None

        allocation = self._state_root / instance_id
        quarantine = self._state_root / f".{allocation_id}.quarantine"
        if os.path.lexists(quarantine):
            raise StateProvisionError(_PROVISIONING_QUARANTINED_ERROR)

        try:
            allocation_status = os.lstat(allocation)
        except FileNotFoundError:
            try:
                return self._provision_missing(
                    allocation_record,
                    root_status,
                    instance_id,
                    allocation_id,
                    layout_id,
                )
            except StateProvisionError as error:
                if os.path.lexists(quarantine) and not os.path.lexists(allocation):
                    raise StateProvisionError(_PROVISIONING_QUARANTINED_ERROR) from None
                if str(error) == _EXISTS_ERROR:
                    raise StateProvisionError(_PROVISIONING_FOREIGN_ERROR) from None
                raise StateProvisionError(_VERIFY_PROVISIONING_ERROR) from None
        except OSError:
            raise StateProvisionError(_VERIFY_PROVISIONING_ERROR) from None

        try:
            _require_directory(allocation_status)
        except OSError:
            raise StateProvisionError(_PROVISIONING_FOREIGN_ERROR) from None
        try:
            verified_allocation_status = _validated_directory_status(
                allocation,
                self._runtime_uid,
            )
        except (OSError, RuntimeError, StateProvisionError, ValueError):
            raise StateProvisionError(_VERIFY_PROVISIONING_ERROR) from None
        if not _same_directory_identity(
            allocation_status,
            verified_allocation_status,
        ):
            raise StateProvisionError(_VERIFY_PROVISIONING_ERROR)
        allocation_status = verified_allocation_status

        identity_name = f".allocation-{allocation_id}"
        expected_names = {*_LAYOUT_DIRECTORIES, identity_name}
        try:
            _require_root_identity(self._state_root, root_status, self._runtime_uid)
            _require_contained_allocation(self._state_root, allocation)
            with os.scandir(allocation) as entries:
                actual_names = {entry.name for entry in entries}
        except (OSError, RuntimeError, StateProvisionError, ValueError):
            raise StateProvisionError(_VERIFY_PROVISIONING_ERROR) from None

        if not actual_names <= expected_names:
            raise StateProvisionError(_PROVISIONING_FOREIGN_ERROR)

        component_names = tuple(
            name for name in _LAYOUT_DIRECTORIES if name in actual_names
        )
        try:
            observed_component_statuses = {
                name: os.lstat(allocation / name) for name in component_names
            }
            observed_identity_status = (
                os.lstat(allocation / identity_name)
                if identity_name in actual_names
                else None
            )
        except OSError:
            raise StateProvisionError(_VERIFY_PROVISIONING_ERROR) from None

        try:
            for status in observed_component_statuses.values():
                _require_directory(status)
            if observed_identity_status is not None:
                _require_empty_identity_file(observed_identity_status)
        except OSError:
            raise StateProvisionError(_PROVISIONING_FOREIGN_ERROR) from None

        try:
            component_statuses = {
                name: _validated_directory_status(
                    allocation / name,
                    self._runtime_uid,
                )
                for name in component_names
            }
            identity_status = (
                _verified_identity_file_status(
                    allocation / identity_name,
                    self._runtime_uid,
                )
                if observed_identity_status is not None
                else None
            )
        except (OSError, RuntimeError, StateProvisionError, ValueError):
            raise StateProvisionError(_VERIFY_PROVISIONING_ERROR) from None
        if any(
            not _same_directory_identity(
                observed_component_statuses[name],
                component_statuses[name],
            )
            for name in component_names
        ) or (
            observed_identity_status is not None
            and (
                identity_status is None
                or not _same_managed_file_identity(
                    observed_identity_status,
                    identity_status,
                )
            )
        ):
            raise StateProvisionError(_VERIFY_PROVISIONING_ERROR)

        if actual_names < expected_names:
            raise StateProvisionError(_PROVISIONING_PARTIAL_ERROR)

        try:
            verified_layout = _verify_existing_layout(
                self._state_root,
                root_status,
                instance_id,
                allocation_id,
                self._runtime_uid,
            )
        except (OSError, RuntimeError, StateProvisionError, ValueError):
            if os.path.lexists(quarantine):
                raise StateProvisionError(_PROVISIONING_QUARANTINED_ERROR) from None
            raise StateProvisionError(_VERIFY_PROVISIONING_ERROR) from None
        final_component_statuses = dict(verified_layout.component_statuses)
        if (
            identity_status is None
            or not _same_directory_identity(
                allocation_status,
                verified_layout.allocation_status,
            )
            or set(final_component_statuses) != set(component_statuses)
            or any(
                not _same_directory_identity(
                    component_statuses[name],
                    final_component_statuses[name],
                )
                for name in component_statuses
            )
            or not _same_managed_file_identity(
                identity_status,
                verified_layout.identity_status,
            )
        ):
            raise StateProvisionError(_VERIFY_PROVISIONING_ERROR)

        state = ProvisionedState(
            state_allocation_id=allocation_id,
            instance_id=instance_id,
            layout_id=layout_id,
            provider_id=allocation_record.provider_id,
            generation=allocation_record.generation,
            relative_path=allocation_record.relative_path,
            durability=(
                "atomic-process-crash" if _is_windows() else "power-loss-posix"
            ),
        )
        return self._remember_proof(state, verified_layout)

    def verify_existing(
        self,
        instance_id: str,
        allocation_id: str,
        layout_id: str,
    ) -> ProvisionedState:
        allocation_record = self._reservation
        if not _existing_is_valid(
            allocation_record,
            self._runtime_uid,
            instance_id,
            allocation_id,
            layout_id,
        ):
            raise StateProvisionError(_EXISTING_ERROR)

        try:
            root_status = _validate_root(self._state_root, self._runtime_uid)
            verified_layout = _verify_existing_layout(
                self._state_root,
                root_status,
                instance_id,
                allocation_id,
                self._runtime_uid,
            )
        except (OSError, RuntimeError, StateProvisionError, ValueError):
            raise StateProvisionError(_VERIFY_EXISTING_ERROR) from None

        state = ProvisionedState(
            state_allocation_id=allocation_id,
            instance_id=instance_id,
            layout_id=layout_id,
            provider_id=allocation_record.provider_id,
            generation=allocation_record.generation,
            relative_path=allocation_record.relative_path,
            durability=(
                "atomic-process-crash" if _is_windows() else "power-loss-posix"
            ),
        )
        return self._remember_proof(state, verified_layout)

    def acquire_mount_lease(
        self,
        attempt_id: str,
        proof: ProvisionedState,
    ) -> VerifiedStateMountLease:
        if (
            not isinstance(attempt_id, str)
            or _IDENTIFIER_PATTERN.fullmatch(attempt_id) is None
            or not isinstance(proof, ProvisionedState)
            or self._active_leases
        ):
            raise StateProvisionError(_LEASE_ERROR)
        issued = next(
            (
                candidate
                for candidate in self._issued_proofs
                if candidate.state is proof
            ),
            None,
        )
        if issued is None:
            raise StateProvisionError(_LEASE_ERROR)

        current = self._verify_lease_layout(proof)
        if not _same_verified_layout(issued.layout, current):
            raise StateProvisionError(_LEASE_VERIFICATION_ERROR)

        mount = VerifiedStateMount(
            attempt_id=attempt_id,
            state_allocation_id=proof.state_allocation_id,
            instance_id=proof.instance_id,
            layout_id=proof.layout_id,
            provider_id=proof.provider_id,
            generation=proof.generation,
            relative_path=proof.relative_path,
            source=current.source,
            runtime_uid=self._runtime_uid,
            durability=proof.durability,
        )
        lease_id = secrets.token_hex(32)
        while lease_id in self._active_leases:
            lease_id = secrets.token_hex(32)
        lease = VerifiedStateMountLease(self, lease_id)
        self._active_leases[lease_id] = _ActiveStateLease(
            lease=lease,
            mount=mount,
            identity=_IssuedStateMountIdentity(
                attempt_id=mount.attempt_id,
                state_allocation_id=mount.state_allocation_id,
                instance_id=mount.instance_id,
                layout_id=mount.layout_id,
                provider_id=mount.provider_id,
                generation=mount.generation,
                relative_path=mount.relative_path,
                source=current.source,
                runtime_uid=mount.runtime_uid,
                durability=mount.durability,
            ),
            layout=current,
        )
        return lease

    def revalidate_source(self, lease: VerifiedStateMountLease) -> Path:
        active = self._require_active_lease(lease)
        self._require_minted_mount(active)
        current = self._verify_lease_layout_values(
            active.identity.instance_id,
            active.identity.state_allocation_id,
        )
        if not _same_verified_layout(active.layout, current):
            raise StateProvisionError(_LEASE_VERIFICATION_ERROR)
        return active.identity.source

    def _remember_proof(
        self,
        state: ProvisionedState,
        layout: _VerifiedStateLayout,
    ) -> ProvisionedState:
        self._issued_proofs.append(_IssuedStateProof(state=state, layout=layout))
        return state

    def _verify_lease_layout(self, proof: ProvisionedState) -> _VerifiedStateLayout:
        return self._verify_lease_layout_values(
            proof.instance_id,
            proof.state_allocation_id,
        )

    def _verify_lease_layout_values(
        self,
        instance_id: str,
        allocation_id: str,
    ) -> _VerifiedStateLayout:
        try:
            root_status = _validate_root(self._state_root, self._runtime_uid)
            return _verify_existing_layout(
                self._state_root,
                root_status,
                instance_id,
                allocation_id,
                self._runtime_uid,
            )
        except (OSError, RuntimeError, StateProvisionError, ValueError):
            raise StateProvisionError(_LEASE_VERIFICATION_ERROR) from None

    def _require_active_lease(
        self,
        lease: VerifiedStateMountLease,
    ) -> _ActiveStateLease:
        if type(lease) is not VerifiedStateMountLease:
            raise StateProvisionError(_LEASE_ERROR)
        active = self._active_leases.get(lease._lease_id)
        if (
            active is None
            or active.lease is not lease
            or lease._provider is not self
            or lease._closed
        ):
            raise StateProvisionError(_LEASE_ERROR)
        return active

    def _mount_for_lease(self, lease: VerifiedStateMountLease) -> VerifiedStateMount:
        active = self._require_active_lease(lease)
        self._require_minted_mount(active)
        return active.mount

    def _close_mount_lease(self, lease: VerifiedStateMountLease) -> None:
        active = self._require_active_lease(lease)
        valid = _same_minted_mount(active.mount, active.identity)
        del self._active_leases[lease._lease_id]
        if not valid:
            raise StateProvisionError(_LEASE_VERIFICATION_ERROR)

    @staticmethod
    def _require_minted_mount(active: _ActiveStateLease) -> None:
        if not _same_minted_mount(active.mount, active.identity):
            raise StateProvisionError(_LEASE_VERIFICATION_ERROR)


def _same_minted_mount(
    mount: VerifiedStateMount,
    identity: _IssuedStateMountIdentity,
) -> bool:
    if (
        type(mount) is not VerifiedStateMount
        or type(identity) is not _IssuedStateMountIdentity
        or any(
            type(value) is not str
            for value in (
                mount.attempt_id,
                mount.state_allocation_id,
                mount.instance_id,
                mount.layout_id,
                mount.provider_id,
                mount.relative_path,
                mount.durability,
            )
        )
        or type(mount.generation) is not int
        or type(mount.runtime_uid) is not int
        or type(mount.source) is not type(Path())
    ):
        return False
    return (
        mount.attempt_id == identity.attempt_id
        and mount.state_allocation_id == identity.state_allocation_id
        and mount.instance_id == identity.instance_id
        and mount.layout_id == identity.layout_id
        and mount.provider_id == identity.provider_id
        and mount.generation == identity.generation
        and mount.relative_path == identity.relative_path
        and mount.source == identity.source
        and mount.runtime_uid == identity.runtime_uid
        and mount.durability == identity.durability
    )


def _reservation_is_valid(
    reservation: object,
    runtime_uid: object,
    instance_id: object,
    allocation_id: object,
    layout_id: object,
) -> bool:
    if not isinstance(reservation, StateAllocationReservation):
        return False
    identifiers = (
        reservation.state_allocation_id,
        reservation.instance_id,
        reservation.layout_id,
        reservation.provider_id,
        instance_id,
        allocation_id,
        layout_id,
    )
    if not all(
        isinstance(value, str) and _IDENTIFIER_PATTERN.fullmatch(value)
        for value in identifiers
    ):
        return False
    expected_relative_path = f"ft_userdata/runtime/instances/{reservation.instance_id}"
    return (
        reservation.state_allocation_id == allocation_id
        and reservation.instance_id == instance_id
        and reservation.layout_id == layout_id == _LAYOUT_ID
        and reservation.provider_id == _PROVIDER_ID
        and reservation.relative_path == expected_relative_path
        and reservation.kind == "fresh"
        and reservation.status == "reserved"
        and type(reservation.generation) is int
        and reservation.generation >= 1
        and reservation.restore_source_bundle_id is None
        and type(runtime_uid) is int
        and runtime_uid >= 0
    )


def _existing_is_valid(
    allocation: object,
    runtime_uid: object,
    instance_id: object,
    allocation_id: object,
    layout_id: object,
) -> bool:
    if not isinstance(allocation, ExistingStateAllocation):
        return False
    identifiers = (
        allocation.state_allocation_id,
        allocation.instance_id,
        allocation.layout_id,
        allocation.provider_id,
        instance_id,
        allocation_id,
        layout_id,
    )
    if not all(
        isinstance(value, str) and _IDENTIFIER_PATTERN.fullmatch(value)
        for value in identifiers
    ):
        return False
    expected_relative_path = f"ft_userdata/runtime/instances/{allocation.instance_id}"
    return (
        allocation.state_allocation_id == allocation_id
        and allocation.instance_id == instance_id
        and allocation.layout_id == layout_id == _LAYOUT_ID
        and allocation.provider_id == _PROVIDER_ID
        and allocation.relative_path == expected_relative_path
        and allocation.kind == "fresh"
        and allocation.status == "ready"
        and type(allocation.generation) is int
        and allocation.generation >= 1
        and allocation.restore_source_bundle_id is None
        and type(runtime_uid) is int
        and runtime_uid >= 0
    )


def _provisioning_is_valid(
    allocation: object,
    runtime_uid: object,
    instance_id: object,
    allocation_id: object,
    layout_id: object,
) -> bool:
    if type(allocation) is not ProvisioningStateAllocation:
        return False
    identifiers = (
        allocation.state_allocation_id,
        allocation.instance_id,
        allocation.layout_id,
        allocation.provider_id,
        instance_id,
        allocation_id,
        layout_id,
    )
    if not all(
        isinstance(value, str) and _IDENTIFIER_PATTERN.fullmatch(value)
        for value in identifiers
    ):
        return False
    expected_relative_path = f"ft_userdata/runtime/instances/{allocation.instance_id}"
    return (
        allocation.state_allocation_id == allocation_id
        and allocation.instance_id == instance_id
        and allocation.layout_id == layout_id == _LAYOUT_ID
        and allocation.provider_id == _PROVIDER_ID
        and allocation.relative_path == expected_relative_path
        and allocation.kind == "fresh"
        and allocation.status == "provisioning"
        and type(allocation.generation) is int
        and allocation.generation >= 1
        and allocation.restore_source_bundle_id is None
        and type(runtime_uid) is int
        and runtime_uid >= 0
    )


def _validate_root(state_root: Path, runtime_uid: int) -> os.stat_result:
    try:
        after = _verified_root_ancestry(state_root, runtime_uid)
        state_root.resolve(strict=True)
        return after[-1]
    except (OSError, RuntimeError, ValueError):
        raise StateProvisionError(_ROOT_ERROR) from None


def _require_root_identity(
    state_root: Path,
    expected: os.stat_result,
    runtime_uid: int,
) -> None:
    _verified_root_ancestry(state_root, runtime_uid, expected)


def _verified_root_ancestry(
    state_root: Path,
    runtime_uid: int,
    expected: os.stat_result | None = None,
) -> tuple[os.stat_result, ...]:
    before = _capture_directory_ancestry(state_root)
    _verify_managed_state_directory(state_root, runtime_uid)
    after = _capture_directory_ancestry(state_root)
    if (
        len(before) != len(after)
        or any(
            not _same_identity(previous, current)
            for previous, current in zip(before, after, strict=True)
        )
        or (expected is not None and not _same_identity(expected, after[-1]))
    ):
        raise OSError
    return after


def _capture_directory_ancestry(path: Path) -> tuple[os.stat_result, ...]:
    statuses: list[os.stat_result] = []
    for component in (*reversed(path.parents), path):
        status = os.lstat(component)
        _require_directory(status)
        statuses.append(status)
    return tuple(statuses)


def _create_layout(
    allocation: Path,
    allocation_id: str,
    runtime_uid: int,
) -> dict[str, os.stat_result]:
    statuses: dict[str, os.stat_result] = {}
    for name in _LAYOUT_DIRECTORIES:
        path = allocation / name
        os.mkdir(path, 0o700)
        _harden_managed_state_directory(path, runtime_uid)
        statuses[name] = _validated_directory_status(path, runtime_uid)
        _sync_directory(path, statuses[name])

    identity_name = f".allocation-{allocation_id}"
    identity = allocation / identity_name
    temporary = allocation / f".{identity_name}.{secrets.token_hex(8)}.tmp"
    descriptor: int | None = None
    synced_status: os.stat_result | None = None
    try:
        descriptor = os.open(temporary, _exclusive_write_flags(), 0o600)
        _harden_managed_state_identity_file(temporary, runtime_uid)
        opened = os.fstat(descriptor)
        _require_empty_identity_file(opened)
        _verify_managed_state_identity_file(temporary, runtime_uid)
        named = os.lstat(temporary)
        _require_empty_identity_file(named)
        if not _same_managed_file_identity(opened, named):
            raise OSError
        _sync_descriptor(descriptor)
        after = os.fstat(descriptor)
        _require_empty_identity_file(after)
        if not _same_managed_file_identity(opened, after):
            raise OSError
        synced_status = after
    finally:
        if descriptor is not None:
            os.close(descriptor)

    _publish_no_replace(temporary, identity)
    identity_status = os.lstat(identity)
    _require_empty_identity_file(identity_status)
    if synced_status is None or not _same_managed_file_identity(
        synced_status,
        identity_status,
    ):
        raise OSError
    _verify_managed_state_identity_file(identity, runtime_uid)
    statuses[identity_name] = identity_status
    allocation_barrier_status = _validated_directory_status(allocation, runtime_uid)
    _sync_directory(allocation, allocation_barrier_status)
    return statuses


def _validate_final_layout(
    state_root: Path,
    root_status: os.stat_result,
    allocation: Path,
    allocation_status: os.stat_result,
    allocation_id: str,
    component_statuses: dict[str, os.stat_result],
    runtime_uid: int,
) -> None:
    _require_root_identity(state_root, root_status, runtime_uid)
    if os.path.lexists(state_root / f".{allocation_id}.quarantine"):
        raise OSError
    current_allocation = _validated_directory_status(allocation, runtime_uid)
    if not _same_directory_identity(allocation_status, current_allocation):
        raise OSError
    try:
        allocation.resolve(strict=True).relative_to(state_root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        raise OSError from None

    identity_name = f".allocation-{allocation_id}"
    expected_names = {*_LAYOUT_DIRECTORIES, identity_name}
    with os.scandir(allocation) as entries:
        if {entry.name for entry in entries} != expected_names:
            raise OSError

    for name in _LAYOUT_DIRECTORIES:
        status = _validated_directory_status(allocation / name, runtime_uid)
        if not _same_directory_identity(component_statuses[name], status):
            raise OSError

    identity = allocation / identity_name
    status = os.lstat(identity)
    _require_empty_identity_file(status)
    if not _same_managed_file_identity(
        component_statuses[identity_name],
        status,
    ):
        raise OSError
    _verify_managed_state_identity_file(identity, runtime_uid)
    descriptor: int | None = None
    try:
        descriptor = os.open(identity, _read_only_flags())
        opened = os.fstat(descriptor)
        _require_empty_identity_file(opened)
        if (
            not _same_managed_file_identity(status, opened)
            or os.read(descriptor, 1) != b""
        ):
            raise OSError
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _verify_existing_layout(
    state_root: Path,
    root_status: os.stat_result,
    instance_id: str,
    allocation_id: str,
    runtime_uid: int,
) -> _VerifiedStateLayout:
    allocation = state_root / instance_id
    if os.path.lexists(state_root / f".{allocation_id}.quarantine"):
        raise OSError

    allocation_status = _validated_directory_status(allocation, runtime_uid)
    _require_root_identity(state_root, root_status, runtime_uid)
    _require_contained_allocation(state_root, allocation)

    identity_name = f".allocation-{allocation_id}"
    expected_names = {*_LAYOUT_DIRECTORIES, identity_name}
    with os.scandir(allocation) as entries:
        if {entry.name for entry in entries} != expected_names:
            raise OSError

    component_statuses = {
        name: _validated_directory_status(allocation / name, runtime_uid)
        for name in _LAYOUT_DIRECTORIES
    }

    identity = allocation / identity_name
    identity_status = os.lstat(identity)
    _require_empty_identity_file(identity_status)
    _verify_managed_state_identity_file(identity, runtime_uid)
    verified_identity_status = os.lstat(identity)
    _require_empty_identity_file(verified_identity_status)
    if not _same_managed_file_identity(
        identity_status,
        verified_identity_status,
    ):
        raise OSError

    descriptor: int | None = None
    try:
        descriptor = os.open(identity, _read_only_flags())
        opened_before = os.fstat(descriptor)
        _require_empty_identity_file(opened_before)
        if not _same_managed_file_identity(
            verified_identity_status,
            opened_before,
        ):
            raise OSError
        if os.read(descriptor, 1) != b"":
            raise OSError
        opened_after = os.fstat(descriptor)
        _require_empty_identity_file(opened_after)
        if not _same_managed_file_identity(opened_before, opened_after):
            raise OSError

        named_after = os.lstat(identity)
        _require_empty_identity_file(named_after)
        if not _same_managed_file_identity(opened_after, named_after):
            raise OSError
        _verify_managed_state_identity_file(identity, runtime_uid)
        named_verified = os.lstat(identity)
        _require_empty_identity_file(named_verified)
        if not _same_managed_file_identity(named_after, named_verified):
            raise OSError
    finally:
        if descriptor is not None:
            os.close(descriptor)

    _require_root_identity(state_root, root_status, runtime_uid)
    _require_contained_allocation(state_root, allocation)
    if os.path.lexists(state_root / f".{allocation_id}.quarantine"):
        raise OSError
    final_allocation_status = _validated_directory_status(allocation, runtime_uid)
    if not _same_directory_identity(allocation_status, final_allocation_status):
        raise OSError
    final_component_statuses: dict[str, os.stat_result] = {}
    for name, expected in component_statuses.items():
        current = _validated_directory_status(allocation / name, runtime_uid)
        if not _same_directory_identity(expected, current):
            raise OSError
        final_component_statuses[name] = current

    final_identity_status = os.lstat(identity)
    _require_empty_identity_file(final_identity_status)
    _verify_managed_state_identity_file(identity, runtime_uid)
    identity_after_permission = os.lstat(identity)
    _require_empty_identity_file(identity_after_permission)
    if not _same_managed_file_identity(
        final_identity_status,
        identity_after_permission,
    ):
        raise OSError
    if not _same_managed_file_identity(
        verified_identity_status,
        identity_after_permission,
    ):
        raise OSError

    with os.scandir(allocation) as entries:
        if {entry.name for entry in entries} != expected_names:
            raise OSError

    final_root_ancestry = _verified_root_ancestry(
        state_root,
        runtime_uid,
        root_status,
    )

    return _VerifiedStateLayout(
        source=allocation,
        root_ancestry=final_root_ancestry,
        allocation_status=final_allocation_status,
        component_statuses=tuple(
            (name, final_component_statuses[name]) for name in _LAYOUT_DIRECTORIES
        ),
        identity_status=identity_after_permission,
    )


def _require_contained_allocation(state_root: Path, allocation: Path) -> None:
    try:
        allocation.resolve(strict=True).relative_to(state_root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        raise OSError from None


def _quarantine_owned_allocation(
    state_root: Path,
    root_status: os.stat_result,
    allocation: Path,
    allocation_status: os.stat_result | None,
    allocation_id: str,
    instance_id: str,
    runtime_uid: int,
) -> bool:
    if allocation_status is None:
        return False
    try:
        _require_root_identity(state_root, root_status, runtime_uid)
        current = os.lstat(allocation)
        _require_directory(current)
        if not _same_identity(allocation_status, current):
            return False

        container = state_root / f".{allocation_id}.quarantine"
        destination = container / instance_id
        os.mkdir(container, 0o700)
        _harden_managed_state_directory(container, runtime_uid)
        _validated_directory_status(container, runtime_uid)
        current = os.lstat(allocation)
        _require_directory(current)
        if not _same_identity(allocation_status, current):
            return False
        _publish_no_replace(allocation, destination)
        moved = os.lstat(destination)
        _require_directory(moved)
        if not _same_identity(allocation_status, moved) or os.path.lexists(allocation):
            return False
        container_barrier_status = _validated_directory_status(container, runtime_uid)
        _sync_directory(container, container_barrier_status)
        root_barrier_status = _validated_directory_status(state_root, runtime_uid)
        if not _same_identity(root_status, root_barrier_status):
            return False
        _sync_directory(state_root, root_barrier_status)
        _require_root_identity(state_root, root_status, runtime_uid)
        moved_after = os.lstat(destination)
        _require_directory(moved_after)
        if not _same_identity(allocation_status, moved_after):
            return False
        return True
    except Exception:
        return False


def _validated_directory_status(path: Path, runtime_uid: int) -> os.stat_result:
    status = os.lstat(path)
    _require_directory(status)
    _verify_managed_state_directory(path, runtime_uid)
    after = os.lstat(path)
    _require_directory(after)
    if not _same_snapshot(status, after):
        raise OSError
    return after


def _verified_identity_file_status(
    path: Path,
    runtime_uid: int,
) -> os.stat_result:
    status = os.lstat(path)
    _require_empty_identity_file(status)
    _verify_managed_state_identity_file(path, runtime_uid)
    verified = os.lstat(path)
    _require_empty_identity_file(verified)
    if not _same_managed_file_identity(status, verified):
        raise OSError

    descriptor: int | None = None
    opened_after: os.stat_result | None = None
    try:
        descriptor = os.open(path, _read_only_flags())
        opened_before = os.fstat(descriptor)
        _require_empty_identity_file(opened_before)
        if not _same_managed_file_identity(verified, opened_before):
            raise OSError
        if os.read(descriptor, 1) != b"":
            raise OSError
        opened_after = os.fstat(descriptor)
        _require_empty_identity_file(opened_after)
        if not _same_managed_file_identity(opened_before, opened_after):
            raise OSError
    finally:
        if descriptor is not None:
            os.close(descriptor)

    named_after = os.lstat(path)
    _require_empty_identity_file(named_after)
    if opened_after is None or not _same_managed_file_identity(
        opened_after,
        named_after,
    ):
        raise OSError
    return named_after


def _require_directory(status: os.stat_result) -> None:
    if _is_link_or_reparse(status) or not stat.S_ISDIR(status.st_mode):
        raise OSError


def _require_empty_identity_file(status: os.stat_result) -> None:
    if (
        _is_link_or_reparse(status)
        or not stat.S_ISREG(status.st_mode)
        or status.st_nlink != 1
        or status.st_size != 0
    ):
        raise OSError


def _is_link_or_reparse(status: os.stat_result) -> bool:
    if stat.S_ISLNK(status.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    return bool(getattr(status, "st_file_attributes", 0) & reparse_flag)


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _same_directory_identity(left: os.stat_result, right: os.stat_result) -> bool:
    fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_uid",
        "st_gid",
        "st_file_attributes",
        "st_reparse_tag",
    )
    return all(
        getattr(left, field, None) == getattr(right, field, None) for field in fields
    )


def _same_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size")
    return all(
        getattr(left, field, None) == getattr(right, field, None) for field in fields
    )


def _same_managed_file_identity(
    left: os.stat_result,
    right: os.stat_result,
) -> bool:
    fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_uid",
        "st_gid",
        "st_file_attributes",
        "st_reparse_tag",
        "st_nlink",
        "st_size",
    )
    return all(
        getattr(left, field, None) == getattr(right, field, None) for field in fields
    )


def _same_verified_layout(
    left: _VerifiedStateLayout,
    right: _VerifiedStateLayout,
) -> bool:
    if left.source != right.source or len(left.root_ancestry) != len(
        right.root_ancestry
    ):
        return False
    if any(
        not _same_directory_identity(previous, current)
        for previous, current in zip(
            left.root_ancestry,
            right.root_ancestry,
            strict=True,
        )
    ):
        return False
    if not _same_directory_identity(left.allocation_status, right.allocation_status):
        return False
    if tuple(name for name, _status in left.component_statuses) != tuple(
        name for name, _status in right.component_statuses
    ):
        return False
    if any(
        not _same_directory_identity(previous, current)
        for (_left_name, previous), (_right_name, current) in zip(
            left.component_statuses,
            right.component_statuses,
            strict=True,
        )
    ):
        return False
    return _same_managed_file_identity(
        left.identity_status,
        right.identity_status,
    )


def _exclusive_write_flags() -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    for name in ("O_BINARY", "O_CLOEXEC", "O_NOINHERIT", "O_NOFOLLOW"):
        flags |= getattr(os, name, 0)
    return flags


def _read_only_flags() -> int:
    flags = os.O_RDONLY
    for name in ("O_BINARY", "O_CLOEXEC", "O_NOINHERIT", "O_NOFOLLOW"):
        flags |= getattr(os, name, 0)
    return flags


def _publish_no_replace(source: Path, destination: Path) -> None:
    if _is_windows():
        os.rename(source, destination)
        return
    if os.name != "posix":
        raise OSError(errno.ENOTSUP, "atomic no-replace publish is unsupported")

    import ctypes

    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
    except (AttributeError, OSError):
        raise OSError(
            errno.ENOTSUP, "atomic no-replace publish is unsupported"
        ) from None
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    at_fdcwd = -100
    rename_noreplace = 1
    result = renameat2(
        at_fdcwd,
        os.fsencode(source),
        at_fdcwd,
        os.fsencode(destination),
        rename_noreplace,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


def _sync_descriptor(descriptor: int) -> None:
    os.fsync(descriptor)


def _sync_directory(path: Path, expected: os.stat_result) -> None:
    named_before = os.lstat(path)
    _require_directory(named_before)
    if not _same_identity(expected, named_before):
        raise OSError
    if _is_windows():
        named_after = os.lstat(path)
        _require_directory(named_after)
        if not _same_snapshot(named_before, named_after):
            raise OSError
        return
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory is None:
        raise OSError(errno.ENOTSUP, "directory sync proof is unsupported")
    flags = os.O_RDONLY | no_follow | directory | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    try:
        opened_before = os.fstat(descriptor)
        _require_directory(opened_before)
        if not _same_snapshot(named_before, opened_before):
            raise OSError
        os.fsync(descriptor)
        opened_after = os.fstat(descriptor)
        _require_directory(opened_after)
        if not _same_snapshot(opened_before, opened_after):
            raise OSError
        named_after = os.lstat(path)
        _require_directory(named_after)
        if not _same_snapshot(opened_after, named_after):
            raise OSError
    finally:
        os.close(descriptor)
