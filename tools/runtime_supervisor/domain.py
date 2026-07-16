from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tools.runtime_driver import (
    DriverHealth,
    DriverIdentity,
    DriverInspection,
    DriverState,
)


class ReconciliationAction(StrEnum):
    START = "start"
    STOP = "stop"


class ReconciliationDecision(StrEnum):
    ADOPT = "adopt"
    LAUNCH = "launch"
    CONTINUE_OBSERVING = "continue_observing"
    STOP_EXACT = "stop_exact"
    ALREADY_ABSENT = "already_absent"
    FAIL_LATCHED = "fail_latched"
    IDENTITY_MISMATCH = "identity_mismatch"


@dataclass(frozen=True, slots=True)
class ReconciliationOutcome:
    action: ReconciliationAction
    decision: ReconciliationDecision
    attempt_id: str | None
    failure_code: str | None


def identity_matches(
    expected: DriverIdentity,
    observed: DriverInspection,
) -> bool:
    return (
        observed.observed_project_name == expected.project_name
        and observed.observed_container_name == expected.container_name
        and observed.observed_instance_id == expected.instance_id
        and observed.observed_attempt_id == expected.attempt_id
        and observed.observed_runtime_spec_digest == expected.runtime_spec_digest
        and observed.observed_state_allocation_id == expected.state_allocation_id
        and observed.observed_image_id == expected.image_id
        and observed.observed_network_names == expected.network_names
    )


def decide_reconciliation(
    action: ReconciliationAction,
    expected_identity: DriverIdentity,
    inspection: DriverInspection,
) -> ReconciliationDecision:
    if inspection.state is DriverState.UNKNOWN:
        return ReconciliationDecision.FAIL_LATCHED

    if inspection.state is DriverState.ABSENT:
        if action is ReconciliationAction.START:
            return ReconciliationDecision.LAUNCH
        return ReconciliationDecision.ALREADY_ABSENT

    if not identity_matches(expected_identity, inspection):
        return ReconciliationDecision.IDENTITY_MISMATCH

    if action is ReconciliationAction.STOP:
        return ReconciliationDecision.STOP_EXACT

    if inspection.state in (DriverState.CREATED, DriverState.STARTING):
        return ReconciliationDecision.CONTINUE_OBSERVING

    if inspection.state is DriverState.RUNNING:
        if inspection.health is DriverHealth.HEALTHY:
            return ReconciliationDecision.ADOPT
        if inspection.health is DriverHealth.STARTING:
            return ReconciliationDecision.CONTINUE_OBSERVING

    return ReconciliationDecision.FAIL_LATCHED
