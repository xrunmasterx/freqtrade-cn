from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import time
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_DATA = (
    REPO_ROOT / "ft_userdata" / "runtime" / "freqtrade-futures" / "data"
)
OKX_API = "https://www.okx.com/api/v5"
OPTION_PATTERN = re.compile(
    r"^(?P<currency>BTC|ETH)-USD-(?P<expiry>\d{6})-"
    r"(?P<strike>\d+(?:\.\d+)?)-(?P<option_type>[CP])$"
)
STATISTICS = {
    "oi": (
        "/rubik/stat/contracts/open-interest-history",
        ["ts", "oi_contracts", "oi_ccy", "oi_usd"],
    ),
    "taker": (
        "/rubik/stat/taker-volume-contract",
        ["ts", "taker_sell_ccy", "taker_buy_ccy"],
    ),
    "top_account": (
        "/rubik/stat/contracts/long-short-account-ratio-contract-top-trader",
        ["ts", "top_account_ratio"],
    ),
    "top_position": (
        "/rubik/stat/contracts/long-short-position-ratio-contract-top-trader",
        ["ts", "top_position_ratio"],
    ),
    "contract_account": (
        "/rubik/stat/contracts/long-short-account-ratio-contract",
        ["ts", "contract_account_ratio"],
    ),
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare causal OKX derivative sidecars for PriceFlow research."
    )
    parser.add_argument("--start", default="2024-06-01")
    parser.add_argument("--end", default="2026-08-03")
    parser.add_argument("--proxy")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_RUNTIME_DATA)
    parser.add_argument("--skip-download", action="store_true")
    return parser


def _session(proxy: str | None) -> requests.Session:
    session = requests.Session()
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    session.headers["User-Agent"] = "freqtrade-cn-price-flow-research/1"
    return session


def _okx_json(
    session: requests.Session,
    path: str,
    params: dict[str, str],
) -> dict[str, Any]:
    for attempt in range(5):
        response = session.get(f"{OKX_API}{path}", params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") == "0":
            time.sleep(0.45)
            return payload
        if payload.get("code") != "50011" or attempt == 4:
            raise RuntimeError(
                f"OKX {path} failed: {payload.get('code')} {payload.get('msg')}"
            )
        time.sleep(1.0 + attempt)
    raise AssertionError("unreachable")


def _month_windows(start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    months = pd.period_range(start=start, end=end, freq="M")
    windows: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for offset in range(0, len(months), 20):
        chunk = months[offset : offset + 20]
        chunk_start = chunk[0].start_time.tz_localize("UTC")
        chunk_end = chunk[-1].end_time.floor("D").tz_localize("UTC")
        windows.append((chunk_start, chunk_end))
    return windows


def _discover_history_files(
    session: requests.Session,
    *,
    module: str,
    inst_type: str,
    family: str,
    aggregation: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[dict[str, str]]:
    payload = _okx_json(
        session,
        "/public/market-data-history",
        {
            "module": module,
            "instType": inst_type,
            "instFamilyList": family,
            "dateAggrType": aggregation,
            "begin": str(int(start.timestamp() * 1000)),
            "end": str(int(end.timestamp() * 1000)),
        },
    )
    files: list[dict[str, str]] = []
    for group in payload["data"][0].get("details", []):
        files.extend(group.get("groupDetails", []))
    return files


def _download_file(
    session: requests.Session,
    file_info: dict[str, str],
    destination: Path,
) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / file_info["filename"]
    if target.is_file() and target.stat().st_size > 0:
        return target

    temporary = target.with_suffix(f"{target.suffix}.part")
    with session.get(file_info["url"], stream=True, timeout=120) as response:
        response.raise_for_status()
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    os.replace(temporary, target)
    return target


def _download_option_history(
    session: requests.Session,
    raw_root: Path,
    family: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[Path]:
    complete_month_end = end.replace(day=1) - pd.Timedelta(days=1)
    files: list[dict[str, str]] = []
    if start <= complete_month_end:
        for window_start, window_end in _month_windows(start, complete_month_end):
            files.extend(
                _discover_history_files(
                    session,
                    module="1",
                    inst_type="OPTION",
                    family=family,
                    aggregation="monthly",
                    start=window_start,
                    end=window_end,
                )
            )
    partial_start = end.replace(day=1)
    if partial_start <= end:
        files.extend(
            _discover_history_files(
                session,
                module="1",
                inst_type="OPTION",
                family=family,
                aggregation="daily",
                start=partial_start,
                end=end,
            )
        )
    unique = {item["filename"]: item for item in files}
    return [
        _download_file(session, unique[name], raw_root / "options")
        for name in sorted(unique)
    ]


def _download_funding_history(
    session: requests.Session,
    raw_root: Path,
    family: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[Path]:
    complete_month_end = end.replace(day=1) - pd.Timedelta(days=1)
    files: list[dict[str, str]] = []
    for window_start, window_end in _month_windows(start, complete_month_end):
        files.extend(
            _discover_history_files(
                session,
                module="3",
                inst_type="SWAP",
                family=family,
                aggregation="monthly",
                start=window_start,
                end=window_end,
            )
        )
    unique = {item["filename"]: item for item in files}
    return [
        _download_file(session, unique[name], raw_root / "funding")
        for name in sorted(unique)
    ]


def _fetch_statistic(
    session: requests.Session,
    inst_id: str,
    path: str,
    columns: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    collected: list[list[str]] = []
    cursor: int | None = None
    for _ in range(20):
        params = {"instId": inst_id, "period": "1Dutc", "limit": "100"}
        if path.endswith("taker-volume-contract"):
            params["unit"] = "0"
        if cursor is not None:
            params["end"] = str(cursor)
        rows = _okx_json(session, path, params)["data"]
        if not rows:
            break
        collected.extend(rows)
        oldest = min(int(row[0]) for row in rows)
        if pd.to_datetime(oldest, unit="ms", utc=True) < start:
            break
        next_cursor = oldest - 1
        if cursor == next_cursor:
            break
        cursor = next_cursor

    frame = pd.DataFrame(collected, columns=columns).drop_duplicates("ts")
    timestamps = pd.to_numeric(frame.pop("ts"), errors="raise")
    frame["source_date"] = pd.to_datetime(timestamps, unit="ms", utc=True)
    for column in frame.columns:
        if column != "source_date":
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    mask = frame["source_date"].between(start, end, inclusive="both")
    return frame.loc[mask].sort_values("source_date").reset_index(drop=True)


def _fetch_statistics(
    session: requests.Session,
    inst_id: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    frames = []
    for path, columns in STATISTICS.values():
        frames.append(_fetch_statistic(session, inst_id, path, columns, start, end))
    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame, on="source_date", how="outer", validate="one_to_one")
    return merged.sort_values("source_date").reset_index(drop=True)


def _read_zip_csv(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"Expected one CSV in {path}, found {len(members)}")
        with archive.open(members[0]) as handle:
            return pd.read_csv(handle)


def _load_underlying(data_root: Path, currency: str) -> pd.DataFrame:
    path = data_root / "futures" / f"{currency}_USDT_USDT-15m-futures.feather"
    frame = pd.read_feather(path, columns=["date", "close"])
    frame["available_at"] = (
        pd.to_datetime(frame.pop("date"), utc=True) + pd.Timedelta(minutes=15)
    ).astype("datetime64[ns, UTC]")
    return frame.sort_values("available_at").reset_index(drop=True)


def _weighted_sum(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna() & weights.notna() & (weights > 0)
    if not valid.any():
        return math.nan
    return float((values[valid] * weights[valid]).sum())


def _aggregate_option_file(path: Path, underlying: pd.DataFrame) -> pd.DataFrame:
    frame = _read_zip_csv(path)
    expected = {"instrument_name", "side", "price", "size", "created_time"}
    if not expected.issubset(frame.columns):
        raise ValueError(f"Unexpected option columns in {path}: {list(frame.columns)}")

    parsed = frame["instrument_name"].str.extract(OPTION_PATTERN)
    frame = pd.concat([frame, parsed], axis=1)
    frame["trade_time"] = pd.to_datetime(
        frame["created_time"], unit="ms", utc=True
    ).astype("datetime64[ns, UTC]")
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    frame["size"] = pd.to_numeric(frame["size"], errors="coerce")
    frame["strike"] = pd.to_numeric(frame["strike"], errors="coerce")
    frame["expiry_time"] = pd.to_datetime(
        frame["expiry"], format="%y%m%d", utc=True, errors="coerce"
    ) + pd.Timedelta(hours=8)
    frame = frame.sort_values("trade_time").reset_index(drop=True)
    frame = pd.merge_asof(
        frame,
        underlying,
        left_on="trade_time",
        right_on="available_at",
        direction="backward",
        allow_exact_matches=False,
    )
    frame["dte"] = (frame["expiry_time"] - frame["trade_time"]).dt.total_seconds() / 86400
    frame["moneyness"] = frame["strike"] / frame["close"]
    valid = (
        frame["option_type"].notna()
        & frame["side"].isin(["buy", "sell"])
        & (frame["price"] > 0)
        & (frame["size"] > 0)
        & frame["dte"].between(1 / 24, 60)
        & frame["moneyness"].between(0.75, 1.25)
    )
    frame = frame.loc[valid].copy()
    if frame.empty:
        return pd.DataFrame()

    is_call = frame["option_type"].eq("C")
    is_buy = frame["side"].eq("buy")
    frame["flow_sign"] = np.where(is_call == is_buy, 1.0, -1.0)
    frame["premium_weight"] = frame["price"] * frame["size"]
    frame["is_otm"] = np.where(
        is_call,
        frame["moneyness"].between(1.0, 1.15),
        frame["moneyness"].between(0.85, 1.0),
    )
    frame["previous_price"] = frame.groupby("instrument_name")["price"].shift(1)
    frame["previous_time"] = frame.groupby("instrument_name")["trade_time"].shift(1)
    gap = (frame["trade_time"] - frame["previous_time"]).dt.total_seconds()
    frame["price_change"] = np.log(frame["price"] / frame["previous_price"]).clip(-2, 2)
    frame.loc[(gap <= 0) | (gap > 86400), "price_change"] = np.nan
    frame["directional_price_change"] = frame["price_change"] * np.where(is_call, 1, -1)
    frame["price_change_weight"] = np.sqrt(frame["size"])
    frame["source_date"] = frame["trade_time"].dt.floor("D")

    rows: list[dict[str, Any]] = []
    for source_date, group in frame.groupby("source_date", sort=True):
        call_volume = float(group.loc[group["option_type"].eq("C"), "size"].sum())
        put_volume = float(group.loc[group["option_type"].eq("P"), "size"].sum())
        otm = group.loc[group["is_otm"]]
        rows.append(
            {
                "source_date": source_date,
                "option_trade_count": len(group),
                "option_call_volume": call_volume,
                "option_put_volume": put_volume,
                "option_signed_size": float((group["flow_sign"] * group["size"]).sum()),
                "option_size_denominator": float(group["size"].sum()),
                "option_signed_premium": float(
                    (group["flow_sign"] * group["premium_weight"]).sum()
                ),
                "option_premium_denominator": float(group["premium_weight"].sum()),
                "option_otm_signed_size": float((otm["flow_sign"] * otm["size"]).sum()),
                "option_otm_size_denominator": float(otm["size"].sum()),
                "option_price_change_sum": _weighted_sum(
                    group["directional_price_change"], group["price_change_weight"]
                ),
                "option_price_change_weight": float(
                    group.loc[group["directional_price_change"].notna(), "price_change_weight"].sum()
                ),
            }
        )
    return pd.DataFrame(rows)


def _aggregate_options(paths: list[Path], underlying: pd.DataFrame) -> pd.DataFrame:
    chunks = []
    for path in paths:
        chunk = _aggregate_option_file(path, underlying)
        if not chunk.empty:
            chunks.append(chunk)
    if not chunks:
        return pd.DataFrame(columns=["source_date"])
    sums = pd.concat(chunks, ignore_index=True).groupby("source_date", as_index=False).sum()
    total_volume = sums["option_call_volume"] + sums["option_put_volume"]
    sums["option_contract_volume"] = total_volume
    sums["option_put_call_ratio"] = sums["option_put_volume"] / sums[
        "option_call_volume"
    ].replace(0, np.nan)
    sums["option_flow_size"] = sums["option_signed_size"] / sums[
        "option_size_denominator"
    ].replace(0, np.nan)
    sums["option_flow_premium"] = sums["option_signed_premium"] / sums[
        "option_premium_denominator"
    ].replace(0, np.nan)
    sums["option_otm_flow"] = sums["option_otm_signed_size"] / sums[
        "option_otm_size_denominator"
    ].replace(0, np.nan)
    sums["option_directional_price_change"] = sums["option_price_change_sum"] / sums[
        "option_price_change_weight"
    ].replace(0, np.nan)
    internal = [column for column in sums if "denominator" in column or column.endswith("_sum")]
    internal.extend(["option_signed_size", "option_signed_premium", "option_otm_signed_size"])
    return sums.drop(columns=internal)


def _aggregate_funding(paths: list[Path]) -> pd.DataFrame:
    chunks = []
    for path in paths:
        frame = _read_zip_csv(path)
        expected = {"funding_rate", "funding_time"}
        if not expected.issubset(frame.columns):
            raise ValueError(f"Unexpected funding columns in {path}: {list(frame.columns)}")
        frame["source_date"] = pd.to_datetime(
            frame["funding_time"], unit="ms", utc=True
        ).dt.floor("D")
        frame["funding_rate"] = pd.to_numeric(frame["funding_rate"], errors="coerce")
        chunks.append(frame[["source_date", "funding_rate"]])
    combined = pd.concat(chunks, ignore_index=True)
    return (
        combined.groupby("source_date", as_index=False)
        .agg(
            funding_daily_sum=("funding_rate", "sum"),
            funding_daily_mean=("funding_rate", "mean"),
            funding_daily_max_abs=("funding_rate", lambda values: values.abs().max()),
        )
        .sort_values("source_date")
    )


def _rolling_zscore(series: pd.Series, window: int = 90, minimum: int = 30) -> pd.Series:
    mean = series.rolling(window, min_periods=minimum).mean()
    deviation = series.rolling(window, min_periods=minimum).std(ddof=0).replace(0, np.nan)
    return (series - mean) / deviation


def _engineer_features(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.sort_values("source_date").reset_index(drop=True)
    frame["oi_change_1d"] = np.log(frame["oi_ccy"] / frame["oi_ccy"].shift(1))
    frame["oi_change_7d"] = np.log(frame["oi_ccy"] / frame["oi_ccy"].shift(7))
    taker_total = frame["taker_buy_ccy"] + frame["taker_sell_ccy"]
    frame["taker_imbalance"] = (
        (frame["taker_buy_ccy"] - frame["taker_sell_ccy"])
        / taker_total.replace(0, np.nan)
    )
    for ratio in ("top_account_ratio", "top_position_ratio", "contract_account_ratio"):
        log_column = ratio.replace("_ratio", "_log")
        change_column = ratio.replace("_ratio", "_change")
        frame[log_column] = np.log(frame[ratio].where(frame[ratio] > 0))
        frame[change_column] = frame[log_column].diff()
    frame["account_position_divergence"] = (
        frame["top_position_log"] - frame["top_account_log"]
    )
    frame["option_put_call_log"] = np.log(frame["option_put_call_ratio"])

    zscore_columns = [
        "oi_change_1d",
        "oi_change_7d",
        "taker_imbalance",
        "top_account_log",
        "top_position_log",
        "top_account_change",
        "top_position_change",
        "account_position_divergence",
        "contract_account_log",
        "funding_daily_sum",
        "option_contract_volume",
        "option_put_call_log",
        "option_flow_size",
        "option_flow_premium",
        "option_otm_flow",
        "option_directional_price_change",
    ]
    for column in zscore_columns:
        frame[f"{column}_z"] = _rolling_zscore(frame[column])

    frame["date"] = frame["source_date"] + pd.Timedelta(days=1)
    ordered = ["date", "source_date"] + [
        column for column in frame.columns if column not in {"date", "source_date"}
    ]
    return frame[ordered]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_currency(
    session: requests.Session,
    data_root: Path,
    currency: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    skip_download: bool,
) -> dict[str, Any]:
    derivative_root = data_root / "okx" / "derivatives"
    raw_root = derivative_root / "raw"
    option_pattern = f"{currency}-USD-optionchain-trades-*.zip"
    funding_pattern = f"{currency}-USDT-SWAP-fundingrates-*.zip"
    if skip_download:
        option_paths = sorted((raw_root / "options").glob(option_pattern))
        funding_paths = sorted((raw_root / "funding").glob(funding_pattern))
    else:
        option_paths = _download_option_history(
            session, raw_root, f"{currency}-USD", start, end
        )
        funding_paths = _download_funding_history(
            session, raw_root, f"{currency}-USDT", start, end
        )
    if not option_paths or not funding_paths:
        raise RuntimeError(f"Missing downloaded side data for {currency}")

    statistics_start = min(start, pd.Timestamp("2024-01-01", tz="UTC"))
    statistics = _fetch_statistics(
        session, f"{currency}-USDT-SWAP", statistics_start, end
    )
    underlying = _load_underlying(data_root, currency)
    options = _aggregate_options(option_paths, underlying)
    funding = _aggregate_funding(funding_paths)

    combined = statistics.merge(options, on="source_date", how="outer")
    combined = combined.merge(funding, on="source_date", how="outer")
    calendar = pd.DataFrame(
        {"source_date": pd.date_range(statistics_start, end, freq="D", tz="UTC")}
    )
    combined = calendar.merge(combined, on="source_date", how="left", validate="one_to_one")
    engineered = _engineer_features(combined)
    output = derivative_root / f"{currency}_USDT_USDT-1d-derivatives.feather"
    output.parent.mkdir(parents=True, exist_ok=True)
    engineered.to_feather(output)

    raw_paths = option_paths + funding_paths
    return {
        "currency": currency,
        "output": str(output.relative_to(REPO_ROOT)),
        "output_sha256": _sha256(output),
        "rows": len(engineered),
        "source_start": engineered["source_date"].min().isoformat(),
        "source_end": engineered["source_date"].max().isoformat(),
        "option_rows": int(engineered["option_trade_count"].notna().sum()),
        "statistics_rows": int(engineered["oi_ccy"].notna().sum()),
        "raw_files": [
            {
                "path": str(path.relative_to(REPO_ROOT)),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in raw_paths
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    if start > end:
        raise ValueError("--start must not be later than --end")

    data_root = args.data_root.expanduser().resolve()
    session = _session(args.proxy)
    summaries = [
        _prepare_currency(
            session,
            data_root,
            currency,
            start,
            end,
            args.skip_download,
        )
        for currency in ("BTC", "ETH")
    ]
    manifest = {
        "source": "OKX public API and official historical market data",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "availability_rule": (
            "Every UTC daily source row becomes usable at the next UTC day boundary; "
            "option moneyness uses the last strictly closed local 15m candle."
        ),
        "limitations": [
            "Long/short ratios describe accounts or top-trader positions, not total net market direction.",
            "Open interest has no directional sign.",
            "Option taker flow cannot distinguish opening, closing, spreads, or hedges.",
            "Historical feature files support offline research; no live updater is installed.",
        ],
        "currencies": summaries,
    }
    manifest_path = data_root / "okx" / "derivatives" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
