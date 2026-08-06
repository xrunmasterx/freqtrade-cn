from __future__ import annotations

import subprocess

from tools import run_price_flow_event_adaptive_research as research


def test_preregistration_hash_is_frozen() -> None:
    assert research._sha256(research.PREREGISTRATION) == research.EXPECTED_PREREGISTRATION_SHA256


def test_candidate_strategy_names_are_stable() -> None:
    assert research._strategy_name(1) == "PriceFlowEventAdaptive01Strategy"
    assert research._strategy_name(20) == "PriceFlowEventAdaptive20Strategy"


def test_development_gate_rewards_winrate_and_payoff_without_small_samples() -> None:
    baseline = research.Metrics(
        code="C04",
        strategy="PriceFlowEventAdaptiveControl",
        window="development",
        trades=111,
        wins=43,
        losses=68,
        winrate=43 / 111,
        payoff=2.51,
        profit_factor=1.60,
        profit_pct=84.0,
        drawdown_pct=10.2,
    )
    candidate = research.Metrics(
        code="E01",
        strategy="PriceFlowEventAdaptive01Strategy",
        window="development",
        trades=90,
        wins=40,
        losses=50,
        winrate=40 / 90,
        payoff=2.50,
        profit_factor=1.85,
        profit_pct=90.0,
        drawdown_pct=9.0,
        btc_trades=55,
        eth_trades=35,
        long_trades=60,
        short_trades=30,
        btc_long=35,
        btc_short=20,
        eth_long=25,
        eth_short=10,
        independent_weeks=30,
        profitable_folds=3,
        worst_fold_profit_pct=-5.0,
        min_asset_profit_factor=1.20,
        top3_gross_profit_share=0.30,
        best_month_positive_share=0.20,
    )

    status, reason = research._development_gate(candidate, baseline)

    assert status == "DEVELOPMENT_POINT_SURVIVOR"
    assert reason == "all frozen development gates passed"


def test_expansion_diagnostic_requires_more_trades_without_quality_collapse() -> None:
    baseline = research.Metrics(
        code="C04",
        strategy="PriceFlowEventAdaptiveControl",
        window="development",
        trades=100,
        winrate=0.40,
        payoff=2.50,
        profit_factor=1.60,
        drawdown_pct=8.0,
    )
    candidate = research.Metrics(
        code="E11",
        strategy="PriceFlowEventAdaptive11Strategy",
        window="development",
        trades=111,
        winrate=0.395,
        payoff=2.35,
        profit_factor=1.61,
        drawdown_pct=9.0,
    )

    assert research._is_expansion_diagnostic(candidate, baseline)


def test_backtest_runs_from_freqtrade_package_root(monkeypatch, tmp_path) -> None:
    observed: dict[str, object] = {}

    def fake_run(command, **kwargs):
        observed["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(command, 1, "", "load failure")

    monkeypatch.setattr(research, "RESULT_ROOT", tmp_path)
    monkeypatch.setattr(research.subprocess, "run", fake_run)

    metrics = research._run_backtest(
        "PriceFlowEventAdaptiveControl",
        "C04",
        "development",
        research.DEVELOPMENT_WINDOW,
        research.DEVELOPMENT_FOLDS,
        fee=0.0005,
        resume=False,
    )

    assert observed["cwd"] == research.REPO_ROOT / "freqtrade"
    assert metrics.status == "INVALID_IMPLEMENTATION"
