from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
sys.path.insert(0, str(STRATEGY_DIR))

import MultiTimeframeRegimeSwitchResearchStrategy as module
from MultiTimeframeRegimeSwitchResearchStrategy import (
    MtfSwitchR2S2P0Strategy,
    MtfSwitchR2S2P1Strategy,
    MultiTimeframeRegimeSwitchResearchStrategy,
)


def _frame(*, funding: float = 0.0001, basis: float = 0.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=2, freq="15min", tz="UTC"),
            "open": [100.0, 102.0],
            "high": [100.5, 103.0],
            "low": [99.5, 101.0],
            "close": [100.0, 102.0],
            "volume": [1.0, 1.0],
            "regime_state": ["range", "range"],
            "regime_adx_4h": [10.0, 10.0],
            "regime_adx_1d": [10.0, 10.0],
            "basis_1h": [basis, basis],
            "basis_observed": [True, True],
            "funding_rate_1h": [funding, funding],
            "funding_observed": [True, True],
            "range_ema": [100.0, 100.0],
            "range_atr": [1.0, 1.0],
            "range_rsi": [50.0, 80.0],
            "switch_channel_high": [101.0, 101.0],
            "switch_channel_low": [99.0, 99.0],
        }
    )


def test_variant_matrix_is_exactly_50_unique_classes() -> None:
    specs = list(module.VARIANT_SPECS)
    names = [str(spec["name"]) for spec in specs]
    classes = [getattr(module, name) for name in names]

    assert len(specs) == 50
    assert len(set(str(spec["code"]) for spec in specs)) == 50
    assert len(set(names)) == 50
    assert all(issubclass(item, MultiTimeframeRegimeSwitchResearchStrategy) for item in classes)


def test_range_short_signal_is_causal_and_side_specific() -> None:
    strategy = MtfSwitchR2S2P0Strategy(config={})
    result = strategy.populate_entry_trend(_frame(), {"pair": "BTC/USDT:USDT"})

    assert int(result.loc[0, "enter_short"]) == 0
    assert int(result.loc[1, "enter_short"]) == 1
    assert int(result["enter_long"].sum()) == 0


def test_funding_gate_rejects_non_favorable_short_funding() -> None:
    strategy = MtfSwitchR2S2P1Strategy(config={})
    allowed = strategy.populate_entry_trend(
        _frame(funding=0.0001, basis=-0.001), {"pair": "BTC/USDT:USDT"}
    )
    rejected = strategy.populate_entry_trend(
        _frame(funding=-0.0001, basis=-0.001), {"pair": "BTC/USDT:USDT"}
    )

    assert int(allowed.loc[1, "enter_short"]) == 1
    assert int(rejected["enter_short"].sum()) == 0


def test_custom_stoploss_tightens_only_after_short_favorable_move() -> None:
    strategy = MtfSwitchR2S2P0Strategy(config={})

    class FakeTrade:
        open_rate = 100.0
        is_short = True
        leverage = 1.0
        min_rate = 100.0
        max_rate = 100.0
        open_date_utc = datetime(2024, 1, 1, tzinfo=UTC)

        def __init__(self) -> None:
            self.data: dict[str, float] = {}

        def get_custom_data(self, key: str, default: object = None) -> object:
            return self.data.get(key, default)

        def set_custom_data(self, key: str, value: float) -> None:
            self.data[key] = value

    trade = FakeTrade()
    initial = strategy.custom_stoploss(
        "BTC/USDT:USDT", trade, trade.open_date_utc, 100.0, 0.0, False
    )
    trade.min_rate = 99.0
    tightened = strategy.custom_stoploss(
        "BTC/USDT:USDT", trade, trade.open_date_utc, 99.0, 0.01, False
    )

    assert initial is not None and tightened is not None
    assert tightened >= initial
