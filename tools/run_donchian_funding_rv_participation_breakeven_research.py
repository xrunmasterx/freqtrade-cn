from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

if __package__:
    from tools import run_donchian_funding_rv_research as f3
else:
    import run_donchian_funding_rv_research as f3

REPO_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "research_data"
    / "donchian-funding-rv-participation-breakeven"
)
PREREGISTRATION = RESEARCH_ROOT / "PREREGISTRATION.md"
FREEZE = RESEARCH_ROOT / "FREEZE.json"

RUNNER_RELATIVE = Path("tools/run_donchian_funding_rv_participation_breakeven_research.py")
TEST_RELATIVE = Path("tests/test_donchian_funding_rv_participation_breakeven_research.py")
PREREGISTRATION_RELATIVE = PREREGISTRATION.relative_to(REPO_ROOT)
F3_RUNNER_RELATIVE = Path("tools/run_donchian_funding_rv_research.py")
F3_FREEZE_RELATIVE = Path(
    "ft_userdata/user_data/research_data/donchian-funding-rv/FREEZE.json"
)
EXPECTED_BINDINGS = {
    "runner": RUNNER_RELATIVE,
    "tests": TEST_RELATIVE,
    "preregistration": PREREGISTRATION_RELATIVE,
    "f3_base_runner": F3_RUNNER_RELATIVE,
    "f3_base_freeze": F3_FREEZE_RELATIVE,
    "development_manifest": f3.MANIFEST_RELATIVE,
}
ALLOWED_INPUTS = f3.ALLOWED_INPUTS
INPUT_RELATIVE = f3.INPUT_RELATIVE

DEVELOPMENT_START = f3.DEVELOPMENT_START
DEVELOPMENT_END = f3.DEVELOPMENT_END
HOLD = f3.HOLD
INITIAL_WALLET = f3.INITIAL_WALLET
FEE_SCENARIOS = f3.FEE_SCENARIOS
BASELINE_FEE_RATE = FEE_SCENARIOS["baseline"]
CLV_THRESHOLD = 0.35
BODY_ATR_THRESHOLD = 0.30
RELATIVE_VOLUME_THRESHOLD = 0.80
BREAKEVEN_TRIGGER = 0.015

InvalidStage = f3.InvalidStage
Trade = f3.Trade
Portfolio = f3.Portfolio
Metrics = f3.Metrics
sha256 = f3.sha256
calculate_metrics = f3.calculate_metrics
development_gate = f3.development_gate
cross_timeframe_audit = f3.cross_timeframe_audit


@dataclass(frozen=True)
class Event:
    signal_time: pd.Timestamp
    decision_time: pd.Timestamp
    direction: int
    rv24: float
    funding_rate: float | None
    clv: float | None
    body_atr: float | None
    relative_volume: float | None
    passes_f3: bool
    passes_a: bool
    passes_b: bool
    passes_f5: bool


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


def verify_runtime_freeze(
    provided_sha256: str,
    *,
    freeze_path: Path = FREEZE,
    repo_root: Path = REPO_ROOT,
) -> dict[str, object]:
    provided = f3._validate_sha256(provided_sha256, "--freeze-sha256")
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
    for name, expected_path in EXPECTED_BINDINGS.items():
        item = bindings[name]
        if not isinstance(item, dict):
            raise InvalidStage(f"FREEZE.json binding {name} is malformed")
        path = _bound_path(repo_root, item.get("path"), expected_path)
        expected_sha256 = f3._validate_sha256(
            item.get("sha256"), f"freeze {name} SHA-256"
        )
        if sha256(path) != expected_sha256:
            raise InvalidStage(f"frozen artifact hash mismatch for {name}")
        verified_paths[name] = path

    for role, expected_path in INPUT_RELATIVE.items():
        item = execution_inputs[role]
        if not isinstance(item, dict):
            raise InvalidStage(f"FREEZE.json execution input {role} is malformed")
        path = _bound_path(repo_root, item.get("path"), expected_path)
        expected_sha256 = f3._validate_sha256(
            item.get("sha256"), f"freeze {role} SHA-256"
        )
        if sha256(path) != expected_sha256:
            raise InvalidStage(f"frozen execution input hash mismatch for {role}")

    f3._verify_manifest_contract(verified_paths["development_manifest"], execution_inputs)
    return freeze


def compute_participation(
    candles_15m: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    if "volume" not in candles_15m.columns:
        raise InvalidStage("15m lacks required volume column")
    high = candles_15m["high"].astype(float)
    low = candles_15m["low"].astype(float)
    close = candles_15m["close"].astype(float)
    open_ = candles_15m["open"].astype(float)
    volume = candles_15m["volume"].astype(float)

    spread = high - low
    clv = ((2.0 * close - high - low) / spread).clip(-1.0, 1.0).where(spread > 0)
    previous_close = close.shift(1)
    true_range = pd.concat(
        (high - low, (high - previous_close).abs(), (low - previous_close).abs()),
        axis=1,
    ).max(axis=1)
    atr14 = true_range.ewm(alpha=1.0 / 14.0, adjust=False).mean()
    body_atr = ((close - open_).abs() / atr14).where(atr14 > 0)
    prior_volume_mean = volume.rolling(96, min_periods=96).mean().shift(1)
    relative_volume = (volume / prior_volume_mean).where(prior_volume_mean > 0)
    return clv, body_atr, relative_volume


def _finite_or_none(value: object) -> float | None:
    return None if pd.isna(value) else float(value)


def build_events(
    candles_15m: pd.DataFrame,
    funding: pd.DataFrame,
    *,
    start: pd.Timestamp = DEVELOPMENT_START,
    end: pd.Timestamp = DEVELOPMENT_END,
) -> list[Event]:
    candles = f3.validate_candles(candles_15m, "15m", "15min")
    actual_funding = f3.validate_funding(funding)
    prior_high = candles["high"].rolling(20, min_periods=20).max().shift(1)
    prior_low = candles["low"].rolling(20, min_periods=20).min().shift(1)
    long_breakout = candles["close"] > prior_high
    short_breakout = candles["close"] < prior_low
    first_long = long_breakout & ~long_breakout.shift(1, fill_value=False)
    first_short = short_breakout & ~short_breakout.shift(1, fill_value=False)
    rv24 = f3.compute_rv24(candles["close"])
    clv, body_atr, relative_volume = compute_participation(candles)

    events: list[Event] = []
    for index in candles.index[first_long | first_short]:
        signal_time = candles.at[index, "date"]
        decision_time = signal_time + pd.Timedelta(minutes=15)
        if decision_time < start or decision_time + HOLD >= end:
            continue
        direction = 1 if bool(first_long.at[index]) else -1
        rate = f3.funding_asof(actual_funding, decision_time)
        volatility = _finite_or_none(rv24.at[index])
        event_clv = _finite_or_none(clv.at[index])
        event_body_atr = _finite_or_none(body_atr.at[index])
        event_relative_volume = _finite_or_none(relative_volume.at[index])
        if volatility is None:
            continue
        passes_f3 = (
            rate is not None
            and direction * rate <= f3.FUNDING_THRESHOLD
            and volatility <= f3.RV24_THRESHOLD
        )
        passes_a = (
            event_clv is not None
            and direction * event_clv >= CLV_THRESHOLD
            and event_body_atr is not None
            and event_body_atr >= BODY_ATR_THRESHOLD
        )
        passes_b = (
            event_relative_volume is not None
            and event_relative_volume >= RELATIVE_VOLUME_THRESHOLD
        )
        events.append(
            Event(
                signal_time=signal_time,
                decision_time=decision_time,
                direction=direction,
                rv24=volatility,
                funding_rate=rate,
                clv=event_clv,
                body_atr=event_body_atr,
                relative_volume=event_relative_volume,
                passes_f3=passes_f3,
                passes_a=passes_a,
                passes_b=passes_b,
                passes_f5=passes_f3 and passes_a and passes_b,
            )
        )
    return events


def breakeven_price(direction: int, entry_price: float) -> float:
    if direction == 1:
        return entry_price * (1.0 + BASELINE_FEE_RATE) / (1.0 - BASELINE_FEE_RATE)
    if direction == -1:
        return entry_price * (1.0 - BASELINE_FEE_RATE) / (1.0 + BASELINE_FEE_RATE)
    raise InvalidStage("event direction must be +1 or -1")


def _exit_price(
    bars: pd.DataFrame,
    direction: int,
    entry_price: float,
    deadline: pd.Timestamp,
) -> tuple[pd.Timestamp, float, str]:
    initial_stop = entry_price * (0.985 if direction == 1 else 1.015)
    target = entry_price * (1.04 if direction == 1 else 0.96)
    trigger = entry_price * (1.015 if direction == 1 else 0.985)
    cost_stop = breakeven_price(direction, entry_price)
    breakeven_active = False

    for row in bars.itertuples(index=False):
        if row.date == deadline:
            return row.date, float(row.open), "max_hold_48h"
        stop = cost_stop if breakeven_active else initial_stop
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
        if not breakeven_active:
            breakeven_active = row.high >= trigger if direction == 1 else row.low <= trigger
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
    five = f3.validate_candles(candles_5m, "5m", "5min")
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
    actual_funding = f3.validate_funding_path(funding, event.decision_time, exit_time)
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
    five = f3.validate_candles(candles_5m, "5m", "5min")
    actual_funding = f3.validate_funding(funding)
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


def _read_development_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return f3._read_development_inputs()


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
                selector=lambda event: event.passes_f5,
            )
        )
    accept_all = calculate_metrics(
        simulate_portfolio(
            events,
            five,
            funding,
            fee_rate=BASELINE_FEE_RATE,
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
        "research": "OKX BTC Donchian funding RV participation F5 with 1R break-even",
        "retrospective_only": True,
        "default_executes_performance": False,
        "development_requires_explicit_stage": True,
        "validation_authorized": False,
        "pseudo_oos_authorized": False,
        "freeze_authority": FREEZE.relative_to(REPO_ROOT).as_posix(),
        "development_requires_freeze_sha256": True,
        "accept_all_uses_same_breakeven_execution": True,
        "input_roles": {
            role: path.relative_to(REPO_ROOT).as_posix()
            for role, path in ALLOWED_INPUTS.items()
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect the frozen F5 plan or run its explicit development stage."
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
