from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
import hashlib
import json
import unittest

from tools.runtime_driver import (
    DriverHealth,
    DriverInspection,
    DriverPolicyError,
    DriverState,
    DriverTransportError,
)
from tools.runtime_persisted_preparation import (
    CommittedLaunchEvidence,
    PersistedAuthorityPreparation,
    PersistedPreparationError,
    ResolvedImageIdentity,
)
from tools.runtime_preparation_lease import ActiveLaunchAuthorityLease
from tools.runtime_supervisor.reconciler import (
    ReconciliationJob,
    RuntimeSupervisorReconciler,
)
from tools.runtime_supervisor.domain import (
    ReconciliationAction,
    ReconciliationDecision,
)
from tools.runtime_artifacts import CommittedPaperProbeArtifacts
from tests.test_runtime_snapshot import valid_authority


@dataclass(frozen=True, slots=True)
class Owner:
    owner_kind: str
    owner_id: str
    owner_revision: str


@dataclass(frozen=True, slots=True)
class Instance:
    instance_id: str
    instance_kind: str
    owner_ref: Owner
    management_mode: str
    runtime_spec_revision_id: str
    environment: str
    state_allocation_id: str
    desired_state: str
    lifecycle_status: str
    failure_latched: bool
    optimistic_version: int
    retired_at: object | None = None


@dataclass(frozen=True, slots=True)
class RuntimeSpec:
    runtime_spec_revision_id: str
    canonical_payload: str
    payload_digest: str


@dataclass(frozen=True, slots=True)
class AdapterTemplate:
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
class StateAllocation:
    state_allocation_id: str
    instance_id: str
    layout_id: str
    provider_id: str
    status: str
    generation: int


@dataclass(frozen=True, slots=True)
class SecretReference:
    secret_reference_id: str
    provider_id: str
    secret_class: str
    logical_name: str
    owner_ref: Owner
    status: str
    active_version_id: str


@dataclass(frozen=True, slots=True)
class Authority:
    instance: Instance
    runtime_spec: RuntimeSpec
    adapter_template: AdapterTemplate
    state_allocation: StateAllocation
    secret_references: tuple[SecretReference, ...]


@dataclass(frozen=True, slots=True)
class ResolvedVersion:
    secret_reference_id: str
    version_id: str


@dataclass(frozen=True, slots=True)
class ResolvedMaterial:
    runtime_spec_revision_id: str
    adapter_template_revision_id: str
    state_allocation_id: str
    state_allocation_generation: int
    resolved_secret_versions: tuple[ResolvedVersion, ...]
    image_id: str
    root_commit: str
    backend_commit: str
    frontend_commit: str
    strategies_commit: str
    project_identity: str
    container_identity: str


@dataclass(frozen=True, slots=True)
class Latest:
    attempt_id: str
    runtime_spec_payload_digest: str
    resolved_material: ResolvedMaterial


@dataclass(frozen=True, slots=True)
class CurrentLease:
    job_id: str
    instance_id: str
    expected_instance_version: int
    lease_owner: str
    lease_generation: int


@dataclass(frozen=True, slots=True)
class AttemptView:
    started_at: datetime


def _payload(base: object) -> tuple[str, str]:
    spec = base.spec
    document = {
        "adapter_template_revision_id": spec.adapter_template_revision_id,
        "backend_commit": spec.backend_commit,
        "catalog_revision_id": "catalog-revision-1",
        "command_policy_id": spec.command_policy_id,
        "config_blob_commit": spec.config_blob_commit,
        "config_blob_digest": spec.config_blob_digest,
        "environment": spec.environment,
        "frontend_commit": spec.frontend_commit,
        "health_profile_id": spec.health_profile_id,
        "image_policy_id": spec.image_policy_id,
        "instance_kind": spec.instance_kind,
        "market_scope": {
            "instrument_keys": [],
            "market_id": "digital_asset",
            "product_ids": ["spot"],
            "venue_ids": ["bitget"],
        },
        "mount_policy_ids": list(spec.mount_policy_ids),
        "network_policy_id": spec.network_policy_id,
        "owner_ref": {
            "owner_id": "owner-1",
            "owner_kind": spec.owner_kind,
            "owner_revision": "owner-revision-1",
        },
        "resource_profile_id": spec.resource_profile_id,
        "root_commit": spec.root_commit,
        "safety_policy_commit": spec.safety_policy_commit,
        "safety_policy_digest": spec.safety_policy_digest,
        "secret_reference_ids": list(spec.secret_reference_ids),
        "state_allocation_id": spec.state_allocation_id,
        "state_layout_id": spec.state_layout_id,
        "strategies_commit": spec.strategies_commit,
        "strategy_class_name": spec.strategy_class_name,
        "strategy_commit": spec.strategy_commit,
        "strategy_digest": spec.strategy_digest,
        "template_digest": spec.template_digest,
    }
    canonical = json.dumps(
        document, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return canonical, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _authority(base: object | None = None) -> tuple[Authority, object]:
    if base is None:
        base = valid_authority()
    canonical, digest = _payload(base)
    owner = Owner("paper_probe", "owner-1", "owner-revision-1")
    revision_id = f"runtime-spec-{digest}"
    authority = Authority(
        instance=Instance(
            instance_id=base.identity.instance_id,
            instance_kind=base.spec.instance_kind,
            owner_ref=owner,
            management_mode="supervisor",
            runtime_spec_revision_id=revision_id,
            environment="paper",
            state_allocation_id=base.spec.state_allocation_id,
            desired_state="running",
            lifecycle_status="starting",
            failure_latched=False,
            optimistic_version=8,
        ),
        runtime_spec=RuntimeSpec(revision_id, canonical, digest),
        adapter_template=AdapterTemplate(
            adapter_template_revision_id=base.spec.adapter_template_revision_id,
            canonical_payload=base.template.canonical_json,
            payload_digest=base.template.digest,
            source_commit=base.spec.root_commit,
            root_commit=base.spec.root_commit,
            backend_commit=base.spec.backend_commit,
            frontend_commit=base.spec.frontend_commit,
            strategies_commit=base.spec.strategies_commit,
            status="active",
        ),
        state_allocation=StateAllocation(
            base.spec.state_allocation_id,
            base.identity.instance_id,
            base.spec.state_layout_id,
            "managed-local-v1",
            "ready",
            1,
        ),
        secret_references=tuple(
            SecretReference(
                secret.reference_id,
                "local-file-v1",
                secret.secret_class,
                f"logical-{index}",
                owner,
                "active",
                secret.version_id,
            )
            for index, secret in enumerate(base.secrets)
        ),
    )
    return authority, base


class Lease:
    def __init__(
        self,
        events: list[str],
        kind: str,
        value: object,
        *,
        close_fails: bool = False,
        revalidate_fails: bool = False,
    ):
        self.events = events
        self.kind = kind
        self.value = value
        self.closed = False
        self.close_fails = close_fails
        self.revalidate_fails = revalidate_fails

    def _revalidate(self):
        self.events.append(f"revalidate-{self.kind}")
        if self.revalidate_fails:
            raise RuntimeError(f"{self.kind} revalidation failed")

    @property
    def identity(self):
        return self.value

    @property
    def mount(self):
        return self.value

    @property
    def mounts(self):
        return self.value

    @property
    def materials(self):
        return self.value

    def revalidate_identity(self):
        self._revalidate()
        return self.value

    def revalidate_source(self):
        self._revalidate()
        return self.value.source

    def revalidate_sources(self):
        self._revalidate()
        return self.value

    def close(self):
        self.events.append(f"close-{self.kind}")
        self.closed = True
        if self.close_fails:
            raise RuntimeError("close failed")


def active_launch_lease(
    authority: object,
    material_lease: object,
    state_lease: object,
    secret_lease: object,
) -> ActiveLaunchAuthorityLease:
    lease = object.__new__(ActiveLaunchAuthorityLease)
    object.__setattr__(lease, "authority", authority)
    object.__setattr__(lease, "material_lease", material_lease)
    object.__setattr__(lease, "state_lease", state_lease)
    object.__setattr__(lease, "secret_lease", secret_lease)
    return lease


class Repository:
    def __init__(self, authority: Authority, events: list[str]):
        self.authority = authority
        self.events = events
        self.resolve_count = 0
        self.final_authority: object = authority
        self.post_begin_authority: object | None = None
        self.resolve_error: str | None = None
        self.active_error: str | None = None
        self.build_error: str | None = None
        self.material_mutator = None

    def resolve_launch_authority_material(
        self, job_id, attempt_id, lease_owner, lease_generation
    ):
        self.resolve_count += 1
        self.events.append(f"repository-{self.resolve_count}")
        if self.resolve_error is not None:
            raise RuntimeError(self.resolve_error)
        if self.resolve_count == 1:
            return self.authority
        if self.resolve_count >= 3 and self.post_begin_authority is not None:
            return self.post_begin_authority
        return self.final_authority

    def revalidate_active_launch_authority_material(
        self, job_id, attempt_id, lease_owner, lease_generation
    ):
        self.resolve_count += 1
        self.events.append(f"repository-active-{self.resolve_count}")
        if self.active_error is not None:
            raise RuntimeError(self.active_error)
        if self.resolve_error is not None:
            raise RuntimeError(self.resolve_error)
        if self.post_begin_authority is not None:
            return self.post_begin_authority
        return self.final_authority

    def build_resolved_material(self, attempt):
        self.events.append("build-resolved-material")
        if self.build_error is not None:
            raise RuntimeError(self.build_error)
        resolved = ResolvedMaterial(
            attempt.runtime_spec_revision_id,
            attempt.adapter_template_revision_id,
            attempt.state_allocation_id,
            attempt.state_allocation_generation,
            tuple(
                ResolvedVersion(item.secret_reference_id, item.version_id)
                for item in attempt.resolved_secret_versions
            ),
            attempt.image_id,
            attempt.root_commit,
            attempt.backend_commit,
            attempt.frontend_commit,
            attempt.strategies_commit,
            attempt.project_identity,
            attempt.container_identity,
        )
        if self.material_mutator is not None:
            return self.material_mutator(resolved)
        return resolved


class Ports:
    def __init__(self, authority: Authority, base: object, events: list[str]):
        self.authority = authority
        self.base = base
        self.events = events
        self.fail_on: str | None = None
        self.close_fails: str | None = None
        self.revalidate_fails: str | None = None
        self.evidence_error: str | None = None
        self.evidence = CommittedLaunchEvidence(
            template=base.template,
            policies=base.policies,
            artifacts=CommittedPaperProbeArtifacts(
                root_commit=base.spec.root_commit,
                backend_commit=base.spec.backend_commit,
                frontend_commit=base.spec.frontend_commit,
                strategies_commit=base.spec.strategies_commit,
                config_sha256=base.spec.config_blob_digest,
                strategy_sha256=base.spec.strategy_digest,
                safety_sha256=base.spec.safety_policy_digest,
                strategy_class_name=base.spec.strategy_class_name,
            ),
        )

    def _lease(self, kind: str, value: object) -> Lease:
        self.events.append(f"acquire-{kind}")
        if self.fail_on == kind:
            raise RuntimeError(f"{kind} failed")
        return Lease(
            self.events,
            kind,
            value,
            close_fails=self.close_fails == kind,
            revalidate_fails=self.revalidate_fails == kind,
        )

    def acquire_image(self, spec):
        return self._lease(
            "image",
            ResolvedImageIdentity(
                image_id=self.base.identity.image_id,
                image_policy_id=spec.image_policy_id,
                root_commit=spec.root_commit,
                backend_commit=spec.backend_commit,
                frontend_commit=spec.frontend_commit,
            ),
        )

    def acquire_state(self, allocation, attempt_id, runtime_uid):
        return self._lease(
            "state",
            replace(
                self.base.state,
                attempt_id=attempt_id,
                state_allocation_id=allocation.state_allocation_id,
                instance_id=allocation.instance_id,
                layout_id=allocation.layout_id,
                generation=allocation.generation,
                runtime_uid=runtime_uid,
            ),
        )

    def acquire_secrets(self, requirements, attempt_id, runtime_uid):
        by_reference = {item.reference_id: item for item in self.base.secrets}
        mounts = tuple(
            replace(
                by_reference[item.reference_id],
                attempt_id=attempt_id,
                version_id=item.version_id,
                secret_class=item.secret_class,
            )
            for item in sorted(
                requirements,
                key=lambda value: (
                    value.secret_class,
                    value.reference_id,
                    value.version_id,
                ),
            )
        )
        return self._lease("secret", mounts)

    def load_evidence(self, root_commit):
        self.events.append("load-evidence")
        if self.evidence_error is not None:
            raise RuntimeError(self.evidence_error)
        return self.evidence

    def revalidate_evidence(self, evidence):
        self.events.append("revalidate-evidence")
        return self.evidence

    def acquire_materials(self, attempt_id, evidence):
        materials = tuple(
            replace(item, attempt_id=attempt_id) for item in self.base.materials
        )
        return self._lease("material", materials)


def _job(instance_id: str) -> ReconciliationJob:
    return ReconciliationJob(
        job_id="job-1",
        instance_id=instance_id,
        action=ReconciliationAction.START,
        lease_owner="supervisor-1",
        lease_generation=1,
        instance_revision=8,
    )


class PersistedAuthorityPreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.authority, self.base = _authority()
        self.events: list[str] = []
        self.repository = Repository(self.authority, self.events)
        self.ports = Ports(self.authority, self.base, self.events)
        self.preparation = PersistedAuthorityPreparation(
            self.repository,
            self.repository.build_resolved_material,
            self.ports,
            self.ports,
            self.ports,
            self.ports,
            active_launch_lease,
        )
        self.job = _job(self.base.identity.instance_id)
        self.attempt_id = "attempt-1"

    def _revalidated(self):
        return self.preparation.revalidate(self.job, self.attempt_id, None)

    def test_typed_authority_compiles_snapshot_with_derived_identities(self) -> None:
        revalidated = self._revalidated()

        state = self.preparation.resolve_state(revalidated)
        with self.preparation.resolve_secrets(revalidated) as resources:
            snapshot = self.preparation.compile_snapshot(revalidated, state, resources)
            self.assertEqual(snapshot.identity.project_name, "runtime-paper-probe-1")
            self.assertEqual(
                snapshot.identity.container_name, "runtime-paper-probe-1-worker"
            )
            self.assertEqual(
                snapshot.identity.network_names, self.base.identity.network_names
            )
            self.assertNotIn("close-image", self.events[-4:])

        self.assertEqual(
            self.events[-4:],
            ["close-material", "close-secret", "close-state", "close-image"],
        )

    def test_driver_resolver_exposes_only_the_exact_live_compilation_lease(
        self,
    ) -> None:
        revalidated = self._revalidated()
        state = self.preparation.resolve_state(revalidated)
        resolver = self.preparation.driver_authority_resolver

        with self.preparation.resolve_secrets(revalidated) as resources:
            snapshot = self.preparation.compile_snapshot(
                revalidated,
                state,
                resources,
            )
            lease = resolver.resolve_active_launch(
                snapshot.identity,
                snapshot.launch_authority_digest,
            )
            self.assertIs(lease.material_lease, resources.material_lease)
            self.assertIs(lease.state_lease, resources.state_lease)
            self.assertIs(lease.secret_lease, resources.secret_lease)
            self.assertEqual(lease.authority.identity, snapshot.identity)
            self.assertEqual(
                resolver.resolve_health_profile(
                    snapshot.identity,
                    self.base.policies.health_profile.profile_id,
                ),
                self.base.policies.health_profile,
            )

        with self.assertRaisesRegex(
            PersistedPreparationError,
            "^persisted_active_launch_invalid$",
        ):
            resolver.resolve_active_launch(
                snapshot.identity,
                snapshot.launch_authority_digest,
            )
        for kind in ("material", "secret", "state", "image"):
            self.assertEqual(self.events.count(f"close-{kind}"), 2)

    def test_active_attempt_uses_only_the_active_repository_authority_api(
        self,
    ) -> None:
        prepared = self._revalidated()
        latest = Latest(
            self.attempt_id,
            prepared.identity.runtime_spec_digest,
            prepared.resolved_material,
        )
        self.repository.post_begin_authority = replace(
            self.authority,
            adapter_template=replace(self.authority.adapter_template, status="revoked"),
        )
        before = len(self.events)

        active = self.preparation.revalidate(self.job, self.attempt_id, latest)

        self.assertEqual(active.identity, prepared.identity)
        self.assertTrue(active.active_authority)
        repository_events = [
            event for event in self.events[before:] if event.startswith("repository")
        ]
        self.assertEqual(repository_events, ["repository-active-2"])

    def test_prepared_authority_rejects_revoked_template_before_any_lease(
        self,
    ) -> None:
        self.repository.authority = replace(
            self.authority,
            adapter_template=replace(self.authority.adapter_template, status="revoked"),
        )

        with self.assertRaisesRegex(
            PersistedPreparationError,
            "^persisted_authority_invalid$",
        ):
            self._revalidated()

        self.assertFalse(any(event.startswith("acquire-") for event in self.events))

    def test_active_revocation_preserves_only_the_frozen_attempt_binding(
        self,
    ) -> None:
        revalidated = self._revalidated()
        state = self.preparation.resolve_state(revalidated)
        revoked = replace(
            self.authority,
            adapter_template=replace(self.authority.adapter_template, status="revoked"),
        )
        self.repository.post_begin_authority = revoked

        with self.preparation.resolve_secrets(revalidated) as resources:
            snapshot = self.preparation.compile_snapshot(revalidated, state, resources)
            self.preparation.revalidate_for_runtime_action(revalidated, snapshot)
            lease = self.preparation.driver_authority_resolver.resolve_active_launch(
                snapshot.identity,
                snapshot.launch_authority_digest,
            )
            self.assertEqual(lease.authority.attempt, revalidated.attempt)

            self.repository.post_begin_authority = replace(
                revoked,
                adapter_template=replace(
                    revoked.adapter_template,
                    backend_commit="9" * 40,
                ),
            )
            with self.assertRaisesRegex(
                PersistedPreparationError,
                "^persisted_authority_changed$",
            ):
                self.preparation.driver_authority_resolver.resolve_active_launch(
                    snapshot.identity,
                    snapshot.launch_authority_digest,
                )

    def test_explicit_active_cancellation_fence_still_rejects_driver_resolution(
        self,
    ) -> None:
        revalidated = self._revalidated()
        state = self.preparation.resolve_state(revalidated)
        self.repository.post_begin_authority = replace(
            self.authority,
            adapter_template=replace(self.authority.adapter_template, status="revoked"),
        )

        with self.preparation.resolve_secrets(revalidated) as resources:
            snapshot = self.preparation.compile_snapshot(revalidated, state, resources)
            self.repository.active_error = "attempt_cancelled"
            with self.assertRaisesRegex(
                DriverTransportError,
                "^persisted_repository_error$",
            ):
                self.preparation.driver_authority_resolver.resolve_active_launch(
                    snapshot.identity,
                    snapshot.launch_authority_digest,
                )

    def test_driver_resolver_rejects_identity_and_digest_aliases(self) -> None:
        revalidated = self._revalidated()
        state = self.preparation.resolve_state(revalidated)
        resolver = self.preparation.driver_authority_resolver
        with self.preparation.resolve_secrets(revalidated) as resources:
            snapshot = self.preparation.compile_snapshot(
                revalidated,
                state,
                resources,
            )
            with self.assertRaisesRegex(
                PersistedPreparationError,
                "^persisted_active_launch_invalid$",
            ):
                resolver.resolve_active_launch(
                    replace(snapshot.identity, attempt_id="other-attempt"),
                    snapshot.launch_authority_digest,
                )
            with self.assertRaisesRegex(
                PersistedPreparationError,
                "^persisted_active_launch_invalid$",
            ):
                resolver.resolve_active_launch(snapshot.identity, "f" * 64)

    def test_driver_resolver_requires_the_final_active_repository_fence(self) -> None:
        revalidated = self._revalidated()
        state = self.preparation.resolve_state(revalidated)
        resolver = self.preparation.driver_authority_resolver
        with self.preparation.resolve_secrets(revalidated) as resources:
            snapshot = self.preparation.compile_snapshot(
                revalidated,
                state,
                resources,
            )
            self.repository.active_error = "attempt_not_active"
            with self.assertRaisesRegex(
                DriverTransportError,
                "^persisted_repository_error$",
            ):
                resolver.resolve_active_launch(
                    snapshot.identity,
                    snapshot.launch_authority_digest,
                )

        self.assertIn("repository-active-3", self.events)

    def test_raw_mapping_ingress_is_rejected_before_any_lease(self) -> None:
        self.repository.authority = {"instance": self.authority.instance}

        with self.assertRaisesRegex(
            PersistedPreparationError, "^persisted_authority_invalid$"
        ):
            self._revalidated()

        self.assertFalse(any(event.startswith("acquire-") for event in self.events))

    def test_repository_and_evidence_dependency_errors_are_redacted(self) -> None:
        marker = "postgresql://supervisor:password@host/platform"
        self.repository.resolve_error = marker
        with self.assertRaisesRegex(
            DriverTransportError,
            "^persisted_repository_error$",
        ) as repository_error:
            self._revalidated()
        self.assertIsInstance(repository_error.exception, DriverTransportError)
        self.assertNotIn(marker, str(repository_error.exception))

        self.repository.resolve_error = None
        self.ports.evidence_error = marker
        with self.assertRaisesRegex(
            PersistedPreparationError,
            "^persisted_evidence_unavailable$",
        ) as evidence_error:
            self._revalidated()
        self.assertIsInstance(evidence_error.exception, DriverPolicyError)
        self.assertNotIn(marker, str(evidence_error.exception))

        self.ports.evidence_error = None
        self.repository.build_error = marker
        with self.assertRaisesRegex(
            PersistedPreparationError,
            "^persisted_resolved_material_invalid$",
        ) as material_error:
            self._revalidated()
        self.assertIsInstance(material_error.exception, DriverPolicyError)
        self.assertNotIn(marker, str(material_error.exception))

    def test_real_reconciler_blocks_final_authority_drift_without_launch(self) -> None:
        events = self.events

        class SupervisorRepository(Repository):
            def assert_current_lease(
                self,
                job_id: str,
                lease_owner: str,
                lease_generation: int,
            ) -> CurrentLease:
                return CurrentLease(
                    job_id,
                    self.authority.instance.instance_id,
                    8,
                    lease_owner,
                    lease_generation,
                )

            def get_latest_attempt_material(self, instance_id: str) -> None:
                events.append("latest")
                return None

            def prepare_attempt_id(
                self,
                job_id: str,
                lease_owner: str,
                lease_generation: int,
            ) -> str:
                events.append("prepare-attempt")
                return "attempt-1"

            def begin_attempt(
                self,
                job_id: str,
                attempt_id: str,
                resolved_material: object,
                lease_owner: str,
                lease_generation: int,
            ) -> AttemptView:
                events.append("begin-attempt")
                self.post_begin_authority = replace(
                    self.authority,
                    state_allocation=replace(
                        self.authority.state_allocation,
                        generation=2,
                    ),
                )
                return AttemptView(datetime(2026, 7, 17, tzinfo=UTC))

            def record_reconciliation_blocked(
                self,
                job_id: str,
                attempt_id: str | None,
                failure_code: str,
                lease_owner: str,
                lease_generation: int,
            ) -> None:
                events.append(f"blocked-{attempt_id}-{failure_code}")

        class Driver:
            def inspect(self, identity: object) -> DriverInspection:
                events.append("driver-inspect")
                return DriverInspection.absent()

            def launch(self, snapshot: object) -> DriverInspection:
                events.append("driver-launch")
                return DriverInspection.absent()

        class NetworkGate:
            def verify_active(self, plan: object) -> None:
                events.append("network-active")

        class OfflinePublisher:
            def publish(self, identity: object) -> object:
                return identity

        repository = SupervisorRepository(self.authority, events)
        preparation = PersistedAuthorityPreparation(
            repository,
            repository.build_resolved_material,
            self.ports,
            self.ports,
            self.ports,
            self.ports,
            active_launch_lease,
        )
        result = RuntimeSupervisorReconciler(
            repository,
            preparation,
            Driver(),
            NetworkGate(),
            OfflinePublisher(),
            clock=lambda: datetime(2026, 7, 17, tzinfo=UTC),
        ).reconcile(self.job)

        self.assertEqual(result.decision, ReconciliationDecision.FAIL_LATCHED)
        self.assertEqual(result.attempt_id, "attempt-1")
        self.assertEqual(result.failure_code, "runtime_policy_invalid")
        self.assertNotIn("driver-launch", events)
        self.assertEqual(
            events[-5:],
            [
                "close-material",
                "close-secret",
                "close-state",
                "close-image",
                "blocked-attempt-1-runtime_policy_invalid",
            ],
        )

    def test_nested_mapping_ingress_is_rejected(self) -> None:
        self.repository.authority = replace(
            self.authority,
            runtime_spec={
                "canonical_payload": self.authority.runtime_spec.canonical_payload
            },
        )
        with self.assertRaisesRegex(
            PersistedPreparationError, "^persisted_authority_invalid$"
        ):
            self._revalidated()

    def test_noncanonical_runtime_spec_is_rejected_before_evidence_or_leases(
        self,
    ) -> None:
        decoded = json.loads(self.authority.runtime_spec.canonical_payload)
        noncanonical = json.dumps(decoded, indent=2)
        self.repository.authority = replace(
            self.authority,
            runtime_spec=replace(
                self.authority.runtime_spec, canonical_payload=noncanonical
            ),
        )

        with self.assertRaisesRegex(
            PersistedPreparationError, "^persisted_runtime_spec_invalid$"
        ):
            self._revalidated()

        self.assertNotIn("load-evidence", self.events)

    def test_committed_template_drift_is_rejected_before_image_acquisition(
        self,
    ) -> None:
        self.repository.authority = replace(
            self.authority,
            adapter_template=replace(
                self.authority.adapter_template,
                canonical_payload=self.authority.adapter_template.canonical_payload
                + " ",
            ),
        )

        with self.assertRaisesRegex(
            PersistedPreparationError, "^persisted_evidence_mismatch$"
        ):
            self._revalidated()

        self.assertNotIn("acquire-image", self.events)

    def test_preview_leases_are_closed_before_revalidate_returns(self) -> None:
        revalidated = self._revalidated()

        self.assertEqual(revalidated.identity.attempt_id, self.attempt_id)
        self.assertEqual(
            self.events[-5:-1],
            ["close-material", "close-secret", "close-state", "close-image"],
        )
        self.assertEqual(self.events[-1], "build-resolved-material")

    def test_partial_acquisition_closes_every_previously_acquired_lease(self) -> None:
        self.ports.fail_on = "secret"

        with self.assertRaisesRegex(
            PersistedPreparationError,
            "^persisted_resource_acquisition_failed$",
        ) as caught:
            self._revalidated()

        self.assertNotIn("secret failed", str(caught.exception))
        self.assertIn("close-state", self.events)
        self.assertIn("close-image", self.events)
        self.assertNotIn("close-material", self.events)

    def test_partial_acquisition_cleanup_failure_is_never_hidden(self) -> None:
        self.ports.fail_on = "secret"
        self.ports.close_fails = "state"

        with self.assertRaisesRegex(
            PersistedPreparationError,
            "^persisted_resource_close_failed$",
        ):
            self._revalidated()

        self.assertIn("close-state", self.events)
        self.assertIn("close-image", self.events)

    def test_each_lease_revalidation_failure_closes_the_complete_lease_set(
        self,
    ) -> None:
        for failing_kind in ("image", "state", "secret", "material"):
            with self.subTest(failing_kind=failing_kind):
                events: list[str] = []
                repository = Repository(self.authority, events)
                ports = Ports(self.authority, self.base, events)
                ports.revalidate_fails = failing_kind
                preparation = PersistedAuthorityPreparation(
                    repository,
                    repository.build_resolved_material,
                    ports,
                    ports,
                    ports,
                    ports,
                    active_launch_lease,
                )

                with self.assertRaisesRegex(
                    PersistedPreparationError,
                    "^persisted_resource_invalid$",
                ):
                    preparation.revalidate(self.job, self.attempt_id, None)

                for kind in ("material", "secret", "state", "image"):
                    self.assertIn(f"close-{kind}", events)

    def test_compilation_failure_closes_all_leases(self) -> None:
        revalidated = self._revalidated()
        state = self.preparation.resolve_state(revalidated)
        self.ports.evidence = replace(
            self.ports.evidence,
            artifacts=replace(self.ports.evidence.artifacts, config_sha256="f" * 64),
        )

        with self.assertRaisesRegex(
            PersistedPreparationError, "^persisted_evidence_mismatch$"
        ):
            with self.preparation.resolve_secrets(revalidated) as resources:
                self.preparation.compile_snapshot(revalidated, state, resources)

        self.assertEqual(
            self.events[-4:],
            ["close-material", "close-secret", "close-state", "close-image"],
        )

    def test_body_failure_cannot_hide_a_lease_cleanup_failure(self) -> None:
        revalidated = self._revalidated()
        state = self.preparation.resolve_state(revalidated)
        self.ports.close_fails = "secret"
        self.ports.evidence = replace(
            self.ports.evidence,
            artifacts=replace(self.ports.evidence.artifacts, config_sha256="f" * 64),
        )

        with self.assertRaisesRegex(
            PersistedPreparationError,
            "^persisted_resource_close_failed$",
        ):
            with self.preparation.resolve_secrets(revalidated) as resources:
                self.preparation.compile_snapshot(revalidated, state, resources)

        for kind in ("material", "secret", "state", "image"):
            self.assertIn(f"close-{kind}", self.events)

    def test_final_repository_drift_fails_closed_and_closes_all_leases(self) -> None:
        revalidated = self._revalidated()
        state = self.preparation.resolve_state(revalidated)
        self.repository.final_authority = replace(
            self.authority,
            state_allocation=replace(self.authority.state_allocation, generation=2),
        )

        with self.assertRaisesRegex(
            PersistedPreparationError, "^persisted_authority_changed$"
        ):
            with self.preparation.resolve_secrets(revalidated) as resources:
                self.preparation.compile_snapshot(revalidated, state, resources)

        self.assertEqual(self.repository.resolve_count, 2)
        self.assertEqual(
            self.events[-4:],
            ["close-material", "close-secret", "close-state", "close-image"],
        )

    def test_final_repository_revalidation_is_last_authority_gate(self) -> None:
        revalidated = self._revalidated()
        state = self.preparation.resolve_state(revalidated)
        with self.preparation.resolve_secrets(revalidated) as resources:
            self.preparation.compile_snapshot(revalidated, state, resources)
            self.events.append("runtime-action-authorized")

        self.assertLess(
            self.events.index("repository-2"),
            self.events.index("runtime-action-authorized"),
        )

    def test_pre_action_gate_revalidates_live_resources_after_begin_and_before_launch(
        self,
    ) -> None:
        revalidated = self._revalidated()
        state = self.preparation.resolve_state(revalidated)
        with self.preparation.resolve_secrets(revalidated) as resources:
            snapshot = self.preparation.compile_snapshot(revalidated, state, resources)
            self.events.append("begin-attempt-complete")
            self.preparation.revalidate_for_runtime_action(revalidated, snapshot)
            self.events.append("driver-launch")
            self.assertNotIn("close-image", self.events[-8:])

        begin = self.events.index("begin-attempt-complete")
        launch = self.events.index("driver-launch")
        self.assertEqual(
            self.events[begin + 1 : launch],
            [
                "repository-active-3",
                "revalidate-evidence",
                "revalidate-image",
                "revalidate-state",
                "revalidate-secret",
                "revalidate-material",
            ],
        )
        self.assertEqual(
            self.events[-4:],
            ["close-material", "close-secret", "close-state", "close-image"],
        )

    def test_pre_action_gate_rejects_closed_or_uncompiled_context(self) -> None:
        revalidated = self._revalidated()
        state = self.preparation.resolve_state(revalidated)
        with self.preparation.resolve_secrets(revalidated) as resources:
            snapshot = self.preparation.compile_snapshot(revalidated, state, resources)

        with self.assertRaisesRegex(
            PersistedPreparationError,
            "^persisted_runtime_action_context_invalid$",
        ):
            self.preparation.revalidate_for_runtime_action(revalidated, snapshot)

    def test_pre_action_gate_allows_only_begin_owned_lifecycle_transition(self) -> None:
        initial = replace(
            self.authority,
            instance=replace(self.authority.instance, lifecycle_status="registered"),
        )
        events: list[str] = []
        repository = Repository(initial, events)
        repository.final_authority = initial
        repository.post_begin_authority = replace(
            initial,
            instance=replace(initial.instance, lifecycle_status="starting"),
        )
        ports = Ports(initial, self.base, events)
        preparation = PersistedAuthorityPreparation(
            repository,
            repository.build_resolved_material,
            ports,
            ports,
            ports,
            ports,
            active_launch_lease,
        )
        revalidated = preparation.revalidate(self.job, self.attempt_id, None)
        state = preparation.resolve_state(revalidated)
        with preparation.resolve_secrets(revalidated) as resources:
            snapshot = preparation.compile_snapshot(revalidated, state, resources)
            preparation.revalidate_for_runtime_action(revalidated, snapshot)

            repository.post_begin_authority = replace(
                repository.post_begin_authority,
                state_allocation=replace(
                    repository.post_begin_authority.state_allocation,
                    generation=2,
                ),
            )
            with self.assertRaisesRegex(
                PersistedPreparationError,
                "^persisted_authority_changed$",
            ):
                preparation.revalidate_for_runtime_action(revalidated, snapshot)

    def test_resolved_material_builder_output_is_reverse_correlated_exactly(
        self,
    ) -> None:
        mutations = (
            lambda value: replace(value, runtime_spec_revision_id="other-spec"),
            lambda value: replace(value, adapter_template_revision_id="other-template"),
            lambda value: replace(value, state_allocation_id="other-state"),
            lambda value: replace(value, state_allocation_generation=2),
            lambda value: replace(value, image_id="sha256:" + "f" * 64),
            lambda value: replace(value, root_commit="f" * 40),
            lambda value: replace(value, backend_commit="f" * 40),
            lambda value: replace(value, frontend_commit="f" * 40),
            lambda value: replace(value, strategies_commit="f" * 40),
            lambda value: replace(value, project_identity="caller-project"),
            lambda value: replace(value, container_identity="caller-container"),
            lambda value: replace(
                value,
                resolved_secret_versions=(
                    replace(
                        value.resolved_secret_versions[0], version_id="other-version"
                    ),
                    *value.resolved_secret_versions[1:],
                ),
            ),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                events: list[str] = []
                repository = Repository(self.authority, events)
                repository.material_mutator = mutation
                ports = Ports(self.authority, self.base, events)
                preparation = PersistedAuthorityPreparation(
                    repository,
                    repository.build_resolved_material,
                    ports,
                    ports,
                    ports,
                    ports,
                    active_launch_lease,
                )
                with self.assertRaisesRegex(
                    PersistedPreparationError,
                    "^persisted_resolved_material_invalid$",
                ):
                    preparation.revalidate(self.job, self.attempt_id, None)

    def test_sha256_git_object_ids_compile_and_publish_offline_identity(self) -> None:
        base = valid_authority()
        root_commit = "1" * 64
        backend_commit = "2" * 64
        frontend_commit = "3" * 64
        strategies_commit = "4" * 64
        base = replace(
            base,
            spec=replace(
                base.spec,
                config_blob_commit=root_commit,
                strategy_commit=root_commit,
                safety_policy_commit=root_commit,
                root_commit=root_commit,
                backend_commit=backend_commit,
                frontend_commit=frontend_commit,
                strategies_commit=strategies_commit,
            ),
            template=replace(base.template, source_commit=root_commit),
            policies=replace(base.policies, source_commit=root_commit),
            materials=tuple(
                replace(material, root_commit=root_commit)
                for material in base.materials
            ),
        )
        authority, base = _authority(base)
        events: list[str] = []
        repository = Repository(authority, events)
        ports = Ports(authority, base, events)
        preparation = PersistedAuthorityPreparation(
            repository,
            repository.build_resolved_material,
            ports,
            ports,
            ports,
            ports,
            active_launch_lease,
        )
        revalidated = preparation.revalidate(
            _job(base.identity.instance_id),
            self.attempt_id,
            None,
        )
        state = preparation.resolve_state(revalidated)
        with preparation.resolve_secrets(revalidated) as resources:
            snapshot = preparation.compile_snapshot(revalidated, state, resources)
            preparation.revalidate_for_runtime_action(revalidated, snapshot)
            observed = DriverInspection(
                state=DriverState.RUNNING,
                container_id="a" * 64,
                observed_project_name=revalidated.identity.project_name,
                observed_container_name=revalidated.identity.container_name,
                observed_instance_id=revalidated.identity.instance_id,
                observed_attempt_id=revalidated.identity.attempt_id,
                observed_runtime_spec_digest=revalidated.identity.runtime_spec_digest,
                observed_launch_authority_digest=snapshot.launch_authority_digest,
                observed_state_allocation_id=revalidated.identity.state_allocation_id,
                observed_image_id=revalidated.identity.image_id,
                observed_network_names=revalidated.identity.network_names,
                health=DriverHealth.HEALTHY,
                exit_code=None,
            )
            offline = preparation.compile_offline_identity(
                revalidated,
                observed,
                instance_revision=8,
                lease_generation=1,
            )

        self.assertEqual(len(offline.root_commit), 64)
        self.assertEqual(offline.backend_commit, backend_commit)

    def test_recover_identity_rejects_persisted_caller_name_drift(self) -> None:
        revalidated = self._revalidated()
        material = revalidated.resolved_material
        latest = Latest(
            self.attempt_id,
            revalidated.identity.runtime_spec_digest,
            replace(material, project_identity="caller-project"),
        )

        with self.assertRaisesRegex(
            PersistedPreparationError, "^persisted_identity_invalid$"
        ):
            self.preparation.recover_identity(latest)

    def test_recover_identity_derives_networks_from_committed_policy(self) -> None:
        revalidated = self._revalidated()
        latest = Latest(
            self.attempt_id,
            revalidated.identity.runtime_spec_digest,
            revalidated.resolved_material,
        )

        recovered = self.preparation.recover_identity(latest)

        self.assertEqual(recovered.network_names, revalidated.identity.network_names)
        self.assertEqual(self.events[-1], "load-evidence")

    def test_health_access_and_offline_contracts_are_derived_from_authority(
        self,
    ) -> None:
        revalidated = self._revalidated()
        profile = self.preparation.resolve_health_profile(revalidated)
        plan = self.preparation.compile_access_network_plan(revalidated, "a" * 64)
        observed = DriverInspection(
            state=DriverState.RUNNING,
            container_id="a" * 64,
            observed_project_name=revalidated.identity.project_name,
            observed_container_name=revalidated.identity.container_name,
            observed_instance_id=revalidated.identity.instance_id,
            observed_attempt_id=revalidated.identity.attempt_id,
            observed_runtime_spec_digest=revalidated.identity.runtime_spec_digest,
            observed_launch_authority_digest=revalidated.provenance.launch_authority_digest,
            observed_state_allocation_id=revalidated.identity.state_allocation_id,
            observed_image_id=revalidated.identity.image_id,
            observed_network_names=revalidated.identity.network_names,
            health=DriverHealth.HEALTHY,
            exit_code=None,
        )
        offline = self.preparation.compile_offline_identity(
            revalidated,
            observed,
            instance_revision=8,
            lease_generation=1,
        )

        self.assertEqual(profile, self.base.policies.health_profile)
        self.assertEqual(
            plan.access_identity.network_name, self.base.identity.network_names[0]
        )
        self.assertEqual(
            offline.launch_authority_digest,
            revalidated.provenance.launch_authority_digest,
        )

    def test_close_failure_still_attempts_every_lease_close(self) -> None:
        self.ports.close_fails = "secret"

        with self.assertRaisesRegex(
            PersistedPreparationError,
            "^persisted_resource_close_failed$",
        ):
            self._revalidated()

        for kind in ("material", "secret", "state", "image"):
            self.assertIn(f"close-{kind}", self.events)


if __name__ == "__main__":
    unittest.main()
