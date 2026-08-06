from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tools import run_c04_monthly_backtests as monthly


def test_month_windows_cover_36_contiguous_calendar_months():
    assert len(monthly.MONTHS) == 36
    assert monthly.MONTHS[0].label == "2023-08"
    assert monthly.MONTHS[0].start == "20230801"
    assert monthly.MONTHS[-1].label == "2026-07"
    assert monthly.MONTHS[-1].end == "20260801"
    assert all(
        current.end == following.start
        for current, following in zip(
            monthly.MONTHS[:-1], monthly.MONTHS[1:], strict=True
        )
    )


def test_backtest_command_is_single_asset_uncached_and_uses_c04(tmp_path):
    command = monthly._backtest_command("ETH", monthly.MONTHS[0], tmp_path)

    assert command[command.index("--strategy") + 1] == monthly.STRATEGY
    assert command[command.index("--pairs") + 1] == "ETH/USDT:USDT"
    assert command[command.index("--timerange") + 1] == "20230801-20230901"
    assert command[command.index("--fee") + 1] == "0.0005"
    assert command[command.index("--cache") + 1] == "none"


def test_summary_reports_monthly_account_and_trade_metrics(tmp_path):
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
                "pair": "BTC/USDT:USDT",
                "open_date": "2023-08-30 00:00:00+00:00",
                "close_date": "2023-08-31 23:45:00+00:00",
                "profit_ratio": -0.01,
                "profit_abs": -0.18,
                "is_short": True,
                "enter_tag": "ci_c04_extra_short",
                "exit_reason": "force_exit",
                "trade_duration": 2865,
                "funding_fees": -0.02,
            },
        ],
        "results_per_pair": [
            {
                "key": "TOTAL",
                "profit_total_pct": 0.9,
                "profit_total_abs": 0.18,
                "profit_factor": 2.0,
                "expectancy": 0.09,
            }
        ],
        "starting_balance": 20.0,
        "final_balance": 20.18,
        "max_drawdown_account": 0.0125,
        "max_consecutive_wins": 1,
        "max_consecutive_losses": 1,
        "rejected_signals": 3,
        "left_open_trades": [{"key": "TOTAL", "trades": 1}],
        "backtest_start": "2023-08-01 00:00:00",
        "backtest_end": "2023-09-01 00:00:00",
    }
    archive = tmp_path / "result.zip"
    archive.write_bytes(b"test artifact")

    metric = monthly._summarize(
        "isolated_month",
        "BTC",
        monthly.MONTHS[0],
        result,
        archive,
        cross_valid_pct=99.5,
    )

    assert metric.trades == 2
    assert metric.wins == 1
    assert metric.losses == 1
    assert metric.winrate_pct == 50.0
    assert metric.profit_pct == 0.9
    assert metric.payoff == 2.0
    assert metric.profit_factor == 2.0
    assert metric.max_drawdown_pct == 1.25
    assert metric.long_trades == 1
    assert metric.short_trades == 1
    assert metric.force_exit_trades == 1
    assert metric.left_open_trades == 1
    assert metric.funding_fees_usdt == pytest.approx(-0.01)
    assert metric.exit_reason_counts == {"roi": 1, "force_exit": 1}
    assert metric.cross_valid_pct == 99.5


def test_continuous_month_attribution_compounds_to_final_balance():
    result = {
        "starting_balance": 20.0,
        "final_balance": 21.8,
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
            },
            {
                "pair": "BTC/USDT:USDT",
                "open_date": "2023-09-15 00:00:00+00:00",
                "close_date": "2023-09-15 02:00:00+00:00",
                "profit_ratio": -0.01,
                "profit_abs": -0.2,
                "is_short": True,
                "enter_tag": "ci_c04_extra_short",
                "exit_reason": "flow_invalidated_short",
            },
        ],
    }

    rows = monthly._attribute_continuous_months("BTC", result)
    august, september = rows[0], rows[1]

    assert august.trades == 0
    assert august.profit_pct == 0.0
    assert september.trades == 2
    assert september.cross_month_trades == 1
    assert september.opening_balance == 20.0
    assert september.closing_balance == pytest.approx(21.8)
    assert september.profit_pct == pytest.approx(9.0)
    compounded = monthly._compound_returns([row.profit_pct for row in rows])
    assert compounded == pytest.approx(9.0)


def test_continuous_attribution_uses_utc_calendar_boundaries():
    timestamp = monthly._parse_utc("2023-09-01 00:00:00+00:00")

    assert timestamp == datetime(2023, 9, 1, tzinfo=timezone.utc)
