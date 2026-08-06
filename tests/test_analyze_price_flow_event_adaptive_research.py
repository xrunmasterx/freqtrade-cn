from __future__ import annotations

import pandas as pd

from tools import analyze_price_flow_event_adaptive_research as audit


def test_trade_summary_reports_winrate_payoff_and_profit_factor() -> None:
    summary = audit.trade_summary(pd.Series([0.06, 0.03, -0.02, -0.01]))

    assert summary["trades"] == 4
    assert summary["winrate_pct"] == 50.0
    assert summary["payoff"] == 3.0
    assert summary["profit_factor"] == 3.0
    assert summary["profit_sum_pct"] == 6.0


def test_trigger_labels_are_directional() -> None:
    frame = pd.DataFrame(
        {
            "is_short": [False, True, False],
            "ci_price_accept_long": [True, False, False],
            "ci_price_accept_short": [False, False, False],
            "bin_taker_imbalance": [0.2, -0.3, 0.1],
            "bin_taker_lag2": [0.1, -0.2, 0.2],
        }
    )

    assert audit.trigger_labels(frame).tolist() == ["both", "fresh_flow_only", "neither"]


def test_continuous_wallet_monthly_uses_one_shared_compounding_path() -> None:
    wallet = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2024-01-01T00:15:00Z",
                    "2024-01-31T23:45:00Z",
                    "2024-02-29T23:45:00Z",
                    "2024-03-01T00:00:00Z",
                ]
            ),
            "total_quote": [20.0, 22.0, 19.8, 19.8],
        }
    )
    trades = pd.DataFrame(
        {
            "open_date": pd.to_datetime(["2024-01-05T00:00:00Z"]),
            "close_date": pd.to_datetime(["2024-02-02T00:00:00Z"]),
        }
    )

    rows = audit.continuous_wallet_monthly(
        wallet,
        trades,
        start="2024-01-01",
        end="2024-03-01",
    )

    assert [row["month"] for row in rows] == ["2024-01", "2024-02"]
    assert rows[0]["return_pct"] == 10.0
    assert rows[1]["return_pct"] == -10.0
    assert rows[0]["entries_opened"] == 1
    assert rows[1]["trades_closed"] == 1


def test_result_metrics_uses_wallet_weighted_freqtrade_profit_factor(tmp_path) -> None:
    archive = tmp_path / "result.zip"
    archive.write_bytes(b"result")
    result = {
        "trades": [
            {"profit_ratio": 0.10, "pair": "BTC/USDT:USDT"},
            {"profit_ratio": -0.05, "pair": "BTC/USDT:USDT"},
        ],
        "results_per_pair": [
            {
                "key": "TOTAL",
                "profit_factor": 1.5,
                "profit_total_pct": 10.0,
            }
        ],
        "max_drawdown_account": 0.03,
        "final_balance": 22.0,
    }

    metrics = audit._result_metrics("E10", 0.001, result, archive)

    assert metrics["profit_factor"] == 1.5
