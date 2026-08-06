# ruff: noqa: I001

import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd


STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
sys.path.insert(0, str(STRATEGY_DIR))

from QQESupertrendStrategy import QQESupertrendStrategy


class FakeDataProvider:
    def __init__(self, informative_4h):
        self.informative_4h = informative_4h

    def current_whitelist(self):
        return ["BTC/USDT:USDT", "ETH/USDT:USDT"]

    def get_pair_dataframe(self, pair, timeframe):
        assert pair == "BTC/USDT:USDT"
        assert timeframe == "4h"
        return self.informative_4h.copy()


def make_ohlcv(rows, timeframe="1h"):
    dates = pd.date_range(datetime(2026, 1, 1, tzinfo=UTC), periods=rows, freq=timeframe)
    close = pd.Series(range(rows), dtype="float64") * 10 + 50_000
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 20,
            "high": close + 80,
            "low": close - 80,
            "close": close,
            "volume": 100.0,
        }
    )

def signal_value(dataframe, column):
    if column not in dataframe:
        return 0
    value = dataframe.loc[0, column]
    return 0 if pd.isna(value) else int(value)


def base_signal_row():
    return {
        "close": 101.0,
        "volume": 100.0,
        "supertrend_trend": 1,
        "supertrend_trend_4h": 1,
        "supertrend_trend_age_4h": 1.0,
        "supertrend_up": 100.0,
        "supertrend_down": pd.NA,
        "adx_14": 20.0,
        "supertrend_distance_atr": 1.0,
        "supertrend_buy_signal": pd.NA,
        "supertrend_sell_signal": pd.NA,
        "qqe_mod_up_event": True,
        "qqe_mod_down_event": False,
    }


def test_informative_pairs_requests_4h_supertrend_context():
    strategy = QQESupertrendStrategy(
        config={"exchange": {"pair_whitelist": ["BTC/USDT:USDT", "ETH/USDT:USDT"]}}
    )

    assert strategy.informative_pairs() == [
        ("BTC/USDT:USDT", "4h"),
        ("ETH/USDT:USDT", "4h"),
    ]


def test_populate_indicators_adds_1h_qqe_and_4h_supertrend_columns():
    strategy = QQESupertrendStrategy(config={})
    strategy.dp = FakeDataProvider(make_ohlcv(80, "4h"))

    result = strategy.populate_indicators(
        make_ohlcv(160, "1h"),
        {"pair": "BTC/USDT:USDT"},
    )

    assert "qqe_mod_up_event" in result.columns
    assert "qqe_mod_down_event" in result.columns
    assert "supertrend_trend" in result.columns
    assert "supertrend_trend_4h" in result.columns
    assert "supertrend_trend_age_4h" in result.columns
    assert "adx_14" in result.columns
    assert "supertrend_distance_atr" in result.columns


def test_strategy_supertrend_columns_mark_direction_changes():
    dataframe = pd.DataFrame(
        {
            "close": [100.0, 101.0, 99.0, 98.0],
            "supertrend_up": [pd.NA, 95.0, pd.NA, pd.NA],
            "supertrend_down": [pd.NA, pd.NA, 105.0, 104.0],
        }
    )

    result = QQESupertrendStrategy._add_strategy_supertrend_columns(dataframe)

    assert result["supertrend_trend"].tolist()[1:] == [1.0, -1.0, -1.0]
    assert pd.isna(result.loc[1, "supertrend_buy_signal"])
    assert result.loc[2, "supertrend_sell_signal"] == 99.0
    assert result.loc[2, "supertrend_change"] == -2.0


def test_entry_requires_4h_supertrend_and_1h_qqe_up_event_for_long():
    strategy = QQESupertrendStrategy(config={})
    dataframe = pd.DataFrame([base_signal_row()])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 1
    assert result.loc[0, "enter_tag"] == "qqe_st_long"


def test_entry_rejects_long_when_4h_supertrend_is_not_bullish():
    strategy = QQESupertrendStrategy(config={})
    row = base_signal_row()
    row["supertrend_trend_4h"] = -1
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 0


def test_entry_rejects_signal_outside_quality_limits():
    strategy = QQESupertrendStrategy(config={})
    row = base_signal_row()
    row["adx_14"] = 10.0
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 0


def test_entry_requires_4h_supertrend_and_1h_qqe_down_event_for_short():
    strategy = QQESupertrendStrategy(config={})
    row = base_signal_row()
    row.update(
        {
            "close": 99.0,
            "supertrend_trend": -1,
            "supertrend_trend_4h": -1,
            "supertrend_up": pd.NA,
            "supertrend_down": 100.0,
            "qqe_mod_up_event": False,
            "qqe_mod_down_event": True,
        }
    )
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_short") == 1
    assert result.loc[0, "enter_tag"] == "qqe_st_short"


def test_exit_long_on_supertrend_reversal_or_opposite_qqe_event():
    strategy = QQESupertrendStrategy(config={})
    row = base_signal_row()
    row["qqe_mod_up_event"] = False
    row["qqe_mod_down_event"] = True
    dataframe = pd.DataFrame([row])

    result = strategy.populate_exit_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "exit_long") == 1
    assert result.loc[0, "exit_tag"] == "qqe_st_long_exit"


def test_exit_short_when_price_breaks_above_supertrend_down():
    strategy = QQESupertrendStrategy(config={})
    row = base_signal_row()
    row.update(
        {
            "close": 102.0,
            "supertrend_down": 100.0,
            "supertrend_buy_signal": pd.NA,
            "qqe_mod_up_event": False,
        }
    )
    dataframe = pd.DataFrame([row])

    result = strategy.populate_exit_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "exit_short") == 1
    assert result.loc[0, "exit_tag"] == "qqe_st_short_exit"


def test_strategy_uses_cooldown_without_position_adjustment():
    strategy = QQESupertrendStrategy(config={})

    assert strategy.can_short is True
    assert strategy.position_adjustment_enable is False
    assert strategy.protections == [{"method": "CooldownPeriod", "stop_duration_candles": 3}]
    assert (
        strategy.leverage(
            pair="BTC/USDT:USDT",
            current_time=datetime(2026, 1, 1, tzinfo=UTC),
            current_rate=50_000,
            proposed_leverage=10.0,
            max_leverage=20.0,
            entry_tag="qqe_st_long",
            side="long",
        )
        == 2.0
    )
