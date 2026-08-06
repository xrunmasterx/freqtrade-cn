# ruff: noqa: I001

import sys
from pathlib import Path

import pandas as pd


STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
sys.path.insert(0, str(STRATEGY_DIR))

from QQESupertrendDailyRegimeStrategy import QQESupertrendDailyRegimeStrategy


def test_daily_regime_uses_selected_round_five_risk_and_quality_parameters():
    strategy = QQESupertrendDailyRegimeStrategy(config={})

    assert strategy.stoploss == -0.05
    assert strategy.adx_threshold == 15.0
    assert strategy.max_distance_atr == 5.0
    assert strategy.max_4h_trend_age == 72.0
    assert strategy.leverage_value == 2.0


def test_daily_regime_requires_local_4h_and_daily_alignment():
    strategy = QQESupertrendDailyRegimeStrategy(config={})
    dataframe = pd.DataFrame(
        {
            "supertrend_trend": [1, 1, 1, -1],
            "supertrend_trend_4h": [1, 1, -1, -1],
            "supertrend_trend_1d": [1, -1, 1, -1],
        }
    )

    assert strategy._long_regime(dataframe).tolist() == [True, False, False, False]
    assert strategy._short_regime(dataframe).tolist() == [False, False, False, True]
