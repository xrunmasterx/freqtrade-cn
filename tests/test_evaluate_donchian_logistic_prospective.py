from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from tools import evaluate_donchian_logistic_prospective as evaluator


def _trade(
    index: int,
    *,
    profit_ratio: str,
    profit_abs: str,
    is_short: bool,
    exit_reason: str = "roi",
    leverage: str = "14",
) -> dict[str, object]:
    return {
        "exit_reason": exit_reason,
        "funding_fees": "0",
        "is_short": is_short,
        "leverage": leverage,
        "profit_abs": profit_abs,
        "profit_ratio": profit_ratio,
        "trade_id": f"trade-{index:03d}",
    }


def _sufficient_metrics() -> dict[str, object]:
    rows = [
        _trade(
            index,
            profit_ratio="0.03" if index < 12 else "-0.01",
            profit_abs="3" if index < 12 else "-1",
            is_short=index % 2 == 1,
        )
        for index in range(30)
    ]
    metrics = evaluator.recompute_trade_metrics(rows)
    metrics.update(
        {
            "checkpoint_equity": Decimal(2000),
            "max_drawdown": Decimal("0.2499"),
            "net_return": Decimal(1),
        }
    )
    return metrics


def test_trade_metrics_use_decimal_profit_ratio_and_profit_abs_formulas() -> None:
    rows = [
        _trade(0, profit_ratio="0.30", profit_abs="3", is_short=False),
        _trade(1, profit_ratio="0.10", profit_abs="9", is_short=True),
        _trade(2, profit_ratio="-0.10", profit_abs="-4", is_short=False),
        _trade(3, profit_ratio="-0.20", profit_abs="-2", is_short=True),
        _trade(4, profit_ratio="0", profit_abs="0", is_short=False),
    ]

    metrics = evaluator.recompute_trade_metrics(rows)

    assert metrics["win_rate"] == Decimal("0.4")
    assert metrics["strict_payoff"] == Decimal("0.2") / Decimal("0.15")
    assert metrics["profit_factor"] == Decimal(12) / Decimal(6)
    assert metrics["best_trade_concentration"] == Decimal(9) / Decimal(12)
    assert metrics["long"]["closed_trade_count"] == 3
    assert metrics["short"]["closed_trade_count"] == 2


def test_na_and_zero_loss_profit_factor_sentinel_are_explicit() -> None:
    empty = evaluator.recompute_trade_metrics([])
    assert empty["win_rate"] == evaluator.NA
    assert empty["strict_payoff"] == evaluator.NA
    assert empty["profit_factor"] == evaluator.NA

    winners_only = evaluator.recompute_trade_metrics(
        [
            _trade(0, profit_ratio="0.1", profit_abs="2", is_short=False),
            _trade(1, profit_ratio="0.2", profit_abs="3", is_short=True),
        ]
    )
    assert winners_only["strict_payoff"] == evaluator.NA
    assert winners_only["profit_factor"] == evaluator.POSITIVE_INFINITY

    losers_only = evaluator.recompute_trade_metrics(
        [_trade(0, profit_ratio="-0.1", profit_abs="-2", is_short=False)]
    )
    assert losers_only["strict_payoff"] == evaluator.NA
    assert losers_only["profit_factor"] == Decimal(0)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda metrics: metrics.update(closed_trade_count=29, draw_count=-1), "closed"),
        (lambda metrics: metrics["long"].update(closed_trade_count=4), "long"),
        (lambda metrics: metrics["short"].update(closed_trade_count=4), "short"),
        (
            lambda metrics: metrics.update(
                win_count=0, loss_count=30, draw_count=0, win_rate=Decimal(0)
            ),
            "win_count",
        ),
        (
            lambda metrics: metrics.update(
                win_count=30, loss_count=0, draw_count=0, win_rate=Decimal(1)
            ),
            "loss_count",
        ),
    ],
)
def test_auxiliary_direction_and_outcome_sample_rules_are_insufficient(
    mutation, reason: str
) -> None:
    metrics = _sufficient_metrics()
    if reason == "closed":
        metrics["closed_trade_count"] = 29
        metrics["loss_count"] = 17
        metrics["win_rate"] = Decimal(12) / Decimal(29)
        metrics["long"]["closed_trade_count"] = 14
    elif reason == "long":
        metrics["long"]["closed_trade_count"] = 4
        metrics["short"]["closed_trade_count"] = 26
    elif reason == "short":
        metrics["short"]["closed_trade_count"] = 4
        metrics["long"]["closed_trade_count"] = 26
    else:
        mutation(metrics)
        metrics["strict_payoff"] = evaluator.NA
        if reason == "loss_count":
            metrics["profit_factor"] = evaluator.POSITIVE_INFINITY
        else:
            metrics["profit_factor"] = Decimal(0)

    result = evaluator.evaluate_metric_thresholds("D30", "baseline", metrics)

    assert result["sufficient"] is False
    assert result["thresholds_met"] is None
    assert any(reason in item for item in result["insufficiency_reasons"])


def test_exact_sample_boundaries_are_sufficient() -> None:
    metrics = _sufficient_metrics()
    metrics["long"]["closed_trade_count"] = 5
    metrics["short"]["closed_trade_count"] = 25

    result = evaluator.evaluate_metric_thresholds("D30", "baseline", metrics)

    assert result["sufficient"] is True
    assert result["thresholds_met"] is True
    assert "status" not in result


def test_d30_baseline_strict_and_inclusive_boundaries() -> None:
    metrics = _sufficient_metrics()
    passing = evaluator.evaluate_metric_thresholds("D30", "baseline", metrics)
    assert passing["thresholds_met"] is True
    assert passing["checks"]["net_return_gte_100pct"]
    assert passing["checks"]["win_rate_gte_40pct"]

    for field, boundary, failed_check in (
        ("strict_payoff", Decimal(2), "strict_payoff_gt_2"),
        ("profit_factor", Decimal("1.2"), "profit_factor_gt_1_2"),
        ("max_drawdown", Decimal("0.25"), "max_drawdown_lt_25pct"),
    ):
        at_boundary = deepcopy(metrics)
        at_boundary[field] = boundary
        result = evaluator.evaluate_metric_thresholds("D30", "baseline", at_boundary)
        assert result["thresholds_met"] is False
        assert not result["checks"][failed_check]

    below_return = deepcopy(metrics)
    below_return["net_return"] = Decimal("0.999999")
    below_return["checkpoint_equity"] = Decimal("1999.999")
    assert (
        evaluator.evaluate_metric_thresholds("D30", "baseline", below_return)[
            "thresholds_met"
        ]
        is False
    )

    below_win_rate = deepcopy(metrics)
    below_win_rate.update(
        win_count=11,
        loss_count=19,
        win_rate=Decimal(11) / Decimal(30),
    )
    assert (
        evaluator.evaluate_metric_thresholds("D30", "baseline", below_win_rate)[
            "checks"
        ]["win_rate_gte_40pct"]
        is False
    )

    liquidated = deepcopy(metrics)
    liquidated["liquidation_count"] = 1
    assert (
        evaluator.evaluate_metric_thresholds("D30", "baseline", liquidated)["checks"][
            "liquidation_count_eq_0"
        ]
        is False
    )


@pytest.mark.parametrize(
    ("field", "boundary", "check"),
    [
        ("net_return", Decimal(0), "net_return_gt_0"),
        ("profit_factor", Decimal(1), "profit_factor_gt_1"),
        ("max_drawdown", Decimal("0.30"), "max_drawdown_lt_30pct"),
    ],
)
def test_stress_survival_boundaries_are_strict(field: str, boundary: Decimal, check: str) -> None:
    metrics = _sufficient_metrics()
    metrics[field] = boundary
    if field == "net_return":
        metrics["checkpoint_equity"] = evaluator.STARTING_WALLET * (1 + boundary)

    result = evaluator.evaluate_metric_thresholds("D30", "stress", metrics)

    assert result["thresholds_met"] is False
    assert not result["checks"][check]


@pytest.mark.parametrize("endpoint", ["D90", "D180", "D365", "RELEASE_TO_DATE"])
def test_later_baseline_endpoints_require_positive_return(endpoint: str) -> None:
    metrics = _sufficient_metrics()
    metrics["net_return"] = Decimal(0)
    metrics["checkpoint_equity"] = evaluator.STARTING_WALLET

    result = evaluator.evaluate_metric_thresholds(endpoint, "baseline", metrics)

    assert result["thresholds_met"] is False
    assert result["checks"]["net_return_gt_0"] is False


def test_d7_and_severe_are_report_only_and_cannot_repair_a_gate() -> None:
    failing = _sufficient_metrics()
    failing["net_return"] = Decimal("-0.5")
    failing["checkpoint_equity"] = Decimal(500)
    failing["profit_factor"] = Decimal("0.2")
    baseline = evaluator.evaluate_metric_thresholds("D30", "baseline", failing)
    severe = evaluator.evaluate_metric_thresholds("D30", "severe", failing)
    d7 = evaluator.evaluate_metric_thresholds("D7", "baseline", failing)

    assert baseline["thresholds_met"] is False
    assert severe == {
        "checks": {},
        "insufficiency_reasons": [],
        "role": "REPORT_ONLY",
        "sufficient": True,
        "thresholds_met": None,
    }
    assert d7["role"] == "REPORT_ONLY"


def test_fee_scenarios_are_exact_and_baseline_meaning_is_not_exchange_fee_claim() -> None:
    assert evaluator.SCENARIO_FEES == {
        "baseline": Decimal("0.0006"),
        "stress": Decimal("0.0010"),
        "severe": Decimal("0.0015"),
    }
    plan = evaluator.deterministic_plan()
    assert "5bp OKX public-base taker proxy plus 1bp slippage proxy" == plan[
        "fee_scenarios"
    ]["baseline"]["meaning"]
    with pytest.raises(evaluator.InvalidEvidence, match="fee scenario"):
        evaluator.evaluate_metric_thresholds("D30", "unknown", _sufficient_metrics())


def test_fixed_endpoints_and_precommitted_release_to_date_follow_effective_r() -> None:
    release_at = evaluator.SCHEDULED_START + timedelta(days=400)
    times = evaluator.checkpoint_times(evaluator.SCHEDULED_START, release_at)

    assert tuple(times) == evaluator.ENDPOINTS
    assert times["D7"] == datetime(2026, 8, 21, tzinfo=UTC)
    assert times["D30"] == datetime(2026, 9, 13, tzinfo=UTC)
    assert times["D90"] == evaluator.SCHEDULED_START + timedelta(days=90)
    assert times["D180"] == evaluator.SCHEDULED_START + timedelta(days=180)
    assert times["D365"] == evaluator.SCHEDULED_START + timedelta(days=365)
    assert times["RELEASE_TO_DATE"] == release_at

    with pytest.raises(evaluator.InvalidEvidence, match="5m grid"):
        evaluator.checkpoint_times(
            evaluator.SCHEDULED_START, evaluator.SCHEDULED_START + timedelta(seconds=1)
        )


def test_late_final_chain_requires_explicit_future_deferral() -> None:
    late_freeze = evaluator.SCHEDULED_START + timedelta(minutes=1)
    deferred = evaluator.SCHEDULED_START + timedelta(minutes=5)
    assert (
        evaluator.resolve_effective_start(
            frozen_at=late_freeze,
            disposition="DEFERRED",
            effective_start=deferred,
        )
        == deferred
    )
    with pytest.raises(evaluator.InvalidEvidence, match="explicitly precommit"):
        evaluator.resolve_effective_start(
            frozen_at=late_freeze,
            disposition="ON_TIME",
            effective_start=evaluator.SCHEDULED_START,
        )


def test_missing_checkpoint_is_pending_before_time_and_not_ready_after_time() -> None:
    checkpoint = evaluator.SCHEDULED_START + timedelta(days=30)
    assert (
        evaluator.missing_checkpoint_status(
            checkpoint_at=checkpoint, as_of=checkpoint - timedelta(seconds=1)
        )
        == evaluator.PENDING
    )
    assert (
        evaluator.missing_checkpoint_status(checkpoint_at=checkpoint, as_of=checkpoint)
        == evaluator.NOT_READY
    )


def test_nonfinite_missing_funding_wrong_leverage_and_force_exit_fail_closed() -> None:
    valid = _trade(0, profit_ratio="0.1", profit_abs="1", is_short=False)
    cases = []
    nonfinite = dict(valid, profit_ratio="NaN")
    cases.append(nonfinite)
    no_funding = dict(valid)
    del no_funding["funding_fees"]
    cases.append(no_funding)
    cases.append(dict(valid, leverage="13.999"))
    cases.append(dict(valid, exit_reason="force_exit"))

    for row in cases:
        with pytest.raises(evaluator.InvalidEvidence):
            evaluator.recompute_trade_metrics([row])


def test_drawdown_uses_complete_decimal_marked_equity_path() -> None:
    path = ["1000", "1200", "900", "1100", "800"]
    assert evaluator.recompute_max_drawdown(path) == Decimal(1) / Decimal(3)
    metrics = evaluator.add_checkpoint_account_metrics(
        evaluator.recompute_trade_metrics([]), path
    )
    assert metrics["net_return"] == Decimal("-0.2")
    with pytest.raises(evaluator.InvalidEvidence, match=r"binary float|exact Decimal"):
        evaluator.recompute_max_drawdown([1000.0, 900.0])


def test_default_cli_is_deterministic_not_ready_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    before = list(tmp_path.iterdir())

    assert evaluator.main([]) == 0
    first = capsys.readouterr().out
    assert evaluator.main([]) == 0
    second = capsys.readouterr().out

    assert first == second
    payload = __import__("json").loads(first)
    assert payload["status"] == evaluator.NOT_READY
    assert payload["performance_read"] is False
    assert payload["subprocess_execution_implemented"] is False
    assert payload["writes"] is False
    assert "no checkpoint force_exit or reset" in payload["continuous_ledger_contract"]
    assert list(tmp_path.iterdir()) == before
