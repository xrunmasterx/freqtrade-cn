from __future__ import annotations

import pandas as pd

from tools import analyze_price_flow_timeframe_leverage_research as analyze


def test_shared_wallet_months_use_realized_compound_account_path() -> None:
    trades = [
        {
            "close_date": "2025-01-10 00:00:00+00:00",
            "profit_abs": 2.0,
            "profit_ratio": 0.10,
        },
        {
            "close_date": "2025-02-10 00:00:00+00:00",
            "profit_abs": -1.0,
            "profit_ratio": -0.05,
        },
    ]

    result = analyze._shared_wallet_months(
        trades,
        start="20250101",
        end="20250401",
        starting_balance=20.0,
    )

    assert [row["month"] for row in result] == ["2025-01", "2025-02", "2025-03"]
    assert result[0]["start_balance"] == 20.0
    assert result[0]["return_pct"] == 10.0
    assert result[0]["end_balance"] == 22.0
    assert result[1]["return_pct"] == -1 / 22 * 100
    assert result[1]["end_balance"] == 21.0
    assert result[2]["trades"] == 0
    assert result[2]["return_pct"] == 0.0
    assert result[2]["end_balance"] == 21.0


def test_profit_factor_handles_no_loss_month_without_claiming_zero_quality() -> None:
    assert analyze._profit_factor([0.1, 0.2]) == float("inf")
    assert analyze._profit_factor([]) is None
    assert analyze._profit_factor([0.2, -0.1]) == 2.0


def test_month_boundaries_are_end_exclusive() -> None:
    rows = analyze._shared_wallet_months(
        [],
        start="20240701",
        end="20240901",
        starting_balance=20.0,
    )

    assert [pd.Period(row["month"], freq="M") for row in rows] == [
        pd.Period("2024-07", freq="M"),
        pd.Period("2024-08", freq="M"),
    ]


def test_detail_comparison_separates_economic_outcomes_from_exit_timing() -> None:
    baseline = [
        {
            "pair": "BTC/USDT:USDT",
            "open_date": "2025-01-01 00:00:00+00:00",
            "close_date": "2025-01-01 01:00:00+00:00",
            "open_rate": 100.0,
            "close_rate": 102.0,
            "profit_ratio": 0.02,
            "profit_abs": 0.4,
            "is_short": False,
            "enter_tag": "price_acceptance_long",
            "exit_reason": "roi",
            "trade_duration": 60,
        }
    ]
    detail = [
        {
            **baseline[0],
            "close_date": "2025-01-01 01:05:00+00:00",
            "trade_duration": 65,
        }
    ]

    comparison = analyze._detail_comparison(baseline, detail)

    assert comparison == {
        "trade_count_equal": True,
        "economic_outcomes_equal": True,
        "close_timing_equal": False,
        "close_timing_differences": 1,
    }
