from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STRATEGY_DIR = ROOT / "ft_userdata" / "user_data" / "strategies"
sys.path.insert(0, str(ROOT / "freqtrade"))
sys.path.insert(0, str(STRATEGY_DIR))

from TimeframeBreakoutFullHistoryStrategy import prepare_breakout_frame

DATA_ROOT = (
    ROOT
    / "ft_userdata"
    / "user_data"
    / "data"
    / "okx-btc-usdt-swap-full-20260813"
    / "market-data"
    / "futures"
)
DEFAULT_OUTPUT = (
    ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "backtest_results"
    / "goal-100pct"
    / "timeframe-breakout-full-history"
)
STRATEGY_FILE = STRATEGY_DIR / "TimeframeBreakoutFullHistoryStrategy.py"
RUNNER_FILE = Path(__file__).resolve()

BASE_FILE = DATA_ROOT / "BTC_USDT_USDT-5m-futures.feather"
NATIVE_FILES = {
    "15m": DATA_ROOT / "BTC_USDT_USDT-15m-futures.feather",
    "1h": DATA_ROOT / "BTC_USDT_USDT-1h-futures.feather",
}
MARK_FILE = DATA_ROOT / "BTC_USDT_USDT-1h-mark.feather"
FUNDING_FILE = DATA_ROOT / "BTC_USDT_USDT-1h-funding_rate.feather"

TIMEFRAMES = ("5m", "15m", "30m", "1h", "2h", "4h")
TIMEFRAME_MINUTES = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240}
RESAMPLE_RULES = {"30m": "30min", "2h": "2h", "4h": "4h"}
TICK_SIZE = 0.1
TRAIL_MULTIPLIER = 2.5
INITIAL_CAPITAL = 1000.0
TAKER_FEE = 0.0005
BASE_SLIPPAGE = 0.0001
STRESS_SLIPPAGES = (0.0003, 0.0005)
MAINTENANCE_MARGIN_RATE = 0.005
HOURLY_FUNDING_PRESSURE = 0.0000042304172276700455

STAGES = {
    "development": (
        pd.Timestamp("2022-03-01T00:00:00Z"),
        pd.Timestamp("2024-01-01T00:00:00Z"),
    ),
    "validation": (
        pd.Timestamp("2024-01-01T00:00:00Z"),
        pd.Timestamp("2025-01-01T00:00:00Z"),
    ),
    "oos": (
        pd.Timestamp("2025-01-01T00:00:00Z"),
        pd.Timestamp("2026-08-12T19:10:00Z"),
    ),
}

PathModel = Literal["documented", "adverse", "favorable"]
TrailMode = Literal["tick", "price"]


@dataclass(frozen=True)
class Variant:
    timeframe: str
    trail_mode: TrailMode
    hard_stop_atr: float | None
    original_pine: bool = False

    @property
    def name(self) -> str:
        hard = "none" if self.hard_stop_atr is None else f"{self.hard_stop_atr:g}atr"
        prefix = "original" if self.original_pine else "candidate"
        return f"{prefix}-{self.timeframe}-{self.trail_mode}-hard-{hard}"


@dataclass
class Position:
    direction: int
    entry_time: pd.Timestamp
    entry_mid: float
    entry_price: float
    entry_atr: float
    quantity: float
    equity_before_entry: float
    hard_stop_price: float | None
    trail_offset: float | None = None
    trail_active: bool = False
    best_price: float | None = None
    trail_stop_price: float | None = None
    fees: float = 0.0
    slippage_cost: float = 0.0
    funding: float = 0.0


@dataclass
class ClosedTrade:
    direction: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    quantity: float
    net_profit: float
    net_profit_ratio: float
    fees: float
    slippage_cost: float
    funding: float
    exit_reason: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_feather(path: Path) -> pd.DataFrame:
    dataframe = pd.read_feather(path)
    dataframe["date"] = pd.to_datetime(dataframe["date"], utc=True)
    return dataframe.sort_values("date").reset_index(drop=True)


def resample_ohlcv(base: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    rule = RESAMPLE_RULES[timeframe]
    expected = TIMEFRAME_MINUTES[timeframe] // 5
    indexed = base.set_index("date")
    grouped = indexed.resample(rule, label="left", closed="left", origin="epoch")
    result = grouped.agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    counts = grouped["close"].count()
    result = result.loc[counts == expected].reset_index()
    return result


def load_main_frames(base: pd.DataFrame) -> dict[str, pd.DataFrame]:
    frames = {
        "5m": base.copy(),
        "15m": load_feather(NATIVE_FILES["15m"]),
        "1h": load_feather(NATIVE_FILES["1h"]),
    }
    for timeframe in RESAMPLE_RULES:
        frames[timeframe] = resample_ohlcv(base, timeframe)
    return {
        timeframe: prepare_breakout_frame(frames[timeframe])
        for timeframe in TIMEFRAMES
    }


def aggregation_receipt(base: pd.DataFrame) -> dict[str, dict]:
    receipt: dict[str, dict] = {}
    indexed = base.set_index("date")
    for timeframe, native_file in NATIVE_FILES.items():
        rule = "15min" if timeframe == "15m" else "1h"
        expected = TIMEFRAME_MINUTES[timeframe] // 5
        grouped = indexed.resample(rule, label="left", closed="left", origin="epoch")
        rebuilt = grouped.agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        rebuilt = rebuilt.loc[grouped["close"].count() == expected]
        native = load_feather(native_file).set_index("date")
        joined = rebuilt.join(native, lsuffix="_resampled", rsuffix="_native", how="inner")
        joined = joined.loc[STAGES["development"][0] : STAGES["oos"][1]]
        columns: dict[str, dict] = {}
        for column in ("open", "high", "low", "close", "volume"):
            delta = (
                joined[f"{column}_resampled"] - joined[f"{column}_native"]
            ).abs()
            columns[column] = {
                "mismatches_gt_1e-9": int((delta > 1e-9).sum()),
                "max_absolute_difference": float(delta.max()),
            }
        receipt[timeframe] = {
            "common_rows": len(joined),
            "columns": columns,
        }
    return receipt


def build_funding_events(
    funding: pd.DataFrame,
    mark: pd.DataFrame,
) -> tuple[dict[pd.Timestamp, tuple[float, float]], int]:
    mark_prices = mark.set_index("date")["open"].sort_index()
    events: dict[pd.Timestamp, tuple[float, float]] = {}
    missing_marks = 0
    for row in funding.itertuples(index=False):
        timestamp = pd.Timestamp(row.date)
        if timestamp in mark_prices.index:
            mark_price = float(mark_prices.loc[timestamp])
        else:
            prior = mark_prices.loc[:timestamp]
            if prior.empty:
                missing_marks += 1
                continue
            mark_price = float(prior.iloc[-1])
            missing_marks += 1
        events[timestamp] = (float(row.open), mark_price)
    return events, missing_marks


def funding_pressure_events(
    actual: dict[pd.Timestamp, tuple[float, float]],
    mark: pd.DataFrame,
    hourly_shift: float,
) -> dict[pd.Timestamp, tuple[float, float]]:
    events = dict(actual)
    for row in mark.itertuples(index=False):
        timestamp = pd.Timestamp(row.date)
        actual_rate = events.get(timestamp, (0.0, float(row.open)))[0]
        events[timestamp] = (actual_rate + hourly_shift, float(row.open))
    return events


class BreakoutSimulator:
    def __init__(
        self,
        *,
        variant: Variant,
        main_frame: pd.DataFrame,
        detail_frame: pd.DataFrame,
        funding_events: dict[pd.Timestamp, tuple[float, float]],
        start: pd.Timestamp,
        end: pd.Timestamp,
        fee: float = TAKER_FEE,
        slippage: float = BASE_SLIPPAGE,
        path_model: PathModel = "documented",
        leverage: float = 1.0,
        record_curve: bool = False,
    ) -> None:
        self.variant = variant
        self.fee = fee
        self.slippage = slippage
        self.path_model = path_model
        self.leverage = leverage
        self.start = start
        self.end = end
        self.cash = INITIAL_CAPITAL
        self.position: Position | None = None
        self.trades: list[ClosedTrade] = []
        self.total_fees = 0.0
        self.total_slippage = 0.0
        self.total_funding = 0.0
        self.funding_events_applied = 0
        self.liquidations = 0
        self.peak_equity = INITIAL_CAPITAL
        self.max_drawdown = 0.0
        self.record_curve = record_curve
        self.curve: list[tuple[pd.Timestamp, float]] = []

        minutes = TIMEFRAME_MINUTES[variant.timeframe]
        main = main_frame.copy()
        main["close_time"] = main["date"] + pd.Timedelta(minutes=minutes)
        main = main.loc[(main["close_time"] > start) & (main["close_time"] < end)]
        self.main_events = {
            pd.Timestamp(row.close_time): row for row in main.itertuples(index=False)
        }
        self.detail = detail_frame.loc[
            (detail_frame["date"] >= start) & (detail_frame["date"] < end)
        ]
        self.funding_events = funding_events

    def _fill_price(self, mid: float, buy: bool) -> float:
        return mid * (1.0 + self.slippage if buy else 1.0 - self.slippage)

    def _marked_equity(self, price: float) -> float:
        if self.position is None:
            return self.cash
        unrealized = (
            self.position.direction
            * self.position.quantity
            * (price - self.position.entry_price)
        )
        return self.cash + unrealized

    def _record_equity(self, timestamp: pd.Timestamp, price: float) -> None:
        equity = max(0.0, self._marked_equity(price))
        self.peak_equity = max(self.peak_equity, equity)
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - equity) / self.peak_equity
            self.max_drawdown = max(self.max_drawdown, drawdown)
        if self.record_curve:
            self.curve.append((timestamp, equity))

    def _open_position(
        self,
        direction: int,
        timestamp: pd.Timestamp,
        mid_price: float,
        atr: float,
    ) -> None:
        if self.cash <= 0 or not np.isfinite(atr):
            return
        buy = direction > 0
        fill = self._fill_price(mid_price, buy=buy)
        equity_before = self.cash
        quantity = equity_before * self.leverage / fill
        fee = quantity * fill * self.fee
        slippage_cost = quantity * abs(fill - mid_price)
        self.cash -= fee
        hard_stop = None
        if self.variant.hard_stop_atr is not None:
            distance = atr * self.variant.hard_stop_atr
            hard_stop = fill - direction * distance
        self.position = Position(
            direction=direction,
            entry_time=timestamp,
            entry_mid=mid_price,
            entry_price=fill,
            entry_atr=atr,
            quantity=quantity,
            equity_before_entry=equity_before,
            hard_stop_price=hard_stop,
            fees=fee,
            slippage_cost=slippage_cost,
        )
        self.total_fees += fee
        self.total_slippage += slippage_cost

    def _close_position(
        self,
        timestamp: pd.Timestamp,
        mid_price: float,
        reason: str,
        *,
        liquidated: bool = False,
    ) -> None:
        position = self.position
        if position is None:
            return
        if liquidated:
            exit_price = mid_price
            fee = 0.0
            slippage_cost = 0.0
            self.cash = 0.0
            self.liquidations += 1
        else:
            buy = position.direction < 0
            exit_price = self._fill_price(mid_price, buy=buy)
            fee = position.quantity * exit_price * self.fee
            slippage_cost = position.quantity * abs(exit_price - mid_price)
            self.cash += (
                position.direction
                * position.quantity
                * (exit_price - position.entry_price)
                - fee
            )
            self.total_fees += fee
            self.total_slippage += slippage_cost
        position.fees += fee
        position.slippage_cost += slippage_cost
        net_profit = self.cash - position.equity_before_entry
        ratio = net_profit / position.equity_before_entry
        self.trades.append(
            ClosedTrade(
                direction="long" if position.direction > 0 else "short",
                entry_time=position.entry_time.isoformat(),
                exit_time=timestamp.isoformat(),
                entry_price=position.entry_price,
                exit_price=exit_price,
                quantity=position.quantity,
                net_profit=net_profit,
                net_profit_ratio=ratio,
                fees=position.fees,
                slippage_cost=position.slippage_cost,
                funding=position.funding,
                exit_reason=reason,
            )
        )
        self.position = None

    def _liquidation_price(self) -> float | None:
        position = self.position
        if position is None or position.quantity <= 0:
            return None
        quantity = position.quantity
        if position.direction > 0:
            numerator = quantity * position.entry_price - self.cash
            denominator = quantity * (1.0 - MAINTENANCE_MARGIN_RATE)
        else:
            numerator = self.cash + quantity * position.entry_price
            denominator = quantity * (1.0 + MAINTENANCE_MARGIN_RATE)
        price = numerator / denominator
        return price if price > 0 else None

    def _active_stop(self) -> float | None:
        position = self.position
        if position is None:
            return None
        if position.trail_active:
            return position.trail_stop_price
        return position.hard_stop_price

    def _gap_exit(self, timestamp: pd.Timestamp, opening: float) -> bool:
        position = self.position
        if position is None:
            return False
        liquidation = self._liquidation_price()
        if liquidation is not None:
            breached = opening <= liquidation if position.direction > 0 else opening >= liquidation
            if breached:
                self._close_position(timestamp, opening, "liquidation", liquidated=True)
                return True
        stop = self._active_stop()
        if stop is not None:
            breached = opening <= stop if position.direction > 0 else opening >= stop
            if breached:
                self._close_position(timestamp, opening, "gap_stop")
                return True
        return False

    def _activate_trail(self, price: float) -> None:
        position = self.position
        if position is None or position.trail_offset is None:
            return
        position.trail_active = True
        position.best_price = price
        position.trail_stop_price = price - position.direction * position.trail_offset

    def _move_trail(self, price: float) -> None:
        position = self.position
        if position is None or not position.trail_active:
            return
        if position.best_price is None or (
            position.direction * price > position.direction * position.best_price
        ):
            position.best_price = price
            candidate = price - position.direction * float(position.trail_offset)
            if position.trail_stop_price is None:
                position.trail_stop_price = candidate
            elif position.direction > 0:
                position.trail_stop_price = max(position.trail_stop_price, candidate)
            else:
                position.trail_stop_price = min(position.trail_stop_price, candidate)

    def _segment_exit_price(self, previous: float, price: float) -> tuple[float, str] | None:
        position = self.position
        if position is None:
            return None
        adverse = position.direction * price < position.direction * previous
        if not adverse:
            return None
        thresholds: list[tuple[float, str]] = []
        stop = self._active_stop()
        liquidation = self._liquidation_price()
        for threshold, reason in ((stop, "stop"), (liquidation, "liquidation")):
            if threshold is None:
                continue
            crossed = (
                price <= threshold <= previous
                if position.direction > 0
                else previous <= threshold <= price
            )
            if crossed:
                thresholds.append((threshold, reason))
        if not thresholds:
            return None
        if position.direction > 0:
            return max(thresholds, key=lambda item: item[0])
        return min(thresholds, key=lambda item: item[0])

    def _path(self, row) -> tuple[float, float, float, float]:
        opening = float(row.open)
        high = float(row.high)
        low = float(row.low)
        close = float(row.close)
        position = self.position
        if self.path_model == "documented" or position is None:
            if abs(opening - high) < abs(opening - low):
                return opening, high, low, close
            return opening, low, high, close
        favorable_first = self.path_model == "favorable"
        high_first = (position.direction > 0) == favorable_first
        return (opening, high, low, close) if high_first else (opening, low, high, close)

    def _process_detail_bar(self, row) -> None:
        timestamp = pd.Timestamp(row.date)
        opening = float(row.open)
        if self._gap_exit(timestamp, opening):
            self._record_equity(timestamp, opening)
            return

        position = self.position
        if (
            position is not None
            and not position.trail_active
            and position.trail_offset is not None
        ):
            reached = (
                opening <= position.entry_price
                if position.direction < 0
                else opening >= position.entry_price
            )
            if reached:
                self._activate_trail(opening)

        path = self._path(row)
        self._record_equity(timestamp, path[0])
        previous = path[0]
        for price in path[1:]:
            position = self.position
            if position is None:
                self._record_equity(timestamp, price)
                previous = price
                continue

            favorable = position.direction * price > position.direction * previous
            if not position.trail_active and position.trail_offset is not None and favorable:
                activation = position.entry_price
                crosses = (
                    position.direction * previous
                    < position.direction * activation
                    <= position.direction * price
                )
                if crosses:
                    self._activate_trail(activation)
                    self._move_trail(price)
            elif position.trail_active and favorable:
                self._move_trail(price)

            exit_event = self._segment_exit_price(previous, price)
            if exit_event is not None:
                exit_price, reason = exit_event
                self._close_position(
                    timestamp,
                    exit_price,
                    reason,
                    liquidated=reason == "liquidation",
                )
                self._record_equity(timestamp, exit_price)
                return
            self._record_equity(timestamp, price)
            previous = price

    def _update_trail_at_close(self, timestamp: pd.Timestamp, close: float, atr: float) -> None:
        position = self.position
        if position is None or not np.isfinite(atr):
            return
        distance = atr * TRAIL_MULTIPLIER
        if self.variant.trail_mode == "tick":
            distance *= TICK_SIZE
        position.trail_offset = distance
        if not position.trail_active:
            reached = (
                close <= position.entry_price
                if position.direction < 0
                else close >= position.entry_price
            )
            if reached:
                self._activate_trail(close)
        elif position.best_price is not None:
            candidate = position.best_price - position.direction * distance
            if position.direction > 0:
                position.trail_stop_price = max(
                    float(position.trail_stop_price), candidate
                )
            else:
                position.trail_stop_price = min(
                    float(position.trail_stop_price), candidate
                )

        stop = position.trail_stop_price if position.trail_active else None
        if stop is not None:
            crossed = close <= stop if position.direction > 0 else close >= stop
            if crossed:
                self._close_position(timestamp, close, "close_trailing_stop")

    def _process_main_close(self, timestamp: pd.Timestamp, row) -> None:
        close = float(row.close)
        atr = float(row.atr)
        desired = 1 if bool(row.long_cond) else -1 if bool(row.short_cond) else 0
        position = self.position
        if position is not None and desired != 0 and desired != position.direction:
            self._close_position(timestamp, close, "reverse")
            self._open_position(desired, timestamp, close, atr)
        elif position is None and desired != 0:
            self._open_position(desired, timestamp, close, atr)
        elif position is not None:
            self._update_trail_at_close(timestamp, close, atr)
        self._record_equity(timestamp, close)

    def _apply_funding(self, timestamp: pd.Timestamp) -> None:
        position = self.position
        event = self.funding_events.get(timestamp)
        if position is None or event is None:
            return
        rate, mark_price = event
        payment = -position.direction * position.quantity * mark_price * rate
        self.cash += payment
        position.funding += payment
        self.total_funding += payment
        self.funding_events_applied += 1

    def run(self) -> tuple[dict, list[ClosedTrade], pd.DataFrame]:
        last_timestamp: pd.Timestamp | None = None
        last_close: float | None = None
        for row in self.detail.itertuples(index=False):
            timestamp = pd.Timestamp(row.date)
            last_timestamp = timestamp + pd.Timedelta(minutes=5)
            last_close = float(row.close)
            self._apply_funding(timestamp)
            self._process_detail_bar(row)
            main_row = self.main_events.get(last_timestamp)
            if main_row is not None:
                self._process_main_close(last_timestamp, main_row)
            if self.cash <= 0 and self.position is None:
                break

        if self.position is not None and last_timestamp is not None and last_close is not None:
            self._close_position(last_timestamp, last_close, "force_exit")
            self._record_equity(last_timestamp, last_close)

        ratios = np.array([trade.net_profit_ratio for trade in self.trades], dtype=float)
        wins = ratios[ratios > 0]
        losses = ratios[ratios < 0]
        gross_profit = float(wins.sum()) if len(wins) else 0.0
        gross_loss = float(-losses.sum()) if len(losses) else 0.0
        duration_years = (self.end - self.start) / pd.Timedelta(days=365.25)
        total_return = self.cash / INITIAL_CAPITAL - 1.0
        annualized = (
            (self.cash / INITIAL_CAPITAL) ** (1.0 / duration_years) - 1.0
            if self.cash > 0 and duration_years > 0
            else -1.0
        )
        metrics = {
            "variant": self.variant.name,
            "timeframe": self.variant.timeframe,
            "trail_mode": self.variant.trail_mode,
            "hard_stop_atr": self.variant.hard_stop_atr,
            "original_pine": self.variant.original_pine,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "path_model": self.path_model,
            "leverage": self.leverage,
            "exchange_fee_per_side": self.fee,
            "slippage_per_side": self.slippage,
            "effective_cost_per_side": self.fee + self.slippage,
            "initial_capital": INITIAL_CAPITAL,
            "final_equity": self.cash,
            "total_return": total_return,
            "annualized_return": annualized,
            "max_drawdown": self.max_drawdown,
            "trades": len(ratios),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(ratios) if len(ratios) else None,
            "average_payoff": (
                float(wins.mean() / -losses.mean()) if len(wins) and len(losses) else None
            ),
            "profit_factor": gross_profit / gross_loss if gross_loss else None,
            "total_fees": self.total_fees,
            "total_slippage_cost": self.total_slippage,
            "total_funding": self.total_funding,
            "funding_events_applied": self.funding_events_applied,
            "liquidations": self.liquidations,
        }
        curve = pd.DataFrame(self.curve, columns=["date", "equity"])
        return metrics, self.trades, curve


def variants() -> list[Variant]:
    result: list[Variant] = []
    for timeframe in TIMEFRAMES:
        result.append(Variant(timeframe, "tick", None, original_pine=True))
        for trail_mode in ("tick", "price"):
            for hard_stop in (1.0, 1.5, 2.0):
                result.append(Variant(timeframe, trail_mode, hard_stop))
    return result


def run_variant(
    variant: Variant,
    *,
    stage: str,
    main_frames: dict[str, pd.DataFrame],
    detail: pd.DataFrame,
    funding_events: dict[pd.Timestamp, tuple[float, float]],
    path_model: PathModel = "documented",
    leverage: float = 1.0,
    slippage: float = BASE_SLIPPAGE,
    record_curve: bool = False,
) -> tuple[dict, list[ClosedTrade], pd.DataFrame]:
    start, end = STAGES[stage]
    simulator = BreakoutSimulator(
        variant=variant,
        main_frame=main_frames[variant.timeframe],
        detail_frame=detail,
        funding_events=funding_events,
        start=start,
        end=end,
        path_model=path_model,
        leverage=leverage,
        slippage=slippage,
        record_curve=record_curve,
    )
    return simulator.run()


def segment_pass(metrics: dict, *, validation: bool) -> bool:
    minimum_trades = 12 if validation else 30
    return bool(
        metrics["trades"] >= minimum_trades
        and metrics["total_return"] > 0
        and metrics["profit_factor"] is not None
        and metrics["profit_factor"] > 1.0
        and metrics["win_rate"] is not None
        and metrics["win_rate"] >= 0.40
        and metrics["average_payoff"] is not None
        and metrics["average_payoff"] >= 2.0
        and metrics["max_drawdown"] <= 0.40
        and metrics["liquidations"] == 0
    )


def robustness_score(development: dict, validation: dict) -> float:
    worst_growth = min(
        development["annualized_return"], validation["annualized_return"]
    )
    worst_drawdown = max(development["max_drawdown"], validation["max_drawdown"], 0.05)
    return worst_growth / worst_drawdown


def select_candidate(development: list[dict], validation: list[dict]) -> dict:
    dev_by_name = {row["variant"]: row for row in development}
    val_by_name = {row["variant"]: row for row in validation}
    rows = []
    for name in sorted(dev_by_name):
        dev = dev_by_name[name]
        val = val_by_name[name]
        eligible = segment_pass(dev, validation=False) and segment_pass(
            val, validation=True
        )
        rows.append(
            {
                "variant": name,
                "eligible": eligible,
                "score": robustness_score(dev, val),
                "development": dev,
                "validation": val,
            }
        )
    eligible_rows = [row for row in rows if row["eligible"]]
    pool = eligible_rows or rows
    selected = max(pool, key=lambda row: (row["score"], row["variant"]))
    selected["selection_status"] = "eligible" if eligible_rows else "diagnostic_only"
    return selected


def variant_from_metrics(metrics: dict) -> Variant:
    return Variant(
        timeframe=metrics["timeframe"],
        trail_mode=metrics["trail_mode"],
        hard_stop_atr=metrics["hard_stop_atr"],
        original_pine=metrics["original_pine"],
    )


def screen(
    output: Path,
    main_frames: dict[str, pd.DataFrame],
    detail: pd.DataFrame,
    funding_events: dict[pd.Timestamp, tuple[float, float]],
    manifest: dict,
) -> None:
    freeze_path = output / "freeze.json"
    if freeze_path.exists():
        raise FileExistsError(f"screen is already frozen: {freeze_path}")

    development: list[dict] = []
    validation: list[dict] = []
    for variant in variants():
        development.append(
            run_variant(
                variant,
                stage="development",
                main_frames=main_frames,
                detail=detail,
                funding_events=funding_events,
            )[0]
        )
        validation.append(
            run_variant(
                variant,
                stage="validation",
                main_frames=main_frames,
                detail=detail,
                funding_events=funding_events,
            )[0]
        )

    selected = select_candidate(development, validation)
    frozen_variant = variant_from_metrics(selected["development"])
    path_sensitivity: list[dict] = []
    for stage in ("development", "validation"):
        for path_model in ("adverse", "favorable"):
            path_sensitivity.append(
                run_variant(
                    frozen_variant,
                    stage=stage,
                    main_frames=main_frames,
                    detail=detail,
                    funding_events=funding_events,
                    path_model=path_model,
                )[0]
            )

    leverage = 1.0
    leverage_screen: list[dict] = []
    if selected["selection_status"] == "eligible":
        for candidate_leverage in (2.0, 3.0, 5.0, 8.0):
            segment_rows = []
            for stage in ("development", "validation"):
                row = run_variant(
                    frozen_variant,
                    stage=stage,
                    main_frames=main_frames,
                    detail=detail,
                    funding_events=funding_events,
                    leverage=candidate_leverage,
                )[0]
                row["stage"] = stage
                segment_rows.append(row)
                leverage_screen.append(row)
            if segment_pass(segment_rows[0], validation=False) and segment_pass(
                segment_rows[1], validation=True
            ):
                leverage = candidate_leverage
            else:
                break

    pd.DataFrame(development).to_csv(output / "development.csv", index=False)
    pd.DataFrame(validation).to_csv(output / "validation.csv", index=False)
    pd.DataFrame(path_sensitivity).to_csv(output / "screen-path-sensitivity.csv", index=False)
    pd.DataFrame(leverage_screen).to_csv(output / "leverage-screen.csv", index=False)
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    freeze = {
        "selection_protocol": {
            "candidate_grid": "six timeframes; original tick/no-hard baseline; "
            "tick or 2.5-price-ATR trail with 1/1.5/2 ATR pre-activation hard stop",
            "development_gate": "trades>=30, return>0, PF>1, win>=40%, payoff>=2, "
            "DD<=40%, no liquidation",
            "validation_gate": "trades>=12 and the same performance/risk gates",
            "ranking": "maximise min(dev annualised return, validation annualised return) "
            "/ max(dev DD, validation DD, 5%)",
            "fallback": "if no candidate passes both gates, freeze the top-scoring row as "
            "diagnostic-only and do not optimise leverage",
            "leverage": "only after 1x eligibility; test 2/3/5/8x in order and keep the "
            "largest leverage that passes both segment gates",
        },
        "selected": selected,
        "frozen_leverage": leverage,
        "screen_path_sensitivity": path_sensitivity,
        "leverage_screen": leverage_screen,
        "manifest_sha256": hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "oos_protocol": {
            "primary": {
                "path_model": "documented",
                "exchange_fee_per_side": TAKER_FEE,
                "slippage_per_side": BASE_SLIPPAGE,
            },
            "path_sensitivity": ["adverse", "favorable"],
            "slippage_stress": list(STRESS_SLIPPAGES),
            "funding_sensitivity": {
                "zero": "remove actual funding",
                "plus_hourly": HOURLY_FUNDING_PRESSURE,
                "minus_hourly": -HOURLY_FUNDING_PRESSURE,
            },
            "one_time": True,
        },
    }
    freeze_path.write_text(
        json.dumps(freeze, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def validate_frozen_manifest(output: Path, manifest: dict) -> dict:
    freeze_path = output / "freeze.json"
    if not freeze_path.exists():
        raise FileNotFoundError(f"run screen before OOS: {freeze_path}")
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    current_hash = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if freeze["manifest_sha256"] != current_hash:
        raise ValueError("strategy, runner, data, or protocol changed after freeze")
    return freeze


def oos(
    output: Path,
    main_frames: dict[str, pd.DataFrame],
    detail: pd.DataFrame,
    funding_events: dict[pd.Timestamp, tuple[float, float]],
    mark: pd.DataFrame,
    manifest: dict,
) -> None:
    result_path = output / "oos.json"
    if result_path.exists():
        raise FileExistsError(f"one-time OOS was already consumed: {result_path}")
    freeze = validate_frozen_manifest(output, manifest)
    variant = variant_from_metrics(freeze["selected"]["development"])
    leverage = float(freeze["frozen_leverage"])

    primary, trades, curve = run_variant(
        variant,
        stage="oos",
        main_frames=main_frames,
        detail=detail,
        funding_events=funding_events,
        leverage=leverage,
        record_curve=True,
    )
    sensitivities: list[dict] = []
    for path_model in ("adverse", "favorable"):
        sensitivities.append(
            run_variant(
                variant,
                stage="oos",
                main_frames=main_frames,
                detail=detail,
                funding_events=funding_events,
                path_model=path_model,
                leverage=leverage,
            )[0]
        )
    for slippage in STRESS_SLIPPAGES:
        sensitivities.append(
            run_variant(
                variant,
                stage="oos",
                main_frames=main_frames,
                detail=detail,
                funding_events=funding_events,
                leverage=leverage,
                slippage=slippage,
            )[0]
        )
    funding_scenarios = {
        "zero": {},
        "plus_hourly": funding_pressure_events(
            funding_events, mark, HOURLY_FUNDING_PRESSURE
        ),
        "minus_hourly": funding_pressure_events(
            funding_events, mark, -HOURLY_FUNDING_PRESSURE
        ),
    }
    for name, scenario_events in funding_scenarios.items():
        row = run_variant(
            variant,
            stage="oos",
            main_frames=main_frames,
            detail=detail,
            funding_events=scenario_events,
            leverage=leverage,
        )[0]
        row["funding_scenario"] = name
        sensitivities.append(row)

    pd.DataFrame(asdict(trade) for trade in trades).to_csv(
        output / "oos-trades.csv", index=False
    )
    pd.DataFrame(sensitivities).to_csv(output / "oos-sensitivities.csv", index=False)
    if not curve.empty:
        daily = curve.drop_duplicates("date", keep="last").set_index("date")
        daily = daily.resample("1D").last().dropna().reset_index()
        daily.to_csv(output / "oos-daily-equity.csv", index=False)
    result = {
        "selection_status": freeze["selected"]["selection_status"],
        "frozen_variant": variant.name,
        "frozen_leverage": leverage,
        "primary": primary,
        "sensitivities": sensitivities,
        "interpretation": (
            "candidate was eligible before OOS"
            if freeze["selected"]["selection_status"] == "eligible"
            else "diagnostic-only: no development+validation candidate passed the frozen gates"
        ),
    }
    result_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def build_manifest(
    base: pd.DataFrame,
    funding: pd.DataFrame,
    aggregation: dict,
    missing_funding_marks: int,
) -> dict:
    files = [BASE_FILE, *NATIVE_FILES.values(), MARK_FILE, FUNDING_FILE]
    return {
        "protocol_version": 1,
        "strategy_sha256": sha256_file(STRATEGY_FILE),
        "runner_sha256": sha256_file(RUNNER_FILE),
        "data_sha256": {str(path.relative_to(ROOT)): sha256_file(path) for path in files},
        "data_ranges": {
            "five_minute": {
                "rows": len(base),
                "start": base["date"].min().isoformat(),
                "end": base["date"].max().isoformat(),
            },
            "funding": {
                "rows": len(funding),
                "start": funding["date"].min().isoformat(),
                "end": funding["date"].max().isoformat(),
                "missing_exact_mark_timestamps": missing_funding_marks,
            },
        },
        "splits": {
            stage: [start.isoformat(), end.isoformat()]
            for stage, (start, end) in STAGES.items()
        },
        "execution": {
            "initial_capital": INITIAL_CAPITAL,
            "stake": "100% current equity",
            "pyramiding": 1,
            "entry_and_reversal": "confirmed main-candle close",
            "detail": "5m OHLC path; no 1m history available",
            "tick_size": TICK_SIZE,
            "trail_multiplier": TRAIL_MULTIPLIER,
            "fee_per_side": TAKER_FEE,
            "baseline_slippage_per_side": BASE_SLIPPAGE,
            "funding": "actual OKX rate at each settlement using OKX hourly mark open",
            "funding_fallback": "none; complete actual rates cover every study split",
            "funding_pressure": (
                f"zero and actual +/- {HOURLY_FUNDING_PRESSURE:.18f} per held hour"
            ),
            "liquidation": f"isolated approximation at {MAINTENANCE_MARGIN_RATE:.3%} MMR",
        },
        "aggregation_validation": aggregation,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("screen", "oos"), required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    base = load_feather(BASE_FILE)
    funding = load_feather(FUNDING_FILE)
    mark = load_feather(MARK_FILE)
    funding_events, missing_marks = build_funding_events(funding, mark)
    aggregation = aggregation_receipt(base)
    main_frames = load_main_frames(base)
    manifest = build_manifest(base, funding, aggregation, missing_marks)
    if args.phase == "screen":
        screen(args.output, main_frames, base, funding_events, manifest)
    else:
        oos(args.output, main_frames, base, funding_events, mark, manifest)


if __name__ == "__main__":
    main()
