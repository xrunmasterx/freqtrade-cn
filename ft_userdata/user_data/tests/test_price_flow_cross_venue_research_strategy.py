
import sys
from pathlib import Path

import pandas as pd

STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
sys.path.insert(0, str(STRATEGY_DIR))

import PriceFlowCrossVenueResearchStrategy as research_strategy
from PriceFlowCrossVenueResearchStrategy import (
    PriceFlowCrossVenue01Strategy,
    PriceFlowCrossVenue13Strategy,
    PriceFlowCrossVenue23Strategy,
    PriceFlowCrossVenue38Strategy,
    PriceFlowCrossVenueControl,
)


def test_all_frozen_candidates_are_discoverable_by_freqtrade_resolver():
    source = Path(research_strategy.__file__).read_text(encoding="utf-8")

    for candidate_id in range(1, 51):
        name = f"PriceFlowCrossVenue{candidate_id:02d}Strategy"
        assert f"class {name}(" in source
        assert getattr(research_strategy, name).candidate_id == candidate_id


def _entry_row(**overrides):
    row = {
        "volume": 100.0,
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "ema20": 100.0,
        "rolling_vwap_24h": 100.0,
        "long_retest": True,
        "short_retest": False,
        "long_breakout_level": 100.0,
        "short_breakout_level": 99.0,
        "long_trend_1h": True,
        "short_trend_1h": False,
        "long_regime_4h": True,
        "short_regime_4h": False,
        "flow_imbalance_8": 0.11,
        "flow_imbalance_24": 0.04,
        "return_24h_1h": 0.05,
        "cross_data_valid": True,
        "bin_taker_imbalance": 0.2,
        "opt_otm_count_1h": 0,
        "opt_otm_flow_1h": float("nan"),
        "bin_breakout_long_current_15m": False,
        "bin_breakout_short_current_15m": False,
        "liquidation_long_shock": False,
        "liquidation_short_shock": False,
    }
    row.update(overrides)
    return row


def _signal(dataframe, column):
    return int(dataframe.get(column, pd.Series([0])).fillna(0).iloc[0])


def test_control_does_not_turn_sidecar_health_into_an_entry_filter():
    strategy = PriceFlowCrossVenueControl(config={})

    result = strategy.populate_entry_trend(
        pd.DataFrame([_entry_row(cross_data_valid=False)]),
        {"pair": "BTC/USDT:USDT"},
    )

    assert _signal(result, "enter_long") == 1


def test_b01_requires_last_closed_binance_taker_direction():
    strategy = PriceFlowCrossVenue01Strategy(config={})

    accepted = strategy.populate_entry_trend(
        pd.DataFrame([_entry_row(bin_taker_imbalance=0.1)]),
        {"pair": "BTC/USDT:USDT"},
    )
    rejected = strategy.populate_entry_trend(
        pd.DataFrame([_entry_row(bin_taker_imbalance=-0.1)]),
        {"pair": "BTC/USDT:USDT"},
    )

    assert _signal(accepted, "enter_long") == 1
    assert _signal(rejected, "enter_long") == 0


def test_d13_treats_no_option_print_as_no_opinion_but_vetoes_opposition():
    strategy = PriceFlowCrossVenue13Strategy(config={})

    no_print = strategy.populate_entry_trend(
        pd.DataFrame([_entry_row(opt_otm_count_1h=0, opt_otm_flow_1h=float("nan"))]),
        {"pair": "BTC/USDT:USDT"},
    )
    opposed = strategy.populate_entry_trend(
        pd.DataFrame([_entry_row(opt_otm_count_1h=5, opt_otm_flow_1h=-0.2)]),
        {"pair": "BTC/USDT:USDT"},
    )

    assert _signal(no_print, "enter_long") == 1
    assert _signal(opposed, "enter_long") == 0


def test_x23_can_add_a_binance_lead_entry_without_a_core_retest():
    strategy = PriceFlowCrossVenue23Strategy(config={})
    row = _entry_row(
        long_retest=False,
        bin_breakout_long_current_15m=True,
        close=103.0,
        high=103.0,
    )
    dataframe = pd.DataFrame([_entry_row(), row])

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert _signal(result.iloc[[1]].reset_index(drop=True), "enter_long") == 1
    assert result.loc[1, "enter_tag"] == "cv_x23_extra_long"


def test_a38_vetoes_same_direction_liquidation_shock_proxy():
    strategy = PriceFlowCrossVenue38Strategy(config={})

    result = strategy.populate_entry_trend(
        pd.DataFrame([_entry_row(liquidation_long_shock=True)]),
        {"pair": "ETH/USDT:USDT"},
    )

    assert _signal(result, "enter_long") == 0
