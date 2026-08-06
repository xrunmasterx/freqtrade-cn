from __future__ import annotations

import subprocess

from tools import run_price_flow_capital_intent_research as research


def test_preregistration_hash_is_frozen() -> None:
    assert research._sha256(research.PREREGISTRATION) == research.EXPECTED_PREREGISTRATION_SHA256


def test_candidate_strategy_names_are_stable() -> None:
    assert research._strategy_name(1) == "PriceFlowCapitalIntent01Strategy"
    assert research._strategy_name(20) == "PriceFlowCapitalIntent20Strategy"


def test_fold_metrics_use_trade_open_time_and_preserve_empty_folds() -> None:
    trades = [
        {"open_date": "2023-08-10 00:00:00+00:00", "profit_ratio": 0.10},
        {"open_date": "2023-09-10 00:00:00+00:00", "profit_ratio": -0.05},
        {"open_date": "2024-03-10 00:00:00+00:00", "profit_ratio": 0.02},
    ]

    folds = research._fold_metrics(trades, research.DEVELOPMENT_FOLDS)

    assert list(folds) == ["F1", "F2", "F3", "F4"]
    assert folds["F1"]["trades"] == 2
    assert folds["F1"]["profit_sum_pct"] == 5.0
    assert folds["F1"]["profit_factor"] == 2.0
    assert folds["F2"]["trades"] == 1
    assert folds["F3"]["trades"] == 0


def test_development_gate_checks_frozen_increment_and_stability() -> None:
    baseline = research.Metrics(
        code="C00",
        strategy="PriceFlowCapitalIntentControl",
        window="development",
        trades=80,
        wins=30,
        losses=50,
        winrate=0.375,
        payoff=2.0,
        breakeven_winrate=1 / 3,
        profit_factor=1.30,
        expectancy=0.01,
        profit_pct=10.0,
        drawdown_pct=8.0,
    )
    candidate = research.Metrics(
        code="C01",
        strategy="PriceFlowCapitalIntent01Strategy",
        window="development",
        trades=90,
        wins=38,
        losses=52,
        winrate=0.4223,
        payoff=2.10,
        breakeven_winrate=1 / 3.10,
        profit_factor=1.50,
        expectancy=0.01,
        profit_pct=14.0,
        drawdown_pct=9.0,
        btc_trades=45,
        eth_trades=45,
        long_trades=65,
        short_trades=25,
        btc_long=30,
        btc_short=15,
        eth_long=35,
        eth_short=10,
        independent_weeks=40,
        profitable_folds=3,
        worst_fold_profit_pct=-5.0,
        top3_gross_profit_share=0.50,
        best_month_positive_share=0.40,
    )

    status, reason = research._development_gate(candidate, baseline)

    assert status == "DEVELOPMENT_POINT_SURVIVOR"
    assert reason == "all frozen development gates passed"


def test_backtest_runs_from_freqtrade_package_root(monkeypatch, tmp_path) -> None:
    observed: dict[str, object] = {}

    def fake_run(command, **kwargs):
        observed["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(command, 1, "", "load failure")

    monkeypatch.setattr(research, "RESULT_ROOT", tmp_path)
    monkeypatch.setattr(research.subprocess, "run", fake_run)

    metrics = research._run_backtest(
        "PriceFlowCapitalIntentControl",
        "C00",
        "development",
        research.DEVELOPMENT_WINDOW,
        research.DEVELOPMENT_FOLDS,
        resume=False,
    )

    assert observed["cwd"] == research.REPO_ROOT / "freqtrade"
    assert metrics.status == "INVALID_IMPLEMENTATION"
