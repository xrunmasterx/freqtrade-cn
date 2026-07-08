from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = "ft_userdata/user_data/research_data/a_share_meta/calendar/trade_dates.csv"
CALENDAR_SOURCE = "akshare.tool_trade_date_hist_sina"
OPTIONAL_DEPENDENCY_ERROR = "Install optional dependency with `pip install -e .[research_ashare]`."


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

    dataframe = akshare.tool_trade_date_hist_sina()
    normalized = normalize_calendar(dataframe)
    output_path = REPO_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized.to_csv(output_path, index=False)
    print(f"ok: {output_path.relative_to(REPO_ROOT)} rows={len(normalized)}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download A-share trading calendar.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    return parser


def normalize_calendar(dataframe: pd.DataFrame) -> pd.DataFrame:
    date_column = _first_present_column(
        dataframe,
        (
            "trade_date",
            "date",
            "\u4ea4\u6613\u65e5\u671f",
        ),
    )
    normalized = pd.DataFrame()
    normalized["date"] = pd.to_datetime(dataframe[date_column]).dt.date.astype(str)
    normalized["is_open"] = 1
    normalized["source"] = CALENDAR_SOURCE
    return normalized.loc[:, ["date", "is_open", "source"]]


def _first_present_column(dataframe: pd.DataFrame, aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        if alias in dataframe.columns:
            return alias
    raise ValueError(f"Missing required column. Expected one of: {list(aliases)}")


if __name__ == "__main__":
    raise SystemExit(main())
