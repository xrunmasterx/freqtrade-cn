# A-Share Phase 1 OHLCV Data Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first executable A-share data ingestion path: collect raw OHLCV, normalize it into local research CSV files, load those files through a `ResearchMarketDataSource` factory, and verify research chart/backtest behavior from local data.

**Architecture:** Keep A-share ingestion inside the research path. Provider code is isolated behind an adapter, the collector owns provider-to-canonical normalization and file writes, and research APIs read only normalized local files through a data source factory. The existing ccxt `Exchange`, crypto/futures downloader, trading `DataProvider`, and main backtesting engine are not touched.

**Tech Stack:** Python 3.11+, pandas, Pydantic v2, FastAPI, pytest, optional `akshare`, local CSV files, PowerShell.

**Execution note:** Code, tests, docs, and verification were completed without git commits because the workspace already contained unrelated and overlapping uncommitted changes.

---

## Assumptions

- Repository root for this plan is `G:\AI_Trading\freqtrade-cn`.
- Backend package root is `G:\AI_Trading\freqtrade-cn\freqtrade`.
- Existing research hardening is present: `ResearchConfigError`, `ResearchUnsupportedFeatureError`, A-share market rules, available research timeframes, and raw-only adjustment rejection already exist.
- Phase 1 implements raw OHLCV only. `qfq` and `hfq` requests continue to fail explicitly until a later adjustment-factor design is implemented.
- The first collector supports only daily `akshare.stock_zh_a_hist` period `1d`; `1w`, `1M`, and minute bars are rejected until later phases define their research semantics.
- Minute bars are rejected with a clear error in this plan because provider depth and A-share session semantics require separate validation.
- Backtest and chart requests never call `akshare` or any network provider. They read local normalized files only.
- `a-stock-data` remains an engineering reference and is not imported.
- The operational entry point for Phase 1 is a repository-local script under `tools/`, not a first-class `freqtrade` CLI subcommand. This avoids broad command-parser churn while proving the data path.

## Success Criteria

- `LocalCsvResearchDataSource` satisfies a `ResearchMarketDataSource` protocol.
- `api_research.py` and `research/chart.py` build data sources through a factory instead of directly constructing `LocalCsvResearchDataSource`.
- A collector can write `600519.SH-1d.csv` and `000001.SZ-1d.csv` from a fake provider in tests.
- Generated CSV files contain exactly the canonical reader columns in this order: `date,open,high,low,close,volume`.
- Provider rows with missing columns, invalid OHLC values, invalid instruments, unsupported timeframes, unsupported adjustments, and conflicting duplicate dates fail before corrupting existing files.
- A collector run writes a manifest under `.manifests` with source, files, row counts, date range, status, and warnings.
- `AkshareAshareOhlcvProvider` imports `akshare` lazily and produces a setup-oriented error when the optional package is missing.
- `tools/download_a_share_research_data.py` can run a collection against the configured research bot profile.
- Existing research chart and backtest tests still pass, and a smoke test proves collector output can be consumed by chart/backtest code without network access.

## File Structure

### Backend Package

- Modify: `freqtrade/freqtrade/research/data_source.py`
  - Add the `ResearchMarketDataSource` protocol and keep `LocalCsvResearchDataSource` as the local file implementation.
- Add: `freqtrade/freqtrade/research/data_source_factory.py`
  - Create configured research data sources from `ResearchBotProfile`.
- Modify: `freqtrade/freqtrade/research/chart.py`
  - Use `create_research_data_source(profile)` for OHLCV reads.
- Modify: `freqtrade/freqtrade/rpc/api_server/api_research.py`
  - Use `create_research_data_source(profile)` for instruments and backtests.
- Modify: `freqtrade/freqtrade/research/__init__.py`
  - Export the protocol and factory.
- Add: `freqtrade/freqtrade/research/collectors/__init__.py`
  - Package marker for research collectors.
- Add: `freqtrade/freqtrade/research/collectors/a_share_ohlcv.py`
  - A-share OHLCV request types, normalizer, validator, collector, atomic writer, and manifest writer.
- Add: `freqtrade/freqtrade/research/data_sources/__init__.py`
  - Package marker for provider adapters.
- Add: `freqtrade/freqtrade/research/data_sources/akshare_ashare.py`
  - Optional `akshare` adapter for `stock_zh_a_hist`.
- Modify: `freqtrade/pyproject.toml`
  - Add a research/A-share optional dependency extra containing `akshare`.

### Tooling And Docs

- Add: `tools/download_a_share_research_data.py`
  - Repository-local collector entry point for Phase 1.
- Add: `docs/a-share-research-data.md`
  - Operator-facing instructions for installing optional dependencies, running the collector, and verifying research chart/backtest output.

### Tests

- Add: `freqtrade/tests/research/test_data_source_factory.py`
- Add: `freqtrade/tests/research/test_a_share_ohlcv_collector.py`
- Add: `freqtrade/tests/research/test_akshare_ashare_data_source.py`
- Add: `freqtrade/tests/research/test_a_share_phase1_smoke.py`
- Modify: `freqtrade/tests/rpc/test_api_research.py`

---

## Task 1: Research Data Source Protocol And Factory

**Files:**
- Modify: `freqtrade/freqtrade/research/data_source.py`
- Add: `freqtrade/freqtrade/research/data_source_factory.py`
- Modify: `freqtrade/freqtrade/research/chart.py`
- Modify: `freqtrade/freqtrade/rpc/api_server/api_research.py`
- Modify: `freqtrade/freqtrade/research/__init__.py`
- Add: `freqtrade/tests/research/test_data_source_factory.py`
- Modify: `freqtrade/tests/rpc/test_api_research.py`

- [x] **Step 1: Write the failing factory tests**

Create `freqtrade/tests/research/test_data_source_factory.py`:

```python
import pytest

from freqtrade.markets import MarketType
from freqtrade.research import LocalCsvResearchDataSource
from freqtrade.research.data_source_factory import create_research_data_source
from freqtrade.research.exceptions import ResearchConfigError
from freqtrade.research.profiles import ResearchBotProfile, ResearchDataSourceConfig


def _profile(tmp_path, data_source_type: str = "local_csv") -> ResearchBotProfile:
    data_source = ResearchDataSourceConfig(type=data_source_type, root="research_data/a_share")
    return ResearchBotProfile(
        id="a-share-local",
        label="A Share Local",
        market=MarketType.A_SHARE,
        data_source=data_source,
        data_root=tmp_path / "research_data" / "a_share",
    )


def test_create_research_data_source_returns_local_csv_source(tmp_path) -> None:
    data_source = create_research_data_source(_profile(tmp_path))

    assert isinstance(data_source, LocalCsvResearchDataSource)
    assert data_source.root == tmp_path / "research_data" / "a_share"


def test_create_research_data_source_rejects_unsupported_source(tmp_path) -> None:
    profile = _profile(tmp_path)
    profile.data_source.type = "unknown"

    with pytest.raises(ResearchConfigError, match="Unsupported research data source: unknown"):
        create_research_data_source(profile)
```

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_data_source_factory.py -q
```

Expected: FAIL because `freqtrade.research.data_source_factory` does not exist.

- [x] **Step 2: Add the protocol**

In `freqtrade/freqtrade/research/data_source.py`, add:

```python
from typing import Protocol
```

Add above `LocalCsvResearchDataSource`:

```python
class ResearchMarketDataSource(Protocol):
    def list_instruments(self) -> list[Instrument]:
        ...

    def available_timeframes(self, instrument_key: str) -> list[str]:
        ...

    def load_ohlcv(
        self,
        instrument_key: str,
        timeframe: str,
        adjustment: str = "raw",
    ) -> pd.DataFrame:
        ...
```

Change `LocalCsvResearchDataSource.load_ohlcv` to accept `adjustment`:

```python
def load_ohlcv(
    self,
    instrument_key: str,
    timeframe: str,
    adjustment: str = "raw",
) -> pd.DataFrame:
    if adjustment != "raw":
        raise ValueError(f"Unsupported research adjustment: {adjustment}")
    instrument_key = _normalize_a_share_instrument_key(instrument_key)
    timeframe = _validate_timeframe(timeframe)
    path = self._resolve_ohlcv_path(instrument_key, timeframe)
```

Do not change the existing CSV filename behavior in this task.

- [x] **Step 3: Add the factory**

Create `freqtrade/freqtrade/research/data_source_factory.py`:

```python
from freqtrade.research.data_source import LocalCsvResearchDataSource, ResearchMarketDataSource
from freqtrade.research.exceptions import ResearchConfigError
from freqtrade.research.profiles import ResearchBotProfile


def create_research_data_source(profile: ResearchBotProfile) -> ResearchMarketDataSource:
    if profile.data_source.type == "local_csv":
        return LocalCsvResearchDataSource(profile.data_root)

    raise ResearchConfigError(f"Unsupported research data source: {profile.data_source.type}")
```

- [x] **Step 4: Export the factory and protocol**

Modify `freqtrade/freqtrade/research/__init__.py`:

```python
from freqtrade.research.data_source import LocalCsvResearchDataSource, ResearchMarketDataSource
from freqtrade.research.data_source_factory import create_research_data_source
from freqtrade.research.profiles import ResearchBotProfile, load_research_profiles


__all__ = [
    "LocalCsvResearchDataSource",
    "ResearchBotProfile",
    "ResearchMarketDataSource",
    "create_research_data_source",
    "load_research_profiles",
]
```

- [x] **Step 5: Use the factory in chart code**

In `freqtrade/freqtrade/research/chart.py`, replace:

```python
from freqtrade.research import LocalCsvResearchDataSource, ResearchBotProfile
```

with:

```python
from freqtrade.research import ResearchBotProfile, create_research_data_source
```

Replace the load block in `build_research_chart_candles_response`:

```python
data_source = create_research_data_source(profile)
dataframe = data_source.load_ohlcv(
    payload.instrument,
    payload.timeframe,
    adjustment=payload.adjustment,
)
```

- [x] **Step 6: Use the factory in research API**

In `freqtrade/freqtrade/rpc/api_server/api_research.py`, replace the import of `LocalCsvResearchDataSource` with `create_research_data_source`:

```python
from freqtrade.research import (
    ResearchBotProfile,
    create_research_data_source,
    load_research_profiles,
)
```

In `research_instruments`, replace:

```python
data_source = _get_local_csv_data_source(profile)
```

with:

```python
data_source = create_research_data_source(profile)
```

In `research_backtest`, replace:

```python
dataframe = _get_local_csv_data_source(profile).load_ohlcv(
    request.instrument,
    request.timeframe,
)
```

with:

```python
dataframe = create_research_data_source(profile).load_ohlcv(
    request.instrument,
    request.timeframe,
)
```

Remove `_get_local_csv_data_source`.

- [x] **Step 7: Update API mock paths if needed**

If `test_research_backtest_rejects_more_than_5000_rows_after_timerange` patches
`LocalCsvResearchDataSource.load_ohlcv`, update the patch path from:

```python
"freqtrade.rpc.api_server.api_research.LocalCsvResearchDataSource.load_ohlcv"
```

to:

```python
"freqtrade.research.data_source.LocalCsvResearchDataSource.load_ohlcv"
```

The factory still returns `LocalCsvResearchDataSource`, but `api_research.py` should no longer
import that concrete class.

Add this API regression test to `freqtrade/tests/rpc/test_api_research.py`:

```python
def test_research_instruments_uses_data_source_factory(research_client, mocker) -> None:
    factory = mocker.patch(
        "freqtrade.rpc.api_server.api_research.create_research_data_source",
        wraps=create_research_data_source,
    )

    response = client_get(
        research_client,
        f"{BASE_URI}/research/instruments?bot_id=a-share-local",
    )

    assert response.status_code == 200
    assert factory.call_count == 1
```

Add the missing import at the top of that test file:

```python
from freqtrade.research import create_research_data_source
```

- [x] **Step 8: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_data_source_factory.py tests/research/test_data_source.py tests/rpc/test_api_research.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit task**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
git add freqtrade/research/data_source.py freqtrade/research/data_source_factory.py freqtrade/research/chart.py freqtrade/rpc/api_server/api_research.py freqtrade/research/__init__.py tests/research/test_data_source_factory.py tests/rpc/test_api_research.py
git commit -m "feat: add research data source factory"
```

---

## Task 2: A-Share OHLCV Normalizer And Validator

**Files:**
- Add: `freqtrade/freqtrade/research/collectors/__init__.py`
- Add: `freqtrade/freqtrade/research/collectors/a_share_ohlcv.py`
- Add: `freqtrade/tests/research/test_a_share_ohlcv_collector.py`

- [x] **Step 1: Write failing normalizer tests**

Create `freqtrade/tests/research/test_a_share_ohlcv_collector.py`:

```python
import pandas as pd
import pytest

from freqtrade.research.collectors.a_share_ohlcv import (
    AShareOhlcvCollectionError,
    normalize_provider_ohlcv,
    provider_period_for_timeframe,
)


def test_provider_period_for_daily_timeframe() -> None:
    assert provider_period_for_timeframe("1d") == "daily"


@pytest.mark.parametrize("timeframe", ["5m", "1w", "1M"])
def test_provider_period_rejects_unsupported_timeframe(timeframe) -> None:
    with pytest.raises(
        AShareOhlcvCollectionError,
        match=f"Unsupported A-share OHLCV timeframe: {timeframe}",
    ):
        provider_period_for_timeframe(timeframe)


def test_normalize_provider_ohlcv_maps_provider_columns() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-07-06", "2026-07-05"],
            "open": [10.0, 9.0],
            "high": [11.0, 10.0],
            "low": [9.5, 8.5],
            "close": [10.5, 9.5],
            "volume": [1000, 900],
            "amount": [10500, 8550],
        }
    )

    dataframe, warnings = normalize_provider_ohlcv(raw)

    assert warnings == []
    assert list(dataframe.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert dataframe["date"].tolist() == ["2026-07-05", "2026-07-06"]
    assert dataframe["volume"].tolist() == [900.0, 1000.0]
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_a_share_ohlcv_collector.py::test_provider_period_for_daily_timeframes tests/research/test_a_share_ohlcv_collector.py::test_normalize_provider_ohlcv_maps_provider_columns -q
```

Expected: FAIL because the collector module does not exist.

- [x] **Step 2: Write failing validation tests**

Append to `freqtrade/tests/research/test_a_share_ohlcv_collector.py`:

```python
def test_normalize_provider_ohlcv_rejects_missing_columns() -> None:
    raw = pd.DataFrame({"date": ["2026-07-06"], "open": [10.0]})

    with pytest.raises(AShareOhlcvCollectionError, match="Missing provider OHLCV columns"):
        normalize_provider_ohlcv(raw)


def test_normalize_provider_ohlcv_rejects_invalid_ohlc_relationship() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-07-06"],
            "open": [10.0],
            "high": [9.0],
            "low": [8.0],
            "close": [10.5],
            "volume": [1000],
        }
    )

    with pytest.raises(AShareOhlcvCollectionError, match="Invalid OHLC relationship"):
        normalize_provider_ohlcv(raw)


def test_normalize_provider_ohlcv_deduplicates_identical_dates_with_warning() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-07-06", "2026-07-06"],
            "open": [10.0, 10.0],
            "high": [11.0, 11.0],
            "low": [9.5, 9.5],
            "close": [10.5, 10.5],
            "volume": [1000, 1000],
        }
    )

    dataframe, warnings = normalize_provider_ohlcv(raw)

    assert len(dataframe) == 1
    assert warnings == ["Dropped 1 identical duplicate OHLCV rows."]


def test_normalize_provider_ohlcv_rejects_conflicting_duplicate_dates() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-07-06", "2026-07-06"],
            "open": [10.0, 10.1],
            "high": [11.0, 11.0],
            "low": [9.5, 9.5],
            "close": [10.5, 10.5],
            "volume": [1000, 1000],
        }
    )

    with pytest.raises(AShareOhlcvCollectionError, match="Conflicting duplicate OHLCV dates"):
        normalize_provider_ohlcv(raw)
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_a_share_ohlcv_collector.py -q
```

Expected: FAIL until the module is implemented.

- [x] **Step 3: Add package marker**

Create `freqtrade/freqtrade/research/collectors/__init__.py`:

```python
"""Research data collectors."""
```

- [x] **Step 4: Implement normalizer and validator**

Create `freqtrade/freqtrade/research/collectors/a_share_ohlcv.py` with:

```python
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import pandas as pd

from freqtrade.markets import MarketType, parse_instrument_key


RESEARCH_OHLCV_COLUMNS = ["date", "open", "high", "low", "close", "volume"]
_PROVIDER_COLUMN_ALIASES = {
    "date": ("date", "\u65e5\u671f"),
    "open": ("open", "\u5f00\u76d8"),
    "high": ("high", "\u6700\u9ad8"),
    "low": ("low", "\u6700\u4f4e"),
    "close": ("close", "\u6536\u76d8"),
    "volume": ("volume", "\u6210\u4ea4\u91cf"),
}
_TIMEFRAME_TO_PROVIDER_PERIOD = {
    "1d": "daily",
}


class AShareOhlcvCollectionError(ValueError):
    pass


def provider_period_for_timeframe(timeframe: str) -> str:
    try:
        return _TIMEFRAME_TO_PROVIDER_PERIOD[timeframe]
    except KeyError:
        raise AShareOhlcvCollectionError(
            f"Unsupported A-share OHLCV timeframe: {timeframe}"
        ) from None


def normalize_provider_ohlcv(provider_dataframe: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    if provider_dataframe.empty:
        raise AShareOhlcvCollectionError("Provider returned empty OHLCV data.")

    column_map = _resolve_provider_columns(provider_dataframe)
    dataframe = provider_dataframe.loc[:, list(column_map)].rename(columns=column_map)
    dataframe = dataframe.loc[:, RESEARCH_OHLCV_COLUMNS].copy()
    dataframe["date"] = pd.to_datetime(dataframe["date"], errors="raise").dt.strftime("%Y-%m-%d")

    for column in ["open", "high", "low", "close", "volume"]:
        dataframe[column] = pd.to_numeric(dataframe[column], errors="raise").astype(float)

    warnings = _drop_identical_duplicate_dates(dataframe)
    _validate_ohlcv_rows(dataframe)
    dataframe = dataframe.sort_values("date").reset_index(drop=True)
    return dataframe, warnings


def _resolve_provider_columns(provider_dataframe: pd.DataFrame) -> dict[str, str]:
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for target_column, aliases in _PROVIDER_COLUMN_ALIASES.items():
        source_column = next(
            (alias for alias in aliases if alias in provider_dataframe.columns),
            None,
        )
        if source_column is None:
            missing.append(target_column)
            continue
        resolved[source_column] = target_column

    if missing:
        raise AShareOhlcvCollectionError(
            f"Missing provider OHLCV columns: {sorted(missing)}"
        )
    return resolved


def _drop_identical_duplicate_dates(dataframe: pd.DataFrame) -> list[str]:
    duplicated_dates = dataframe[dataframe.duplicated("date", keep=False)]
    if duplicated_dates.empty:
        return []

    for _, group in duplicated_dates.groupby("date"):
        unique_rows = group.loc[:, RESEARCH_OHLCV_COLUMNS].drop_duplicates()
        if len(unique_rows) > 1:
            raise AShareOhlcvCollectionError("Conflicting duplicate OHLCV dates.")

    before = len(dataframe)
    dataframe.drop_duplicates(subset=["date"], keep="first", inplace=True)
    dropped = before - len(dataframe)
    return [f"Dropped {dropped} identical duplicate OHLCV rows."] if dropped else []


def _validate_ohlcv_rows(dataframe: pd.DataFrame) -> None:
    for row in dataframe.itertuples(index=False):
        values = [
            float(row.open),
            float(row.high),
            float(row.low),
            float(row.close),
            float(row.volume),
        ]
        if not all(math.isfinite(value) for value in values):
            raise AShareOhlcvCollectionError("OHLCV values must be finite.")
        if min(row.open, row.high, row.low, row.close) <= 0:
            raise AShareOhlcvCollectionError("OHLC prices must be positive.")
        if row.volume < 0:
            raise AShareOhlcvCollectionError("OHLCV volume must be non-negative.")
        if (
            row.low > min(row.open, row.close)
            or row.high < max(row.open, row.close)
            or row.low > row.high
        ):
            raise AShareOhlcvCollectionError("Invalid OHLC relationship.")
```

- [x] **Step 5: Run normalizer tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_a_share_ohlcv_collector.py -q
```

Expected: PASS for the tests added so far.

- [ ] **Step 6: Commit task**

Run:

```powershell
git add freqtrade/research/collectors/__init__.py freqtrade/research/collectors/a_share_ohlcv.py tests/research/test_a_share_ohlcv_collector.py
git commit -m "feat: normalize a-share OHLCV data"
```

---

## Task 3: Collector File Writes And Manifest

**Files:**
- Modify: `freqtrade/freqtrade/research/collectors/a_share_ohlcv.py`
- Modify: `freqtrade/tests/research/test_a_share_ohlcv_collector.py`

- [x] **Step 1: Write failing collector write test**

Append to `freqtrade/tests/research/test_a_share_ohlcv_collector.py`:

```python
import json

from freqtrade.research.collectors.a_share_ohlcv import (
    AShareOhlcvCollector,
    AShareOhlcvRequest,
)


class FakeOhlcvProvider:
    provider_name = "fake"
    provider_version = "test"

    def fetch_ohlcv(
        self,
        instrument_key: str,
        timeframe: str,
        start_date: str | None,
        end_date: str | None,
        adjustment: str,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": ["2026-07-06", "2026-07-07"],
                "open": [10.0, 10.5],
                "high": [11.0, 11.5],
                "low": [9.5, 10.0],
                "close": [10.5, 11.0],
                "volume": [1000, 1200],
            }
        )


def test_collector_writes_normalized_csv_and_manifest(tmp_path) -> None:
    collector = AShareOhlcvCollector(root=tmp_path, provider=FakeOhlcvProvider())

    summary = collector.collect(
        AShareOhlcvRequest(
            instruments=["600519.SH", "000001.SZ"],
            timeframes=["1d"],
            start_date="20260701",
            end_date="20260731",
        )
    )

    assert summary.failed == 0
    assert summary.succeeded == 2
    csv_path = tmp_path / "600519.SH-1d.csv"
    assert csv_path.read_text(encoding="utf-8").splitlines()[0] == "date,open,high,low,close,volume"
    assert "2026-07-06,10.0,11.0,9.5,10.5,1000.0" in csv_path.read_text(encoding="utf-8")

    manifests = list((tmp_path / ".manifests").glob("*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["market"] == "a_share"
    assert manifest["provider"] == "fake"
    assert manifest["files"][0]["status"] == "ok"
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_a_share_ohlcv_collector.py::test_collector_writes_normalized_csv_and_manifest -q
```

Expected: FAIL because collector request and class do not exist.

- [x] **Step 2: Write failing safety tests**

Append:

```python
class EmptyProvider(FakeOhlcvProvider):
    def fetch_ohlcv(self, *args, **kwargs) -> pd.DataFrame:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])


def test_collector_does_not_overwrite_existing_file_on_empty_provider_data(tmp_path) -> None:
    existing = tmp_path / "600519.SH-1d.csv"
    existing.write_text("date,open,high,low,close,volume\n2026-01-01,1,1,1,1,1\n", encoding="utf-8")
    collector = AShareOhlcvCollector(root=tmp_path, provider=EmptyProvider())

    summary = collector.collect(AShareOhlcvRequest(instruments=["600519.SH"], timeframes=["1d"]))

    assert summary.failed == 1
    assert existing.read_text(encoding="utf-8") == "date,open,high,low,close,volume\n2026-01-01,1,1,1,1,1\n"


def test_collector_rejects_non_raw_adjustment(tmp_path) -> None:
    collector = AShareOhlcvCollector(root=tmp_path, provider=FakeOhlcvProvider())

    with pytest.raises(AShareOhlcvCollectionError, match="Unsupported A-share OHLCV adjustment: qfq"):
        collector.collect(AShareOhlcvRequest(instruments=["600519.SH"], timeframes=["1d"], adjustment="qfq"))
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_a_share_ohlcv_collector.py::test_collector_does_not_overwrite_existing_file_on_empty_provider_data tests/research/test_a_share_ohlcv_collector.py::test_collector_rejects_non_raw_adjustment -q
```

Expected: FAIL until collector is implemented.

- [x] **Step 3: Add request, summary, provider protocol, and collector**

Append these definitions to `freqtrade/freqtrade/research/collectors/a_share_ohlcv.py`:

```python
@dataclass(frozen=True)
class AShareOhlcvRequest:
    instruments: list[str]
    timeframes: list[str]
    start_date: str | None = None
    end_date: str | None = None
    adjustment: str = "raw"


@dataclass(frozen=True)
class AShareOhlcvFileSummary:
    path: str
    rows: int
    start: str | None
    stop: str | None
    status: str
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class AShareOhlcvRunSummary:
    run_id: str
    provider: str
    succeeded: int
    failed: int
    files: list[AShareOhlcvFileSummary]
    warnings: list[str]


class AShareOhlcvProvider(Protocol):
    provider_name: str
    provider_version: str

    def fetch_ohlcv(
        self,
        instrument_key: str,
        timeframe: str,
        start_date: str | None,
        end_date: str | None,
        adjustment: str,
    ) -> pd.DataFrame:
        ...


class AShareOhlcvCollector:
    def __init__(self, root: Path, provider: AShareOhlcvProvider) -> None:
        self.root = Path(root)
        self.provider = provider

    def collect(self, request: AShareOhlcvRequest) -> AShareOhlcvRunSummary:
        if request.adjustment != "raw":
            raise AShareOhlcvCollectionError(
                f"Unsupported A-share OHLCV adjustment: {request.adjustment}"
            )

        self.root.mkdir(parents=True, exist_ok=True)
        run_id = pd.Timestamp.utcnow().strftime("%Y%m%dT%H%M%SZ") + f"-{self.provider.provider_name}-a-share-ohlcv"
        file_summaries: list[AShareOhlcvFileSummary] = []
        run_warnings: list[str] = []

        for raw_instrument in request.instruments:
            instrument = parse_instrument_key(raw_instrument, market=MarketType.A_SHARE)
            for timeframe in request.timeframes:
                provider_period_for_timeframe(timeframe)
                file_summaries.append(
                    self._collect_one(instrument.key, timeframe, request)
                )

        succeeded = sum(1 for item in file_summaries if item.status == "ok")
        failed = sum(1 for item in file_summaries if item.status == "error")
        summary = AShareOhlcvRunSummary(
            run_id=run_id,
            provider=self.provider.provider_name,
            succeeded=succeeded,
            failed=failed,
            files=file_summaries,
            warnings=run_warnings,
        )
        self._write_manifest(summary, request)
        return summary

    def _collect_one(
        self,
        instrument_key: str,
        timeframe: str,
        request: AShareOhlcvRequest,
    ) -> AShareOhlcvFileSummary:
        target = self.root / f"{instrument_key}-{timeframe}.csv"
        try:
            provider_dataframe = self.provider.fetch_ohlcv(
                instrument_key=instrument_key,
                timeframe=timeframe,
                start_date=request.start_date,
                end_date=request.end_date,
                adjustment=request.adjustment,
            )
            dataframe, warnings = normalize_provider_ohlcv(provider_dataframe)
            _atomic_write_csv(dataframe, target)
            return AShareOhlcvFileSummary(
                path=target.name,
                rows=len(dataframe),
                start=str(dataframe.iloc[0]["date"]) if not dataframe.empty else None,
                stop=str(dataframe.iloc[-1]["date"]) if not dataframe.empty else None,
                status="ok",
                warnings=warnings,
            )
        except Exception as exc:
            return AShareOhlcvFileSummary(
                path=target.name,
                rows=0,
                start=None,
                stop=None,
                status="error",
                error=str(exc),
            )

    def _write_manifest(
        self,
        summary: AShareOhlcvRunSummary,
        request: AShareOhlcvRequest,
    ) -> None:
        import json

        manifest_dir = self.root / ".manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "run_id": summary.run_id,
            "market": "a_share",
            "provider": self.provider.provider_name,
            "provider_version": self.provider.provider_version,
            "created_at": pd.Timestamp.utcnow().isoformat(),
            "instruments": request.instruments,
            "timeframes": request.timeframes,
            "adjustment": request.adjustment,
            "timerange": _timerange_text(request.start_date, request.end_date),
            "files": [item.__dict__ for item in summary.files],
            "warnings": summary.warnings,
        }
        manifest_path = manifest_dir / f"{summary.run_id}.json"
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _atomic_write_csv(dataframe: pd.DataFrame, target: Path) -> None:
    temp_path = target.with_name(f".{target.name}.tmp")
    dataframe.loc[:, RESEARCH_OHLCV_COLUMNS].to_csv(temp_path, index=False)
    temp_path.replace(target)


def _timerange_text(start_date: str | None, end_date: str | None) -> str | None:
    if start_date is None and end_date is None:
        return None
    return f"{start_date or ''}-{end_date or ''}"
```

- [x] **Step 4: Run collector tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_a_share_ohlcv_collector.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit task**

Run:

```powershell
git add freqtrade/research/collectors/a_share_ohlcv.py tests/research/test_a_share_ohlcv_collector.py
git commit -m "feat: collect a-share OHLCV files"
```

---

## Task 4: Optional Akshare Provider Adapter

**Files:**
- Add: `freqtrade/freqtrade/research/data_sources/__init__.py`
- Add: `freqtrade/freqtrade/research/data_sources/akshare_ashare.py`
- Add: `freqtrade/tests/research/test_akshare_ashare_data_source.py`
- Modify: `freqtrade/pyproject.toml`

- [x] **Step 1: Write failing adapter tests**

Create `freqtrade/tests/research/test_akshare_ashare_data_source.py`:

```python
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from freqtrade.research.collectors.a_share_ohlcv import AShareOhlcvCollectionError
from freqtrade.research.data_sources.akshare_ashare import AkshareAshareOhlcvProvider


def test_akshare_provider_maps_instrument_and_timeframe(monkeypatch) -> None:
    calls = []

    def stock_zh_a_hist(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            {
                "date": ["2026-07-06"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.5],
                "close": [10.5],
                "volume": [1000],
            }
        )

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(stock_zh_a_hist=stock_zh_a_hist))

    provider = AkshareAshareOhlcvProvider()
    dataframe = provider.fetch_ohlcv("600519.SH", "1d", "20260701", "20260731", "raw")

    assert len(dataframe) == 1
    assert calls == [
        {
            "symbol": "600519",
            "period": "daily",
            "start_date": "20260701",
            "end_date": "20260731",
            "adjust": "",
        }
    ]


def test_akshare_provider_reports_missing_dependency(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "akshare", None)

    provider = AkshareAshareOhlcvProvider()

    with pytest.raises(AShareOhlcvCollectionError, match="Install optional dependency"):
        provider.fetch_ohlcv("600519.SH", "1d", None, None, "raw")
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_akshare_ashare_data_source.py -q
```

Expected: FAIL because the adapter package does not exist.

- [x] **Step 2: Add data source package marker**

Create `freqtrade/freqtrade/research/data_sources/__init__.py`:

```python
"""Research provider adapters."""
```

- [x] **Step 3: Implement the optional adapter**

Create `freqtrade/freqtrade/research/data_sources/akshare_ashare.py`:

```python
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version

import pandas as pd

from freqtrade.markets import MarketType, parse_instrument_key
from freqtrade.research.collectors.a_share_ohlcv import (
    AShareOhlcvCollectionError,
    provider_period_for_timeframe,
)


class AkshareAshareOhlcvProvider:
    provider_name = "akshare"

    @property
    def provider_version(self) -> str:
        try:
            return version("akshare")
        except PackageNotFoundError:
            return "not-installed"

    def fetch_ohlcv(
        self,
        instrument_key: str,
        timeframe: str,
        start_date: str | None,
        end_date: str | None,
        adjustment: str,
    ) -> pd.DataFrame:
        if adjustment != "raw":
            raise AShareOhlcvCollectionError(
                f"Unsupported A-share OHLCV adjustment: {adjustment}"
            )

        instrument = parse_instrument_key(instrument_key, market=MarketType.A_SHARE)
        period = provider_period_for_timeframe(timeframe)
        akshare = _import_akshare()
        return akshare.stock_zh_a_hist(
            symbol=instrument.symbol,
            period=period,
            start_date=start_date or "19700101",
            end_date=end_date or "22220101",
            adjust="",
        )


def _import_akshare():
    try:
        akshare = import_module("akshare")
    except ImportError as exc:
        raise AShareOhlcvCollectionError(
            "Install optional dependency with `pip install -e .[research_ashare]` before using the akshare A-share collector."
        ) from exc
    if akshare is None:
        raise AShareOhlcvCollectionError(
            "Install optional dependency with `pip install -e .[research_ashare]` before using the akshare A-share collector."
        )
    return akshare
```

- [x] **Step 4: Add optional dependency extra**

In `freqtrade/pyproject.toml`, add under `[project.optional-dependencies]`:

```toml
research_ashare = [
  "akshare",
]
```

Do not add `akshare` to the main `dependencies` array.

- [x] **Step 5: Run adapter tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_akshare_ashare_data_source.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit task**

Run:

```powershell
git add freqtrade/research/data_sources/__init__.py freqtrade/research/data_sources/akshare_ashare.py tests/research/test_akshare_ashare_data_source.py pyproject.toml
git commit -m "feat: add optional akshare a-share provider"
```

---

## Task 5: Repository-Local Collector Script

**Files:**
- Add: `tools/download_a_share_research_data.py`
- Add: `freqtrade/tests/research/test_a_share_phase1_smoke.py`

- [x] **Step 1: Write a smoke test around the collector output**

Create `freqtrade/tests/research/test_a_share_phase1_smoke.py`:

```python
import pandas as pd

from freqtrade.markets import MarketType
from freqtrade.research.backtesting import ResearchBacktestConfig, run_research_backtest
from freqtrade.research.chart import build_research_chart_candles_response
from freqtrade.research.collectors.a_share_ohlcv import (
    AShareOhlcvCollector,
    AShareOhlcvRequest,
)
from freqtrade.research.profiles import ResearchBotProfile, ResearchDataSourceConfig
from freqtrade.rpc.api_server.api_schemas import ResearchChartCandlesRequest


class FakeOhlcvProvider:
    provider_name = "fake"
    provider_version = "test"

    def fetch_ohlcv(self, *args, **kwargs) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": ["2026-07-06", "2026-07-07", "2026-07-08"],
                "open": [10.0, 10.5, 11.0],
                "high": [11.0, 11.5, 12.0],
                "low": [9.5, 10.0, 10.5],
                "close": [10.5, 11.0, 11.5],
                "volume": [1000, 1200, 1300],
            }
        )


def test_collector_output_feeds_research_chart_and_backtest(tmp_path) -> None:
    collector = AShareOhlcvCollector(root=tmp_path, provider=FakeOhlcvProvider())
    collector.collect(AShareOhlcvRequest(instruments=["600519.SH"], timeframes=["1d"]))
    profile = ResearchBotProfile(
        id="a-share-local",
        label="A Share Local",
        market=MarketType.A_SHARE,
        data_source=ResearchDataSourceConfig(type="local_csv", root="research_data/a_share"),
        data_root=tmp_path,
    )

    chart = build_research_chart_candles_response(
        profile,
        ResearchChartCandlesRequest(
            bot_id="a-share-local",
            instrument="600519.SH",
            timeframe="1d",
            limit=10,
        ),
    )
    assert chart["pair"] == "600519.SH"
    assert chart["length"] == 3

    dataframe = profile.data_root.joinpath("600519.SH-1d.csv")
    loaded = pd.read_csv(dataframe)
    loaded["date"] = pd.to_datetime(loaded["date"], utc=True)
    result = run_research_backtest(
        "600519.SH",
        loaded,
        ResearchBacktestConfig(initial_cash=100000, fast=1, slow=2),
    )
    assert result.metrics["initial_cash"] == 100000
    assert "return_ratio" in result.metrics
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_a_share_phase1_smoke.py -q
```

Expected: PASS after Tasks 1 to 4 are complete.

- [x] **Step 2: Add script argument parsing and config loading**

Create `tools/download_a_share_research_data.py`:

```python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FREQTRADE_ROOT = REPO_ROOT / "freqtrade"
sys.path.insert(0, str(FREQTRADE_ROOT))

from freqtrade.research.collectors.a_share_ohlcv import (
    AShareOhlcvCollectionError,
    AShareOhlcvCollector,
    AShareOhlcvRequest,
)
from freqtrade.research.data_sources.akshare_ashare import AkshareAshareOhlcvProvider
from freqtrade.research.profiles import load_research_profiles


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download A-share OHLCV into research CSV files.")
    parser.add_argument("--config", required=True, help="Path to a research config JSON file.")
    parser.add_argument("--bot-id", required=True, help="Research bot id from research_bots.")
    parser.add_argument("--instruments", nargs="+", required=True, help="A-share keys such as 600519.SH.")
    parser.add_argument("--timeframes", nargs="+", default=["1d"], help="Supported value: 1d.")
    parser.add_argument("--timerange", default=None, help="Timerange in YYYYMMDD-YYYYMMDD form.")
    parser.add_argument("--adjustment", default="raw", choices=["raw", "qfq", "hfq"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config.setdefault("user_data_dir", config_path.parent)
    profiles = {profile.id: profile for profile in load_research_profiles(config)}
    if args.bot_id not in profiles:
        print(f"Unknown research bot: {args.bot_id}", file=sys.stderr)
        return 2

    start_date, end_date = _parse_timerange(args.timerange)
    profile = profiles[args.bot_id]
    collector = AShareOhlcvCollector(
        root=profile.data_root,
        provider=AkshareAshareOhlcvProvider(),
    )
    try:
        summary = collector.collect(
            AShareOhlcvRequest(
                instruments=args.instruments,
                timeframes=args.timeframes,
                start_date=start_date,
                end_date=end_date,
                adjustment=args.adjustment,
            )
        )
    except AShareOhlcvCollectionError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    for item in summary.files:
        print(f"{item.status}: {item.path} rows={item.rows} error={item.error or ''}")
    return 1 if summary.failed else 0


def _parse_timerange(timerange: str | None) -> tuple[str | None, str | None]:
    if not timerange:
        return None, None
    start_date, separator, end_date = timerange.partition("-")
    if separator != "-":
        raise ValueError("Timerange must use YYYYMMDD-YYYYMMDD form.")
    return start_date or None, end_date or None


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 3: Run script help**

Run from `G:\AI_Trading\freqtrade-cn`:

```powershell
python tools/download_a_share_research_data.py --help
```

Expected: command prints usage and exits with code 0.

- [x] **Step 4: Run backend smoke tests**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_a_share_phase1_smoke.py tests/research/test_a_share_ohlcv_collector.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit task**

Run:

```powershell
git add ../tools/download_a_share_research_data.py tests/research/test_a_share_phase1_smoke.py
git commit -m "feat: add a-share research data download tool"
```

---

## Task 6: API Verification From Standardized Local Files

**Files:**
- Modify: `freqtrade/tests/rpc/test_api_research.py`

- [x] **Step 1: Add API test proving generated files are consumed**

Add to `freqtrade/tests/rpc/test_api_research.py`:

```python
def test_research_chart_and_backtest_consume_generated_a_share_csv(research_client, tmp_path) -> None:
    data_root = tmp_path / "research_data" / "a_share"
    (data_root / "000001.SZ-1d.csv").write_text(
        "date,open,high,low,close,volume\n"
        "2026-07-06,10.0,11.0,9.5,10.5,1000.0\n"
        "2026-07-07,10.5,11.5,10.0,11.0,1200.0\n"
        "2026-07-08,11.0,12.0,10.5,11.5,1300.0\n",
        encoding="utf-8",
    )

    chart_response = client_post(
        research_client,
        f"{BASE_URI}/research/chart_candles",
        data={
            "bot_id": "a-share-local",
            "instrument": "000001.SZ",
            "timeframe": "1d",
            "limit": 10,
        },
    )
    assert chart_response.status_code == 200
    assert chart_response.json()["pair"] == "000001.SZ"
    assert chart_response.json()["length"] == 3

    backtest_response = client_post(
        research_client,
        f"{BASE_URI}/research/backtest",
        data={
            "bot_id": "a-share-local",
            "instrument": "000001.SZ",
            "timeframe": "1d",
            "initial_cash": 100000,
            "strategy": {"type": "sma_cross", "fast": 1, "slow": 2},
        },
    )
    assert backtest_response.status_code == 200
    assert backtest_response.json()["metrics"]["initial_cash"] == 100000
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/rpc/test_api_research.py::test_research_chart_and_backtest_consume_generated_a_share_csv -q
```

Expected: PASS after Tasks 1 to 5 are complete.

- [x] **Step 2: Run full research API test file**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/rpc/test_api_research.py -q
```

Expected: PASS.

- [ ] **Step 3: Commit task**

Run:

```powershell
git add tests/rpc/test_api_research.py
git commit -m "test: verify generated a-share research data in api"
```

---

## Task 7: Operator Documentation

**Files:**
- Add: `docs/a-share-research-data.md`

- [x] **Step 1: Add collector usage document**

Create `docs/a-share-research-data.md`:

```markdown
# A-Share Research Data

This document describes the Phase 1 A-share OHLCV ingestion flow.

## Scope

Phase 1 downloads raw A-share OHLCV into local research CSV files and verifies those files through the Research chart and backtest APIs. It does not enable A-share live trading, dry-run trading, broker execution, funds flow, news, announcements, research reports, or AI document ingestion.

## Install Optional Provider Dependency

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
.\.venv\Scripts\python -m pip install -e .[research_ashare]
```

## Download Raw Daily OHLCV

Run from `G:\AI_Trading\freqtrade-cn`:

```powershell
python tools/download_a_share_research_data.py `
  --config ft_userdata/user_data/config.research.example.json `
  --bot-id a-share-local `
  --instruments 600519.SH 000001.SZ `
  --timeframes 1d `
  --timerange 20240101-20240701 `
  --adjustment raw
```

The collector writes files like:

```text
ft_userdata/user_data/research_data/a_share/600519.SH-1d.csv
ft_userdata/user_data/research_data/a_share/000001.SZ-1d.csv
ft_userdata/user_data/research_data/a_share/.manifests/{run_id}.json
```

## Verify Local Files

The expected CSV columns are:

```text
date,open,high,low,close,volume
```

Research chart and backtest read these local files through `local_csv`. They do not call akshare during API requests.

## Unsupported Inputs

Minute timeframes, `qfq`, and `hfq` are intentionally rejected in Phase 1. They require session-aware minute history and adjustment-factor support before they can be used for credible chart/backtest behavior.
```

- [x] **Step 2: Verify document wording**

Run:

```powershell
rg -n "live trading|dry-run|qfq|hfq|akshare" docs/a-share-research-data.md
```

Expected: output shows the scope and unsupported-input sections.

- [ ] **Step 3: Commit task**

Run:

```powershell
git add docs/a-share-research-data.md
git commit -m "docs: describe a-share research data ingestion"
```

---

## Full Verification

Run backend tests:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_data_source.py tests/research/test_data_source_factory.py tests/research/test_a_share_ohlcv_collector.py tests/research/test_akshare_ashare_data_source.py tests/research/test_a_share_phase1_smoke.py tests/rpc/test_api_research.py -q
```

Run lint for changed backend surfaces:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m ruff check freqtrade/research freqtrade/rpc/api_server/api_research.py tests/research tests/rpc/test_api_research.py
```

Run script help:

```powershell
cd G:\AI_Trading\freqtrade-cn
python tools/download_a_share_research_data.py --help
```

Run optional live provider smoke only when `akshare` is installed and network access is acceptable:

```powershell
cd G:\AI_Trading\freqtrade-cn
python tools/download_a_share_research_data.py `
  --config ft_userdata/user_data/config.research.example.json `
  --bot-id a-share-local `
  --instruments 600519.SH 000001.SZ `
  --timeframes 1d `
  --timerange 20240101-20240701 `
  --adjustment raw
```

Expected local files:

```text
G:\AI_Trading\freqtrade-cn\ft_userdata\user_data\research_data\a_share\600519.SH-1d.csv
G:\AI_Trading\freqtrade-cn\ft_userdata\user_data\research_data\a_share\000001.SZ-1d.csv
```

Manual research API/UI verification:

- Start the research webserver with `ft_userdata/user_data/config.research.example.json`.
- Call `/api/v1/research/instruments?bot_id=a-share-local` and confirm `600519.SH` and `000001.SZ` are listed after collection.
- Open the Research page and render `600519.SH` with timeframe `1d`.
- Run the SMA research backtest for `600519.SH`.
- Confirm no API request to chart/backtest imports or calls `akshare`.

## Execution Order

1. Task 1 first because chart/backtest must be decoupled from concrete data source construction before provider work lands.
2. Task 2 second because the collector needs a tested normalization and validation boundary.
3. Task 3 third because file writes and manifests create the local store that research APIs consume.
4. Task 4 fourth because the real provider adapter should plug into the tested collector boundary.
5. Task 5 fifth because the operator script should reuse the tested collector and adapter.
6. Task 6 sixth because API verification should run against generated local files.
7. Task 7 last because docs should reflect the actual command and final behavior.

## Out Of Scope For This Plan

- A-share live trading or dry-run trading.
- Broker, wallet, order, and force-entry/force-exit integration.
- Main `Exchange`, ccxt, crypto downloader, or main Freqtrade backtesting changes.
- Minute data ingestion.
- `qfq` and `hfq` chart/backtest support.
- Funds flow, news, announcements, financial statements, research reports, and AI document ingestion.
- Portfolio-level A-share backtesting.
- Historical universes, delisting metadata, and full corporate-action adjustment.
