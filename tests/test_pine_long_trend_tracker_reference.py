from datetime import UTC, datetime, timedelta

import pandas as pd
from tools.run_pine_long_trend_tracker_reference import (
    PineLongTrendTrackerReference,
    Position,
    TrailingOrder,
)


def candle_frame(*, reversal: bool = False) -> pd.DataFrame:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    rows = [
        {
            "date": start + timedelta(minutes=5 * index),
            "open": 99.0,
            "high": 100.0,
            "low": 98.0,
            "close": 99.0,
            "volume": 1.0,
        }
        for index in range(21)
    ]
    rows.append(
        {
            "date": start + timedelta(minutes=105),
            "open": 99.0,
            "high": 102.0,
            "low": 98.0,
            "close": 101.0,
            "volume": 1.0,
        }
    )
    rows.append(
        {
            "date": start + timedelta(minutes=110),
            "open": 101.0,
            "high": 102.0,
            "low": 96.0 if reversal else 90.0,
            "close": 97.0 if reversal else 101.0,
            "volume": 1.0,
        }
    )
    rows.append(
        {
            "date": start + timedelta(minutes=115),
            "open": 101.0,
            "high": 101.5,
            "low": 99.0,
            "close": 99.5,
            "volume": 1.0,
        }
    )
    return pd.DataFrame(rows)


def test_entry_fills_on_signal_close_and_trailing_order_starts_next_close():
    frame = candle_frame()
    runner = PineLongTrendTrackerReference()

    result = runner.run(
        frame,
        start=pd.Timestamp(frame.iloc[0]["date"]),
        end=pd.Timestamp(frame.iloc[-1]["date"]) + pd.Timedelta(minutes=5),
    )

    assert result["closed_trades"] == 1
    trade = runner.trades[0]
    assert trade.entry_time == pd.Timestamp(frame.iloc[21]["date"]).isoformat()
    assert trade.entry_price == 101.0
    assert trade.exit_time == pd.Timestamp(frame.iloc[23]["date"]).isoformat()
    assert trade.exit_reason == "trailing_stop"


def test_opposite_entry_reverses_at_same_close():
    frame = candle_frame(reversal=True)
    runner = PineLongTrendTrackerReference()

    result = runner.run(
        frame.iloc[:23],
        start=pd.Timestamp(frame.iloc[0]["date"]),
        end=pd.Timestamp(frame.iloc[23]["date"]),
    )

    assert result["closed_trades"] == 1
    trade = runner.trades[0]
    assert trade.direction == "long"
    assert trade.exit_time == pd.Timestamp(frame.iloc[22]["date"]).isoformat()
    assert trade.exit_price == 97.0
    assert trade.exit_reason == "reverse"
    assert result["open_position"] == "short"


def test_default_ohlc_path_updates_then_hits_long_trailing_stop():
    timestamp = pd.Timestamp("2026-08-01T00:00:00Z")
    row = pd.DataFrame(
        [
            {
                "date": timestamp,
                "open": 101.0,
                "high": 110.0,
                "low": 90.0,
                "close": 95.0,
            }
        ]
    ).itertuples(index=False).__next__()
    runner = PineLongTrendTrackerReference()
    runner.position = Position(1, timestamp, 100.0, 10.0)
    runner.trailing_order = TrailingOrder(
        activation_price=100.0,
        offset_price=5.0,
        active=True,
        best_price=101.0,
        stop_price=96.0,
    )

    exit_price = runner._process_trailing_bar(row)

    assert exit_price == 105.0
