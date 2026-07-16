from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
import hashlib
import json
import re
from typing import Protocol

from tools.runtime_access_network import compile_runtime_access_network_plan
from tools.runtime_artifacts import (
    CommittedPaperProbeArtifacts,
    VerifiedReadOnlyMaterial,
)
from tools.runtime_driver import (
    DriverIdentity,
    DriverInspection,
    DriverPolicyError,
    DriverTransportError,
    DriverValidationError,
    HealthProfile,
    LaunchSnapshot,
    RuntimeAccessNetworkPlan,
)
from tools.runtime_launch_policy import (
    NetworkIdentitySource,
    NetworkNameDerivation,
    ResolvedLaunchPolicyBundle,
    validate_resolved_launch_policy_bundle,
)
from tools.runtime_preparation_lease import ActiveLaunchAuthorityLease
from tools.runtime_secrets import (
    SecretMaterialRequirement,
    VerifiedSecretMount,
)
from tools.runtime_snapshot import (
    LaunchCompilationAuthority,
    ResolvedAttemptAuthority,
    ResolvedSecretVersionAuthority,
    RuntimeSpecLaunchAuthority,
    compile_launch_snapshot,
    validate_launch_snapshot,
)
from tools.runtime_state import VerifiedStateMount
from tools.runtime_supervisor.offline_identity import OfflineRuntimeIdentity
from tools.runtime_supervisor.reconciler import (
    LaunchProvenance,
    ReconciliationJob,
    RevalidatedAttempt,
)
from tools.runtime_templates import CommittedTemplate


_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_GIT_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
_RUNTIME_SPEC_FIELDS = frozenset(
    {
        "adapter_template_revision_id",
        "backend_commit",
        "catalog_revision_id",
        "command_policy_id",
        "config_blob_commit",
        "config_blob_digest",
        "environment",
        "frontend_commit",
        "health_profile_id",
        "image_policy_id",
        "instance_kind",
        "market_scope",
        "mount_policy_ids",
        "network_policy_id",
        "owner_ref",
        "resource_profile_id",
        "root_commit",
        "safety_policy_commit",
        "safety_policy_digest",
        "secret_reference_ids",
        "state_allocation_id",
        "state_layout_id",
        "strategies_commit",
        "strategy_class_name",
        "strategy_commit",
        "strategy_digest",
        "template_digest",
    }
)


class PersistedPreparationError(DriverPolicyError):
    def __init__(self, code: str) -> None:
        RuntimeError.__init__(self, code)


class PersistedPreparationRepositoryError(DriverTransportError):
    def __init__(self) -> None:
        RuntimeError.__init__(self, "persisted_repository_error")


@dataclass(frozen=True, slots=True)
class CommittedLaunchEvidence:
    template: CommittedTemplate
    policies: ResolvedLaunchPolicyBundle
    artifacts: CommittedPaperProbeArtifacts

    def __post_init__(self) -> None:
        if (
            type(self.template) is not CommittedTemplate
            or type(self.policies) is not ResolvedLaunchPolicyBundle
            or type(self.artifacts) is not CommittedPaperProbeArtifacts
        ):
            raise PersistedPreparationError("persisted_evidence_invalid")


@dataclass(frozen=True, slots=True)
class ResolvedImageIdentity:
    image_id: str
    image_policy_id: str
    root_commit: str
    backend_commit: str
    frontend_commit: str

    def __post_init__(self) -> None:
        if (
            type(self.image_id) is not str
            or _IMAGE_ID.fullmatch(self.image_id) is None
            or not _is_identifier(self.image_policy_id)
            or any(
                type(value) is not str or _GIT_OBJECT_ID.fullmatch(value) is None
                for value in (
                    self.root_commit,
                    self.backend_commit,
                    self.frontend_commit,
                )
            )
        ):
            raise PersistedPreparationError("persisted_image_invalid")


@dataclass(frozen=True, slots=True)
class _OwnerAuthority:
    owner_kind: str
    owner_id: str
    owner_revision: str


@dataclass(frozen=True, slots=True)
class _InstanceAuthority:
    instance_id: str
    instance_kind: str
    owner: _OwnerAuthority
    management_mode: str
    runtime_spec_revision_id: str
    environment: str
    state_allocation_id: str
    desired_state: str
    lifecycle_status: str
    failure_latched: bool
    optimistic_version: int


@dataclass(frozen=True, slots=True)
class _TemplateAuthority:
    adapter_template_revision_id: str
    canonical_payload: str
    payload_digest: str
    source_commit: str
    root_commit: str
    backend_commit: str
    frontend_commit: str
    strategies_commit: str
    status: str


@dataclass(frozen=True, slots=True)
class _StateAuthority:
    state_allocation_id: str
    instance_id: str
    layout_id: str
    provider_id: str
    generation: int


@dataclass(frozen=True, slots=True)
class _SecretAuthority:
    secret_reference_id: str
    provider_id: str
    secret_class: str
    logical_name: str
    owner: _OwnerAuthority
    active_version_id: str


@dataclass(frozen=True, slots=True)
class _PersistedAuthority:
    instance: _InstanceAuthority
    runtime_spec_revision_id: str
    canonical_runtime_spec: str
    runtime_spec_digest: str
    template: _TemplateAuthority
    state: _StateAuthority
    secrets: tuple[_SecretAuthority, ...]


def _same_frozen_active_authority(
    current: _PersistedAuthority,
    expected: _PersistedAuthority,
) -> bool:
    normalized = replace(
        current,
        template=replace(current.template, status=expected.template.status),
    )
    return normalized == expected


@dataclass(frozen=True, slots=True)
class _StateResolutionToken:
    session: _PreparationSession


@dataclass(slots=True)
class _PreparationSession:
    token: object
    active_resources: _CompilationResources | None = None
    compiled_snapshot: LaunchSnapshot | None = None
    compilation_authority: LaunchCompilationAuthority | None = None
    active_launch_lease: ActiveLaunchAuthorityLease | None = None

    def bind(self, resources: _CompilationResources) -> None:
        if (
            self.active_resources is not None
            or self.compiled_snapshot is not None
            or self.compilation_authority is not None
            or self.active_launch_lease is not None
        ):
            raise PersistedPreparationError("persisted_resource_context_invalid")
        self.active_resources = resources

    def release(self, resources: _CompilationResources) -> None:
        if self.active_resources is resources:
            self.active_resources = None
            self.compiled_snapshot = None
            self.compilation_authority = None
            self.active_launch_lease = None


@dataclass(frozen=True, slots=True)
class _PersistedRevalidatedAttempt(RevalidatedAttempt):
    job: ReconciliationJob
    persisted: _PersistedAuthority
    spec: RuntimeSpecLaunchAuthority
    evidence: CommittedLaunchEvidence
    attempt: ResolvedAttemptAuthority
    session: _PreparationSession
    active_authority: bool


class RepositoryPort(Protocol):
    def resolve_launch_authority_material(
        self,
        job_id: str,
        attempt_id: str,
        lease_owner: str,
        lease_generation: int,
    ) -> object: ...

    def revalidate_active_launch_authority_material(
        self,
        job_id: str,
        attempt_id: str,
        lease_owner: str,
        lease_generation: int,
    ) -> object: ...


class ResolvedMaterialFactory(Protocol):
    def __call__(self, attempt: ResolvedAttemptAuthority) -> object: ...


class ActiveLaunchLeaseFactory(Protocol):
    def __call__(
        self,
        authority: LaunchCompilationAuthority,
        material_lease: MaterialLease,
        state_lease: StateLease,
        secret_lease: SecretLease,
    ) -> ActiveLaunchAuthorityLease: ...


@dataclass(frozen=True, slots=True)
class _ActiveLaunchRegistration:
    revalidated: _PersistedRevalidatedAttempt
    resources: _CompilationResources
    snapshot: LaunchSnapshot
    authority: LaunchCompilationAuthority
    lease: ActiveLaunchAuthorityLease


class PersistedDriverAuthorityResolver:
    """Narrow SafeCompose authority view backed by one Preparation instance."""

    def __init__(self, preparation: PersistedAuthorityPreparation) -> None:
        self._preparation = preparation

    def resolve_active_launch(
        self,
        identity: DriverIdentity,
        launch_authority_digest: str,
    ) -> ActiveLaunchAuthorityLease:
        return self._preparation._resolve_active_launch(
            identity,
            launch_authority_digest,
        )

    def resolve_health_profile(
        self,
        identity: DriverIdentity,
        profile_id: str,
    ) -> HealthProfile:
        return self._preparation._resolve_driver_health_profile(identity, profile_id)


class ImageLease(Protocol):
    @property
    def identity(self) -> ResolvedImageIdentity: ...

    def revalidate_identity(self) -> ResolvedImageIdentity: ...

    def close(self) -> None: ...


class ImagePort(Protocol):
    def acquire_image(self, spec: RuntimeSpecLaunchAuthority) -> ImageLease: ...


class StateLease(Protocol):
    @property
    def mount(self) -> VerifiedStateMount: ...

    def revalidate_source(self) -> object: ...

    def close(self) -> None: ...


class StatePort(Protocol):
    def acquire_state(
        self,
        allocation: _StateAuthority,
        attempt_id: str,
        runtime_uid: int,
    ) -> StateLease: ...


class SecretLease(Protocol):
    @property
    def mounts(self) -> tuple[VerifiedSecretMount, ...]: ...

    def revalidate_sources(self) -> tuple[VerifiedSecretMount, ...]: ...

    def close(self) -> None: ...


class SecretPort(Protocol):
    def acquire_secrets(
        self,
        requirements: tuple[SecretMaterialRequirement, ...],
        attempt_id: str,
        runtime_uid: int,
    ) -> SecretLease: ...


class MaterialLease(Protocol):
    @property
    def materials(self) -> tuple[VerifiedReadOnlyMaterial, ...]: ...

    def revalidate_sources(self) -> object: ...

    def close(self) -> None: ...


class MaterialPort(Protocol):
    def load_evidence(self, root_commit: str) -> CommittedLaunchEvidence: ...

    def revalidate_evidence(
        self, evidence: CommittedLaunchEvidence
    ) -> CommittedLaunchEvidence: ...

    def acquire_materials(
        self,
        attempt_id: str,
        evidence: CommittedLaunchEvidence,
    ) -> MaterialLease: ...


@dataclass(slots=True)
class _CompilationResources:
    owner_token: object
    image_lease: ImageLease
    state_lease: StateLease
    secret_lease: SecretLease
    material_lease: MaterialLease
    closed: bool = False

    def close(self) -> None:
        if self.closed:
            return
        first_error: BaseException | None = None
        for lease in (
            self.material_lease,
            self.secret_lease,
            self.state_lease,
            self.image_lease,
        ):
            try:
                lease.close()
            except BaseException as error:
                if first_error is None:
                    first_error = error
        self.closed = True
        if first_error is not None:
            if isinstance(first_error, Exception):
                raise PersistedPreparationError(
                    "persisted_resource_close_failed"
                ) from None
            raise first_error


class _CompilationResourceContext(AbstractContextManager[_CompilationResources]):
    """Own every launch lease inside PreparationPort's one context-managed span."""

    def __init__(
        self,
        preparation: PersistedAuthorityPreparation,
        revalidated: _PersistedRevalidatedAttempt,
    ) -> None:
        self._preparation = preparation
        self._revalidated = revalidated
        self._resources: _CompilationResources | None = None

    def __enter__(self) -> _CompilationResources:
        if self._resources is not None:
            raise PersistedPreparationError("persisted_resource_context_invalid")
        acquired: list[object] = []
        try:
            image = self._preparation._image_port.acquire_image(self._revalidated.spec)
            acquired.append(image)
            state = self._preparation._state_port.acquire_state(
                self._revalidated.persisted.state,
                self._revalidated.attempt.attempt_id,
                self._revalidated.evidence.policies.runtime_user.uid,
            )
            acquired.append(state)
            secrets = self._preparation._secret_port.acquire_secrets(
                _secret_requirements(self._revalidated.persisted.secrets),
                self._revalidated.attempt.attempt_id,
                self._revalidated.evidence.policies.runtime_user.uid,
            )
            acquired.append(secrets)
            materials = self._preparation._material_port.acquire_materials(
                self._revalidated.attempt.attempt_id,
                self._revalidated.evidence,
            )
            acquired.append(materials)
            resources = _CompilationResources(
                owner_token=self._revalidated.session.token,
                image_lease=image,
                state_lease=state,
                secret_lease=secrets,
                material_lease=materials,
            )
            self._preparation._require_resources(self._revalidated, resources)
            self._revalidated.session.bind(resources)
            self._resources = resources
            return resources
        except BaseException as error:
            cleanup_failed = False
            for lease in reversed(acquired):
                try:
                    close = getattr(lease, "close")
                    close()
                except BaseException:
                    cleanup_failed = True
            if cleanup_failed:
                raise PersistedPreparationError(
                    "persisted_resource_close_failed"
                ) from None
            if isinstance(error, PersistedPreparationError):
                raise
            if isinstance(error, Exception):
                raise PersistedPreparationError(
                    "persisted_resource_acquisition_failed"
                ) from None
            raise

    def __exit__(
        self,
        exception_type: object,
        exception: object,
        traceback: object,
    ) -> None:
        resources = self._resources
        if resources is None:
            return
        cleanup_failed = False
        try:
            self._preparation._release_active_launch(self._revalidated, resources)
        except BaseException:
            cleanup_failed = True
        try:
            resources.close()
        except BaseException:
            cleanup_failed = True
        finally:
            self._revalidated.session.release(resources)
        if cleanup_failed:
            raise PersistedPreparationError("persisted_resource_close_failed") from None


class PersistedAuthorityPreparation:
    """Typed persisted-authority adapter for the Supervisor PreparationPort."""

    def __init__(
        self,
        repository: RepositoryPort,
        resolved_material_factory: ResolvedMaterialFactory,
        image_port: ImagePort,
        state_port: StatePort,
        secret_port: SecretPort,
        material_port: MaterialPort,
        active_launch_lease_factory: ActiveLaunchLeaseFactory = (
            ActiveLaunchAuthorityLease
        ),
    ) -> None:
        for dependency in (
            repository,
            resolved_material_factory,
            image_port,
            state_port,
            secret_port,
            material_port,
            active_launch_lease_factory,
        ):
            if dependency is None or isinstance(dependency, Mapping):
                raise PersistedPreparationError(
                    "persisted_preparation_dependency_invalid"
                )
        if not callable(resolved_material_factory):
            raise PersistedPreparationError(
                "persisted_preparation_dependency_invalid"
            )
        if not callable(active_launch_lease_factory):
            raise PersistedPreparationError(
                "persisted_preparation_dependency_invalid"
            )
        self._repository = repository
        self._resolved_material_factory = resolved_material_factory
        self._image_port = image_port
        self._state_port = state_port
        self._secret_port = secret_port
        self._material_port = material_port
        self._active_launch_lease_factory = active_launch_lease_factory
        self._active_launches: dict[
            tuple[DriverIdentity, str], _ActiveLaunchRegistration
        ] = {}
        self._health_profiles: dict[str, tuple[DriverIdentity, HealthProfile]] = {}
        self.driver_authority_resolver = PersistedDriverAuthorityResolver(self)

    def recover_identity(self, latest: object) -> DriverIdentity:
        try:
            if isinstance(latest, Mapping):
                raise ValueError
            attempt_id = _identifier(_attribute(latest, "attempt_id"))
            digest = _digest(_attribute(latest, "runtime_spec_payload_digest"))
            material = _attribute(latest, "resolved_material")
            if isinstance(material, Mapping):
                raise ValueError
            project = _identifier(_attribute(material, "project_identity"))
            container = _identifier(_attribute(material, "container_identity"))
            prefix = "runtime-"
            if not project.startswith(prefix):
                raise ValueError
            instance_id = _identifier(project[len(prefix) :])
            expected_project, expected_container = _runtime_names(instance_id)
            if project != expected_project or container != expected_container:
                raise ValueError
            root_commit = _git_object_id(_attribute(material, "root_commit"))
            evidence = self._material_port.load_evidence(root_commit)
            if (
                type(evidence) is not CommittedLaunchEvidence
                or evidence.template.source_commit != root_commit
                or evidence.policies.source_commit != root_commit
                or evidence.artifacts.root_commit != root_commit
            ):
                raise ValueError
            validate_resolved_launch_policy_bundle(
                evidence.policies,
                evidence.template,
            )
            return DriverIdentity(
                project_name=project,
                container_name=container,
                instance_id=instance_id,
                attempt_id=attempt_id,
                runtime_spec_digest=digest,
                state_allocation_id=_identifier(
                    _attribute(material, "state_allocation_id")
                ),
                image_id=_image_id(_attribute(material, "image_id")),
                network_names=_network_names(instance_id, evidence.policies),
            )
        except Exception:
            raise PersistedPreparationError("persisted_identity_invalid") from None

    def revalidate(
        self,
        job: ReconciliationJob,
        attempt_id: str,
        latest: object | None,
    ) -> RevalidatedAttempt:
        if type(job) is not ReconciliationJob or not _is_identifier(attempt_id):
            raise PersistedPreparationError("persisted_preparation_input_invalid")
        try:
            active_authority = (
                latest is not None
                and not isinstance(latest, Mapping)
                and _identifier(_attribute(latest, "attempt_id")) == attempt_id
            )
        except (AttributeError, TypeError, ValueError):
            raise PersistedPreparationError(
                "persisted_preparation_input_invalid"
            ) from None
        try:
            if active_authority:
                raw_authority = (
                    self._repository.revalidate_active_launch_authority_material(
                        job.job_id,
                        attempt_id,
                        job.lease_owner,
                        job.lease_generation,
                    )
                )
            else:
                raw_authority = self._repository.resolve_launch_authority_material(
                    job.job_id,
                    attempt_id,
                    job.lease_owner,
                    job.lease_generation,
                )
        except Exception:
            raise PersistedPreparationRepositoryError() from None
        persisted = _convert_persisted_authority(
            raw_authority,
            allow_revoked_template=active_authority,
        )
        if persisted.instance.instance_id != job.instance_id:
            raise PersistedPreparationError("persisted_authority_invalid")
        spec = _runtime_spec(persisted)
        try:
            evidence = self._material_port.load_evidence(spec.root_commit)
        except Exception:
            raise PersistedPreparationError("persisted_evidence_unavailable") from None
        _correlate_evidence(persisted, spec, evidence)
        session = _PreparationSession(object())
        provisional = _PersistedRevalidatedAttempt(
            identity=_provisional_identity(
                spec,
                persisted.instance.instance_id,
                attempt_id,
                evidence.policies,
            ),
            resolved_material=object(),
            provenance=LaunchProvenance(
                launch_authority_digest="0" * 64,
                root_commit=spec.root_commit,
                backend_commit=spec.backend_commit,
                frontend_commit=spec.frontend_commit,
                strategies_commit=spec.strategies_commit,
            ),
            job=job,
            persisted=persisted,
            spec=spec,
            evidence=evidence,
            attempt=_provisional_attempt(
                spec,
                persisted,
                attempt_id,
                "sha256:" + "0" * 64,
            ),
            session=session,
            active_authority=active_authority,
        )
        with _CompilationResourceContext(self, provisional) as resources:
            image = self._require_resources(provisional, resources)
            attempt = _provisional_attempt(
                spec,
                persisted,
                attempt_id,
                image.image_id,
            )
            identity = _identity(attempt, evidence.policies)
            authority = self._compilation_authority(
                provisional,
                resources,
                attempt=attempt,
                identity=identity,
            )
            snapshot = compile_launch_snapshot(authority)
            validate_launch_snapshot(snapshot, authority)
        try:
            resolved_material = self._resolved_material_factory(attempt)
        except Exception:
            raise PersistedPreparationError(
                "persisted_resolved_material_invalid"
            ) from None
        if resolved_material is None or isinstance(resolved_material, Mapping):
            raise PersistedPreparationError("persisted_resolved_material_invalid")
        if (
            _attempt_from_resolved_material(
                resolved_material,
                attempt_id=attempt.attempt_id,
                instance_id=attempt.instance_id,
                runtime_spec_payload_digest=attempt.runtime_spec_payload_digest,
            )
            != attempt
        ):
            raise PersistedPreparationError("persisted_resolved_material_invalid")
        result = _PersistedRevalidatedAttempt(
            identity=identity,
            resolved_material=resolved_material,
            provenance=LaunchProvenance(
                launch_authority_digest=snapshot.launch_authority_digest,
                root_commit=spec.root_commit,
                backend_commit=spec.backend_commit,
                frontend_commit=spec.frontend_commit,
                strategies_commit=spec.strategies_commit,
            ),
            job=job,
            persisted=persisted,
            spec=spec,
            evidence=evidence,
            attempt=attempt,
            session=session,
            active_authority=active_authority,
        )
        self._remember_health_profile(result)
        return result

    def resolve_state(self, revalidated: RevalidatedAttempt) -> object:
        value = self._prepared(revalidated)
        return _StateResolutionToken(value.session)

    def resolve_secrets(
        self, revalidated: RevalidatedAttempt
    ) -> AbstractContextManager[object]:
        return _CompilationResourceContext(self, self._prepared(revalidated))

    def compile_snapshot(
        self,
        revalidated: RevalidatedAttempt,
        state: object,
        secrets: object,
    ) -> LaunchSnapshot:
        value = self._prepared(revalidated)
        if (
            type(state) is not _StateResolutionToken
            or state.session is not value.session
            or type(secrets) is not _CompilationResources
            or secrets.owner_token is not value.session.token
            or value.session.active_resources is not secrets
            or secrets.closed
        ):
            raise PersistedPreparationError("persisted_compilation_context_invalid")
        image = self._require_resources(value, secrets)
        try:
            current_evidence = self._material_port.revalidate_evidence(value.evidence)
        except Exception:
            raise PersistedPreparationError("persisted_evidence_mismatch") from None
        if current_evidence != value.evidence:
            raise PersistedPreparationError("persisted_evidence_mismatch")
        authority = self._compilation_authority(
            value,
            secrets,
            attempt=value.attempt,
            identity=value.identity,
        )
        if image.image_id != value.attempt.image_id:
            raise PersistedPreparationError("persisted_image_changed")
        snapshot = compile_launch_snapshot(authority)
        validate_launch_snapshot(snapshot, authority)
        final = self._repository_authority(value, active=value.active_authority)
        if final != value.persisted and (
            not value.active_authority
            or not _same_frozen_active_authority(final, value.persisted)
        ):
            raise PersistedPreparationError("persisted_authority_changed")
        if snapshot.launch_authority_digest != value.provenance.launch_authority_digest:
            raise PersistedPreparationError("persisted_compilation_changed")
        self._register_active_launch(value, secrets, authority, snapshot)
        return snapshot

    def revalidate_for_runtime_action(
        self,
        revalidated: RevalidatedAttempt,
        snapshot: LaunchSnapshot,
    ) -> None:
        value = self._prepared(revalidated)
        resources = value.session.active_resources
        if (
            type(snapshot) is not LaunchSnapshot
            or type(resources) is not _CompilationResources
            or resources.closed
            or resources.owner_token is not value.session.token
            or value.session.compiled_snapshot is not snapshot
        ):
            raise PersistedPreparationError("persisted_runtime_action_context_invalid")
        self._revalidate_active_registration(value, resources, snapshot)

    def compile_access_network_plan(
        self,
        revalidated: RevalidatedAttempt,
        container_id: str,
    ) -> RuntimeAccessNetworkPlan:
        value = self._prepared(revalidated)
        state = self.resolve_state(value)
        with self.resolve_secrets(value) as resources:
            snapshot = self.compile_snapshot(value, state, resources)
        return compile_runtime_access_network_plan(snapshot, container_id)

    def resolve_health_profile(
        self,
        revalidated: RevalidatedAttempt,
    ) -> HealthProfile:
        return self._prepared(revalidated).evidence.policies.health_profile

    def compile_offline_identity(
        self,
        revalidated: RevalidatedAttempt,
        observed: DriverInspection,
        *,
        instance_revision: int,
        lease_generation: int,
    ) -> OfflineRuntimeIdentity:
        value = self._prepared(revalidated)
        if type(observed) is not DriverInspection or observed.container_id is None:
            raise PersistedPreparationError("persisted_offline_identity_invalid")
        try:
            return OfflineRuntimeIdentity.from_driver_identity(
                value.identity,
                container_id=observed.container_id,
                instance_revision=instance_revision,
                lease_generation=lease_generation,
                launch_authority_digest=value.provenance.launch_authority_digest,
                root_commit=value.provenance.root_commit,
                backend_commit=value.provenance.backend_commit,
                frontend_commit=value.provenance.frontend_commit,
                strategies_commit=value.provenance.strategies_commit,
            )
        except Exception:
            raise PersistedPreparationError(
                "persisted_offline_identity_invalid"
            ) from None

    def _prepared(self, value: RevalidatedAttempt) -> _PersistedRevalidatedAttempt:
        if type(value) is not _PersistedRevalidatedAttempt:
            raise PersistedPreparationError("persisted_revalidated_attempt_invalid")
        return value

    def _remember_health_profile(
        self,
        value: _PersistedRevalidatedAttempt,
    ) -> None:
        profile = value.evidence.policies.health_profile
        self._health_profiles[value.identity.instance_id] = (value.identity, profile)

    def _resolve_driver_health_profile(
        self,
        identity: DriverIdentity,
        profile_id: str,
    ) -> HealthProfile:
        if type(identity) is not DriverIdentity or not _is_identifier(profile_id):
            raise PersistedPreparationError("persisted_health_profile_invalid")
        registration = self._health_profiles.get(identity.instance_id)
        if registration is None:
            raise PersistedPreparationError("persisted_health_profile_invalid")
        registered_identity, profile = registration
        if registered_identity != identity or profile.profile_id != profile_id:
            raise PersistedPreparationError("persisted_health_profile_invalid")
        return profile

    def _register_active_launch(
        self,
        value: _PersistedRevalidatedAttempt,
        resources: _CompilationResources,
        authority: LaunchCompilationAuthority,
        snapshot: LaunchSnapshot,
    ) -> None:
        session = value.session
        if (
            session.compiled_snapshot is not None
            or session.compilation_authority is not None
            or session.active_launch_lease is not None
        ):
            raise PersistedPreparationError("persisted_active_launch_invalid")
        try:
            lease = self._active_launch_lease_factory(
                authority,
                resources.material_lease,
                resources.state_lease,
                resources.secret_lease,
            )
        except Exception:
            raise PersistedPreparationError("persisted_active_launch_invalid") from None
        if (
            type(lease) is not ActiveLaunchAuthorityLease
            or lease.authority is not authority
            or lease.material_lease is not resources.material_lease
            or lease.state_lease is not resources.state_lease
            or lease.secret_lease is not resources.secret_lease
        ):
            raise PersistedPreparationError("persisted_active_launch_invalid")
        key = (snapshot.identity, snapshot.launch_authority_digest)
        if key in self._active_launches:
            raise PersistedPreparationError("persisted_active_launch_invalid")
        registration = _ActiveLaunchRegistration(
            revalidated=value,
            resources=resources,
            snapshot=snapshot,
            authority=authority,
            lease=lease,
        )
        self._active_launches[key] = registration
        session.compiled_snapshot = snapshot
        session.compilation_authority = authority
        session.active_launch_lease = lease

    def _resolve_active_launch(
        self,
        identity: DriverIdentity,
        launch_authority_digest: str,
    ) -> ActiveLaunchAuthorityLease:
        if (
            type(identity) is not DriverIdentity
            or type(launch_authority_digest) is not str
            or _DIGEST.fullmatch(launch_authority_digest) is None
        ):
            raise PersistedPreparationError("persisted_active_launch_invalid")
        registration = self._active_launches.get(
            (identity, launch_authority_digest)
        )
        if registration is None:
            raise PersistedPreparationError("persisted_active_launch_invalid")
        resources = registration.resources
        lease = registration.lease
        if (
            resources.closed
            or registration.snapshot.identity != identity
            or registration.snapshot.launch_authority_digest
            != launch_authority_digest
            or registration.authority.identity != identity
            or lease.authority is not registration.authority
            or lease.material_lease is not resources.material_lease
            or lease.state_lease is not resources.state_lease
            or lease.secret_lease is not resources.secret_lease
        ):
            raise PersistedPreparationError("persisted_active_launch_invalid")
        self._revalidate_active_registration(
            registration.revalidated,
            resources,
            registration.snapshot,
        )
        return lease

    def _release_active_launch(
        self,
        value: _PersistedRevalidatedAttempt,
        resources: _CompilationResources,
    ) -> None:
        session = value.session
        snapshot = session.compiled_snapshot
        authority = session.compilation_authority
        lease = session.active_launch_lease
        if snapshot is None and authority is None and lease is None:
            return
        if snapshot is None or authority is None or lease is None:
            raise PersistedPreparationError("persisted_active_launch_invalid")
        key = (snapshot.identity, snapshot.launch_authority_digest)
        registration = self._active_launches.pop(key, None)
        if (
            registration is None
            or registration.revalidated is not value
            or registration.resources is not resources
            or registration.snapshot is not snapshot
            or registration.authority is not authority
            or registration.lease is not lease
        ):
            raise PersistedPreparationError("persisted_active_launch_invalid")

    def _revalidate_active_registration(
        self,
        value: _PersistedRevalidatedAttempt,
        resources: _CompilationResources,
        snapshot: LaunchSnapshot,
    ) -> None:
        final = self._repository_authority(value, active=True)
        expected_after_begin = replace(
            value.persisted,
            instance=replace(
                value.persisted.instance,
                lifecycle_status="starting",
            ),
        )
        if not _same_frozen_active_authority(final, expected_after_begin):
            raise PersistedPreparationError("persisted_authority_changed")
        try:
            current_evidence = self._material_port.revalidate_evidence(value.evidence)
        except Exception:
            raise PersistedPreparationError("persisted_evidence_mismatch") from None
        if current_evidence != value.evidence:
            raise PersistedPreparationError("persisted_evidence_mismatch")
        image = self._require_resources(value, resources)
        if image.image_id != value.attempt.image_id:
            raise PersistedPreparationError("persisted_image_changed")
        authority = self._compilation_authority(
            value,
            resources,
            attempt=value.attempt,
            identity=value.identity,
        )
        current = compile_launch_snapshot(authority)
        validate_launch_snapshot(current, authority)
        if current != snapshot:
            raise PersistedPreparationError("persisted_compilation_changed")

    def _repository_authority(
        self,
        value: _PersistedRevalidatedAttempt,
        *,
        active: bool,
    ) -> _PersistedAuthority:
        try:
            if active:
                authority = (
                    self._repository.revalidate_active_launch_authority_material(
                        value.job.job_id,
                        value.attempt.attempt_id,
                        value.job.lease_owner,
                        value.job.lease_generation,
                    )
                )
            else:
                authority = self._repository.resolve_launch_authority_material(
                    value.job.job_id,
                    value.attempt.attempt_id,
                    value.job.lease_owner,
                    value.job.lease_generation,
                )
        except Exception:
            raise PersistedPreparationRepositoryError() from None
        return _convert_persisted_authority(
            authority,
            allow_revoked_template=active,
        )

    def _require_resources(
        self,
        revalidated: _PersistedRevalidatedAttempt,
        resources: _CompilationResources,
    ) -> ResolvedImageIdentity:
        if resources.closed or resources.owner_token is not revalidated.session.token:
            raise PersistedPreparationError("persisted_compilation_context_invalid")
        try:
            issued_image = resources.image_lease.identity
            issued_state = resources.state_lease.mount
            issued_secrets = resources.secret_lease.mounts
            issued_materials = resources.material_lease.materials
            image = resources.image_lease.revalidate_identity()
            state_source = resources.state_lease.revalidate_source()
            secrets = resources.secret_lease.revalidate_sources()
            resources.material_lease.revalidate_sources()
            current_state = resources.state_lease.mount
            current_secrets = resources.secret_lease.mounts
            current_materials = resources.material_lease.materials
            if (
                type(image) is not ResolvedImageIdentity
                or image is not issued_image
                or type(current_state) is not VerifiedStateMount
                or current_state is not issued_state
                or state_source != current_state.source
                or type(secrets) is not tuple
                or secrets is not issued_secrets
                or current_secrets is not issued_secrets
                or type(current_materials) is not tuple
                or current_materials is not issued_materials
            ):
                raise ValueError
            _correlate_image(image, revalidated.spec)
            return image
        except PersistedPreparationError:
            raise
        except Exception:
            raise PersistedPreparationError("persisted_resource_invalid") from None

    def _compilation_authority(
        self,
        revalidated: _PersistedRevalidatedAttempt,
        resources: _CompilationResources,
        *,
        attempt: ResolvedAttemptAuthority,
        identity: DriverIdentity,
    ) -> LaunchCompilationAuthority:
        try:
            return LaunchCompilationAuthority(
                spec=revalidated.spec,
                attempt=attempt,
                template=revalidated.evidence.template,
                policies=revalidated.evidence.policies,
                state=resources.state_lease.mount,
                secrets=resources.secret_lease.mounts,
                materials=resources.material_lease.materials,
                identity=identity,
            )
        except (DriverValidationError, ValueError):
            raise PersistedPreparationError("persisted_compilation_invalid") from None


def _attribute(value: object, name: str) -> object:
    if value is None or isinstance(value, Mapping):
        raise AttributeError(name)
    return getattr(value, name)


def _attempt_from_resolved_material(
    value: object,
    *,
    attempt_id: str,
    instance_id: str,
    runtime_spec_payload_digest: str,
) -> ResolvedAttemptAuthority:
    try:
        if isinstance(value, Mapping):
            raise ValueError
        secret_values = _attribute(value, "resolved_secret_versions")
        if type(secret_values) is not tuple or any(
            isinstance(secret, Mapping) for secret in secret_values
        ):
            raise ValueError
        return ResolvedAttemptAuthority(
            attempt_id=attempt_id,
            instance_id=instance_id,
            runtime_spec_revision_id=_identifier(
                _attribute(value, "runtime_spec_revision_id")
            ),
            runtime_spec_payload_digest=_digest(runtime_spec_payload_digest),
            adapter_template_revision_id=_identifier(
                _attribute(value, "adapter_template_revision_id")
            ),
            state_allocation_id=_identifier(_attribute(value, "state_allocation_id")),
            state_allocation_generation=_positive_integer(
                _attribute(value, "state_allocation_generation")
            ),
            resolved_secret_versions=tuple(
                ResolvedSecretVersionAuthority(
                    _identifier(_attribute(secret, "secret_reference_id")),
                    _identifier(_attribute(secret, "version_id")),
                )
                for secret in secret_values
            ),
            image_id=_image_id(_attribute(value, "image_id")),
            root_commit=_git_object_id(_attribute(value, "root_commit")),
            backend_commit=_git_object_id(_attribute(value, "backend_commit")),
            frontend_commit=_git_object_id(_attribute(value, "frontend_commit")),
            strategies_commit=_git_object_id(_attribute(value, "strategies_commit")),
            project_identity=_identifier(_attribute(value, "project_identity")),
            container_identity=_identifier(_attribute(value, "container_identity")),
        )
    except (AttributeError, DriverValidationError, TypeError, ValueError):
        raise PersistedPreparationError("persisted_resolved_material_invalid") from None


def _enum_text(value: object) -> str:
    if type(value) is str:
        return value
    enum_value = getattr(value, "value", None)
    if type(enum_value) is str:
        return enum_value
    raise ValueError


def _positive_integer(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError
    return value


def _identifier(value: object) -> str:
    text = _enum_text(value)
    if _IDENTIFIER.fullmatch(text) is None:
        raise ValueError
    return text


def _is_identifier(value: object) -> bool:
    try:
        _identifier(value)
        return True
    except ValueError:
        return False


def _digest(value: object) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ValueError
    return value


def _git_object_id(value: object) -> str:
    if type(value) is not str or _GIT_OBJECT_ID.fullmatch(value) is None:
        raise ValueError
    return value


def _image_id(value: object) -> str:
    if type(value) is not str or _IMAGE_ID.fullmatch(value) is None:
        raise ValueError
    return value


def _strict_string(value: object) -> str:
    if type(value) is not str or not value:
        raise ValueError
    return value


def _owner(value: object) -> _OwnerAuthority:
    return _OwnerAuthority(
        owner_kind=_identifier(_attribute(value, "owner_kind")),
        owner_id=_identifier(_attribute(value, "owner_id")),
        owner_revision=_identifier(_attribute(value, "owner_revision")),
    )


def _convert_persisted_authority(
    value: object,
    *,
    allow_revoked_template: bool = False,
) -> _PersistedAuthority:
    try:
        if isinstance(value, Mapping):
            raise ValueError
        instance_value = _attribute(value, "instance")
        runtime_spec_value = _attribute(value, "runtime_spec")
        template_value = _attribute(value, "adapter_template")
        state_value = _attribute(value, "state_allocation")
        secret_values = _attribute(value, "secret_references")
        if any(
            isinstance(item, Mapping)
            for item in (
                instance_value,
                runtime_spec_value,
                template_value,
                state_value,
            )
        ):
            raise ValueError
        if type(secret_values) is not tuple:
            raise ValueError
        instance = _InstanceAuthority(
            instance_id=_identifier(_attribute(instance_value, "instance_id")),
            instance_kind=_identifier(_attribute(instance_value, "instance_kind")),
            owner=_owner(_attribute(instance_value, "owner_ref")),
            management_mode=_identifier(_attribute(instance_value, "management_mode")),
            runtime_spec_revision_id=_identifier(
                _attribute(instance_value, "runtime_spec_revision_id")
            ),
            environment=_identifier(_attribute(instance_value, "environment")),
            state_allocation_id=_identifier(
                _attribute(instance_value, "state_allocation_id")
            ),
            desired_state=_identifier(_attribute(instance_value, "desired_state")),
            lifecycle_status=_identifier(
                _attribute(instance_value, "lifecycle_status")
            ),
            failure_latched=_attribute(instance_value, "failure_latched"),
            optimistic_version=_attribute(instance_value, "optimistic_version"),
        )
        if (
            instance.management_mode != "supervisor"
            or _attribute(instance_value, "retired_at") is not None
            or instance.failure_latched is not False
            or type(instance.optimistic_version) is not int
            or instance.optimistic_version < 0
        ):
            raise ValueError
        template = _TemplateAuthority(
            adapter_template_revision_id=_identifier(
                _attribute(template_value, "adapter_template_revision_id")
            ),
            canonical_payload=_strict_string(
                _attribute(template_value, "canonical_payload")
            ),
            payload_digest=_digest(_attribute(template_value, "payload_digest")),
            source_commit=_git_object_id(_attribute(template_value, "source_commit")),
            root_commit=_git_object_id(_attribute(template_value, "root_commit")),
            backend_commit=_git_object_id(_attribute(template_value, "backend_commit")),
            frontend_commit=_git_object_id(
                _attribute(template_value, "frontend_commit")
            ),
            strategies_commit=_git_object_id(
                _attribute(template_value, "strategies_commit")
            ),
            status=_identifier(_attribute(template_value, "status")),
        )
        allowed_template_statuses = {"active", "deprecated"}
        if allow_revoked_template:
            allowed_template_statuses.add("revoked")
        if template.status not in allowed_template_statuses:
            raise ValueError
        state = _StateAuthority(
            state_allocation_id=_identifier(
                _attribute(state_value, "state_allocation_id")
            ),
            instance_id=_identifier(_attribute(state_value, "instance_id")),
            layout_id=_identifier(_attribute(state_value, "layout_id")),
            provider_id=_identifier(_attribute(state_value, "provider_id")),
            generation=_attribute(state_value, "generation"),
        )
        if (
            _enum_text(_attribute(state_value, "status")) != "ready"
            or state.provider_id != "managed-local-v1"
            or type(state.generation) is not int
            or state.generation < 1
        ):
            raise ValueError
        secrets = tuple(
            _SecretAuthority(
                secret_reference_id=_identifier(
                    _attribute(secret, "secret_reference_id")
                ),
                provider_id=_identifier(_attribute(secret, "provider_id")),
                secret_class=_identifier(_attribute(secret, "secret_class")),
                logical_name=_identifier(_attribute(secret, "logical_name")),
                owner=_owner(_attribute(secret, "owner_ref")),
                active_version_id=_identifier(_attribute(secret, "active_version_id")),
            )
            for secret in secret_values
        )
        if (
            not secrets
            or any(isinstance(secret, Mapping) for secret in secret_values)
            or any(
                _enum_text(_attribute(raw, "status")) != "active"
                or secret.provider_id != "local-file-v1"
                for raw, secret in zip(secret_values, secrets, strict=True)
            )
            or tuple(item.secret_reference_id for item in secrets)
            != tuple(sorted({item.secret_reference_id for item in secrets}))
        ):
            raise ValueError
        persisted = _PersistedAuthority(
            instance=instance,
            runtime_spec_revision_id=_identifier(
                _attribute(runtime_spec_value, "runtime_spec_revision_id")
            ),
            canonical_runtime_spec=_strict_string(
                _attribute(runtime_spec_value, "canonical_payload")
            ),
            runtime_spec_digest=_digest(
                _attribute(runtime_spec_value, "payload_digest")
            ),
            template=template,
            state=state,
            secrets=secrets,
        )
        if (
            instance.runtime_spec_revision_id != persisted.runtime_spec_revision_id
            or instance.state_allocation_id != state.state_allocation_id
            or instance.instance_id != state.instance_id
            or any(secret.owner != instance.owner for secret in secrets)
        ):
            raise ValueError
        return persisted
    except (AttributeError, TypeError, ValueError):
        raise PersistedPreparationError("persisted_authority_invalid") from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError


def _json_identifier_tuple(
    value: object, *, allow_empty: bool = False
) -> tuple[str, ...]:
    if (
        type(value) is not list
        or (not allow_empty and not value)
        or any(not _is_identifier(item) for item in value)
        or len(value) != len(set(value))
    ):
        raise ValueError
    return tuple(value)


def _runtime_spec(persisted: _PersistedAuthority) -> RuntimeSpecLaunchAuthority:
    try:
        document = json.loads(
            persisted.canonical_runtime_spec,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        if type(document) is not dict or set(document) != _RUNTIME_SPEC_FIELDS:
            raise ValueError
        canonical = json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if canonical != persisted.canonical_runtime_spec:
            raise ValueError
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if (
            digest != persisted.runtime_spec_digest
            or persisted.runtime_spec_revision_id != f"runtime-spec-{digest}"
        ):
            raise ValueError
        owner = document["owner_ref"]
        market = document["market_scope"]
        if (
            type(owner) is not dict
            or set(owner) != {"owner_kind", "owner_id", "owner_revision"}
            or type(market) is not dict
            or set(market)
            != {"market_id", "product_ids", "venue_ids", "instrument_keys"}
        ):
            raise ValueError
        _identifier(market["market_id"])
        _json_identifier_tuple(market["product_ids"])
        _json_identifier_tuple(market["venue_ids"], allow_empty=True)
        instruments = market["instrument_keys"]
        if type(instruments) is not list or any(
            type(item) is not str or not 0 < len(item) <= 256 for item in instruments
        ):
            raise ValueError
        if len(instruments) != len(set(instruments)):
            raise ValueError
        spec = RuntimeSpecLaunchAuthority(
            runtime_spec_revision_id=persisted.runtime_spec_revision_id,
            payload_digest=digest,
            owner_kind=_identifier(owner["owner_kind"]),
            instance_kind=_identifier(document["instance_kind"]),
            environment=_identifier(document["environment"]),
            adapter_template_revision_id=_identifier(
                document["adapter_template_revision_id"]
            ),
            template_digest=_digest(document["template_digest"]),
            image_policy_id=_identifier(document["image_policy_id"]),
            command_policy_id=_identifier(document["command_policy_id"]),
            mount_policy_ids=_json_identifier_tuple(document["mount_policy_ids"]),
            network_policy_id=_identifier(document["network_policy_id"]),
            health_profile_id=_identifier(document["health_profile_id"]),
            resource_profile_id=_identifier(document["resource_profile_id"]),
            state_layout_id=_identifier(document["state_layout_id"]),
            state_allocation_id=_identifier(document["state_allocation_id"]),
            secret_reference_ids=_json_identifier_tuple(
                document["secret_reference_ids"]
            ),
            config_blob_commit=_git_object_id(document["config_blob_commit"]),
            strategy_commit=_git_object_id(document["strategy_commit"]),
            strategy_class_name=_strict_string(document["strategy_class_name"]),
            safety_policy_commit=_git_object_id(document["safety_policy_commit"]),
            root_commit=_git_object_id(document["root_commit"]),
            backend_commit=_git_object_id(document["backend_commit"]),
            frontend_commit=_git_object_id(document["frontend_commit"]),
            strategies_commit=_git_object_id(document["strategies_commit"]),
            config_blob_digest=_digest(document["config_blob_digest"]),
            strategy_digest=_digest(document["strategy_digest"]),
            safety_policy_digest=_digest(document["safety_policy_digest"]),
        )
        _identifier(document["catalog_revision_id"])
        if (
            spec.owner_kind != persisted.instance.owner.owner_kind
            or _identifier(owner["owner_id"]) != persisted.instance.owner.owner_id
            or _identifier(owner["owner_revision"])
            != persisted.instance.owner.owner_revision
            or spec.instance_kind != persisted.instance.instance_kind
            or spec.environment != persisted.instance.environment
            or spec.state_allocation_id != persisted.state.state_allocation_id
            or spec.state_layout_id != persisted.state.layout_id
            or spec.secret_reference_ids
            != tuple(secret.secret_reference_id for secret in persisted.secrets)
        ):
            raise ValueError
        return spec
    except (DriverValidationError, TypeError, ValueError, json.JSONDecodeError):
        raise PersistedPreparationError("persisted_runtime_spec_invalid") from None


def _correlate_evidence(
    persisted: _PersistedAuthority,
    spec: RuntimeSpecLaunchAuthority,
    evidence: CommittedLaunchEvidence,
) -> None:
    try:
        evidence.__post_init__()
        template = evidence.template
        policies = evidence.policies
        artifacts = evidence.artifacts
        decoded_template = json.loads(
            template.canonical_json,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        canonical_template = (
            json.dumps(
                decoded_template,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )
        if (
            canonical_template != template.canonical_json
            or hashlib.sha256(canonical_template.encode("utf-8")).hexdigest()
            != template.digest
        ):
            raise ValueError
        validate_resolved_launch_policy_bundle(policies, template)
        expected_artifacts = CommittedPaperProbeArtifacts(
            root_commit=spec.root_commit,
            backend_commit=spec.backend_commit,
            frontend_commit=spec.frontend_commit,
            strategies_commit=spec.strategies_commit,
            config_sha256=spec.config_blob_digest,
            strategy_sha256=spec.strategy_digest,
            safety_sha256=spec.safety_policy_digest,
            strategy_class_name=spec.strategy_class_name or "",
        )
        if (
            persisted.template.adapter_template_revision_id
            != spec.adapter_template_revision_id
            or persisted.template.adapter_template_revision_id
            != f"template-{template.digest}"
            or persisted.template.canonical_payload != template.canonical_json
            or persisted.template.payload_digest != template.digest
            or persisted.template.source_commit != template.source_commit
            or persisted.template.root_commit != spec.root_commit
            or persisted.template.backend_commit != spec.backend_commit
            or persisted.template.frontend_commit != spec.frontend_commit
            or persisted.template.strategies_commit != spec.strategies_commit
            or template.source_commit != spec.root_commit
            or policies.source_commit != spec.root_commit
            or policies.template_digest != template.digest
            or artifacts != expected_artifacts
        ):
            raise ValueError
    except (PersistedPreparationError, TypeError, ValueError):
        raise PersistedPreparationError("persisted_evidence_mismatch") from None


def _correlate_image(
    image: ResolvedImageIdentity,
    spec: RuntimeSpecLaunchAuthority,
) -> None:
    image.__post_init__()
    if (
        image.image_policy_id != spec.image_policy_id
        or image.root_commit != spec.root_commit
        or image.backend_commit != spec.backend_commit
        or image.frontend_commit != spec.frontend_commit
    ):
        raise PersistedPreparationError("persisted_image_invalid")


def _runtime_names(instance_id: str) -> tuple[str, str]:
    project = f"runtime-{instance_id}"
    container = f"{project}-worker"
    if not _is_identifier(project) or not _is_identifier(container):
        raise PersistedPreparationError("persisted_identity_invalid")
    return project, container


def _network_names(
    instance_id: str,
    policies: ResolvedLaunchPolicyBundle,
) -> tuple[str, ...]:
    names: list[str] = []
    for rule in policies.network_rules:
        if (
            rule.identity_source is not NetworkIdentitySource.INSTANCE_ID
            or rule.derivation is not NetworkNameDerivation.SHA256_PREFIX_V1
        ):
            raise PersistedPreparationError("persisted_network_policy_invalid")
        digest = hashlib.sha256(instance_id.encode("utf-8")).hexdigest()
        names.append(f"{rule.prefix}{digest[: rule.digest_characters]}{rule.suffix}")
    result = tuple(sorted(names))
    if not result or result != tuple(sorted(set(result))):
        raise PersistedPreparationError("persisted_network_policy_invalid")
    return result


def _secret_requirements(
    secrets: tuple[_SecretAuthority, ...],
) -> tuple[SecretMaterialRequirement, ...]:
    try:
        return tuple(
            SecretMaterialRequirement(
                secret.secret_reference_id,
                secret.active_version_id,
                secret.secret_class,
            )
            for secret in secrets
        )
    except Exception:
        raise PersistedPreparationError("persisted_secret_authority_invalid") from None


def _provisional_attempt(
    spec: RuntimeSpecLaunchAuthority,
    persisted: _PersistedAuthority,
    attempt_id: str,
    image_id: str,
) -> ResolvedAttemptAuthority:
    project, container = _runtime_names(persisted.instance.instance_id)
    return ResolvedAttemptAuthority(
        attempt_id=attempt_id,
        instance_id=persisted.instance.instance_id,
        runtime_spec_revision_id=spec.runtime_spec_revision_id,
        runtime_spec_payload_digest=spec.payload_digest,
        adapter_template_revision_id=spec.adapter_template_revision_id,
        state_allocation_id=spec.state_allocation_id,
        state_allocation_generation=persisted.state.generation,
        resolved_secret_versions=tuple(
            ResolvedSecretVersionAuthority(
                secret.secret_reference_id,
                secret.active_version_id,
            )
            for secret in persisted.secrets
        ),
        image_id=image_id,
        root_commit=spec.root_commit,
        backend_commit=spec.backend_commit,
        frontend_commit=spec.frontend_commit,
        strategies_commit=spec.strategies_commit,
        project_identity=project,
        container_identity=container,
    )


def _identity(
    attempt: ResolvedAttemptAuthority,
    policies: ResolvedLaunchPolicyBundle,
) -> DriverIdentity:
    return DriverIdentity(
        project_name=attempt.project_identity,
        container_name=attempt.container_identity,
        instance_id=attempt.instance_id,
        attempt_id=attempt.attempt_id,
        runtime_spec_digest=attempt.runtime_spec_payload_digest,
        state_allocation_id=attempt.state_allocation_id,
        image_id=attempt.image_id,
        network_names=_network_names(attempt.instance_id, policies),
    )


def _provisional_identity(
    spec: RuntimeSpecLaunchAuthority,
    instance_id: str,
    attempt_id: str,
    policies: ResolvedLaunchPolicyBundle,
) -> DriverIdentity:
    project, container = _runtime_names(instance_id)
    return DriverIdentity(
        project_name=project,
        container_name=container,
        instance_id=instance_id,
        attempt_id=attempt_id,
        runtime_spec_digest=spec.payload_digest,
        state_allocation_id=spec.state_allocation_id,
        image_id="sha256:" + "0" * 64,
        network_names=_network_names(instance_id, policies),
    )
