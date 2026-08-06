from __future__ import annotations

import pandas as pd
import pytest

from tools import prepare_price_flow_timeframe_leverage_data as prepare


def _ohlcv() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2024-01-01T00:00:00Z",
                    "2024-01-01T00:15:00Z",
                    "2024-01-01T00:30:00Z",
                    "2024-01-01T00:45:00Z",
                    "2024-01-01T01:00:00Z",
                ],
                utc=True,
            ),
            "open": [100.0, 101.0, 103.0, 102.0, 105.0],
            "high": [102.0, 104.0, 104.0, 106.0, 107.0],
            "low": [99.0, 100.0, 101.0, 101.0, 104.0],
            "close": [101.0, 103.0, 102.0, 105.0, 106.0],
            "volume": [10.0, 20.0, 30.0, 40.0, 50.0],
        }
    )


def test_resample_30m_uses_exchange_ohlcv_semantics_and_drops_partial_bucket() -> None:
    result = prepare._resample_ohlcv(_ohlcv(), "30min", source_minutes=15)

    assert len(result) == 2
    assert result.iloc[0].to_dict() == {
        "date": pd.Timestamp("2024-01-01T00:00:00Z"),
        "open": 100.0,
        "high": 104.0,
        "low": 99.0,
        "close": 103.0,
        "volume": 30.0,
    }
    assert result.iloc[1].to_dict() == {
        "date": pd.Timestamp("2024-01-01T00:30:00Z"),
        "open": 103.0,
        "high": 106.0,
        "low": 101.0,
        "close": 105.0,
        "volume": 70.0,
    }


def test_augment_five_minute_flow_uses_only_present_and_past_rows() -> None:
    frame = pd.DataFrame(
        {
            "bin_taker_imbalance": [0.1, 0.2, 0.3, 0.4],
            "bin_oi_change_5m": [0.01, 0.02, 0.03, 0.04],
            "bin_top_position_change_5m": [0.001, 0.002, 0.003, 0.004],
            "bin_breakout_long_5m": [False, True, False, False],
            "bin_breakout_short_5m": [False, False, False, False],
            "bin_taker_cusum_cross": [0, 1, 0, 0],
            "bin_three_5m_valid": [True, True, True, True],
        },
        index=pd.date_range("2024-01-01T00:05:00Z", periods=4, freq="5min"),
    )

    result = prepare._augment_five_minute_flow(frame)

    assert pd.isna(result.iloc[0]["bin_taker_lag1"])
    assert result.iloc[2]["bin_taker_lag1"] == 0.2
    assert result.iloc[2]["bin_taker_lag2"] == 0.1
    assert result.iloc[2]["bin_oi_delta_lag1"] == 0.02
    assert bool(result.iloc[2]["bin_breakout_long_current_15m"])


def test_parity_check_rejects_a_material_15m_mismatch() -> None:
    decision = pd.to_datetime(["2024-01-01T00:15:00Z"], utc=True)
    generated = pd.DataFrame(
        {"decision_time": decision, "bin_taker_imbalance": [0.1]}
    )
    frozen = pd.DataFrame(
        {"decision_time": decision, "bin_taker_imbalance": [0.2]}
    )

    with pytest.raises(ValueError, match="15m parity"):
        prepare._validate_15m_parity(
            generated,
            frozen,
            columns=["bin_taker_imbalance"],
        )
