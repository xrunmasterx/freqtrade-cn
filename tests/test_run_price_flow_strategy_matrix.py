from __future__ import annotations

import pytest

from tools import run_price_flow_strategy_matrix as matrix


def test_windows_share_frozen_end_and_run_short_to_long():
    assert [window.label for window in matrix.WINDOWS] == [
        "7d",
        "15d",
        "1m",
        "2m",
        "4m",
        "6m",
        "1y",
        "2y",
        "3y",
        "4y",
        "5y",
    ]
    assert {window.end for window in matrix.WINDOWS} == {"20260801"}
    assert matrix.WINDOWS[0].start == "20260725"
    assert matrix.WINDOWS[-1].start == "20210801"


def test_backtest_command_is_single_asset_and_uncached(tmp_path):
    command = matrix._backtest_command(
        matrix.STRATEGIES[0], "ETH", matrix.WINDOWS[0], tmp_path
    )

    assert command[command.index("--pairs") + 1] == "ETH/USDT:USDT"
    assert command[command.index("--timerange") + 1] == "20260725-20260801"
    assert command[command.index("--fee") + 1] == "0.0005"
    assert command[command.index("--cache") + 1] == "none"


def test_summary_reports_return_winrate_payoff_and_sides(tmp_path):
    result = {
        "trades": [
            {
                "profit_ratio": 0.02,
                "is_short": False,
                "enter_tag": "core_long",
            },
            {
                "profit_ratio": -0.01,
                "is_short": True,
                "enter_tag": "a40_extra_short",
            },
            {
                "profit_ratio": 0.0,
                "is_short": False,
                "enter_tag": "core_long",
            },
        ],
        "results_per_pair": [
            {
                "key": "TOTAL",
                "profit_total_pct": 4.5,
                "profit_total_abs": 0.9,
                "profit_factor": 2.0,
            }
        ],
        "max_drawdown_account": 0.03,
    }

    metric = matrix._summarize(
        matrix.STRATEGIES[0],
        "BTC",
        matrix.WINDOWS[0],
        result,
        tmp_path / "result.zip",
        cross_valid_pct=100.0,
    )

    assert metric.trades == 3
    assert metric.wins == 1
    assert metric.draws == 1
    assert metric.losses == 1
    assert metric.winrate_pct == pytest.approx(100 / 3)
    assert metric.payoff == 2.0
    assert metric.long_trades == 2
    assert metric.short_trades == 1
    assert metric.extra_trades == 1
    assert metric.profit_pct == 4.5
    assert metric.max_drawdown_pct == 3.0


def test_summary_leaves_profit_factor_undefined_without_a_losing_trade(tmp_path):
    result = {
        "trades": [
            {
                "profit_ratio": 0.02,
                "is_short": False,
                "enter_tag": "core_long",
            }
        ],
        "results_per_pair": [
            {
                "key": "TOTAL",
                "profit_total_pct": 3.5,
                "profit_total_abs": 0.7,
                "profit_factor": 0.0,
            }
        ],
        "max_drawdown_account": 0.0,
    }

    metric = matrix._summarize(
        matrix.STRATEGIES[0],
        "BTC",
        matrix.WINDOWS[0],
        result,
        tmp_path / "result.zip",
        cross_valid_pct=100.0,
    )

    assert metric.profit_factor is None
    assert metric.payoff is None
