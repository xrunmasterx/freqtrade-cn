from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path

import pandas as pd

if __package__:
    from tools import run_donchian_funding_rv_participation_breakeven_research as f5
else:
    import run_donchian_funding_rv_participation_breakeven_research as f5

REPO_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "research_data"
    / "donchian-funding-rv-participation-half-risk"
)
PREREGISTRATION = RESEARCH_ROOT / "PREREGISTRATION.md"
FREEZE = RESEARCH_ROOT / "FREEZE.json"

RUNNER_RELATIVE = Path("tools/run_donchian_funding_rv_participation_half_risk_research.py")
TEST_RELATIVE = Path("tests/test_donchian_funding_rv_participation_half_risk_research.py")
PREREGISTRATION_RELATIVE = PREREGISTRATION.relative_to(REPO_ROOT)
F5_RUNNER_RELATIVE = Path(
    "tools/run_donchian_funding_rv_participation_breakeven_research.py"
)
F5_FREEZE_RELATIVE = Path(
    "ft_userdata/user_data/research_data/"
    "donchian-funding-rv-participation-breakeven/FREEZE.json"
)
F3_RUNNER_RELATIVE = f5.F3_RUNNER_RELATIVE
F3_FREEZE_RELATIVE = f5.F3_FREEZE_RELATIVE
EXPECTED_BINDINGS = {
    "runner": RUNNER_RELATIVE,
    "tests": TEST_RELATIVE,
    "preregistration": PREREGISTRATION_RELATIVE,
    "f5_base_runner": F5_RUNNER_RELATIVE,
    "f5_base_freeze": F5_FREEZE_RELATIVE,
    "f3_base_runner": F3_RUNNER_RELATIVE,
    "f3_base_freeze": F3_FREEZE_RELATIVE,
    "development_manifest": f5.f3.MANIFEST_RELATIVE,
}
ALLOWED_INPUTS = f5.ALLOWED_INPUTS
INPUT_RELATIVE = f5.INPUT_RELATIVE

DEVELOPMENT_START = f5.DEVELOPMENT_START
DEVELOPMENT_END = f5.DEVELOPMENT_END
HOLD = f5.HOLD
INITIAL_WALLET = f5.INITIAL_WALLET
FEE_SCENARIOS = f5.FEE_SCENARIOS
BASELINE_FEE_RATE = f5.BASELINE_FEE_RATE
TRIGGER_FRACTION = f5.BREAKEVEN_TRIGGER
HALF_RISK_STOP_FRACTION = 0.0075

InvalidStage = f5.InvalidStage
Event = f5.Event
Trade = f5.Trade
Portfolio = f5.Portfolio
Metrics = f5.Metrics
sha256 = f5.sha256
build_events = f5.build_events
calculate_metrics = f5.calculate_metrics
development_gate = f5.development_gate
cross_timeframe_audit = f5.cross_timeframe_audit


def verify_runtime_freeze(
    provided_sha256: str,
    *,
    freeze_path: Path = FREEZE,
    repo_root: Path = REPO_ROOT,
) -> dict[str, object]:
    provided = f5.f3._validate_sha256(provided_sha256, "--freeze-sha256")
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
        path = f5._bound_path(repo_root, item.get("path"), expected_path)
        expected_sha256 = f5.f3._validate_sha256(
            item.get("sha256"), f"freeze {name} SHA-256"
        )
        if sha256(path) != expected_sha256:
            raise InvalidStage(f"frozen artifact hash mismatch for {name}")
        verified_paths[name] = path

    for role, expected_path in INPUT_RELATIVE.items():
        item = execution_inputs[role]
        if not isinstance(item, dict):
            raise InvalidStage(f"FREEZE.json execution input {role} is malformed")
        path = f5._bound_path(repo_root, item.get("path"), expected_path)
        expected_sha256 = f5.f3._validate_sha256(
            item.get("sha256"), f"freeze {role} SHA-256"
        )
        if sha256(path) != expected_sha256:
            raise InvalidStage(f"frozen execution input hash mismatch for {role}")

    f5.f3._verify_manifest_contract(
        verified_paths["development_manifest"], execution_inputs
    )
    return freeze


def half_risk_stop_price(direction: int, entry_price: float) -> float:
    if direction == 1:
        return entry_price * (1.0 - HALF_RISK_STOP_FRACTION)
    if direction == -1:
        return entry_price * (1.0 + HALF_RISK_STOP_FRACTION)
    raise InvalidStage("event direction must be +1 or -1")


def _exit_price(
    bars: pd.DataFrame,
    direction: int,
    entry_price: float,
    deadline: pd.Timestamp,
) -> tuple[pd.Timestamp, float, str]:
    initial_stop = entry_price * (0.985 if direction == 1 else 1.015)
    target = entry_price * (1.04 if direction == 1 else 0.96)
    trigger = entry_price * (
        1.0 + TRIGGER_FRACTION if direction == 1 else 1.0 - TRIGGER_FRACTION
    )
    fixed_stop = half_risk_stop_price(direction, entry_price)
    fixed_stop_active = False

    for row in bars.itertuples(index=False):
        if row.date == deadline:
            return row.date, float(row.open), "max_hold_48h"
        stop = fixed_stop if fixed_stop_active else initial_stop
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
        if not fixed_stop_active:
            fixed_stop_active = row.high >= trigger if direction == 1 else row.low <= trigger
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
    five = f5.f3.validate_candles(candles_5m, "5m", "5min")
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
    actual_funding = f5.f3.validate_funding_path(
        funding, event.decision_time, exit_time
    )
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


def candidate_selector(event: Event) -> bool:
    return event.passes_f5


def accept_all_selector(_event: Event) -> bool:
    return True


def simulate_portfolio(
    events: Sequence[Event],
    candles_5m: pd.DataFrame,
    funding: pd.DataFrame,
    *,
    fee_rate: float,
    selector: Callable[[Event], bool],
    stage_end: pd.Timestamp = DEVELOPMENT_END,
) -> Portfolio:
    five = f5.f3.validate_candles(candles_5m, "5m", "5min")
    actual_funding = f5.f3.validate_funding(funding)
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
    return f5._read_development_inputs()


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
                selector=candidate_selector,
            )
        )
    accept_all = calculate_metrics(
        simulate_portfolio(
            events,
            five,
            funding,
            fee_rate=BASELINE_FEE_RATE,
            selector=accept_all_selector,
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
        "research": "OKX BTC Donchian funding RV participation F6 fixed half-risk stop",
        "retrospective_only": True,
        "default_executes_performance": False,
        "development_requires_explicit_stage": True,
        "validation_authorized": False,
        "pseudo_oos_authorized": False,
        "freeze_authority": FREEZE.relative_to(REPO_ROOT).as_posix(),
        "development_requires_freeze_sha256": True,
        "accept_all_uses_same_half_risk_execution": True,
        "input_roles": {
            role: path.relative_to(REPO_ROOT).as_posix()
            for role, path in ALLOWED_INPUTS.items()
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect the frozen F6 plan or run its explicit development stage."
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
