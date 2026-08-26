# ruff: noqa: E402, S101

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest


STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
sys.path.insert(0, str(STRATEGY_DIR))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from prepare_binance_taker_priceflow_research import build_fifteen_minute
from PriceFlowBinanceTakerConfirmationResearchStrategy import (
    PriceFlowBinanceTakerConfirmationResearchStrategy,
)


def row(**overrides):
    values = {
        "date": pd.Timestamp("2023-06-01T00:00:00Z"),
        "volume": 100.0,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "ema20": 100.0,
        "rolling_vwap_24h": 100.0,
        "long_retest": True,
        "short_retest": False,
        "long_trend_1h": True,
        "short_trend_1h": False,
        "long_regime_4h": True,
        "short_regime_4h": False,
        "flow_imbalance_8": 0.11,
        "flow_imbalance_24": 0.04,
        "return_24h_1h": 0.05,
        "relative_volume": 0.80,
        "close_location": 0.20,
        "body_atr": 0.20,
        "binance_source_complete_time": pd.Timestamp("2023-06-01T00:00:00Z"),
        "constituent_5m_count": 3,
        "binance_taker_improved_long_10m": True,
        "binance_taker_improved_short_10m": False,
    }
    values.update(overrides)
    return values


def signal(frame: pd.DataFrame, column: str) -> int:
    return int(frame.get(column, pd.Series([0])).fillna(0).iloc[-1])


def test_long_requires_base_signal_and_participation_floor() -> None:
    strategy = PriceFlowBinanceTakerConfirmationResearchStrategy(config={})
    accepted = strategy.populate_entry_trend(
        pd.DataFrame([row()]), {"pair": "BTC/USDT:USDT"}
    )
    rejected = strategy.populate_entry_trend(
        pd.DataFrame([row(relative_volume=0.79)]), {"pair": "BTC/USDT:USDT"}
    )
    no_base = strategy.populate_entry_trend(
        pd.DataFrame([row(long_retest=False)]), {"pair": "BTC/USDT:USDT"}
    )

    assert signal(accepted, "enter_long") == 1
    assert signal(rejected, "enter_long") == 0
    assert signal(no_base, "enter_long") == 0


def test_price_acceptance_is_the_alternative_to_taker_improvement() -> None:
    strategy = PriceFlowBinanceTakerConfirmationResearchStrategy(config={})
    previous = row(
        date=pd.Timestamp("2023-05-31T23:45:00Z"),
        long_retest=False,
        high=100.0,
        close=99.5,
        binance_taker_improved_long_10m=False,
    )
    current = row(
        close=101.5,
        high=102.0,
        close_location=0.35,
        body_atr=0.30,
        binance_taker_improved_long_10m=False,
    )

    result = strategy.populate_entry_trend(
        pd.DataFrame([previous, current]), {"pair": "BTC/USDT:USDT"}
    )

    assert signal(result, "enter_long") == 1


def test_incomplete_or_not_fully_lagged_binance_evidence_fails_closed() -> None:
    strategy = PriceFlowBinanceTakerConfirmationResearchStrategy(config={})
    incomplete = strategy.populate_entry_trend(
        pd.DataFrame([row(constituent_5m_count=2)]), {"pair": "BTC/USDT:USDT"}
    )
    too_fresh = strategy.populate_entry_trend(
        pd.DataFrame(
            [
                row(
                    binance_source_complete_time=pd.Timestamp("2023-06-01T00:05:00Z")
                )
            ]
        ),
        {"pair": "BTC/USDT:USDT"},
    )

    assert signal(incomplete, "enter_long") == 0
    assert signal(too_fresh, "enter_long") == 0


def test_short_rule_is_symmetric() -> None:
    strategy = PriceFlowBinanceTakerConfirmationResearchStrategy(config={})
    dataframe = pd.DataFrame(
        [
            row(
                open=100.0,
                high=101.0,
                low=99.0,
                close=99.5,
                long_retest=False,
                short_retest=True,
                long_trend_1h=False,
                short_trend_1h=True,
                long_regime_4h=False,
                short_regime_4h=True,
                flow_imbalance_8=-0.11,
                flow_imbalance_24=-0.04,
                return_24h_1h=-0.05,
                binance_taker_improved_long_10m=False,
                binance_taker_improved_short_10m=True,
            )
        ]
    )

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal(result, "enter_short") == 1


def test_research_strategy_is_fixed_at_one_x() -> None:
    strategy = PriceFlowBinanceTakerConfirmationResearchStrategy(config={})

    assert strategy.research_only is True
    assert (
        strategy.leverage(
            pair="BTC/USDT:USDT",
            current_time=datetime(2023, 6, 1, tzinfo=UTC),
            current_rate=27_000,
            proposed_leverage=10,
            max_leverage=100,
            entry_tag=None,
            side="long",
        )
        == 1.0
    )


def test_complete_15m_bucket_compares_constituents_ten_minutes_apart_then_lags() -> None:
    dates = pd.date_range("2023-06-01T00:00:00Z", periods=6, freq="5min")
    five = pd.DataFrame(
        {
            "date": dates,
            "volume": [10.0] * 6,
            "taker_buy_volume": [4.0, 5.0, 6.0, 6.0, 5.0, 4.0],
        }
    )

    result = build_fifteen_minute(five)

    assert result["constituent_5m_count"].tolist() == [3, 3]
    assert result["binance_taker_improved_long_10m"].tolist() == [True, False]
    assert result["binance_taker_improved_short_10m"].tolist() == [False, True]
    assert result["source_complete_time"].tolist() == [
        pd.Timestamp("2023-06-01T00:15:00Z"),
        pd.Timestamp("2023-06-01T00:30:00Z"),
    ]
    assert result["date"].equals(result["source_complete_time"])
    assert (
        result["decision_time"] - result["source_complete_time"]
    ).dt.total_seconds().tolist() == [900.0, 900.0]


def test_lagged_sidecar_excludes_decisions_at_or_after_2025_boundary() -> None:
    dates = pd.date_range("2024-12-31T23:15:00Z", periods=9, freq="5min")
    five = pd.DataFrame(
        {
            "date": dates,
            "volume": [10.0] * 9,
            "taker_buy_volume": [5.0] * 9,
        }
    )

    result = build_fifteen_minute(five)

    assert result["decision_time"].tolist() == [pd.Timestamp("2024-12-31T23:45:00Z")]
    assert result["decision_time"].lt(pd.Timestamp("2025-01-01T00:00:00Z")).all()


def test_sidecar_contract_rejects_misaligned_publication_metadata() -> None:
    five = pd.DataFrame(
        {
            "date": pd.date_range("2023-06-01T00:00:00Z", periods=3, freq="5min"),
            "volume": [10.0, 10.0, 10.0],
            "taker_buy_volume": [4.0, 5.0, 6.0],
        }
    )
    sidecar = build_fifteen_minute(five)
    strategy_frame = pd.DataFrame(
        {"date": [pd.Timestamp("2023-06-01T00:15:00Z")]}
    )

    for column, invalid in (
        ("decision_time", pd.Timestamp("2023-06-01T00:15:00Z")),
        ("source_complete_time", pd.Timestamp("2023-06-01T00:10:00Z")),
        ("bucket_open", pd.Timestamp("2023-06-01T00:05:00Z")),
        ("publication_lag_minutes", 0),
        ("constituent_5m_count", 2),
    ):
        contradictory = sidecar.copy()
        contradictory.loc[0, column] = invalid
        with pytest.raises(ValueError):
            PriceFlowBinanceTakerConfirmationResearchStrategy._merge_binance_sidecar(
                strategy_frame, contradictory
            )


def test_sidecar_contract_accepts_exactly_one_lagged_complete_bucket() -> None:
    five = pd.DataFrame(
        {
            "date": pd.date_range("2023-06-01T00:00:00Z", periods=3, freq="5min"),
            "volume": [10.0, 10.0, 10.0],
            "taker_buy_volume": [4.0, 5.0, 6.0],
        }
    )
    sidecar = build_fifteen_minute(five)
    strategy_frame = pd.DataFrame(
        {"date": [pd.Timestamp("2023-06-01T00:15:00Z")]}
    )

    merged = PriceFlowBinanceTakerConfirmationResearchStrategy._merge_binance_sidecar(
        strategy_frame, sidecar
    )

    assert merged["binance_source_complete_time"].iloc[0] == pd.Timestamp(
        "2023-06-01T00:15:00Z"
    )
    assert merged["binance_decision_time"].iloc[0] == pd.Timestamp(
        "2023-06-01T00:30:00Z"
    )


def test_research_strategy_rejects_a_decision_at_the_2025_boundary() -> None:
    strategy = PriceFlowBinanceTakerConfirmationResearchStrategy(config={})
    frame = pd.DataFrame(
        {
            "date": [pd.Timestamp("2024-12-31T23:45:00Z")],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [1.0],
        }
    )

    with pytest.raises(ValueError, match="2025"):
        strategy.populate_indicators(frame, {"pair": "BTC/USDT:USDT"})
