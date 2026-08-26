from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
STRATEGY_DIR = ROOT / "ft_userdata" / "user_data" / "strategies"
sys.path.insert(0, str(STRATEGY_DIR))

from PineLongTrendTrackerStrategy import PineLongTrendTrackerStrategy  # noqa: E402


@dataclass
class Position:
    direction: int
    entry_time: pd.Timestamp
    entry_price: float
    quantity: float


@dataclass
class TrailingOrder:
    activation_price: float
    offset_price: float
    active: bool = False
    best_price: float | None = None
    stop_price: float | None = None


@dataclass
class ClosedTrade:
    direction: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    quantity: float
    profit: float
    profit_ratio: float
    exit_reason: str


def prepare_pine_frame(
    dataframe: pd.DataFrame,
    *,
    channel_length: int = 20,
    trail_multiplier: float = 2.5,
) -> pd.DataFrame:
    strategy = PineLongTrendTrackerStrategy(config={})
    strategy.channel_length = channel_length
    strategy.trail_multiplier = trail_multiplier
    result = strategy.populate_indicators(dataframe.copy(), {})
    result["long_cond"] = (result["close"] > result["high_channel"]) & (
        result["close"].shift(1) <= result["high_channel"].shift(1)
    )
    result["short_cond"] = (result["close"] < result["low_channel"]) & (
        result["close"].shift(1) >= result["low_channel"].shift(1)
    )
    return result


class PineLongTrendTrackerReference:
    """Documented Pine v6 OHLC broker-emulator semantics for the supplied script."""

    def __init__(
        self,
        *,
        initial_capital: float = 1000.0,
        tick_size: float = 0.1,
        trail_multiplier: float = 2.5,
    ) -> None:
        self.initial_capital = initial_capital
        self.tick_size = tick_size
        self.trail_multiplier = trail_multiplier
        self.equity = initial_capital
        self.position: Position | None = None
        self.trailing_order: TrailingOrder | None = None
        self.trades: list[ClosedTrade] = []

    @staticmethod
    def _bar_path(row) -> tuple[float, float, float, float]:
        open_price = float(row.open)
        high = float(row.high)
        low = float(row.low)
        close = float(row.close)
        if abs(open_price - high) < abs(open_price - low):
            return open_price, high, low, close
        return open_price, low, high, close

    def _activate(self, price: float) -> None:
        order = self.trailing_order
        position = self.position
        if order is None or position is None:
            return
        order.active = True
        order.best_price = price
        order.stop_price = price - position.direction * order.offset_price

    def _move_favorably(self, price: float) -> None:
        order = self.trailing_order
        position = self.position
        if order is None or position is None or not order.active:
            return
        if (
            order.best_price is None
            or position.direction * price > position.direction * order.best_price
        ):
            order.best_price = price
            candidate = price - position.direction * order.offset_price
            if order.stop_price is None:
                order.stop_price = candidate
            elif position.direction > 0:
                order.stop_price = max(order.stop_price, candidate)
            else:
                order.stop_price = min(order.stop_price, candidate)

    def _process_trailing_bar(self, row) -> float | None:  # noqa: C901
        order = self.trailing_order
        position = self.position
        if order is None or position is None:
            return None

        path = self._bar_path(row)
        opening = path[0]
        if order.active and order.stop_price is not None:
            if position.direction > 0 and opening <= order.stop_price:
                return opening
            if position.direction < 0 and opening >= order.stop_price:
                return opening
        elif position.direction * opening >= position.direction * order.activation_price:
            self._activate(opening)

        previous = opening
        for price in path[1:]:
            favorable = position.direction * price > position.direction * previous
            if not order.active and favorable:
                crosses_activation = (
                    position.direction * previous
                    < position.direction * order.activation_price
                    <= position.direction * price
                )
                if crosses_activation:
                    self._activate(order.activation_price)

            if order.active:
                if favorable:
                    self._move_favorably(price)
                elif order.stop_price is not None:
                    crossed_stop = (
                        position.direction * price
                        <= position.direction * order.stop_price
                        <= position.direction * previous
                    )
                    if crossed_stop:
                        return order.stop_price
            previous = price
        return None

    def _close_position(self, exit_time: pd.Timestamp, exit_price: float, reason: str) -> None:
        position = self.position
        if position is None:
            return
        profit = position.direction * position.quantity * (exit_price - position.entry_price)
        self.equity += profit
        self.trades.append(
            ClosedTrade(
                direction="long" if position.direction > 0 else "short",
                entry_time=position.entry_time.isoformat(),
                exit_time=exit_time.isoformat(),
                entry_price=position.entry_price,
                exit_price=exit_price,
                quantity=position.quantity,
                profit=profit,
                profit_ratio=position.direction * (exit_price / position.entry_price - 1.0),
                exit_reason=reason,
            )
        )
        self.position = None
        self.trailing_order = None

    def _open_position(self, direction: int, entry_time: pd.Timestamp, price: float) -> None:
        self.position = Position(
            direction=direction,
            entry_time=entry_time,
            entry_price=price,
            quantity=self.equity / price,
        )
        self.trailing_order = None

    def _update_trailing_order(self, close: float, atr: float) -> float | None:
        position = self.position
        if position is None or not np.isfinite(atr):
            return None
        offset = atr * self.trail_multiplier * self.tick_size
        if self.trailing_order is None:
            self.trailing_order = TrailingOrder(position.entry_price, offset)
        else:
            self.trailing_order.offset_price = offset

        order = self.trailing_order
        activation_reached = (
            position.direction * close >= position.direction * order.activation_price
        )
        if not order.active and activation_reached:
            self._activate(close)
        elif order.active and order.best_price is not None:
            candidate = order.best_price - position.direction * offset
            if position.direction > 0:
                order.stop_price = max(float(order.stop_price), candidate)
            else:
                order.stop_price = min(float(order.stop_price), candidate)

        if order.active and order.stop_price is not None:
            crossed = position.direction * close <= position.direction * order.stop_price
            if crossed:
                return close
        return None

    def run(
        self,
        dataframe: pd.DataFrame,
        *,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> dict:
        frame = prepare_pine_frame(dataframe, trail_multiplier=self.trail_multiplier)
        frame = frame.loc[(frame["date"] >= start) & (frame["date"] < end)]
        marked_equity: list[float] = []

        for row in frame.itertuples(index=False):
            timestamp = pd.Timestamp(row.date)
            trailing_exit = self._process_trailing_bar(row)
            if trailing_exit is not None:
                self._close_position(timestamp, trailing_exit, "trailing_stop")

            position_at_calculation = self.position
            desired_direction = 1 if bool(row.long_cond) else 0
            if bool(row.short_cond):
                desired_direction = -1

            is_reversal = (
                position_at_calculation is not None
                and desired_direction != 0
                and desired_direction != position_at_calculation.direction
            )
            if is_reversal:
                self._close_position(timestamp, float(row.close), "reverse")
                self._open_position(desired_direction, timestamp, float(row.close))
            else:
                if position_at_calculation is None and desired_direction != 0:
                    self._open_position(desired_direction, timestamp, float(row.close))
                if position_at_calculation is not None:
                    close_exit = self._update_trailing_order(float(row.close), float(row.atr))
                    if close_exit is not None:
                        self._close_position(timestamp, close_exit, "trailing_stop")

            open_profit = 0.0
            if self.position is not None:
                open_profit = self.position.direction * self.position.quantity * (
                    float(row.close) - self.position.entry_price
                )
            marked_equity.append(self.equity + open_profit)

        final_equity = marked_equity[-1] if marked_equity else self.equity
        peaks = np.maximum.accumulate(marked_equity) if marked_equity else np.array([])
        drawdowns = (peaks - marked_equity) / peaks if marked_equity else np.array([])
        profits = [trade.profit for trade in self.trades]
        gross_profit = sum(profit for profit in profits if profit > 0)
        gross_loss = -sum(profit for profit in profits if profit < 0)
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "candles": len(frame),
            "initial_capital": self.initial_capital,
            "closed_equity": self.equity,
            "final_marked_equity": final_equity,
            "total_return": final_equity / self.initial_capital - 1.0,
            "closed_trades": len(self.trades),
            "wins": sum(profit > 0 for profit in profits),
            "draws": sum(profit == 0 for profit in profits),
            "losses": sum(profit < 0 for profit in profits),
            "profit_factor": gross_profit / gross_loss if gross_loss else None,
            "max_close_drawdown": float(drawdowns.max()) if len(drawdowns) else 0.0,
            "open_position": None
            if self.position is None
            else "long"
            if self.position.direction > 0
            else "short",
        }


def parse_timestamp(value: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--end", type=parse_timestamp, required=True)
    parser.add_argument("--days", nargs="+", type=int, default=[7, 30, 90, 365])
    parser.add_argument("--tick-size", type=float, default=0.1)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataframe = pd.read_feather(args.data)
    dataframe["date"] = pd.to_datetime(dataframe["date"], utc=True)
    args.output.mkdir(parents=True, exist_ok=True)
    summaries: dict[str, dict] = {}
    for days in args.days:
        runner = PineLongTrendTrackerReference(tick_size=args.tick_size)
        start = args.end - pd.Timedelta(days=days)
        summary = runner.run(dataframe, start=start, end=args.end)
        summaries[f"{days}d"] = summary
        pd.DataFrame(asdict(trade) for trade in runner.trades).to_csv(
            args.output / f"{days}d-trades.csv", index=False
        )
    (args.output / "summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
