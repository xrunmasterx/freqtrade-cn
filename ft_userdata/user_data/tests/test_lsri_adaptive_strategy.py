import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
sys.path.insert(0, str(STRATEGY_DIR))

from LSRIAdaptiveStrategy import LSRIAdaptiveStrategy
from LSRICoreStrategy import LSRICoreStrategy
from test_lsri_core_strategy import (
    FakeTrade,
    base_signal_row,
    signal_value,
)


def test_adaptive_profile_is_pair_agnostic():
    strategy = LSRIAdaptiveStrategy(config={})

    for pair in ("SOXL/USDT:USDT", "SKHY/USDT:USDT", "OTHER/USDT:USDT"):
        assert strategy._pair_max_stop_distance(pair) == 0.045
        assert (
            strategy.leverage(
                pair=pair,
                current_time=datetime(2026, 8, 3, tzinfo=timezone.utc),
                current_rate=100,
                proposed_leverage=10,
                max_leverage=10,
                entry_tag="lsri_adaptive_short_trend",
                side="short",
            )
            == 3.0
        )


def test_adaptive_entry_gate_matches_for_soxl_and_skhy():
    strategy = LSRIAdaptiveStrategy(config={})
    row = base_signal_row()
    row.update(
        {
            "long_risk_pct": 0.020,
            "volume_z20_15m": 1.2,
            "dist_ema20_15m": 0.020,
            "dist_vwap_15m": 0.030,
            "ret24_1h": 0.10,
            "dist_ema200_4h": 0.20,
            "atrp_15m": 0.006,
            "adx14_15m": 25.0,
            "short_pullback_reject": False,
        }
    )

    for pair in ("SOXL/USDT:USDT", "SKHY/USDT:USDT"):
        result = strategy.populate_entry_trend(pd.DataFrame([row]), {"pair": pair})

        assert signal_value(result, "enter_long") == 1
        assert result.loc[0, "enter_tag"] == "lsri_adaptive_long_trend"


def test_adaptive_profile_requires_direction_aligned_daily_momentum():
    strategy = LSRIAdaptiveStrategy(config={})
    row = base_signal_row()
    row.update(
        {
            "ret24_1h": -0.01,
            "short_pullback_reject": False,
        }
    )

    result = strategy.populate_entry_trend(
        pd.DataFrame([row]),
        {"pair": "SKHY/USDT:USDT"},
    )

    assert signal_value(result, "enter_long") == 0


def test_adaptive_take_profit_reason_matches_two_r_target_for_skhy():
    strategy = LSRIAdaptiveStrategy(config={})
    trade = FakeTrade(
        open_rate=100.0,
        custom_data={
            "initial_stop_rate": 95.0,
            "risk_rate": 5.0,
            "take_profit_rate": 110.0,
            "half_r_rate": 102.5,
        },
    )

    result = strategy.custom_exit(
        pair="SKHY/USDT:USDT",
        trade=trade,
        current_time=datetime(2026, 8, 3, 1, tzinfo=timezone.utc),
        current_rate=110.0,
        current_profit=0.3,
    )

    assert result == "long_tp_2_0r"


def test_core_strategy_does_not_apply_adaptive_profile_by_pair_name():
    strategy = LSRICoreStrategy(config={})

    assert strategy._pair_max_stop_distance("SOXL/USDT:USDT") == 0.0
    assert strategy._pair_max_stop_distance("SKHY/USDT:USDT") == 0.0
    assert strategy._pair_leverage("SOXL/USDT:USDT") == 1.0
    assert strategy._pair_leverage("SKHY/USDT:USDT") == 1.0


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
            print(f"PASS {name}")
