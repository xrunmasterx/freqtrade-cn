from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd
import pytest

from tools import run_donchian_funding_rv_participation_half_risk_research as research


def candles_15m(rows: int = 120, breakout_index: int = 100) -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", periods=rows, freq="15min", tz="UTC")
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": [100.0] * rows,
            "high": [101.0] * rows,
            "low": [99.0] * rows,
            "close": [100.0] * rows,
            "volume": [100.0] * rows,
        }
    )
    frame.loc[breakout_index, ["open", "high", "low", "close", "volume"]] = [
        100.0,
        101.6,
        99.5,
        101.5,
        80.0,
    ]
    return frame


def funding_frame(*rows: tuple[pd.Timestamp, float]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["date", "funding_rate"])


def funding_schedule(
    entry: pd.Timestamp, *, hours: int = 48, rate: float = 0.0
) -> pd.DataFrame:
    dates = pd.date_range(entry, entry + pd.Timedelta(hours=hours), freq="8h", tz="UTC")
    return funding_frame(*((date, rate) for date in dates))


def execution_bars(
    entry: pd.Timestamp, *, periods: int = 577, price: float = 100.0
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range(entry, periods=periods, freq="5min", tz="UTC"),
            "open": [price] * periods,
            "high": [price] * periods,
            "low": [price] * periods,
            "close": [price] * periods,
        }
    )


def event_at(
    entry: pd.Timestamp, direction: int = 1, passes_f5: bool = True
) -> research.Event:
    return research.Event(
        signal_time=entry - pd.Timedelta(minutes=15),
        decision_time=entry,
        direction=direction,
        rv24=0.01,
        funding_rate=-0.001 * direction,
        clv=0.8 * direction,
        body_atr=0.5,
        relative_volume=1.0,
        passes_f3=True,
        passes_a=True,
        passes_b=True,
        passes_f5=passes_f5,
    )


def metric(marker: int) -> research.Metrics:
    return research.Metrics(
        trades=marker,
        long_trades=marker,
        short_trades=marker,
        wins=marker,
        losses=1,
        win_rate=0.5,
        strict_payoff=2.0,
        profit_factor=2.0,
        net_profit_abs=1.0,
        account_drawdown=0.1,
        left_open=0,
    )


def test_half_risk_stop_formulas_are_frozen_for_long_and_short() -> None:
    assert research.half_risk_stop_price(1, 100.0) == pytest.approx(99.25)
    assert research.half_risk_stop_price(-1, 100.0) == pytest.approx(100.75)


@pytest.mark.parametrize(
    ("high", "low", "reason", "price"),
    [
        (101.5, 98.0, "stop", 98.5),
        (104.0, 99.0, "target", 104.0),
    ],
)
def test_activation_bar_keeps_old_stop_and_target_priority(
    high: float, low: float, reason: str, price: float
) -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    bars = execution_bars(entry)
    bars.loc[0, ["high", "low", "close"]] = [high, low, 100.0]

    trade = research.simulate_trade(
        event_at(entry),
        bars,
        funding_frame((entry - pd.Timedelta(hours=1), 0.0)),
        wallet=1000.0,
        fee_rate=0.0,
    )

    assert trade.exit_time == entry
    assert trade.exit_reason == reason
    assert trade.exit_price == pytest.approx(price)


def test_half_risk_stop_starts_on_the_next_bar_and_never_uses_break_even() -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    bars = execution_bars(entry)
    bars.loc[0, ["high", "low", "close"]] = [101.5, 99.0, 101.0]
    bars.loc[1, ["open", "high", "low", "close"]] = [100.0, 100.5, 99.0, 99.5]

    trade = research.simulate_trade(
        event_at(entry),
        bars,
        funding_frame((entry - pd.Timedelta(hours=1), 0.0)),
        wallet=1000.0,
        fee_rate=0.0,
    )

    assert trade.exit_time == entry + pd.Timedelta(minutes=5)
    assert trade.exit_reason == "stop"
    assert trade.exit_price == pytest.approx(99.25)


@pytest.mark.parametrize(
    ("direction", "second_bar", "reason", "price"),
    [
        (1, [99.0, 100.0, 98.0, 99.0], "stop_gap", 99.0),
        (-1, [101.5, 102.0, 100.0, 101.5], "stop_gap", 101.5),
    ],
)
def test_half_risk_gap_uses_worse_open(
    direction: int, second_bar: list[float], reason: str, price: float
) -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    bars = execution_bars(entry)
    if direction == 1:
        bars.loc[0, ["high", "close"]] = [101.5, 101.0]
    else:
        bars.loc[0, ["low", "close"]] = [98.5, 99.0]
    bars.loc[1, ["open", "high", "low", "close"]] = second_bar

    trade = research.simulate_trade(
        event_at(entry, direction),
        bars,
        funding_frame((entry - pd.Timedelta(hours=1), 0.0)),
        wallet=1000.0,
        fee_rate=0.0,
    )

    assert trade.exit_reason == reason
    assert trade.exit_price == price


def test_half_risk_intrabar_double_touch_is_stop_first() -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    bars = execution_bars(entry)
    bars.loc[0, ["high", "close"]] = [101.5, 101.0]
    bars.loc[1, ["open", "high", "low", "close"]] = [100.0, 104.0, 99.0, 100.0]

    trade = research.simulate_trade(
        event_at(entry),
        bars,
        funding_frame((entry - pd.Timedelta(hours=1), 0.0)),
        wallet=1000.0,
        fee_rate=0.0,
    )

    assert trade.exit_reason == "stop"
    assert trade.exit_price == pytest.approx(99.25)


def test_deadline_open_precedes_deadline_bar_range() -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    bars = execution_bars(entry)
    bars.loc[576, ["open", "high", "low", "close"]] = [100.5, 105.0, 98.0, 102.0]

    trade = research.simulate_trade(
        event_at(entry),
        bars,
        funding_schedule(entry),
        wallet=1000.0,
        fee_rate=0.0,
    )

    assert trade.exit_time == entry + pd.Timedelta(hours=48)
    assert trade.exit_reason == "max_hold_48h"
    assert trade.exit_price == 100.5


def test_three_fee_scenarios_use_the_same_stop_price_and_time_but_different_accounting() -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    bars = execution_bars(entry)
    bars.loc[0, ["high", "close"]] = [101.5, 101.0]
    bars.loc[1, ["open", "high", "low", "close"]] = [100.0, 100.5, 99.0, 99.5]
    funding = funding_frame((entry - pd.Timedelta(hours=1), 0.0))

    trades = [
        research.simulate_trade(
            event_at(entry), bars, funding, wallet=1000.0, fee_rate=fee_rate
        )
        for fee_rate in research.FEE_SCENARIOS.values()
    ]

    assert {trade.exit_time for trade in trades} == {entry + pd.Timedelta(minutes=5)}
    assert {trade.exit_price for trade in trades} == {99.25}
    assert len({trade.profit_abs for trade in trades}) == 3


def test_funding_changes_net_but_not_the_stop() -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    exit_time = entry + pd.Timedelta(minutes=5)
    bars = execution_bars(entry)
    bars.loc[0, ["high", "close"]] = [101.5, 101.0]
    bars.loc[1, ["open", "high", "low", "close"]] = [100.0, 100.5, 99.0, 99.5]
    no_funding = funding_frame((entry - pd.Timedelta(hours=1), 0.0))
    paid_funding = funding_frame(
        (entry - pd.Timedelta(hours=1), 0.0),
        (exit_time, 0.001),
    )

    without = research.simulate_trade(
        event_at(entry), bars, no_funding, wallet=1000.0, fee_rate=0.0006
    )
    with_funding = research.simulate_trade(
        event_at(entry), bars, paid_funding, wallet=1000.0, fee_rate=0.0006
    )

    assert with_funding.exit_time == without.exit_time
    assert with_funding.exit_price == without.exit_price == 99.25
    assert with_funding.funding_cash == pytest.approx(-1.0)
    assert with_funding.profit_abs == pytest.approx(without.profit_abs - 1.0)


def test_event_builder_and_candidate_selector_are_exactly_f5() -> None:
    assert research.Event is research.f5.Event
    assert research.build_events is research.f5.build_events
    events = research.build_events(
        candles_15m(),
        funding_frame((pd.Timestamp("2022-12-31", tz="UTC"), -0.001)),
    )

    assert len(events) == 1
    assert events[0].passes_f3 and events[0].passes_a and events[0].passes_b
    assert research.candidate_selector(events[0]) == events[0].passes_f5


def test_accept_all_differs_only_by_selector(monkeypatch) -> None:
    events = [
        event_at(pd.Timestamp("2023-03-01T00:00:00Z"), passes_f5=True),
        event_at(pd.Timestamp("2023-03-04T00:00:00Z"), passes_f5=False),
    ]
    calls: list[tuple[float, tuple[bool, ...]]] = []
    frames = (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    monkeypatch.setattr(research, "verify_runtime_freeze", lambda value: {"sha": value})
    monkeypatch.setattr(research, "_read_development_inputs", lambda: frames)
    monkeypatch.setattr(research, "cross_timeframe_audit", lambda *_args: {"checked": 1})
    monkeypatch.setattr(research, "build_events", lambda *_args: events)

    def fake_simulate(_events, _five, _funding, *, fee_rate, selector, **_kwargs):
        calls.append((fee_rate, tuple(selector(event) for event in events)))
        return len(calls)

    metrics = {1: metric(11), 2: metric(12), 3: metric(13), 4: metric(14)}
    monkeypatch.setattr(research, "simulate_portfolio", fake_simulate)
    monkeypatch.setattr(research, "calculate_metrics", lambda token: metrics[token])
    monkeypatch.setattr(
        research, "development_gate", lambda *_args: {"status": "SYNTHETIC_GATE"}
    )

    result = research.run_development("a" * 64)

    assert calls == [
        (0.0006, (True, False)),
        (0.0010, (True, False)),
        (0.0015, (True, False)),
        (0.0006, (True, True)),
    ]
    assert result["candidate"]["severe"] == asdict(metrics[3])
    assert result["accept_all_baseline"] == asdict(metrics[4])
    assert result["subsequent_stage_authorized"] is False


def test_same_exit_timestamp_can_reenter_after_long_tie_priority() -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    bars = execution_bars(entry)
    bars.loc[0, ["high", "low", "close"]] = [104.0, 99.0, 103.0]

    portfolio = research.simulate_portfolio(
        [event_at(entry, -1), event_at(entry, 1)],
        bars,
        funding_schedule(entry),
        fee_rate=0.0,
        selector=research.accept_all_selector,
        stage_end=entry + pd.Timedelta(days=3),
    )

    assert [trade.direction for trade in portfolio.trades] == [1, -1]
    assert [trade.exit_time for trade in portfolio.trades] == [entry, entry]
    assert portfolio.ignored_while_open == 0


def test_development_gate_is_unchanged_and_any_failure_rejects() -> None:
    assert research.development_gate is research.f5.development_gate
    baseline = replace(
        metric(30),
        long_trades=15,
        short_trades=15,
        profit_factor=2.0,
        account_drawdown=0.10,
    )
    stress = replace(metric(30), profit_factor=1.1, account_drawdown=0.20)
    accept_all = replace(metric(40), profit_factor=1.84, account_drawdown=0.10)

    passed = research.development_gate(baseline, stress, accept_all)
    rejected = research.development_gate(
        replace(baseline, profit_factor=1.98), stress, accept_all
    )

    assert passed["status"] == "DEVELOPMENT_PASSED"
    assert all(passed["checks"].values())
    assert rejected["status"] == "DEVELOPMENT_REJECTED"
    assert not rejected["checks"]["relative_profit_factor_plus_0_15"]


def write_synthetic_freeze(repo_root: Path) -> Path:
    for relative in research.EXPECTED_BINDINGS.values():
        if relative == research.f5.f3.MANIFEST_RELATIVE:
            continue
        path = repo_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.as_posix().encode())
    execution_inputs = {}
    derived = {}
    sources = {}
    for role, relative in research.INPUT_RELATIVE.items():
        path = repo_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"derived-{role}".encode())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        execution_inputs[role] = {"path": relative.as_posix(), "sha256": digest}
        derived[role] = {
            "path": relative.as_posix(),
            "sha256": digest,
            "rows": 1,
            "first": "2023-01-01T00:00:00+00:00",
            "last": "2023-01-01T00:00:00+00:00",
        }
        sources[role] = {
            "path": f"identity-source/{role}.feather",
            "sha256": hashlib.sha256(f"source-{role}".encode()).hexdigest(),
        }
    manifest = repo_root / research.f5.f3.MANIFEST_RELATIVE
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "purpose": "physical-development-snapshot-only",
                "cutoff_exclusive": research.DEVELOPMENT_END.isoformat(),
                "source_snapshot": sources,
                "derived_snapshot": derived,
            }
        ),
        encoding="utf-8",
    )
    bindings = {
        name: {
            "path": relative.as_posix(),
            "sha256": research.sha256(repo_root / relative),
        }
        for name, relative in research.EXPECTED_BINDINGS.items()
    }
    freeze_path = repo_root / "FREEZE.json"
    freeze_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "FROZEN",
                "bindings": bindings,
                "execution_inputs": execution_inputs,
            }
        ),
        encoding="utf-8",
    )
    return freeze_path


def test_freeze_binds_f6_f5_f3_manifest_inputs_and_fails_on_tamper(tmp_path) -> None:
    freeze_path = write_synthetic_freeze(tmp_path)
    freeze_sha256 = research.sha256(freeze_path)
    frozen = research.verify_runtime_freeze(
        freeze_sha256, freeze_path=freeze_path, repo_root=tmp_path
    )

    assert set(frozen["bindings"]) == set(research.EXPECTED_BINDINGS)
    f5_freeze = tmp_path / research.F5_FREEZE_RELATIVE
    f5_freeze.write_bytes(f5_freeze.read_bytes() + b"tampered")
    with pytest.raises(research.InvalidStage, match="f5_base_freeze"):
        research.verify_runtime_freeze(
            freeze_sha256, freeze_path=freeze_path, repo_root=tmp_path
        )


def test_default_command_only_prints_plan(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        research,
        "run_development",
        lambda _sha: (_ for _ in ()).throw(AssertionError("performance must not run")),
    )

    assert research.main([]) == 0
    output = capsys.readouterr().out
    assert '"default_executes_performance": false' in output
    assert '"accept_all_uses_same_half_risk_execution": true' in output


@pytest.mark.parametrize("stage", ["validation", "pseudo-oos"])
def test_unauthorized_stages_fail_before_any_input_read(
    monkeypatch, stage: str
) -> None:
    monkeypatch.setattr(
        research,
        "_read_development_inputs",
        lambda: (_ for _ in ()).throw(AssertionError("later stage read inputs")),
    )

    with pytest.raises(research.InvalidStage, match="not authorized"):
        research.main(["--stage", stage])
