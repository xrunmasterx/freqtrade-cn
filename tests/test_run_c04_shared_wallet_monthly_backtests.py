from __future__ import annotations

import pytest

from tools import run_c04_shared_wallet_monthly_backtests as shared


def test_windows_cover_36_complete_calendar_months():
    assert len(shared.MONTHS) == 36
    assert shared.MONTHS[0].label == "2023-08"
    assert shared.MONTHS[-1].label == "2026-07"
    assert shared.MONTHS[0].start == "20230801"
    assert shared.MONTHS[-1].end == "20260801"


def test_command_binds_both_pairs_to_one_backtest(tmp_path):
    command = shared._backtest_command(shared.MONTHS[0], tmp_path)

    pair_index = command.index("--pairs")
    assert command[pair_index + 1 : pair_index + 3] == [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
    ]
    assert command[command.index("--timerange") + 1] == "20230801-20230901"
    assert command[command.index("--strategy") + 1] == shared.STRATEGY
    assert command[command.index("--fee") + 1] == "0.0005"
    assert command[command.index("--cache") + 1] == "none"


def test_summary_reports_shared_wallet_and_pair_contributions(tmp_path):
    result = {
        "trades": [
            {
                "pair": "BTC/USDT:USDT",
                "open_date": "2023-08-03 00:00:00+00:00",
                "close_date": "2023-08-03 01:00:00+00:00",
                "profit_ratio": 0.02,
                "profit_abs": 0.36,
                "is_short": False,
                "enter_tag": "ci_c04_core_long",
                "exit_reason": "roi",
                "trade_duration": 60,
                "funding_fees": 0.01,
            },
            {
                "pair": "ETH/USDT:USDT",
                "open_date": "2023-08-20 00:00:00+00:00",
                "close_date": "2023-08-20 02:00:00+00:00",
                "profit_ratio": -0.01,
                "profit_abs": -0.18,
                "is_short": True,
                "enter_tag": "ci_c04_extra_short",
                "exit_reason": "force_exit",
                "trade_duration": 120,
                "funding_fees": -0.02,
            },
        ],
        "results_per_pair": [
            {
                "key": "BTC/USDT:USDT",
                "trades": 1,
                "profit_total_pct": 1.8,
                "profit_total_abs": 0.36,
            },
            {
                "key": "ETH/USDT:USDT",
                "trades": 1,
                "profit_total_pct": -0.9,
                "profit_total_abs": -0.18,
            },
            {
                "key": "TOTAL",
                "trades": 2,
                "profit_total_pct": 0.9,
                "profit_total_abs": 0.18,
                "profit_factor": 2.0,
                "expectancy": 0.09,
            },
        ],
        "starting_balance": 20.0,
        "final_balance": 20.18,
        "max_drawdown_account": 0.0125,
        "max_consecutive_wins": 1,
        "max_consecutive_losses": 1,
        "left_open_trades": [{"key": "TOTAL", "trades": 1}],
        "backtest_start": "2023-08-01 00:00:00",
        "backtest_end": "2023-09-01 00:00:00",
    }
    archive = tmp_path / "result.zip"
    archive.write_bytes(b"test artifact")

    metric = shared._summarize(
        "isolated_month", shared.MONTHS[0], result, archive
    )

    assert metric.trades == 2
    assert metric.winrate_pct == 50.0
    assert metric.profit_pct == 0.9
    assert metric.payoff == 2.0
    assert metric.profit_factor == 2.0
    assert metric.btc_trades == 1
    assert metric.eth_trades == 1
    assert metric.btc_profit_usdt == 0.36
    assert metric.eth_profit_usdt == -0.18
    assert metric.force_exit_trades == 1
    assert metric.left_open_trades == 1
    assert metric.funding_fees_usdt == pytest.approx(-0.01)


def test_continuous_month_attribution_compounds_shared_balance():
    result = {
        "starting_balance": 20.0,
        "final_balance": 22.7,
        "trades": [
            {
                "pair": "BTC/USDT:USDT",
                "open_date": "2023-08-31 23:00:00+00:00",
                "close_date": "2023-09-01 01:00:00+00:00",
                "profit_ratio": 0.10,
                "profit_abs": 2.0,
                "is_short": False,
                "enter_tag": "ci_c04_core_long",
                "exit_reason": "roi",
                "funding_fees": 0.0,
            },
            {
                "pair": "ETH/USDT:USDT",
                "open_date": "2023-09-15 00:00:00+00:00",
                "close_date": "2023-09-15 02:00:00+00:00",
                "profit_ratio": 0.035,
                "profit_abs": 0.7,
                "is_short": True,
                "enter_tag": "ci_c04_extra_short",
                "exit_reason": "roi",
                "funding_fees": 0.0,
            },
        ],
    }

    rows = shared._attribute_continuous_months(result)

    assert rows[0].trades == 0
    assert rows[1].trades == 2
    assert rows[1].btc_trades == 1
    assert rows[1].eth_trades == 1
    assert rows[1].cross_month_trades == 1
    assert rows[1].opening_balance == 20.0
    assert rows[1].closing_balance == pytest.approx(22.7)
    assert rows[1].profit_pct == pytest.approx(13.5)
    assert shared._compound_returns(row.profit_pct for row in rows) == pytest.approx(
        13.5
    )
