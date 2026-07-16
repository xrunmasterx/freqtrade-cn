from __future__ import annotations

from enum import StrEnum

from tools.runtime_driver import (
    AccessNetworkIdentity,
    AccessNetworkIdentityError,
    AccessNetworkLabel,
    AccessNetworkMember,
    AccessNetworkMemberMismatch,
    AccessNetworkObservation,
    AccessNetworkState,
    DriverValidationError,
    LaunchSnapshot,
    PlatformControlIdentity,
    RuntimeAccessAttachmentMissing,
    RuntimeAccessMemberIdentity,
    RuntimeAccessNetworkDriver,
    RuntimeAccessNetworkGate,
    RuntimeAccessNetworkPlan,
    PlatformControlIdentityProvider,
)


class AccessNetworkAction(StrEnum):
    CREATE = "create"
    CONNECT_PLATFORM_CONTROL = "connect_platform_control"
    READY = "ready"
    REMOVE = "remove"
    ALREADY_ABSENT = "already_absent"


def _access_binding(snapshot: LaunchSnapshot):
    if type(snapshot) is not LaunchSnapshot:
        raise DriverValidationError()
    snapshot.__post_init__()
    bindings = tuple(
        binding for binding in snapshot.network_bindings if binding.role == "access"
    )
    if len(bindings) != 1:
        raise AccessNetworkIdentityError()
    return bindings[0]


def compile_access_network_identity(snapshot: LaunchSnapshot) -> AccessNetworkIdentity:
    binding = _access_binding(snapshot)
    return AccessNetworkIdentity(
        instance_id=snapshot.identity.instance_id,
        network_name=binding.network_name,
        policy_digest=binding.policy_digest,
        internal=binding.internal,
        requires_upstream_access=binding.requires_upstream_access,
        requires_platform_control=binding.requires_platform_control,
    )


def compile_runtime_access_member(
    snapshot: LaunchSnapshot,
    container_id: str,
) -> RuntimeAccessMemberIdentity:
    binding = _access_binding(snapshot)
    return RuntimeAccessMemberIdentity(
        container_id=container_id,
        runtime_identity=snapshot.identity,
        compose_service="runtime",
        runtime_alias=binding.runtime_alias,
    )


def compile_runtime_access_network_plan(
    snapshot: LaunchSnapshot,
    container_id: str,
) -> RuntimeAccessNetworkPlan:
    return RuntimeAccessNetworkPlan(
        access_identity=compile_access_network_identity(snapshot),
        runtime_member=compile_runtime_access_member(snapshot, container_id),
    )


class RuntimeAccessNetworkCoordinator(RuntimeAccessNetworkGate):
    def __init__(
        self,
        driver: RuntimeAccessNetworkDriver,
        platform_control_provider: PlatformControlIdentityProvider,
    ) -> None:
        self._driver = driver
        self._platform_control_provider = platform_control_provider

    def verify_active(self, plan: RuntimeAccessNetworkPlan) -> None:
        if type(plan) is not RuntimeAccessNetworkPlan:
            raise DriverValidationError()
        platform_control = (
            self._platform_control_provider.resolve_platform_control_identity()
        )
        if type(platform_control) is not PlatformControlIdentity:
            raise DriverValidationError()
        self._driver.ensure_access_network(
            plan.access_identity,
            platform_control,
            plan.runtime_member,
        )
        self._driver.verify_active_access_network(
            plan.access_identity,
            platform_control,
            plan.runtime_member,
        )


def expected_access_network_labels(
    identity: AccessNetworkIdentity,
) -> tuple[AccessNetworkLabel, ...]:
    if type(identity) is not AccessNetworkIdentity:
        raise DriverValidationError()
    labels = {
        "io.freqtrade.runtime.network.identity-revision": "runtime-access-v1",
        "io.freqtrade.runtime.network.instance-id": identity.instance_id,
        "io.freqtrade.runtime.network.managed": "true",
        "io.freqtrade.runtime.network.policy-digest": identity.policy_digest,
        "io.freqtrade.runtime.network.role": "access",
    }
    return tuple(
        AccessNetworkLabel(name, labels[name])
        for name in sorted(labels)
    )


def _validate_network_identity(
    identity: AccessNetworkIdentity,
    observed: AccessNetworkObservation,
) -> None:
    if (
        type(identity) is not AccessNetworkIdentity
        or type(observed) is not AccessNetworkObservation
    ):
        raise DriverValidationError()
    if observed.state is AccessNetworkState.ABSENT:
        return
    if (
        observed.observed_name != identity.network_name
        or observed.observed_driver != "bridge"
        or observed.observed_scope != "local"
        or observed.observed_internal is not identity.internal
        or observed.observed_attachable is not False
        or observed.observed_ingress is not False
        or observed.observed_config_only is not False
        or observed.observed_labels != expected_access_network_labels(identity)
    ):
        raise AccessNetworkIdentityError()


def _validate_member_aliases(
    member: AccessNetworkMember,
    *,
    required_alias: str,
    allowed_aliases: frozenset[str],
) -> None:
    allowed_aliases = allowed_aliases | {
        member.container_id,
        member.container_id[:12],
    }
    if member.aliases is None or required_alias not in member.aliases:
        raise AccessNetworkMemberMismatch()
    if not set(member.aliases) <= allowed_aliases:
        raise AccessNetworkMemberMismatch()
    allowed_dns_names = allowed_aliases
    if member.dns_names is not None and not set(member.dns_names) <= allowed_dns_names:
        raise AccessNetworkMemberMismatch()


def _validate_platform_member(
    member: AccessNetworkMember,
    platform_control: PlatformControlIdentity,
) -> None:
    if (
        member.container_id != platform_control.container_id
        or member.container_name != platform_control.container_name
    ):
        raise AccessNetworkMemberMismatch()
    _validate_member_aliases(
        member,
        required_alias="platform-control",
        allowed_aliases=frozenset(
            {
                "platform-control",
                platform_control.container_name,
                platform_control.compose_service,
            }
        ),
    )


def _validate_runtime_member(
    member: AccessNetworkMember,
    runtime: RuntimeAccessMemberIdentity,
) -> None:
    if (
        member.container_id != runtime.container_id
        or member.container_name != runtime.container_name
    ):
        raise AccessNetworkMemberMismatch()
    _validate_member_aliases(
        member,
        required_alias=runtime.runtime_alias,
        allowed_aliases=frozenset(
            {
                runtime.runtime_alias,
                runtime.container_name,
                runtime.compose_service,
            }
        ),
    )


def decide_access_network_preparation(
    identity: AccessNetworkIdentity,
    platform_control: PlatformControlIdentity,
    observed: AccessNetworkObservation,
    runtime: RuntimeAccessMemberIdentity | None = None,
) -> AccessNetworkAction:
    if (
        type(platform_control) is not PlatformControlIdentity
        or (runtime is not None and type(runtime) is not RuntimeAccessMemberIdentity)
    ):
        raise DriverValidationError()
    _validate_network_identity(identity, observed)
    if observed.state is AccessNetworkState.ABSENT:
        return AccessNetworkAction.CREATE

    members = {member.container_id: member for member in observed.members}
    allowed_ids = {platform_control.container_id}
    if runtime is not None:
        allowed_ids.add(runtime.container_id)
    if not set(members) <= allowed_ids:
        raise AccessNetworkMemberMismatch()
    platform_member = members.get(platform_control.container_id)
    if platform_member is None:
        return AccessNetworkAction.CONNECT_PLATFORM_CONTROL
    _validate_platform_member(platform_member, platform_control)
    if runtime is not None:
        runtime_member = members.get(runtime.container_id)
        if runtime_member is None:
            raise RuntimeAccessAttachmentMissing()
        _validate_runtime_member(runtime_member, runtime)
    return AccessNetworkAction.READY


def decide_active_access_network(
    identity: AccessNetworkIdentity,
    platform_control: PlatformControlIdentity,
    runtime: RuntimeAccessMemberIdentity,
    observed: AccessNetworkObservation,
) -> AccessNetworkAction:
    if type(runtime) is not RuntimeAccessMemberIdentity:
        raise DriverValidationError()
    if observed.state is AccessNetworkState.ABSENT:
        raise RuntimeAccessAttachmentMissing()
    return decide_access_network_preparation(
        identity,
        platform_control,
        observed,
        runtime,
    )


def decide_access_network_removal(
    identity: AccessNetworkIdentity,
    observed: AccessNetworkObservation,
) -> AccessNetworkAction:
    _validate_network_identity(identity, observed)
    if observed.state is AccessNetworkState.ABSENT:
        return AccessNetworkAction.ALREADY_ABSENT
    if observed.members:
        raise AccessNetworkMemberMismatch()
    return AccessNetworkAction.REMOVE
