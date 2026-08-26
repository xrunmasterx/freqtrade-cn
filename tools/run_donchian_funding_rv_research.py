from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
PREREGISTRATION = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "research_data"
    / "donchian-funding-rv"
    / "PREREGISTRATION.md"
)
RESEARCH_ROOT = PREREGISTRATION.parent
FREEZE = RESEARCH_ROOT / "FREEZE.json"
DEVELOPMENT_DATA_ROOT = RESEARCH_ROOT / "development-data"
DEVELOPMENT_MANIFEST = DEVELOPMENT_DATA_ROOT / "manifest.json"
ALLOWED_INPUTS = {
    "5m": DEVELOPMENT_DATA_ROOT / "BTC_USDT_USDT-5m-futures.feather",
    "15m": DEVELOPMENT_DATA_ROOT / "BTC_USDT_USDT-15m-futures.feather",
    "funding": DEVELOPMENT_DATA_ROOT / "BTC_USDT_USDT-1h-funding_rate.feather",
}
RUNNER_RELATIVE = Path("tools/run_donchian_funding_rv_research.py")
TEST_RELATIVE = Path("tests/test_donchian_funding_rv_research.py")
PREPARER_RELATIVE = Path("tools/prepare_donchian_funding_rv_development_data.py")
PREREGISTRATION_RELATIVE = PREREGISTRATION.relative_to(REPO_ROOT)
MANIFEST_RELATIVE = DEVELOPMENT_MANIFEST.relative_to(REPO_ROOT)
INPUT_RELATIVE = {
    role: path.relative_to(REPO_ROOT) for role, path in ALLOWED_INPUTS.items()
}
EXPECTED_BINDINGS = {
    "runner": RUNNER_RELATIVE,
    "tests": TEST_RELATIVE,
    "preparer": PREPARER_RELATIVE,
    "preregistration": PREREGISTRATION_RELATIVE,
    "development_manifest": MANIFEST_RELATIVE,
}

DEVELOPMENT_START = pd.Timestamp("2022-03-01T00:00:00Z")
DEVELOPMENT_END = pd.Timestamp("2024-01-01T00:00:00Z")
HOLD = pd.Timedelta(hours=48)
MAX_FUNDING_GAP = pd.Timedelta(hours=10)
SPECIAL_FUNDING_TRANSITIONS = (
    (
        pd.Timestamp("2022-12-18T08:00:00Z"),
        pd.Timestamp("2022-12-18T18:00:00Z"),
    ),
    (
        pd.Timestamp("2022-12-18T18:00:00Z"),
        pd.Timestamp("2022-12-19T00:00:00Z"),
    ),
)
FUNDING_THRESHOLD = -0.0000352449
RV24_THRESHOLD = 0.0269415
INITIAL_WALLET = 1000.0
FEE_SCENARIOS = {"baseline": 0.0006, "stress": 0.0010, "severe": 0.0015}


class InvalidStage(RuntimeError):
    pass


@dataclass(frozen=True)
class Event:
    signal_time: pd.Timestamp
    decision_time: pd.Timestamp
    direction: int
    rv24: float
    funding_rate: float | None
    passes_f3: bool


@dataclass(frozen=True)
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: int
    quantity: float
    entry_price: float
    exit_price: float
    entry_fee: float
    exit_fee: float
    funding_cash: float
    profit_abs: float
    profit_ratio: float
    wallet_before: float
    wallet_after: float
    exit_reason: str


@dataclass(frozen=True)
class Portfolio:
    trades: tuple[Trade, ...]
    ignored_while_open: int
    left_open: int


@dataclass(frozen=True)
class Metrics:
    trades: int
    long_trades: int
    short_trades: int
    wins: int
    losses: int
    win_rate: float
    strict_payoff: float | None
    profit_factor: float | None
    net_profit_abs: float
    account_drawdown: float
    left_open: int


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise InvalidStage(f"{name} is not a lowercase SHA-256 digest")
    return value


def _bound_path(repo_root: Path, relative_path: object, expected: Path) -> Path:
    if relative_path != expected.as_posix():
        raise InvalidStage(f"freeze path differs from the frozen path: {expected.as_posix()}")
    path = (repo_root / expected).resolve()
    try:
        path.relative_to(repo_root.resolve())
    except ValueError as error:
        raise InvalidStage("freeze path escapes the repository") from error
    if not path.is_file():
        raise InvalidStage(f"frozen artifact is missing: {expected.as_posix()}")
    return path


def _verify_manifest_contract(
    manifest_path: Path, execution_inputs: dict[str, object]
) -> None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InvalidStage("development manifest is unreadable") from error
    if manifest.get("schema_version") != 1:
        raise InvalidStage("development manifest schema differs from version 1")
    if manifest.get("purpose") != "physical-development-snapshot-only":
        raise InvalidStage("development manifest purpose is not frozen")
    if manifest.get("cutoff_exclusive") != DEVELOPMENT_END.isoformat():
        raise InvalidStage("development manifest cutoff is not pre-2024")
    sources = manifest.get("source_snapshot")
    derived = manifest.get("derived_snapshot")
    if not isinstance(sources, dict) or set(sources) != set(ALLOWED_INPUTS):
        raise InvalidStage("development manifest source roles differ from the frozen set")
    if not isinstance(derived, dict) or set(derived) != set(ALLOWED_INPUTS):
        raise InvalidStage("development manifest derived roles differ from the frozen set")
    for role in ALLOWED_INPUTS:
        source = sources[role]
        item = derived[role]
        if not isinstance(source, dict) or not isinstance(item, dict):
            raise InvalidStage(f"development manifest {role} identity is malformed")
        _validate_sha256(source.get("sha256"), f"manifest source {role} SHA-256")
        frozen_input = execution_inputs[role]
        if not isinstance(frozen_input, dict):
            raise InvalidStage(f"freeze execution input {role} is malformed")
        if item.get("path") != frozen_input.get("path"):
            raise InvalidStage(f"manifest path mismatch for {role}")
        if item.get("sha256") != frozen_input.get("sha256"):
            raise InvalidStage(f"manifest SHA-256 mismatch for {role}")
        if not isinstance(item.get("rows"), int) or item["rows"] <= 0:
            raise InvalidStage(f"manifest row count is invalid for {role}")
        try:
            first = pd.Timestamp(item["first"])
            last = pd.Timestamp(item["last"])
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidStage(f"manifest timestamp is invalid for {role}") from error
        if first.tzinfo is None or last.tzinfo is None or first > last or last >= DEVELOPMENT_END:
            raise InvalidStage(f"manifest timestamps are not physical pre-2024 data for {role}")


def verify_runtime_freeze(
    provided_sha256: str,
    *,
    freeze_path: Path = FREEZE,
    repo_root: Path = REPO_ROOT,
) -> dict[str, object]:
    provided = _validate_sha256(provided_sha256, "--freeze-sha256")
    if sha256(freeze_path) != provided:
        raise InvalidStage("FREEZE.json SHA-256 mismatch")
    try:
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InvalidStage("FREEZE.json is unreadable") from error
    if freeze.get("schema_version") != 1 or freeze.get("status") != "FROZEN":
        raise InvalidStage("FREEZE.json authority is not frozen schema version 1")
    bindings = freeze.get("bindings")
    execution_inputs = freeze.get("execution_inputs")
    if not isinstance(bindings, dict) or set(bindings) != set(EXPECTED_BINDINGS):
        raise InvalidStage("FREEZE.json bindings differ from the required artifact set")
    if not isinstance(execution_inputs, dict) or set(execution_inputs) != set(ALLOWED_INPUTS):
        raise InvalidStage("FREEZE.json execution inputs differ from the required roles")

    verified_paths: dict[str, Path] = {}
    binding_order = ("development_manifest", "runner", "tests", "preparer", "preregistration")
    for name in binding_order:
        item = bindings[name]
        if not isinstance(item, dict):
            raise InvalidStage(f"FREEZE.json binding {name} is malformed")
        path = _bound_path(repo_root, item.get("path"), EXPECTED_BINDINGS[name])
        expected_sha256 = _validate_sha256(item.get("sha256"), f"freeze {name} SHA-256")
        if sha256(path) != expected_sha256:
            raise InvalidStage(f"frozen artifact hash mismatch for {name}")
        verified_paths[name] = path

    for role, expected_path in INPUT_RELATIVE.items():
        item = execution_inputs[role]
        if not isinstance(item, dict):
            raise InvalidStage(f"FREEZE.json execution input {role} is malformed")
        path = _bound_path(repo_root, item.get("path"), expected_path)
        expected_sha256 = _validate_sha256(item.get("sha256"), f"freeze {role} SHA-256")
        if sha256(path) != expected_sha256:
            raise InvalidStage(f"frozen execution input hash mismatch for {role}")

    _verify_manifest_contract(verified_paths["development_manifest"], execution_inputs)
    return freeze


def validate_input_path(role: str, path: Path) -> None:
    expected = ALLOWED_INPUTS.get(role)
    if expected is None or path.resolve() != expected.resolve():
        raise InvalidStage(f"input path is not the frozen {role} whitelist member")


def _utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True)


def _validate_timestamp_order(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    if frame.empty:
        raise InvalidStage(f"{name} input is empty")
    result = frame.copy()
    result["date"] = _utc(result["date"])
    if result["date"].duplicated().any() or not result["date"].is_monotonic_increasing:
        raise InvalidStage(f"{name} timestamps are duplicated or out of order")
    if result["date"].max() >= DEVELOPMENT_END:
        raise InvalidStage(f"{name} physical input contains a timestamp at or after 2024-01-01")
    return result


def validate_candles(frame: pd.DataFrame, name: str, frequency: str) -> pd.DataFrame:
    required = {"date", "open", "high", "low", "close"}
    if not required.issubset(frame.columns):
        raise InvalidStage(f"{name} lacks required OHLC columns")
    result = _validate_timestamp_order(frame, name)
    if result[list(required - {"date"})].isna().any().any():
        raise InvalidStage(f"{name} contains missing OHLC values")
    expected = pd.Timedelta(frequency)
    if len(result) > 1 and not result["date"].diff().iloc[1:].eq(expected).all():
        raise InvalidStage(f"{name} has missing or non-{frequency} candles")
    return result


def validate_funding(frame: pd.DataFrame) -> pd.DataFrame:
    if not {"date", "funding_rate"}.issubset(frame.columns):
        raise InvalidStage("funding lacks date/funding_rate columns")
    result = _validate_timestamp_order(frame, "funding")
    if result["funding_rate"].isna().any():
        raise InvalidStage("funding contains a missing actual settlement rate")
    return result


def validate_development_funding(frame: pd.DataFrame) -> pd.DataFrame:
    result = validate_funding(frame)
    dates = result["date"]
    previous = dates.loc[dates <= DEVELOPMENT_START]
    if previous.empty or DEVELOPMENT_START - previous.iloc[-1] > MAX_FUNDING_GAP:
        raise InvalidStage("funding does not cover the development window start")
    before_end = dates.loc[dates < DEVELOPMENT_END]
    if before_end.empty or DEVELOPMENT_END - before_end.iloc[-1] > MAX_FUNDING_GAP:
        raise InvalidStage("funding does not cover the development window end")
    covered = dates.loc[(dates >= previous.iloc[-1]) & (dates < DEVELOPMENT_END)]
    if covered.diff().dropna().gt(MAX_FUNDING_GAP).any():
        raise InvalidStage("funding has an internal settlement gap greater than 10 hours")
    pairs = set(zip(covered.iloc[:-1], covered.iloc[1:], strict=True))
    for transition in SPECIAL_FUNDING_TRANSITIONS:
        if transition not in pairs:
            raise InvalidStage("funding lacks the frozen official 2022-12-18 10h/6h schedule")
    return result


def validate_funding_path(
    frame: pd.DataFrame, entry_time: pd.Timestamp, exit_time: pd.Timestamp
) -> pd.DataFrame:
    result = validate_funding(frame)
    if exit_time < entry_time or exit_time - entry_time > HOLD:
        raise InvalidStage("funding path lies outside the maximum 48-hour holding period")
    dates = result["date"]
    previous = dates.loc[dates <= entry_time]
    if previous.empty or entry_time - previous.iloc[-1] > MAX_FUNDING_GAP:
        raise InvalidStage("funding path is not covered at entry")
    path_dates = dates.loc[(dates >= previous.iloc[-1]) & (dates <= exit_time)]
    if path_dates.diff().dropna().gt(MAX_FUNDING_GAP).any():
        raise InvalidStage("funding path has a settlement gap greater than 10 hours")
    if exit_time - path_dates.iloc[-1] > MAX_FUNDING_GAP:
        raise InvalidStage("funding path is not covered at exit")
    return result


def compute_rv24(close: pd.Series) -> pd.Series:
    log_return = close.astype(float).map(math.log).diff()
    return log_return.pow(2).rolling(96, min_periods=96).sum().pow(0.5)


def funding_asof(funding: pd.DataFrame, decision_time: pd.Timestamp) -> float | None:
    known = funding.loc[funding["date"] <= decision_time, "funding_rate"]
    return None if known.empty else float(known.iloc[-1])


def build_events(
    candles_15m: pd.DataFrame,
    funding: pd.DataFrame,
    *,
    start: pd.Timestamp = DEVELOPMENT_START,
    end: pd.Timestamp = DEVELOPMENT_END,
) -> list[Event]:
    candles = validate_candles(candles_15m, "15m", "15min")
    actual_funding = validate_funding(funding)
    prior_high = candles["high"].rolling(20, min_periods=20).max().shift(1)
    prior_low = candles["low"].rolling(20, min_periods=20).min().shift(1)
    long_breakout = candles["close"] > prior_high
    short_breakout = candles["close"] < prior_low
    first_long = long_breakout & ~long_breakout.shift(1, fill_value=False)
    first_short = short_breakout & ~short_breakout.shift(1, fill_value=False)
    rv24 = compute_rv24(candles["close"])

    events: list[Event] = []
    for index in candles.index[first_long | first_short]:
        signal_time = candles.at[index, "date"]
        decision_time = signal_time + pd.Timedelta(minutes=15)
        if decision_time < start or decision_time + HOLD >= end:
            continue
        direction = 1 if bool(first_long.at[index]) else -1
        rate = funding_asof(actual_funding, decision_time)
        volatility = rv24.at[index]
        if pd.isna(volatility):
            continue
        passes_f3 = (
            rate is not None
            and direction * rate <= FUNDING_THRESHOLD
            and float(volatility) <= RV24_THRESHOLD
        )
        events.append(
            Event(
                signal_time=signal_time,
                decision_time=decision_time,
                direction=direction,
                rv24=float(volatility),
                funding_rate=rate,
                passes_f3=passes_f3,
            )
        )
    return events


def cross_timeframe_audit(
    candles_5m: pd.DataFrame, candles_15m: pd.DataFrame
) -> dict[str, int]:
    five = validate_candles(candles_5m, "5m", "5min")
    fifteen = validate_candles(candles_15m, "15m", "15min")
    grouped = five.assign(bucket=five["date"].dt.floor("15min")).groupby("bucket")
    aggregate = grouped.agg(
        count=("date", "size"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    )
    official = fifteen.set_index("date")
    common = official.index.intersection(aggregate.index)
    complete = aggregate.loc[common, "count"].eq(3)
    compared = common[complete]
    mismatches = 0
    for timestamp in compared:
        if any(
            not math.isclose(
                float(official.at[timestamp, column]),
                float(aggregate.at[timestamp, column]),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            for column in ("open", "high", "low", "close")
        ):
            mismatches += 1
    return {
        "official_15m_rows": len(official),
        "compared_rows": len(compared),
        "revision_mismatch_rows": mismatches,
        "missing_or_incomplete_5m_groups": len(official) - len(compared),
    }


def _exit_price(
    bars: pd.DataFrame, direction: int, entry_price: float, deadline: pd.Timestamp
) -> tuple[pd.Timestamp, float, str]:
    stop = entry_price * (0.985 if direction == 1 else 1.015)
    target = entry_price * (1.04 if direction == 1 else 0.96)
    for row in bars.itertuples(index=False):
        if row.date == deadline:
            return row.date, float(row.open), "max_hold_48h"
        stop_gap = row.open <= stop if direction == 1 else row.open >= stop
        target_gap = row.open >= target if direction == 1 else row.open <= target
        if stop_gap:
            return row.date, float(row.open), "stop_gap"
        if target_gap:
            return row.date, target, "target_gap"
        stop_hit = row.low <= stop if direction == 1 else row.high >= stop
        target_hit = row.high >= target if direction == 1 else row.low <= target
        if stop_hit:
            return row.date, stop, "stop"
        if target_hit:
            return row.date, target, "target"
    raise InvalidStage("5m execution path ends before a deterministic exit")


def simulate_trade(
    event: Event,
    candles_5m: pd.DataFrame,
    funding: pd.DataFrame,
    *,
    wallet: float,
    fee_rate: float,
    stage_end: pd.Timestamp = DEVELOPMENT_END,
) -> Trade:
    if event.direction not in (-1, 1):
        raise InvalidStage("event direction must be +1 or -1")
    five = validate_candles(candles_5m, "5m", "5min")
    deadline = event.decision_time + HOLD
    if deadline >= stage_end:
        raise InvalidStage("trade label or holding period reaches the development boundary")
    bars = five.loc[(five["date"] >= event.decision_time) & (five["date"] <= deadline)]
    expected_rows = int(HOLD / pd.Timedelta(minutes=5)) + 1
    if len(bars) != expected_rows or bars.iloc[0]["date"] != event.decision_time:
        raise InvalidStage("5m execution path is missing an entry or holding-period candle")
    entry_price = float(bars.iloc[0]["open"])
    exit_time, exit_price, reason = _exit_price(
        bars, event.direction, entry_price, deadline
    )
    actual_funding = validate_funding_path(funding, event.decision_time, exit_time)
    quantity = wallet / entry_price
    entry_notional = quantity * entry_price
    entry_fee = entry_notional * fee_rate
    exit_fee = quantity * exit_price * fee_rate
    settled = actual_funding.loc[
        (actual_funding["date"] > event.decision_time)
        & (actual_funding["date"] <= exit_time),
        "funding_rate",
    ]
    funding_cash = -event.direction * entry_notional * float(settled.sum())
    gross = event.direction * quantity * (exit_price - entry_price)
    profit_abs = gross - entry_fee - exit_fee + funding_cash
    wallet_after = wallet + profit_abs
    if wallet_after <= 0:
        raise InvalidStage("wallet exhausted under frozen 1x cash accounting")
    return Trade(
        entry_time=event.decision_time,
        exit_time=exit_time,
        direction=event.direction,
        quantity=quantity,
        entry_price=entry_price,
        exit_price=exit_price,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        funding_cash=funding_cash,
        profit_abs=profit_abs,
        profit_ratio=profit_abs / wallet,
        wallet_before=wallet,
        wallet_after=wallet_after,
        exit_reason=reason,
    )


def simulate_portfolio(
    events: Sequence[Event],
    candles_5m: pd.DataFrame,
    funding: pd.DataFrame,
    *,
    fee_rate: float,
    selector: Callable[[Event], bool],
    stage_end: pd.Timestamp = DEVELOPMENT_END,
) -> Portfolio:
    five = validate_candles(candles_5m, "5m", "5min")
    actual_funding = validate_funding(funding)
    ordered = sorted(
        enumerate(events),
        key=lambda item: (
            item[1].decision_time,
            0 if item[1].direction == 1 else 1,
            item[0],
        ),
    )
    wallet = INITIAL_WALLET
    busy_until: pd.Timestamp | None = None
    ignored = 0
    trades: list[Trade] = []
    for _, event in ordered:
        if not selector(event):
            continue
        if busy_until is not None and event.decision_time < busy_until:
            ignored += 1
            continue
        trade = simulate_trade(
            event,
            five,
            actual_funding,
            wallet=wallet,
            fee_rate=fee_rate,
            stage_end=stage_end,
        )
        trades.append(trade)
        wallet = trade.wallet_after
        busy_until = trade.exit_time
    return Portfolio(tuple(trades), ignored, 0)


def calculate_metrics(portfolio: Portfolio) -> Metrics:
    trades = portfolio.trades
    winning_abs = [trade.profit_abs for trade in trades if trade.profit_abs > 0]
    losing_abs = [trade.profit_abs for trade in trades if trade.profit_abs < 0]
    winning_ratio = [trade.profit_ratio for trade in trades if trade.profit_ratio > 0]
    losing_ratio = [trade.profit_ratio for trade in trades if trade.profit_ratio < 0]
    profit_factor = sum(winning_abs) / abs(sum(losing_abs)) if losing_abs else None
    strict_payoff = (
        (sum(winning_ratio) / len(winning_ratio))
        / abs(sum(losing_ratio) / len(losing_ratio))
        if winning_ratio and losing_ratio
        else None
    )
    peak = INITIAL_WALLET
    max_drawdown = 0.0
    for trade in trades:
        peak = max(peak, trade.wallet_after)
        max_drawdown = max(max_drawdown, (peak - trade.wallet_after) / peak)
    return Metrics(
        trades=len(trades),
        long_trades=sum(trade.direction == 1 for trade in trades),
        short_trades=sum(trade.direction == -1 for trade in trades),
        wins=len(winning_abs),
        losses=len(losing_abs),
        win_rate=len(winning_abs) / len(trades) if trades else 0.0,
        strict_payoff=strict_payoff,
        profit_factor=profit_factor,
        net_profit_abs=sum(trade.profit_abs for trade in trades),
        account_drawdown=max_drawdown,
        left_open=portfolio.left_open,
    )


def development_gate(
    candidate_baseline: Metrics,
    candidate_stress: Metrics,
    accept_all_baseline: Metrics,
) -> dict[str, object]:
    checks = {
        "baseline_trades_gte_30": candidate_baseline.trades >= 30,
        "baseline_long_gte_5": candidate_baseline.long_trades >= 5,
        "baseline_short_gte_5": candidate_baseline.short_trades >= 5,
        "baseline_win_rate_gte_40pct": candidate_baseline.win_rate >= 0.40,
        "baseline_has_winner": candidate_baseline.wins > 0,
        "baseline_has_loser": candidate_baseline.losses > 0,
        "baseline_strict_payoff_gte_2": (
            candidate_baseline.strict_payoff is not None
            and candidate_baseline.strict_payoff >= 2.0
        ),
        "baseline_profit_factor_gt_1_2": (
            candidate_baseline.profit_factor is not None
            and candidate_baseline.profit_factor > 1.2
        ),
        "baseline_net_gt_0": candidate_baseline.net_profit_abs > 0,
        "baseline_drawdown_lt_25pct": candidate_baseline.account_drawdown < 0.25,
        "baseline_left_open_eq_0": candidate_baseline.left_open == 0,
        "stress_profit_factor_gt_1": (
            candidate_stress.profit_factor is not None
            and candidate_stress.profit_factor > 1.0
        ),
        "stress_net_gt_0": candidate_stress.net_profit_abs > 0,
        "stress_drawdown_lt_30pct": candidate_stress.account_drawdown < 0.30,
        "relative_profit_factor_plus_0_15": (
            candidate_baseline.profit_factor is not None
            and accept_all_baseline.profit_factor is not None
            and candidate_baseline.profit_factor >= accept_all_baseline.profit_factor + 0.15
        ),
        "relative_drawdown_not_higher": (
            candidate_baseline.account_drawdown <= accept_all_baseline.account_drawdown
        ),
    }
    passed = all(checks.values())
    return {
        "status": "DEVELOPMENT_PASSED" if passed else "DEVELOPMENT_REJECTED",
        "checks": checks,
    }


def _read_development_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    for role, path in ALLOWED_INPUTS.items():
        validate_input_path(role, path)
    five = validate_candles(pd.read_feather(ALLOWED_INPUTS["5m"]), "5m", "5min")
    fifteen = validate_candles(
        pd.read_feather(ALLOWED_INPUTS["15m"]), "15m", "15min"
    )
    funding_raw = pd.read_feather(ALLOWED_INPUTS["funding"], columns=["date", "open"])
    funding = funding_raw.rename(columns={"open": "funding_rate"})
    return five, fifteen, validate_development_funding(funding)


def run_development(freeze_sha256: str) -> dict[str, object]:
    verify_runtime_freeze(freeze_sha256)
    five, fifteen, funding = _read_development_inputs()
    audit = cross_timeframe_audit(five, fifteen)
    events = build_events(fifteen, funding)
    candidate: dict[str, Metrics] = {}
    for name, fee_rate in FEE_SCENARIOS.items():
        candidate[name] = calculate_metrics(
            simulate_portfolio(
                events,
                five,
                funding,
                fee_rate=fee_rate,
                selector=lambda event: event.passes_f3,
            )
        )
    accept_all = calculate_metrics(
        simulate_portfolio(
            events,
            five,
            funding,
            fee_rate=FEE_SCENARIOS["baseline"],
            selector=lambda _event: True,
        )
    )
    gate = development_gate(candidate["baseline"], candidate["stress"], accept_all)
    return {
        "stage": "development",
        "retrospective_only": True,
        "freeze_sha256": freeze_sha256,
        "cross_timeframe_audit": audit,
        "base_event_count": len(events),
        "candidate": {name: asdict(metrics) for name, metrics in candidate.items()},
        "accept_all_baseline": asdict(accept_all),
        "gate": gate,
        "subsequent_stage_authorized": False,
    }


def frozen_plan() -> dict[str, object]:
    return {
        "research": "OKX BTC Donchian funding RV F3",
        "retrospective_only": True,
        "default_executes_performance": False,
        "development_requires_explicit_stage": True,
        "validation_authorized": False,
        "pseudo_oos_authorized": False,
        "freeze_authority": FREEZE.relative_to(REPO_ROOT).as_posix(),
        "development_requires_freeze_sha256": True,
        "input_roles": {role: path.relative_to(REPO_ROOT).as_posix() for role, path in ALLOWED_INPUTS.items()},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mechanically inspect the frozen F3 plan or run its explicit development stage."
    )
    parser.add_argument("--stage", choices=("development", "validation", "pseudo-oos"))
    parser.add_argument("--freeze-sha256")
    args = parser.parse_args(argv)
    if args.stage is None:
        print(json.dumps(frozen_plan(), indent=2, sort_keys=True))
        return 0
    if args.stage != "development":
        raise InvalidStage(f"{args.stage} is fail-closed and not authorized")
    if args.freeze_sha256 is None:
        raise InvalidStage("--stage development requires --freeze-sha256")
    print(json.dumps(run_development(args.freeze_sha256), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
