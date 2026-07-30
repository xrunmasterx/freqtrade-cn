import sys
from datetime import datetime
from pathlib import Path

import pandas as pd


STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
sys.path.insert(0, str(STRATEGY_DIR))

from QQE4hSupertrendFullStakeStrategy import QQE4hSupertrendFullStakeStrategy  # noqa: E402


def make_ohlcv(rows):
    dates = pd.date_range(datetime(2026, 1, 1), periods=rows, freq="4h")
    close = pd.Series(range(rows), dtype="float64") * 100 + 50_000
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 20,
            "high": close + 100,
            "low": close - 100,
            "close": close,
            "volume": 100.0,
        }
    )


def signal_value(dataframe, row_index, column):
    if column not in dataframe:
        return 0
    value = dataframe.loc[row_index, column]
    numeric_value = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return 0 if pd.isna(numeric_value) else int(numeric_value)


def base_rows():
    return pd.DataFrame(
        [
            {
                "volume": 100.0,
                "supertrend_trend": 1,
                "supertrend_trend_4h": 1,
                "qqe_mod_up": 14.0,
                "qqe_mod_down": pd.NA,
                "qqe_mod_up_state": True,
                "qqe_mod_down_state": False,
            },
            {
                "volume": 100.0,
                "supertrend_trend": 1,
                "supertrend_trend_4h": 1,
                "qqe_mod_up": 15.0,
                "qqe_mod_down": pd.NA,
                "qqe_mod_up_state": True,
                "qqe_mod_down_state": False,
            },
        ]
    )


def test_populate_indicators_adds_4h_supertrend_and_qqe_columns():
    strategy = QQE4hSupertrendFullStakeStrategy(config={})

    result = strategy.populate_indicators(make_ohlcv(120), {"pair": "BTC/USDT:USDT"})

    assert "supertrend_trend" in result.columns
    assert "qqe_mod_up" in result.columns
    assert "qqe_mod_down" in result.columns
    assert "qqe_mod_up_state" in result.columns
    assert "qqe_mod_down_state" in result.columns


def test_enters_long_only_when_4h_supertrend_up_and_qqe_up_crosses_15():
    strategy = QQE4hSupertrendFullStakeStrategy(config={})

    result = strategy.populate_entry_trend(base_rows(), {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, 0, "enter_long") == 0
    assert signal_value(result, 1, "enter_long") == 1
    assert result.loc[1, "enter_tag"] == "4h_qqe_st_full_long"


def test_rejects_long_when_supertrend_is_not_up():
    strategy = QQE4hSupertrendFullStakeStrategy(config={})
    dataframe = base_rows()
    dataframe["supertrend_trend"] = -1

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, 1, "enter_long") == 0


def test_rejects_long_when_4h_supertrend_is_down_even_if_1h_is_up():
    strategy = QQE4hSupertrendFullStakeStrategy(config={})
    dataframe = base_rows()
    dataframe["supertrend_trend"] = 1
    dataframe["supertrend_trend_4h"] = -1

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, 1, "enter_long") == 0


def test_enters_short_only_when_4h_supertrend_down_and_qqe_down_crosses_minus_15():
    strategy = QQE4hSupertrendFullStakeStrategy(config={})
    dataframe = pd.DataFrame(
        [
            {
                "volume": 100.0,
                "supertrend_trend": -1,
                "supertrend_trend_4h": -1,
                "qqe_mod_up": pd.NA,
                "qqe_mod_down": -14.0,
                "qqe_mod_up_state": False,
                "qqe_mod_down_state": True,
            },
            {
                "volume": 100.0,
                "supertrend_trend": -1,
                "supertrend_trend_4h": -1,
                "qqe_mod_up": pd.NA,
                "qqe_mod_down": -15.0,
                "qqe_mod_up_state": False,
                "qqe_mod_down_state": True,
            },
        ]
    )

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, 0, "enter_short") == 0
    assert signal_value(result, 1, "enter_short") == 1
    assert result.loc[1, "enter_tag"] == "4h_qqe_st_full_short"


def test_rejects_short_when_4h_supertrend_is_up_even_if_1h_is_down():
    strategy = QQE4hSupertrendFullStakeStrategy(config={})
    dataframe = pd.DataFrame(
        [
            {
                "volume": 100.0,
                "supertrend_trend": -1,
                "supertrend_trend_4h": 1,
                "qqe_mod_up": pd.NA,
                "qqe_mod_down": -14.0,
                "qqe_mod_up_state": False,
                "qqe_mod_down_state": True,
            },
            {
                "volume": 100.0,
                "supertrend_trend": -1,
                "supertrend_trend_4h": 1,
                "qqe_mod_up": pd.NA,
                "qqe_mod_down": -15.0,
                "qqe_mod_up_state": False,
                "qqe_mod_down_state": True,
            },
        ]
    )

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, 1, "enter_short") == 0


def test_exits_long_only_after_paired_long_entry():
    strategy = QQE4hSupertrendFullStakeStrategy(config={})
    dataframe = pd.DataFrame(
        [
            {
                "volume": 100.0,
                "supertrend_trend": 1,
                "qqe_mod_up": pd.NA,
                "qqe_mod_down": pd.NA,
                "qqe_mod_up_state": True,
                "qqe_mod_down_state": False,
            },
            {
                "volume": 100.0,
                "supertrend_trend": -1,
                "qqe_mod_up": pd.NA,
                "qqe_mod_down": pd.NA,
                "qqe_mod_up_state": True,
                "qqe_mod_down_state": False,
            },
            {
                "volume": 100.0,
                "supertrend_trend": 1,
                "qqe_mod_up": 14.0,
                "qqe_mod_down": pd.NA,
                "qqe_mod_up_state": True,
                "qqe_mod_down_state": False,
            },
            {
                "volume": 100.0,
                "supertrend_trend": 1,
                "qqe_mod_up": 15.0,
                "qqe_mod_down": pd.NA,
                "qqe_mod_up_state": True,
                "qqe_mod_down_state": False,
            },
            {
                "volume": 100.0,
                "supertrend_trend": 1,
                "qqe_mod_up": 16.0,
                "qqe_mod_down": pd.NA,
                "qqe_mod_up_state": False,
                "qqe_mod_down_state": False,
            },
            {
                "volume": 100.0,
                "supertrend_trend": 1,
                "qqe_mod_up": 16.0,
                "qqe_mod_down": pd.NA,
                "qqe_mod_up_state": False,
                "qqe_mod_down_state": False,
            },
        ]
    )

    result = strategy.populate_exit_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, 0, "exit_long") == 0
    assert signal_value(result, 1, "exit_long") == 0
    assert signal_value(result, 2, "exit_long") == 0
    assert signal_value(result, 3, "enter_long") == 1
    assert signal_value(result, 4, "exit_long") == 1
    assert signal_value(result, 5, "exit_long") == 0


def test_exits_long_when_4h_supertrend_turns_down_without_waiting_for_1h_exit():
    strategy = QQE4hSupertrendFullStakeStrategy(config={})
    dataframe = pd.DataFrame(
        [
            {
                "volume": 100.0,
                "supertrend_trend": 1,
                "supertrend_trend_4h": 1,
                "qqe_mod_up": 14.0,
                "qqe_mod_down": pd.NA,
                "qqe_mod_up_state": True,
                "qqe_mod_down_state": False,
            },
            {
                "volume": 100.0,
                "supertrend_trend": 1,
                "supertrend_trend_4h": 1,
                "qqe_mod_up": 15.0,
                "qqe_mod_down": pd.NA,
                "qqe_mod_up_state": True,
                "qqe_mod_down_state": False,
            },
            {
                "volume": 100.0,
                "supertrend_trend": 1,
                "supertrend_trend_4h": -1,
                "qqe_mod_up": 16.0,
                "qqe_mod_down": pd.NA,
                "qqe_mod_up_state": True,
                "qqe_mod_down_state": False,
            },
        ]
    )

    result = strategy.populate_exit_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, 1, "enter_long") == 1
    assert signal_value(result, 2, "exit_long") == 1
    assert result.loc[2, "exit_tag"] == "4h_qqe_st_full_long_exit"


def test_exits_short_only_after_paired_short_entry():
    strategy = QQE4hSupertrendFullStakeStrategy(config={})
    dataframe = pd.DataFrame(
        [
            {
                "volume": 100.0,
                "supertrend_trend": -1,
                "qqe_mod_up": pd.NA,
                "qqe_mod_down": pd.NA,
                "qqe_mod_up_state": False,
                "qqe_mod_down_state": True,
            },
            {
                "volume": 100.0,
                "supertrend_trend": 1,
                "qqe_mod_up": pd.NA,
                "qqe_mod_down": pd.NA,
                "qqe_mod_up_state": False,
                "qqe_mod_down_state": True,
            },
            {
                "volume": 100.0,
                "supertrend_trend": -1,
                "qqe_mod_up": pd.NA,
                "qqe_mod_down": -14.0,
                "qqe_mod_up_state": False,
                "qqe_mod_down_state": True,
            },
            {
                "volume": 100.0,
                "supertrend_trend": -1,
                "qqe_mod_up": pd.NA,
                "qqe_mod_down": -15.0,
                "qqe_mod_up_state": False,
                "qqe_mod_down_state": True,
            },
            {
                "volume": 100.0,
                "supertrend_trend": -1,
                "qqe_mod_up": pd.NA,
                "qqe_mod_down": -16.0,
                "qqe_mod_up_state": False,
                "qqe_mod_down_state": False,
            },
            {
                "volume": 100.0,
                "supertrend_trend": -1,
                "qqe_mod_up": pd.NA,
                "qqe_mod_down": -16.0,
                "qqe_mod_up_state": False,
                "qqe_mod_down_state": False,
            },
        ]
    )

    result = strategy.populate_exit_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, 0, "exit_short") == 0
    assert signal_value(result, 1, "exit_short") == 0
    assert signal_value(result, 2, "exit_short") == 0
    assert signal_value(result, 3, "enter_short") == 1
    assert signal_value(result, 4, "exit_short") == 1
    assert signal_value(result, 5, "exit_short") == 0


def test_exits_short_when_4h_supertrend_turns_up_without_waiting_for_1h_exit():
    strategy = QQE4hSupertrendFullStakeStrategy(config={})
    dataframe = pd.DataFrame(
        [
            {
                "volume": 100.0,
                "supertrend_trend": -1,
                "supertrend_trend_4h": -1,
                "qqe_mod_up": pd.NA,
                "qqe_mod_down": -14.0,
                "qqe_mod_up_state": False,
                "qqe_mod_down_state": True,
            },
            {
                "volume": 100.0,
                "supertrend_trend": -1,
                "supertrend_trend_4h": -1,
                "qqe_mod_up": pd.NA,
                "qqe_mod_down": -15.0,
                "qqe_mod_up_state": False,
                "qqe_mod_down_state": True,
            },
            {
                "volume": 100.0,
                "supertrend_trend": -1,
                "supertrend_trend_4h": 1,
                "qqe_mod_up": pd.NA,
                "qqe_mod_down": -16.0,
                "qqe_mod_up_state": False,
                "qqe_mod_down_state": True,
            },
        ]
    )

    result = strategy.populate_exit_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, 1, "enter_short") == 1
    assert signal_value(result, 2, "exit_short") == 1
    assert result.loc[2, "exit_tag"] == "4h_qqe_st_full_short_exit"


def test_full_stake_three_times_leverage_without_strategy_stoploss():
    strategy = QQE4hSupertrendFullStakeStrategy(config={})

    assert strategy.stoploss == -1.0
    assert strategy.custom_stake_amount(
        pair="BTC/USDT:USDT",
        current_time=datetime(2026, 1, 1),
        current_rate=50_000,
        proposed_stake=10.0,
        min_stake=None,
        max_stake=90.0,
        leverage=3.0,
        entry_tag="4h_qqe_st_full_long",
        side="long",
    ) == 90.0
    assert (
        strategy.leverage(
            pair="BTC/USDT:USDT",
            current_time=datetime(2026, 1, 1),
            current_rate=50_000,
            proposed_leverage=10.0,
            max_leverage=20.0,
            entry_tag="4h_qqe_st_full_long",
            side="long",
        )
        == 3.0
    )
