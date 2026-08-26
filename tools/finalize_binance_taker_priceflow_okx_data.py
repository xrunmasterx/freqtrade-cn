from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "research_data"
    / "binance-taker-priceflow-confirmation"
)
FUTURES_ROOT = RESEARCH_ROOT / "okx-market-data" / "futures"
FUNDING_ARCHIVE_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "data"
    / "okx-btc-usdt-swap-full-20260813"
    / "raw-funding-archives"
)
START = pd.Timestamp("2022-02-01T00:00:00Z")
END_EXCLUSIVE = pd.Timestamp("2025-01-01T00:00:00Z")
MARKET_FILES = {
    "5m": "BTC_USDT_USDT-5m-futures.feather",
    "15m": "BTC_USDT_USDT-15m-futures.feather",
    "1h": "BTC_USDT_USDT-1h-futures.feather",
    "4h": "BTC_USDT_USDT-4h-futures.feather",
    "1h-mark": "BTC_USDT_USDT-1h-mark.feather",
}
INTERVALS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1h-mark": 3600}
FUNDING_ARCHIVE_PREFIX = (
    "https://static.okx.com/cdn/okex/traderecords/swaprates/monthly/"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_feather(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_suffix(f"{path.suffix}.part")
    frame.reset_index(drop=True).to_feather(temporary)
    temporary.replace(path)


def trim_market_file(label: str, filename: str) -> dict[str, object]:
    path = FUTURES_ROOT / filename
    frame = pd.read_feather(path)
    frame["date"] = pd.to_datetime(frame["date"], utc=True)
    downloaded_rows = len(frame)
    downloaded_last = frame["date"].max()
    in_scope = frame["date"].ge(START) & frame["date"].lt(END_EXCLUSIVE)
    discarded_after_end = int(frame["date"].ge(END_EXCLUSIVE).sum())
    frame = frame.loc[in_scope].sort_values("date").reset_index(drop=True)

    duplicates = int(frame.duplicated("date", keep=False).sum())
    if duplicates:
        raise ValueError(f"{label} has {duplicates} duplicate timestamp rows")
    interval = INTERVALS[label]
    deltas = frame["date"].diff().dropna().dt.total_seconds().astype(int)
    unexpected = int(deltas.ne(interval).sum())
    if unexpected:
        raise ValueError(f"{label} has {unexpected} unexpected timestamp intervals")
    if frame.empty or frame["date"].iloc[0] != START:
        raise ValueError(f"{label} does not start at the frozen boundary")
    if frame["date"].ge(END_EXCLUSIVE).any():
        raise ValueError(f"{label} retained out-of-scope rows")

    write_feather(frame, path)
    return {
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "source": "OKX /api/v5/market/history-candles via CCXT/Freqtrade",
        "download_requested_start": START.isoformat(),
        "download_requested_end_exclusive": END_EXCLUSIVE.isoformat(),
        "downloader_overfetch_disclosed": discarded_after_end > 0,
        "downloaded_rows_before_trim": downloaded_rows,
        "downloaded_last_before_trim_utc": downloaded_last.isoformat(),
        "discarded_at_or_after_end": discarded_after_end,
        "rows": len(frame),
        "first_utc": frame["date"].iloc[0].isoformat(),
        "last_utc": frame["date"].iloc[-1].isoformat(),
        "duplicate_timestamp_rows": duplicates,
        "unexpected_interval_count": unexpected,
        "sha256": sha256(path),
    }


def read_funding_archive(path: Path) -> pd.DataFrame:
    expected_member = path.name.removesuffix(".zip") + ".csv"
    with zipfile.ZipFile(path) as archive:
        if archive.namelist() != [expected_member]:
            raise ValueError(f"Unexpected archive members in {path}")
        with archive.open(expected_member) as handle:
            frame = pd.read_csv(handle)
    if list(frame.columns) != ["instrument_name", "funding_rate", "funding_time"]:
        raise ValueError(f"Unexpected funding schema in {path}")
    if not frame["instrument_name"].eq("BTC-USDT-SWAP").all():
        raise ValueError(f"Unexpected instrument in {path}")
    frame["date_exact"] = pd.to_datetime(
        pd.to_numeric(frame["funding_time"], errors="raise"), unit="ms", utc=True
    )
    frame["open"] = pd.to_numeric(frame["funding_rate"], errors="raise")
    return frame[["date_exact", "open"]]


def build_funding() -> dict[str, object]:
    months = [str(period) for period in pd.period_range("2022-02", "2024-12", freq="M")]
    archives = []
    chunks = []
    for month in months:
        name = f"BTC-USDT-SWAP-fundingrates-{month}.zip"
        path = FUNDING_ARCHIVE_ROOT / name
        if not path.is_file():
            raise FileNotFoundError(path)
        chunk = read_funding_archive(path)
        chunks.append(chunk)
        archives.append(
            {
                "month": month,
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "source_url": f"{FUNDING_ARCHIVE_PREFIX}{name}",
                "bytes": path.stat().st_size,
                "rows": len(chunk),
                "sha256": sha256(path),
            }
        )

    exact = pd.concat(chunks, ignore_index=True)
    exact = exact.loc[
        exact["date_exact"].ge(START) & exact["date_exact"].lt(END_EXCLUSIVE)
    ].copy()
    exact.sort_values("date_exact", inplace=True)
    duplicate_exact = int(exact.duplicated("date_exact", keep=False).sum())
    if duplicate_exact:
        conflicts = exact.groupby("date_exact")["open"].nunique()
        if (conflicts > 1).any():
            raise ValueError("Conflicting exact OKX funding events")
        exact.drop_duplicates("date_exact", keep="first", inplace=True)

    exact["date"] = exact["date_exact"].dt.floor("1h")
    conflicts = exact.groupby("date")["open"].nunique()
    if (conflicts > 1).any():
        raise ValueError("Conflicting OKX funding events after 1h normalization")
    normalized = exact.drop_duplicates("date", keep="last")[["date", "open"]].copy()
    normalized["high"] = 0.0
    normalized["low"] = 0.0
    normalized["close"] = 0.0
    normalized["volume"] = 0.0
    normalized = normalized[["date", "open", "high", "low", "close", "volume"]]
    if normalized["date"].ge(END_EXCLUSIVE).any():
        raise ValueError("Funding retained out-of-scope rows")

    path = FUTURES_ROOT / "BTC_USDT_USDT-1h-funding_rate.feather"
    write_feather(normalized, path)
    deltas = exact["date_exact"].diff().dropna().dt.total_seconds().astype(int)
    distribution = {str(seconds): count for seconds, count in sorted(Counter(deltas).items())}
    return {
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "source": "OKX official monthly swaprates archives",
        "archive_index_endpoint": (
            "https://www.okx.com/api/v5/public/market-data-history"
        ),
        "archives": archives,
        "rows": len(normalized),
        "first_exact_utc": exact["date_exact"].iloc[0].isoformat(),
        "last_exact_utc": exact["date_exact"].iloc[-1].isoformat(),
        "duplicate_exact_timestamp_rows": duplicate_exact,
        "exact_interval_seconds_distribution": distribution,
        "normalization": "official event timestamps floored to 1h for Freqtrade",
        "sha256": sha256(path),
    }


def main() -> None:
    FUTURES_ROOT.mkdir(parents=True, exist_ok=True)
    market = {
        label: trim_market_file(label, filename)
        for label, filename in MARKET_FILES.items()
    }
    funding = build_funding()
    manifest = {
        "research_only": True,
        "pair": "BTC/USDT:USDT",
        "exchange": "OKX",
        "window": {
            "start_inclusive": START.isoformat(),
            "end_exclusive": END_EXCLUSIVE.isoformat(),
            "contains_rows_at_or_after_end": False,
        },
        "market": market,
        "funding": funding,
        "funding_fallback_per_hour": 0.0000042304172276700455,
        "funding_fallback_semantics": (
            "Freqtrade leading-gap fallback per 1h mark row; actual OKX funding events "
            "are retained where present; 8h mean divided by 8"
        ),
    }
    path = RESEARCH_ROOT / "okx-data-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"manifest {path}")
    print(f"manifest_sha256 {sha256(path)}")


if __name__ == "__main__":
    main()
