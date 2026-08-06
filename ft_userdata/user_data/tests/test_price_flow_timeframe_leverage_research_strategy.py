from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
sys.path.insert(0, str(STRATEGY_DIR))

import PriceFlowTimeframeLeverageResearchStrategy as research
from PriceFlowTimeframeLeverageResearchStrategy import (
    PriceFlowE10Tf1hLev10Strategy,
    PriceFlowE10Tf5mLev1Strategy,
    PriceFlowE10Tf15mLev2Strategy,
    PriceFlowE10Tf30mLev3Strategy,
)


@pytest.mark.parametrize(
    ("strategy_type", "expected"),
    [
        (
            PriceFlowE10Tf5mLev1Strategy,
            {
                "atr": 42,
                "ema": 60,
                "donchian": 144,
                "relative_volume": 288,
                "vwap": 288,
                "flow_fast": 24,
                "flow_slow": 72,
                "retest": 24,
                "cooldown": 12,
            },
        ),
        (
            PriceFlowE10Tf15mLev2Strategy,
            {
                "atr": 14,
                "ema": 20,
                "donchian": 48,
                "relative_volume": 96,
                "vwap": 96,
                "flow_fast": 8,
                "flow_slow": 24,
                "retest": 8,
                "cooldown": 4,
            },
        ),
        (
            PriceFlowE10Tf30mLev3Strategy,
            {
                "atr": 7,
                "ema": 10,
                "donchian": 24,
                "relative_volume": 48,
                "vwap": 48,
                "flow_fast": 4,
                "flow_slow": 12,
                "retest": 4,
                "cooldown": 2,
            },
        ),
        (
            PriceFlowE10Tf1hLev10Strategy,
            {
                "atr": 4,
                "ema": 5,
                "donchian": 12,
                "relative_volume": 24,
                "vwap": 24,
                "flow_fast": 2,
                "flow_slow": 6,
                "retest": 2,
                "cooldown": 1,
            },
        ),
    ],
)
def test_price_windows_preserve_real_clock_durations(strategy_type, expected) -> None:
    strategy = strategy_type(config={})

    assert strategy.adaptive_windows == expected
    assert strategy.retest_window == expected["retest"]
    assert strategy.protections == [
        {"method": "CooldownPeriod", "stop_duration_candles": expected["cooldown"]}
    ]


def test_all_twenty_matrix_strategies_are_discoverable_and_stable() -> None:
    source = Path(research.__file__).read_text(encoding="utf-8")

    for timeframe in ("5m", "15m", "30m", "1h"):
        for leverage in (1, 2, 3, 5, 10):
            name = f"PriceFlowE10Tf{timeframe}Lev{leverage}Strategy"
            strategy_type = getattr(research, name)
            assert f"class {name}(" in source
            assert strategy_type.timeframe == timeframe
            assert strategy_type.target_leverage == float(leverage)
            assert strategy_type.event_id == 10


def test_leverage_callback_uses_the_frozen_matrix_value_and_exchange_cap() -> None:
    strategy = PriceFlowE10Tf1hLev10Strategy(config={})

    assert strategy.leverage(
        "BTC/USDT:USDT",
        pd.Timestamp("2025-01-01T00:00:00Z"),
        100_000.0,
        1.0,
        20.0,
        None,
        "long",
    ) == 10.0
    assert strategy.leverage(
        "BTC/USDT:USDT",
        pd.Timestamp("2025-01-01T00:00:00Z"),
        100_000.0,
        1.0,
        5.0,
        None,
        "long",
    ) == 5.0


def test_informative_asof_merge_never_reads_an_unclosed_hour() -> None:
    strategy = PriceFlowE10Tf5mLev1Strategy(config={})
    base = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2024-01-01T00:50:00Z", "2024-01-01T00:55:00Z"], utc=True
            ),
            "close": [100.0, 101.0],
        }
    )
    informative = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2023-12-31T23:00:00Z", "2024-01-01T00:00:00Z"], utc=True
            ),
            "close": [90.0, 110.0],
            "long_trend": [False, True],
        }
    )

    merged = strategy._merge_closed_informative(
        base,
        informative,
        informative_timeframe="1h",
    )

    assert merged["close_1h"].tolist() == [90.0, 110.0]
    assert merged["long_trend_1h"].tolist() == [False, True]


def test_cross_venue_asof_merge_uses_only_evidence_available_at_candle_close(
    monkeypatch,
) -> None:
    strategy = PriceFlowE10Tf5mLev1Strategy(config={})
    base = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2024-01-01T00:00:00Z",
                    "2024-01-01T00:05:00Z",
                    "2024-01-01T00:10:00Z",
                ],
                utc=True,
            ),
            "close": [100.0, 101.0, 102.0],
        }
    )
    sidecar = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2023-12-31T23:45:00Z", "2024-01-01T00:00:00Z"], utc=True
            ),
            "decision_time": pd.to_datetime(
                ["2024-01-01T00:00:00Z", "2024-01-01T00:15:00Z"], utc=True
            ),
            "venue_spread": [1.0, 2.0],
            "cross_data_valid": [True, True],
        }
    )
    flow = pd.DataFrame(
        {
            "decision_time": pd.to_datetime(
                [
                    "2024-01-01T00:05:00Z",
                    "2024-01-01T00:10:00Z",
                    "2024-01-01T00:15:00Z",
                ],
                utc=True,
            ),
            "bin_taker_imbalance": [0.1, 0.2, 0.3],
            "bin_three_5m_valid": [True, True, True],
        }
    )
    monkeypatch.setattr(strategy, "_load_sidecar", lambda pair: sidecar.copy())
    monkeypatch.setattr(strategy, "_load_five_minute_flow", lambda pair: flow.copy())

    merged = strategy._merge_causal_cross_venue(base, "BTC/USDT:USDT")

    assert merged["decision_time"].tolist() == list(
        pd.to_datetime(
            [
                "2024-01-01T00:05:00Z",
                "2024-01-01T00:10:00Z",
                "2024-01-01T00:15:00Z",
            ],
            utc=True,
        )
    )
    assert merged["venue_spread"].tolist() == [1.0, 1.0, 2.0]
    assert merged["bin_taker_imbalance"].tolist() == [0.1, 0.2, 0.3]
    assert merged["cross_data_valid"].tolist() == [True, True, True]


def test_stale_or_invalid_five_minute_flow_fails_closed(monkeypatch) -> None:
    strategy = PriceFlowE10Tf15mLev2Strategy(config={})
    base = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01T00:00:00Z"], utc=True),
            "close": [100.0],
        }
    )
    sidecar = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01T00:00:00Z"], utc=True),
            "decision_time": pd.to_datetime(["2024-01-01T00:15:00Z"], utc=True),
            "cross_data_valid": [True],
        }
    )
    stale_flow = pd.DataFrame(
        {
            "decision_time": pd.to_datetime(["2024-01-01T00:05:00Z"], utc=True),
            "bin_taker_imbalance": [0.1],
            "bin_three_5m_valid": [True],
        }
    )
    monkeypatch.setattr(strategy, "_load_sidecar", lambda pair: sidecar.copy())
    monkeypatch.setattr(
        strategy, "_load_five_minute_flow", lambda pair: stale_flow.copy()
    )

    merged = strategy._merge_causal_cross_venue(base, "BTC/USDT:USDT")

    assert not bool(merged.iloc[0]["cross_data_valid"])


def test_preregistered_signed_freshness_requires_current_direction() -> None:
    original = PriceFlowE10Tf15mLev2Strategy(config={})
    signed = research.PriceFlowE10Tf15mLev2SignedFreshStrategy(config={})
    signed_oi = research.PriceFlowE10Tf15mLev2SignedFreshOiStrategy(config={})
    dataframe = pd.DataFrame(
        {
            "relative_volume": [1.0, 1.0],
            "bin_oi_change_15m_z": [1.0, 1.0],
            "ema50_slope_4h": [0.01, 0.01],
            "bin_taker_imbalance": [-0.1, 0.1],
            "bin_taker_lag2": [-0.2, 0.0],
            "close": [100.0, 101.0],
            "ci_oi_add": [False, False],
            "cross_data_valid": [True, True],
        }
    )

    original_long, _ = original._directional_features(dataframe)
    signed_long, _ = signed._directional_features(dataframe)
    signed_oi_long, _ = signed_oi._directional_features(dataframe)

    assert original_long["fresh"].tolist() == [True, True]
    assert signed_long["fresh"].tolist() == [False, True]
    assert signed_oi_long["fresh"].tolist() == [False, False]


def test_price_geometry_diagnostic_keeps_the_same_market_stop_and_roi_distance() -> None:
    one_x = research.PriceFlowE10Tf30mLev1PriceGeometryStrategy(config={})
    ten_x = research.PriceFlowE10Tf30mLev10PriceGeometryStrategy(config={})

    assert one_x.stoploss == -0.015
    assert ten_x.stoploss == -0.15
    assert one_x.minimal_roi == {"0": 0.03, "720": 0.02, "1440": 0.01}
    assert ten_x.minimal_roi == {"0": 0.30, "720": 0.20, "1440": 0.10}


def test_all_preregistered_adaptive_variants_have_discovery_markers() -> None:
    source = Path(research.__file__).read_text(encoding="utf-8")

    for timeframe in ("5m", "15m", "30m", "1h"):
        for leverage in (1, 2, 3, 5, 10):
            prefix = f"PriceFlowE10Tf{timeframe}Lev{leverage}"
            for suffix in (
                "SignedFreshStrategy",
                "SignedFreshOiStrategy",
                "PriceGeometryStrategy",
            ):
                name = f"{prefix}{suffix}"
                assert f"class {name}(" in source
                assert getattr(research, name).event_id == 10
