from __future__ import annotations

import unittest
from unittest import mock

from tests.test_runtime_snapshot import valid_authority
from tools.runtime_artifacts import VerifiedReadOnlyMaterialLease
from tools.runtime_preparation_lease import (
    ActiveLaunchAuthorityLease,
    LaunchPreparationLeaseError,
)
from tools.runtime_secrets import VerifiedSecretMountLease
from tools.runtime_state import VerifiedStateMountLease


def _uninitialized_lease(lease_type: type[object]) -> object:
    return object.__new__(lease_type)


class ActiveLaunchAuthorityLeaseTests(unittest.TestCase):
    def test_revalidates_all_original_provider_leases_before_runtime_action(
        self,
    ) -> None:
        authority = valid_authority()
        material_lease = _uninitialized_lease(VerifiedReadOnlyMaterialLease)
        state_lease = _uninitialized_lease(VerifiedStateMountLease)
        secret_lease = _uninitialized_lease(VerifiedSecretMountLease)

        with (
            mock.patch.object(
                VerifiedReadOnlyMaterialLease,
                "materials",
                new_callable=mock.PropertyMock,
                return_value=authority.materials,
            ),
            mock.patch.object(
                VerifiedStateMountLease,
                "mount",
                new_callable=mock.PropertyMock,
                return_value=authority.state,
            ),
            mock.patch.object(
                VerifiedSecretMountLease,
                "mounts",
                new_callable=mock.PropertyMock,
                return_value=authority.secrets,
            ),
            mock.patch.object(
                VerifiedReadOnlyMaterialLease,
                "revalidate_sources",
            ) as material_revalidate,
            mock.patch.object(
                VerifiedStateMountLease,
                "revalidate_source",
                return_value=authority.state.source,
            ) as state_revalidate,
            mock.patch.object(
                VerifiedSecretMountLease,
                "revalidate_sources",
                return_value=authority.secrets,
            ) as secret_revalidate,
        ):
            lease = ActiveLaunchAuthorityLease(
                authority,
                material_lease,
                state_lease,
                secret_lease,
            )
            lease.revalidate_for_runtime_action()

        material_revalidate.assert_called_once_with()
        state_revalidate.assert_called_once_with()
        secret_revalidate.assert_called_once_with()

    def test_rejects_lease_that_did_not_mint_the_authority_values(self) -> None:
        authority = valid_authority()
        material_lease = _uninitialized_lease(VerifiedReadOnlyMaterialLease)
        state_lease = _uninitialized_lease(VerifiedStateMountLease)
        secret_lease = _uninitialized_lease(VerifiedSecretMountLease)

        with (
            mock.patch.object(
                VerifiedReadOnlyMaterialLease,
                "materials",
                new_callable=mock.PropertyMock,
                return_value=authority.materials[:-1],
            ),
            mock.patch.object(
                VerifiedStateMountLease,
                "mount",
                new_callable=mock.PropertyMock,
                return_value=authority.state,
            ),
            mock.patch.object(
                VerifiedSecretMountLease,
                "mounts",
                new_callable=mock.PropertyMock,
                return_value=authority.secrets,
            ),
            self.assertRaisesRegex(
                LaunchPreparationLeaseError,
                "^launch_preparation_lease_invalid$",
            ),
        ):
            ActiveLaunchAuthorityLease(
                authority,
                material_lease,
                state_lease,
                secret_lease,
            )

    def test_closed_source_lease_fails_before_later_runtime_preparation(self) -> None:
        authority = valid_authority()
        material_lease = _uninitialized_lease(VerifiedReadOnlyMaterialLease)
        state_lease = _uninitialized_lease(VerifiedStateMountLease)
        secret_lease = _uninitialized_lease(VerifiedSecretMountLease)

        with (
            mock.patch.object(
                VerifiedReadOnlyMaterialLease,
                "materials",
                new_callable=mock.PropertyMock,
                return_value=authority.materials,
            ),
            mock.patch.object(
                VerifiedStateMountLease,
                "mount",
                new_callable=mock.PropertyMock,
                return_value=authority.state,
            ),
            mock.patch.object(
                VerifiedSecretMountLease,
                "mounts",
                new_callable=mock.PropertyMock,
                return_value=authority.secrets,
            ),
        ):
            lease = ActiveLaunchAuthorityLease(
                authority,
                material_lease,
                state_lease,
                secret_lease,
            )

        with (
            mock.patch.object(
                VerifiedReadOnlyMaterialLease,
                "revalidate_sources",
                side_effect=ValueError("material_lease_closed"),
            ),
            mock.patch.object(
                VerifiedStateMountLease,
                "revalidate_source",
            ) as state_revalidate,
            mock.patch.object(
                VerifiedSecretMountLease,
                "revalidate_sources",
            ) as secret_revalidate,
            self.assertRaisesRegex(ValueError, "^material_lease_closed$"),
        ):
            lease.revalidate_for_runtime_action()

        state_revalidate.assert_not_called()
        secret_revalidate.assert_not_called()

    def test_close_attempts_every_lease_before_reraising_first_error(self) -> None:
        authority = valid_authority()
        material_lease = _uninitialized_lease(VerifiedReadOnlyMaterialLease)
        state_lease = _uninitialized_lease(VerifiedStateMountLease)
        secret_lease = _uninitialized_lease(VerifiedSecretMountLease)

        with (
            mock.patch.object(
                VerifiedReadOnlyMaterialLease,
                "materials",
                new_callable=mock.PropertyMock,
                return_value=authority.materials,
            ),
            mock.patch.object(
                VerifiedStateMountLease,
                "mount",
                new_callable=mock.PropertyMock,
                return_value=authority.state,
            ),
            mock.patch.object(
                VerifiedSecretMountLease,
                "mounts",
                new_callable=mock.PropertyMock,
                return_value=authority.secrets,
            ),
        ):
            lease = ActiveLaunchAuthorityLease(
                authority,
                material_lease,
                state_lease,
                secret_lease,
            )

        for error in (KeyboardInterrupt(), SystemExit(), OSError("close failed")):
            with (
                self.subTest(error_type=type(error).__name__),
                mock.patch.object(
                    VerifiedSecretMountLease,
                    "close",
                    side_effect=error,
                ) as secret_close,
                mock.patch.object(
                    VerifiedStateMountLease,
                    "close",
                ) as state_close,
                mock.patch.object(
                    VerifiedReadOnlyMaterialLease,
                    "close",
                ) as material_close,
                self.assertRaises(type(error)),
            ):
                lease.close()

            secret_close.assert_called_once_with()
            state_close.assert_called_once_with()
            material_close.assert_called_once_with()

    def test_rejects_untyped_lease_ingress(self) -> None:
        authority = valid_authority()
        with self.assertRaisesRegex(
            LaunchPreparationLeaseError,
            "^launch_preparation_lease_invalid$",
        ):
            ActiveLaunchAuthorityLease(authority, object(), object(), object())

    def test_repr_does_not_expose_provider_or_host_paths(self) -> None:
        authority = valid_authority()
        material_lease = _uninitialized_lease(VerifiedReadOnlyMaterialLease)
        state_lease = _uninitialized_lease(VerifiedStateMountLease)
        secret_lease = _uninitialized_lease(VerifiedSecretMountLease)

        with (
            mock.patch.object(
                VerifiedReadOnlyMaterialLease,
                "materials",
                new_callable=mock.PropertyMock,
                return_value=authority.materials,
            ),
            mock.patch.object(
                VerifiedStateMountLease,
                "mount",
                new_callable=mock.PropertyMock,
                return_value=authority.state,
            ),
            mock.patch.object(
                VerifiedSecretMountLease,
                "mounts",
                new_callable=mock.PropertyMock,
                return_value=authority.secrets,
            ),
        ):
            representation = repr(
                ActiveLaunchAuthorityLease(
                    authority,
                    material_lease,
                    state_lease,
                    secret_lease,
                )
            )

        self.assertIn(authority.attempt.attempt_id, representation)
        for material in authority.materials:
            self.assertNotIn(str(material.source_path), representation)
        for secret in authority.secrets:
            self.assertNotIn(str(secret.source), representation)
        self.assertNotIn(str(authority.state.source), representation)


if __name__ == "__main__":
    unittest.main()
