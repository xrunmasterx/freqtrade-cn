from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
sys.path.insert(0, str(STRATEGY_DIR))

import PriceFlowEventAdaptiveResearchStrategy as event_adaptive
from PriceFlowEventAdaptiveResearchStrategy import (
    PriceFlowEventAdaptive01Strategy,
    PriceFlowEventAdaptive04Strategy,
    PriceFlowEventAdaptive10Strategy,
    PriceFlowEventAdaptive11Strategy,
    PriceFlowEventAdaptive16Strategy,
    PriceFlowEventAdaptive17Strategy,
    PriceFlowEventAdaptive18Strategy,
    PriceFlowEventAdaptive19Strategy,
    PriceFlowEventAdaptive20Strategy,
    PriceFlowEventAdaptiveControl,
)
from PriceFlowParticipationFreshnessStrategy import (
    PriceFlowParticipationFreshnessStrategy,
)
from PriceFlowPositionAccountContinuationStrategy import (
    PriceFlowPositionAccountContinuationStrategy,
)


def _row(**overrides):
    row = {
        "date": pd.Timestamp("2024-02-01 00:00:00Z"),
        "decision_time": pd.Timestamp("2024-02-01 00:15:00Z"),
        "volume": 100.0,
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.5,
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
        "ema50_slope_4h": 0.005,
        "flow_imbalance_8": 0.11,
        "flow_imbalance_24": 0.04,
        "return_24h_1h": 0.05,
        "relative_volume": 1.0,
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
        "minutes_from_cpi": 10_000.0,
        "minutes_from_expiry": 10_000.0,
    }
    row.update(overrides)
    return row


def _signal(dataframe: pd.DataFrame, column: str, row: int = -1) -> int:
    values = dataframe.get(column, pd.Series(0, index=dataframe.index)).fillna(0)
    return int(values.iloc[row])


def _price_accept_frame(**signal_overrides) -> pd.DataFrame:
    signal_values = dict(signal_overrides)
    decision = pd.Timestamp(signal_values.pop("decision_time", "2024-02-01 00:15:00Z"))
    previous = _row(
        date=decision - pd.Timedelta(minutes=30),
        decision_time=decision - pd.Timedelta(minutes=15),
        open=99.5,
        high=100.5,
        low=99.0,
        close=100.0,
        taker_cusum_long_follow=False,
    )
    signal = _row(
        date=decision - pd.Timedelta(minutes=15),
        decision_time=decision,
        **signal_values,
    )
    return pd.DataFrame([previous, signal])


def test_all_twenty_candidates_have_literal_discovery_markers() -> None:
    source = Path(event_adaptive.__file__).read_text(encoding="utf-8")

    for candidate_id in range(1, 21):
        name = f"PriceFlowEventAdaptive{candidate_id:02d}Strategy"
        assert f"class {name}(" in source
        assert getattr(event_adaptive, name).event_id == candidate_id


def test_control_preserves_frozen_c04_entry_semantics() -> None:
    control = PriceFlowEventAdaptiveControl(config={})
    frozen = PriceFlowPositionAccountContinuationStrategy(config={})
    dataframe = pd.DataFrame([_row(), _row(relative_volume=0.5)])

    control_result = control.populate_entry_trend(dataframe.copy(), {"pair": "BTC/USDT:USDT"})
    frozen_result = frozen.populate_entry_trend(dataframe.copy(), {"pair": "BTC/USDT:USDT"})

    assert control_result[["enter_long", "enter_short"]].equals(
        frozen_result[["enter_long", "enter_short"]]
    )


def test_e01_requires_the_preregistered_participation_floor() -> None:
    strategy = PriceFlowEventAdaptive01Strategy(config={})

    accepted = strategy.populate_entry_trend(
        pd.DataFrame([_row(relative_volume=0.80)]),
        {"pair": "BTC/USDT:USDT"},
    )
    rejected = strategy.populate_entry_trend(
        pd.DataFrame([_row(relative_volume=0.79)]),
        {"pair": "BTC/USDT:USDT"},
    )

    assert _signal(accepted, "enter_long") == 1
    assert _signal(rejected, "enter_long") == 0


def test_e04_requires_directional_price_acceptance() -> None:
    strategy = PriceFlowEventAdaptive04Strategy(config={})

    accepted = strategy.populate_entry_trend(_price_accept_frame(), {"pair": "BTC/USDT:USDT"})
    rejected = strategy.populate_entry_trend(
        _price_accept_frame(body_atr=0.29), {"pair": "BTC/USDT:USDT"}
    )

    assert _signal(accepted, "enter_long") == 1
    assert _signal(rejected, "enter_long") == 0


def test_e11_can_add_accepted_capital_without_cusum() -> None:
    strategy = PriceFlowEventAdaptive11Strategy(config={})
    dataframe = _price_accept_frame(taker_cusum_long_follow=False)

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert _signal(result, "enter_long") == 1
    assert result.iloc[-1]["enter_tag"] == "ea_e11_acceptance_long"


def test_e16_waits_for_a_second_price_acceptance_step() -> None:
    strategy = PriceFlowEventAdaptive16Strategy(config={})
    dataframe = pd.DataFrame(
        [
            _row(
                date=pd.Timestamp("2024-01-31 23:45:00Z"),
                decision_time=pd.Timestamp("2024-02-01 00:00:00Z"),
                open=99.0,
                high=100.0,
                low=98.5,
                close=99.5,
                taker_cusum_long_follow=False,
            ),
            _row(
                date=pd.Timestamp("2024-02-01 00:00:00Z"),
                decision_time=pd.Timestamp("2024-02-01 00:15:00Z"),
                high=101.0,
                close=100.8,
                taker_cusum_long_follow=False,
            ),
            _row(
                date=pd.Timestamp("2024-02-01 00:15:00Z"),
                decision_time=pd.Timestamp("2024-02-01 00:30:00Z"),
                open=100.8,
                high=102.0,
                low=100.5,
                close=101.8,
                taker_cusum_long_follow=False,
            ),
        ]
    )

    result = strategy.populate_entry_trend(dataframe, {"pair": "BTC/USDT:USDT"})

    assert _signal(result.iloc[[1]], "enter_long") == 0
    assert _signal(result.iloc[[2]], "enter_long") == 1
    assert result.iloc[2]["enter_tag"] == "ea_e16_second_acceptance_long"


def test_complete_fomc_calendar_fills_the_missing_early_research_period() -> None:
    strategy = PriceFlowEventAdaptive17Strategy(config={})
    dataframe = strategy._derive_event_features(
        pd.DataFrame(
            [
                _row(
                    decision_time=pd.Timestamp("2024-01-31 18:00:00Z"),
                    minutes_from_cpi=10_000.0,
                )
            ]
        )
    )

    assert dataframe.iloc[0]["ea_minutes_from_fomc"] == -60.0
    assert dataframe.iloc[0]["ea_minutes_from_scheduled"] == -60.0


def test_missing_decision_time_has_no_event_distance() -> None:
    strategy = PriceFlowEventAdaptive17Strategy(config={})

    result = strategy._derive_event_features(
        pd.DataFrame([_row(decision_time=pd.NaT, minutes_from_cpi=float("nan"))])
    )

    assert pd.isna(result.iloc[0]["ea_minutes_from_fomc"])
    assert pd.isna(result.iloc[0]["ea_minutes_from_policy"])


def test_e17_vetoes_pre_fomc_and_requires_post_release_confirmation() -> None:
    strategy = PriceFlowEventAdaptive17Strategy(config={})
    pre = strategy.populate_entry_trend(
        _price_accept_frame(
            decision_time=pd.Timestamp("2024-01-31 18:00:00Z"),
            minutes_from_cpi=10_000.0,
        ),
        {"pair": "BTC/USDT:USDT"},
    )
    accepted = strategy.populate_entry_trend(
        _price_accept_frame(
            decision_time=pd.Timestamp("2024-01-31 19:15:00Z"),
            minutes_from_cpi=10_000.0,
            bin_oi_change_15m_z=1.0,
        ),
        {"pair": "BTC/USDT:USDT"},
    )
    rejected = strategy.populate_entry_trend(
        _price_accept_frame(
            decision_time=pd.Timestamp("2024-01-31 19:30:00Z"),
            minutes_from_cpi=10_000.0,
            bin_oi_change_15m_z=0.99,
        ),
        {"pair": "BTC/USDT:USDT"},
    )

    assert _signal(pre, "enter_long") == 0
    assert _signal(accepted, "enter_long") == 1
    assert _signal(rejected, "enter_long") == 0


def test_e18_post_macro_extra_is_fail_closed_on_option_opposition() -> None:
    strategy = PriceFlowEventAdaptive18Strategy(config={})
    common = {
        "decision_time": pd.Timestamp("2024-01-31 19:15:00Z"),
        "minutes_from_cpi": 10_000.0,
        "taker_cusum_long_follow": False,
    }

    accepted = strategy.populate_entry_trend(
        _price_accept_frame(**common), {"pair": "BTC/USDT:USDT"}
    )
    opposed = strategy.populate_entry_trend(
        _price_accept_frame(
            **common,
            opt_dte_1_7_count_1h=4,
            opt_dte_1_7_urgency_1h=-0.2,
        ),
        {"pair": "BTC/USDT:USDT"},
    )

    assert _signal(accepted, "enter_long") == 1
    assert _signal(opposed, "enter_long") == 0


def test_e19_requires_strong_confirmation_during_endogenous_shock() -> None:
    strategy = PriceFlowEventAdaptive19Strategy(config={})

    accepted = strategy.populate_entry_trend(
        _price_accept_frame(volatility_event=True, bin_oi_change_15m_z=1.0),
        {"pair": "BTC/USDT:USDT"},
    )
    rejected = strategy.populate_entry_trend(
        _price_accept_frame(volatility_event=True, bin_oi_change_15m_z=0.99),
        {"pair": "BTC/USDT:USDT"},
    )

    assert _signal(accepted, "enter_long") == 1
    assert _signal(rejected, "enter_long") == 0


def test_e20_policy_state_begins_only_at_conservative_public_boundary() -> None:
    strategy = PriceFlowEventAdaptive20Strategy(config={})
    dataframe = strategy._derive_event_features(
        pd.DataFrame(
            [
                _row(decision_time=pd.Timestamp("2025-03-06 23:45:00Z")),
                _row(decision_time=pd.Timestamp("2025-03-07 00:00:00Z")),
                _row(decision_time=pd.Timestamp("2025-03-08 00:00:00Z")),
            ]
        )
    )

    assert not bool(dataframe.iloc[0]["ea_policy_post_24h"])
    assert bool(dataframe.iloc[1]["ea_policy_post_24h"])
    assert bool(dataframe.iloc[2]["ea_policy_post_24h"])


def test_frozen_participation_freshness_strategy_preserves_e10_entries() -> None:
    frozen = PriceFlowParticipationFreshnessStrategy(config={})
    research = PriceFlowEventAdaptive10Strategy(config={})
    dataframe = pd.DataFrame(
        [
            _row(relative_volume=0.79),
            _row(relative_volume=0.80),
            _row(relative_volume=1.20, bin_taker_imbalance=-0.10),
        ]
    )

    frozen_result = frozen.populate_entry_trend(dataframe.copy(), {"pair": "BTC/USDT:USDT"})
    research_result = research.populate_entry_trend(dataframe.copy(), {"pair": "BTC/USDT:USDT"})

    assert frozen.event_id == 10
    assert frozen_result[["enter_long", "enter_short", "enter_tag"]].equals(
        research_result[["enter_long", "enter_short", "enter_tag"]]
    )
