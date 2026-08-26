from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from prepare_okx_orderflow_score_data import (
    _daily_windows,
    aggregate_trades,
    attach_funding,
    attach_open_interest,
    attach_previous_day_profile,
    build_daily_profiles,
    build_fifteen_minute,
    validate_candle_volume,
)


def test_archive_discovery_splits_ranges_before_the_okx_limit() -> None:
    windows = _daily_windows(
        pd.Timestamp("2026-01-01T00:00:00Z"),
        pd.Timestamp("2026-02-05T00:00:00Z"),
    )

    assert windows == [
        (
            pd.Timestamp("2026-01-01T00:00:00Z"),
            pd.Timestamp("2026-01-10T00:00:00Z"),
        ),
        (
            pd.Timestamp("2026-01-10T00:00:00Z"),
            pd.Timestamp("2026-01-19T00:00:00Z"),
        ),
        (
            pd.Timestamp("2026-01-19T00:00:00Z"),
            pd.Timestamp("2026-01-28T00:00:00Z"),
        ),
        (
            pd.Timestamp("2026-01-28T00:00:00Z"),
            pd.Timestamp("2026-02-05T00:00:00Z"),
        ),
    ]


def test_open_interest_merge_normalizes_timestamp_precision() -> None:
    sidecar = pd.DataFrame(
        {"date": pd.to_datetime(["2026-01-02T00:00:00Z"]).astype("datetime64[ms, UTC]")}
    )
    oi = pd.DataFrame(
        {
            "oi_source_time": pd.to_datetime(["2026-01-01T00:00:00Z"]).astype(
                "datetime64[us, UTC]"
            ),
            "oi_available_time": pd.to_datetime(["2026-01-02T00:00:00Z"]).astype(
                "datetime64[us, UTC]"
            ),
            "oi_usd": [2_000_000_000.0],
        }
    )

    result = attach_open_interest(sidecar, oi)

    assert result["oi_usd"].tolist() == [2_000_000_000.0]


def test_session_cvd_slope_is_available_from_the_first_closed_bucket() -> None:
    five = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01T00:00:00Z", periods=3, freq="5min"),
            "buy_base": [2.0, 2.0, 2.0],
            "sell_base": [1.0, 1.0, 1.0],
            "trade_count": [2, 2, 2],
            "first_price": [100.0, 101.0, 102.0],
            "last_price": [101.0, 102.0, 103.0],
            "high_price": [101.0, 102.0, 103.0],
            "low_price": [100.0, 101.0, 102.0],
        }
    )

    result = build_fifteen_minute(five)

    assert result["cvd_slope_4"].tolist() == [3.0]


def test_funding_event_is_used_only_after_the_publication_delay() -> None:
    sidecar = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01T07:45:00Z", "2026-01-01T08:00:00Z"]),
            "source_complete_time": pd.to_datetime(
                ["2026-01-01T08:00:00Z", "2026-01-01T08:15:00Z"]
            ),
        }
    )
    funding = pd.DataFrame(
        {
            "funding_source_time": pd.to_datetime(
                ["2026-01-01T00:00:00Z", "2026-01-01T08:00:00Z"]
            ),
            "funding_rate": [0.0001, 0.0002],
        }
    )

    result = attach_funding(sidecar, funding)

    assert result["funding_rate"].tolist() == pytest.approx([0.0001, 0.0002])
    assert (
        result["funding_source_time"]
        .le(result["date"] + pd.Timedelta(minutes=15))
        .all()
    )


def test_trade_aggregation_uses_real_side_and_contract_value() -> None:
    trades = pd.DataFrame(
        {
            "side": ["buy", "sell", "buy"],
            "price": [100.0, 99.0, 101.0],
            "size": [2.0, 3.0, 1.0],
            "created_time": [
                1_767_225_601_000,
                1_767_225_899_000,
                1_767_226_001_000,
            ],
        }
    )

    five, price_volume = aggregate_trades(trades, contract_value=0.1)

    assert five["date"].tolist() == [
        pd.Timestamp("2026-01-01T00:00:00Z"),
        pd.Timestamp("2026-01-01T00:05:00Z"),
    ]
    assert five["buy_base"].tolist() == pytest.approx([0.2, 0.1])
    assert five["sell_base"].tolist() == pytest.approx([0.3, 0.0])
    assert five["trade_count"].tolist() == [2, 1]
    assert price_volume["base_volume"].sum() == pytest.approx(0.6)


def test_profile_attached_to_a_day_uses_only_the_completed_prior_day() -> None:
    price_volume = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2026-01-01T00:01:00Z",
                    "2026-01-01T12:00:00Z",
                    "2026-01-01T23:59:00Z",
                    "2026-01-02T00:01:00Z",
                ]
            ),
            "price": [99.0, 100.0, 101.0, 500.0],
            "base_volume": [1.0, 10.0, 1.0, 100.0],
        }
    )
    profiles = build_daily_profiles(price_volume, bins=3, value_area=0.70)
    candles = pd.DataFrame(
        {"date": pd.to_datetime(["2026-01-02T00:00:00Z", "2026-01-02T12:00:00Z"])}
    )

    result = attach_previous_day_profile(candles, profiles)

    assert result["vp_source_day"].tolist() == [
        pd.Timestamp("2026-01-01T00:00:00Z"),
        pd.Timestamp("2026-01-01T00:00:00Z"),
    ]
    assert result["vp_poc"].tolist() == pytest.approx([100.0, 100.0])
    assert result["vp_source_complete_time"].le(result["date"]).all()


def test_tick_volume_must_match_official_candle_volume() -> None:
    candles = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01T00:00:00Z"]),
            "volume": [0.5],
        }
    )
    aggregated = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01T00:00:00Z"]),
            "total_base": [0.5],
        }
    )

    summary = validate_candle_volume(aggregated, candles)

    assert summary["maximum_relative_error"] == 0.0

    corrected_archive = aggregated.assign(total_base=0.50025)
    corrected_summary = validate_candle_volume(corrected_archive, candles)
    assert corrected_summary["maximum_relative_error"] == pytest.approx(0.0005)

    with pytest.raises(ValueError, match="volume mismatch"):
        validate_candle_volume(aggregated.assign(total_base=0.4), candles)
