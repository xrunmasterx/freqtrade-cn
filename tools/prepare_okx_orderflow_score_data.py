from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
OKX_API = "https://www.okx.com/api/v5"
DEFAULT_RAW_ROOT = REPO_ROOT / "ft_userdata" / "runtime" / "okx-orderflow-score" / "raw"
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "ft_userdata" / "user_data" / "research_data" / "okx-orderflow-score"
)
DEFAULT_CANDLE_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "data"
    / "okx"
    / "futures"
)
PAIR_SPECS = {
    "BTC": {
        "inst_id": "BTC-USDT-SWAP",
        "family": "BTC-USDT",
        "freqtrade_name": "BTC_USDT_USDT",
        "minimum_oi_usd": 1_000_000_000.0,
    },
    "ETH": {
        "inst_id": "ETH-USDT-SWAP",
        "family": "ETH-USDT",
        "freqtrade_name": "ETH_USDT_USDT",
        "minimum_oi_usd": 500_000_000.0,
    },
}
TRADE_COLUMNS = ["side", "price", "size", "created_time"]


def _timestamp(value: str) -> pd.Timestamp:
    result = pd.Timestamp(value)
    return result.tz_localize("UTC") if result.tz is None else result.tz_convert("UTC")


def _okx_json(
    session: requests.Session,
    path: str,
    params: dict[str, str],
) -> dict[str, Any]:
    for attempt in range(8):
        response = session.get(f"{OKX_API}{path}", params=params, timeout=60)
        payload = response.json()
        if payload.get("code") == "0":
            return payload
        if payload.get("code") != "50011" or attempt == 7:
            raise RuntimeError(
                f"OKX {path} failed: {payload.get('code')} {payload.get('msg')}"
            )
        time.sleep(1.0 + attempt)
    raise AssertionError("unreachable")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_contract_value(session: requests.Session, inst_id: str) -> float:
    payload = _okx_json(
        session,
        "/public/instruments",
        {"instType": "SWAP", "instId": inst_id},
    )
    rows = payload.get("data", [])
    if len(rows) != 1 or rows[0].get("instId") != inst_id:
        raise ValueError(f"OKX did not return exactly one instrument for {inst_id}")
    value = float(rows[0]["ctVal"])
    if not np.isfinite(value) or value <= 0:
        raise ValueError(f"Invalid OKX contract value for {inst_id}: {value}")
    return value


def _daily_windows(
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    windows = []
    cursor = start
    while cursor < end:
        window_end = min(cursor + pd.Timedelta(days=9), end)
        windows.append((cursor, window_end))
        cursor = window_end
    return windows


def discover_daily_archives(
    session: requests.Session,
    family: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[dict[str, str]]:
    # OKX trade archives use UTC+8 calendar boundaries. Widen discovery and
    # filter the actual millisecond timestamps while parsing.
    query_start = start - pd.Timedelta(days=1)
    query_end = end + pd.Timedelta(days=1)
    files: dict[str, dict[str, str]] = {}
    for window_start, window_end in _daily_windows(query_start, query_end):
        payload = _okx_json(
            session,
            "/public/market-data-history",
            {
                "module": "1",
                "instType": "SWAP",
                "instFamilyList": family,
                "dateAggrType": "daily",
                "begin": str(int(window_start.timestamp() * 1000)),
                "end": str(int(window_end.timestamp() * 1000)),
            },
        )
        for result in payload.get("data", []):
            for detail in result.get("details", []):
                for item in detail.get("groupDetails", []):
                    files[item["filename"]] = item
    if not files:
        raise ValueError(f"OKX returned no daily trade archives for {family}")
    return [files[name] for name in sorted(files)]


def download_archive(
    session: requests.Session,
    item: dict[str, str],
    destination: Path,
) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / item["filename"]
    if target.is_file() and target.stat().st_size > 0:
        return target
    temporary = target.with_suffix(f"{target.suffix}.part")
    with session.get(item["url"], stream=True, timeout=180) as response:
        response.raise_for_status()
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    os.replace(temporary, target)
    return target


def aggregate_trades(
    trades: pd.DataFrame,
    *,
    contract_value: float,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    missing = set(TRADE_COLUMNS).difference(trades.columns)
    if missing:
        raise ValueError(f"OKX trade data is missing columns: {sorted(missing)}")
    frame = trades[TRADE_COLUMNS].copy()
    frame["created_time"] = pd.to_numeric(frame["created_time"], errors="raise")
    frame["date"] = pd.to_datetime(frame["created_time"], unit="ms", utc=True)
    if start is not None:
        frame = frame.loc[frame["date"] >= start]
    if end is not None:
        frame = frame.loc[frame["date"] < end]
    if frame.empty:
        return pd.DataFrame(), pd.DataFrame()
    frame["price"] = pd.to_numeric(frame["price"], errors="raise")
    frame["size"] = pd.to_numeric(frame["size"], errors="raise")
    if not frame["side"].isin(["buy", "sell"]).all():
        raise ValueError("OKX trade side must be buy or sell")
    if (frame[["price", "size"]].le(0).any(axis=1)).any():
        raise ValueError("OKX trade price and size must be positive")
    frame = frame.sort_values("created_time")
    frame["base_volume"] = frame["size"] * contract_value
    frame["bucket"] = frame["date"].dt.floor("5min")
    frame["buy_base"] = frame["base_volume"].where(frame["side"].eq("buy"), 0.0)
    frame["sell_base"] = frame["base_volume"].where(frame["side"].eq("sell"), 0.0)
    five = (
        frame.groupby("bucket", sort=True, observed=True)
        .agg(
            buy_base=("buy_base", "sum"),
            sell_base=("sell_base", "sum"),
            trade_count=("side", "size"),
            first_price=("price", "first"),
            last_price=("price", "last"),
            high_price=("price", "max"),
            low_price=("price", "min"),
        )
        .rename_axis("date")
        .reset_index()
    )
    price_volume = (
        frame.assign(date=frame["date"].dt.floor("D"))
        .groupby(["date", "price"], as_index=False, sort=True, observed=True)[
            "base_volume"
        ]
        .sum()
    )
    return five, price_volume


def _combine_five_minute(parts: list[pd.DataFrame]) -> pd.DataFrame:
    if not parts:
        raise ValueError("No OKX trades overlapped the requested interval")
    frame = pd.concat(parts, ignore_index=True).sort_values("date")
    return frame.groupby("date", as_index=False, sort=True, observed=True).agg(
        buy_base=("buy_base", "sum"),
        sell_base=("sell_base", "sum"),
        trade_count=("trade_count", "sum"),
        first_price=("first_price", "first"),
        last_price=("last_price", "last"),
        high_price=("high_price", "max"),
        low_price=("low_price", "min"),
    )


def _combine_price_volume(parts: list[pd.DataFrame]) -> pd.DataFrame:
    if not parts:
        raise ValueError("No price-volume rows overlapped the requested interval")
    return (
        pd.concat(parts, ignore_index=True)
        .groupby(["date", "price"], as_index=False, sort=True, observed=True)[
            "base_volume"
        ]
        .sum()
    )


def aggregate_archives(
    archives: list[Path],
    *,
    contract_value: float,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    five_parts: list[pd.DataFrame] = []
    price_parts: list[pd.DataFrame] = []
    for archive in archives:
        print(f"aggregate {archive.name}", flush=True)
        with zipfile.ZipFile(archive) as bundle:
            members = [
                name for name in bundle.namelist() if name.lower().endswith(".csv")
            ]
            if len(members) != 1:
                raise ValueError(f"Expected one CSV in {archive}, found {members}")
            with bundle.open(members[0]) as handle:
                for chunk in pd.read_csv(
                    handle,
                    usecols=TRADE_COLUMNS,
                    chunksize=500_000,
                ):
                    five, price = aggregate_trades(
                        chunk,
                        contract_value=contract_value,
                        start=start,
                        end=end,
                    )
                    if not five.empty:
                        five_parts.append(five)
                        price_parts.append(price)
    return _combine_five_minute(five_parts), _combine_price_volume(price_parts)


def _profile_for_day(
    day: pd.Timestamp,
    frame: pd.DataFrame,
    *,
    bins: int,
    value_area: float,
) -> dict[str, Any]:
    low = float(frame["price"].min())
    high = float(frame["price"].max())
    if low == high:
        poc = vah = val = low
    else:
        edges = np.linspace(low, high, bins + 1)
        indexes = np.searchsorted(edges, frame["price"].to_numpy(), side="right") - 1
        indexes = np.clip(indexes, 0, bins - 1)
        working = frame.assign(bin=indexes)
        weighted = working.assign(weighted=working["price"] * working["base_volume"])
        weighted = weighted.groupby("bin", observed=True).agg(
            volume=("base_volume", "sum"), weighted=("weighted", "sum")
        )
        grouped = weighted.reindex(range(bins), fill_value=0.0)
        volumes = grouped["volume"].to_numpy()
        poc_index = int(np.argmax(volumes))
        poc = float(grouped.iloc[poc_index]["weighted"] / volumes[poc_index])
        selected = {poc_index}
        accumulated = volumes[poc_index]
        target = volumes.sum() * value_area
        lower = upper = poc_index
        while accumulated < target and (lower > 0 or upper < bins - 1):
            below = volumes[lower - 1] if lower > 0 else -1.0
            above = volumes[upper + 1] if upper < bins - 1 else -1.0
            if above >= below:
                upper += 1
                selected.add(upper)
                accumulated += volumes[upper]
            else:
                lower -= 1
                selected.add(lower)
                accumulated += volumes[lower]
        val = float(edges[min(selected)])
        vah = float(edges[max(selected) + 1])
    return {
        "source_day": day,
        "source_complete_time": day + pd.Timedelta(days=1),
        "vp_poc": poc,
        "vp_vah": vah,
        "vp_val": val,
        "prior_day_high": high,
        "prior_day_low": low,
        "profile_base_volume": float(frame["base_volume"].sum()),
    }


def build_daily_profiles(
    price_volume: pd.DataFrame,
    *,
    bins: int = 100,
    value_area: float = 0.70,
) -> pd.DataFrame:
    if bins < 2:
        raise ValueError("Volume profile requires at least two bins")
    if not 0 < value_area <= 1:
        raise ValueError("value_area must be in (0, 1]")
    frame = price_volume.copy()
    frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="raise").dt.floor(
        "D"
    )
    rows = [
        _profile_for_day(day, group, bins=bins, value_area=value_area)
        for day, group in frame.groupby("date", sort=True, observed=True)
    ]
    return pd.DataFrame(rows)


def attach_previous_day_profile(
    candles: pd.DataFrame,
    profiles: pd.DataFrame,
) -> pd.DataFrame:
    result = candles.copy()
    result["date"] = pd.to_datetime(result["date"], utc=True, errors="raise")
    result["vp_source_day"] = result["date"].dt.floor("D") - pd.Timedelta(days=1)
    evidence = profiles.rename(
        columns={
            "source_day": "vp_source_day",
            "source_complete_time": "vp_source_complete_time",
        }
    )
    result = result.merge(
        evidence, on="vp_source_day", how="left", validate="many_to_one"
    )
    contradiction = result["vp_source_complete_time"].notna() & result[
        "vp_source_complete_time"
    ].gt(result["date"])
    if contradiction.any():
        raise ValueError("Volume profile evidence is newer than the decision candle")
    return result


def build_fifteen_minute(five: pd.DataFrame) -> pd.DataFrame:
    frame = five.copy().sort_values("date")
    frame["total_base"] = frame["buy_base"] + frame["sell_base"]
    frame["delta_base"] = frame["buy_base"] - frame["sell_base"]
    frame["imbalance"] = frame["delta_base"] / frame["total_base"].replace(0, np.nan)
    frame["bucket"] = frame["date"].dt.floor("15min")
    fifteen = (
        frame.groupby("bucket", sort=True, observed=True)
        .agg(
            constituent_5m_count=("date", "size"),
            trade_count=("trade_count", "sum"),
            buy_base=("buy_base", "sum"),
            sell_base=("sell_base", "sum"),
            total_base=("total_base", "sum"),
            delta_base=("delta_base", "sum"),
            first_5m_imbalance=("imbalance", "first"),
            last_5m_imbalance=("imbalance", "last"),
            first_price=("first_price", "first"),
            last_price=("last_price", "last"),
        )
        .rename_axis("date")
        .reset_index()
    )
    fifteen["imbalance"] = fifteen["delta_base"] / fifteen["total_base"].replace(
        0, np.nan
    )
    fifteen["last_5m_return"] = fifteen["last_price"] / fifteen["first_price"] - 1.0
    session = fifteen["date"].dt.floor("D")
    fifteen["cvd_session"] = fifteen["delta_base"].groupby(session).cumsum()
    fifteen["cvd_slope_4"] = (
        fifteen["delta_base"]
        .groupby(session)
        .transform(lambda values: values.rolling(4, min_periods=1).sum())
    )
    fifteen["source_complete_time"] = fifteen["date"] + pd.Timedelta(minutes=15)
    fifteen["decision_time"] = fifteen["source_complete_time"]
    return fifteen


def validate_candle_volume(
    aggregated: pd.DataFrame,
    candles: pd.DataFrame,
) -> dict[str, float | int]:
    expected = candles[["date", "volume"]].copy()
    expected["date"] = pd.to_datetime(expected["date"], utc=True, errors="raise")
    actual = aggregated[["date", "total_base"]].copy()
    actual["date"] = pd.to_datetime(actual["date"], utc=True, errors="raise")
    compared = expected.merge(actual, on="date", how="left", validate="one_to_one")
    if compared["total_base"].isna().any():
        first = compared.loc[compared["total_base"].isna(), "date"].iloc[0]
        raise ValueError(f"OKX tick archive is missing candle volume at {first}")
    candle_volume = compared["volume"].to_numpy(dtype=float)
    tick_volume = compared["total_base"].to_numpy(dtype=float)
    relative_error = np.abs(tick_volume - candle_volume) / np.maximum(
        np.abs(candle_volume), 1e-12
    )
    # OKX occasionally reconciles a tiny number of trades differently between
    # its official archive and OHLCV endpoint. Larger divergence is a bad file,
    # wrong contract value, or time-boundary error and must fail closed.
    valid = relative_error <= 0.001
    if not valid.all():
        row = compared.loc[~valid].iloc[0]
        raise ValueError(
            "OKX tick/candle volume mismatch at "
            f"{row['date']}: candle={row['volume']} ticks={row['total_base']}"
        )
    return {
        "candles_compared": len(compared),
        "maximum_relative_error": float(relative_error.max()),
        "mean_relative_error": float(relative_error.mean()),
    }


def fetch_open_interest(
    session: requests.Session,
    inst_id: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    rows: list[list[str]] = []
    cursor: int | None = None
    for _ in range(20):
        params = {"instId": inst_id, "period": "1Dutc", "limit": "100"}
        if cursor is not None:
            params["end"] = str(cursor)
        page = _okx_json(
            session,
            "/rubik/stat/contracts/open-interest-history",
            params,
        ).get("data", [])
        if not page:
            break
        rows.extend(page)
        oldest = min(int(row[0]) for row in page)
        if pd.to_datetime(oldest, unit="ms", utc=True) < start - pd.Timedelta(days=2):
            break
        cursor = oldest - 1
        time.sleep(0.5)
    frame = pd.DataFrame(
        rows,
        columns=["oi_source_time", "oi_contracts", "oi_ccy", "oi_usd"],
    ).drop_duplicates("oi_source_time")
    frame["oi_source_time"] = pd.to_datetime(
        pd.to_numeric(frame["oi_source_time"], errors="raise"), unit="ms", utc=True
    )
    frame["oi_usd"] = pd.to_numeric(frame["oi_usd"], errors="raise")
    frame["oi_available_time"] = frame["oi_source_time"] + pd.Timedelta(days=1)
    return frame.loc[
        frame["oi_available_time"].between(start, end, inclusive="left"),
        ["oi_source_time", "oi_available_time", "oi_usd"],
    ].sort_values("oi_available_time")


def attach_open_interest(sidecar: pd.DataFrame, oi: pd.DataFrame) -> pd.DataFrame:
    sidecar = sidecar.copy()
    oi = oi.copy()
    sidecar["date"] = sidecar["date"].astype("datetime64[ns, UTC]")
    for column in ("oi_source_time", "oi_available_time"):
        oi[column] = oi[column].astype("datetime64[ns, UTC]")
    result = pd.merge_asof(
        sidecar.sort_values("date"),
        oi.sort_values("oi_available_time"),
        left_on="date",
        right_on="oi_available_time",
        direction="backward",
    )
    contradiction = result["oi_source_time"].notna() & result["oi_source_time"].gt(
        result["date"]
    )
    if contradiction.any():
        raise ValueError("Open-interest evidence is newer than the decision candle")
    return result.drop(columns=["oi_available_time"])


def attach_funding(sidecar: pd.DataFrame, funding: pd.DataFrame) -> pd.DataFrame:
    result = sidecar.copy()
    evidence = funding.copy()
    result["source_complete_time"] = result["source_complete_time"].astype(
        "datetime64[ns, UTC]"
    )
    evidence["funding_source_time"] = evidence["funding_source_time"].astype(
        "datetime64[ns, UTC]"
    )
    evidence["funding_available_time"] = evidence["funding_source_time"] + pd.Timedelta(
        minutes=15
    )
    result = pd.merge_asof(
        result.sort_values("source_complete_time"),
        evidence.sort_values("funding_available_time"),
        left_on="source_complete_time",
        right_on="funding_available_time",
        direction="backward",
    )
    contradiction = result["funding_available_time"].notna() & result[
        "funding_available_time"
    ].gt(result["source_complete_time"])
    if contradiction.any():
        raise ValueError("Funding evidence is newer than the decision candle")
    return result.drop(columns=["funding_available_time"])


def _load_candles(
    candle_root: Path,
    freqtrade_name: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    path = candle_root / f"{freqtrade_name}-15m-futures.feather"
    frame = pd.read_feather(path)
    frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="raise")
    result = frame.loc[frame["date"].between(start, end, inclusive="left")].copy()
    if result.empty:
        raise ValueError(
            f"No local OKX 15m candles in {start}..{end} for {freqtrade_name}"
        )
    return result


def _load_funding(candle_root: Path, freqtrade_name: str) -> pd.DataFrame:
    path = candle_root / f"{freqtrade_name}-1h-funding_rate.feather"
    frame = pd.read_feather(path, columns=["date", "open"])
    frame["funding_source_time"] = pd.to_datetime(
        frame.pop("date"), utc=True, errors="raise"
    ).astype("datetime64[ns, UTC]")
    frame["funding_rate"] = pd.to_numeric(frame.pop("open"), errors="raise")
    return frame.sort_values("funding_source_time")


def prepare_pair(
    session: requests.Session,
    symbol: str,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    raw_root: Path,
    output_root: Path,
    candle_root: Path,
) -> dict[str, Any]:
    spec = PAIR_SPECS[symbol]
    contract_value = fetch_contract_value(session, spec["inst_id"])
    items = discover_daily_archives(session, spec["family"], start, end)
    archives = []
    for index, item in enumerate(items, start=1):
        print(f"download {symbol} {index}/{len(items)} {item['filename']}", flush=True)
        archives.append(download_archive(session, item, raw_root / symbol))
    five, price_volume = aggregate_archives(
        archives,
        contract_value=contract_value,
        start=start - pd.Timedelta(days=1),
        end=end,
    )
    fifteen = build_fifteen_minute(five)
    requested = fifteen["date"].between(start, end, inclusive="left")
    fifteen = fifteen.loc[requested].reset_index(drop=True)
    profiles = build_daily_profiles(price_volume)
    sidecar = attach_previous_day_profile(fifteen, profiles)
    oi = fetch_open_interest(session, spec["inst_id"], start, end)
    sidecar = attach_open_interest(sidecar, oi)
    funding = _load_funding(candle_root, spec["freqtrade_name"])
    sidecar = attach_funding(sidecar, funding)
    sidecar["minimum_oi_usd"] = spec["minimum_oi_usd"]
    sidecar["contract_value"] = contract_value
    candles = _load_candles(candle_root, spec["freqtrade_name"], start, end)
    volume_validation = validate_candle_volume(sidecar, candles)
    if sidecar["constituent_5m_count"].ne(3).any():
        first = sidecar.loc[sidecar["constituent_5m_count"].ne(3), "date"].iloc[0]
        raise ValueError(f"Incomplete 15m order-flow evidence at {first}")
    required = ["vp_poc", "vp_vah", "vp_val", "oi_usd", "funding_rate"]
    if sidecar[required].isna().any().any():
        missing = sidecar.loc[sidecar[required].isna().any(axis=1), "date"].iloc[0]
        raise ValueError(f"Missing causal profile/OI evidence at {missing}")
    derived = output_root / "derived"
    derived.mkdir(parents=True, exist_ok=True)
    output = derived / f"{symbol}-USDT-SWAP-15m-orderflow.feather"
    sidecar.reset_index(drop=True).to_feather(output)
    return {
        "symbol": symbol,
        "instrument": spec["inst_id"],
        "contract_value": contract_value,
        "minimum_oi_usd": spec["minimum_oi_usd"],
        "rows": len(sidecar),
        "start": sidecar["date"].min().isoformat(),
        "end": sidecar["date"].max().isoformat(),
        "output": str(output.relative_to(REPO_ROOT)),
        "output_sha256": _sha256(output),
        "volume_validation": volume_validation,
        "raw_archives": [
            {
                "filename": path.name,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in archives
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build causal BTC/ETH OKX aggressor-flow and prior-session profile sidecars."
    )
    parser.add_argument("--start", required=True, help="Inclusive UTC timestamp/date")
    parser.add_argument("--end", required=True, help="Exclusive UTC timestamp/date")
    parser.add_argument(
        "--symbols", nargs="+", choices=sorted(PAIR_SPECS), default=["BTC", "ETH"]
    )
    parser.add_argument("--proxy")
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--candle-root", type=Path, default=DEFAULT_CANDLE_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    start = _timestamp(args.start)
    end = _timestamp(args.end)
    if start >= end:
        raise ValueError("--start must be earlier than --end")
    session = requests.Session()
    session.headers["User-Agent"] = "freqtrade-cn-okx-orderflow-score/1"
    if args.proxy:
        session.proxies.update({"http": args.proxy, "https": args.proxy})
    summaries = [
        prepare_pair(
            session,
            symbol,
            start=start,
            end=end,
            raw_root=args.raw_root.expanduser().resolve(),
            output_root=args.output_root.expanduser().resolve(),
            candle_root=args.candle_root.expanduser().resolve(),
        )
        for symbol in args.symbols
    ]
    manifest = {
        "source": "OKX official daily trade archives, OKX OHLCV, and OKX Rubik OI",
        "start_inclusive": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "causality": {
            "orderflow": "15m source is usable only at that candle close",
            "volume_profile": "previous completed UTC day only",
            "open_interest": "daily OKX observation delayed by one UTC day",
            "funding": "raw settlement observation delayed by one 15m candle",
        },
        "not_available": [
            "historical best-bid/ask spread (requires a separate L2 archive pipeline)",
            "historical liquidation clusters",
        ],
        "pairs": summaries,
    }
    output_root = args.output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
