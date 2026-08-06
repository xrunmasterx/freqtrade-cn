from __future__ import annotations

import argparse
import gzip
import hashlib
import http.client
import json
import re
import socket
import ssl
import time
import zipfile
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = (
    REPO_ROOT / "ft_userdata" / "runtime" / "freqtrade-futures" / "data-price-flow-funded"
)
BINANCE_DATA = "https://data.binance.vision/data/futures/um"
DERIBIT_HOST = "history.deribit.com"
DERIBIT_PATH = "/api/v2/public/get_last_trades_by_currency_and_time"
DERIBIT_AGGREGATE_CACHE_VERSION = "2026-08-05-v1"
ASSETS = ("BTC", "ETH")
BINANCE_METRICS_ARCHIVE_START = {
    "BTC": date(2021, 1, 1),
    "ETH": date(2021, 12, 1),
}
METRIC_COLUMNS = [
    "create_time",
    "symbol",
    "sum_open_interest",
    "sum_open_interest_value",
    "count_toptrader_long_short_ratio",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
]
KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trade_count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
]
OPTION_PATTERN = re.compile(
    r"^(?P<asset>BTC|ETH)-(?P<expiry>\d{1,2}[A-Z]{3}\d{2})-"
    r"(?P<strike>\d+(?:\.\d+)?)-(?P<option_type>[CP])$"
)
MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare causal Binance/Deribit sidecars for PriceFlow research."
    )
    parser.add_argument("--start", default="2024-05-01")
    parser.add_argument("--end", default="2026-02-04")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--proxy-host", default="127.0.0.1")
    parser.add_argument("--proxy-port", type=int, default=12639)
    parser.add_argument("--deribit-ip", default="104.18.4.240")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--skip-download", action="store_true")
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.part")
    temporary.write_bytes(content)
    temporary.replace(path)


def _atomic_feather(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.part")
    frame.to_feather(temporary)
    temporary.replace(path)


def _date_range(start: pd.Timestamp, end: pd.Timestamp) -> list[date]:
    return [item.date() for item in pd.date_range(start.floor("D"), end.floor("D"), freq="D")]


def _month_range(start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    return [str(item) for item in pd.period_range(start=start, end=end, freq="M")]


def _utc_ns(values: Any) -> Any:
    return pd.to_datetime(values, utc=True).astype("datetime64[ns, UTC]")


def _download_checked(url: str, target: Path) -> dict[str, Any]:
    checksum_target = target.with_name(f"{target.name}.CHECKSUM")
    if target.is_file() and checksum_target.is_file():
        expected = checksum_target.read_text(encoding="utf-8").split()[0].lower()
        actual = _sha256(target)
        if actual == expected:
            return {"path": target, "sha256": actual, "reused": True}

    for attempt in range(5):
        try:
            session = requests.Session()
            session.headers["User-Agent"] = "freqtrade-cn-cross-venue-research/1"
            checksum_response = session.get(f"{url}.CHECKSUM", timeout=30)
            checksum_response.raise_for_status()
            expected = checksum_response.text.split()[0].lower()
            response = session.get(url, timeout=60)
            response.raise_for_status()
            actual = hashlib.sha256(response.content).hexdigest()
            if actual != expected:
                raise ValueError(
                    f"Checksum mismatch for {url}: {actual} != {expected}"
                )
            _atomic_write(target, response.content)
            _atomic_write(checksum_target, checksum_response.content)
            return {"path": target, "sha256": actual, "reused": False}
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 4:
                raise
            time.sleep(0.5 * (attempt + 1))

    raise AssertionError("unreachable")


def _binance_jobs(
    raw_root: Path, start: pd.Timestamp, end: pd.Timestamp
) -> list[tuple[str, Path]]:
    jobs: list[tuple[str, Path]] = []
    for asset in ASSETS:
        symbol = f"{asset}USDT"
        for day in _date_range(start, end):
            if day < BINANCE_METRICS_ARCHIVE_START[asset]:
                continue
            stamp = day.isoformat()
            name = f"{symbol}-metrics-{stamp}.zip"
            jobs.append(
                (
                    f"{BINANCE_DATA}/daily/metrics/{symbol}/{name}",
                    raw_root / "metrics" / asset / name,
                )
            )
        for month in _month_range(start, end):
            kline_name = f"{symbol}-5m-{month}.zip"
            jobs.append(
                (
                    f"{BINANCE_DATA}/monthly/klines/{symbol}/5m/{kline_name}",
                    raw_root / "klines" / asset / kline_name,
                )
            )
            funding_name = f"{symbol}-fundingRate-{month}.zip"
            jobs.append(
                (
                    f"{BINANCE_DATA}/monthly/fundingRate/{symbol}/{funding_name}",
                    raw_root / "funding" / asset / funding_name,
                )
            )
    return jobs


def _download_binance(
    raw_root: Path, start: pd.Timestamp, end: pd.Timestamp, workers: int
) -> list[dict[str, Any]]:
    jobs = _binance_jobs(raw_root, start, end)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers * 2)) as executor:
        futures = {
            executor.submit(_download_checked, url, target): (url, target)
            for url, target in jobs
        }
        for future in as_completed(futures):
            url, target = futures[future]
            result = future.result()
            results.append(
                {
                    "url": url,
                    "path": str(target.relative_to(REPO_ROOT)),
                    "bytes": target.stat().st_size,
                    "sha256": result["sha256"],
                }
            )
    return sorted(results, key=lambda item: item["path"])


def _local_binance_manifest(
    raw_root: Path, start: pd.Timestamp, end: pd.Timestamp
) -> list[dict[str, Any]]:
    results = []
    for url, target in _binance_jobs(raw_root, start, end):
        checksum_target = target.with_name(f"{target.name}.CHECKSUM")
        if not target.is_file() or not checksum_target.is_file():
            raise FileNotFoundError(f"Missing cached Binance archive or checksum: {target}")
        expected = checksum_target.read_text(encoding="utf-8").split()[0].lower()
        actual = _sha256(target)
        if actual != expected:
            raise ValueError(f"Checksum mismatch for cached Binance archive: {target}")
        results.append(
            {
                "url": url,
                "path": str(target.relative_to(REPO_ROOT)),
                "bytes": target.stat().st_size,
                "sha256": actual,
            }
        )
    return sorted(results, key=lambda item: item["path"])


class _PinnedHTTPSConnection(http.client.HTTPConnection):
    def __init__(
        self,
        host: str,
        connect_ip: str,
        proxy_host: str,
        proxy_port: int,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(host, 443, timeout=timeout)
        self.connect_ip = connect_ip
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port

    def connect(self) -> None:
        raw = socket.create_connection(
            (self.proxy_host, self.proxy_port), timeout=self.timeout
        )
        connect_request = (
            f"CONNECT {self.connect_ip}:443 HTTP/1.1\r\n"
            f"Host: {self.host}:443\r\nProxy-Connection: Keep-Alive\r\n\r\n"
        )
        raw.sendall(connect_request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response and len(response) < 65536:
            chunk = raw.recv(4096)
            if not chunk:
                break
            response += chunk
        status_line = response.split(b"\r\n", maxsplit=1)[0]
        if b" 200 " not in status_line:
            raw.close()
            raise ConnectionError(f"Proxy CONNECT failed: {status_line!r}")
        context = ssl.create_default_context()
        self.sock = context.wrap_socket(raw, server_hostname=self.host)


def _deribit_json(
    params: dict[str, str], *, connect_ip: str, proxy_host: str, proxy_port: int
) -> dict[str, Any]:
    path = f"{DERIBIT_PATH}?{urlencode(params)}"
    last_error: Exception | None = None
    for attempt in range(5):
        connection = _PinnedHTTPSConnection(
            DERIBIT_HOST, connect_ip, proxy_host, proxy_port
        )
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "Host": DERIBIT_HOST,
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "User-Agent": "freqtrade-cn-cross-venue-research/1",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            payload = response.read()
            if response.status != 200:
                raise RuntimeError(
                    f"Deribit HTTP {response.status}: {payload[:300]!r}"
                )
            if response.getheader("Content-Encoding") == "gzip":
                payload = gzip.decompress(payload)
            decoded = json.loads(payload)
            if "error" in decoded:
                raise RuntimeError(f"Deribit API error: {decoded['error']}")
            return decoded
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
            last_error = error
            time.sleep(0.5 * (attempt + 1))
        finally:
            connection.close()
    raise RuntimeError(f"Deribit request failed after retries: {last_error}")


def _download_deribit_day(
    asset: str,
    day: date,
    raw_root: Path,
    *,
    connect_ip: str,
    proxy_host: str,
    proxy_port: int,
) -> dict[str, Any]:
    target = raw_root / "deribit" / asset / f"{day.isoformat()}.jsonl.gz"
    metadata_target = target.with_suffix(".meta.json")
    if target.is_file() and metadata_target.is_file():
        metadata = json.loads(metadata_target.read_text(encoding="utf-8"))
        if metadata.get("complete") and metadata.get("sha256") == _sha256(target):
            return metadata

    start = pd.Timestamp(day, tz="UTC")
    end = start + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
    cursor = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    trades: dict[str, dict[str, Any]] = {}
    page_count = 0
    while cursor <= end_ms:
        payload = _deribit_json(
            {
                "currency": asset,
                "kind": "option",
                "start_timestamp": str(cursor),
                "end_timestamp": str(end_ms),
                "sorting": "asc",
                "count": "10000",
                "include_old": "true",
            },
            connect_ip=connect_ip,
            proxy_host=proxy_host,
            proxy_port=proxy_port,
        )
        result = payload["result"]
        rows = result.get("trades", [])
        page_count += 1
        if not rows:
            break
        before = len(trades)
        for row in rows:
            trades[str(row["trade_id"])] = row
        last_timestamp = max(int(row["timestamp"]) for row in rows)
        if not result.get("has_more"):
            break
        if last_timestamp < cursor or (last_timestamp == cursor and len(trades) == before):
            raise RuntimeError(f"Deribit pagination made no progress for {asset} {day}")
        cursor = last_timestamp

    ordered = sorted(
        trades.values(), key=lambda row: (int(row["timestamp"]), str(row["trade_id"]))
    )
    content = b"".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        for row in ordered
    )
    compressed = gzip.compress(content, compresslevel=6, mtime=0)
    _atomic_write(target, compressed)
    metadata = {
        "asset": asset,
        "date": day.isoformat(),
        "complete": True,
        "trade_count": len(ordered),
        "page_count": page_count,
        "first_timestamp": int(ordered[0]["timestamp"]) if ordered else None,
        "last_timestamp": int(ordered[-1]["timestamp"]) if ordered else None,
        "bytes": len(compressed),
        "sha256": hashlib.sha256(compressed).hexdigest(),
        "host": DERIBIT_HOST,
        "connect_ip": connect_ip,
    }
    _atomic_write(
        metadata_target,
        json.dumps(metadata, indent=2, sort_keys=True).encode("utf-8"),
    )
    return metadata


def _download_deribit(
    raw_root: Path,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    connect_ip: str,
    proxy_host: str,
    proxy_port: int,
    workers: int,
) -> list[dict[str, Any]]:
    jobs = [(asset, day) for asset in ASSETS for day in _date_range(start, end)]
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(
                _download_deribit_day,
                asset,
                day,
                raw_root,
                connect_ip=connect_ip,
                proxy_host=proxy_host,
                proxy_port=proxy_port,
            ): (asset, day)
            for asset, day in jobs
        }
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda item: (item["asset"], item["date"]))


def _local_deribit_manifest(
    raw_root: Path, start: pd.Timestamp, end: pd.Timestamp
) -> list[dict[str, Any]]:
    results = []
    for asset in ASSETS:
        for day in _date_range(start, end):
            target = raw_root / "deribit" / asset / f"{day.isoformat()}.jsonl.gz"
            metadata_target = target.with_suffix(".meta.json")
            if not target.is_file() or not metadata_target.is_file():
                raise FileNotFoundError(
                    f"Missing cached Deribit day or metadata: {target}"
                )
            metadata = json.loads(metadata_target.read_text(encoding="utf-8"))
            if (
                not metadata.get("complete")
                or metadata.get("asset") != asset
                or metadata.get("date") != day.isoformat()
                or metadata.get("sha256") != _sha256(target)
            ):
                raise ValueError(f"Invalid cached Deribit metadata: {metadata_target}")
            results.append(metadata)
    return sorted(results, key=lambda item: (item["asset"], item["date"]))


def _read_zip_csv(path: Path, **kwargs: Any) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"Expected one CSV in {path}, found {len(members)}")
        with archive.open(members[0]) as handle:
            return pd.read_csv(handle, **kwargs)


def _past_robust_z(
    series: pd.Series, *, window: int, minimum: int, scale_floor: float
) -> pd.Series:
    history = series.shift(1)
    median = history.rolling(window, min_periods=minimum).median()
    residual = (series - median).abs()
    mad = 1.4826 * residual.shift(1).rolling(window, min_periods=minimum).median()
    return (series - median) / mad.clip(lower=scale_floor)


def _cusum_cross(zscore: pd.Series, k: float = 0.5, threshold: float = 5.0) -> pd.Series:
    direction = np.zeros(len(zscore), dtype=np.int8)
    positive = 0.0
    negative = 0.0
    for position, value in enumerate(zscore.to_numpy(dtype=float, na_value=np.nan)):
        if not np.isfinite(value):
            positive = 0.0
            negative = 0.0
            continue
        positive = max(0.0, positive + value - k)
        negative = min(0.0, negative + value + k)
        if positive > threshold:
            direction[position] = 1
            positive = 0.0
            negative = 0.0
        elif negative < -threshold:
            direction[position] = -1
            positive = 0.0
            negative = 0.0
    return pd.Series(direction, index=zscore.index)


def _drop_conflicting_duplicates(
    frame: pd.DataFrame, key: str, value_columns: list[str]
) -> tuple[pd.DataFrame, list[str]]:
    duplicate = frame.duplicated(key, keep=False)
    conflicts: list[str] = []
    if duplicate.any():
        for timestamp, group in frame.loc[duplicate].groupby(key, sort=True):
            unique_rows = group[value_columns].drop_duplicates()
            if len(unique_rows) > 1:
                conflicts.append(pd.Timestamp(timestamp).isoformat())
        if conflicts:
            conflict_times = pd.to_datetime(conflicts, utc=True)
            frame = frame.loc[~frame[key].isin(conflict_times)].copy()
    return frame.drop_duplicates(key, keep="first"), conflicts


def _load_binance_metrics(paths: list[Path]) -> tuple[pd.DataFrame, list[str]]:
    chunks = []
    for path in paths:
        frame = _read_zip_csv(path)
        if list(frame.columns) != METRIC_COLUMNS:
            raise ValueError(f"Unexpected metrics columns in {path}: {list(frame.columns)}")
        chunks.append(frame)
    combined = pd.concat(chunks, ignore_index=True)
    raw_time = _utc_ns(
        pd.to_datetime(combined.pop("create_time"), utc=True, errors="coerce")
    )
    grid_time = raw_time.dt.round("5min")
    grid_error = (raw_time - grid_time).dt.total_seconds().abs()
    combined["raw_create_time"] = raw_time
    combined["period_end"] = grid_time
    combined["grid_error_seconds"] = grid_error
    combined = combined.loc[raw_time.notna() & grid_error.le(30)].copy()
    numeric = [column for column in METRIC_COLUMNS if column not in {"create_time", "symbol"}]
    for column in numeric:
        combined[column] = pd.to_numeric(combined[column], errors="coerce")
    combined, conflicts = _drop_conflicting_duplicates(combined, "period_end", numeric)

    other_columns = [
        "sum_open_interest",
        "sum_open_interest_value",
        "count_toptrader_long_short_ratio",
        "sum_toptrader_long_short_ratio",
        "count_long_short_ratio",
    ]
    other = combined[["period_end", *other_columns]].set_index("period_end")
    taker = combined[["period_end", "sum_taker_long_short_vol_ratio"]].copy()
    taker["period_end"] += pd.Timedelta(minutes=5)
    taker = taker.set_index("period_end")
    result = other.join(taker, how="outer").sort_index()
    result = result.rename(
        columns={
            "sum_open_interest": "bin_oi",
            "sum_open_interest_value": "bin_oi_value",
            "count_toptrader_long_short_ratio": "bin_top_account_ratio",
            "sum_toptrader_long_short_ratio": "bin_top_position_ratio",
            "count_long_short_ratio": "bin_global_account_ratio",
            "sum_taker_long_short_vol_ratio": "bin_taker_ratio",
        }
    )
    required = list(result.columns)
    result["bin_metrics_valid"] = result[required].notna().all(axis=1)
    return result, conflicts


def _load_binance_klines(paths: list[Path]) -> tuple[pd.DataFrame, list[str]]:
    chunks = []
    for path in paths:
        frame = _read_zip_csv(path, header=None, names=KLINE_COLUMNS)
        frame["open_time"] = pd.to_numeric(frame["open_time"], errors="coerce")
        chunks.append(frame.loc[frame["open_time"].notna()])
    combined = pd.concat(chunks, ignore_index=True)
    for column in KLINE_COLUMNS:
        combined[column] = pd.to_numeric(combined[column], errors="coerce")
    combined["period_end"] = _utc_ns(
        pd.to_datetime(combined["open_time"], unit="ms", utc=True)
        + pd.Timedelta(minutes=5)
    )
    value_columns = ["open", "high", "low", "close", "volume", "quote_volume"]
    combined, conflicts = _drop_conflicting_duplicates(
        combined, "period_end", value_columns
    )
    result = combined.set_index("period_end")[value_columns].sort_index()
    result = result.rename(columns={column: f"bin_{column}" for column in value_columns})
    result["bin_price_valid"] = result.notna().all(axis=1)
    return result, conflicts


def _load_binance_funding(paths: list[Path]) -> pd.DataFrame:
    chunks = []
    for path in paths:
        frame = _read_zip_csv(path)
        expected = {"calc_time", "last_funding_rate"}
        if not expected.issubset(frame.columns):
            raise ValueError(f"Unexpected funding columns in {path}: {list(frame.columns)}")
        frame["date"] = _utc_ns(
            pd.to_datetime(
                pd.to_numeric(frame["calc_time"], errors="coerce"),
                unit="ms",
                utc=True,
            )
        )
        frame["bin_funding_rate"] = pd.to_numeric(
            frame["last_funding_rate"], errors="coerce"
        )
        chunks.append(frame[["date", "bin_funding_rate"]])
    return (
        pd.concat(chunks, ignore_index=True)
        .dropna()
        .drop_duplicates("date", keep="first")
        .sort_values("date")
        .reset_index(drop=True)
    )


def _positive_log_change(series: pd.Series, periods: int) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    positive = numeric.where(numeric > 0)
    return np.log(positive / positive.shift(periods))


def _engineer_binance_5m(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.sort_index().copy()
    frame["bin_metrics_valid"] &= (
        frame[
            [
                "bin_oi",
                "bin_top_position_ratio",
                "bin_top_account_ratio",
                "bin_global_account_ratio",
            ]
        ]
        .gt(0)
        .all(axis=1)
        & frame["bin_taker_ratio"].ge(0)
    )
    frame["bin_price_valid"] &= frame[
        ["bin_open", "bin_high", "bin_low", "bin_close"]
    ].gt(0).all(axis=1)
    frame["bin_taker_imbalance"] = (
        (frame["bin_taker_ratio"] - 1) / (frame["bin_taker_ratio"] + 1)
    ).clip(-1, 1)
    frame["bin_oi_change_5m"] = _positive_log_change(frame["bin_oi"], 1)
    frame["bin_oi_change_15m"] = _positive_log_change(frame["bin_oi"], 3)
    frame["bin_top_position_change_5m"] = _positive_log_change(
        frame["bin_top_position_ratio"], 1
    )
    frame["bin_top_account_change_5m"] = _positive_log_change(
        frame["bin_top_account_ratio"], 1
    )
    frame["bin_top_position_change_2h"] = _positive_log_change(
        frame["bin_top_position_ratio"], 24
    )
    frame["bin_top_account_change_2h"] = _positive_log_change(
        frame["bin_top_account_ratio"], 24
    )
    frame["bin_global_account_log"] = np.log(
        frame["bin_global_account_ratio"].where(frame["bin_global_account_ratio"] > 0)
    )

    prior_close = frame["bin_close"].shift(1)
    true_range = pd.concat(
        [
            frame["bin_high"] - frame["bin_low"],
            (frame["bin_high"] - prior_close).abs(),
            (frame["bin_low"] - prior_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.ewm(alpha=1 / 14, adjust=False).mean()
    candle_range = (frame["bin_high"] - frame["bin_low"]).replace(0, np.nan)
    close_location = (
        (2 * frame["bin_close"] - frame["bin_high"] - frame["bin_low"])
        / candle_range
    ).clip(-1, 1)
    body_atr = (frame["bin_close"] - frame["bin_open"]).abs() / atr
    relative_volume = frame["bin_volume"] / frame["bin_volume"].rolling(288).median()
    prior_high = frame["bin_high"].rolling(72).max().shift(1)
    prior_low = frame["bin_low"].rolling(72).min().shift(1)
    frame["bin_breakout_long_5m"] = (
        (frame["bin_close"] > prior_high)
        & (body_atr >= 0.7)
        & (relative_volume >= 1.5)
        & (close_location >= 0.6)
    )
    frame["bin_breakout_short_5m"] = (
        (frame["bin_close"] < prior_low)
        & (body_atr >= 0.7)
        & (relative_volume >= 1.5)
        & (close_location <= -0.6)
    )
    frame["bin_price_return_15m"] = _positive_log_change(frame["bin_close"], 3)
    frame["bin_oi_change_15m_z"] = _past_robust_z(
        frame["bin_oi_change_15m"], window=8640, minimum=1000, scale_floor=1e-5
    )
    frame["bin_global_account_log_z"] = _past_robust_z(
        frame["bin_global_account_log"], window=8640, minimum=1000, scale_floor=1e-4
    )
    frame["bin_taker_imbalance_z"] = _past_robust_z(
        frame["bin_taker_imbalance"], window=8640, minimum=1000, scale_floor=0.01
    )
    frame["bin_taker_cusum_cross"] = _cusum_cross(frame["bin_taker_imbalance_z"])
    frame["bin_three_5m_valid"] = (
        frame["bin_metrics_valid"].rolling(4, min_periods=4).sum().eq(4)
        & frame["bin_price_valid"].rolling(4, min_periods=4).sum().eq(4)
    )
    return frame


def _sample_binance_15m(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["bin_taker_lag1"] = frame["bin_taker_imbalance"].shift(1)
    frame["bin_taker_lag2"] = frame["bin_taker_imbalance"].shift(2)
    frame["bin_oi_delta_lag1"] = frame["bin_oi_change_5m"].shift(1)
    frame["bin_oi_delta_lag2"] = frame["bin_oi_change_5m"].shift(2)
    frame["bin_top_position_delta_lag1"] = frame[
        "bin_top_position_change_5m"
    ].shift(1)
    frame["bin_breakout_long_recent"] = (
        frame["bin_breakout_long_5m"].shift(1).rolling(24).max().fillna(0) > 0
    )
    frame["bin_breakout_short_recent"] = (
        frame["bin_breakout_short_5m"].shift(1).rolling(24).max().fillna(0) > 0
    )
    frame["bin_breakout_long_current_15m"] = (
        frame["bin_breakout_long_5m"].rolling(3).max().fillna(0) > 0
    )
    frame["bin_breakout_short_current_15m"] = (
        frame["bin_breakout_short_5m"].rolling(3).max().fillna(0) > 0
    )
    frame["bin_cusum_long_current_15m"] = (
        frame["bin_taker_cusum_cross"].eq(1).rolling(3).max().fillna(0) > 0
    )
    frame["bin_cusum_short_current_15m"] = (
        frame["bin_taker_cusum_cross"].eq(-1).rolling(3).max().fillna(0) > 0
    )
    required_finite = [
        "bin_taker_imbalance",
        "bin_taker_lag1",
        "bin_taker_lag2",
        "bin_oi_change_5m",
        "bin_oi_change_15m",
        "bin_oi_delta_lag1",
        "bin_oi_delta_lag2",
        "bin_top_position_ratio",
        "bin_top_account_ratio",
        "bin_top_position_change_2h",
        "bin_top_account_change_2h",
        "bin_top_position_delta_lag1",
        "bin_global_account_log_z",
        "bin_price_return_15m",
        "bin_oi_change_15m_z",
        "bin_taker_imbalance_z",
    ]
    frame["bin_three_5m_valid"] &= np.isfinite(frame[required_finite]).all(axis=1)
    return frame.loc[frame.index.minute.isin([0, 15, 30, 45])].copy()


def _parse_expiry(value: str) -> pd.Timestamp:
    match = re.fullmatch(r"(\d{1,2})([A-Z]{3})(\d{2})", value)
    if not match or match.group(2) not in MONTHS:
        return pd.NaT
    return pd.Timestamp(
        year=2000 + int(match.group(3)),
        month=MONTHS[match.group(2)],
        day=int(match.group(1)),
        hour=8,
        tz="UTC",
    )


def _read_deribit_file(path: Path) -> pd.DataFrame:
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return pd.DataFrame(rows)


def _conditional_sum(
    frame: pd.DataFrame, mask: pd.Series, column: str
) -> pd.Series:
    return frame[column].where(mask, 0.0)


def _deribit_trade_id_range(frame: pd.DataFrame, path: Path) -> tuple[int, int]:
    assets = (
        frame["instrument_name"]
        .astype(str)
        .str.extract(r"^(BTC|ETH)-", expand=False)
        .dropna()
        .unique()
    )
    if len(assets) != 1:
        raise ValueError(f"Cannot prove one Deribit asset in {path}: {assets.tolist()}")
    asset = str(assets[0])
    ids = frame["trade_id"].astype(str)
    pattern = r"\d+" if asset == "BTC" else rf"{asset}-\d+"
    if not ids.str.fullmatch(pattern).all():
        invalid = ids.loc[~ids.str.fullmatch(pattern)].head(3).tolist()
        raise ValueError(f"Unexpected Deribit trade ids in {path}: {invalid}")
    numeric = pd.to_numeric(ids.str.rsplit("-", n=1).str[-1], errors="raise")
    return int(numeric.min()), int(numeric.max())


def _check_deribit_trade_id_order(
    previous_maximum: int | None,
    minimum: int,
    maximum: int,
    path: Path,
) -> int:
    if previous_maximum is not None and minimum <= previous_maximum:
        raise ValueError(
            "Deribit trade ids are not strictly separated across UTC-day files; "
            f"global uniqueness cannot be proven for {path}: "
            f"minimum={minimum}, previous_maximum={previous_maximum}"
        )
    return maximum


def _deribit_cache_paths(cache_root: Path, path: Path) -> tuple[Path, Path]:
    name = path.name.removesuffix(".jsonl.gz")
    return cache_root / f"{name}.feather", cache_root / f"{name}.meta.json"


def _load_deribit_day_cache(
    cache_root: Path,
    path: Path,
    raw_sha256: str,
) -> tuple[pd.DataFrame, dict[str, Any]] | None:
    feather_path, metadata_path = _deribit_cache_paths(cache_root, path)
    if not feather_path.is_file() or not metadata_path.is_file():
        return None
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if (
        metadata.get("cache_version") != DERIBIT_AGGREGATE_CACHE_VERSION
        or metadata.get("raw_sha256") != raw_sha256
        or metadata.get("aggregate_sha256") != _sha256(feather_path)
    ):
        return None
    frame = pd.read_feather(feather_path)
    frame["decision_time"] = _utc_ns(frame["decision_time"])
    frame = frame.set_index("decision_time")
    if len(frame) != metadata.get("aggregate_rows"):
        raise ValueError(f"Deribit aggregate cache row mismatch: {feather_path}")
    return frame, metadata


def _write_deribit_day_cache(
    cache_root: Path,
    path: Path,
    raw_sha256: str,
    frame: pd.DataFrame,
    metadata: dict[str, Any],
) -> None:
    feather_path, metadata_path = _deribit_cache_paths(cache_root, path)
    _atomic_feather(frame.reset_index(), feather_path)
    payload = {
        "cache_version": DERIBIT_AGGREGATE_CACHE_VERSION,
        "raw_sha256": raw_sha256,
        "aggregate_sha256": _sha256(feather_path),
        "aggregate_rows": len(frame),
        **metadata,
    }
    _atomic_write(
        metadata_path,
        json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"),
    )


def _aggregate_deribit(
    paths: list[Path],
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    cache_root: Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    chunks: list[pd.DataFrame] = []
    last_iv: dict[str, float] = {}
    missing_fields: dict[str, int] = {}
    duplicate_trade_ids = 0
    trade_ids = 0
    previous_trade_id_maximum: int | None = None
    for path in sorted(paths):
        raw_sha256 = _sha256(path) if cache_root is not None else ""
        cached = (
            _load_deribit_day_cache(cache_root, path, raw_sha256)
            if cache_root is not None
            else None
        )
        if cached is not None:
            cached_frame, cached_metadata = cached
            minimum = int(cached_metadata["trade_id_minimum"])
            maximum = int(cached_metadata["trade_id_maximum"])
            previous_trade_id_maximum = _check_deribit_trade_id_order(
                previous_trade_id_maximum, minimum, maximum, path
            )
            trade_ids += int(cached_metadata["trade_ids"])
            duplicate_trade_ids += int(cached_metadata["duplicate_trade_ids"])
            for field, count in cached_metadata["missing_optional_field_rows"].items():
                missing_fields[field] = missing_fields.get(field, 0) + int(count)
            last_iv.update(
                {
                    str(instrument): float(value)
                    for instrument, value in cached_metadata["last_iv_delta"].items()
                }
            )
            chunks.append(cached_frame)
            continue

        frame = _read_deribit_file(path)
        if frame.empty:
            continue
        required = {
            "trade_id",
            "timestamp",
            "instrument_name",
            "direction",
            "price",
            "amount",
            "mark_price",
            "iv",
            "index_price",
        }
        absent = required.difference(frame.columns)
        if absent:
            raise ValueError(f"Missing Deribit fields in {path}: {sorted(absent)}")
        ids = frame["trade_id"].astype(str)
        duplicated = ids.duplicated(keep="first")
        day_duplicate_trade_ids = int(duplicated.sum())
        duplicate_trade_ids += day_duplicate_trade_ids
        frame = frame.loc[~duplicated].copy()
        trade_id_minimum, trade_id_maximum = _deribit_trade_id_range(frame, path)
        previous_trade_id_maximum = _check_deribit_trade_id_order(
            previous_trade_id_maximum,
            trade_id_minimum,
            trade_id_maximum,
            path,
        )
        day_trade_ids = len(frame)
        trade_ids += day_trade_ids
        if frame.empty:
            continue

        day_missing_fields: dict[str, int] = {}
        parsed = frame["instrument_name"].str.extract(OPTION_PATTERN)
        frame = pd.concat([frame, parsed], axis=1)
        frame["trade_time"] = _utc_ns(
            pd.to_datetime(
                pd.to_numeric(frame["timestamp"], errors="coerce"),
                unit="ms",
                utc=True,
            )
        )
        for column in ("price", "amount", "mark_price", "iv", "index_price", "strike"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["expiry_time"] = frame["expiry"].map(_parse_expiry)
        frame["dte"] = (
            frame["expiry_time"] - frame["trade_time"]
        ).dt.total_seconds() / 86400
        frame["log_moneyness"] = np.log(frame["strike"] / frame["index_price"])
        for column in (
            "block_trade_id",
            "block_rfq_id",
            "combo_id",
            "combo_trade_id",
            "liquidation",
        ):
            if column not in frame:
                day_missing_fields[column] = len(frame)
                missing_fields[column] = missing_fields.get(column, 0) + len(frame)
                frame[column] = None
        valid = (
            frame["asset"].isin(ASSETS)
            & frame["direction"].isin(["buy", "sell"])
            & frame["trade_time"].notna()
            & (frame["price"] > 0)
            & (frame["amount"] > 0)
            & (frame["mark_price"] > 0)
            & (frame["index_price"] > 0)
            & (frame["dte"] > 0)
        )
        frame = frame.loc[valid].sort_values(
            ["trade_time", "trade_id"], kind="stable"
        )
        if frame.empty:
            continue

        taker_sign = np.where(frame["direction"].eq("buy"), 1.0, -1.0)
        type_sign = np.where(frame["option_type"].eq("C"), 1.0, -1.0)
        frame["direction_sign"] = taker_sign * type_sign
        frame["premium_usd"] = frame["amount"] * frame["price"] * frame["index_price"]
        frame["mark_gap"] = (frame["price"] - frame["mark_price"]) / frame[
            "mark_price"
        ]
        frame["aggressor_urgency"] = taker_sign * frame["mark_gap"]
        frame["directional_urgency"] = frame["direction_sign"] * frame[
            "aggressor_urgency"
        ]
        frame["is_block"] = frame[
            ["block_trade_id", "block_rfq_id"]
        ].notna().any(axis=1)
        frame["is_combo"] = frame[["combo_id", "combo_trade_id"]].notna().any(axis=1)
        frame["is_liquidation"] = frame["liquidation"].notna()
        frame["is_core"] = ~(
            frame["is_block"] | frame["is_combo"] | frame["is_liquidation"]
        )
        is_call = frame["option_type"].eq("C")
        frame["is_otm"] = (
            (is_call & frame["log_moneyness"].between(0, np.log(1.25), inclusive="right"))
            | (
                ~is_call
                & frame["log_moneyness"].between(np.log(0.75), 0, inclusive="left")
            )
        )
        frame["is_atm"] = frame["log_moneyness"].abs() <= 0.05
        frame["is_dte_1_7"] = frame["dte"].between(1, 7, inclusive="both")
        frame["is_dte_8_30"] = frame["dte"].between(8, 30, inclusive="both")
        frame["is_dte_gt30"] = frame["dte"] > 30

        frame["previous_iv"] = frame.groupby("instrument_name", sort=False)["iv"].shift(1)
        first = ~frame.duplicated("instrument_name")
        frame.loc[first, "previous_iv"] = frame.loc[first, "instrument_name"].map(last_iv)
        frame["iv_change"] = frame["iv"] - frame["previous_iv"]
        last_iv_delta: dict[str, float] = {}
        for instrument, value in frame.groupby("instrument_name", sort=False)["iv"].last().items():
            if np.isfinite(value):
                last_iv_delta[str(instrument)] = float(value)
        last_iv.update(last_iv_delta)

        frame["decision_time"] = frame["trade_time"].dt.floor("15min") + pd.Timedelta(
            minutes=15
        )
        core = frame["is_core"]
        otm = core & frame["is_otm"]
        atm = core & frame["is_atm"]
        dte_1_7 = otm & frame["is_dte_1_7"]
        dte_8_30 = otm & frame["is_dte_8_30"]
        dte_gt30 = otm & frame["is_dte_gt30"]
        block = frame["is_block"] & ~frame["is_combo"] & ~frame["is_liquidation"]
        call_otm = otm & is_call
        put_otm = otm & ~is_call
        urgent_buy = frame["aggressor_urgency"].clip(lower=0)

        frame["core_count"] = core.astype(int)
        frame["core_den"] = _conditional_sum(frame, core, "premium_usd")
        frame["core_dir_premium"] = _conditional_sum(
            frame, core, "premium_usd"
        ) * frame["direction_sign"]
        frame["core_dir_urgency"] = _conditional_sum(
            frame, core, "premium_usd"
        ) * frame["directional_urgency"]
        frame["otm_count"] = otm.astype(int)
        frame["otm_den"] = _conditional_sum(frame, otm, "premium_usd")
        frame["otm_dir_premium"] = _conditional_sum(
            frame, otm, "premium_usd"
        ) * frame["direction_sign"]
        frame["otm_dir_urgency"] = _conditional_sum(
            frame, otm, "premium_usd"
        ) * frame["directional_urgency"]
        for label, mask in (
            ("dte_1_7", dte_1_7),
            ("dte_8_30", dte_8_30),
            ("dte_gt30", dte_gt30),
            ("call_otm", call_otm),
            ("put_otm", put_otm),
        ):
            frame[f"{label}_count"] = mask.astype(int)
            frame[f"{label}_den"] = _conditional_sum(frame, mask, "premium_usd")
            frame[f"{label}_dir_premium"] = _conditional_sum(
                frame, mask, "premium_usd"
            ) * frame["direction_sign"]
            frame[f"{label}_dir_urgency"] = _conditional_sum(
                frame, mask, "premium_usd"
            ) * frame["directional_urgency"]
        frame["atm_count"] = atm.astype(int)
        frame["atm_den"] = _conditional_sum(frame, atm, "premium_usd")
        frame["atm_buy_urgency"] = (
            _conditional_sum(frame, atm, "premium_usd") * urgent_buy
        )
        frame["atm_direction"] = (
            _conditional_sum(frame, atm, "premium_usd") * frame["direction_sign"]
        )
        frame["block_count"] = block.astype(int)
        frame["block_den"] = _conditional_sum(frame, block, "premium_usd")
        frame["block_dir_urgency"] = _conditional_sum(
            frame, block, "premium_usd"
        ) * frame["directional_urgency"]
        iv_valid = core & frame["iv_change"].notna()
        frame["iv_count"] = iv_valid.astype(int)
        frame["iv_abs_change"] = frame["iv_change"].abs().where(iv_valid, 0.0)
        frame["iv_directional_change"] = (
            frame["iv_change"].abs() * frame["direction_sign"]
        ).where(iv_valid, 0.0)

        aggregation_columns = [
            column
            for column in frame.columns
            if column.endswith(("_count", "_den", "_premium", "_urgency", "_direction"))
            or column in {"iv_abs_change", "iv_directional_change"}
        ]
        day_aggregate = frame.groupby("decision_time")[aggregation_columns].sum()
        if cache_root is not None:
            _write_deribit_day_cache(
                cache_root,
                path,
                raw_sha256,
                day_aggregate,
                {
                    "trade_ids": day_trade_ids,
                    "duplicate_trade_ids": day_duplicate_trade_ids,
                    "trade_id_minimum": trade_id_minimum,
                    "trade_id_maximum": trade_id_maximum,
                    "missing_optional_field_rows": day_missing_fields,
                    "last_iv_delta": last_iv_delta,
                },
            )
        chunks.append(day_aggregate)

    index = pd.date_range(
        start.floor("15min") + pd.Timedelta(minutes=15),
        end.floor("D") + pd.Timedelta(days=1),
        freq="15min",
        tz="UTC",
    )
    if chunks:
        combined = pd.concat(chunks).groupby(level=0).sum().reindex(index, fill_value=0.0)
    else:
        combined = pd.DataFrame(index=index)
    combined.index.name = "decision_time"
    audit = {
        "trade_ids": trade_ids,
        "duplicate_trade_ids": duplicate_trade_ids,
        "missing_optional_field_rows": missing_fields,
    }
    return combined, audit


def _ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0, np.nan)


def _engineer_deribit_15m(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    rolling = frame.rolling(4, min_periods=1).sum()
    frame["opt_core_count_1h"] = rolling["core_count"]
    frame["opt_core_flow_1h"] = _ratio(
        rolling["core_dir_premium"], rolling["core_den"]
    )
    frame["opt_core_urgency_1h"] = _ratio(
        rolling["core_dir_urgency"], rolling["core_den"]
    )
    frame["opt_otm_count_1h"] = rolling["otm_count"]
    frame["opt_otm_flow_1h"] = _ratio(
        rolling["otm_dir_premium"], rolling["otm_den"]
    )
    frame["opt_otm_urgency_1h"] = _ratio(
        rolling["otm_dir_urgency"], rolling["otm_den"]
    )
    for label in ("dte_1_7", "dte_8_30", "dte_gt30"):
        frame[f"opt_{label}_count_1h"] = rolling[f"{label}_count"]
        frame[f"opt_{label}_flow_1h"] = _ratio(
            rolling[f"{label}_dir_premium"], rolling[f"{label}_den"]
        )
        frame[f"opt_{label}_urgency_1h"] = _ratio(
            rolling[f"{label}_dir_urgency"], rolling[f"{label}_den"]
        )
    frame["opt_wing_urgency_1h"] = _ratio(
        rolling["call_otm_dir_urgency"] + rolling["put_otm_dir_urgency"],
        rolling["call_otm_den"] + rolling["put_otm_den"],
    )
    frame["opt_atm_count_1h"] = rolling["atm_count"]
    frame["opt_atm_buy_urgency_1h"] = _ratio(
        rolling["atm_buy_urgency"], rolling["atm_den"]
    )
    frame["opt_atm_direction_1h"] = _ratio(
        rolling["atm_direction"], rolling["atm_den"]
    )
    frame["opt_block_count_1h"] = rolling["block_count"]
    frame["opt_block_urgency_1h"] = _ratio(
        rolling["block_dir_urgency"], rolling["block_den"]
    )
    frame["opt_iv_count_1h"] = rolling["iv_count"]
    frame["opt_iv_abs_change_1h"] = _ratio(
        rolling["iv_abs_change"], rolling["iv_count"]
    )
    frame["opt_iv_direction_1h"] = _ratio(
        rolling["iv_directional_change"], rolling["iv_count"]
    )
    frame["opt_atm_buy_urgency_z"] = _past_robust_z(
        frame["opt_atm_buy_urgency_1h"].fillna(0),
        window=2880,
        minimum=1000,
        scale_floor=1e-5,
    )
    frame["opt_iv_abs_change_z"] = _past_robust_z(
        frame["opt_iv_abs_change_1h"].fillna(0),
        window=2880,
        minimum=1000,
        scale_floor=0.25,
    )
    frame["opt_iv_event_direction"] = np.where(
        (frame["opt_iv_count_1h"] >= 3)
        & (frame["opt_iv_abs_change_1h"] >= 5)
        & (frame["opt_iv_abs_change_z"].abs() >= 4),
        np.sign(frame["opt_iv_direction_1h"]),
        0,
    )
    return frame


FOMC_EVENTS = [
    "2024-09-18T18:00:00Z",
    "2024-11-07T19:00:00Z",
    "2024-12-18T19:00:00Z",
    "2025-01-29T19:00:00Z",
    "2025-03-19T18:00:00Z",
    "2025-05-07T18:00:00Z",
    "2025-06-18T18:00:00Z",
    "2025-07-30T18:00:00Z",
    "2025-09-17T18:00:00Z",
    "2025-10-29T18:00:00Z",
    "2025-12-10T19:00:00Z",
    "2026-01-28T19:00:00Z",
]
CPI_EVENTS_STRICT = [
    "2021-06-10T12:30:00Z",
    "2021-07-13T12:30:00Z",
    "2021-08-11T12:30:00Z",
    "2021-09-14T12:30:00Z",
    "2021-10-13T12:30:00Z",
    "2021-11-10T13:30:00Z",
    "2021-12-10T13:30:00Z",
    "2022-01-12T13:30:00Z",
    "2022-02-10T13:30:00Z",
    "2022-03-10T13:30:00Z",
    "2022-04-12T12:30:00Z",
    "2022-05-11T12:30:00Z",
    "2022-06-10T12:30:00Z",
    "2022-07-13T12:30:00Z",
    "2022-08-10T12:30:00Z",
    "2022-09-13T12:30:00Z",
    "2022-10-13T12:30:00Z",
    "2022-11-10T13:30:00Z",
    "2022-12-13T13:30:00Z",
    "2023-01-12T13:30:00Z",
    "2023-02-14T13:30:00Z",
    "2023-03-14T12:30:00Z",
    "2023-04-12T12:30:00Z",
    "2023-05-10T12:30:00Z",
    "2023-06-13T12:30:00Z",
    "2023-07-12T12:30:00Z",
    "2023-08-10T12:30:00Z",
    "2023-09-13T12:30:00Z",
    "2023-10-12T12:30:00Z",
    "2023-11-14T13:30:00Z",
    "2023-12-12T13:30:00Z",
    "2024-01-11T13:30:00Z",
    "2024-02-13T13:30:00Z",
    "2024-03-12T12:30:00Z",
    "2024-04-10T12:30:00Z",
    "2024-05-15T12:30:00Z",
    "2024-06-12T12:30:00Z",
    "2024-07-11T12:30:00Z",
    "2024-08-14T12:30:00Z",
    "2024-09-11T12:30:00Z",
    "2024-10-10T12:30:00Z",
    "2024-11-13T13:30:00Z",
    "2024-12-11T13:30:00Z",
    "2025-01-15T13:30:00Z",
    "2025-02-12T13:30:00Z",
    "2025-03-12T12:30:00Z",
    "2025-04-10T12:30:00Z",
    "2025-05-13T12:30:00Z",
    "2025-06-11T12:30:00Z",
    "2025-07-15T12:30:00Z",
    "2025-08-12T12:30:00Z",
    "2025-09-11T12:30:00Z",
    "2025-10-24T12:30:00Z",
    "2025-12-18T13:30:00Z",
    "2026-01-13T13:30:00Z",
    "2026-02-13T13:30:00Z",
    "2026-03-11T12:30:00Z",
    "2026-04-10T12:30:00Z",
    "2026-05-12T12:30:00Z",
    "2026-06-10T12:30:00Z",
    "2026-07-14T12:30:00Z",
]


def _expiry_events(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    events = []
    for period in pd.period_range(start=start, end=end, freq="M"):
        month_end = period.end_time.floor("D")
        offset = (month_end.weekday() - 4) % 7
        last_friday = month_end - pd.Timedelta(days=offset)
        events.append(last_friday.tz_localize("UTC") + pd.Timedelta(hours=8))
    return events


def _nearest_event_minutes(
    decisions: pd.Series, event_times: Iterable[pd.Timestamp]
) -> pd.Series:
    values = np.full(len(decisions), np.nan)
    event_ns = np.array([pd.Timestamp(event).value for event in event_times], dtype=np.int64)
    if not len(event_ns):
        return pd.Series(values, index=decisions.index)
    decision_ns = (
        pd.to_datetime(decisions, utc=True)
        .astype("datetime64[ns, UTC]")
        .array.asi8
    )
    for position, timestamp in enumerate(decision_ns):
        nearest = event_ns[np.argmin(np.abs(event_ns - timestamp))]
        values[position] = (timestamp - nearest) / (60 * 1_000_000_000)
    return pd.Series(values, index=decisions.index)


def _load_underlying(data_root: Path, asset: str) -> pd.DataFrame:
    path = data_root / "futures" / f"{asset}_USDT_USDT-15m-futures.feather"
    frame = pd.read_feather(path)
    required = {"date", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Unexpected underlying columns in {path}: {list(frame.columns)}")
    frame["date"] = _utc_ns(frame["date"])
    frame["decision_time"] = frame["date"] + pd.Timedelta(minutes=15)
    return frame.sort_values("date").reset_index(drop=True)


def _load_okx_funding(data_root: Path, asset: str) -> pd.DataFrame:
    path = data_root / "futures" / f"{asset}_USDT_USDT-1h-funding_rate.feather"
    frame = pd.read_feather(path, columns=["date", "open"])
    frame["date"] = _utc_ns(frame["date"])
    frame["okx_funding_rate"] = pd.to_numeric(frame["open"], errors="coerce")
    return frame[["date", "okx_funding_rate"]].sort_values("date")


def _funding_sidecar(
    decisions: pd.DataFrame,
    binance_funding: pd.DataFrame,
    okx_funding: pd.DataFrame,
) -> pd.DataFrame:
    left = decisions[["decision_time"]].sort_values("decision_time").copy()
    left["decision_time"] = _utc_ns(left["decision_time"])
    binance_funding = binance_funding.copy()
    okx_funding = okx_funding.copy()
    binance_funding["date"] = _utc_ns(binance_funding["date"])
    okx_funding["date"] = _utc_ns(okx_funding["date"])
    result = pd.merge_asof(
        left,
        binance_funding.rename(columns={"date": "bin_funding_time"}),
        left_on="decision_time",
        right_on="bin_funding_time",
        direction="backward",
        allow_exact_matches=True,
    )
    result = pd.merge_asof(
        result,
        okx_funding.rename(columns={"date": "okx_funding_time"}),
        left_on="decision_time",
        right_on="okx_funding_time",
        direction="backward",
        allow_exact_matches=True,
    )
    result["funding_dispersion"] = (
        result["bin_funding_rate"] - result["okx_funding_rate"]
    )
    result["funding_dispersion_z"] = _past_robust_z(
        result["funding_dispersion"], window=2880, minimum=1000, scale_floor=1e-6
    )
    max_age = pd.Timedelta(hours=9)
    result["funding_valid"] = (
        result["bin_funding_time"].notna()
        & result["okx_funding_time"].notna()
        & ((result["decision_time"] - result["bin_funding_time"]) <= max_age)
        & ((result["decision_time"] - result["okx_funding_time"]) <= max_age)
    )
    return result[
        [
            "decision_time",
            "funding_dispersion",
            "funding_dispersion_z",
            "funding_valid",
        ]
    ]


def _engineer_cross_venue(
    underlying: pd.DataFrame,
    binance: pd.DataFrame,
    options: pd.DataFrame,
    funding: pd.DataFrame,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    scored = underlying.loc[
        underlying["decision_time"].between(
            start + pd.Timedelta(minutes=15),
            end + pd.Timedelta(days=1),
            inclusive="both",
        )
    ].copy()
    binance_frame = binance.reset_index().rename(columns={"period_end": "decision_time"})
    option_frame = options.reset_index()
    frame = scored.merge(binance_frame, on="decision_time", how="left", validate="one_to_one")
    frame = frame.merge(option_frame, on="decision_time", how="left", validate="one_to_one")
    frame = frame.merge(funding, on="decision_time", how="left", validate="one_to_one")

    frame["venue_spread"] = np.log(frame["bin_close"] / frame["close"])
    frame["venue_spread_z"] = _past_robust_z(
        frame["venue_spread"], window=2880, minimum=1000, scale_floor=1e-5
    )
    frame["venue_spread_shock"] = (
        frame["venue_spread_z"].abs().ge(4) & frame["venue_spread"].abs().ge(0.001)
    )
    spread_sign = np.sign(frame["venue_spread"])
    frame["venue_spread_cross_zero"] = (
        spread_sign.ne(spread_sign.shift(1))
        & spread_sign.ne(0)
        & spread_sign.shift(1).ne(0)
    )
    frame["okx_return_15m"] = np.log(frame["close"] / frame["close"].shift(1))
    frame["okx_return_15m_z"] = _past_robust_z(
        frame["okx_return_15m"], window=2880, minimum=1000, scale_floor=1e-4
    )
    price_long_shock = (
        frame["okx_return_15m_z"].ge(4) & frame["okx_return_15m"].ge(0.005)
    )
    price_short_shock = (
        frame["okx_return_15m_z"].le(-4) & frame["okx_return_15m"].le(-0.005)
    )
    oi_expansion = (
        frame["bin_oi_change_15m_z"].ge(4) & frame["bin_oi_change_15m"].ge(0.005)
    )
    oi_contraction = (
        frame["bin_oi_change_15m_z"].le(-4)
        & frame["bin_oi_change_15m"].le(-0.005)
    )
    frame["position_adding_long_shock"] = price_long_shock & oi_expansion
    frame["position_adding_short_shock"] = price_short_shock & oi_expansion
    frame["liquidation_long_shock"] = price_long_shock & oi_contraction
    frame["liquidation_short_shock"] = price_short_shock & oi_contraction
    frame["position_adding_long_follow"] = (
        frame["position_adding_long_shock"].shift(1).fillna(False)
        & (frame["close"] >= frame["close"].shift(1))
    )
    frame["position_adding_short_follow"] = (
        frame["position_adding_short_shock"].shift(1).fillna(False)
        & (frame["close"] <= frame["close"].shift(1))
    )
    frame["liquidation_long_reversal"] = (
        frame["liquidation_long_shock"].shift(1).fillna(False)
        & (frame["close"] < frame["high"].shift(1))
        & (frame["close"] < frame["open"])
    )
    frame["liquidation_short_reversal"] = (
        frame["liquidation_short_shock"].shift(1).fillna(False)
        & (frame["close"] > frame["low"].shift(1))
        & (frame["close"] > frame["open"])
    )
    frame["volatility_event"] = (
        frame["okx_return_15m_z"].abs().ge(4)
        & frame["okx_return_15m"].abs().ge(0.005)
    )
    frame["taker_cusum_long_follow"] = (
        frame["bin_cusum_long_current_15m"].shift(1).fillna(False)
        & (frame["close"] > frame["open"])
    )
    frame["taker_cusum_short_follow"] = (
        frame["bin_cusum_short_current_15m"].shift(1).fillna(False)
        & (frame["close"] < frame["open"])
    )
    frame["option_iv_long_follow"] = (
        frame["opt_iv_event_direction"].shift(1).eq(1)
        & (frame["close"] > frame["open"])
    )
    frame["option_iv_short_follow"] = (
        frame["opt_iv_event_direction"].shift(1).eq(-1)
        & (frame["close"] < frame["open"])
    )
    frame["cross_data_valid"] = (
        frame["bin_three_5m_valid"].fillna(False)
        & frame["bin_close"].notna()
        & frame["venue_spread"].notna()
    )

    decisions = frame["decision_time"]
    frame["minutes_from_fomc"] = _nearest_event_minutes(
        decisions, [pd.Timestamp(value) for value in FOMC_EVENTS]
    )
    frame["minutes_from_cpi"] = _nearest_event_minutes(
        decisions, [pd.Timestamp(value) for value in CPI_EVENTS_STRICT]
    )
    frame["minutes_from_expiry"] = _nearest_event_minutes(
        decisions, _expiry_events(start, end)
    )
    frame["nfp_calendar_valid"] = False
    return frame


def _prepare_asset(
    data_root: Path,
    raw_root: Path,
    output_root: Path,
    asset: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, Any]:
    metric_paths = sorted((raw_root / "metrics" / asset).glob("*.zip"))
    kline_paths = sorted((raw_root / "klines" / asset).glob("*.zip"))
    funding_paths = sorted((raw_root / "funding" / asset).glob("*.zip"))
    option_paths = sorted((raw_root / "deribit" / asset).glob("*.jsonl.gz"))
    if not metric_paths or not kline_paths or not funding_paths or not option_paths:
        raise RuntimeError(f"Incomplete raw cross-venue data for {asset}")

    metrics, metric_conflicts = _load_binance_metrics(metric_paths)
    klines, kline_conflicts = _load_binance_klines(kline_paths)
    five_minute = metrics.join(klines, how="outer").sort_index()
    five_minute = five_minute.loc[
        five_minute.index.to_series().between(
            start, end + pd.Timedelta(days=1), inclusive="left"
        )
    ]
    five_minute = _engineer_binance_5m(five_minute)
    binance = _sample_binance_15m(five_minute)

    option_raw, option_audit = _aggregate_deribit(
        option_paths,
        start,
        end,
        cache_root=raw_root / "deribit-aggregate-cache" / asset,
    )
    options = _engineer_deribit_15m(option_raw)
    underlying = _load_underlying(data_root, asset)
    binance_funding = _load_binance_funding(funding_paths)
    okx_funding = _load_okx_funding(data_root, asset)
    funding = _funding_sidecar(underlying, binance_funding, okx_funding)
    engineered = _engineer_cross_venue(
        underlying, binance, options, funding, start=start, end=end
    )

    output = output_root / f"{asset}_USDT_USDT-15m-cross-venue.feather"
    output.parent.mkdir(parents=True, exist_ok=True)
    engineered.reset_index(drop=True).to_feather(output)
    return {
        "asset": asset,
        "output": str(output.relative_to(REPO_ROOT)),
        "output_sha256": _sha256(output),
        "rows": len(engineered),
        "decision_start": engineered["decision_time"].min().isoformat(),
        "decision_end": engineered["decision_time"].max().isoformat(),
        "binance_metric_conflicts": metric_conflicts,
        "binance_kline_conflicts": kline_conflicts,
        "cross_valid_rows": int(engineered["cross_data_valid"].sum()),
        "option_core_trade_buckets": int((engineered["opt_core_count_1h"] > 0).sum()),
        "option_audit": option_audit,
    }


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    if start > end:
        raise ValueError("--start must not be later than --end")
    if args.workers < 1:
        raise ValueError("--workers must be positive")

    data_root = args.data_root.expanduser().resolve()
    output_root = data_root / "cross-venue"
    raw_root = output_root / "raw"
    if args.skip_download:
        binance_manifest = _local_binance_manifest(raw_root, start, end)
        deribit_manifest = _local_deribit_manifest(raw_root, start, end)
    else:
        binance_manifest = _download_binance(raw_root, start, end, args.workers)
        deribit_manifest = _download_deribit(
            raw_root,
            start,
            end,
            connect_ip=args.deribit_ip,
            proxy_host=args.proxy_host,
            proxy_port=args.proxy_port,
            workers=args.workers,
        )
    summaries = [
        _prepare_asset(data_root, raw_root, output_root, asset, start, end)
        for asset in ASSETS
    ]
    manifest = {
        "source": {
            "binance": "Official data.binance.vision UM futures archives",
            "deribit": "Official history.deribit.com public option trades",
        },
        "start": start.isoformat(),
        "end": end.isoformat(),
        "availability_rule": {
            "binance": (
                "Live-equivalent simulation only: metrics/OI/account timestamps are period end, "
                "taker timestamps are shifted from period start to period end, then +10 seconds."
            ),
            "deribit": "Live-equivalent simulation only: trade timestamp +10 seconds.",
            "decision": (
                "A sidecar row stamped with candle start contains only source events strictly "
                "before or available by that candle's end plus fixed lateness."
            ),
        },
        "limitations": [
            (
                "Archive first-seen timestamps were not historically polled; this is not "
                "archive-availability replay."
            ),
            "Binance, OKX and Deribit are distinct capital pools and settlement mechanisms.",
            (
                "Deribit direction is taker side and cannot identify opening, closing, "
                "customer, dealer or hedge intent."
            ),
            "No live updater or execution-quality order-book model is installed.",
        ],
        "binance_files": binance_manifest,
        "deribit_days": deribit_manifest,
        "assets": summaries,
    }
    manifest_path = output_root / "manifest.json"
    _atomic_write(
        manifest_path,
        json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
