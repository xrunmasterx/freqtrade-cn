from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from tools.prepare_mtf_capital_regime_research_data import prepare


def _frame(start: str, periods: int, frequency: str) -> pd.DataFrame:
    values = pd.Series(range(periods), dtype=float) + 100.0
    return pd.DataFrame(
        {
            "date": pd.date_range(start, periods=periods, freq=frequency, tz="UTC"),
            "open": values,
            "high": values + 1,
            "low": values - 1,
            "close": values + 0.5,
            "volume": values,
        }
    )


def test_prepare_copies_mark_and_records_causal_side_data(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    pair = "BTC_USDT_USDT"
    _frame("2021-01-01", 48, "5min").to_feather(source / f"{pair}-5m-futures.feather")
    _frame("2021-01-01", 4, "1h").to_feather(source / f"{pair}-1h-funding_rate.feather")
    _frame("2021-01-01", 4, "1h").to_feather(source / f"{pair}-1h-mark.feather")
    (source / "leverage_tiers_USDT.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "output"

    manifest = prepare(source, output)

    mark_copy = output / "okx" / "futures" / f"{pair}-1h-mark.feather"
    assert mark_copy.is_file()
    assert manifest["schema_version"] == 2
    assert manifest["mark"]["rows"] == 4
    assert manifest["causal_side_data"]["funding_observation_age_cap_hours"] == 8
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8"))["mark"]["sha256"] == manifest["mark"]["sha256"]
