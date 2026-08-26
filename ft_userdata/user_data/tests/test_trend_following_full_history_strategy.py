# ruff: noqa: S101

import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from freqtrade.strategy import stoploss_from_absolute


STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
sys.path.insert(0, str(STRATEGY_DIR))

from TrendFollowingFullHistoryStrategy import (  # noqa: E402
    TrendFollowing2hN20Stop15Trail25Strategy,
)


ROOT = STRATEGY_DIR.parents[2]
sys.path.insert(0, str(ROOT))

from tools import run_trend_following_full_history as runner  # noqa: E402


class FakeTrade:
    def __init__(self, *, is_short: bool):
        self.is_short = is_short
        self.leverage = 1.0
        self.open_date_utc = datetime(2023, 1, 1, 4, tzinfo=UTC)
        self.open_rate = 100.0
        self.max_rate = None
        self.min_rate = None
        self.custom_data: dict[str, object] = {}

    def get_custom_data(self, key: str, default=None):
        return self.custom_data.get(key, default)

    def set_custom_data(self, key: str, value) -> None:
        self.custom_data[key] = value


class FakeDataProvider:
    def __init__(self):
        self.dataframe = pd.DataFrame(
            {
                "date": [
                    datetime(2023, 1, 1, 0, tzinfo=UTC),
                    datetime(2023, 1, 1, 2, tzinfo=UTC),
                    datetime(2023, 1, 1, 4, tzinfo=UTC),
                ],
                "atr": [4.0, 4.0, 99.0],
            }
        )

    def get_analyzed_dataframe(self, pair: str, timeframe: str):
        return self.dataframe.copy(), None


@pytest.mark.parametrize(
    ("is_short", "expected_stop"),
    [(False, 94.0), (True, 106.0)],
)
def test_missing_favorable_rate_initializes_from_open_rate(is_short, expected_stop):
    strategy = TrendFollowing2hN20Stop15Trail25Strategy(config={})
    strategy.dp = FakeDataProvider()
    trade = FakeTrade(is_short=is_short)
    current_time = trade.open_date_utc + timedelta(minutes=5)

    result = strategy.custom_stoploss(
        pair="BTC/USDT:USDT",
        trade=trade,
        current_time=current_time,
        current_rate=100.0,
        current_profit=0.0,
        after_fill=False,
    )

    expected = stoploss_from_absolute(
        expected_stop,
        100.0,
        is_short=is_short,
    )
    assert math.isclose(result, expected, rel_tol=1e-12, abs_tol=1e-12)
    assert trade.get_custom_data("trend_stop_rate") == expected_stop


def test_validation_prerequisite_requires_only_complete_development_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RESULT_ROOT", tmp_path)
    for candidate in runner.CANDIDATES:
        path = runner.receipt_path(
            "development",
            candidate,
            "fee_plus_slippage_baseline",
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    runner.validate_validation_prerequisites()
