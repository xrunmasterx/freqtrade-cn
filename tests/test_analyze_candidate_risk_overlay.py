from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "analyze_candidate_risk_overlay.py"
SPEC = importlib.util.spec_from_file_location("risk_overlay", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
risk_overlay = importlib.util.module_from_spec(SPEC)
sys.modules["risk_overlay"] = risk_overlay
SPEC.loader.exec_module(risk_overlay)


def test_scaled_overlay_preserves_underlying_stop_and_roi_distances() -> None:
    specs = risk_overlay.build_specs(
        reference_roi={"0": 0.52},
        reference_stoploss=-0.21,
        reference_leverage=14,
        fee_per_side=0.0006,
        leverages=[1, 14],
        risks=[],
    )

    one, fourteen = specs
    assert one.stoploss == pytest.approx(-0.015)
    assert fourteen.stoploss == pytest.approx(-0.21)
    assert one.minimal_roi["0"] == pytest.approx(0.52 / 14)
    assert fourteen.minimal_roi["0"] == pytest.approx(0.52)
    assert abs(one.stoploss) / one.leverage == pytest.approx(0.015)
    assert abs(fourteen.stoploss) / fourteen.leverage == pytest.approx(0.015)


def test_fixed_risk_sizing_includes_roundtrip_cost_and_caps_wallet() -> None:
    fraction, capped = risk_overlay.fixed_risk_stake_fraction(
        target_risk_fraction=0.01,
        price_stop_distance=0.015,
        leverage=14,
        fee_per_side=0.0006,
        is_short=False,
    )
    assert capped is False
    assert fraction == pytest.approx(0.01 / (14 * (0.015 + 0.0012 - 0.015 * 0.0006)))

    short_fraction, short_capped = risk_overlay.fixed_risk_stake_fraction(
        target_risk_fraction=0.01,
        price_stop_distance=0.015,
        leverage=14,
        fee_per_side=0.0006,
        is_short=True,
    )
    assert short_capped is False
    assert short_fraction == pytest.approx(0.01 / (14 * (0.015 + 0.0012 + 0.015 * 0.0006)))
    assert short_fraction < fraction

    fraction, capped = risk_overlay.fixed_risk_stake_fraction(
        target_risk_fraction=0.02,
        price_stop_distance=0.015,
        leverage=1,
        fee_per_side=0.0006,
        is_short=False,
    )
    assert fraction == 1.0
    assert capped is True


def test_longest_losing_streak_uses_close_order() -> None:
    trades = [
        {"close_timestamp": 30, "profit_ratio": -0.1},
        {"close_timestamp": 10, "profit_ratio": -0.1},
        {"close_timestamp": 20, "profit_ratio": 0.1},
        {"close_timestamp": 40, "profit_ratio": -0.1},
    ]
    assert risk_overlay.longest_losing_streak(trades) == 2


def test_entry_equities_exclude_same_candle_trade_profit() -> None:
    trades = [
        {"open_timestamp": 10, "close_timestamp": 20, "profit_abs": 50.0},
        {"open_timestamp": 20, "close_timestamp": 20, "profit_abs": -10.0},
    ]

    assert risk_overlay.entry_equities(trades, 1000.0) == {0: 1000.0, 1: 1050.0}


def test_profit_factor_uses_cash_profit_not_trade_return_ratios() -> None:
    trades = [
        {"profit_abs": 20.0, "profit_ratio": 0.50},
        {"profit_abs": -10.0, "profit_ratio": -0.05},
    ]

    assert risk_overlay.profit_factor_abs(trades) == pytest.approx(2.0)


def test_rolling_30d_uses_actual_wallet_path() -> None:
    dates = pd.date_range("2026-01-01", periods=32, freq="1D", tz="UTC")
    wallet = pd.DataFrame(
        {
            "date": dates,
            "total_quote": [100.0] * 30 + [120.0, 90.0],
        }
    )

    result = risk_overlay.rolling_30d_stats(wallet)

    assert result["observations"] == 2
    assert result["max_pct"] == pytest.approx(20.0)
    assert result["latest_pct"] == pytest.approx(-10.0)
    assert result["positive_fraction"] == pytest.approx(0.5)


def test_liquidation_distances_match_engine_linear_isolated_formula() -> None:
    long_raw, short_raw, long_buffered, short_buffered = risk_overlay.liquidation_distances(
        leverage=14,
        maintenance_margin_rate=0.004,
        taker_rate=0.0005,
        liquidation_buffer=0.05,
    )
    expected_long_raw = (1 / 14 - 0.0045) / (1 - 0.0045)
    expected_short_raw = (1 / 14 - 0.0045) / (1 + 0.0045)
    assert long_raw == pytest.approx(expected_long_raw)
    assert short_raw == pytest.approx(expected_short_raw)
    assert long_buffered == pytest.approx(expected_long_raw * 0.95)
    assert short_buffered == pytest.approx(expected_short_raw * 0.95)


def test_okx_tier_selection_converts_base_amount_to_contracts() -> None:
    tiers = [
        {"tier": 1, "minNotional": 0.0},
        {"tier": 2, "minNotional": 1000.01},
    ]

    tier, contracts = risk_overlay._tier_for_okx_contracts(tiers, base_amount=9.0)

    assert contracts == pytest.approx(900.0)
    assert tier["tier"] == 1


def test_generic_overlay_rejects_path_dependent_risk_callbacks() -> None:
    class CustomStopStrategy:
        use_custom_stoploss = True
        trailing_stop = False
        position_adjustment_enable = False

    with pytest.raises(ValueError, match="use_custom_stoploss"):
        risk_overlay._validate_static_risk_overlay(CustomStopStrategy)
