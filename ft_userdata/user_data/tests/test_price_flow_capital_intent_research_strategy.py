from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
sys.path.insert(0, str(STRATEGY_DIR))

import PriceFlowCapitalIntentResearchStrategy as capital_intent
from PriceFlowCapitalIntentResearchStrategy import (
    PriceFlowCapitalIntent01Strategy,
    PriceFlowCapitalIntent04Strategy,
    PriceFlowCapitalIntent10Strategy,
    PriceFlowCapitalIntent11Strategy,
    PriceFlowCapitalIntent19Strategy,
    PriceFlowCapitalIntent20Strategy,
    PriceFlowCapitalIntentControl,
)
from PriceFlowPositionAccountContinuationStrategy import (
    PriceFlowPositionAccountContinuationStrategy,
)


def _row(**overrides):
    row = {
        "volume": 100.0,
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "ema20": 100.0,
        "rolling_vwap_24h": 100.0,
        "long_retest": False,
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
        "taker_cusum_long_follow": True,
        "taker_cusum_short_follow": False,
        "bin_taker_imbalance": 0.20,
        "bin_taker_lag1": 0.10,
        "bin_taker_lag2": -0.05,
        "bin_oi_change_15m": 0.01,
        "bin_oi_change_15m_z": 1.5,
        "bin_top_position_change_5m": 0.01,
        "bin_top_position_change_2h": 0.03,
        "bin_top_account_change_2h": 0.01,
        "bin_global_account_log_z": 0.0,
        "funding_valid": False,
        "funding_dispersion_z": float("nan"),
        "venue_spread_shock": False,
        "venue_spread_z": 0.0,
        "venue_spread": 0.0,
        "venue_spread_cross_zero": False,
        "bin_price_return_15m": 0.01,
        "opt_dte_1_7_count_1h": 0.0,
        "opt_dte_1_7_urgency_1h": float("nan"),
        "volatility_event": False,
        "long_displacement": False,
        "short_displacement": False,
        "close_location": 0.5,
        "body_atr": 0.5,
    }
    row.update(overrides)
    return row


def _signal(dataframe: pd.DataFrame, column: str, row: int = -1) -> int:
    values = dataframe.get(column, pd.Series(0, index=dataframe.index)).fillna(0)
    return int(values.iloc[row])


def test_all_twenty_candidates_have_literal_discovery_markers() -> None:
    source = Path(capital_intent.__file__).read_text(encoding="utf-8")

    for candidate_id in range(1, 21):
        name = f"PriceFlowCapitalIntent{candidate_id:02d}Strategy"
        assert f"class {name}(" in source
        assert getattr(capital_intent, name).research_id == candidate_id


def test_promoted_position_account_strategy_freezes_c04_semantics() -> None:
    promoted = PriceFlowPositionAccountContinuationStrategy(config={})
    candidate = PriceFlowCapitalIntent04Strategy(config={})
    dataframe = pd.DataFrame(
        [
            _row(bin_top_position_change_2h=0.03, bin_top_account_change_2h=0.01),
            _row(bin_top_position_change_2h=0.01, bin_top_account_change_2h=0.03),
        ]
    )

    promoted_result = promoted.populate_entry_trend(
        dataframe.copy(), {"pair": "BTC/USDT:USDT"}
    )
    candidate_result = candidate.populate_entry_trend(
        dataframe.copy(), {"pair": "BTC/USDT:USDT"}
    )

    assert promoted.research_id == 4
    assert promoted_result[["enter_long", "enter_short"]].equals(
        candidate_result[["enter_long", "enter_short"]]
    )


def test_control_is_fail_closed_when_cross_venue_data_is_invalid() -> None:
    strategy = PriceFlowCapitalIntentControl(config={})

    result = strategy.populate_entry_trend(
        pd.DataFrame([_row(cross_data_valid=False)]),
        {"pair": "BTC/USDT:USDT"},
    )

    assert _signal(result, "enter_long") == 0


def test_c01_requires_oi_addition_for_cusum_extra() -> None:
    strategy = PriceFlowCapitalIntent01Strategy(config={})

    accepted = strategy.populate_entry_trend(
        pd.DataFrame([_row(bin_oi_change_15m=0.01)]),
        {"pair": "BTC/USDT:USDT"},
    )
    rejected = strategy.populate_entry_trend(
        pd.DataFrame([_row(bin_oi_change_15m=-0.01)]),
        {"pair": "BTC/USDT:USDT"},
    )

    assert _signal(accepted, "enter_long") == 1
    assert _signal(rejected, "enter_long") == 0


def test_c04_uses_position_minus_account_change_as_leader_size() -> None:
    strategy = PriceFlowCapitalIntent04Strategy(config={})

    accepted = strategy.populate_entry_trend(
        pd.DataFrame(
            [_row(bin_top_position_change_2h=0.03, bin_top_account_change_2h=0.01)]
        ),
        {"pair": "BTC/USDT:USDT"},
    )
    rejected = strategy.populate_entry_trend(
        pd.DataFrame(
            [_row(bin_top_position_change_2h=0.01, bin_top_account_change_2h=0.03)]
        ),
        {"pair": "BTC/USDT:USDT"},
    )

    assert _signal(accepted, "enter_long") == 1
    assert _signal(rejected, "enter_long") == 0


def test_c10_treats_no_option_print_as_neutral_and_vetoes_opposition() -> None:
    strategy = PriceFlowCapitalIntent10Strategy(config={})

    no_print = strategy.populate_entry_trend(
        pd.DataFrame([_row()]),
        {"pair": "BTC/USDT:USDT"},
    )
    opposed = strategy.populate_entry_trend(
        pd.DataFrame(
            [_row(opt_dte_1_7_count_1h=4, opt_dte_1_7_urgency_1h=-0.20)]
        ),
        {"pair": "BTC/USDT:USDT"},
    )

    assert _signal(no_print, "enter_long") == 1
    assert _signal(opposed, "enter_long") == 0


def test_c11_can_add_absorption_reload_without_cusum() -> None:
    strategy = PriceFlowCapitalIntent11Strategy(config={})
    dataframe = pd.DataFrame(
        [
            _row(
                open=100,
                high=101,
                low=99,
                close=100.5,
                close_location=0.5,
                taker_cusum_long_follow=False,
                bin_taker_imbalance=-0.2,
                bin_taker_lag1=-0.1,
                bin_taker_lag2=0.1,
            ),
            _row(
                open=100.5,
                high=102,
                low=100,
                close=101.5,
                taker_cusum_long_follow=False,
                bin_taker_imbalance=0.2,
                bin_oi_change_15m=0.01,
            ),
        ]
    )

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert _signal(result, "enter_long") == 1
    assert result.iloc[-1]["enter_tag"] == "ci_c11_absorption_long"


def test_c19_delays_event_signal_until_another_acceptance_candle() -> None:
    strategy = PriceFlowCapitalIntent19Strategy(config={})
    dataframe = pd.DataFrame(
        [
            _row(high=101, close=100.8, volatility_event=True),
            _row(
                open=100.8,
                high=102,
                low=100.5,
                close=101.8,
                volatility_event=False,
                taker_cusum_long_follow=False,
            ),
        ]
    )

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert _signal(result.iloc[[0]], "enter_long") == 0
    assert _signal(result.iloc[[1]], "enter_long") == 1
    assert result.iloc[1]["enter_tag"] == "ci_c19_event_delay_long"


def test_c20_requires_price_flow_and_oi_failure_for_normal_exit() -> None:
    strategy = PriceFlowCapitalIntent20Strategy(config={})
    common = {
        "volume": 100.0,
        "close": 99.0,
        "rolling_vwap_24h": 100.0,
        "flow_imbalance_8": -0.2,
        "short_displacement": False,
        "long_displacement": False,
        "bin_taker_imbalance": -0.2,
        "bin_oi_change_15m": 0.01,
    }

    oi_still_adding = strategy.populate_exit_trend(pd.DataFrame([common]), {})
    all_failed = strategy.populate_exit_trend(
        pd.DataFrame([{**common, "bin_oi_change_15m": -0.01}]),
        {},
    )

    assert _signal(oi_still_adding, "exit_long") == 0
    assert _signal(all_failed, "exit_long") == 1
    assert all_failed.iloc[0]["exit_tag"] == "ci_c20_capital_failure_long"
