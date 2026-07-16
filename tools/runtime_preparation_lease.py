from __future__ import annotations

from dataclasses import dataclass

from tools.runtime_artifacts import VerifiedReadOnlyMaterialLease
from tools.runtime_secrets import VerifiedSecretMountLease
from tools.runtime_snapshot import LaunchCompilationAuthority
from tools.runtime_state import VerifiedStateMountLease


class LaunchPreparationLeaseError(RuntimeError):
    code = "launch_preparation_lease_invalid"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True, repr=False)
class ActiveLaunchAuthorityLease:
    """Keeps the exact provider leases that minted one compilation authority."""

    authority: LaunchCompilationAuthority
    material_lease: VerifiedReadOnlyMaterialLease
    state_lease: VerifiedStateMountLease
    secret_lease: VerifiedSecretMountLease

    def __post_init__(self) -> None:
        if (
            type(self.authority) is not LaunchCompilationAuthority
            or type(self.material_lease) is not VerifiedReadOnlyMaterialLease
            or type(self.state_lease) is not VerifiedStateMountLease
            or type(self.secret_lease) is not VerifiedSecretMountLease
        ):
            raise LaunchPreparationLeaseError()
        self._require_exact_binding()

    def revalidate_for_runtime_action(self) -> None:
        """Revalidate every source immediately before a runtime mutation."""

        self.material_lease.revalidate_sources()
        state_source = self.state_lease.revalidate_source()
        secrets = self.secret_lease.revalidate_sources()
        if state_source is not self.authority.state.source and (
            type(state_source) is not type(self.authority.state.source)
            or state_source != self.authority.state.source
        ):
            raise LaunchPreparationLeaseError()
        if secrets is not self.authority.secrets and (
            len(secrets) != len(self.authority.secrets)
            or any(
                current is not expected
                for current, expected in zip(
                    secrets,
                    self.authority.secrets,
                    strict=True,
                )
            )
        ):
            raise LaunchPreparationLeaseError()
        self._require_exact_binding()

    def close(self) -> None:
        first_error: BaseException | None = None
        for lease in (self.secret_lease, self.state_lease, self.material_lease):
            try:
                lease.close()
            except BaseException as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

    def __enter__(self) -> ActiveLaunchAuthorityLease:
        self._require_exact_binding()
        return self

    def __exit__(self, *_exception: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            "<ActiveLaunchAuthorityLease "
            f"attempt_id={self.authority.attempt.attempt_id!r}>"
        )

    def _require_exact_binding(self) -> None:
        materials = self.material_lease.materials
        state = self.state_lease.mount
        secrets = self.secret_lease.mounts
        if (
            len(materials) != len(self.authority.materials)
            or any(
                current is not expected
                for current, expected in zip(
                    materials,
                    self.authority.materials,
                    strict=True,
                )
            )
            or state is not self.authority.state
            or len(secrets) != len(self.authority.secrets)
            or any(
                current is not expected
                for current, expected in zip(
                    secrets,
                    self.authority.secrets,
                    strict=True,
                )
            )
        ):
            raise LaunchPreparationLeaseError()
