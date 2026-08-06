
import gzip
import hashlib
import json
import zipfile

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

import tools.prepare_price_flow_cross_venue as prepare
from tools.prepare_price_flow_cross_venue import (
    CPI_EVENTS_STRICT,
    FOMC_EVENTS,
    METRIC_COLUMNS,
    _aggregate_deribit,
    _engineer_binance_5m,
    _engineer_deribit_15m,
    _expiry_events,
    _load_binance_metrics,
    _local_binance_manifest,
    _local_deribit_manifest,
    _nearest_event_minutes,
    _past_robust_z,
)


def _write_metrics_zip(path, rows):
    frame = pd.DataFrame(rows, columns=METRIC_COLUMNS)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("metrics.csv", frame.to_csv(index=False))


def _option_trade(
    trade_id,
    timestamp,
    instrument,
    direction,
    price,
    mark_price,
    *,
    block_trade_id=None,
    iv=50.0,
):
    return {
        "trade_id": trade_id,
        "trade_seq": int(trade_id),
        "timestamp": timestamp,
        "instrument_name": instrument,
        "direction": direction,
        "price": price,
        "amount": 1.0,
        "mark_price": mark_price,
        "iv": iv,
        "index_price": 50_000.0,
        "block_trade_id": block_trade_id,
    }


def test_binance_taker_period_is_shifted_from_start_to_end(tmp_path):
    path = tmp_path / "BTCUSDT-metrics-2025-01-01.zip"
    _write_metrics_zip(
        path,
        [
            [
                "2025-01-01 00:00:00",
                "BTCUSDT",
                100,
                5_000_000,
                1.1,
                1.2,
                1.3,
                2.0,
            ],
            [
                "2025-01-01 00:05:02",
                "BTCUSDT",
                101,
                5_050_000,
                1.2,
                1.3,
                1.4,
                0.5,
            ],
        ],
    )

    result, conflicts = _load_binance_metrics([path])

    assert conflicts == []
    assert result.loc[pd.Timestamp("2025-01-01 00:00:00Z"), "bin_oi"] == 100
    assert np.isnan(
        result.loc[pd.Timestamp("2025-01-01 00:00:00Z"), "bin_taker_ratio"]
    )
    assert result.loc[pd.Timestamp("2025-01-01 00:05:00Z"), "bin_taker_ratio"] == 2.0
    assert result.loc[pd.Timestamp("2025-01-01 00:10:00Z"), "bin_taker_ratio"] == 0.5


def test_conflicting_binance_archive_rows_are_quarantined(tmp_path):
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    common = ["2025-01-01 00:00:00", "BTCUSDT"]
    _write_metrics_zip(first, [[*common, 100, 5_000_000, 1.1, 1.2, 1.3, 1.0]])
    _write_metrics_zip(second, [[*common, 101, 5_050_000, 1.1, 1.2, 1.3, 1.0]])

    result, conflicts = _load_binance_metrics([first, second])

    assert conflicts == ["2025-01-01T00:00:00+00:00"]
    assert pd.Timestamp("2025-01-01 00:00:00Z") not in result.index


def test_nonpositive_binance_oi_is_invalid_and_never_infinite():
    index = pd.date_range("2025-01-01", periods=6, freq="5min", tz="UTC")
    frame = pd.DataFrame(
        {
            "bin_oi": [100.0, 101.0, 0.0, 103.0, 104.0, 105.0],
            "bin_top_position_ratio": 1.1,
            "bin_top_account_ratio": 1.2,
            "bin_global_account_ratio": 1.3,
            "bin_taker_ratio": 1.0,
            "bin_open": 50_000.0,
            "bin_high": 50_100.0,
            "bin_low": 49_900.0,
            "bin_close": 50_000.0,
            "bin_volume": 100.0,
            "bin_metrics_valid": True,
            "bin_price_valid": True,
        },
        index=index,
    )

    result = _engineer_binance_5m(frame)

    assert not result.loc[index[2], "bin_metrics_valid"]
    assert not np.isinf(
        result[["bin_oi_change_5m", "bin_oi_change_15m", "bin_oi_change_15m_z"]]
        .to_numpy(dtype=float)
    ).any()


def test_deribit_urgency_is_directional_and_block_is_separate(tmp_path):
    path = tmp_path / "BTC.jsonl.gz"
    timestamp = int(pd.Timestamp("2025-01-01 00:01:00Z").timestamp() * 1000)
    rows = [
        _option_trade("1", timestamp, "BTC-3JAN25-55000-C", "buy", 0.11, 0.10),
        _option_trade("2", timestamp + 1, "BTC-3JAN25-45000-P", "buy", 0.11, 0.10),
        _option_trade(
            "3",
            timestamp + 2,
            "BTC-3JAN25-55000-C",
            "buy",
            0.20,
            0.10,
            block_trade_id="block-1",
        ),
    ]
    path.write_bytes(
        gzip.compress(
            b"".join(json.dumps(row).encode() + b"\n" for row in rows), mtime=0
        )
    )

    aggregated, audit = _aggregate_deribit(
        [path], pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")
    )
    result = _engineer_deribit_15m(aggregated)
    row = result.loc[pd.Timestamp("2025-01-01 00:15:00Z")]

    assert audit["trade_ids"] == 3
    assert row["opt_core_count_1h"] == 2
    assert row["opt_block_count_1h"] == 1
    assert row["opt_core_urgency_1h"] == 0
    assert row["opt_block_urgency_1h"] > 0


def test_deribit_day_cache_preserves_cross_day_iv_state(tmp_path, monkeypatch):
    raw_root = tmp_path / "raw" / "deribit" / "BTC"
    raw_root.mkdir(parents=True)
    first_path = raw_root / "2025-01-01.jsonl.gz"
    second_path = raw_root / "2025-01-02.jsonl.gz"
    instrument = "BTC-3JAN25-55000-C"
    first_timestamp = int(pd.Timestamp("2025-01-01 00:01:00Z").timestamp() * 1000)
    second_timestamp = int(pd.Timestamp("2025-01-02 00:01:00Z").timestamp() * 1000)
    first_path.write_bytes(
        gzip.compress(
            json.dumps(
                _option_trade(
                    "1", first_timestamp, instrument, "buy", 0.11, 0.10, iv=50.0
                )
            ).encode()
            + b"\n",
            mtime=0,
        )
    )
    second_path.write_bytes(
        gzip.compress(
            json.dumps(
                _option_trade(
                    "2", second_timestamp, instrument, "buy", 0.11, 0.10, iv=55.0
                )
            ).encode()
            + b"\n",
            mtime=0,
        )
    )
    cache_root = tmp_path / "cache"
    start = pd.Timestamp("2025-01-01", tz="UTC")
    end = pd.Timestamp("2025-01-02", tz="UTC")

    first, first_audit = _aggregate_deribit(
        [first_path, second_path], start, end, cache_root=cache_root
    )

    assert first.loc[pd.Timestamp("2025-01-02 00:15:00Z"), "iv_count"] == 1
    assert first.loc[pd.Timestamp("2025-01-02 00:15:00Z"), "iv_abs_change"] == 5
    assert len(list(cache_root.glob("*.feather"))) == 2

    def fail_read(_path):
        raise AssertionError("valid daily cache was not reused")

    monkeypatch.setattr(
        "tools.prepare_price_flow_cross_venue._read_deribit_file", fail_read
    )
    second, second_audit = _aggregate_deribit(
        [first_path, second_path], start, end, cache_root=cache_root
    )

    assert_frame_equal(first, second)
    assert first_audit == second_audit


def test_deribit_cross_day_trade_ids_must_be_strictly_separated(tmp_path):
    first_path = tmp_path / "2025-01-01.jsonl.gz"
    second_path = tmp_path / "2025-01-02.jsonl.gz"
    instrument = "BTC-3JAN25-55000-C"
    rows = [
        (
            first_path,
            _option_trade(
                "2",
                int(pd.Timestamp("2025-01-01 00:01:00Z").timestamp() * 1000),
                instrument,
                "buy",
                0.11,
                0.10,
            ),
        ),
        (
            second_path,
            _option_trade(
                "1",
                int(pd.Timestamp("2025-01-02 00:01:00Z").timestamp() * 1000),
                instrument,
                "buy",
                0.11,
                0.10,
            ),
        ),
    ]
    for path, row in rows:
        path.write_bytes(gzip.compress(json.dumps(row).encode() + b"\n", mtime=0))

    with pytest.raises(ValueError, match="global uniqueness cannot be proven"):
        _aggregate_deribit(
            [first_path, second_path],
            pd.Timestamp("2025-01-01", tz="UTC"),
            pd.Timestamp("2025-01-02", tz="UTC"),
        )


def test_past_robust_score_is_prefix_invariant():
    values = pd.Series(np.sin(np.arange(1200) / 17) + np.arange(1200) / 10_000)
    prefix = _past_robust_z(values.iloc[:1100], window=200, minimum=100, scale_floor=1e-6)
    full = _past_robust_z(values, window=200, minimum=100, scale_floor=1e-6).iloc[:1100]

    assert_series_equal(prefix, full)


def test_event_distance_keeps_direction_and_utc_minutes():
    decisions = pd.Series(
        pd.to_datetime(["2025-01-01 11:30Z", "2025-01-01 12:15Z"], utc=True)
    )

    result = _nearest_event_minutes(decisions, [pd.Timestamp("2025-01-01 12:00Z")])

    assert result.tolist() == [-30.0, 15.0]


def test_cpi_calendar_covers_official_releases_through_evaluation_end():
    assert len(CPI_EVENTS_STRICT) == 61
    assert CPI_EVENTS_STRICT[0] == "2021-06-10T12:30:00Z"
    assert CPI_EVENTS_STRICT[-1] == "2026-07-14T12:30:00Z"
    assert "2025-10-24T12:30:00Z" in CPI_EVENTS_STRICT
    assert "2025-12-18T13:30:00Z" in CPI_EVENTS_STRICT
    assert "2025-10-15T12:30:00Z" not in CPI_EVENTS_STRICT
    assert "2025-11-01T12:30:00Z" not in CPI_EVENTS_STRICT


def test_executable_event_counts_are_frozen_for_d1_and_d2():
    windows = [
        (pd.Timestamp("2024-08-03 16:00Z"), pd.Timestamp("2025-08-03 16:00Z")),
        (pd.Timestamp("2024-08-03 16:00Z"), pd.Timestamp("2026-02-04 16:00Z")),
    ]

    counts = []
    for start, end in windows:
        counts.append(
            (
                sum(start <= pd.Timestamp(event) < end for event in FOMC_EVENTS),
                sum(
                    start <= pd.Timestamp(event) < end
                    for event in CPI_EVENTS_STRICT
                ),
                sum(start <= event < end for event in _expiry_events(start, end)),
            )
        )

    assert counts == [(8, 12, 12), (12, 17, 18)]


def test_binance_jobs_respect_eth_metrics_archive_start(tmp_path):
    start = pd.Timestamp("2021-11-30", tz="UTC")
    end = pd.Timestamp("2021-12-01", tz="UTC")

    jobs = prepare._binance_jobs(tmp_path, start, end)
    metric_names = sorted(
        target.name for _url, target in jobs if target.parent.parent.name == "metrics"
    )

    assert metric_names == [
        "BTCUSDT-metrics-2021-11-30.zip",
        "BTCUSDT-metrics-2021-12-01.zip",
        "ETHUSDT-metrics-2021-12-01.zip",
    ]


def test_binance_download_retries_transient_connection_error(tmp_path, monkeypatch):
    content = b"verified archive"
    checksum = hashlib.sha256(content).hexdigest()
    calls = []

    class Response:
        def __init__(self, body):
            self.content = body
            self.text = body.decode()

        def raise_for_status(self):
            return None

    class Session:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout):
            calls.append((url, timeout))
            if len(calls) == 1:
                raise prepare.requests.ConnectionError("temporary disconnect")
            if url.endswith(".CHECKSUM"):
                return Response(f"{checksum}  archive.zip\n".encode())
            return Response(content)

    monkeypatch.setattr(prepare.requests, "Session", Session)
    monkeypatch.setattr(prepare.time, "sleep", lambda _seconds: None)
    target = tmp_path / "archive.zip"

    result = prepare._download_checked("https://example.test/archive.zip", target)

    assert result["sha256"] == checksum
    assert not result["reused"]
    assert target.read_bytes() == content
    assert len(calls) == 3


def test_skip_download_manifests_revalidate_cached_source_files(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(prepare, "REPO_ROOT", tmp_path)
    raw_root = tmp_path / "raw"
    start = pd.Timestamp("2025-01-01", tz="UTC")
    end = start

    for _url, target in prepare._binance_jobs(raw_root, start, end):
        target.parent.mkdir(parents=True, exist_ok=True)
        content = target.name.encode()
        target.write_bytes(content)
        target.with_name(f"{target.name}.CHECKSUM").write_text(
            f"{hashlib.sha256(content).hexdigest()}  {target.name}\n",
            encoding="utf-8",
        )

    binance = _local_binance_manifest(raw_root, start, end)

    assert len(binance) == 6
    assert [item["path"] for item in binance] == sorted(
        item["path"] for item in binance
    )

    for asset in prepare.ASSETS:
        target = raw_root / "deribit" / asset / "2025-01-01.jsonl.gz"
        target.parent.mkdir(parents=True, exist_ok=True)
        content = f"{asset}-trades".encode()
        target.write_bytes(content)
        target.with_suffix(".meta.json").write_text(
            json.dumps(
                {
                    "asset": asset,
                    "date": "2025-01-01",
                    "complete": True,
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            ),
            encoding="utf-8",
        )

    deribit = _local_deribit_manifest(raw_root, start, end)

    assert [(item["asset"], item["date"]) for item in deribit] == [
        ("BTC", "2025-01-01"),
        ("ETH", "2025-01-01"),
    ]

    first_binance = tmp_path / binance[0]["path"]
    first_binance.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        _local_binance_manifest(raw_root, start, end)
