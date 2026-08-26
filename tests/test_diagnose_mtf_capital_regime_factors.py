from __future__ import annotations

import pandas as pd

from tools.diagnose_mtf_capital_regime_factors import _causal_merge


def _frame(start: str, periods: int, frequency: str, value: float = 1.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range(start, periods=periods, freq=frequency, tz="UTC"),
            "value": [value] * periods,
        }
    )


def test_causal_merge_exposes_only_closed_informative_rows() -> None:
    base = _frame("2024-01-01", 20, "15min")
    informative = _frame("2024-01-01", 4, "1h", value=10.0)
    merged = _causal_merge(base, informative, informative_minutes=60, prefix="mark")

    first = merged.loc[merged["date"] == pd.Timestamp("2024-01-01 00:45:00Z")].iloc[0]
    assert first["mark_source_date"] == pd.Timestamp("2024-01-01 00:00:00Z")
    assert (merged["mark_source_date"].dropna() <= merged.loc[merged["mark_source_date"].notna(), "date"]).all()


def test_future_informative_mutation_does_not_change_prior_prefix() -> None:
    base = _frame("2024-01-01", 20, "15min")
    informative = _frame("2024-01-01", 4, "1h", value=10.0)
    original = _causal_merge(base, informative, informative_minutes=60, prefix="regime")
    changed = informative.copy()
    changed.loc[changed["date"] == pd.Timestamp("2024-01-01 02:00:00Z"), "value"] = -99.0
    revised = _causal_merge(base, changed, informative_minutes=60, prefix="regime")
    before = original["date"] < pd.Timestamp("2024-01-01 02:45:00Z")
    pd.testing.assert_series_equal(
        original.loc[before, "regime_value"].reset_index(drop=True),
        revised.loc[before, "regime_value"].reset_index(drop=True),
    )
