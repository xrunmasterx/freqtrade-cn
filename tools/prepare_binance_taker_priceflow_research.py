from __future__ import annotations

import hashlib
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "research_data"
    / "binance-taker-priceflow-confirmation"
)
RAW_ROOT = DATA_ROOT / "raw" / "binance-vision" / "futures" / "um" / "BTCUSDT" / "5m"
SOURCE_ROOT = "https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/5m"
START = pd.Timestamp("2022-02-01T00:00:00Z")
END_EXCLUSIVE = pd.Timestamp("2025-01-01T00:00:00Z")
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.part")
    temporary.write_bytes(content)
    temporary.replace(path)


def download_month(month: str) -> dict[str, object]:
    name = f"BTCUSDT-5m-{month}.zip"
    url = f"{SOURCE_ROOT}/{name}"
    archive_path = RAW_ROOT / name
    checksum_path = RAW_ROOT / f"{name}.CHECKSUM"

    if archive_path.is_file() and checksum_path.is_file():
        expected = checksum_path.read_text(encoding="utf-8").split()[0].lower()
        actual = sha256(archive_path)
        if actual == expected:
            return {
                "month": month,
                "url": url,
                "path": archive_path.relative_to(REPO_ROOT).as_posix(),
                "bytes": archive_path.stat().st_size,
                "sha256": actual,
                "official_checksum": expected,
                "reused": True,
            }

    session = requests.Session()
    session.headers["User-Agent"] = "freqtrade-cn-binance-taker-priceflow-research/1"
    checksum_response = session.get(f"{url}.CHECKSUM", timeout=30)
    checksum_response.raise_for_status()
    expected = checksum_response.text.split()[0].lower()
    archive_response = session.get(url, timeout=120)
    archive_response.raise_for_status()
    actual = hashlib.sha256(archive_response.content).hexdigest()
    if actual != expected:
        raise ValueError(f"Checksum mismatch for {url}: {actual} != {expected}")

    atomic_write(archive_path, archive_response.content)
    atomic_write(checksum_path, checksum_response.content)
    return {
        "month": month,
        "url": url,
        "path": archive_path.relative_to(REPO_ROOT).as_posix(),
        "bytes": archive_path.stat().st_size,
        "sha256": actual,
        "official_checksum": expected,
        "reused": False,
    }


def read_month(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"Expected one CSV in {path}, found {len(members)}")
        with archive.open(members[0]) as handle:
            frame = pd.read_csv(handle, header=None, names=KLINE_COLUMNS)

    frame["open_time"] = pd.to_numeric(frame["open_time"], errors="coerce")
    frame = frame.loc[frame["open_time"].notna()].copy()
    numeric = [column for column in KLINE_COLUMNS if column != "ignore"]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["date"] = pd.to_datetime(frame.pop("open_time"), unit="ms", utc=True)
    return frame


def validate_five_minute(frame: pd.DataFrame) -> dict[str, object]:
    frame.sort_values("date", inplace=True)
    duplicate_rows = int(frame.duplicated("date", keep=False).sum())
    if duplicate_rows:
        raise ValueError(f"Duplicate 5m timestamps: {duplicate_rows}")

    expected = pd.date_range(START, END_EXCLUSIVE, freq="5min", inclusive="left")
    missing = expected.difference(pd.DatetimeIndex(frame["date"]))
    unexpected = pd.DatetimeIndex(frame["date"]).difference(expected)
    if len(missing) or len(unexpected):
        raise ValueError(
            f"5m continuity failure: missing={len(missing)}, unexpected={len(unexpected)}"
        )
    if len(frame) != len(expected):
        raise ValueError(f"5m row count mismatch: {len(frame)} != {len(expected)}")

    required = [
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
    ]
    if frame[required].isna().any().any():
        raise ValueError("5m kline contains non-numeric required values")
    if (frame["volume"] < 0).any() or (frame["taker_buy_volume"] < 0).any():
        raise ValueError("5m kline contains negative volume")
    tolerance = frame["volume"].abs().clip(lower=1.0) * 1e-12
    if (frame["taker_buy_volume"] - frame["volume"] > tolerance).any():
        raise ValueError("5m taker-buy volume exceeds total volume")

    expected_close_ms = (
        frame["date"].astype("datetime64[ms, UTC]").astype("int64") + 5 * 60_000 - 1
    )
    bad_close_time = int((frame["close_time"].round().astype("int64") != expected_close_ms).sum())
    if bad_close_time:
        raise ValueError(f"Unexpected 5m close_time rows: {bad_close_time}")

    return {
        "rows": len(frame),
        "expected_rows": len(expected),
        "first_open_utc": frame["date"].iloc[0].isoformat(),
        "last_open_utc": frame["date"].iloc[-1].isoformat(),
        "duplicate_timestamp_rows": duplicate_rows,
        "missing_timestamp_count": len(missing),
        "unexpected_timestamp_count": len(unexpected),
        "timestamp_step_seconds": 300,
        "close_time_mismatch_count": bad_close_time,
    }


def build_fifteen_minute(frame: pd.DataFrame) -> pd.DataFrame:
    five = frame[["date", "volume", "taker_buy_volume"]].copy()
    five["taker_imbalance_5m"] = (
        2 * five["taker_buy_volume"] / five["volume"].replace(0, float("nan")) - 1
    )
    five["bucket_open"] = five["date"].dt.floor("15min")
    five["position"] = five.groupby("bucket_open").cumcount()

    totals = five.groupby("bucket_open", sort=True).agg(
        binance_volume_15m=("volume", "sum"),
        binance_taker_buy_volume_15m=("taker_buy_volume", "sum"),
        constituent_5m_count=("date", "size"),
    )
    first = five.loc[five["position"].eq(0)].set_index("bucket_open")["taker_imbalance_5m"]
    last = five.loc[five["position"].eq(2)].set_index("bucket_open")["taker_imbalance_5m"]
    result = totals.join(first.rename("binance_taker_imbalance_first_5m")).join(
        last.rename("binance_taker_imbalance_last_5m")
    )
    if not result["constituent_5m_count"].eq(3).all():
        raise ValueError("Incomplete 15m Binance aggregation")

    result["binance_taker_imbalance_15m"] = (
        2
        * result["binance_taker_buy_volume_15m"]
        / result["binance_volume_15m"].replace(0, float("nan"))
        - 1
    )
    result["binance_taker_improved_long_10m"] = (
        result["binance_taker_imbalance_last_5m"]
        >= result["binance_taker_imbalance_first_5m"]
    )
    result["binance_taker_improved_short_10m"] = (
        result["binance_taker_imbalance_last_5m"]
        <= result["binance_taker_imbalance_first_5m"]
    )
    result = result.reset_index()
    result["source_complete_time"] = result["bucket_open"] + pd.Timedelta(minutes=15)
    result["date"] = result["bucket_open"] + pd.Timedelta(minutes=15)
    result["decision_time"] = result["date"] + pd.Timedelta(minutes=15)
    result["publication_lag_minutes"] = 15
    result = result.loc[result["decision_time"] < END_EXCLUSIVE].copy()
    return result[
        [
            "date",
            "decision_time",
            "bucket_open",
            "source_complete_time",
            "publication_lag_minutes",
            "constituent_5m_count",
            "binance_volume_15m",
            "binance_taker_buy_volume_15m",
            "binance_taker_imbalance_15m",
            "binance_taker_imbalance_first_5m",
            "binance_taker_imbalance_last_5m",
            "binance_taker_improved_long_10m",
            "binance_taker_improved_short_10m",
        ]
    ]


def write_feather(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.part")
    frame.reset_index(drop=True).to_feather(temporary)
    temporary.replace(path)


def main() -> None:
    months = [str(period) for period in pd.period_range("2022-02", "2024-12", freq="M")]
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(download_month, month): month for month in months}
        archives = []
        for future in as_completed(futures):
            result = future.result()
            archives.append(result)
            print(f"verified {result['month']} {result['sha256']}", flush=True)
    archives.sort(key=lambda item: str(item["month"]))

    chunks = [read_month(REPO_ROOT / str(item["path"])) for item in archives]
    five = pd.concat(chunks, ignore_index=True)
    five_validation = validate_five_minute(five)
    five["taker_imbalance_5m"] = (
        2 * five["taker_buy_volume"] / five["volume"].replace(0, float("nan")) - 1
    )
    five_path = DATA_ROOT / "derived" / "BTCUSDT-5m-kline-taker.feather"
    write_feather(five, five_path)

    fifteen = build_fifteen_minute(five)
    fifteen_path = DATA_ROOT / "derived" / "BTCUSDT-15m-taker-confirmation.feather"
    write_feather(fifteen, fifteen_path)

    manifest = {
        "research_only": True,
        "source": {
            "provider": "Binance Vision",
            "market": "USD-M perpetual",
            "symbol": "BTCUSDT",
            "timeframe": "5m",
            "dataset": "monthly klines",
            "url_root": SOURCE_ROOT,
            "field_contract": KLINE_COLUMNS,
        },
        "window": {
            "start_inclusive": START.isoformat(),
            "end_exclusive": END_EXCLUSIVE.isoformat(),
            "months": months,
            "forbid_2025_and_later": True,
        },
        "raw_archives": archives,
        "validation": five_validation,
        "derived": {
            "five_minute": {
                "path": five_path.relative_to(REPO_ROOT).as_posix(),
                "rows": len(five),
                "sha256": sha256(five_path),
            },
            "fifteen_minute": {
                "path": fifteen_path.relative_to(REPO_ROOT).as_posix(),
                "rows": len(fifteen),
                "first_date_utc": fifteen["date"].iloc[0].isoformat(),
                "last_date_utc": fifteen["date"].iloc[-1].isoformat(),
                "duplicate_date_rows": int(fifteen.duplicated("date", keep=False).sum()),
                "incomplete_aggregate_rows": int(
                    fifteen["constituent_5m_count"].ne(3).sum()
                ),
                "sha256": sha256(fifteen_path),
            },
        },
        "feature_semantics": {
            "imbalance": "2 * taker_buy_base_volume / total_base_volume - 1",
            "ten_minute_improvement": (
                "last constituent 5m imbalance compared with first constituent 5m "
                "imbalance in the same complete 15m bucket"
            ),
            "availability": (
                "complete 15m bucket is shifted onto the next 15m strategy candle; "
                "at that candle's close it is at least 15 minutes old"
            ),
        },
    }
    manifest_path = DATA_ROOT / "binance-data-manifest.json"
    atomic_write(
        manifest_path,
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    print(f"manifest {manifest_path}", flush=True)
    print(f"manifest_sha256 {sha256(manifest_path)}", flush=True)


if __name__ == "__main__":
    main()
