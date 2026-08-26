from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd
import pytest

from tools import run_donchian_funding_rv_participation_breakeven_research as research


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


def test_a_and_b_use_closed_signal_bar_and_shifted_prior_volume() -> None:
    candles = candles_15m()
    funding = funding_frame((pd.Timestamp("2022-12-31", tz="UTC"), -0.001))

    events = research.build_events(candles, funding)

    assert len(events) == 1
    event = events[0]
    assert event.clv == pytest.approx((2 * 101.5 - 101.6 - 99.5) / (101.6 - 99.5))
    assert event.body_atr is not None and event.body_atr >= research.BODY_ATR_THRESHOLD
    assert event.relative_volume == pytest.approx(0.80)
    assert event.passes_f3 and event.passes_a and event.passes_b and event.passes_f5


def test_participation_prefix_is_invariant_to_future_mutation_and_current_volume_is_numerator() -> None:
    original = candles_15m()
    mutated = original.copy()
    mutated.loc[101:, ["open", "high", "low", "close", "volume"]] = [
        20.0,
        500.0,
        1.0,
        2.0,
        1_000_000.0,
    ]
    clv, body_atr, relative_volume = research.compute_participation(original)
    mutated_values = research.compute_participation(mutated)

    assert clv.loc[100] == mutated_values[0].loc[100]
    assert body_atr.loc[100] == mutated_values[1].loc[100]
    assert relative_volume.loc[100] == mutated_values[2].loc[100] == pytest.approx(0.8)

    lower_current = original.copy()
    lower_current.loc[100, "volume"] = 79.0
    assert research.compute_participation(lower_current)[2].loc[100] == pytest.approx(0.79)


def test_a_or_b_failure_fails_the_unique_candidate_closed() -> None:
    funding = funding_frame((pd.Timestamp("2022-12-31", tz="UTC"), -0.001))
    weak_body = candles_15m()
    weak_body.loc[100, "open"] = 101.4
    weak_volume = candles_15m()
    weak_volume.loc[100, "volume"] = 79.0

    a_event = research.build_events(weak_body, funding)[0]
    b_event = research.build_events(weak_volume, funding)[0]

    assert not a_event.passes_a and not a_event.passes_f5
    assert not b_event.passes_b and not b_event.passes_f5


def test_1r_activation_moves_stop_only_from_the_next_bar() -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    bars = execution_bars(entry)
    bars.loc[0, ["high", "low", "close"]] = [101.5, 100.0, 101.0]
    bars.loc[1, ["open", "high", "low", "close"]] = [100.5, 101.0, 100.0, 100.5]
    funding = funding_frame((entry - pd.Timedelta(hours=1), 0.0))

    trade = research.simulate_trade(
        event_at(entry), bars, funding, wallet=1000.0, fee_rate=0.0006
    )

    assert trade.exit_time == entry + pd.Timedelta(minutes=5)
    assert trade.exit_price == pytest.approx(research.breakeven_price(1, 100.0))
    assert trade.exit_reason == "stop"


def test_activation_bar_keeps_old_stop_and_stop_first_priority() -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    bars = execution_bars(entry)
    bars.loc[0, ["high", "low", "close"]] = [101.5, 98.0, 100.0]
    funding = funding_frame((entry - pd.Timedelta(hours=1), 0.0))

    trade = research.simulate_trade(
        event_at(entry), bars, funding, wallet=1000.0, fee_rate=0.0
    )

    assert trade.exit_time == entry
    assert trade.exit_reason == "stop"
    assert trade.exit_price == pytest.approx(98.5)


def test_breakeven_formulas_are_frozen_for_long_and_short() -> None:
    assert research.breakeven_price(1, 100.0) == pytest.approx(
        100.0 * 1.0006 / 0.9994
    )
    assert research.breakeven_price(-1, 100.0) == pytest.approx(
        100.0 * 0.9994 / 1.0006
    )


def test_post_activation_gap_uses_worse_open_and_intrabar_uses_breakeven_stop() -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    funding = funding_frame((entry - pd.Timedelta(hours=1), 0.0))
    gap_bars = execution_bars(entry)
    gap_bars.loc[0, ["high", "close"]] = [101.5, 101.0]
    gap_bars.loc[1, ["open", "high", "low", "close"]] = [99.0, 100.0, 98.5, 99.0]
    stop_bars = execution_bars(entry)
    stop_bars.loc[0, ["high", "close"]] = [101.5, 101.0]
    stop_bars.loc[1, ["open", "high", "low", "close"]] = [
        100.5,
        101.0,
        100.0,
        100.5,
    ]

    gap_trade = research.simulate_trade(
        event_at(entry), gap_bars, funding, wallet=1000.0, fee_rate=0.0
    )
    stop_trade = research.simulate_trade(
        event_at(entry), stop_bars, funding, wallet=1000.0, fee_rate=0.0
    )

    assert gap_trade.exit_reason == "stop_gap"
    assert gap_trade.exit_price == 99.0
    assert stop_trade.exit_reason == "stop"
    assert stop_trade.exit_price == pytest.approx(research.breakeven_price(1, 100.0))


@pytest.mark.parametrize("fee_rate", [0.0010, 0.0015])
def test_stress_and_severe_keep_the_baseline_breakeven_price(fee_rate: float) -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    bars = execution_bars(entry)
    bars.loc[0, ["high", "close"]] = [101.5, 101.0]
    bars.loc[1, ["open", "high", "low", "close"]] = [100.5, 101.0, 100.0, 100.5]
    funding = funding_frame((entry - pd.Timedelta(hours=1), 0.0))

    trade = research.simulate_trade(
        event_at(entry), bars, funding, wallet=1000.0, fee_rate=fee_rate
    )

    assert trade.exit_price == pytest.approx(100.0 * 1.0006 / 0.9994)


def test_same_exit_timestamp_can_reenter_after_long_tie_priority() -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    bars = execution_bars(entry)
    bars.loc[0, ["high", "low", "close"]] = [104.0, 99.0, 103.0]
    funding = funding_schedule(entry)

    portfolio = research.simulate_portfolio(
        [event_at(entry, -1), event_at(entry, 1)],
        bars,
        funding,
        fee_rate=0.0,
        selector=lambda _event: True,
        stage_end=entry + pd.Timedelta(days=3),
    )

    assert [trade.direction for trade in portfolio.trades] == [1, -1]
    assert [trade.exit_time for trade in portfolio.trades] == [entry, entry]
    assert portfolio.ignored_while_open == 0


def test_baseline_breakeven_covers_fees_but_funding_still_changes_net() -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    exit_time = entry + pd.Timedelta(minutes=5)
    bars = execution_bars(entry)
    bars.loc[0, ["high", "close"]] = [101.5, 101.0]
    bars.loc[1, ["open", "high", "low", "close"]] = [100.5, 101.0, 100.0, 100.5]
    funding = funding_frame(
        (entry - pd.Timedelta(hours=1), 0.0),
        (exit_time, 0.001),
    )

    trade = research.simulate_trade(
        event_at(entry), bars, funding, wallet=1000.0, fee_rate=0.0006
    )

    assert trade.entry_fee == pytest.approx(0.6)
    assert trade.exit_fee == pytest.approx(trade.quantity * trade.exit_price * 0.0006)
    assert trade.funding_cash == pytest.approx(-1.0)
    assert trade.profit_abs == pytest.approx(-1.0)


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


def test_development_gate_is_the_f3_gate_and_severe_is_report_only() -> None:
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


def test_run_uses_f5_three_fees_and_accept_all_with_the_same_executor(monkeypatch) -> None:
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
        research,
        "development_gate",
        lambda *_args: {"status": "SYNTHETIC_GATE"},
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


def write_synthetic_freeze(repo_root: Path) -> Path:
    for relative in research.EXPECTED_BINDINGS.values():
        if relative == research.f3.MANIFEST_RELATIVE:
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
    manifest = repo_root / research.f3.MANIFEST_RELATIVE
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
        name: {"path": relative.as_posix(), "sha256": research.sha256(repo_root / relative)}
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


def test_freeze_binds_base_and_new_artifacts_and_fails_on_tamper(tmp_path) -> None:
    freeze_path = write_synthetic_freeze(tmp_path)
    freeze_sha256 = research.sha256(freeze_path)
    frozen = research.verify_runtime_freeze(
        freeze_sha256, freeze_path=freeze_path, repo_root=tmp_path
    )
    assert set(frozen["bindings"]) == set(research.EXPECTED_BINDINGS)

    base_runner = tmp_path / research.F3_RUNNER_RELATIVE
    base_runner.write_bytes(base_runner.read_bytes() + b"tampered")
    with pytest.raises(research.InvalidStage, match="f3_base_runner"):
        research.verify_runtime_freeze(
            freeze_sha256, freeze_path=freeze_path, repo_root=tmp_path
        )


def test_repository_freeze_binds_current_files() -> None:
    frozen = research.verify_runtime_freeze(research.sha256(research.FREEZE))

    assert frozen["status"] == "FROZEN"


def test_default_command_only_prints_plan(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        research,
        "run_development",
        lambda _sha: (_ for _ in ()).throw(AssertionError("performance must not run")),
    )

    assert research.main([]) == 0
    output = capsys.readouterr().out
    assert '"default_executes_performance": false' in output
    assert '"accept_all_uses_same_breakeven_execution": true' in output


@pytest.mark.parametrize("stage", ["validation", "pseudo-oos"])
def test_subsequent_stages_fail_before_any_input_read(monkeypatch, stage: str) -> None:
    monkeypatch.setattr(
        research,
        "_read_development_inputs",
        lambda: (_ for _ in ()).throw(AssertionError("later stage read inputs")),
    )

    with pytest.raises(research.InvalidStage, match="not authorized"):
        research.main(["--stage", stage])
