import math
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from freqtrade.strategy import stoploss_from_absolute


STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
sys.path.insert(0, str(STRATEGY_DIR))

from LSRICoreStrategy import LSRICoreStrategy  # noqa: E402


class FakeTrade:
    def __init__(self, *, is_short=False, open_rate=100.0, leverage=1.0, custom_data=None):
        self.is_short = is_short
        self.open_rate = open_rate
        self.leverage = leverage
        self.open_date_utc = datetime(2026, 6, 1)
        self._custom_data = custom_data or {}

    def get_custom_data(self, key):
        return self._custom_data.get(key)

    def set_custom_data(self, key, value):
        self._custom_data[key] = value


class FakeDataProvider:
    def __init__(self, dataframe):
        self.dataframe = dataframe

    def get_analyzed_dataframe(self, pair, timeframe):
        return self.dataframe.copy(), None


def assert_close(actual, expected):
    assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12), (
        actual,
        expected,
    )


def test_scheme_a_keeps_initial_stop_at_one_r_long():
    strategy = LSRICoreStrategy(config={})
    trade = FakeTrade(
        open_rate=100.0,
        leverage=20.0,
        custom_data={"initial_stop_rate": 95.0, "risk_rate": 5.0},
    )

    result = strategy.custom_stoploss(
        pair="BTC/USDT:USDT",
        trade=trade,
        current_time=datetime(2026, 6, 1, 1),
        current_rate=105.0,
        current_profit=1.0,
        after_fill=False,
    )

    expected = stoploss_from_absolute(95.0, 105.0, is_short=False, leverage=20.0)
    assert_close(result, expected)


def test_scheme_a_moves_stop_to_point_eight_r_at_one_point_six_r_long():
    strategy = LSRICoreStrategy(config={})
    trade = FakeTrade(
        open_rate=100.0,
        leverage=20.0,
        custom_data={"initial_stop_rate": 95.0, "risk_rate": 5.0},
    )

    result = strategy.custom_stoploss(
        pair="BTC/USDT:USDT",
        trade=trade,
        current_time=datetime(2026, 6, 1, 1),
        current_rate=108.0,
        current_profit=1.6,
        after_fill=False,
    )

    expected = stoploss_from_absolute(104.0, 108.0, is_short=False, leverage=20.0)
    assert_close(result, expected)


def test_scheme_a_keeps_initial_stop_at_one_r_short():
    strategy = LSRICoreStrategy(config={})
    trade = FakeTrade(
        is_short=True,
        open_rate=100.0,
        leverage=15.0,
        custom_data={"initial_stop_rate": 105.0, "risk_rate": 5.0},
    )

    result = strategy.custom_stoploss(
        pair="ETH/USDT:USDT",
        trade=trade,
        current_time=datetime(2026, 6, 1, 1),
        current_rate=95.0,
        current_profit=1.0,
        after_fill=False,
    )

    expected = stoploss_from_absolute(105.0, 95.0, is_short=True, leverage=15.0)
    assert_close(result, expected)


def base_signal_row():
    return {
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.5,
        "volume": 100.0,
        "funding_rate_fr_1h": 0.00005,
        "ret24_1h": 0.005,
        "ema50_slope24_1h": -0.001,
        "dist_ema200_4h": 0.03,
        "dist_ema20_15m": 0.002,
        "dist_vwap_15m": 0.003,
        "atrp_15m": 0.003,
        "ema_spread_1h": 0.006,
        "adx14_15m": 32.0,
        "adx_rising_15m": True,
        "plus_di14_15m": 28.0,
        "minus_di14_15m": 18.0,
        "volume_z20_15m": 2.6,
        "rsi14_15m": 60.0,
        "long_trend_1h": True,
        "long_regime_4h": True,
        "long_pullback_reclaim": True,
        "long_funding_ok": True,
        "long_stop_valid": True,
        "long_risk_pct": 0.0048,
        "long_recent_breakout": True,
        "long_score": 80,
        "short_trend_1h": True,
        "short_regime_4h": True,
        "short_pullback_reject": True,
        "short_funding_ok": True,
        "short_stop_valid": True,
        "short_risk_pct": 0.0048,
        "short_recent_breakdown": True,
        "short_score": 110,
    }


def make_short_signal_row():
    row = base_signal_row()
    row.update(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 98.0,
            "close": 98.5,
            "ret24_1h": -0.005,
            "ema50_slope24_1h": -0.001,
            "dist_ema200_4h": -0.03,
            "dist_ema20_15m": -0.002,
            "dist_vwap_15m": -0.003,
            "plus_di14_15m": 18.0,
            "minus_di14_15m": 28.0,
            "rsi14_15m": 40.0,
        }
    )
    return row


def signal_value(dataframe, column):
    if column not in dataframe:
        return 0
    value = dataframe.loc[0, column]
    return 0 if pd.isna(value) else int(value)


def test_long_a_plus_gate_requires_trend_not_only_score():
    strategy = LSRICoreStrategy(config={})
    row = base_signal_row()
    row["long_trend_1h"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 0


def test_long_a_plus_gate_accepts_all_required_conditions():
    strategy = LSRICoreStrategy(config={})
    row = base_signal_row()
    row["short_score"] = 0
    row["short_pullback_reject"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 1
    assert result.loc[0, "enter_tag"] == "lsri_v2_long_trend"


def test_long_a_plus_gate_rejects_rsi_outside_hard_range():
    strategy = LSRICoreStrategy(config={})
    row = base_signal_row()
    row["rsi14_15m"] = 76.0
    row["short_score"] = 0
    row["short_pullback_reject"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 0


def test_long_a_plus_gate_accepts_moderate_volume():
    strategy = LSRICoreStrategy(config={})
    row = base_signal_row()
    row["volume_z20_15m"] = 1.5
    row["short_score"] = 0
    row["short_pullback_reject"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 1


def test_long_a_plus_gate_rejects_climax_volume():
    strategy = LSRICoreStrategy(config={})
    row = base_signal_row()
    row["volume_z20_15m"] = 3.4
    row["short_score"] = 0
    row["short_pullback_reject"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 0


def test_long_a_plus_gate_accepts_slightly_negative_funding():
    strategy = LSRICoreStrategy(config={})
    row = base_signal_row()
    row["funding_rate_fr_1h"] = -0.00001
    row["short_score"] = 0
    row["short_pullback_reject"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 1


def test_long_a_plus_gate_rejects_crowded_positive_funding():
    strategy = LSRICoreStrategy(config={})
    row = base_signal_row()
    row["funding_rate_fr_1h"] = 0.0002
    row["short_score"] = 0
    row["short_pullback_reject"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 0


def test_long_a_plus_gate_rejects_narrow_risk_distance():
    strategy = LSRICoreStrategy(config={})
    row = base_signal_row()
    row["long_risk_pct"] = 0.0020
    row["short_score"] = 0
    row["short_pullback_reject"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 0


def test_long_a_plus_gate_rejects_wide_risk_distance():
    strategy = LSRICoreStrategy(config={})
    row = base_signal_row()
    row["long_risk_pct"] = 0.0070
    row["short_score"] = 0
    row["short_pullback_reject"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 0


def test_long_a_plus_gate_rejects_missing_prior_breakout():
    strategy = LSRICoreStrategy(config={})
    row = base_signal_row()
    row["long_recent_breakout"] = False
    row["short_score"] = 0
    row["short_pullback_reject"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 0


def test_long_a_plus_gate_rejects_missing_adx_impulse():
    strategy = LSRICoreStrategy(config={})
    row = base_signal_row()
    row["adx_rising_15m"] = False
    row["short_score"] = 0
    row["short_pullback_reject"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 0


def test_long_a_plus_gate_rejects_wrong_di_direction():
    strategy = LSRICoreStrategy(config={})
    row = base_signal_row()
    row["plus_di14_15m"] = 20.0
    row["minus_di14_15m"] = 20.0
    row["short_score"] = 0
    row["short_pullback_reject"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 0


def test_long_a_plus_gate_rejects_bad_candle_quality():
    strategy = LSRICoreStrategy(config={})
    row = base_signal_row()
    row["open"] = 100.0
    row["high"] = 104.0
    row["low"] = 99.0
    row["close"] = 101.0
    row["short_score"] = 0
    row["short_pullback_reject"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 0


def test_long_a_plus_gate_rejects_extended_move():
    strategy = LSRICoreStrategy(config={})
    row = base_signal_row()
    row["ret24_1h"] = 0.04
    row["short_score"] = 0
    row["short_pullback_reject"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 0


def test_long_a_plus_gate_rejects_chop_regime():
    strategy = LSRICoreStrategy(config={})
    row = base_signal_row()
    row["atrp_15m"] = 0.0015
    row["short_score"] = 0
    row["short_pullback_reject"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 0


def test_long_a_plus_gate_ignores_low_score_when_hard_conditions_pass():
    strategy = LSRICoreStrategy(config={})
    row = base_signal_row()
    row["long_score"] = 20
    row["short_score"] = 0
    row["short_pullback_reject"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert signal_value(result, "enter_long") == 1


def test_short_a_plus_gate_requires_pullback_reject_not_only_score():
    strategy = LSRICoreStrategy(config={})
    row = make_short_signal_row()
    row["short_pullback_reject"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "ETH/USDT:USDT"})

    assert signal_value(result, "enter_short") == 0


def test_short_a_plus_gate_accepts_all_required_conditions():
    strategy = LSRICoreStrategy(config={})
    row = make_short_signal_row()
    row["long_score"] = 0
    row["long_pullback_reclaim"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "ETH/USDT:USDT"})

    assert signal_value(result, "enter_short") == 1
    assert result.loc[0, "enter_tag"] == "lsri_v2_short_trend"


def test_short_a_plus_gate_rejects_crowded_negative_funding():
    strategy = LSRICoreStrategy(config={})
    row = make_short_signal_row()
    row["funding_rate_fr_1h"] = -0.0002
    row["long_score"] = 0
    row["long_pullback_reclaim"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "ETH/USDT:USDT"})

    assert signal_value(result, "enter_short") == 0


def test_short_a_plus_gate_ignores_low_score_when_hard_conditions_pass():
    strategy = LSRICoreStrategy(config={})
    row = make_short_signal_row()
    row["short_score"] = 20
    row["long_score"] = 0
    row["long_pullback_reclaim"] = False
    dataframe = pd.DataFrame([row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "ETH/USDT:USDT"})

    assert signal_value(result, "enter_short") == 1


def test_v2_uses_fail_safe_stoploss():
    assert LSRICoreStrategy.stoploss == -0.16


def test_v2_uses_reduced_btc_leverage():
    strategy = LSRICoreStrategy(config={})

    assert (
        strategy.leverage(
            pair="BTC/USDT:USDT",
            current_time=datetime(2026, 6, 1),
            current_rate=100_000,
            proposed_leverage=20,
            max_leverage=20,
            entry_tag="lsri_v2_long_trend",
            side="long",
        )
        == 12.0
    )


def test_v2_uses_reduced_eth_leverage():
    strategy = LSRICoreStrategy(config={})

    assert (
        strategy.leverage(
            pair="ETH/USDT:USDT",
            current_time=datetime(2026, 6, 1),
            current_rate=5_000,
            proposed_leverage=15,
            max_leverage=15,
            entry_tag="lsri_v2_long_trend",
            side="long",
        )
        == 8.0
    )


def test_custom_stake_limits_btc_by_signal_risk_pct():
    strategy = LSRICoreStrategy(config={})
    dataframe = pd.DataFrame(
        [
            {
                "date": datetime(2026, 6, 1, 0, 0),
                "enter_long": 1,
                "long_risk_pct": 0.0068,
                "short_risk_pct": 0.0035,
            },
            {
                "date": datetime(2026, 6, 1, 0, 5),
                "enter_long": 0,
                "long_risk_pct": 0.0035,
                "short_risk_pct": 0.0035,
            },
        ]
    )
    strategy.dp = FakeDataProvider(dataframe)

    result = strategy.custom_stake_amount(
        pair="BTC/USDT:USDT",
        current_time=datetime(2026, 6, 1, 0, 5),
        current_rate=100_000,
        proposed_stake=90.0,
        min_stake=5.0,
        max_stake=90.0,
        leverage=12.0,
        entry_tag="lsri_v2_long_trend",
        side="long",
    )

    expected = (90.0 * strategy.max_account_risk_pct) / (0.0068 * 12.0)
    assert_close(result, expected)


def test_custom_stake_uses_short_signal_risk_pct_for_short_entries():
    strategy = LSRICoreStrategy(config={})
    dataframe = pd.DataFrame(
        [
            {
                "date": datetime(2026, 6, 1, 0, 5),
                "enter_short": 1,
                "long_risk_pct": 0.0200,
                "short_risk_pct": 0.0068,
            }
        ]
    )
    strategy.dp = FakeDataProvider(dataframe)

    result = strategy.custom_stake_amount(
        pair="BTC/USDT:USDT",
        current_time=datetime(2026, 6, 1, 0, 5),
        current_rate=100_000,
        proposed_stake=90.0,
        min_stake=5.0,
        max_stake=90.0,
        leverage=12.0,
        entry_tag="lsri_v2_short_trend",
        side="short",
    )

    expected = (90.0 * strategy.max_account_risk_pct) / (0.0068 * 12.0)
    assert_close(result, expected)


def test_custom_stake_returns_zero_when_risk_limited_stake_is_below_min_stake():
    strategy = LSRICoreStrategy(config={})
    dataframe = pd.DataFrame(
        [
            {
                "date": datetime(2026, 6, 1, 0, 5),
                "long_risk_pct": 0.0068,
                "short_risk_pct": 0.0068,
            }
        ]
    )
    strategy.dp = FakeDataProvider(dataframe)

    result = strategy.custom_stake_amount(
        pair="BTC/USDT:USDT",
        current_time=datetime(2026, 6, 1, 0, 5),
        current_rate=100_000,
        proposed_stake=5.0,
        min_stake=5.0,
        max_stake=5.0,
        leverage=12.0,
        entry_tag="lsri_v2_long_trend",
        side="long",
    )

    assert result == 0


def test_custom_stake_falls_back_to_caps_without_signal_risk_pct():
    strategy = LSRICoreStrategy(config={})

    result = strategy.custom_stake_amount(
        pair="BTC/USDT:USDT",
        current_time=datetime(2026, 6, 1, 0, 5),
        current_rate=100_000,
        proposed_stake=100.0,
        min_stake=5.0,
        max_stake=95.0,
        leverage=12.0,
        entry_tag="lsri_v2_long_trend",
        side="long",
    )

    assert result == 95.0


def test_custom_stake_scales_with_account_size_instead_of_fixed_cap():
    strategy = LSRICoreStrategy(config={})
    dataframe = pd.DataFrame(
        [
            {
                "date": datetime(2026, 6, 1, 0, 5),
                "long_risk_pct": 0.0068,
                "short_risk_pct": 0.0068,
            }
        ]
    )
    strategy.dp = FakeDataProvider(dataframe)

    result = strategy.custom_stake_amount(
        pair="BTC/USDT:USDT",
        current_time=datetime(2026, 6, 1, 0, 5),
        current_rate=100_000,
        proposed_stake=180.0,
        min_stake=5.0,
        max_stake=180.0,
        leverage=12.0,
        entry_tag="lsri_v2_long_trend",
        side="long",
    )

    expected = (180.0 * strategy.max_account_risk_pct) / (0.0068 * 12.0)
    assert result > 90.0
    assert_close(result, expected)


def test_custom_exit_tracks_max_favorable_r():
    strategy = LSRICoreStrategy(config={})
    trade = FakeTrade(
        open_rate=100.0,
        custom_data={
            "initial_stop_rate": 95.0,
            "risk_rate": 5.0,
            "take_profit_rate": 111.0,
            "half_r_rate": 102.5,
        },
    )

    result = strategy.custom_exit(
        pair="BTC/USDT:USDT",
        trade=trade,
        current_time=datetime(2026, 6, 1, 0, 30),
        current_rate=103.0,
        current_profit=0.03,
    )

    assert result is None
    assert_close(trade.get_custom_data("max_favorable_r"), 0.6)


def test_custom_exit_exits_early_when_no_favorable_impulse_long():
    strategy = LSRICoreStrategy(config={})
    trade = FakeTrade(
        open_rate=100.0,
        custom_data={
            "initial_stop_rate": 95.0,
            "risk_rate": 5.0,
            "take_profit_rate": 111.0,
            "half_r_rate": 102.5,
        },
    )

    result = strategy.custom_exit(
        pair="BTC/USDT:USDT",
        trade=trade,
        current_time=datetime(2026, 6, 1, 0, 45),
        current_rate=101.0,
        current_profit=0.01,
    )

    assert result == "early_time_stop_no_impulse"


def test_custom_exit_keeps_trade_when_early_impulse_reached_long():
    strategy = LSRICoreStrategy(config={})
    trade = FakeTrade(
        open_rate=100.0,
        custom_data={
            "initial_stop_rate": 95.0,
            "risk_rate": 5.0,
            "take_profit_rate": 111.0,
            "half_r_rate": 102.5,
            "max_favorable_r": 0.6,
        },
    )

    result = strategy.custom_exit(
        pair="BTC/USDT:USDT",
        trade=trade,
        current_time=datetime(2026, 6, 1, 0, 45),
        current_rate=100.5,
        current_profit=0.005,
    )

    assert result is None


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
            print(f"PASS {name}")
