from __future__ import annotations

import argparse
import importlib
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = "ft_userdata/user_data/research_data/a_share_meta/status/daily_status.csv"
STATUS_SOURCE = "akshare.stock_zh_a_spot_em"
OPTIONAL_DEPENDENCY_ERROR = "Install optional dependency with `pip install -e .[research_ashare]`."
SHANGHAI = ZoneInfo("Asia/Shanghai")
STATUS_COLUMNS = [
    "date",
    "instrument",
    "suspended",
    "limit_up",
    "limit_down",
    "volume",
    "listed_date",
    "delisted_date",
    "source",
]


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    try:
        akshare = importlib.import_module("akshare")
    except ImportError:
        print(OPTIONAL_DEPENDENCY_ERROR, file=sys.stderr)
        return 2

    dataframe = akshare.stock_zh_a_spot_em()
    normalized = normalize_daily_status(dataframe)
    output_path = REPO_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized.to_csv(output_path, index=False)
    print(f"ok: {output_path.relative_to(REPO_ROOT)} rows={len(normalized)}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download A-share daily status snapshot.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    return parser


def normalize_daily_status(
    dataframe: pd.DataFrame,
    *,
    default_date: str | None = None,
) -> pd.DataFrame:
    normalized = pd.DataFrame()
    normalized["date"] = _normalize_date_column(dataframe, default_date=default_date)
    normalized["instrument"] = _get_required_column(
        dataframe,
        (
            "code",
            "symbol",
            "\u4ee3\u7801",
        ),
    ).map(normalize_instrument)
    normalized["suspended"] = _normalize_suspended_column(dataframe)
    normalized["limit_up"] = _get_optional_column(
        dataframe,
        (
            "limit_up",
            "upper_limit",
            "\u6da8\u505c",
        ),
    )
    normalized["limit_down"] = _get_optional_column(
        dataframe,
        (
            "limit_down",
            "lower_limit",
            "\u8dcc\u505c",
        ),
    )
    normalized["volume"] = pd.to_numeric(
        _get_optional_column(
            dataframe,
            (
                "volume",
                "\u6210\u4ea4\u91cf",
            ),
        ),
        errors="coerce",
    )
    normalized["listed_date"] = _normalize_optional_date_column(
        dataframe,
        (
            "listed_date",
            "list_date",
            "\u4e0a\u5e02\u65f6\u95f4",
        ),
    )
    normalized["delisted_date"] = _normalize_optional_date_column(
        dataframe,
        (
            "delisted_date",
            "de_listed_date",
            "\u9000\u5e02\u65f6\u95f4",
        ),
    )
    normalized["source"] = STATUS_SOURCE
    return normalized.loc[:, STATUS_COLUMNS]


def normalize_instrument(symbol: object) -> str:
    code = str(symbol).strip().upper()
    if "." in code:
        code = code.split(".", maxsplit=1)[0]
    code = code.zfill(6)
    suffix = "SH" if code.startswith(("5", "6", "9")) else "SZ"
    return f"{code}.{suffix}"


def _normalize_date_column(dataframe: pd.DataFrame, *, default_date: str | None) -> pd.Series:
    date_series = _get_optional_column(
        dataframe,
        (
            "date",
            "trade_date",
            "\u65e5\u671f",
        ),
    )
    if not date_series.isna().all():
        return pd.to_datetime(date_series, errors="coerce").dt.date.astype(str)

    fallback_date = default_date or datetime.now(SHANGHAI).date().isoformat()
    return pd.Series([fallback_date] * len(dataframe), index=dataframe.index, dtype="object")


def _normalize_suspended_column(dataframe: pd.DataFrame) -> pd.Series:
    suspended_series = _get_optional_column(
        dataframe,
        (
            "suspended",
            "halted",
            "\u505c\u724c",
        ),
    )
    if suspended_series.isna().all():
        return pd.Series([0] * len(dataframe), index=dataframe.index, dtype="int64")
    return pd.to_numeric(suspended_series, errors="coerce").fillna(0).astype(int)


def _normalize_optional_date_column(
    dataframe: pd.DataFrame,
    aliases: tuple[str, ...],
) -> pd.Series:
    column = _get_optional_column(dataframe, aliases)
    result = pd.Series([""] * len(dataframe), index=dataframe.index, dtype="object")
    present = column.notna() & (column.astype(str).str.strip() != "")
    if present.any():
        converted = pd.to_datetime(column.loc[present], errors="coerce")
        valid = converted.notna()
        result.loc[converted.index[valid]] = converted.loc[valid].dt.date.astype(str)
    return result


def _get_required_column(dataframe: pd.DataFrame, aliases: tuple[str, ...]) -> pd.Series:
    for alias in aliases:
        if alias in dataframe.columns:
            return dataframe[alias]
    raise ValueError(f"Missing required column. Expected one of: {list(aliases)}")


def _get_optional_column(dataframe: pd.DataFrame, aliases: tuple[str, ...]) -> pd.Series:
    for alias in aliases:
        if alias in dataframe.columns:
            return dataframe[alias]
    return pd.Series([pd.NA] * len(dataframe), index=dataframe.index)


if __name__ == "__main__":
    raise SystemExit(main())
