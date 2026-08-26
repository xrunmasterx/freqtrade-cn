from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd
import pytest

from tools import prepare_donchian_funding_rv_development_data as preparer
from tools import run_donchian_funding_rv_research as research


def candles_15m(rows: int = 120, breakout_index: int = 100) -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", periods=rows, freq="15min", tz="UTC")
    close = [100.0] * rows
    close[breakout_index] = 102.0
    return pd.DataFrame(
        {
            "date": dates,
            "open": [100.0] * rows,
            "high": [101.0] * rows,
            "low": [99.0] * rows,
            "close": close,
        }
    )


def funding_frame(*rows: tuple[pd.Timestamp, float]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["date", "funding_rate"])


def funding_schedule(
    entry: pd.Timestamp, *, hours: int = 48, first_rate: float = 0.0
) -> pd.DataFrame:
    dates = pd.date_range(entry, entry + pd.Timedelta(hours=hours), freq="8h", tz="UTC")
    rates = [0.0] * len(dates)
    if len(rates) > 1:
        rates[1] = first_rate
    return funding_frame(*zip(dates, rates, strict=True))


def development_funding_schedule() -> pd.DataFrame:
    dates = list(
        pd.date_range(
            research.DEVELOPMENT_START,
            research.DEVELOPMENT_END - pd.Timedelta(hours=8),
            freq="8h",
            tz="UTC",
        )
    )
    dates.remove(pd.Timestamp("2022-12-18T16:00:00Z"))
    dates.append(pd.Timestamp("2022-12-18T18:00:00Z"))
    dates.sort()
    return funding_frame(*((date, 0.0) for date in dates))


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


def event_at(entry: pd.Timestamp, direction: int = 1, passes_f3: bool = True) -> research.Event:
    return research.Event(
        signal_time=entry - pd.Timedelta(minutes=15),
        decision_time=entry,
        direction=direction,
        rv24=0.01,
        funding_rate=-0.001 * direction,
        passes_f3=passes_f3,
    )


def test_prior_channel_uses_no_current_or_future_high() -> None:
    candles = candles_15m()
    candles.loc[100, "high"] = 500.0
    funding = funding_frame((pd.Timestamp("2022-12-31", tz="UTC"), -0.001))

    events = research.build_events(candles, funding)

    assert [event.signal_time for event in events] == [candles.loc[100, "date"]]


def test_prefix_events_are_invariant_to_future_mutation() -> None:
    original = candles_15m()
    mutated = original.copy()
    mutated.loc[105:, ["open", "high", "low", "close"]] = [50.0, 500.0, 1.0, 2.0]
    funding = funding_frame((pd.Timestamp("2022-12-31", tz="UTC"), -0.001))
    cutoff = original.loc[101, "date"]

    original_prefix = [
        event for event in research.build_events(original, funding) if event.signal_time <= cutoff
    ]
    mutated_prefix = [
        event for event in research.build_events(mutated, funding) if event.signal_time <= cutoff
    ]

    assert original_prefix == mutated_prefix


def test_rv24_is_current_plus_prior_95_log_returns() -> None:
    returns = [0.01] * 96
    closes = pd.Series([100.0] + [100.0 * math.exp(sum(returns[:index])) for index in range(1, 97)])

    rv = research.compute_rv24(closes)

    assert rv.iloc[95] != rv.iloc[95]
    assert rv.iloc[96] == pytest.approx(math.sqrt(96 * 0.01**2))


def test_funding_asof_includes_boundary_and_missing_fails_f3_closed() -> None:
    decision = pd.Timestamp("2023-01-02T01:15:00Z")
    funding = funding_frame(
        (decision - pd.Timedelta(hours=8), 0.001),
        (decision, -0.002),
        (decision + pd.Timedelta(hours=8), 0.003),
    )
    assert research.funding_asof(funding, decision) == -0.002

    candles = candles_15m()
    breakout_decision = candles.loc[100, "date"] + pd.Timedelta(minutes=15)
    future_only = funding_frame((breakout_decision + pd.Timedelta(hours=1), -0.002))

    events = research.build_events(candles, future_only)

    assert len(events) == 1
    assert events[0].funding_rate is None
    assert not events[0].passes_f3


def test_same_bar_double_touch_is_stop_first() -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    bars = execution_bars(entry)
    bars.loc[0, ["high", "low", "close"]] = [105.0, 98.0, 100.0]
    funding = funding_frame((entry - pd.Timedelta(hours=1), 0.0))

    trade = research.simulate_trade(
        event_at(entry), bars, funding, wallet=1000.0, fee_rate=0.0
    )

    assert trade.exit_reason == "stop"
    assert trade.exit_price == pytest.approx(98.5)


def test_long_pays_and_short_receives_positive_funding() -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    bars = execution_bars(entry)
    funding = funding_schedule(entry, first_rate=0.001)

    long_trade = research.simulate_trade(
        event_at(entry, 1), bars, funding, wallet=1000.0, fee_rate=0.0
    )
    short_trade = research.simulate_trade(
        event_at(entry, -1), bars, funding, wallet=1000.0, fee_rate=0.0
    )

    assert long_trade.funding_cash == pytest.approx(-1.0)
    assert short_trade.funding_cash == pytest.approx(1.0)


def test_stop_gap_uses_worse_open_and_max_hold_uses_48h_open() -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    funding = funding_schedule(entry)
    gap_bars = execution_bars(entry)
    gap_bars.loc[1, ["open", "high", "low", "close"]] = [97.0, 98.0, 96.0, 97.0]

    gap_trade = research.simulate_trade(
        event_at(entry), gap_bars, funding, wallet=1000.0, fee_rate=0.0
    )
    hold_bars = execution_bars(entry)
    hold_bars.loc[576, "open"] = 100.5
    hold_trade = research.simulate_trade(
        event_at(entry), hold_bars, funding, wallet=1000.0, fee_rate=0.0
    )

    assert gap_trade.exit_reason == "stop_gap"
    assert gap_trade.exit_price == 97.0
    assert hold_trade.exit_reason == "max_hold_48h"
    assert hold_trade.exit_time == entry + pd.Timedelta(hours=48)
    assert hold_trade.exit_price == 100.5


def test_max_one_suppresses_events_and_sorts_long_before_short() -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    bars = execution_bars(entry, periods=1153)
    funding = funding_schedule(entry, hours=96)
    events = [event_at(entry, -1), event_at(entry, 1)]

    portfolio = research.simulate_portfolio(
        events,
        bars,
        funding,
        fee_rate=0.0,
        selector=lambda _event: True,
        stage_end=entry + pd.Timedelta(days=7),
    )

    assert len(portfolio.trades) == 1
    assert portfolio.trades[0].direction == 1
    assert portfolio.ignored_while_open == 1


def test_fee_accounting_has_separate_entry_and_exit_fees() -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    bars = execution_bars(entry)
    bars.loc[0, ["high", "close"]] = [104.0, 104.0]
    funding = funding_frame((entry - pd.Timedelta(hours=1), 0.0))

    trade = research.simulate_trade(
        event_at(entry), bars, funding, wallet=1000.0, fee_rate=0.0006
    )

    assert trade.quantity == 10.0
    assert trade.entry_fee == pytest.approx(0.6)
    assert trade.exit_fee == pytest.approx(0.624)
    assert trade.profit_abs == pytest.approx(38.776)
    assert trade.wallet_after == pytest.approx(1038.776)


def make_trade(profit_abs: float, profit_ratio: float, wallet_after: float) -> research.Trade:
    return research.Trade(
        entry_time=pd.Timestamp("2023-01-01", tz="UTC"),
        exit_time=pd.Timestamp("2023-01-02", tz="UTC"),
        direction=1,
        quantity=1.0,
        entry_price=100.0,
        exit_price=100.0,
        entry_fee=0.0,
        exit_fee=0.0,
        funding_cash=0.0,
        profit_abs=profit_abs,
        profit_ratio=profit_ratio,
        wallet_before=1000.0,
        wallet_after=wallet_after,
        exit_reason="test",
    )


def test_strict_metrics_use_abs_for_pf_ratio_for_payoff_and_na_fails_gate() -> None:
    portfolio = research.Portfolio(
        (
            make_trade(20.0, 0.02, 1020.0),
            make_trade(10.0, 0.01, 1030.0),
            make_trade(-10.0, -0.005, 1020.0),
        ),
        ignored_while_open=0,
        left_open=0,
    )

    metrics = research.calculate_metrics(portfolio)
    no_loser = research.calculate_metrics(
        research.Portfolio((make_trade(1.0, 0.001, 1001.0),), 0, 0)
    )
    gate = research.development_gate(no_loser, no_loser, metrics)

    assert metrics.profit_factor == 3.0
    assert metrics.strict_payoff == 3.0
    assert no_loser.profit_factor is None
    assert no_loser.strict_payoff is None
    assert gate["status"] == "DEVELOPMENT_REJECTED"

    no_winner = research.calculate_metrics(
        research.Portfolio((make_trade(-1.0, -0.001, 999.0),), 0, 0)
    )
    assert no_winner.profit_factor == 0.0


def test_pre_2024_boundary_and_non_whitelisted_path_are_denied(tmp_path) -> None:
    frame = execution_bars(pd.Timestamp("2024-01-01T00:00:00Z"), periods=1)
    with pytest.raises(research.InvalidStage, match="2024-01-01"):
        research.validate_candles(frame, "5m", "5min")
    with pytest.raises(research.InvalidStage, match="whitelist"):
        research.validate_input_path("5m", tmp_path / "BTC-5m.feather")


def test_development_loader_reads_only_physical_pre_2024_inputs(
    monkeypatch, tmp_path
) -> None:
    paths = {
        role: tmp_path / "development-data" / f"{role}.feather"
        for role in research.ALLOWED_INPUTS
    }
    source_with_2024 = tmp_path / "source-with-2024.feather"
    five = execution_bars(pd.Timestamp("2023-01-01T00:00:00Z"), periods=4)
    fifteen = candles_15m(rows=4, breakout_index=3)
    funding = development_funding_schedule().rename(columns={"funding_rate": "open"})
    frames = {paths["5m"]: five, paths["15m"]: fifteen, paths["funding"]: funding}
    reads: list[Path] = []

    def fake_read(path: Path, columns=None):
        resolved = Path(path)
        reads.append(resolved)
        if resolved == source_with_2024:
            raise AssertionError("development loader accessed a source containing 2024")
        frame = frames[resolved]
        return frame if columns is None else frame.loc[:, columns]

    monkeypatch.setattr(research, "ALLOWED_INPUTS", paths)
    monkeypatch.setattr(research.pd, "read_feather", fake_read)

    loaded = research._read_development_inputs()

    assert [len(frame) for frame in loaded] == [4, 4, len(funding)]
    assert reads == [paths["5m"], paths["15m"], paths["funding"]]
    assert source_with_2024 not in reads


def test_funding_official_10h_6h_schedule_is_valid_but_internal_missing_event_is_not() -> None:
    complete = development_funding_schedule()

    validated = research.validate_development_funding(complete)

    assert pd.Timestamp("2022-12-18T16:00:00Z") not in set(validated["date"])
    assert pd.Timestamp("2022-12-18T18:00:00Z") in set(validated["date"])
    missing = complete.loc[
        complete["date"] != pd.Timestamp("2023-07-01T08:00:00Z")
    ].reset_index(drop=True)
    with pytest.raises(research.InvalidStage, match="greater than 10 hours"):
        research.validate_development_funding(missing)


def test_each_trade_funding_path_rejects_a_gap_over_10h() -> None:
    entry = pd.Timestamp("2023-03-01T00:00:00Z")
    bars = execution_bars(entry)
    funding = funding_schedule(entry)
    funding = funding.loc[
        funding["date"] != entry + pd.Timedelta(hours=16)
    ].reset_index(drop=True)

    with pytest.raises(research.InvalidStage, match="funding path has a settlement gap"):
        research.simulate_trade(
            event_at(entry), bars, funding, wallet=1000.0, fee_rate=0.0
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


def test_run_development_uses_f3_accept_all_three_fees_and_severe_is_report_only(
    monkeypatch,
) -> None:
    events = [
        event_at(pd.Timestamp("2023-03-01T00:00:00Z"), passes_f3=True),
        event_at(pd.Timestamp("2023-03-04T00:00:00Z"), passes_f3=False),
    ]
    calls: list[tuple[float, tuple[bool, ...]]] = []
    gate_args: list[tuple[research.Metrics, research.Metrics, research.Metrics]] = []
    frames = (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    monkeypatch.setattr(research, "verify_runtime_freeze", lambda value: {"sha": value})
    monkeypatch.setattr(research, "_read_development_inputs", lambda: frames)
    monkeypatch.setattr(research, "cross_timeframe_audit", lambda *_args: {"checked": 1})
    monkeypatch.setattr(research, "build_events", lambda *_args: events)

    def fake_simulate(_events, _five, _funding, *, fee_rate, selector, **_kwargs):
        selected = tuple(selector(event) for event in events)
        calls.append((fee_rate, selected))
        return len(calls)

    metrics = {1: metric(11), 2: metric(12), 3: metric(13), 4: metric(14)}
    monkeypatch.setattr(research, "simulate_portfolio", fake_simulate)
    monkeypatch.setattr(research, "calculate_metrics", lambda token: metrics[token])

    def fake_gate(baseline, stress, accept_all):
        gate_args.append((baseline, stress, accept_all))
        return {"status": "SYNTHETIC_GATE"}

    monkeypatch.setattr(research, "development_gate", fake_gate)

    result = research.run_development("a" * 64)

    assert calls == [
        (0.0006, (True, False)),
        (0.0010, (True, False)),
        (0.0015, (True, False)),
        (0.0006, (True, True)),
    ]
    assert gate_args == [(metrics[1], metrics[2], metrics[4])]
    assert result["candidate"]["severe"] == asdict(metrics[3])
    assert result["gate"] == {"status": "SYNTHETIC_GATE"}


def test_development_gate_uses_all_frozen_and_relative_conditions() -> None:
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
    insufficient_relative = research.development_gate(
        replace(baseline, profit_factor=1.98), stress, accept_all
    )

    assert passed["status"] == "DEVELOPMENT_PASSED"
    assert all(passed["checks"].values())
    assert insufficient_relative["status"] == "DEVELOPMENT_REJECTED"
    assert not insufficient_relative["checks"]["relative_profit_factor_plus_0_15"]


def write_synthetic_freeze(repo_root: Path) -> Path:
    for relative in research.EXPECTED_BINDINGS.values():
        if relative == research.MANIFEST_RELATIVE:
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
    manifest_path = repo_root / research.MANIFEST_RELATIVE
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
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
    bindings = {}
    for name, relative in research.EXPECTED_BINDINGS.items():
        path = repo_root / relative
        bindings[name] = {"path": relative.as_posix(), "sha256": research.sha256(path)}
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


def test_freeze_manifest_tamper_fails_closed(tmp_path) -> None:
    freeze_path = write_synthetic_freeze(tmp_path)
    freeze_sha256 = research.sha256(freeze_path)
    research.verify_runtime_freeze(
        freeze_sha256, freeze_path=freeze_path, repo_root=tmp_path
    )
    manifest = tmp_path / research.MANIFEST_RELATIVE
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(research.InvalidStage, match="development_manifest"):
        research.verify_runtime_freeze(
            freeze_sha256, freeze_path=freeze_path, repo_root=tmp_path
        )


def test_preparer_refuses_to_overwrite_an_existing_output(tmp_path) -> None:
    output = tmp_path / "development-data"
    output.mkdir()

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        preparer.prepare(output)


def test_repository_freeze_binds_current_files() -> None:
    frozen = research.verify_runtime_freeze(research.sha256(research.FREEZE))

    assert frozen["status"] == "FROZEN"


def test_default_command_does_not_execute_development(monkeypatch, capsys) -> None:
    def forbidden(_sha: str):
        raise AssertionError("development must not run by default")

    monkeypatch.setattr(research, "run_development", forbidden)

    assert research.main([]) == 0
    assert '"default_executes_performance": false' in capsys.readouterr().out


def test_validation_is_fail_closed_before_input_read(monkeypatch) -> None:
    def forbidden():
        raise AssertionError("validation must not read inputs")

    monkeypatch.setattr(research, "_read_development_inputs", forbidden)

    with pytest.raises(research.InvalidStage, match="not authorized"):
        research.main(["--stage", "validation"])
