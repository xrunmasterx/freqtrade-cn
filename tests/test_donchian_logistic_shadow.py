from __future__ import annotations

import copy
import hashlib
import inspect
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tools import run_donchian_logistic_shadow as shadow


def _rewrite_model(path: Path, artifact: dict[str, object]) -> str:
    artifact = copy.deepcopy(artifact)
    artifact.pop("semantic_sha256", None)
    artifact["semantic_sha256"] = shadow.semantic_sha256(artifact)
    raw = shadow.canonical_json_bytes(artifact) + b"\n"
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _candles(
    start: str, periods: int, timeframe: str, price: float = 100.0
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range(start, periods=periods, freq=timeframe, tz="UTC"),
            "open": np.full(periods, price),
            "high": np.full(periods, price + 1.0),
            "low": np.full(periods, price - 1.0),
            "close": np.full(periods, price),
            "volume": np.full(periods, 1000.0),
        }
    )


def _label_bars(execution_ms: int) -> pd.DataFrame:
    return _candles(shadow._iso(execution_ms), shadow.LABEL_ROWS, "5min")


def _replay_seed_frames(decision_ms: int) -> dict[str, pd.DataFrame]:
    execution_ms = decision_ms + shadow.INTERVAL_MS["5m"]
    return {
        "15m": _candles(
            shadow._iso(decision_ms - 2 * shadow.INTERVAL_MS["15m"]),
            1,
            "15min",
        ),
        "5m": _label_bars(execution_ms),
    }


def _prediction_record(
    decision_ms: int, *, computed_at_ms: int | None = None
) -> dict[str, object]:
    computed = decision_ms if computed_at_ms is None else computed_at_ms
    execution = shadow._execution_time_ms(computed)
    return {
        "computed_at": shadow._iso(computed),
        "computed_at_ms": computed,
        "decision_time": shadow._iso(decision_ms),
        "decision_time_ms": decision_ms,
        "direction": "long",
        "execution_time": shadow._iso(execution),
        "execution_time_ms": execution,
        "features": [0.0] * len(shadow.FEATURE_ORDER),
        "kind": "event_prediction",
        "predicted_positive": True,
        "probability": 0.5,
        "signal_time": shadow._iso(decision_ms - shadow.INTERVAL_MS["15m"]),
        "threshold": 0.5,
    }


def _excluded_record(decision_ms: int) -> dict[str, object]:
    return {
        "computed_at": shadow._iso(decision_ms),
        "computed_at_ms": decision_ms,
        "decision_time": shadow._iso(decision_ms),
        "decision_time_ms": decision_ms,
        "direction": "long",
        "kind": "event_excluded",
        "reason": "missing_lookback",
        "signal_time": shadow._iso(decision_ms - shadow.INTERVAL_MS["15m"]),
    }


def _label_record(
    decision_ms: int,
    *,
    entry: float = 100.0,
    exit_reason: str = "deadline_open",
    label: int = 0,
) -> dict[str, object]:
    execution_ms = decision_ms + shadow.INTERVAL_MS["5m"]
    exit_ms = execution_ms + shadow.HOLD_MS
    return {
        "decision_time": shadow._iso(decision_ms),
        "decision_time_ms": decision_ms,
        "direction": "long",
        "entry": entry,
        "execution_time": shadow._iso(execution_ms),
        "execution_time_ms": execution_ms,
        "exit_reason": exit_reason,
        "exit_time": shadow._iso(exit_ms),
        "exit_time_ms": exit_ms,
        "kind": "label_matured",
        "label": label,
        "matured_at": shadow._iso(
            execution_ms + shadow.HOLD_MS + shadow.INTERVAL_MS["5m"]
        ),
    }


def _candle_record(
    timestamp_ms: int,
    timeframe: str = "15m",
    *,
    close: float = 100.0,
    observed_at_ms: int | None = None,
) -> dict[str, object]:
    observed = observed_at_ms if observed_at_ms is not None else timestamp_ms + shadow.INTERVAL_MS[timeframe]
    return {
        "close": close,
        "high": max(101.0, close),
        "kind": "candle",
        "low": min(99.0, close),
        "observed_at": shadow._iso(observed),
        "open": 100.0,
        "timeframe": timeframe,
        "timestamp": shadow._iso(timestamp_ms),
        "timestamp_ms": timestamp_ms,
        "volume": 1.0,
    }


def _event_source(decision_ms: int, *, observed_at_ms: int | None = None) -> dict[str, object]:
    return _candle_record(
        decision_ms - shadow.INTERVAL_MS["15m"],
        observed_at_ms=decision_ms if observed_at_ms is None else observed_at_ms,
    )


def _write_journal(path: Path, records: list[dict[str, object]]) -> None:
    with shadow.locked_journal(path), shadow._create_journal(path) as handle:
        shadow._append_records(
            handle,
            path,
            records,
            sync_parent_entry=True,
        )


def _event_replay_fixture(
    decision_ms: int,
) -> tuple[dict[str, pd.DataFrame], list[dict[str, object]], dict[str, object]]:
    signal_ms = decision_ms - shadow.INTERVAL_MS["15m"]
    seed_15m = _candles(
        shadow._iso(signal_ms - 110 * shadow.INTERVAL_MS["15m"]),
        110,
        "15min",
    )
    signal = _event_source(decision_ms)
    signal.update({"close": 107.0, "high": 108.0, "low": 99.0, "volume": 1000.0})
    observed_ms = decision_ms - shadow.INTERVAL_MS["15m"]
    funding = {
        "available_at": shadow._iso(decision_ms),
        "available_at_ms": decision_ms,
        "kind": "funding_observation",
        "observed_at": shadow._iso(observed_ms),
        "rate": 0.0001,
        "timestamp": shadow._iso(observed_ms),
        "timestamp_ms": observed_ms,
    }
    source_records = [funding, signal]
    frame = shadow._candle_frame(seed_15m, source_records, "15m")
    computed_ms = decision_ms + 60_000
    events = shadow.generate_events(
        frame,
        source_records,
        shadow.load_model(),
        lambda: datetime.fromtimestamp(computed_ms / 1000, tz=UTC),
    )
    event = next(
        record
        for record in events
        if record["decision_time_ms"] == decision_ms
    )
    seeds = {
        "15m": seed_15m,
        "5m": _label_bars(decision_ms + shadow.INTERVAL_MS["5m"]),
    }
    return seeds, source_records, event


class FakeExchange:
    def __init__(
        self,
        *,
        ohlcv: dict[str, list[list[float | int]]] | None = None,
        funding: list[dict[str, float | int]] | None = None,
    ) -> None:
        self.ohlcv = ohlcv or {}
        self.funding = funding or []
        self.calls: list[tuple[object, ...]] = []
        self.order_calls = 0

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: int, limit: int
    ) -> list[list[float | int]]:
        self.calls.append(("fetch_ohlcv", symbol, timeframe, since, limit))
        return [row for row in self.ohlcv.get(timeframe, []) if int(row[0]) >= since][:limit]

    def fetch_funding_rate_history(
        self, symbol: str, since: int, limit: int
    ) -> list[dict[str, float | int]]:
        self.calls.append(("fetch_funding_rate_history", symbol, since, limit))
        return [row for row in self.funding if int(row["timestamp"]) >= since][:limit]

    def create_order(self, *_args: object, **_kwargs: object) -> None:
        self.order_calls += 1
        raise AssertionError("orders are forbidden")


def test_model_validation_rejects_coherent_self_hashed_nested_malformed_artifacts(
    tmp_path: Path,
) -> None:
    valid = shadow.load_model()
    malformed_values: list[dict[str, object]] = []

    extra_key = copy.deepcopy(valid)
    extra_key["model"]["preprocessing"]["future_option"] = 1  # type: ignore[index]
    malformed_values.append(extra_key)

    boolean_number = copy.deepcopy(valid)
    boolean_number["model"]["settings"]["C"] = True  # type: ignore[index]
    malformed_values.append(boolean_number)

    zero_scale = copy.deepcopy(valid)
    zero_scale["model"]["preprocessing"]["scaler_scale"][0] = 0.0  # type: ignore[index]
    malformed_values.append(zero_scale)

    wrong_constant = copy.deepcopy(valid)
    wrong_constant["label"]["ordering"] = [  # type: ignore[index]
        "gap_target",
        "gap_stop",
        "intrabar_stop",
        "intrabar_target",
    ]
    malformed_values.append(wrong_constant)

    float_classes = copy.deepcopy(valid)
    float_classes["model"]["classes"] = [0.0, 1.0]  # type: ignore[index]
    malformed_values.append(float_classes)

    numeric_frozen_boolean = copy.deepcopy(valid)
    numeric_frozen_boolean["preregistration_scope"][  # type: ignore[index]
        "cannot_prove_current_profitability"
    ] = 1
    malformed_values.append(numeric_frozen_boolean)

    changed_source_hash = copy.deepcopy(valid)
    changed_source_hash["source_hashes"]["freezer"] = "0" * 64  # type: ignore[index]
    malformed_values.append(changed_source_hash)

    changed_training_hash = copy.deepcopy(valid)
    changed_training_hash["training_data_sha256"] = "0" * 64
    malformed_values.append(changed_training_hash)

    for index, artifact in enumerate(malformed_values):
        path = tmp_path / f"MODEL-{index}.json"
        byte_hash = _rewrite_model(path, artifact)
        with pytest.raises(shadow.ShadowError):
            shadow.load_model(path, byte_hash)


def test_model_byte_hash_is_checked_before_schema(tmp_path: Path) -> None:
    path = tmp_path / "MODEL.json"
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(shadow.ShadowError, match="byte SHA-256 mismatch"):
        shadow.load_model(path)


def test_boundary_is_exclusive_and_seed_origin_is_fixed() -> None:
    start_ms = shadow.BOUNDARY_MS - 101 * shadow.INTERVAL_MS["15m"]
    candles = _candles(shadow._iso(start_ms), 104, "15min")
    candles.loc[100, ["open", "high", "low", "close"]] = [100.0, 106.0, 99.0, 105.0]
    candles.loc[101, ["open", "high", "low", "close"]] = [100.0, 101.0, 99.0, 100.0]
    candles.loc[102, ["open", "high", "low", "close"]] = [100.0, 108.0, 99.0, 107.0]

    computed_at = shadow.BOUNDARY_MS + 2 * shadow.INTERVAL_MS["15m"] + 60_000
    events = shadow.generate_events(
        candles,
        [],
        shadow.load_model(),
        lambda: datetime.fromtimestamp(computed_at / 1000, tz=UTC),
    )

    assert shadow._iso(shadow.SEED_ORIGIN_MS) == shadow.SEED_ORIGIN
    assert all(int(event["decision_time_ms"]) > shadow.BOUNDARY_MS for event in events)
    assert [event["decision_time_ms"] for event in events] == [
        shadow.BOUNDARY_MS + 2 * shadow.INTERVAL_MS["15m"]
    ]


def test_full_operational_seeds_are_bound_and_match_the_f3_overlap() -> None:
    frames = shadow.load_seed_frames()
    assert {
        timeframe: int(frame.iloc[0]["date"].timestamp() * 1000)
        for timeframe, frame in frames.items()
    } == {"15m": shadow.SEED_ORIGIN_MS, "5m": shadow.SEED_ORIGIN_MS}
    assert all(
        int(frame.iloc[-1]["date"].timestamp() * 1000)
        + shadow.INTERVAL_MS[timeframe]
        <= shadow.SNAPSHOT_CUTOFF_MS
        for timeframe, frame in frames.items()
    )


def test_seed_api_and_journal_ohlcv_require_open_and_close_inside_range() -> None:
    seed = _candles(shadow.SEED_ORIGIN, 1, "5min")
    seed.loc[0, "open"] = 102.0
    with pytest.raises(shadow.ShadowError, match="seed OHLCV is invalid"):
        shadow._validate_frame(seed, "5m")

    with pytest.raises(shadow.ShadowError, match="invalid 5m OHLCV response"):
        shadow._parse_ohlcv_row(
            [shadow.BOUNDARY_MS, 100.0, 101.0, 99.0, 102.0, 1.0],
            "5m",
            shadow.BOUNDARY_MS + shadow.INTERVAL_MS["5m"],
        )

    candle = _candle_record(shadow.BOUNDARY_MS, timeframe="5m")
    candle["open"] = 102.0
    with pytest.raises(shadow.ShadowError, match="journal candle OHLCV is invalid"):
        shadow._validate_record(candle)


def test_late_computation_excludes_without_calculating_a_prediction() -> None:
    start_ms = shadow.BOUNDARY_MS - 101 * shadow.INTERVAL_MS["15m"]
    candles = _candles(shadow._iso(start_ms), 103, "15min")
    candles.loc[102, ["open", "high", "low", "close"]] = [100.0, 108.0, 99.0, 107.0]
    decision = start_ms + 103 * shadow.INTERVAL_MS["15m"]

    events = shadow.generate_events(
        candles,
        [],
        shadow.load_model(),
        lambda: datetime.fromtimestamp(
            (decision + shadow.INTERVAL_MS["5m"]) / 1000,
            tz=UTC,
        ),
    )

    assert len(events) == 1
    assert events[0]["kind"] == "event_excluded"
    assert events[0]["reason"] == "late_computation"


def test_probability_crossing_deadline_emits_only_late_exclusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    seeds, sources, _event = _event_replay_fixture(decision)
    candles = shadow._candle_frame(seeds["15m"], sources, "15m")
    now_ms = decision + shadow.INTERVAL_MS["5m"] - 1
    prediction_calls = 0
    original_predict = shadow.predict_probability

    def cross_deadline(
        model_artifact: dict[str, object], features: list[float]
    ) -> float:
        nonlocal now_ms, prediction_calls
        prediction_calls += 1
        probability = original_predict(model_artifact, features)
        now_ms = decision + shadow.INTERVAL_MS["5m"]
        return probability

    monkeypatch.setattr(shadow, "predict_probability", cross_deadline)
    events = shadow.generate_events(
        candles,
        sources,
        shadow.load_model(),
        lambda: datetime.fromtimestamp(now_ms / 1000, tz=UTC),
    )
    event = next(
        value for value in events if value["decision_time_ms"] == decision
    )

    assert prediction_calls == 1
    assert event["kind"] == "event_excluded"
    assert event["reason"] == "late_computation"
    assert event["computed_at_ms"] == decision + shadow.INTERVAL_MS["5m"]
    assert not {
        "execution_time",
        "execution_time_ms",
        "features",
        "predicted_positive",
        "probability",
        "threshold",
    } & set(event)


def test_event_generation_rejects_computation_before_decision() -> None:
    start_ms = shadow.BOUNDARY_MS - 101 * shadow.INTERVAL_MS["15m"]
    candles = _candles(shadow._iso(start_ms), 103, "15min")
    candles.loc[102, ["open", "high", "low", "close"]] = [100.0, 108.0, 99.0, 107.0]
    decision = start_ms + 103 * shadow.INTERVAL_MS["15m"]

    with pytest.raises(shadow.ShadowError, match="precedes its decision"):
        shadow.generate_events(
            candles,
            [],
            shadow.load_model(),
            lambda: datetime.fromtimestamp((decision - 1) / 1000, tz=UTC),
        )


def test_timely_prediction_executes_at_first_strict_5m_boundary() -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    _seeds, _sources, event = _event_replay_fixture(decision)

    assert event["computed_at_ms"] == decision + 60_000
    assert event["execution_time_ms"] == decision + shadow.INTERVAL_MS["5m"]
    assert event["execution_time"] == shadow._iso(
        decision + shadow.INTERVAL_MS["5m"]
    )


def test_replay_rejects_signal_observed_after_computation() -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    seeds, sources, event = _event_replay_fixture(decision)
    changed_sources = copy.deepcopy(sources)
    changed_sources[-1]["observed_at"] = shadow._iso(
        int(event["computed_at_ms"]) + 1
    )
    records = [shadow.build_header(), *changed_sources, event]

    with pytest.raises(shadow.ShadowError, match="predates used 15m source"):
        shadow._validate_existing_events(records, seeds, shadow.load_model())


def test_event_validation_computes_indicators_once_for_multiple_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    seeds, sources, first_event = _event_replay_fixture(first_decision)
    reset = _candle_record(first_decision, close=100.0)
    second_signal = _candle_record(
        first_decision + shadow.INTERVAL_MS["15m"],
        close=110.0,
    )
    prefix = [*sources, first_event, reset, second_signal]
    candles = shadow._candle_frame(seeds["15m"], prefix, "15m")
    second_decision = first_decision + 2 * shadow.INTERVAL_MS["15m"]
    second_event = next(
        record
        for record in shadow.generate_events(
            candles,
            prefix,
            shadow.load_model(),
            lambda: datetime.fromtimestamp(
                (second_decision + 60_000) / 1000,
                tz=UTC,
            ),
        )
        if record["decision_time_ms"] == second_decision
    )
    records = [shadow.build_header(), *prefix, second_event]
    calls = 0
    original_compute = shadow.compute_indicators

    def count_compute(frame: pd.DataFrame) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        return original_compute(frame)

    monkeypatch.setattr(shadow, "compute_indicators", count_compute)
    shadow._validate_existing_events(records, seeds, shadow.load_model())

    assert calls == 1


def test_new_events_build_one_funding_index_for_bounded_lookups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    seeds, sources, _event = _event_replay_fixture(decision)
    candles = shadow._candle_frame(seeds["15m"], sources, "15m")
    indicators = shadow.compute_indicators(candles)
    indicators.loc[indicators.index[-1], ["first_long", "first_short"]] = True
    funding_records = [
        {
            **sources[0],
            "timestamp": shadow._iso(int(sources[0]["timestamp_ms"]) - offset),
            "timestamp_ms": int(sources[0]["timestamp_ms"]) - offset,
        }
        for offset in range(1024)
    ]
    iterations = 0
    lookup_calls = 0
    original_latest = shadow._FundingPrefixIndex.latest

    class CountingSequence:
        def __iter__(self) -> Iterator[dict[str, object]]:
            nonlocal iterations
            iterations += 1
            return iter(funding_records)

    def count_latest(
        index: shadow._FundingPrefixIndex, decision_ms: int
    ) -> dict[str, object] | None:
        nonlocal lookup_calls
        lookup_calls += 1
        return original_latest(index, decision_ms)  # type: ignore[return-value]

    monkeypatch.setattr(shadow._FundingPrefixIndex, "latest", count_latest)
    events = shadow.generate_events(
        candles,
        CountingSequence(),  # type: ignore[arg-type]
        shadow.load_model(),
        lambda: datetime.fromtimestamp((decision + 60_000) / 1000, tz=UTC),
        indicators=indicators,
    )
    matching = [event for event in events if event["decision_time_ms"] == decision]

    assert iterations == 1
    assert lookup_calls == 2
    assert [event["direction"] for event in matching] == ["long", "short"]
    assert [event["features"][0] for event in matching] == [-0.0001, 0.0001]


@pytest.mark.parametrize("tamper", ["reason", "signal_time"])
def test_tampered_event_exclusion_reason_or_time_is_rejected(tamper: str) -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    seeds, sources, _event = _event_replay_fixture(decision)
    signal_only = [sources[-1]]
    frame = shadow._candle_frame(seeds["15m"], signal_only, "15m")
    excluded = next(
        record
        for record in shadow.generate_events(
            frame,
            signal_only,
            shadow.load_model(),
            lambda: datetime.fromtimestamp((decision + 60_000) / 1000, tz=UTC),
        )
        if record["decision_time_ms"] == decision
    )
    changed = copy.deepcopy(excluded)
    if tamper == "reason":
        changed["reason"] = "missing_lookback"
    else:
        changed["signal_time"] = shadow._iso(
            decision - shadow.INTERVAL_MS["15m"] + 1
        )

    with pytest.raises(shadow.ShadowError, match="exact frozen replay"):
        shadow._validate_existing_events(
            [shadow.build_header(), *signal_only, changed],
            seeds,
            shadow.load_model(),
        )


def test_event_validation_rejects_used_funding_observed_after_computation() -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    seeds, sources, event = _event_replay_fixture(decision)
    changed_sources = copy.deepcopy(sources)
    changed_sources[0]["observed_at"] = shadow._iso(int(event["computed_at_ms"]) + 1)

    with pytest.raises(shadow.ShadowError, match="predates used funding observation"):
        shadow._validate_existing_events(
            [shadow.build_header(), *changed_sources, event],
            seeds,
            shadow.load_model(),
        )


@pytest.mark.parametrize("computed_offset", [-1, shadow.INTERVAL_MS["5m"]])
def test_journal_read_rejects_predictions_outside_timely_window(
    tmp_path: Path, computed_offset: int
) -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    path = tmp_path / "shadow.jsonl"
    _write_journal(
        path,
        [
            shadow.build_header(),
            _event_source(decision),
            _prediction_record(
                decision,
                computed_at_ms=decision + computed_offset,
            ),
        ],
    )

    with pytest.raises(shadow.ShadowError, match="computed before|computed too late"):
        shadow.read_journal(path)


def test_funding_preserves_exact_timestamp_and_is_available_next_strict_boundary() -> None:
    timestamp = shadow.BOUNDARY_MS + 7 * 60 * 1000 + 13_000
    observed = shadow.BOUNDARY_MS + 14 * 60 * 1000 + 59_000
    exchange = FakeExchange(funding=[{"timestamp": timestamp, "fundingRate": 0.0001}])

    records = shadow.fetch_funding(
        exchange,
        shadow.BOUNDARY_MS,
        lambda: datetime.fromtimestamp(observed / 1000, tz=UTC),
    )

    assert records[0]["timestamp_ms"] == timestamp
    assert records[0]["timestamp"] == shadow._iso(timestamp)
    available = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    assert records[0]["available_at_ms"] == available
    assert shadow._funding_for_decision(records, available - 1)[0] is None
    assert shadow._funding_for_decision(records, available) == (0.0001, None)


def test_only_closed_candles_are_returned_and_timestamps_are_not_floored() -> None:
    start = shadow.BOUNDARY_MS
    now = start + 20 * 60 * 1000
    exchange = FakeExchange(
        ohlcv={
            "15m": [
                [start, 100.0, 101.0, 99.0, 100.0, 1.0],
                [start + 15 * 60 * 1000, 100.0, 101.0, 99.0, 100.0, 1.0],
            ]
        }
    )

    records = shadow.fetch_closed_ohlcv(
        exchange,
        "15m",
        start,
        lambda: datetime.fromtimestamp(now / 1000, tz=UTC),
    )

    assert [record["timestamp_ms"] for record in records] == [start]
    bad = FakeExchange(
        ohlcv={"15m": [[start + 1, 100.0, 101.0, 99.0, 100.0, 1.0]]}
    )
    with pytest.raises(shadow.ShadowError, match="unaligned exact"):
        shadow.fetch_closed_ohlcv(
            bad,
            "15m",
            start,
            lambda: datetime.fromtimestamp(now / 1000, tz=UTC),
        )


def test_recursive_indicators_are_prefix_invariant() -> None:
    rows = 220
    step = np.arange(rows, dtype=float)
    close = 100.0 * np.exp(0.0004 * step + 0.002 * np.sin(step / 7.0))
    frame = pd.DataFrame(
        {
            "date": pd.date_range(shadow.SEED_ORIGIN, periods=rows, freq="15min"),
            "open": close * 0.999,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": 1000.0 + step,
        }
    )
    prefix_length = 180
    prefix = shadow.compute_indicators(frame.iloc[:prefix_length].copy())
    extended = frame.copy()
    extended.loc[prefix_length:, ["open", "high", "low", "close", "volume"]] *= 50.0
    full = shadow.compute_indicators(extended).iloc[:prefix_length]
    pd.testing.assert_frame_equal(prefix, full)


def test_long_and_short_labels_use_stop_first_and_deadline_open() -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    execution = decision + shadow.INTERVAL_MS["5m"]

    long_bars = _label_bars(execution)
    long_bars.loc[1, ["high", "low"]] = [105.0, 98.0]
    assert shadow.label_event(long_bars, execution, "long")[:2] == (0, "stop")

    short_bars = _label_bars(execution)
    short_bars.loc[1, ["high", "low"]] = [102.0, 95.0]
    assert shadow.label_event(short_bars, execution, "short")[:2] == (0, "stop")

    long_target = _label_bars(execution)
    long_target.loc[1, ["high", "low"]] = [105.0, 99.0]
    assert shadow.label_event(long_target, execution, "long")[:2] == (1, "target")

    short_target = _label_bars(execution)
    short_target.loc[1, ["high", "low"]] = [101.0, 95.0]
    assert shadow.label_event(short_target, execution, "short")[:2] == (1, "target")

    deadline = _label_bars(execution)
    deadline.loc[576, ["open", "high", "low"]] = [100.0, 110.0, 90.0]
    assert shadow.label_event(deadline, execution, "long")[:2] == (0, "deadline_open")


def test_decision_bar_target_does_not_override_execution_path() -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    execution = decision + shadow.INTERVAL_MS["5m"]
    bars = _candles(shadow._iso(decision), shadow.LABEL_ROWS + 1, "5min")
    bars.loc[0, ["high", "low"]] = [105.0, 99.0]
    bars.loc[1, ["high", "low"]] = [101.0, 98.0]

    label, reason, entry, exit_ms = shadow.label_event(
        bars, execution, "long"
    )

    assert (label, reason, entry, exit_ms) == (0, "stop", 100.0, execution)


@pytest.mark.parametrize(
    ("label", "exit_reason"),
    [(0, "target"), (0, "target_gap"), (1, "stop"), (1, "stop_gap"), (1, "deadline_open")],
)
def test_journal_label_value_must_match_exit_reason(
    label: int, exit_reason: str
) -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    with pytest.raises(shadow.ShadowError, match="conflicts with its exit reason"):
        shadow._validate_record(
            _label_record(decision, label=label, exit_reason=exit_reason)
        )


@pytest.mark.parametrize("predecessor", ["missing", "excluded"])
def test_journal_label_requires_preceding_timely_prediction(
    tmp_path: Path, predecessor: str
) -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    records = [shadow.build_header()]
    if predecessor == "excluded":
        records.extend([_event_source(decision), _excluded_record(decision)])
    records.append(_label_record(decision))
    path = tmp_path / f"{predecessor}.jsonl"
    _write_journal(path, records)

    with pytest.raises(shadow.ShadowError, match="preceding timely prediction"):
        shadow.read_journal(path)


def test_label_matures_only_after_48_hours_plus_5_minutes() -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    event = _prediction_record(decision, computed_at_ms=decision + 60_000)
    execution = decision + shadow.INTERVAL_MS["5m"]
    bars = _label_bars(execution)
    assert shadow.generate_labels([event], bars, execution + shadow.HOLD_MS) == []
    labels = shadow.generate_labels(
        [event], bars, execution + shadow.HOLD_MS + shadow.INTERVAL_MS["5m"]
    )
    assert len(labels) == 1
    assert labels[0]["label"] == 0
    assert labels[0]["execution_time_ms"] == execution
    assert labels[0]["exit_time_ms"] == execution + shadow.HOLD_MS


def test_label_validation_builds_timestamp_and_observation_indexes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    second_decision = first_decision + shadow.INTERVAL_MS["15m"]
    first_execution = first_decision + shadow.INTERVAL_MS["5m"]
    candles = _candles(
        shadow._iso(first_execution),
        shadow.LABEL_ROWS + 3,
        "5min",
    )
    records = [
        _prediction_record(first_decision),
        _label_record(first_decision),
        _prediction_record(second_decision),
        _label_record(second_decision),
    ]
    timestamp_calls = 0
    observation_calls = 0
    original_timestamp_index = shadow._five_minute_timestamp_index
    original_observation_map = shadow._five_minute_observation_map

    def count_timestamp_index(frame: pd.DataFrame) -> np.ndarray:
        nonlocal timestamp_calls
        timestamp_calls += 1
        return original_timestamp_index(frame)

    def count_observation_map(
        values: list[dict[str, object]],
    ) -> dict[int, tuple[int, int]]:
        nonlocal observation_calls
        observation_calls += 1
        return original_observation_map(values)

    monkeypatch.setattr(
        shadow,
        "_five_minute_timestamp_index",
        count_timestamp_index,
    )
    monkeypatch.setattr(
        shadow,
        "_five_minute_observation_map",
        count_observation_map,
    )
    shadow._validate_existing_labels(records, candles)

    assert timestamp_calls == 1
    assert observation_calls == 1


def test_poll_once_builds_replay_context_once_per_phase(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    seeds = _replay_seed_frames(decision)
    journal = tmp_path / "shadow.jsonl"
    _write_journal(journal, [shadow.build_header()])
    before = journal.read_bytes()
    counts = {
        "15m_frame": 0,
        "5m_frame": 0,
        "indicators": 0,
        "timestamp_index": 0,
        "observation_map": 0,
    }
    first_phase: dict[str, int] = {}
    original_candle_frame = shadow._candle_frame
    original_compute = shadow.compute_indicators
    original_timestamp_index = shadow._five_minute_timestamp_index
    original_observation_map = shadow._five_minute_observation_map

    def count_candle_frame(
        seed: pd.DataFrame,
        records: list[dict[str, object]],
        timeframe: str,
    ) -> pd.DataFrame:
        counts[f"{timeframe}_frame"] += 1
        return original_candle_frame(seed, records, timeframe)

    def count_compute(frame: pd.DataFrame) -> pd.DataFrame:
        counts["indicators"] += 1
        return original_compute(frame)

    def count_timestamp_index(frame: pd.DataFrame) -> np.ndarray:
        counts["timestamp_index"] += 1
        return original_timestamp_index(frame)

    def count_observation_map(
        records: list[dict[str, object]],
    ) -> dict[int, tuple[int, int]]:
        counts["observation_map"] += 1
        return original_observation_map(records)

    def fetch_nothing(*_args: object) -> list[dict[str, object]]:
        if not first_phase:
            first_phase.update(counts)
        return []

    monkeypatch.setattr(shadow, "load_model", dict)
    monkeypatch.setattr(shadow, "load_seed_frames", lambda: seeds)
    monkeypatch.setattr(shadow, "_candle_frame", count_candle_frame)
    monkeypatch.setattr(shadow, "compute_indicators", count_compute)
    monkeypatch.setattr(
        shadow,
        "_five_minute_timestamp_index",
        count_timestamp_index,
    )
    monkeypatch.setattr(
        shadow,
        "_five_minute_observation_map",
        count_observation_map,
    )
    monkeypatch.setattr(shadow, "fetch_closed_ohlcv", fetch_nothing)
    monkeypatch.setattr(shadow, "fetch_funding", lambda *_args: [])

    result = shadow.poll_once(exchange=FakeExchange(), journal_path=journal)

    expected = {
        "15m_frame": 1,
        "5m_frame": 1,
        "indicators": 1,
        "timestamp_index": 1,
        "observation_map": 1,
    }
    assert first_phase == expected
    assert {key: counts[key] - first_phase[key] for key in counts} == expected
    assert result == {
        "appended": 0,
        "event_records": 0,
        "label_records": 0,
        "status": "poll_complete",
    }
    assert journal.read_bytes() == before


@pytest.mark.parametrize(
    "tamper",
    ["label", "exit_reason", "execution_time", "exit_time"],
)
def test_tampered_label_fields_are_rejected(tamper: str) -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    execution = decision + shadow.INTERVAL_MS["5m"]
    prediction = _prediction_record(decision)
    label = _label_record(decision)
    if tamper == "label":
        label["label"] = 1
    elif tamper == "exit_reason":
        label["exit_reason"] = "stop"
    elif tamper == "execution_time":
        changed_execution = execution + shadow.INTERVAL_MS["5m"]
        label["execution_time_ms"] = changed_execution
        label["execution_time"] = shadow._iso(changed_execution)
    else:
        changed_exit = execution + shadow.HOLD_MS - shadow.INTERVAL_MS["5m"]
        label["exit_time_ms"] = changed_exit
        label["exit_time"] = shadow._iso(changed_exit)

    with pytest.raises(shadow.ShadowError, match="exact 577-row path"):
        shadow._validate_existing_labels(
            [prediction, label],
            _label_bars(execution),
        )


def test_append_is_idempotent_and_conflict_closed(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    header = shadow.build_header()
    candle = _candle_record(shadow.BOUNDARY_MS)
    _write_journal(path, [header, candle])

    duplicate = {
        **candle,
        "observed_at": shadow._iso(
            int(candle["timestamp_ms"]) + shadow.INTERVAL_MS["15m"] + 99_000
        ),
    }
    assert shadow.reconcile_records([header, candle], [duplicate]) == []
    with pytest.raises(shadow.ShadowError, match="conflicts"):
        shadow.reconcile_records([header, candle], [{**candle, "close": 100.5}])


def test_sidecar_lock_does_not_create_journal_and_data_sync_precedes_parent_sync(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "shadow.jsonl"
    lock_path = path.with_name(f"{path.name}.lock")
    sync_order: list[str] = []
    with shadow.locked_journal(path):
        assert not path.exists()
        assert lock_path.exists()
        assert lock_path.read_bytes() == b""
        monkeypatch.setattr(
            shadow.os, "fsync", lambda _descriptor: sync_order.append("data")
        )
        monkeypatch.setattr(
            shadow,
            "_sync_parent_directory",
            lambda _path: sync_order.append("parent"),
        )
        with shadow._create_journal(path) as handle:
            shadow._append_records(
                handle,
                path,
                [shadow.build_header()],
                sync_parent_entry=True,
            )

    with shadow.locked_journal(path):
        assert path.exists()
    assert sync_order == (["data"] if os.name == "nt" else ["data", "parent"])


def test_windows_creation_source_uses_create_new_and_write_through() -> None:
    source = inspect.getsource(shadow._create_windows_journal_descriptor)

    assert "CreateFileW" in source
    assert "WINDOWS_CREATE_NEW" in source
    assert "WINDOWS_FILE_FLAG_WRITE_THROUGH" in source
    assert "WINDOWS_GENERIC_READ | WINDOWS_GENERIC_WRITE" in source
    assert "os.open(" not in source


@pytest.mark.skipif(os.name != "nt", reason="Windows CreateFileW contract")
def test_windows_first_creation_is_exclusive_and_writes_exact_bytes(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "windows-create.jsonl"
    expected = shadow.canonical_json_bytes(shadow.build_header()) + b"\n"

    with shadow._create_journal(journal) as handle:
        shadow._append_records(handle, journal, [shadow.build_header()])

    assert journal.read_bytes() == expected
    with (
        pytest.raises(shadow.ShadowError, match="exclusively created"),
        shadow._create_journal(journal),
    ):
        pass


def test_sidecar_lock_requires_preexisting_parent(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "shadow.jsonl"

    with (
        pytest.raises(
            shadow.ShadowError,
            match="parent directory must already exist",
        ),
        shadow.locked_journal(path),
    ):
        pass

    assert not path.parent.exists()


@pytest.mark.parametrize(
    ("suffix", "message"),
    [
        (b'{"kind":"event_pred', "torn or unterminated"),
        (b"not-json\n", "malformed complete JSON"),
    ],
)
def test_journal_corruption_fails_closed_without_mutating_bytes(
    tmp_path: Path, suffix: bytes, message: str
) -> None:
    path = tmp_path / "shadow.jsonl"
    _write_journal(path, [shadow.build_header()])
    with path.open("ab") as handle:
        handle.write(suffix)
    before = path.read_bytes()

    with (
        shadow.locked_journal(path),
        shadow._open_existing_journal(path) as handle,
        pytest.raises(shadow.ShadowError, match=message),
    ):
        assert handle is not None
        shadow._read_journal_handle(handle)

    assert path.read_bytes() == before


def _patch_storage_only_poll(
    monkeypatch: pytest.MonkeyPatch,
    seeds: dict[str, pd.DataFrame],
) -> None:
    monkeypatch.setattr(shadow, "load_model", dict)
    monkeypatch.setattr(shadow, "load_seed_frames", lambda: seeds)
    monkeypatch.setattr(shadow, "_validate_existing_events", lambda *_args: None)
    monkeypatch.setattr(shadow, "_validate_existing_labels", lambda *_args: None)
    monkeypatch.setattr(shadow, "fetch_funding", lambda *_args: [])
    monkeypatch.setattr(shadow, "generate_events", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(shadow, "generate_labels", lambda *_args, **_kwargs: [])


def test_same_inode_valid_prefix_truncation_during_network_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    seeds = _replay_seed_frames(decision)
    journal = tmp_path / "shadow.jsonl"
    records = [shadow.build_header(), _event_source(decision)]
    _write_journal(journal, records)
    original = journal.read_bytes()
    identity = journal.stat().st_ino
    changed = False
    _patch_storage_only_poll(monkeypatch, seeds)

    def truncate_once(*_args: object) -> list[dict[str, object]]:
        nonlocal changed
        if not changed:
            journal.write_bytes(
                shadow.canonical_json_bytes(shadow.build_header()) + b"\n"
            )
            changed = True
            assert journal.stat().st_ino == identity
        raise shadow.NetworkDeferred("synthetic network failure after truncation")

    monkeypatch.setattr(shadow, "fetch_closed_ohlcv", truncate_once)
    with pytest.raises(shadow.ShadowError, match="not an exact prefix"):
        shadow.poll_once(exchange=FakeExchange(), journal_path=journal)

    assert journal.read_bytes() != original


@pytest.mark.parametrize("mutation", ["rewrite", "reorder"])
def test_same_inode_rewrite_or_reorder_during_network_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    seeds = _replay_seed_frames(decision)
    journal = tmp_path / f"{mutation}.jsonl"
    first = _event_source(decision)
    second = _candle_record(decision)
    records = [shadow.build_header(), first, second]
    _write_journal(journal, records)
    identity = journal.stat().st_ino
    changed = False
    _patch_storage_only_poll(monkeypatch, seeds)

    def mutate_once(*_args: object) -> list[dict[str, object]]:
        nonlocal changed
        if not changed:
            changed_records = copy.deepcopy(records)
            if mutation == "rewrite":
                changed_records[1]["close"] = 100.5
            else:
                changed_records[1:] = reversed(changed_records[1:])
            journal.write_bytes(
                b"".join(
                    shadow.canonical_json_bytes(record) + b"\n"
                    for record in changed_records
                )
            )
            changed = True
            assert journal.stat().st_ino == identity
        return []

    monkeypatch.setattr(shadow, "fetch_closed_ohlcv", mutate_once)
    with pytest.raises(shadow.ShadowError, match="not an exact prefix"):
        shadow.poll_once(exchange=FakeExchange(), journal_path=journal)


def test_same_inode_concurrent_append_after_exact_prefix_is_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    seeds = _replay_seed_frames(decision)
    journal = tmp_path / "shadow.jsonl"
    _write_journal(journal, [shadow.build_header()])
    identity = journal.stat().st_ino
    appended = False
    _patch_storage_only_poll(monkeypatch, seeds)

    def append_once(*_args: object) -> list[dict[str, object]]:
        nonlocal appended
        if not appended:
            with shadow._open_existing_journal(journal) as handle:
                assert handle is not None
                shadow._append_records(handle, journal, [_event_source(decision)])
            appended = True
            assert journal.stat().st_ino == identity
        return []

    monkeypatch.setattr(shadow, "fetch_closed_ohlcv", append_once)
    result = shadow.poll_once(exchange=FakeExchange(), journal_path=journal)

    assert result["appended"] == 0
    assert shadow.read_journal(journal) == [
        shadow.build_header(),
        _event_source(decision),
    ]


def test_empty_append_still_checks_path_descriptor_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    journal = tmp_path / "shadow.jsonl"
    _write_journal(journal, [shadow.build_header()])
    calls = 0
    original_verify = shadow._verify_path_identity

    def count_verify(path: Path, handle: object) -> None:
        nonlocal calls
        calls += 1
        original_verify(path, handle)  # type: ignore[arg-type]

    monkeypatch.setattr(shadow, "_verify_path_identity", count_verify)
    with shadow._open_existing_journal(journal) as handle:
        assert handle is not None
        calls = 0
        shadow._append_records(handle, journal, [])

    assert calls == 1


def test_existing_zero_byte_journal_fails_closed_before_network_without_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    journal = tmp_path / "shadow.jsonl"
    journal.write_bytes(b"")
    monkeypatch.setattr(shadow, "load_model", dict)
    monkeypatch.setattr(
        shadow,
        "load_seed_frames",
        lambda: _replay_seed_frames(shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]),
    )
    exchange = FakeExchange()

    with pytest.raises(shadow.ShadowError, match="existing zero-byte"):
        shadow.poll_once(exchange=exchange, journal_path=journal)

    assert journal.read_bytes() == b""
    assert exchange.calls == []


def test_existing_labels_are_recomputed_before_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    journal = tmp_path / "shadow.jsonl"
    _write_journal(
        journal,
        [
            shadow.build_header(),
            _event_source(decision),
            _prediction_record(decision),
            _label_record(decision, entry=101.0),
        ],
    )
    monkeypatch.setattr(shadow, "load_model", dict)
    monkeypatch.setattr(shadow, "_validate_existing_events", lambda *_args: None)
    monkeypatch.setattr(
        shadow, "load_seed_frames", lambda: _replay_seed_frames(decision)
    )
    exchange = FakeExchange()

    with pytest.raises(shadow.ShadowError, match="exact 577-row path"):
        shadow.poll_once(exchange=exchange, journal_path=journal)

    assert exchange.calls == []


def test_existing_labels_are_recomputed_after_locked_reread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    journal = tmp_path / "shadow.jsonl"
    _write_journal(
        journal,
        [shadow.build_header(), _event_source(decision), _prediction_record(decision)],
    )
    monkeypatch.setattr(shadow, "load_model", dict)
    monkeypatch.setattr(shadow, "_validate_existing_events", lambda *_args: None)
    monkeypatch.setattr(
        shadow, "load_seed_frames", lambda: _replay_seed_frames(decision)
    )
    monkeypatch.setattr(shadow, "fetch_closed_ohlcv", lambda *_args: [])
    monkeypatch.setattr(shadow, "fetch_funding", lambda *_args: [])

    original_lock = shadow.locked_journal
    lock_count = 0

    @contextmanager
    def inject_changed_journal(path: Path) -> Iterator[None]:
        nonlocal lock_count
        with original_lock(path):
            lock_count += 1
            if lock_count == 2:
                with shadow._open_existing_journal(journal) as handle:
                    assert handle is not None
                    shadow._append_records(
                        handle,
                        journal,
                        [_label_record(decision, entry=101.0)],
                    )
            yield

    monkeypatch.setattr(shadow, "locked_journal", inject_changed_journal)

    with pytest.raises(shadow.ShadowError, match="exact 577-row path"):
        shadow.poll_once(exchange=FakeExchange(), journal_path=journal)


def test_tampered_prediction_is_rejected_before_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    seeds, sources, event = _event_replay_fixture(decision)
    tampered = copy.deepcopy(event)
    tampered["features"][0] = float(tampered["features"][0]) + 0.00001
    journal = tmp_path / "shadow.jsonl"
    _write_journal(journal, [shadow.build_header(), *sources, tampered])
    monkeypatch.setattr(shadow, "load_seed_frames", lambda: seeds)
    exchange = FakeExchange()

    with pytest.raises(shadow.ShadowError, match="exact frozen replay"):
        shadow.poll_once(exchange=exchange, journal_path=journal)

    assert exchange.calls == []


def test_tampered_prediction_is_rejected_after_locked_reread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    seeds, sources, event = _event_replay_fixture(decision)
    journal = tmp_path / "shadow.jsonl"
    records = [shadow.build_header(), *sources, event]
    _write_journal(journal, records)
    monkeypatch.setattr(shadow, "load_seed_frames", lambda: seeds)
    monkeypatch.setattr(shadow, "fetch_closed_ohlcv", lambda *_args: [])
    monkeypatch.setattr(shadow, "fetch_funding", lambda *_args: [])
    original_lock = shadow.locked_journal
    lock_count = 0

    @contextmanager
    def tamper_before_second_read(path: Path) -> Iterator[None]:
        nonlocal lock_count
        lock_count += 1
        if lock_count == 2:
            changed = copy.deepcopy(records)
            changed[-1]["features"][0] = float(changed[-1]["features"][0]) + 0.00001
            journal.write_bytes(
                b"".join(shadow.canonical_json_bytes(record) + b"\n" for record in changed)
            )
        with original_lock(path):
            yield

    monkeypatch.setattr(shadow, "locked_journal", tamper_before_second_read)

    with pytest.raises(shadow.ShadowError, match="not an exact prefix"):
        shadow.poll_once(exchange=FakeExchange(), journal_path=journal)


def test_label_rejects_reordered_or_late_observed_5m_sources(tmp_path: Path) -> None:
    decision = shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    prediction = _prediction_record(decision)
    label = _label_record(decision)
    execution = decision + shadow.INTERVAL_MS["5m"]

    reordered = tmp_path / "reordered.jsonl"
    _write_journal(
        reordered,
        [
            shadow.build_header(),
            _event_source(decision),
            prediction,
            label,
            _candle_record(execution, "5m"),
        ],
    )
    with pytest.raises(shadow.ShadowError, match="precedes a required 5m source"):
        shadow.read_journal(reordered)

    matured_ms = shadow._parse_iso(label["matured_at"], "matured_at")
    late_observed = tmp_path / "late-observed.jsonl"
    _write_journal(
        late_observed,
        [
            shadow.build_header(),
            _event_source(decision),
            prediction,
            _candle_record(
                execution,
                "5m",
                observed_at_ms=matured_ms + 1,
            ),
            label,
        ],
    )
    with pytest.raises(shadow.ShadowError, match="predates a required 5m observation"):
        shadow.read_journal(late_observed)


def test_validation_failure_after_lock_leaves_initial_journal_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    journal = tmp_path / "shadow.jsonl"
    seeds = _replay_seed_frames(
        shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    )
    monkeypatch.setattr(shadow, "load_model", dict)
    monkeypatch.setattr(shadow, "load_seed_frames", lambda: seeds)
    monkeypatch.setattr(shadow, "fetch_closed_ohlcv", lambda *_args: [])
    monkeypatch.setattr(shadow, "fetch_funding", lambda *_args: [])
    monkeypatch.setattr(
        shadow,
        "generate_events",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            shadow.ShadowError("synthetic validation")
        ),
    )

    with pytest.raises(shadow.ShadowError, match="synthetic validation"):
        shadow.poll_once(exchange=FakeExchange(), journal_path=journal)

    assert not journal.exists()
    assert journal.with_name(f"{journal.name}.lock").exists()


def test_two_concurrent_first_writers_serialize_without_zero_byte_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    journal = tmp_path / "shadow.jsonl"
    seeds = _replay_seed_frames(
        shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    )
    fetch_barrier = threading.Barrier(2)
    monkeypatch.setattr(shadow, "load_model", dict)
    monkeypatch.setattr(shadow, "load_seed_frames", lambda: seeds)
    monkeypatch.setattr(shadow, "fetch_closed_ohlcv", lambda *_args: [])
    monkeypatch.setattr(
        shadow,
        "fetch_funding",
        lambda *_args: (fetch_barrier.wait(), [])[1],
    )
    monkeypatch.setattr(shadow, "generate_events", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(shadow, "generate_labels", lambda *_args, **_kwargs: [])
    results: list[dict[str, object]] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            results.append(
                shadow.poll_once(exchange=FakeExchange(), journal_path=journal)
            )
        except shadow.ShadowError as error:
            errors.append(error)

    workers = [threading.Thread(target=run) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)

    assert not any(worker.is_alive() for worker in workers)
    assert errors == []
    assert sorted(int(result["appended"]) for result in results) == [0, 1]
    assert shadow.read_journal(journal) == [shadow.build_header()]


def test_preexisting_journal_deletion_is_not_recreated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    journal = tmp_path / "shadow.jsonl"
    _write_journal(journal, [shadow.build_header()])
    seeds = _replay_seed_frames(
        shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]
    )
    monkeypatch.setattr(shadow, "load_model", dict)
    monkeypatch.setattr(shadow, "load_seed_frames", lambda: seeds)
    deleted = False

    def delete_during_fetch(*_args: object) -> list[dict[str, object]]:
        nonlocal deleted
        if not deleted:
            journal.unlink()
            deleted = True
        return []

    monkeypatch.setattr(shadow, "fetch_closed_ohlcv", delete_during_fetch)
    monkeypatch.setattr(shadow, "fetch_funding", lambda *_args: [])

    with pytest.raises(shadow.ShadowError, match="preexisting journal disappeared"):
        shadow.poll_once(exchange=FakeExchange(), journal_path=journal)

    assert not journal.exists()


def test_short_write_raises_and_cannot_report_success(tmp_path: Path) -> None:
    journal = tmp_path / "shadow.jsonl"
    journal.touch()

    class ShortWriter:
        def __init__(self, handle: object) -> None:
            self.handle = handle

        def fileno(self) -> int:
            return self.handle.fileno()  # type: ignore[no-any-return,union-attr]

        def seek(self, offset: int, whence: int = 0) -> int:
            return self.handle.seek(offset, whence)  # type: ignore[no-any-return,union-attr]

        def write(self, payload: bytes) -> int:
            return self.handle.write(payload[:-1])  # type: ignore[no-any-return,union-attr]

        def flush(self) -> None:
            self.handle.flush()  # type: ignore[union-attr]

    with journal.open("r+b", buffering=0) as real_handle:
        writer = ShortWriter(real_handle)
        with pytest.raises(shadow.ShadowError, match="short write"):
            shadow._append_records(  # type: ignore[arg-type]
                writer,
                journal,
                [shadow.build_header()],
            )

    assert journal.read_bytes()


def test_flush_failure_is_fail_closed(tmp_path: Path) -> None:
    journal = tmp_path / "shadow.jsonl"
    journal.touch()

    class FlushFailure:
        def __init__(self, handle: object) -> None:
            self.handle = handle

        def fileno(self) -> int:
            return self.handle.fileno()  # type: ignore[no-any-return,union-attr]

        def seek(self, offset: int, whence: int = 0) -> int:
            return self.handle.seek(offset, whence)  # type: ignore[no-any-return,union-attr]

        def write(self, payload: bytes) -> int:
            return self.handle.write(payload)  # type: ignore[no-any-return,union-attr]

        def flush(self) -> None:
            raise OSError("synthetic flush failure")

    with (
        journal.open("r+b", buffering=0) as real_handle,
        pytest.raises(shadow.ShadowError, match="append or fsync failed"),
    ):
        shadow._append_records(  # type: ignore[arg-type]
            FlushFailure(real_handle),
            journal,
            [shadow.build_header()],
        )


def test_v7_preregistration_is_exactly_bound_before_poll_setup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert shadow.SHADOW_PREREGISTRATION.name == "SHADOW_PREREGISTRATION_V7.md"
    assert (
        hashlib.sha256(shadow.SHADOW_PREREGISTRATION.read_bytes()).hexdigest()
        == shadow.SHADOW_PREREGISTRATION_SHA256
    )
    model_loaded = False

    def fail_hash(_path: Path) -> str:
        return "0" * 64

    def record_model_load() -> dict[str, object]:
        nonlocal model_loaded
        model_loaded = True
        return {}

    exchange = FakeExchange()
    monkeypatch.setattr(shadow, "sha256_file", fail_hash)
    monkeypatch.setattr(shadow, "load_model", record_model_load)
    with pytest.raises(shadow.ShadowError, match="preregistration SHA-256 mismatch"):
        shadow.poll_once(exchange=exchange, journal_path=tmp_path / "shadow.jsonl")
    assert not model_loaded
    assert exchange.calls == []


def test_v7_schema_rejects_a_v6_header() -> None:
    v6_header = shadow.build_header()
    v6_header["schema_version"] = 3
    v6_header["shadow_preregistration_v6_sha256"] = (
        "04678181a7c50d8adf327fc38b75f7e0b019c7140bf4d7afe9dbec56e3380326"
    )
    del v6_header["shadow_preregistration_v7_sha256"]

    with pytest.raises(shadow.ShadowError, match="schema mismatch"):
        shadow._validate_record(v6_header)


def test_consecutive_polls_advance_restart_cursors_and_do_not_duplicate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seed_frames = {
        "15m": _candles(
            shadow._iso(shadow.BOUNDARY_MS - 120 * shadow.INTERVAL_MS["15m"]),
            120,
            "15min",
        ),
        "5m": _candles(
            shadow._iso(shadow.BOUNDARY_MS - 120 * shadow.INTERVAL_MS["5m"]),
            120,
            "5min",
        ),
    }
    monkeypatch.setattr(shadow, "load_model", dict)
    monkeypatch.setattr(shadow, "load_seed_frames", lambda: seed_frames)
    monkeypatch.setattr(shadow, "generate_events", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(shadow, "generate_labels", lambda *_args, **_kwargs: [])

    def row(timestamp_ms: int) -> list[float | int]:
        return [timestamp_ms, 100.0, 101.0, 99.0, 100.0, 1.0]

    exchange = FakeExchange(
        ohlcv={
            "15m": [
                row(shadow.BOUNDARY_MS),
                row(shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"]),
            ],
            "5m": [
                row(shadow.BOUNDARY_MS + offset * shadow.INTERVAL_MS["5m"])
                for offset in range(7)
            ],
        },
        funding=[
            {
                "timestamp": shadow.BOUNDARY_MS + 60_000,
                "fundingRate": 0.0001,
            }
        ],
    )
    now_ms = shadow.BOUNDARY_MS + 20 * 60_000

    def clock() -> datetime:
        return datetime.fromtimestamp(now_ms / 1000, tz=UTC)

    journal = tmp_path / "shadow.jsonl"
    first = shadow.poll_once(exchange=exchange, clock=clock, journal_path=journal)
    assert journal.exists()
    first_calls = list(exchange.calls)
    now_ms = shadow.BOUNDARY_MS + 35 * 60_000
    second = shadow.poll_once(exchange=exchange, clock=clock, journal_path=journal)
    second_calls = exchange.calls[len(first_calls) :]

    assert first["appended"] == 7
    assert second["appended"] == 4
    assert first_calls == [
        (
            "fetch_ohlcv",
            shadow.SYMBOL,
            "15m",
            shadow.BOUNDARY_MS,
            shadow.FETCH_LIMIT,
        ),
        (
            "fetch_ohlcv",
            shadow.SYMBOL,
            "5m",
            shadow.BOUNDARY_MS,
            shadow.FETCH_LIMIT,
        ),
        (
            "fetch_funding_rate_history",
            shadow.SYMBOL,
            shadow.BOUNDARY_MS - shadow.FUNDING_MAX_AGE_MS,
            shadow.FETCH_LIMIT,
        ),
    ]
    assert second_calls == [
        (
            "fetch_ohlcv",
            shadow.SYMBOL,
            "15m",
            shadow.BOUNDARY_MS + shadow.INTERVAL_MS["15m"],
            shadow.FETCH_LIMIT,
        ),
        (
            "fetch_ohlcv",
            shadow.SYMBOL,
            "5m",
            shadow.BOUNDARY_MS + 4 * shadow.INTERVAL_MS["5m"],
            shadow.FETCH_LIMIT,
        ),
        (
            "fetch_funding_rate_history",
            shadow.SYMBOL,
            shadow.BOUNDARY_MS + 60_001,
            shadow.FETCH_LIMIT,
        ),
    ]
    records = shadow.read_journal(journal)
    keys = [shadow._record_key(record) for record in records]
    assert len(records) == 11
    assert len(keys) == len(set(keys))


def test_fake_exchange_surface_never_places_orders() -> None:
    start = shadow.BOUNDARY_MS
    exchange = FakeExchange(
        ohlcv={"5m": [[start, 100.0, 101.0, 99.0, 100.0, 1.0]]},
        funding=[],
    )
    now = datetime.fromtimestamp((start + 6 * 60 * 1000) / 1000, tz=UTC)
    shadow.fetch_closed_ohlcv(exchange, "5m", start, lambda: now)
    shadow.fetch_funding(exchange, start, lambda: now)
    assert exchange.order_calls == 0
    assert {call[0] for call in exchange.calls} == {
        "fetch_ohlcv",
        "fetch_funding_rate_history",
    }


def test_transient_fake_exchange_failure_leaves_no_journal(tmp_path: Path) -> None:
    class FailingExchange(FakeExchange):
        def fetch_ohlcv(
            self, symbol: str, timeframe: str, since: int, limit: int
        ) -> list[list[float | int]]:
            raise TimeoutError("synthetic timeout")

    journal = tmp_path / "shadow.jsonl"
    now = datetime(2026, 8, 14, 0, 1, tzinfo=UTC)

    result = shadow.poll_once(
        exchange=FailingExchange(), clock=lambda: now, journal_path=journal
    )

    assert result["status"] == "network_deferred"
    assert result["appended"] == 0
    assert not journal.exists()


def test_default_invocation_is_plan_only_without_network_or_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forbidden = tmp_path / "must-not-exist.jsonl"
    forbidden_lock = forbidden.with_name(f"{forbidden.name}.lock")

    def fail_poll() -> dict[str, object]:
        raise AssertionError("default invocation called poll_once")

    monkeypatch.setattr(shadow, "poll_once", fail_poll)
    monkeypatch.setattr(shadow, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(shadow, "JOURNAL_PATH", forbidden)
    assert shadow.main([]) == 0
    output = capsys.readouterr().out
    assert '"default_network": false' in output
    assert '"default_writes": false' in output
    assert (
        f'"shadow_preregistration_v7_sha256": "{shadow.SHADOW_PREREGISTRATION_SHA256}"'
        in output
    )
    assert "shadow_preregistration_v6_sha256" not in output
    assert not forbidden.exists()
    assert not forbidden_lock.exists()
