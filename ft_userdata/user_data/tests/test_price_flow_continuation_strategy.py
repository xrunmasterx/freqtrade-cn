# ruff: noqa: I001

import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd


STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
sys.path.insert(0, str(STRATEGY_DIR))

from PriceFlowContinuationStrategy import PriceFlowContinuationStrategy


def entry_row(**overrides):
    row = {
        "volume": 100.0,
        "close": 101.0,
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
    }
    row.update(overrides)
    return row


def signal_value(dataframe, column):
    return int(dataframe.get(column, pd.Series([0])).fillna(0).iloc[0])


def test_strategy_uses_locked_risk_and_flow_parameters():
    strategy = PriceFlowContinuationStrategy(config={})

    assert strategy.stoploss == -0.03
    assert strategy.minimal_roi == {"0": 0.06, "720": 0.04, "1440": 0.02}
    assert strategy.flow_fast_threshold == 0.10
    assert strategy.flow_slow_threshold == 0.03
    assert strategy.max_directional_return_24h == 0.08
    assert strategy.startup_candle_count == 960


def test_strategy_is_pair_agnostic_and_does_not_require_mark_candles():
    strategy = PriceFlowContinuationStrategy(
        config={
            "exchange": {
                "pair_whitelist": ["BTC/USDT:USDT", "ETH/USDT:USDT"],
            }
        }
    )

    assert strategy.informative_pairs() == [
        ("BTC/USDT:USDT", "1h"),
        ("BTC/USDT:USDT", "4h"),
        ("ETH/USDT:USDT", "1h"),
        ("ETH/USDT:USDT", "4h"),
    ]

    for pair in ("BTC/USDT:USDT", "ETH/USDT:USDT"):
        result = strategy.populate_entry_trend(pd.DataFrame([entry_row()]), {"pair": pair})
        assert signal_value(result, "enter_long") == 1
        assert result.loc[0, "enter_tag"] == "price_flow_retest_long"


def test_directional_extension_filter_rejects_a_late_long_entry():
    strategy = PriceFlowContinuationStrategy(config={})
    dataframe = pd.DataFrame([entry_row(return_24h_1h=0.081)])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 0


def test_short_entry_requires_negative_flow_alignment():
    strategy = PriceFlowContinuationStrategy(config={})
    dataframe = pd.DataFrame(
        [
            entry_row(
                close=99.0,
                long_retest=False,
                short_retest=True,
                long_trend_1h=False,
                short_trend_1h=True,
                long_regime_4h=False,
                short_regime_4h=True,
                flow_imbalance_8=-0.11,
                flow_imbalance_24=-0.04,
                return_24h_1h=-0.05,
            )
        ]
    )

    result = strategy.populate_entry_trend(dataframe, {"pair": "ETH/USDT:USDT"})

    assert signal_value(result, "enter_short") == 1
    assert result.loc[0, "enter_tag"] == "price_flow_retest_short"


def test_leverage_is_capped_at_two():
    strategy = PriceFlowContinuationStrategy(config={})

    assert (
        strategy.leverage(
            pair="BTC/USDT:USDT",
            current_time=datetime(2026, 8, 3, tzinfo=UTC),
            current_rate=100_000,
            proposed_leverage=10,
            max_leverage=5,
            entry_tag="price_flow_retest_long",
            side="long",
        )
        == 2.0
    )
