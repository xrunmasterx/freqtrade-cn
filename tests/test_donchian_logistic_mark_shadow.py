from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools import run_donchian_logistic_mark_shadow as shadow
from tools import run_donchian_logistic_shadow as v7


HOUR_MS = 60 * 60 * 1000


def _at(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)


def _freeze() -> shadow.Freeze:
    return shadow.Freeze(
        manifest={"test_fixture": "synthetic freeze identity"},
        manifest_sha256="f" * 64,
    )


def _jsonl(records: Sequence[Mapping[str, object]]) -> bytes:
    return b"".join(shadow.canonical_json_bytes(record) + b"\n" for record in records)


class FakeExchange:
    def __init__(
        self,
        *,
        marks: list[list[float | int]] | None = None,
        funding: list[dict[str, object]] | None = None,
        mark_capability: object = True,
    ) -> None:
        self.has = {"fetchMarkOHLCV": mark_capability}
        self.marks = marks or []
        self.funding = funding or []
        self.calls: list[tuple[object, ...]] = []
        self.forbidden_calls: list[str] = []

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int,
        limit: int,
        params: dict[str, object],
    ) -> list[list[float | int]]:
        self.calls.append(
            ("fetch_ohlcv", symbol, timeframe, since, limit, dict(params))
        )
        return [row for row in self.marks if int(row[0]) >= since][:limit]

    def publicGetPublicFundingRateHistory(
        self, request: dict[str, object]
    ) -> dict[str, object]:
        self.calls.append(
            ("publicGetPublicFundingRateHistory", dict(request))
        )
        limit = int(request["limit"])
        return {"code": "0", "msg": "", "data": self.funding[-limit:][::-1]}

    def create_order(self, *_args: object, **_kwargs: object) -> None:
        self.forbidden_calls.append("create_order")

    def fetch_balance(self, *_args: object, **_kwargs: object) -> None:
        self.forbidden_calls.append("fetch_balance")

    def fetch_positions(self, *_args: object, **_kwargs: object) -> None:
        self.forbidden_calls.append("fetch_positions")

    def fetch_my_trades(self, *_args: object, **_kwargs: object) -> None:
        self.forbidden_calls.append("fetch_my_trades")


def _mark_rows(
    start_ms: int, count: int, *, first_open: float = 100.0
) -> list[list[float | int]]:
    return [
        [
            start_ms + index * HOUR_MS,
            first_open + index,
            -999.0,
            -999.0,
            -999.0,
            -999.0,
        ]
        for index in range(count)
    ]


def _funding_row(timestamp_ms: int, rate: float) -> dict[str, object]:
    return {
        "instType": "SWAP",
        "instId": "BTC-USDT-SWAP",
        "fundingRate": str(rate),
        "realizedRate": str(rate),
        "fundingTime": str(timestamp_ms),
    }


def _projection(
    *,
    decision_ms: int | None = None,
    execution_ms: int | None = None,
) -> dict[str, object]:
    decision = shadow.BOUNDARY_MS + HOUR_MS if decision_ms is None else decision_ms
    execution = decision + 5 * 60_000 if execution_ms is None else execution_ms
    return {
        "kind": "event_projection",
        "symbol": shadow.SYMBOL,
        "decision_time": shadow._iso(decision),
        "decision_time_ms": decision,
        "direction": "long",
        "execution_time": shadow._iso(execution),
        "execution_time_ms": execution,
        "event_sha256": "1" * 64,
        "v7_prefix_byte_length": 123,
        "v7_prefix_sha256": "2" * 64,
    }


def _receipt(
    projection: Mapping[str, object], durable_at_ms: int
) -> dict[str, object]:
    execution_ms = int(projection["execution_time_ms"])
    return {
        "kind": "publication_receipt",
        "decision_time": projection["decision_time"],
        "decision_time_ms": projection["decision_time_ms"],
        "direction": projection["direction"],
        "execution_time": projection["execution_time"],
        "execution_time_ms": execution_ms,
        "projection_sha256": hashlib.sha256(
            shadow.canonical_json_bytes(projection)
        ).hexdigest(),
        "projection_durable_at": shadow._iso(durable_at_ms),
        "projection_durable_at_ms": durable_at_ms,
        "eligible": durable_at_ms < execution_ms,
    }


def _event_prediction(
    *,
    decision_ms: int | None = None,
    execution_ms: int | None = None,
) -> dict[str, object]:
    decision = shadow.BOUNDARY_MS + HOUR_MS if decision_ms is None else decision_ms
    execution = decision + 5 * 60_000 if execution_ms is None else execution_ms
    return {
        "computed_at": shadow._iso(decision),
        "computed_at_ms": decision,
        "decision_time": shadow._iso(decision),
        "decision_time_ms": decision,
        "direction": "long",
        "execution_time": shadow._iso(execution),
        "execution_time_ms": execution,
        "features": [0.0] * len(v7.FEATURE_ORDER),
        "kind": "event_prediction",
        "predicted_positive": True,
        "probability": 0.5,
        "signal_time": shadow._iso(decision - v7.INTERVAL_MS["15m"]),
        "threshold": 0.5,
    }


def _fetch_marks(
    rows: list[list[float | int]],
    *,
    cutoff_ms: int,
    observed_at_ms: int | None = None,
    start_ms: int = shadow.BOUNDARY_MS,
) -> list[dict[str, object]]:
    observed = cutoff_ms + 10_000 if observed_at_ms is None else observed_at_ms
    return shadow.fetch_mark_open_observations(
        FakeExchange(marks=rows),
        start_ms,
        cutoff_ms,
        lambda: _at(observed),
    )


def _fetch_funding(
    rows: list[dict[str, object]],
    *,
    cutoff_ms: int,
    observed_at_ms: int | None = None,
) -> list[dict[str, object]]:
    observed = cutoff_ms + 10_000 if observed_at_ms is None else observed_at_ms
    return shadow.fetch_funding_settlements(
        FakeExchange(funding=rows),
        shadow.BOUNDARY_MS + 1,
        cutoff_ms,
        lambda: _at(observed),
    )


def test_mark_open_observation_includes_forming_hour_and_uses_only_mark_open() -> None:
    cutoff = shadow.BOUNDARY_MS + HOUR_MS
    exchange = FakeExchange(marks=_mark_rows(shadow.BOUNDARY_MS, 2))
    observed = cutoff + 2 * 60_000

    records = shadow.fetch_mark_open_observations(
        exchange,
        shadow.BOUNDARY_MS,
        cutoff,
        lambda: _at(observed),
    )

    assert records == [
        {
            "kind": "mark_open_observation",
            "timestamp": shadow._iso(shadow.BOUNDARY_MS),
            "timestamp_ms": shadow.BOUNDARY_MS,
            "open": 100.0,
            "observed_at": shadow._iso(observed),
            "observed_at_ms": observed,
            "source_method": "ccxt.fetch_ohlcv.price_mark",
        },
        {
            "kind": "mark_open_observation",
            "timestamp": shadow._iso(cutoff),
            "timestamp_ms": cutoff,
            "open": 101.0,
            "observed_at": shadow._iso(observed),
            "observed_at_ms": observed,
            "source_method": "ccxt.fetch_ohlcv.price_mark",
        },
    ]
    assert exchange.calls == [
        (
            "fetch_ohlcv",
            shadow.SYMBOL,
            "1h",
            shadow.BOUNDARY_MS,
            shadow.FETCH_LIMIT,
            {"paginate": False, "price": "mark"},
        )
    ]
    assert exchange.forbidden_calls == []
    assert all(
        not ({"high", "low", "close", "volume"} & set(record))
        for record in records
    )


@pytest.mark.parametrize("capability", [False, None, "emulated"])
def test_mark_capability_must_be_literal_true_before_fetch(capability: object) -> None:
    exchange = FakeExchange(
        marks=_mark_rows(shadow.BOUNDARY_MS, 1),
        mark_capability=capability,
    )

    with pytest.raises(shadow.ShadowError, match="fetchMarkOHLCV"):
        shadow.fetch_mark_open_observations(
            exchange,
            shadow.BOUNDARY_MS,
            shadow.BOUNDARY_MS,
            lambda: _at(shadow.BOUNDARY_MS + 1),
        )

    assert exchange.calls == []


def test_mark_rows_must_start_at_boundary_and_remain_hourly() -> None:
    gap = [
        *_mark_rows(shadow.BOUNDARY_MS, 1),
        *_mark_rows(shadow.BOUNDARY_MS + 2 * HOUR_MS, 1),
    ]

    with pytest.raises(shadow.ShadowError, match=r"continuous|consecutive|gap"):
        _fetch_marks(gap, cutoff_ms=shadow.BOUNDARY_MS + 2 * HOUR_MS)

    late_start = _mark_rows(shadow.BOUNDARY_MS + HOUR_MS, 1)
    with pytest.raises(shadow.ShadowError, match=r"boundary|start|continuous|gap"):
        _fetch_marks(late_start, cutoff_ms=shadow.BOUNDARY_MS + HOUR_MS)


def test_fetch_round_is_bounded_by_fixed_cutoff() -> None:
    cutoff = shadow.BOUNDARY_MS + HOUR_MS
    after_cutoff = cutoff + HOUR_MS
    mark_exchange = FakeExchange(marks=_mark_rows(shadow.BOUNDARY_MS, 3))
    funding_exchange = FakeExchange(
        funding=[
            _funding_row(cutoff, 0.0001),
        ]
    )

    marks = shadow.fetch_mark_open_observations(
        mark_exchange,
        shadow.BOUNDARY_MS,
        cutoff,
        lambda: _at(after_cutoff + 1),
    )
    funding = shadow.fetch_funding_settlements(
        funding_exchange,
        shadow.BOUNDARY_MS + 1,
        cutoff,
        lambda: _at(after_cutoff + 1),
    )

    assert [record["timestamp_ms"] for record in marks] == [
        shadow.BOUNDARY_MS,
        cutoff,
    ]
    assert [record["raw_settlement_timestamp_ms"] for record in funding] == [cutoff]


def test_mark_manual_pagination_over_one_hundred_is_complete_and_exact() -> None:
    rows = _mark_rows(shadow.BOUNDARY_MS, 205)
    cutoff = shadow.BOUNDARY_MS + 204 * HOUR_MS
    exchange = FakeExchange(marks=rows)

    records = shadow.fetch_mark_open_observations(
        exchange,
        shadow.BOUNDARY_MS,
        cutoff,
        lambda: _at(cutoff + 1),
    )

    timestamps = [int(record["timestamp_ms"]) for record in records]
    assert timestamps == [shadow.BOUNDARY_MS + index * HOUR_MS for index in range(205)]
    assert len(timestamps) == len(set(timestamps)) == 205
    assert exchange.calls == [
        (
            "fetch_ohlcv",
            shadow.SYMBOL,
            "1h",
            shadow.BOUNDARY_MS + page * 100 * HOUR_MS,
            100,
            {"paginate": False, "price": "mark"},
        )
        for page in range(3)
    ]


def test_funding_single_page_of_ninety_nine_is_complete_and_exact() -> None:
    timestamps = [
        shadow.BOUNDARY_MS + 1 + index * 73 * 60_000 for index in range(1, 100)
    ]
    rows = [
        _funding_row(timestamp, index / 1_000_000)
        for index, timestamp in enumerate(timestamps)
    ]
    exchange = FakeExchange(funding=rows)

    records = shadow.fetch_funding_settlements(
        exchange,
        shadow.BOUNDARY_MS + 1,
        timestamps[-1],
        lambda: _at(timestamps[-1] + 1),
    )

    actual = [int(record["raw_settlement_timestamp_ms"]) for record in records]
    assert actual == timestamps
    assert len(actual) == len(set(actual)) == 99
    assert exchange.calls == [
        (
            "publicGetPublicFundingRateHistory",
            {
                "instId": shadow.OKX_INSTRUMENT_ID,
                "before": shadow.BOUNDARY_MS,
                "limit": 100,
            },
        )
    ]


def test_full_funding_page_is_ambiguous_and_fails_without_accounting_write(
    tmp_path: Path,
) -> None:
    timestamps = [
        shadow.BOUNDARY_MS + 1 + index * 3 * 60_000 for index in range(1, 101)
    ]

    cutoff = timestamps[-1]
    raw_rows = [
        _funding_row(timestamp, index / 1_000_000)
        for index, timestamp in enumerate(timestamps)
    ]
    raw_rows[50]["instId"] = "ETH-USDT-SWAP"
    exchange = FakeExchange(
        marks=_mark_rows(
            shadow.BOUNDARY_MS,
            (cutoff // HOUR_MS * HOUR_MS - shadow.BOUNDARY_MS) // HOUR_MS + 1,
        ),
        funding=raw_rows,
    )
    accounting = tmp_path / "accounting.jsonl"

    with pytest.raises(shadow.ShadowError, match=r"full|limit|ambiguous|backlog"):
        shadow.poll_accounting(
            exchange,
            path=accounting,
            clock=lambda: _at(cutoff + 1),
            freeze=_freeze(),
        )

    assert not accounting.exists()
    funding_calls = [
        call for call in exchange.calls if call[0] == "publicGetPublicFundingRateHistory"
    ]
    assert funding_calls == [
        (
            "publicGetPublicFundingRateHistory",
            {
                "instId": shadow.OKX_INSTRUMENT_ID,
                "before": shadow.BOUNDARY_MS,
                "limit": 100,
            },
        )
    ]


def test_second_accounting_poll_advances_raw_cursor_and_is_idempotent(
    tmp_path: Path,
) -> None:
    raw_ms = shadow.BOUNDARY_MS + 1_000
    path = tmp_path / "accounting.jsonl"
    first = FakeExchange(
        marks=_mark_rows(shadow.BOUNDARY_MS, 1),
        funding=[_funding_row(raw_ms, 0.0001)],
    )
    freeze = _freeze()

    initial = shadow.poll_accounting(
        first,
        path=path,
        clock=lambda: _at(raw_ms + 1),
        freeze=freeze,
    )
    original = path.read_bytes()
    second = FakeExchange(marks=_mark_rows(shadow.BOUNDARY_MS, 1))
    repeated = shadow.poll_accounting(
        second,
        path=path,
        clock=lambda: _at(raw_ms + 2),
        freeze=freeze,
    )

    assert initial["funding_settlements"] == 1
    assert repeated["appended"] == 0
    assert path.read_bytes() == original
    funding_calls = [
        call
        for call in second.calls
        if call[0] == "publicGetPublicFundingRateHistory"
    ]
    assert funding_calls == [
        (
            "publicGetPublicFundingRateHistory",
            {
                "instId": shadow.OKX_INSTRUMENT_ID,
                "before": raw_ms,
                "limit": shadow.FETCH_LIMIT,
            },
        )
    ]


def test_programmer_type_errors_are_not_reported_as_network_deferred() -> None:
    class BuggyExchange(FakeExchange):
        def fetch_ohlcv(
            self,
            symbol: str,
            timeframe: str,
            since: int,
            limit: int,
            params: dict[str, object],
        ) -> list[list[float | int]]:
            raise TypeError("synthetic mark integration bug")

        def publicGetPublicFundingRateHistory(
            self, request: dict[str, object]
        ) -> dict[str, object]:
            raise TypeError("synthetic funding integration bug")

    exchange = BuggyExchange()
    with pytest.raises(shadow.ShadowError, match="outside the recoverable") as mark_error:
        shadow.fetch_mark_open_observations(
            exchange,
            shadow.BOUNDARY_MS,
            shadow.BOUNDARY_MS,
            lambda: _at(shadow.BOUNDARY_MS + 1),
        )
    assert not isinstance(mark_error.value, shadow.NetworkDeferred)
    assert isinstance(mark_error.value.__cause__, TypeError)
    with pytest.raises(shadow.ShadowError, match="outside the recoverable") as funding_error:
        shadow.fetch_funding_settlements(
            exchange,
            shadow.BOUNDARY_MS + 1,
            shadow.BOUNDARY_MS + 1,
            lambda: _at(shadow.BOUNDARY_MS + 2),
        )
    assert not isinstance(funding_error.value, shadow.NetworkDeferred)
    assert isinstance(funding_error.value.__cause__, TypeError)


def test_raw_okx_funding_request_is_exact_and_has_no_pagination_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeExchange()
    captured: list[dict[str, object]] = []

    def fake_request(request: dict[str, object]) -> dict[str, object]:
        captured.append(dict(request))
        return {"code": "0", "data": [], "msg": ""}

    monkeypatch.setattr(client, "publicGetPublicFundingRateHistory", fake_request)
    since = shadow.BOUNDARY_MS + 123_456

    assert shadow.fetch_funding_settlements(
        client,
        since,
        since,
        lambda: _at(since + 1),
    ) == []
    assert captured == [
        {
            "instId": shadow.OKX_INSTRUMENT_ID,
            "before": since - 1,
            "limit": 100,
        }
    ]


def test_irregular_funding_preserves_raw_timestamp_and_utc_minute_floor() -> None:
    first = shadow.BOUNDARY_MS + HOUR_MS + 43_210
    second = shadow.BOUNDARY_MS + 3 * HOUR_MS + 58_999
    cutoff = shadow.BOUNDARY_MS + 4 * HOUR_MS
    exchange = FakeExchange(
        funding=[
            _funding_row(first, 0.0001),
            _funding_row(second, -0.0002),
        ]
    )
    observed = cutoff + 15_000

    records = shadow.fetch_funding_settlements(
        exchange,
        shadow.BOUNDARY_MS + 1,
        cutoff,
        lambda: _at(observed),
    )

    assert [record["raw_settlement_timestamp_ms"] for record in records] == [
        first,
        second,
    ]
    assert [record["accounting_timestamp_ms"] for record in records] == [
        first // 60_000 * 60_000,
        second // 60_000 * 60_000,
    ]
    assert [record["rate"] for record in records] == [0.0001, -0.0002]
    assert all(
        record["source_method"] == "ccxt.okx.publicGetPublicFundingRateHistory"
        and record["observed_at_ms"] == observed
        for record in records
    )
    assert exchange.calls == [
        (
            "publicGetPublicFundingRateHistory",
            {
                "instId": shadow.OKX_INSTRUMENT_ID,
                "before": shadow.BOUNDARY_MS,
                "limit": shadow.FETCH_LIMIT,
            },
        )
    ]
    assert exchange.forbidden_calls == []


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        (lambda row: row.pop("realizedRate"), "schema"),
        (lambda row: row.update(extra="drift"), "schema"),
        (lambda row: row.update(realizedRate="NaN"), "finite|realizedRate"),
        (lambda row: row.update(fundingTime="not-a-timestamp"), "fundingTime"),
        (lambda row: row.update(instId="ETH-USDT-SWAP"), "instId|instrument"),
        (lambda row: row.update(instType="FUTURES"), "instType|market"),
        (lambda row: row.update(fundingRate="Infinity"), "finite|fundingRate"),
    ],
)
def test_funding_requires_exact_okx_raw_provenance(
    tamper: Callable[[dict[str, object]], object], message: str
) -> None:
    timestamp = shadow.BOUNDARY_MS + HOUR_MS
    row = _funding_row(timestamp, 0.0001)
    tamper(row)

    with pytest.raises(shadow.ShadowError, match=message):
        _fetch_funding([row], cutoff_ms=timestamp)


@pytest.mark.parametrize(
    ("offsets", "cutoff_offset", "message"),
    [
        ([60_000, 120_000], 120_000, "descending|order"),
        ([60_000, 60_000], 60_000, "duplicate|descending"),
        ([-1], 60_000, "cursor"),
        ([60_001], 60_000, "cutoff"),
    ],
)
def test_raw_funding_rejects_order_duplicate_and_range_violations(
    monkeypatch: pytest.MonkeyPatch,
    offsets: list[int],
    cutoff_offset: int,
    message: str,
) -> None:
    cursor = shadow.BOUNDARY_MS + 1
    rows = [_funding_row(cursor + offset, 0.0001) for offset in offsets]
    exchange = FakeExchange()

    def fake_request(_request: dict[str, object]) -> dict[str, object]:
        return {"code": "0", "msg": "", "data": rows}

    monkeypatch.setattr(exchange, "publicGetPublicFundingRateHistory", fake_request)
    with pytest.raises(shadow.ShadowError, match=message):
        shadow.fetch_funding_settlements(
            exchange,
            cursor,
            cursor + cutoff_offset,
            lambda: _at(cursor + cutoff_offset + 1),
        )


@pytest.mark.parametrize(
    "response",
    [
        {"code": "0", "msg": ""},
        {"code": "0", "msg": "", "data": [], "extra": None},
        {"code": 0, "msg": "", "data": []},
        {"code": "0", "msg": "unexpected", "data": []},
        {"code": "0", "msg": "", "data": ()},
    ],
)
def test_raw_funding_requires_exact_success_envelope(
    monkeypatch: pytest.MonkeyPatch,
    response: object,
) -> None:
    exchange = FakeExchange()
    monkeypatch.setattr(
        exchange,
        "publicGetPublicFundingRateHistory",
        lambda _request: response,
    )

    with pytest.raises(shadow.ShadowError, match=r"envelope|error|data"):
        shadow.fetch_funding_settlements(
            exchange,
            shadow.BOUNDARY_MS + 1,
            shadow.BOUNDARY_MS + 1,
            lambda: _at(shadow.BOUNDARY_MS + 2),
        )


def test_two_raw_funding_timestamps_in_one_accounting_minute_fail_closed() -> None:
    minute = shadow.BOUNDARY_MS + HOUR_MS
    rows = [
        _funding_row(minute + 1_000, 0.0001),
        _funding_row(minute + 59_000, 0.0001),
    ]

    with pytest.raises(shadow.ShadowError, match=r"collision|same.*minute"):
        _fetch_funding(rows, cutoff_ms=minute + 60_000)


def test_exact_minute_join_replays_pinned_open_mark_and_open_fund() -> None:
    mark_tail = shadow.BOUNDARY_MS + 3 * HOUR_MS
    marks = _fetch_marks(
        _mark_rows(shadow.BOUNDARY_MS, 4),
        cutoff_ms=mark_tail,
    )
    first_raw = shadow.BOUNDARY_MS + HOUR_MS + 13_000
    second_raw = shadow.BOUNDARY_MS + 3 * HOUR_MS + 49_000
    funding = _fetch_funding(
        [
            _funding_row(first_raw, 0.0001),
            _funding_row(second_raw, -0.0002),
        ],
        cutoff_ms=mark_tail + 59_000,
    )
    freeze = _freeze()
    sources = [shadow.build_header("accounting", freeze), *marks, *funding]

    joins = shadow.generate_accounting_joins(sources)

    assert len(joins) == 2
    assert [(join["open_mark"], join["open_fund"]) for join in joins] == [
        (101.0, 0.0001),
        (103.0, -0.0002),
    ]
    assert [join["raw_settlement_timestamp_ms"] for join in joins] == [
        first_raw,
        second_raw,
    ]
    for join, funding_record in zip(joins, funding, strict=True):
        accounting_ms = int(join["accounting_timestamp_ms"])
        mark = next(record for record in marks if record["timestamp_ms"] == accounting_ms)
        assert join["mark_record_sha256"] == hashlib.sha256(
            shadow.canonical_json_bytes(mark)
        ).hexdigest()
        assert join["funding_record_sha256"] == hashlib.sha256(
            shadow.canonical_json_bytes(funding_record)
        ).hexdigest()
        assert set(join) == {
            "kind",
            "raw_settlement_timestamp",
            "raw_settlement_timestamp_ms",
            "accounting_timestamp",
            "accounting_timestamp_ms",
            "open_mark",
            "open_fund",
            "mark_record_sha256",
            "funding_record_sha256",
        }

    prospective = [*sources, *joins]
    assert shadow._parse_journal(_jsonl(prospective), "accounting", freeze) == prospective


def test_pending_funding_is_preserved_then_joined_when_exact_mark_arrives() -> None:
    pending_raw = shadow.BOUNDARY_MS + 2 * HOUR_MS + 1_000
    first_mark = _fetch_marks(
        _mark_rows(shadow.BOUNDARY_MS, 1),
        cutoff_ms=shadow.BOUNDARY_MS,
    )
    funding = _fetch_funding(
        [_funding_row(pending_raw, 0.0003)],
        cutoff_ms=pending_raw,
    )
    freeze = _freeze()
    header = shadow.build_header("accounting", freeze)
    pending = [header, *first_mark, *funding]

    assert shadow.generate_accounting_joins(pending) == []
    assert shadow._parse_journal(_jsonl(pending), "accounting", freeze) == pending

    later_marks = _fetch_marks(
        _mark_rows(shadow.BOUNDARY_MS + HOUR_MS, 2, first_open=101.0),
        cutoff_ms=shadow.BOUNDARY_MS + 2 * HOUR_MS,
        start_ms=shadow.BOUNDARY_MS + HOUR_MS,
    )
    ready = [*pending, *later_marks]
    joins = shadow.generate_accounting_joins(ready)
    assert len(joins) == 1
    assert joins[0]["accounting_timestamp_ms"] == shadow.BOUNDARY_MS + 2 * HOUR_MS
    prospective = [*ready, *joins]
    assert shadow._parse_journal(_jsonl(prospective), "accounting", freeze) == prospective


def test_off_grid_accounting_minute_fails_once_mark_tail_has_passed() -> None:
    marks = _fetch_marks(
        _mark_rows(shadow.BOUNDARY_MS, 3),
        cutoff_ms=shadow.BOUNDARY_MS + 2 * HOUR_MS,
    )
    raw = shadow.BOUNDARY_MS + HOUR_MS + 60_000 + 7_000
    funding = _fetch_funding(
        [_funding_row(raw, 0.0001)],
        cutoff_ms=raw,
    )
    records = [shadow.build_header("accounting", _freeze()), *marks, *funding]

    with pytest.raises(shadow.ShadowError, match=r"exact.*mark|mark.*open|off-grid"):
        shadow.generate_accounting_joins(records)


def test_first_seen_market_values_are_idempotent_but_revisions_conflict() -> None:
    freeze = _freeze()
    header = shadow.build_header("accounting", freeze)
    mark = _fetch_marks(
        _mark_rows(shadow.BOUNDARY_MS, 1),
        cutoff_ms=shadow.BOUNDARY_MS,
    )[0]
    later_repeat = {
        **mark,
        "observed_at": shadow._iso(int(mark["observed_at_ms"]) + 60_000),
        "observed_at_ms": int(mark["observed_at_ms"]) + 60_000,
    }

    assert shadow.reconcile_records(
        [header, mark], [later_repeat], "accounting"
    ) == []
    with pytest.raises(shadow.ShadowError, match=r"conflict|revision"):
        shadow.reconcile_records(
            [header, mark], [{**later_repeat, "open": 100.01}], "accounting"
        )

    raw = shadow.BOUNDARY_MS + HOUR_MS + 1_000
    funding = _fetch_funding(
        [_funding_row(raw, 0.0001)],
        cutoff_ms=raw,
    )[0]
    later_funding = {
        **funding,
        "observed_at": shadow._iso(int(funding["observed_at_ms"]) + 60_000),
        "observed_at_ms": int(funding["observed_at_ms"]) + 60_000,
    }
    assert shadow.reconcile_records(
        [header, funding], [later_funding], "accounting"
    ) == []
    with pytest.raises(shadow.ShadowError, match=r"conflict|revision"):
        shadow.reconcile_records(
            [header, funding],
            [{**later_funding, "rate": 0.0002}],
            "accounting",
        )


def test_accounting_join_cannot_precede_either_source_or_silently_disappear() -> None:
    freeze = _freeze()
    header = shadow.build_header("accounting", freeze)
    raw = shadow.BOUNDARY_MS + 1_000
    marks = _fetch_marks(
        _mark_rows(shadow.BOUNDARY_MS, 1),
        cutoff_ms=shadow.BOUNDARY_MS,
    )
    funding = _fetch_funding(
        [_funding_row(raw, 0.0001)],
        cutoff_ms=raw,
    )
    sources = [header, *marks, *funding]
    join = shadow.generate_accounting_joins(sources)[0]

    with pytest.raises(shadow.ShadowError, match=r"source|preced"):
        shadow._parse_journal(
            _jsonl([header, join, *marks, *funding]), "accounting", freeze
        )
    with pytest.raises(shadow.ShadowError, match=r"join|missing|accounting"):
        shadow._parse_journal(_jsonl(sources), "accounting", freeze)


def test_accounting_journal_requires_boundary_mark_even_with_no_funding() -> None:
    freeze = _freeze()
    header = shadow.build_header("accounting", freeze)
    late = _fetch_marks(
        _mark_rows(shadow.BOUNDARY_MS + HOUR_MS, 1),
        cutoff_ms=shadow.BOUNDARY_MS + HOUR_MS,
        start_ms=shadow.BOUNDARY_MS + HOUR_MS,
    )[0]

    with pytest.raises(shadow.ShadowError, match=r"boundary|first mark"):
        shadow._parse_journal(_jsonl([header, late]), "accounting", freeze)


def test_v8_parser_is_independent_and_rejects_a_v7_header() -> None:
    raw = v7.canonical_json_bytes(v7.build_header()) + b"\n"

    with pytest.raises(shadow.ShadowError, match=r"header|schema|journal"):
        shadow._parse_journal(raw, "accounting", _freeze())


def test_publication_schema_is_label_free_and_requires_projection_before_receipt() -> None:
    freeze = _freeze()
    projection = _projection()
    receipt = _receipt(projection, int(projection["execution_time_ms"]) - 1)
    records = [shadow.build_header("publication", freeze), projection, receipt]

    assert shadow._parse_journal(_jsonl(records), "publication", freeze) == records
    assert receipt["eligible"] is True
    assert not (
        {
            "label",
            "entry",
            "exit",
            "exit_time",
            "exit_reason",
            "fee",
            "pnl",
            "profit",
        }
        & set(projection)
    )

    reordered = [records[0], receipt, projection]
    with pytest.raises(shadow.ShadowError, match=r"projection|preced"):
        shadow._parse_journal(_jsonl(reordered), "publication", freeze)


def test_publication_eligibility_is_strict_and_orphan_is_valid_but_ineligible() -> None:
    freeze = _freeze()
    header = shadow.build_header("publication", freeze)
    projection = _projection()
    execution_ms = int(projection["execution_time_ms"])

    orphan = [header, projection]
    assert shadow._parse_journal(_jsonl(orphan), "publication", freeze) == orphan

    equal_receipt = _receipt(projection, execution_ms)
    assert equal_receipt["eligible"] is False
    equal_records = [*orphan, equal_receipt]
    assert (
        shadow._parse_journal(_jsonl(equal_records), "publication", freeze)
        == equal_records
    )

    lied = {**equal_receipt, "eligible": True}
    with pytest.raises(shadow.ShadowError, match=r"eligible|strict"):
        shadow._parse_journal(_jsonl([*orphan, lied]), "publication", freeze)

    regressed = _receipt(projection, int(projection["decision_time_ms"]) - 1)
    with pytest.raises(shadow.ShadowError, match=r"decision|durable|regress"):
        shadow._parse_journal(
            _jsonl([*orphan, regressed]), "publication", freeze
        )


def test_record_publication_writes_projection_before_sampling_durable_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    publication = tmp_path / "publication.jsonl"
    freeze = _freeze()
    event = _event_prediction()
    v7_raw = v7.canonical_json_bytes(event) + b"\n"
    execution_ms = int(event["execution_time_ms"])
    calls: list[tuple[str, int | None]] = []
    original_append = shadow._append_records

    def observe_append(
        handle: object,
        path: Path,
        records: Sequence[Mapping[str, object]],
        *,
        sync_parent_entry: bool = False,
    ) -> None:
        calls.append(
            (
                "append",
                None if not records else 1 if records[-1]["kind"] == "event_projection" else 2,
            )
        )
        original_append(
            handle,  # type: ignore[arg-type]
            path,
            records,
            sync_parent_entry=sync_parent_entry,
        )

    def clock() -> datetime:
        calls.append(("clock", None))
        return _at(execution_ms - 1)

    monkeypatch.setattr(shadow, "_append_records", observe_append)

    result = shadow.record_publication(
        [event], v7_raw, path=publication, clock=clock, freeze=freeze
    )

    assert result == {
        "status": "publication_complete",
        "projections": 1,
        "receipts": 1,
        "eligible": 1,
        "ineligible": 0,
        "appended": 3,
    }
    assert calls == [("append", 1), ("clock", None), ("append", 2)]
    records = shadow.read_journal(publication, "publication", freeze)
    assert [record["kind"] for record in records] == [
        "header",
        "event_projection",
        "publication_receipt",
    ]
    assert records[-1]["projection_durable_at_ms"] == execution_ms - 1
    assert records[-1]["eligible"] is True


def test_orphan_projection_is_refsynced_then_receipted_at_current_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    publication = tmp_path / "publication.jsonl"
    freeze = _freeze()
    event = _event_prediction()
    v7_raw = v7.canonical_json_bytes(event) + b"\n"
    execution_ms = int(event["execution_time_ms"])
    original_append = shadow._append_records
    phase = "create_orphan"

    def fail_receipt_once(
        handle: object,
        path: Path,
        records: Sequence[Mapping[str, object]],
        *,
        sync_parent_entry: bool = False,
    ) -> None:
        nonlocal phase
        if phase == "create_orphan" and records and records[-1]["kind"] == "publication_receipt":
            phase = "recover"
            raise shadow.ShadowError("synthetic receipt failure")
        original_append(
            handle,  # type: ignore[arg-type]
            path,
            records,
            sync_parent_entry=sync_parent_entry,
        )

    monkeypatch.setattr(shadow, "_append_records", fail_receipt_once)
    with pytest.raises(shadow.ShadowError, match="synthetic receipt failure"):
        shadow.record_publication(
            [event],
            v7_raw,
            path=publication,
            clock=lambda: _at(execution_ms - 1),
            freeze=freeze,
        )

    orphan = shadow.read_journal(publication, "publication", freeze)
    assert [record["kind"] for record in orphan] == ["header", "event_projection"]

    fsync_before_clock: list[str] = []
    original_fsync = shadow.os.fsync

    def observe_fsync(descriptor: int) -> None:
        fsync_before_clock.append("fsync")
        original_fsync(descriptor)

    def recovery_clock() -> datetime:
        fsync_before_clock.append("clock")
        return _at(execution_ms + 1)

    monkeypatch.setattr(shadow.os, "fsync", observe_fsync)
    recovered = shadow.record_publication(
        [event],
        v7_raw,
        path=publication,
        clock=recovery_clock,
        freeze=freeze,
    )

    assert fsync_before_clock[:2] == ["fsync", "clock"]
    assert recovered["projections"] == 0
    assert recovered["receipts"] == 1
    assert recovered["eligible"] == 0
    assert recovered["ineligible"] == 1
    assert recovered["appended"] == 1
    records = shadow.read_journal(publication, "publication", freeze)
    assert records[-1]["projection_durable_at_ms"] == execution_ms + 1
    assert records[-1]["eligible"] is False


def test_labels_in_v7_raw_never_select_a_projection(tmp_path: Path) -> None:
    publication = tmp_path / "publication.jsonl"
    freeze = _freeze()
    event = _event_prediction()
    label = {
        "kind": "label_matured",
        "decision_time": event["decision_time"],
        "decision_time_ms": event["decision_time_ms"],
        "direction": event["direction"],
        "entry": 100.0,
        "execution_time": event["execution_time"],
        "execution_time_ms": event["execution_time_ms"],
        "exit_reason": "deadline_open",
        "exit_time": shadow._iso(int(event["execution_time_ms"]) + v7.HOLD_MS),
        "exit_time_ms": int(event["execution_time_ms"]) + v7.HOLD_MS,
        "label": 0,
        "matured_at": shadow._iso(
            int(event["execution_time_ms"]) + v7.HOLD_MS + v7.INTERVAL_MS["5m"]
        ),
    }
    raw = v7.canonical_json_bytes(label) + b"\n"

    result = shadow.record_publication(
        [],
        raw,
        path=publication,
        clock=lambda: (_ for _ in ()).throw(
            AssertionError("label-only publication sampled a durable time")
        ),
        freeze=freeze,
    )

    assert result == {
        "status": "publication_complete",
        "projections": 0,
        "receipts": 0,
        "eligible": 0,
        "ineligible": 0,
        "appended": 1,
    }
    assert shadow.read_journal(publication, "publication", freeze) == [
        shadow.build_header("publication", freeze)
    ]
    with pytest.raises(shadow.ShadowError, match="only V7 event_prediction"):
        shadow._build_projection(label, raw)


def test_repeated_exact_publication_is_an_idempotent_first_writer_win(
    tmp_path: Path,
) -> None:
    publication = tmp_path / "publication.jsonl"
    freeze = _freeze()
    event = _event_prediction()
    raw = v7.canonical_json_bytes(event) + b"\n"
    execution_ms = int(event["execution_time_ms"])

    first = shadow.record_publication(
        [event],
        raw,
        path=publication,
        clock=lambda: _at(execution_ms - 1),
        freeze=freeze,
    )
    before = publication.read_bytes()
    second = shadow.record_publication(
        [event],
        raw,
        path=publication,
        clock=lambda: (_ for _ in ()).throw(
            AssertionError("idempotent complete publication sampled the clock")
        ),
        freeze=freeze,
    )

    assert first["appended"] == 3
    assert second == {
        "status": "publication_complete",
        "projections": 0,
        "receipts": 0,
        "eligible": 0,
        "ineligible": 0,
        "appended": 0,
    }
    assert publication.read_bytes() == before


def test_growing_v7_prefix_preserves_old_projection_and_only_projects_new_event(
    tmp_path: Path,
) -> None:
    publication = tmp_path / "publication.jsonl"
    freeze = _freeze()
    first_event = _event_prediction()
    first_raw = v7.canonical_json_bytes(first_event) + b"\n"
    first_execution = int(first_event["execution_time_ms"])
    shadow.record_publication(
        [first_event],
        first_raw,
        path=publication,
        clock=lambda: _at(first_execution - 1),
        freeze=freeze,
    )
    old_projection = shadow.read_journal(publication, "publication", freeze)[1]

    second_event = _event_prediction(
        decision_ms=int(first_event["decision_time_ms"]) + HOUR_MS,
    )
    grown_raw = first_raw + v7.canonical_json_bytes(second_event) + b"\n"
    no_new_event = shadow.record_publication(
        [first_event],
        grown_raw,
        path=publication,
        clock=lambda: (_ for _ in ()).throw(
            AssertionError("old projection was replaced after V7 prefix growth")
        ),
        freeze=freeze,
    )
    assert no_new_event["appended"] == 0

    second_execution = int(second_event["execution_time_ms"])
    addition = shadow.record_publication(
        [first_event, second_event],
        grown_raw,
        path=publication,
        clock=lambda: _at(second_execution - 1),
        freeze=freeze,
    )

    assert addition == {
        "status": "publication_complete",
        "projections": 1,
        "receipts": 1,
        "eligible": 1,
        "ineligible": 0,
        "appended": 2,
    }
    records = shadow.read_journal(publication, "publication", freeze)
    projections = [
        record for record in records if record["kind"] == "event_projection"
    ]
    assert projections[0] == old_projection
    assert projections[0]["v7_prefix_byte_length"] == len(first_raw)
    assert projections[1]["v7_prefix_byte_length"] == len(grown_raw)


def test_two_concurrent_first_publication_writers_serialize_cleanly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    publication = tmp_path / "publication.jsonl"
    freeze = _freeze()
    event = _event_prediction()
    raw = v7.canonical_json_bytes(event) + b"\n"
    execution_ms = int(event["execution_time_ms"])
    snapshot_barrier = threading.Barrier(2)
    original_capture = shadow._capture_snapshot

    def synchronized_capture(
        path: Path, journal_type: str, capture_freeze: shadow.Freeze
    ) -> shadow.JournalSnapshot:
        snapshot = original_capture(path, journal_type, capture_freeze)
        snapshot_barrier.wait(timeout=10)
        return snapshot

    monkeypatch.setattr(shadow, "_capture_snapshot", synchronized_capture)
    results: list[dict[str, object]] = []
    errors: list[Exception] = []

    def run() -> None:
        try:
            results.append(
                shadow.record_publication(
                    [event],
                    raw,
                    path=publication,
                    clock=lambda: _at(execution_ms - 1),
                    freeze=freeze,
                )
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
    assert sorted(int(result["appended"]) for result in results) == [0, 3]
    records = shadow.read_journal(publication, "publication", freeze)
    assert [record["kind"] for record in records] == [
        "header",
        "event_projection",
        "publication_receipt",
    ]


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"", "zero-byte"),
        (b'{"kind":"header"}', "torn|unterminated"),
        (b"not-json\n", "malformed"),
        (b'{"kind": "header"}\n', "canonical"),
    ],
)
def test_v8_parser_fails_closed_on_noncanonical_or_corrupt_jsonl(
    raw: bytes, message: str
) -> None:
    with pytest.raises(shadow.ShadowError, match=message):
        shadow._parse_journal(raw, "accounting", _freeze())


def test_freeze_manifest_mismatch_fails_before_v7_lock_or_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    attempted: list[str] = []
    manifest = tmp_path / "bad-freeze.json"
    manifest.write_bytes(b'{"schema_version":1}\n')

    monkeypatch.setattr(
        shadow,
        "_load_verified_v7",
        lambda *_args, **_kwargs: attempted.append("v7")
        or (_ for _ in ()).throw(AssertionError("freeze failure loaded V7")),
    )
    exchange = FakeExchange()

    with pytest.raises(shadow.ShadowError, match=r"manifest|freeze|schema"):
        shadow.poll_once(
            exchange=exchange,
            manifest_path=manifest,
            expected_manifest_sha256="0" * 64,
            publication_path=tmp_path / "publication.jsonl",
            accounting_path=tmp_path / "accounting.jsonl",
            v7_journal_path=tmp_path / "v7.jsonl",
        )

    assert attempted == []
    assert exchange.calls == []
    assert list(tmp_path.iterdir()) == [manifest]


def test_poll_requires_out_of_band_expected_manifest_hash_before_loading_v7(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    attempted: list[str] = []
    monkeypatch.setattr(
        shadow,
        "_load_verified_v7",
        lambda *_args, **_kwargs: attempted.append("v7"),
    )

    with pytest.raises(shadow.ShadowError, match=r"expected.*manifest|manifest.*SHA"):
        shadow.poll_once(
            exchange=FakeExchange(),
            manifest_path=tmp_path / "freeze.json",
            expected_manifest_sha256=None,
            publication_path=tmp_path / "publication.jsonl",
            accounting_path=tmp_path / "accounting.jsonl",
            v7_journal_path=tmp_path / "v7.jsonl",
        )

    assert attempted == []
    assert list(tmp_path.iterdir()) == []


def test_default_invocation_is_deterministic_plan_without_poll_lock_or_write(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_poll(**_kwargs: object) -> dict[str, object]:
        raise AssertionError("default invocation called poll_once")

    monkeypatch.setattr(shadow, "poll_once", fail_poll)
    monkeypatch.setattr(
        shadow,
        "_load_verified_v7",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("default invocation loaded V7")
        ),
    )

    first = shadow.plan()
    second = shadow.plan()
    assert first == second
    assert first["default_network"] is False
    assert first["default_writes"] is False
    assert first["poll_flag"] == "--poll-once"
    assert shadow.main([]) == 0
    assert json.loads(capsys.readouterr().out) == first


def test_source_contains_no_performance_or_private_exchange_surface() -> None:
    source = Path(shadow.__file__).read_text(encoding="utf-8")

    for forbidden in (
        "fetch_balance(",
        "fetch_positions(",
        "fetch_my_trades(",
        "create_order(",
        "fetch_orders(",
        "fetch_open_orders(",
        "fetch_closed_orders(",
        "fetch_trades(",
    ):
        assert forbidden not in source
    assert "calculate_funding_fees" not in source
    assert "profit_ratio" not in source


def test_snapshot_requires_same_inode_and_exact_retained_byte_prefix(
    tmp_path: Path,
) -> None:
    path = tmp_path / "journal.jsonl"
    freeze = _freeze()
    header = shadow.build_header("publication", freeze)
    path.write_bytes(_jsonl([header]))
    snapshot = shadow._capture_snapshot(path, "publication", freeze)
    original = path.read_bytes()

    with path.open("r+b", buffering=0) as handle:
        path.write_bytes(original[:-1] + b" ")
        assert os.fstat(handle.fileno()).st_ino == snapshot.identity[1]
        with pytest.raises(shadow.ShadowError, match="exact byte prefix"):
            shadow._verify_snapshot(snapshot, handle, path.read_bytes())

    path.write_bytes(original)
    replacement_snapshot = shadow._capture_snapshot(path, "publication", freeze)
    path.unlink()
    path.write_bytes(original)
    with (
        path.open("r+b", buffering=0) as replacement,
        pytest.raises(shadow.ShadowError, match="identity changed"),
    ):
        shadow._verify_snapshot(
            replacement_snapshot,
            replacement,
            path.read_bytes(),
        )


def test_exact_concurrent_prefix_extension_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    freeze = _freeze()
    header = shadow.build_header("publication", freeze)
    path.write_bytes(_jsonl([header]))
    snapshot = shadow._capture_snapshot(path, "publication", freeze)
    extension = shadow.canonical_json_bytes(
        {"concurrent": "canonical extension"}
    ) + b"\n"

    with path.open("r+b", buffering=0) as handle:
        handle.seek(0, os.SEEK_END)
        handle.write(extension)
        shadow._verify_snapshot(snapshot, handle, path.read_bytes())


def test_empty_append_checks_identity_and_short_write_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "journal.jsonl"
    path.write_bytes(b"")
    calls = 0
    original_verify = shadow._verify_path_identity

    def count_identity(check_path: Path, handle: object) -> None:
        nonlocal calls
        calls += 1
        original_verify(check_path, handle)  # type: ignore[arg-type]

    monkeypatch.setattr(shadow, "_verify_path_identity", count_identity)
    with path.open("r+b", buffering=0) as handle:
        shadow._append_records(handle, path, [])
    assert calls == 1

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

    with (
        path.open("r+b", buffering=0) as real_handle,
        pytest.raises(shadow.ShadowError, match="short write"),
    ):
        shadow._append_records(  # type: ignore[arg-type]
            ShortWriter(real_handle),
            path,
            [{"kind": "synthetic"}],
        )


def test_accounting_network_failure_does_not_roll_back_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    publication = tmp_path / "publication.jsonl"
    accounting = tmp_path / "accounting.jsonl"
    event = _event_prediction()
    freeze = _freeze()
    v7_raw = v7.canonical_json_bytes(event) + b"\n"
    execution_ms = int(event["execution_time_ms"])

    monkeypatch.setattr(shadow, "load_freeze_manifest", lambda *_args, **_kwargs: freeze)
    monkeypatch.setattr(shadow, "_load_verified_v7", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        shadow,
        "_run_v7_and_load_events",
        lambda *_args, **_kwargs: ({"status": "poll_complete"}, [event], v7_raw),
    )

    class FailingAccountingExchange(FakeExchange):
        def fetch_ohlcv(
            self,
            symbol: str,
            timeframe: str,
            since: int,
            limit: int,
            params: dict[str, object],
        ) -> list[list[float | int]]:
            raise TimeoutError("synthetic accounting timeout")

    result = shadow.poll_once(
        exchange=FailingAccountingExchange(),
        clock=lambda: _at(execution_ms - 1),
        manifest_path=tmp_path / "unused-freeze.json",
        expected_manifest_sha256="0" * 64,
        publication_path=publication,
        accounting_path=accounting,
        v7_journal_path=tmp_path / "v7.jsonl",
    )

    assert result["publication"]["status"] == "publication_complete"
    assert result["accounting"]["status"] == "network_deferred"
    assert result["status"] == "accounting_deferred"
    assert publication.exists()
    assert [
        record["kind"]
        for record in shadow.read_journal(publication, "publication", freeze)
    ] == ["header", "event_projection", "publication_receipt"]
    assert not accounting.exists()
