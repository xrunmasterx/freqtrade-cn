"""Fail-closed preregistered gate math for the Donchian-logistic candidate.

This revision deliberately has no performance-artifact reader.  The pure functions freeze the
Decimal metric and threshold rules for tests, but only a future hash-bound materializer may call
them as part of an acceptance path.  The CLI therefore emits a deterministic NOT_READY plan.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any


CANDIDATE_ID = "donchian-logistic-meta-label-v1"
SCHEDULED_START = datetime(2026, 8, 14, tzinfo=UTC)
STARTING_WALLET = Decimal(1000)
LEVERAGE = Decimal(14)
FIVE_MINUTES = timedelta(minutes=5)

PENDING = "PENDING"
NOT_READY = "NOT_READY"
INVALID = "INVALID"
INSUFFICIENT = "INSUFFICIENT"
FAIL = "FAIL"
PASS = "PASS"  # noqa: S105 - protocol state, not a credential
STATUSES = (PENDING, NOT_READY, INVALID, INSUFFICIENT, FAIL, PASS)

NA = "N/A"
POSITIVE_INFINITY = "+infinity"

ENDPOINT_DAYS: dict[str, int] = {
    "D7": 7,
    "D30": 30,
    "D90": 90,
    "D180": 180,
    "D365": 365,
}
ENDPOINTS = (*ENDPOINT_DAYS, "RELEASE_TO_DATE")
SCENARIO_FEES: dict[str, Decimal] = {
    "baseline": Decimal("0.0006"),
    "stress": Decimal("0.0010"),
    "severe": Decimal("0.0015"),
}

TRADE_ROW_FIELDS = frozenset(
    {
        "exit_reason",
        "funding_fees",
        "is_short",
        "leverage",
        "profit_abs",
        "profit_ratio",
        "trade_id",
    }
)


class InvalidEvidence(ValueError):
    """Raised when normalized prospective evidence violates the frozen contract."""


def _decimal(value: Any, field: str) -> Decimal:
    """Convert an exact JSON-style number without ever accepting a binary float."""

    if value is None or isinstance(value, (bool, float)):
        raise InvalidEvidence(f"{field} is not an exact Decimal input")
    if not isinstance(value, (Decimal, int, str)):
        raise InvalidEvidence(f"{field} is not an exact Decimal input")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise InvalidEvidence(f"{field} is not an exact Decimal input") from error
    if not result.is_finite():
        raise InvalidEvidence(f"{field} is nonfinite")
    return result


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise InvalidEvidence("cannot serialize a nonfinite Decimal")
    if value == 0:
        return "0"
    rendered = format(value.normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise InvalidEvidence("timestamp lacks a timezone")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _whole_number(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidEvidence(f"{field} is not a nonnegative integer")
    return value


def resolve_effective_start(
    *, frozen_at: datetime, disposition: str, effective_start: datetime
) -> datetime:
    """Validate the scheduled-R or explicit-deferral rule from a future final manifest."""

    for field, value in (("frozen_at", frozen_at), ("effective_start", effective_start)):
        if value.tzinfo is None:
            raise InvalidEvidence(f"{field} lacks a timezone")
    frozen_at = frozen_at.astimezone(UTC)
    effective_start = effective_start.astimezone(UTC)
    if frozen_at < SCHEDULED_START:
        if disposition != "ON_TIME" or effective_start != SCHEDULED_START:
            raise InvalidEvidence("a pre-R freeze must use ON_TIME and scheduled R")
    elif disposition != "DEFERRED" or effective_start <= frozen_at:
        raise InvalidEvidence("a chain not frozen before R must explicitly precommit a later R")
    if frozen_at >= effective_start:
        raise InvalidEvidence("the complete chain was not frozen before effective R")
    if (effective_start - datetime(1970, 1, 1, tzinfo=UTC)) % FIVE_MINUTES:
        raise InvalidEvidence("effective R is not 5m-aligned")
    return effective_start


def checkpoint_times(
    effective_start: datetime, release_to_date_at: datetime
) -> dict[str, datetime]:
    """Return fixed elapsed checkpoints plus one precommitted release-to-date instant."""

    if effective_start.tzinfo is None or release_to_date_at.tzinfo is None:
        raise InvalidEvidence("checkpoint timestamps must be timezone-aware")
    effective_start = effective_start.astimezone(UTC)
    release_to_date_at = release_to_date_at.astimezone(UTC)
    if release_to_date_at <= effective_start:
        raise InvalidEvidence("release-to-date must be after effective R")
    if (release_to_date_at - effective_start) % FIVE_MINUTES:
        raise InvalidEvidence("release-to-date must be precommitted on the continuous 5m grid")
    result = {
        name: effective_start + timedelta(days=days) for name, days in ENDPOINT_DAYS.items()
    }
    result["RELEASE_TO_DATE"] = release_to_date_at
    return result


def missing_checkpoint_status(*, checkpoint_at: datetime, as_of: datetime) -> str:
    """Classify absent evidence without inspecting any performance artifact."""

    if checkpoint_at.tzinfo is None or as_of.tzinfo is None:
        raise InvalidEvidence("readiness timestamps must be timezone-aware")
    return PENDING if as_of.astimezone(UTC) < checkpoint_at.astimezone(UTC) else NOT_READY


def _direction_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    absolute = [_decimal(row["profit_abs"], "profit_abs") for row in rows]
    ratios = [_decimal(row["profit_ratio"], "profit_ratio") for row in rows]
    positive_abs = [value for value in absolute if value > 0]
    negative_abs = [value for value in absolute if value < 0]
    positive_ratios = [value for value in ratios if value > 0]
    negative_ratios = [value for value in ratios if value < 0]

    count = len(rows)
    win_rate: Decimal | str = Decimal(len(positive_abs)) / Decimal(count) if count else NA
    strict_payoff: Decimal | str = NA
    if positive_ratios and negative_ratios:
        mean_win = sum(positive_ratios, Decimal(0)) / Decimal(len(positive_ratios))
        mean_loss = sum(negative_ratios, Decimal(0)) / Decimal(len(negative_ratios))
        strict_payoff = mean_win / abs(mean_loss)

    gross_profit_abs = sum(positive_abs, Decimal(0))
    gross_loss_abs = abs(sum(negative_abs, Decimal(0)))
    profit_factor: Decimal | str
    if gross_loss_abs > 0:
        profit_factor = gross_profit_abs / gross_loss_abs
    elif gross_profit_abs > 0:
        profit_factor = POSITIVE_INFINITY
    else:
        profit_factor = NA

    concentration: Decimal | str = NA
    if gross_profit_abs > 0:
        concentration = max(positive_abs) / gross_profit_abs
    return {
        "closed_trade_count": count,
        "win_count": len(positive_abs),
        "loss_count": len(negative_abs),
        "draw_count": count - len(positive_abs) - len(negative_abs),
        "win_rate": win_rate,
        "strict_payoff": strict_payoff,
        "profit_factor": profit_factor,
        "gross_profit_abs": gross_profit_abs,
        "gross_loss_abs": gross_loss_abs,
        "net_profit_abs": sum(absolute, Decimal(0)),
        "best_trade_concentration": concentration,
    }


def recompute_trade_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Recompute natural-close metrics from strict normalized trade rows using Decimal.

    This does not establish that rows are authoritative.  A future materializer must derive and
    bind them to the standard Freqtrade result before this math may support acceptance.
    """

    normalized: list[dict[str, Any]] = []
    trade_ids: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping) or set(raw) != TRADE_ROW_FIELDS:
            raise InvalidEvidence(f"trade[{index}] schema mismatch")
        trade_id = raw["trade_id"]
        if not isinstance(trade_id, str) or not trade_id or trade_id in trade_ids:
            raise InvalidEvidence(f"trade[{index}].trade_id is invalid or duplicated")
        trade_ids.add(trade_id)
        if not isinstance(raw["is_short"], bool):
            raise InvalidEvidence(f"trade[{index}].is_short is not boolean")
        if _decimal(raw["leverage"], f"trade[{index}].leverage") != LEVERAGE:
            raise InvalidEvidence(f"trade[{index}].leverage is not exactly 14")
        _decimal(raw["funding_fees"], f"trade[{index}].funding_fees")
        profit_abs = _decimal(raw["profit_abs"], f"trade[{index}].profit_abs")
        profit_ratio = _decimal(raw["profit_ratio"], f"trade[{index}].profit_ratio")
        if (profit_abs > 0) != (profit_ratio > 0) or (profit_abs < 0) != (profit_ratio < 0):
            raise InvalidEvidence(f"trade[{index}] profit signs disagree")
        exit_reason = raw["exit_reason"]
        if not isinstance(exit_reason, str) or not exit_reason:
            raise InvalidEvidence(f"trade[{index}].exit_reason is invalid")
        if exit_reason == "force_exit":
            raise InvalidEvidence("checkpoint force_exit violates the frozen continuous ledger")
        normalized.append(dict(raw))

    result = _direction_metrics(normalized)
    long_rows = [row for row in normalized if row["is_short"] is False]
    short_rows = [row for row in normalized if row["is_short"] is True]
    result["long"] = _direction_metrics(long_rows)
    result["short"] = _direction_metrics(short_rows)
    result["liquidation_count"] = sum(
        row["exit_reason"] == "liquidation" for row in normalized
    )
    return result


def recompute_max_drawdown(equity_path: Sequence[Any]) -> Decimal:
    """Recompute account drawdown from a complete authoritative marked-equity prefix."""

    if not equity_path:
        raise InvalidEvidence("marked-equity path is empty")
    values = [_decimal(value, f"equity[{index}]") for index, value in enumerate(equity_path)]
    if values[0] != STARTING_WALLET:
        raise InvalidEvidence("marked-equity path does not start at 1000 USDT")
    if any(value < 0 for value in values):
        raise InvalidEvidence("marked-equity path contains negative equity")
    peak = values[0]
    maximum = Decimal(0)
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            maximum = max(maximum, (peak - value) / peak)
    return maximum


def add_checkpoint_account_metrics(
    trade_metrics: Mapping[str, Any], equity_path: Sequence[Any]
) -> dict[str, Any]:
    """Attach net return and drawdown to already validated trade metrics.

    The function is contractual math only.  It never asserts that the supplied equity path is a
    hash-bound 5m mark/funding recomputation.
    """

    if not equity_path:
        raise InvalidEvidence("marked-equity path is empty")
    result = dict(trade_metrics)
    terminal_equity = _decimal(equity_path[-1], "checkpoint_equity")
    result["checkpoint_equity"] = terminal_equity
    result["net_return"] = terminal_equity / STARTING_WALLET - Decimal(1)
    result["max_drawdown"] = recompute_max_drawdown(equity_path)
    return result


def _metric_decimal(metrics: Mapping[str, Any], field: str) -> Decimal:
    if field not in metrics:
        raise InvalidEvidence(f"validated metrics are missing {field}")
    value = metrics[field]
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvalidEvidence(f"validated metric {field} is not a finite Decimal")
    return value


def _metric_count(metrics: Mapping[str, Any], field: str) -> int:
    if field not in metrics:
        raise InvalidEvidence(f"validated metrics are missing {field}")
    return _whole_number(metrics[field], field)


def _profit_factor_gt(value: Any, threshold: Decimal) -> bool:
    if value == POSITIVE_INFINITY:
        return True
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvalidEvidence("validated profit_factor has an invalid sentinel or value")
    return value > threshold


def _optional_metric_decimal(
    metrics: Mapping[str, Any], field: str, *, allow_infinity: bool = False
) -> Decimal | str:
    if field not in metrics:
        raise InvalidEvidence(f"validated metrics are missing {field}")
    value = metrics[field]
    allowed = {NA, POSITIVE_INFINITY} if allow_infinity else {NA}
    if isinstance(value, str):
        if value not in allowed:
            raise InvalidEvidence(f"validated metric {field} has an invalid sentinel")
        return value
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise InvalidEvidence(f"validated metric {field} is invalid")
    return value


def _validate_outcome_sentinels(metrics: Mapping[str, Any], wins: int, losses: int) -> None:
    payoff = _optional_metric_decimal(metrics, "strict_payoff")
    profit_factor = _optional_metric_decimal(metrics, "profit_factor", allow_infinity=True)
    if wins and losses:
        if payoff == NA or profit_factor in (NA, POSITIVE_INFINITY):
            raise InvalidEvidence("validated payoff/PF sentinels disagree with wins and losses")
        return
    if payoff != NA:
        raise InvalidEvidence("validated payoff must be N/A without both wins and losses")
    if wins:
        expected_profit_factor: Decimal | str = POSITIVE_INFINITY
    elif losses:
        expected_profit_factor = Decimal(0)
    else:
        expected_profit_factor = NA
    if profit_factor != expected_profit_factor:
        raise InvalidEvidence("validated profit_factor sentinel disagrees with outcomes")


def _validate_metric_shape(metrics: Mapping[str, Any]) -> None:
    if not isinstance(metrics.get("long"), Mapping) or not isinstance(
        metrics.get("short"), Mapping
    ):
        raise InvalidEvidence("validated metrics lack direction evidence")
    count = _metric_count(metrics, "closed_trade_count")
    wins = _metric_count(metrics, "win_count")
    losses = _metric_count(metrics, "loss_count")
    draws = _metric_count(metrics, "draw_count")
    if wins + losses + draws != count:
        raise InvalidEvidence("validated win/loss/draw counts do not sum to closed trades")
    long_count = _metric_count(metrics["long"], "closed_trade_count")
    short_count = _metric_count(metrics["short"], "closed_trade_count")
    if long_count + short_count != count:
        raise InvalidEvidence("validated direction counts do not sum to closed trades")
    win_rate = _optional_metric_decimal(metrics, "win_rate")
    expected_win_rate: Decimal | str = Decimal(wins) / Decimal(count) if count else NA
    if win_rate != expected_win_rate:
        raise InvalidEvidence("validated win_rate disagrees with the trade counts")
    _validate_outcome_sentinels(metrics, wins, losses)
    net_return = _metric_decimal(metrics, "net_return")
    checkpoint_equity = _metric_decimal(metrics, "checkpoint_equity")
    drawdown = _metric_decimal(metrics, "max_drawdown")
    if checkpoint_equity < 0 or net_return != checkpoint_equity / STARTING_WALLET - 1:
        raise InvalidEvidence("validated checkpoint equity and net return disagree")
    if drawdown < 0 or drawdown > 1:
        raise InvalidEvidence("validated max_drawdown is outside [0,1]")
    if not net_return.is_finite():
        raise InvalidEvidence("validated net_return is nonfinite")
    liquidations = _metric_count(metrics, "liquidation_count")
    if liquidations > count:
        raise InvalidEvidence("liquidation_count exceeds closed_trade_count")


def evaluate_metric_thresholds(
    endpoint: str, scenario: str, metrics: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate frozen threshold math without emitting an acceptance status.

    This helper cannot validate evidence.  In particular, ``thresholds_met=True`` is not PASS;
    only a future authoritative materializer may use these checks inside a fail-closed state
    transition.
    """

    if endpoint not in ENDPOINTS:
        raise InvalidEvidence(f"unknown endpoint: {endpoint}")
    if scenario not in SCENARIO_FEES:
        raise InvalidEvidence(f"unknown fee scenario: {scenario}")
    _validate_metric_shape(metrics)
    count = _metric_count(metrics, "closed_trade_count")
    wins = _metric_count(metrics, "win_count")
    losses = _metric_count(metrics, "loss_count")
    long_count = _metric_count(metrics["long"], "closed_trade_count")
    short_count = _metric_count(metrics["short"], "closed_trade_count")
    insufficiency: list[str] = []
    if count < 30:
        insufficiency.append("closed_trade_count_lt_30")
    if long_count < 5:
        insufficiency.append("long_closed_trade_count_lt_5")
    if short_count < 5:
        insufficiency.append("short_closed_trade_count_lt_5")
    if wins < 1:
        insufficiency.append("win_count_lt_1")
    if losses < 1:
        insufficiency.append("loss_count_lt_1")

    role = "REPORT_ONLY" if endpoint == "D7" or scenario == "severe" else "GATE"
    required = ("profit_factor",) if scenario == "stress" else (
        "win_rate",
        "strict_payoff",
        "profit_factor",
    )
    if role == "GATE":
        insufficiency.extend(
            f"required_metric_{field}_is_N/A" for field in required if metrics.get(field) == NA
        )
    if insufficiency:
        return {
            "checks": {},
            "insufficiency_reasons": insufficiency,
            "role": role,
            "sufficient": False,
            "thresholds_met": None,
        }
    if role == "REPORT_ONLY":
        return {
            "checks": {},
            "insufficiency_reasons": [],
            "role": role,
            "sufficient": True,
            "thresholds_met": None,
        }

    net_return = _metric_decimal(metrics, "net_return")
    max_drawdown = _metric_decimal(metrics, "max_drawdown")
    liquidation_count = _metric_count(metrics, "liquidation_count")
    if scenario == "stress":
        checks = {
            "net_return_gt_0": net_return > 0,
            "profit_factor_gt_1": _profit_factor_gt(metrics["profit_factor"], Decimal(1)),
            "max_drawdown_lt_30pct": max_drawdown < Decimal("0.30"),
            "liquidation_count_eq_0": liquidation_count == 0,
        }
    else:
        win_rate = _metric_decimal(metrics, "win_rate")
        strict_payoff = _metric_decimal(metrics, "strict_payoff")
        return_key = "net_return_gte_100pct" if endpoint == "D30" else "net_return_gt_0"
        return_passes = net_return >= 1 if endpoint == "D30" else net_return > 0
        checks = {
            return_key: return_passes,
            "win_rate_gte_40pct": win_rate >= Decimal("0.40"),
            "strict_payoff_gt_2": strict_payoff > Decimal(2),
            "profit_factor_gt_1_2": _profit_factor_gt(
                metrics["profit_factor"], Decimal("1.2")
            ),
            "max_drawdown_lt_25pct": max_drawdown < Decimal("0.25"),
            "liquidation_count_eq_0": liquidation_count == 0,
        }
    return {
        "checks": checks,
        "insufficiency_reasons": [],
        "role": role,
        "sufficient": True,
        "thresholds_met": all(checks.values()),
    }


def deterministic_plan() -> dict[str, Any]:
    checkpoints = [
        {
            "endpoint": endpoint,
            "scheduled_at": (
                _timestamp(SCHEDULED_START + timedelta(days=ENDPOINT_DAYS[endpoint]))
                if endpoint in ENDPOINT_DAYS
                else "FINAL_MANIFEST_PRECOMMIT_REQUIRED"
            ),
        }
        for endpoint in ENDPOINTS
    ]
    return {
        "action": "plan",
        "authorization": "NONE_RESEARCH_EVIDENCE_ONLY",
        "candidate_id": CANDIDATE_ID,
        "checkpoints": checkpoints,
        "continuous_ledger_contract": (
            "one wallet per fee scenario from effective R and 1000 USDT; checkpoints preserve "
            "open state and use complete 5m marked equity; no checkpoint force_exit or reset"
        ),
        "fee_scenarios": {
            "baseline": {
                "fee_per_side": format(SCENARIO_FEES["baseline"], ".4f"),
                "meaning": "5bp OKX public-base taker proxy plus 1bp slippage proxy",
            },
            "stress": {"fee_per_side": format(SCENARIO_FEES["stress"], ".4f")},
            "severe": {
                "fee_per_side": format(SCENARIO_FEES["severe"], ".4f"),
                "role": "REPORT_ONLY",
            },
        },
        "network_access": False,
        "performance_read": False,
        "scheduled_start_at": _timestamp(SCHEDULED_START),
        "status": NOT_READY,
        "status_reason": (
            "the final freeze and authoritative materializer/input schema do not yet bind "
            "standard Freqtrade rows plus self-recomputed 5m mark/funding equity"
        ),
        "subprocess_execution_implemented": False,
        "writes": False,
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print the fail-closed Donchian-logistic prospective evaluation plan."
    )
    parser.add_argument("--plan", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    build_parser().parse_args(argv)
    print(json.dumps(_jsonable(deterministic_plan()), allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
