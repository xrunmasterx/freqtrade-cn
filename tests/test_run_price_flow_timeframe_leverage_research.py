from __future__ import annotations

import subprocess

from tools import run_price_flow_timeframe_leverage_research as research


def _passing_metrics(**overrides) -> research.Metrics:
    values = {
        "code": "T15-L2",
        "strategy": "PriceFlowE10Tf15mLev2Strategy",
        "stage": "development",
        "timeframe": "15m",
        "leverage": 2,
        "risk_model": "fixed_account",
        "trades": 40,
        "wins": 18,
        "losses": 22,
        "winrate": 0.45,
        "payoff": 2.5,
        "profit_factor": 2.0,
        "profit_pct": 50.0,
        "drawdown_pct": 8.0,
        "btc_trades": 20,
        "eth_trades": 20,
        "long_trades": 26,
        "short_trades": 14,
        "independent_weeks": 20,
        "profitable_folds": 3,
        "worst_fold_profit_pct": -2.0,
        "min_asset_profit_factor": 1.4,
        "btc_profit_sum_pct": 20.0,
        "eth_profit_sum_pct": 15.0,
        "btc_profit_factor": 1.5,
        "eth_profit_factor": 1.4,
        "top3_gross_profit_share": 0.40,
        "best_month_positive_share": 0.30,
    }
    values.update(overrides)
    return research.Metrics(**values)


def test_preregistration_hash_is_frozen() -> None:
    assert research._sha256(research.PREREGISTRATION) == (
        research.EXPECTED_PREREGISTRATION_SHA256
    )


def test_baseline_matrix_has_four_timeframes_and_five_leverages() -> None:
    specs = research._baseline_specs()

    assert len(specs) == 20
    assert {(spec.timeframe, spec.leverage) for spec in specs} == {
        (timeframe, leverage)
        for timeframe in ("5m", "15m", "30m", "1h")
        for leverage in (1, 2, 3, 5, 10)
    }
    assert all(spec.risk_model == "fixed_account" for spec in specs)


def test_development_gate_requires_sample_quality_and_both_assets() -> None:
    passed = _passing_metrics()
    rejected = _passing_metrics(eth_profit_sum_pct=-1.0)

    assert research._development_gate(passed) == (
        "DEVELOPMENT_SURVIVOR",
        "all frozen development gates passed",
    )
    status, reason = research._development_gate(rejected)
    assert status == "REJECTED_QUALITY"
    assert "ETH profit" in reason


def test_frozen_score_prioritizes_worst_fold_before_total_profit() -> None:
    robust = _passing_metrics(worst_fold_profit_pct=1.0, profit_pct=20.0)
    concentrated = _passing_metrics(worst_fold_profit_pct=-1.0, profit_pct=200.0)

    assert research._score(robust) > research._score(concentrated)


def test_representatives_choose_one_per_timeframe() -> None:
    metrics = [
        _passing_metrics(code="5m-low", timeframe="5m", leverage=1, profit_factor=1.8),
        _passing_metrics(code="5m-high", timeframe="5m", leverage=2, profit_factor=2.2),
        _passing_metrics(code="15m", timeframe="15m", leverage=2),
    ]

    selected = research._timeframe_representatives(metrics)

    assert [item.code for item in selected] == ["5m-high", "15m"]


def test_backtest_command_uses_shared_wallet_pairs_and_freqtrade_root(
    monkeypatch, tmp_path
) -> None:
    observed: dict[str, object] = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(command, 1, "", "load failure")

    monkeypatch.setattr(research, "RESULT_ROOT", tmp_path)
    monkeypatch.setattr(research.subprocess, "run", fake_run)
    spec = research.StrategySpec(
        code="T15-L2",
        strategy="PriceFlowE10Tf15mLev2Strategy",
        timeframe="15m",
        leverage=2,
        risk_model="fixed_account",
        confirmation="original",
    )

    metrics = research._run_backtest(
        spec,
        "development",
        research.DEVELOPMENT_WINDOW,
        research.DEVELOPMENT_FOLDS,
        fee=0.0005,
        resume=False,
    )

    command = observed["command"]
    pair_index = command.index("--pairs")
    assert command[pair_index + 1 : pair_index + 3] == list(research.PAIRS)
    assert observed["cwd"] == research.REPO_ROOT / "freqtrade"
    assert metrics.status == "INVALID_IMPLEMENTATION"
