from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
sys.path.insert(0, str(STRATEGY_DIR))

from OkxOrderFlowAScoreStrategy import OkxOrderFlowAScoreStrategy


def test_grade_requires_the_published_component_gates() -> None:
    frame = pd.DataFrame(
        {
            "total": [85, 78, 90, 69],
            "htf": [25, 18, 25, 25],
            "key": [20, 15, 20, 20],
            "orderflow": [25, 18, 10, 25],
        }
    )

    grade = OkxOrderFlowAScoreStrategy._grade(
        frame["total"], frame["htf"], frame["key"], frame["orderflow"]
    )

    assert grade.tolist() == [2, 1, 0, 0]


def test_cvd_sign_alone_is_not_cvd_leading() -> None:
    long, short = OkxOrderFlowAScoreStrategy._cvd_leading(
        cvd_slope=pd.Series([5.0, 12.0, 12.0, -12.0]),
        last_imbalance=pd.Series([0.10, 0.10, 0.10, -0.10]),
        close=pd.Series([99.0, 99.0, 101.0, 101.0]),
        prior_high=pd.Series([100.0] * 4),
        prior_low=pd.Series([100.0] * 4),
        upper_threshold=pd.Series([10.0] * 4),
        lower_threshold=pd.Series([-10.0] * 4),
    )

    assert long.tolist() == [False, True, False, False]
    assert short.tolist() == [False, False, False, True]


def test_sidecar_contract_rejects_future_or_incomplete_evidence() -> None:
    sidecar = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01T00:00:00Z"]),
            "source_complete_time": pd.to_datetime(["2026-01-01T00:15:00Z"]),
            "decision_time": pd.to_datetime(["2026-01-01T00:15:00Z"]),
            "constituent_5m_count": [3],
            "trade_count": [100],
            "buy_base": [10.0],
            "sell_base": [9.0],
            "total_base": [19.0],
            "delta_base": [1.0],
            "imbalance": [1.0 / 19.0],
            "first_5m_imbalance": [0.0],
            "last_5m_imbalance": [0.1],
            "last_5m_return": [0.001],
            "cvd_session": [1.0],
            "cvd_slope_4": [1.0],
            "vp_source_day": pd.to_datetime(["2025-12-31T00:00:00Z"]),
            "vp_source_complete_time": pd.to_datetime(["2026-01-01T00:00:00Z"]),
            "vp_poc": [100.0],
            "vp_vah": [101.0],
            "vp_val": [99.0],
            "prior_day_high": [102.0],
            "prior_day_low": [98.0],
            "oi_source_time": pd.to_datetime(["2025-12-31T00:00:00Z"]),
            "oi_usd": [2_000_000_000.0],
            "funding_source_time": pd.to_datetime(["2025-12-31T16:00:00Z"]),
            "funding_rate": [0.0001],
        }
    )
    for column in (
        "source_complete_time",
        "decision_time",
        "vp_source_day",
        "vp_source_complete_time",
        "oi_source_time",
        "funding_source_time",
    ):
        sidecar[column] = sidecar[column].astype("datetime64[us, UTC]")

    OkxOrderFlowAScoreStrategy._prepare_sidecar(sidecar)

    future = sidecar.copy()
    future.loc[0, "source_complete_time"] = pd.Timestamp("2026-01-01T00:30:00Z")
    with pytest.raises(ValueError, match="complete"):
        OkxOrderFlowAScoreStrategy._prepare_sidecar(future)

    incomplete = sidecar.assign(constituent_5m_count=2)
    with pytest.raises(ValueError, match="three complete"):
        OkxOrderFlowAScoreStrategy._prepare_sidecar(incomplete)


def test_missing_orderflow_evidence_cannot_create_an_entry() -> None:
    strategy = OkxOrderFlowAScoreStrategy(config={})
    frame = pd.DataFrame(
        {
            "long_total_score": [100],
            "long_htf_score": [25],
            "long_key_score": [20],
            "long_orderflow_score": [25],
            "short_total_score": [0],
            "short_htf_score": [0],
            "short_key_score": [0],
            "short_orderflow_score": [0],
            "orderflow_evidence_valid": [False],
            "oi_ok": [True],
            "volatility_ok": [True],
            "volume": [1.0],
        }
    )

    result = strategy.populate_entry_trend(frame, {"pair": "BTC/USDT:USDT"})

    assert int(result["enter_long"].iloc[0]) == 0


def test_out_of_range_atr_cannot_create_an_entry() -> None:
    strategy = OkxOrderFlowAScoreStrategy(config={})
    frame = pd.DataFrame(
        {
            "long_total_score": [100],
            "long_htf_score": [25],
            "long_key_score": [20],
            "long_orderflow_score": [25],
            "short_total_score": [0],
            "short_htf_score": [0],
            "short_key_score": [0],
            "short_orderflow_score": [0],
            "orderflow_evidence_valid": [True],
            "oi_ok": [True],
            "volatility_ok": [False],
            "volume": [1.0],
        }
    )

    result = strategy.populate_entry_trend(frame, {"pair": "BTC/USDT:USDT"})

    assert int(result["enter_long"].iloc[0]) == 0
