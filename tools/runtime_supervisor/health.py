from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from tools.runtime_driver import DriverValidationError, HealthProfile


def health_profile_digest(profile: HealthProfile) -> str:
    if type(profile) is not HealthProfile:
        raise DriverValidationError()
    try:
        profile.__post_init__()
    except Exception:
        raise DriverValidationError() from None
    payload = {
        "interval_seconds": profile.interval_seconds,
        "probe_argv": list(profile.probe_argv),
        "profile_id": profile.profile_id,
        "retries": profile.retries,
        "start_period_seconds": profile.start_period_seconds,
        "timeout_seconds": profile.timeout_seconds,
    }
    document = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(document).hexdigest()


def health_probe_not_before(
    started_at: datetime,
    profile: HealthProfile,
    ordinal: int,
) -> datetime:
    _validate_schedule_inputs(started_at, profile, ordinal)
    return started_at + timedelta(
        seconds=(
            profile.start_period_seconds + ((ordinal - 1) * profile.interval_seconds)
        )
    )


def health_deadline(started_at: datetime, profile: HealthProfile) -> datetime:
    return health_probe_not_before(started_at, profile, profile.retries) + timedelta(
        seconds=profile.timeout_seconds
    )


def _validate_schedule_inputs(
    started_at: datetime,
    profile: HealthProfile,
    ordinal: int,
) -> None:
    if (
        type(started_at) is not datetime
        or started_at.tzinfo is None
        or started_at.utcoffset() is None
        or started_at.utcoffset() != timedelta(0)
        or type(profile) is not HealthProfile
        or type(ordinal) is not int
        or ordinal <= 0
        or ordinal > profile.retries
    ):
        raise DriverValidationError()
