# A-Share Phase 0 Closure And Phase 2 Market Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining Phase 0 research-hardening gaps, then implement the smallest credible Phase 2 A-share market-correctness layer for research chart/backtest.

**Architecture:** Keep A-share work inside the research-only path. Market correctness lives behind calendar/status/rules interfaces consumed by research backtests and later market-data queries; it does not touch `Exchange`, ccxt, wallets, orders, crypto/futures data download, or the main Freqtrade backtesting engine. Provider-specific details stay in collectors/adapters, while strategy/research code reads canonical local files and typed rule interfaces.

**Tech Stack:** Python 3.11+, pandas, Pydantic v2, FastAPI, pytest, optional `akshare`, local CSV/JSON manifests, PowerShell.

## Global Constraints

- Repository root is `G:\AI_Trading\freqtrade-cn`.
- Backend package root is `G:\AI_Trading\freqtrade-cn\freqtrade`.
- Current Phase 1 A-share OHLCV support is `1d + raw` only.
- Keep `qfq`, `hfq`, `1m`, `5m`, `1w`, and `1M` unsupported in chart/backtest until the corresponding phase explicitly enables them.
- Do not route A-share data through `freqtrade.exchange.Exchange`, ccxt, the main trading `DataProvider`, wallets, orders, or the main backtesting engine.
- Backtests and chart requests must read local canonical files only; they must not call `akshare`, Eastmoney, Tencent, Sina, mootdx, iwencai, or any network provider.
- OHLCV canonical columns remain exactly `date,open,high,low,close,volume` for Phase 2.
- Side-channel market correctness data must not be mixed into the OHLCV six-column CSV.
- Every new error returned by API/CLI must avoid leaking absolute local paths.
- Do not commit from a shared dirty worktree unless the user explicitly asks for commits. If executing this plan in an isolated worktree, commit at each task checkpoint.

---

## Current State

Completed enough to build on:

- Phase 1 OHLCV daily collector writes canonical CSV and manifest.
- `ResearchMarketDataSource` and `create_research_data_source(profile)` exist.
- `LocalCsvResearchDataSource` reads local canonical CSV.
- Research chart/backtest APIs consume local CSV.
- Browser verification has shown `600519.SH-1d.csv` real data through the Research UI.
- Existing `AShareMarketRules` covers lot size, commission, stamp tax, and a natural-date T+1 shape.
- Existing `AShareCalendar` covers weekday and intraday session shape, but not real exchange trading days.

Not complete yet:

- Chart/backtest responses do not expose data version/provenance from manifests.
- `AShareCalendar` does not load a real cached trading calendar or manual overrides.
- `AShareMarketRules` does not enforce suspended status, zero volume, limit-up/limit-down fill blocking, listing/delisting windows, or trading-day-based T+1.
- No canonical instrument daily status store exists.
- `raw/qfq/hfq` consistency is not implemented; Phase 2 should keep `qfq/hfq` rejected while introducing a later-phase adjustment-factor contract.

## File Structure

### New Backend Files

- Create: `freqtrade/freqtrade/research/provenance.py`
  - Parse collector manifests and expose local data provenance for a CSV file.
- Create: `freqtrade/freqtrade/markets/calendar_store.py`
  - Load cached A-share trading dates and manual closed-date overrides.
- Create: `freqtrade/freqtrade/markets/status_store.py`
  - Load per-instrument daily status rows used by backtest fill rules.

### Modified Backend Files

- Modify: `freqtrade/freqtrade/research/data_source.py`
  - Add provenance lookup to the local CSV data source.
- Modify: `freqtrade/freqtrade/research/chart.py`
  - Attach provenance metadata to chart response metadata.
- Modify: `freqtrade/freqtrade/research/backtesting.py`
  - Accept optional market context and apply calendar/status/rules checks.
- Modify: `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
  - Add response schema fields for research data provenance.
- Modify: `freqtrade/freqtrade/rpc/api_server/api_research.py`
  - Return new provenance fields and keep sanitized errors.
- Modify: `freqtrade/freqtrade/markets/calendar.py`
  - Add trading-day methods backed by cached store.
- Modify: `freqtrade/freqtrade/markets/rules.py`
  - Add rule checks for fill eligibility.
- Modify: `freqtrade/freqtrade/markets/__init__.py`
  - Export the new typed calendar/status/rules helpers.

### New Parent-Repo Tooling

- Create: `tools/download_a_share_market_calendar.py`
  - Seed/cache real A-share trading dates through optional provider code.
- Create: `tools/download_a_share_daily_status.py`
  - Seed/cache daily instrument status snapshots used by rules.

### New Tests

- Create: `freqtrade/tests/research/test_provenance.py`
- Create: `freqtrade/tests/markets/test_calendar_store.py`
- Create: `freqtrade/tests/markets/test_status_store.py`
- Modify: `freqtrade/tests/markets/test_rules.py`
- Modify: `freqtrade/tests/research/test_backtesting.py`
- Modify: `freqtrade/tests/rpc/test_api_research.py`
- Create: `freqtrade/tests/research/test_a_share_phase2_market_correctness.py`

### Docs

- Create: `docs/a-share-market-correctness.md`
- Modify: `docs/a-share-research-data.md`

---

## Task 1: Phase 0 Provenance Metadata From Collector Manifests

**Files:**
- Create: `freqtrade/freqtrade/research/provenance.py`
- Modify: `freqtrade/freqtrade/research/data_source.py`
- Modify: `freqtrade/freqtrade/research/chart.py`
- Modify: `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
- Modify: `freqtrade/tests/research/test_data_source.py`
- Create: `freqtrade/tests/research/test_provenance.py`
- Modify: `freqtrade/tests/rpc/test_api_research.py`

**Interfaces:**
- Produces:
  - `ResearchDataProvenance(BaseModel)`
  - `find_local_csv_provenance(root: Path, artifact_path: str) -> ResearchDataProvenance`
  - `ResearchMarketDataSource.get_ohlcv_provenance(instrument_key: str, timeframe: str, adjustment: str = "raw") -> ResearchDataProvenance`
- Consumes:
  - Existing collector manifest JSON shape under `.manifests`.

- [ ] **Step 1: Write manifest provenance tests**

Create `freqtrade/tests/research/test_provenance.py`:

```python
import json

from freqtrade.research.provenance import find_local_csv_provenance


def test_find_local_csv_provenance_uses_latest_ok_manifest(tmp_path) -> None:
    manifest_dir = tmp_path / ".manifests"
    manifest_dir.mkdir()
    (tmp_path / "600519.SH-1d.csv").write_text(
        "date,open,high,low,close,volume\n2024-01-02,1,1,1,1,1\n",
        encoding="utf-8",
    )
    (manifest_dir / "old.json").write_text(
        json.dumps(
            {
                "run_id": "old",
                "provider": "akshare",
                "provider_version": "1.0",
                "created_at": "2026-07-07T01:00:00+00:00",
                "adjustment": "raw",
                "timerange": {"start": "20240101", "end": "20240131"},
                "files": [
                    {
                        "path": "600519.SH-1d.csv",
                        "rows": 1,
                        "start": "2024-01-02",
                        "stop": "2024-01-02",
                        "status": "ok",
                        "warnings": [],
                        "error": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (manifest_dir / "new.json").write_text(
        json.dumps(
            {
                "run_id": "new",
                "provider": "akshare",
                "provider_version": "1.18.64",
                "created_at": "2026-07-07T02:00:00+00:00",
                "adjustment": "raw",
                "timerange": {"start": "20240101", "end": "20240701"},
                "files": [
                    {
                        "path": "600519.SH-1d.csv",
                        "rows": 118,
                        "start": "2024-01-02",
                        "stop": "2024-07-01",
                        "status": "ok",
                        "warnings": [],
                        "error": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    provenance = find_local_csv_provenance(tmp_path, "600519.SH-1d.csv")

    assert provenance.source_type == "local_csv"
    assert provenance.artifact_path == "600519.SH-1d.csv"
    assert provenance.manifest_run_id == "new"
    assert provenance.provider == "akshare"
    assert provenance.provider_version == "1.18.64"
    assert provenance.rows == 118
    assert provenance.start == "2024-01-02"
    assert provenance.stop == "2024-07-01"
    assert provenance.adjustment == "raw"


def test_find_local_csv_provenance_falls_back_without_manifest(tmp_path) -> None:
    (tmp_path / "600519.SH-1d.csv").write_text(
        "date,open,high,low,close,volume\n2024-01-02,1,1,1,1,1\n",
        encoding="utf-8",
    )

    provenance = find_local_csv_provenance(tmp_path, "600519.SH-1d.csv")

    assert provenance.source_type == "local_csv"
    assert provenance.artifact_path == "600519.SH-1d.csv"
    assert provenance.manifest_run_id is None
    assert provenance.provider is None
```

- [ ] **Step 2: Run provenance tests and confirm failure**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_provenance.py -q
```

Expected: FAIL because `freqtrade.research.provenance` does not exist.

- [ ] **Step 3: Implement provenance model and manifest lookup**

Create `freqtrade/freqtrade/research/provenance.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class ResearchDataProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_type: str = "local_csv"
    artifact_path: str
    manifest_run_id: str | None = None
    manifest_path: str | None = None
    provider: str | None = None
    provider_version: str | None = None
    rows: int | None = None
    start: str | None = None
    stop: str | None = None
    adjustment: str | None = None
    created_at: str | None = None
    warnings: list[str] = []


def find_local_csv_provenance(root: Path, artifact_path: str) -> ResearchDataProvenance:
    manifest_dir = root / ".manifests"
    best: tuple[str, Path, dict] | None = None
    if manifest_dir.is_dir():
        for path in manifest_dir.glob("*.json"):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            created_at = str(manifest.get("created_at", ""))
            for file_summary in manifest.get("files", []):
                if (
                    file_summary.get("path") == artifact_path
                    and file_summary.get("status") == "ok"
                ):
                    candidate = (created_at, path, manifest)
                    if best is None or candidate[0] > best[0]:
                        best = candidate

    if best is None:
        return ResearchDataProvenance(artifact_path=artifact_path)

    _, path, manifest = best
    file_summary = next(
        item for item in manifest["files"] if item.get("path") == artifact_path
    )
    return ResearchDataProvenance(
        artifact_path=artifact_path,
        manifest_run_id=manifest.get("run_id"),
        manifest_path=str(path.relative_to(root)),
        provider=manifest.get("provider"),
        provider_version=manifest.get("provider_version"),
        rows=file_summary.get("rows"),
        start=file_summary.get("start"),
        stop=file_summary.get("stop"),
        adjustment=manifest.get("adjustment"),
        created_at=manifest.get("created_at"),
        warnings=file_summary.get("warnings") or [],
    )
```

- [ ] **Step 4: Expose provenance on data source**

Modify `freqtrade/freqtrade/research/data_source.py`:

```python
from freqtrade.research.provenance import ResearchDataProvenance, find_local_csv_provenance
```

Extend `ResearchMarketDataSource`:

```python
def get_ohlcv_provenance(
    self,
    instrument_key: str,
    timeframe: str,
    adjustment: str = "raw",
) -> ResearchDataProvenance:
    ...
```

Add to `LocalCsvResearchDataSource`:

```python
def get_ohlcv_provenance(
    self,
    instrument_key: str,
    timeframe: str,
    adjustment: str = "raw",
) -> ResearchDataProvenance:
    if adjustment != "raw":
        raise ValueError(f"Unsupported research adjustment: {adjustment}")
    instrument_key = _normalize_a_share_instrument_key(instrument_key)
    timeframe = _validate_timeframe(timeframe)
    path = self._resolve_ohlcv_path(instrument_key, timeframe)
    artifact_path = path.name
    return find_local_csv_provenance(self.root, artifact_path)
```

- [ ] **Step 5: Add API schema fields**

Modify `ChartResponseMeta` in `freqtrade/freqtrade/rpc/api_server/api_schemas.py`:

```python
class ChartResponseMeta(BaseModel):
    schema_version: int = 1
    window: ChartWindowMeta
    layers: list[ChartLayerMeta] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    data_provenance: dict[str, Any] | None = None
```

Modify `ResearchBacktestResult` in `freqtrade/freqtrade/research/backtesting.py`:

```python
data_provenance: dict[str, Any] | None = None
```

- [ ] **Step 6: Attach provenance to chart and backtest responses**

In `freqtrade/freqtrade/research/chart.py`, build the data source once:

```python
data_source = create_research_data_source(profile)
dataframe = data_source.load_ohlcv(
    payload.instrument,
    payload.timeframe,
    payload.adjustment,
)
provenance = data_source.get_ohlcv_provenance(
    payload.instrument,
    payload.timeframe,
    payload.adjustment,
)
```

Pass `data_provenance=provenance.model_dump()` into `ChartResponseMeta`.

In `freqtrade/freqtrade/rpc/api_server/api_research.py`, get provenance before running backtest:

```python
data_source = create_research_data_source(profile)
dataframe = data_source.load_ohlcv(request.instrument, request.timeframe)
provenance = data_source.get_ohlcv_provenance(request.instrument, request.timeframe)
```

After `run_research_backtest(...)`:

```python
result.data_provenance = provenance.model_dump()
```

- [ ] **Step 7: Add API tests**

Append to `freqtrade/tests/rpc/test_api_research.py`:

```python
def test_research_chart_returns_data_provenance(research_client) -> None:
    response = client_post(
        research_client,
        f"{BASE_URI}/research/chart_candles",
        data={
            "bot_id": "a-share-local",
            "instrument": "600519.SH",
            "timeframe": "1d",
            "limit": 10,
        },
    )

    assert response.status_code == 200
    provenance = response.json()["meta"]["data_provenance"]
    assert provenance["source_type"] == "local_csv"
    assert provenance["artifact_path"] == "600519.SH-1d.csv"


def test_research_backtest_returns_data_provenance(research_client) -> None:
    response = client_post(
        research_client,
        f"{BASE_URI}/research/backtest",
        data={
            "bot_id": "a-share-local",
            "instrument": "600519.SH",
            "timeframe": "1d",
            "initial_cash": 100000,
            "strategy": {
                "type": "sma_cross",
                "fast": 1,
                "slow": 2,
            },
        },
    )

    assert response.status_code == 200
    provenance = response.json()["data_provenance"]
    assert provenance["source_type"] == "local_csv"
    assert provenance["artifact_path"] == "600519.SH-1d.csv"
```

- [ ] **Step 8: Run focused tests**

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_provenance.py tests/research/test_data_source.py tests/research/test_chart.py tests/rpc/test_api_research.py -q
```

Expected: PASS.

- [ ] **Step 9: Checkpoint**

If executing in an isolated clean worktree:

```powershell
git add freqtrade/research/provenance.py freqtrade/research/data_source.py freqtrade/research/chart.py freqtrade/rpc/api_server/api_schemas.py freqtrade/research/backtesting.py tests/research/test_provenance.py tests/research/test_data_source.py tests/research/test_chart.py tests/rpc/test_api_research.py
git commit -m "feat: expose research data provenance"
```

In the current shared dirty worktree, do not commit unless explicitly requested.

---

## Task 2: Cached A-Share Trading Calendar And Overrides

**Files:**
- Create: `freqtrade/freqtrade/markets/calendar_store.py`
- Modify: `freqtrade/freqtrade/markets/calendar.py`
- Modify: `freqtrade/freqtrade/markets/__init__.py`
- Create: `freqtrade/tests/markets/test_calendar_store.py`
- Modify: `freqtrade/tests/markets/test_rules.py`

**Interfaces:**
- Produces:
  - `CachedAShareCalendar.from_csv(path: Path, override_closed_dates: set[str] | None = None) -> CachedAShareCalendar`
  - `CachedAShareCalendar.is_trading_day(value: date | datetime | str) -> bool`
  - `CachedAShareCalendar.next_trading_day(value: date | datetime | str) -> date`
  - `AShareCalendar.is_trading_day(...)`
- Consumes:
  - CSV columns: `date,is_open,source`

- [ ] **Step 1: Write failing calendar tests**

Create `freqtrade/tests/markets/test_calendar_store.py`:

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from freqtrade.markets.calendar_store import CachedAShareCalendar


def test_cached_calendar_reads_trading_days_and_closed_overrides(tmp_path) -> None:
    path = tmp_path / "a_share_trade_dates.csv"
    path.write_text(
        "date,is_open,source\n"
        "2024-02-08,1,sina\n"
        "2024-02-09,1,sina\n"
        "2024-02-10,0,sina\n"
        "2024-02-19,1,sina\n",
        encoding="utf-8",
    )

    calendar = CachedAShareCalendar.from_csv(path, override_closed_dates={"2024-02-09"})

    assert calendar.is_trading_day("2024-02-08") is True
    assert calendar.is_trading_day("2024-02-09") is False
    assert calendar.is_trading_day("2024-02-10") is False
    assert calendar.next_trading_day("2024-02-08") == date(2024, 2, 19)


def test_cached_calendar_accepts_timezone_aware_datetime(tmp_path) -> None:
    path = tmp_path / "a_share_trade_dates.csv"
    path.write_text("date,is_open,source\n2024-01-02,1,sina\n", encoding="utf-8")
    calendar = CachedAShareCalendar.from_csv(path)

    assert calendar.is_trading_day(
        datetime(2024, 1, 2, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    )


def test_cached_calendar_rejects_next_day_when_no_future_session(tmp_path) -> None:
    path = tmp_path / "a_share_trade_dates.csv"
    path.write_text("date,is_open,source\n2024-01-02,1,sina\n", encoding="utf-8")
    calendar = CachedAShareCalendar.from_csv(path)

    with pytest.raises(ValueError, match="No next A-share trading day after 2024-01-02"):
        calendar.next_trading_day("2024-01-02")
```

- [ ] **Step 2: Run failing tests**

```powershell
.\.venv\Scripts\python -m pytest tests/markets/test_calendar_store.py -q
```

Expected: FAIL because `calendar_store.py` does not exist.

- [ ] **Step 3: Implement cached calendar**

Create `freqtrade/freqtrade/markets/calendar_store.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


_ASIA_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class CachedAShareCalendar:
    open_dates: frozenset[date]
    known_dates: frozenset[date]

    @classmethod
    def from_csv(
        cls,
        path: Path,
        override_closed_dates: set[str] | None = None,
    ) -> "CachedAShareCalendar":
        dataframe = pd.read_csv(path)
        required = {"date", "is_open", "source"}
        missing = required - set(dataframe.columns)
        if missing:
            raise ValueError(f"Missing A-share calendar columns: {sorted(missing)}")
        dataframe["date"] = pd.to_datetime(dataframe["date"]).dt.date
        known_dates = set(dataframe["date"])
        open_dates = set(dataframe.loc[dataframe["is_open"].astype(int) == 1, "date"])
        for closed_date in override_closed_dates or set():
            open_dates.discard(pd.Timestamp(closed_date).date())
            known_dates.add(pd.Timestamp(closed_date).date())
        return cls(frozenset(open_dates), frozenset(known_dates))

    def is_trading_day(self, value: date | datetime | str) -> bool:
        return _to_date(value) in self.open_dates

    def next_trading_day(self, value: date | datetime | str) -> date:
        current = _to_date(value)
        future_open_dates = sorted(day for day in self.open_dates if day > current)
        if not future_open_dates:
            raise ValueError(f"No next A-share trading day after {current.isoformat()}")
        return future_open_dates[0]


def _to_date(value: date | datetime | str) -> date:
    timestamp = pd.Timestamp(value)
    if isinstance(value, datetime) and timestamp.tzinfo is not None:
        return timestamp.tz_convert(_ASIA_SHANGHAI).date()
    return timestamp.date()
```

- [ ] **Step 4: Integrate with existing AShareCalendar**

Modify `freqtrade/freqtrade/markets/calendar.py`:

```python
from freqtrade.markets.calendar_store import CachedAShareCalendar
```

Change constructor:

```python
def __init__(
    self,
    closed_dates: set[str] | None = None,
    cached_calendar: CachedAShareCalendar | None = None,
) -> None:
    self.closed_dates = closed_dates or set()
    self.cached_calendar = cached_calendar
```

Add:

```python
def is_trading_day(self, value: datetime | str) -> bool:
    if self.cached_calendar is not None:
        return self.cached_calendar.is_trading_day(value)
    timestamp = pd.Timestamp(value)
    local_dt = timestamp.tz_convert(_ASIA_SHANGHAI) if timestamp.tzinfo else timestamp
    return local_dt.weekday() < 5 and local_dt.date().isoformat() not in self.closed_dates

def next_trading_day(self, value: datetime | str):
    if self.cached_calendar is not None:
        return self.cached_calendar.next_trading_day(value)
    timestamp = pd.Timestamp(value)
    candidate = timestamp.date()
    while True:
        candidate = candidate + timedelta(days=1)
        if self.is_trading_day(str(candidate)):
            return candidate
```

Keep `is_session_open()` behavior, but call `is_trading_day(local_dt)` before checking intraday time.

- [ ] **Step 5: Export and run tests**

Modify `freqtrade/freqtrade/markets/__init__.py`:

```python
from freqtrade.markets.calendar_store import CachedAShareCalendar
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/markets/test_calendar_store.py tests/markets/test_rules.py -q
```

Expected: PASS.

- [ ] **Step 6: Checkpoint**

Commit only in an isolated clean worktree:

```powershell
git add freqtrade/markets/calendar_store.py freqtrade/markets/calendar.py freqtrade/markets/__init__.py tests/markets/test_calendar_store.py tests/markets/test_rules.py
git commit -m "feat: add cached a-share trading calendar"
```

---

## Task 3: Instrument Daily Status Store For Suspended, Limit, And Listing State

**Files:**
- Create: `freqtrade/freqtrade/markets/status_store.py`
- Modify: `freqtrade/freqtrade/markets/__init__.py`
- Create: `freqtrade/tests/markets/test_status_store.py`

**Interfaces:**
- Produces:
  - `AShareDailyStatus(BaseModel)`
  - `AShareStatusStore.from_csv(path: Path) -> AShareStatusStore`
  - `AShareStatusStore.get_status(instrument_key: str, value: date | datetime | str) -> AShareDailyStatus | None`
- Consumes:
  - CSV columns: `date,instrument,suspended,limit_up,limit_down,volume,listed_date,delisted_date,source`

- [ ] **Step 1: Write failing status tests**

Create `freqtrade/tests/markets/test_status_store.py`:

```python
from freqtrade.markets.status_store import AShareStatusStore


def test_status_store_reads_daily_status(tmp_path) -> None:
    path = tmp_path / "a_share_daily_status.csv"
    path.write_text(
        "date,instrument,suspended,limit_up,limit_down,volume,listed_date,delisted_date,source\n"
        "2024-01-02,600519.SH,0,1853.51,1516.51,32156,2001-08-27,,snapshot\n",
        encoding="utf-8",
    )

    store = AShareStatusStore.from_csv(path)
    status = store.get_status("600519.SH", "2024-01-02")

    assert status is not None
    assert status.instrument == "600519.SH"
    assert status.suspended is False
    assert status.limit_up == 1853.51
    assert status.limit_down == 1516.51
    assert status.volume == 32156
    assert status.listed_date == "2001-08-27"
    assert status.delisted_date is None


def test_status_store_returns_none_for_missing_row(tmp_path) -> None:
    path = tmp_path / "a_share_daily_status.csv"
    path.write_text(
        "date,instrument,suspended,limit_up,limit_down,volume,listed_date,delisted_date,source\n",
        encoding="utf-8",
    )

    store = AShareStatusStore.from_csv(path)

    assert store.get_status("600519.SH", "2024-01-02") is None
```

- [ ] **Step 2: Run failing tests**

```powershell
.\.venv\Scripts\python -m pytest tests/markets/test_status_store.py -q
```

Expected: FAIL because `status_store.py` does not exist.

- [ ] **Step 3: Implement status store**

Create `freqtrade/freqtrade/markets/status_store.py`:

```python
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict

from freqtrade.markets import MarketType, parse_instrument_key


class AShareDailyStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: str
    instrument: str
    suspended: bool
    limit_up: float | None
    limit_down: float | None
    volume: float | None
    listed_date: str | None
    delisted_date: str | None
    source: str


class AShareStatusStore:
    def __init__(self, statuses: dict[tuple[str, str], AShareDailyStatus]) -> None:
        self._statuses = statuses

    @classmethod
    def from_csv(cls, path: Path) -> "AShareStatusStore":
        dataframe = pd.read_csv(path)
        required = {
            "date",
            "instrument",
            "suspended",
            "limit_up",
            "limit_down",
            "volume",
            "listed_date",
            "delisted_date",
            "source",
        }
        missing = required - set(dataframe.columns)
        if missing:
            raise ValueError(f"Missing A-share status columns: {sorted(missing)}")

        statuses = {}
        for row in dataframe.to_dict("records"):
            instrument = parse_instrument_key(row["instrument"], market=MarketType.A_SHARE).key
            trading_date = pd.Timestamp(row["date"]).date().isoformat()
            status = AShareDailyStatus(
                date=trading_date,
                instrument=instrument,
                suspended=bool(int(row["suspended"])),
                limit_up=_optional_float(row["limit_up"]),
                limit_down=_optional_float(row["limit_down"]),
                volume=_optional_float(row["volume"]),
                listed_date=_optional_date(row["listed_date"]),
                delisted_date=_optional_date(row["delisted_date"]),
                source=str(row["source"]),
            )
            statuses[(instrument, trading_date)] = status
        return cls(statuses)

    def get_status(
        self,
        instrument_key: str,
        value: date | datetime | str,
    ) -> AShareDailyStatus | None:
        instrument = parse_instrument_key(instrument_key, market=MarketType.A_SHARE).key
        trading_date = pd.Timestamp(value).date().isoformat()
        return self._statuses.get((instrument, trading_date))


def _optional_float(value) -> float | None:
    if pd.isna(value) or value == "":
        return None
    return float(value)


def _optional_date(value) -> str | None:
    if pd.isna(value) or value == "":
        return None
    return pd.Timestamp(value).date().isoformat()
```

- [ ] **Step 4: Export and run tests**

Modify `freqtrade/freqtrade/markets/__init__.py`:

```python
from freqtrade.markets.status_store import AShareDailyStatus, AShareStatusStore
```

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/markets/test_status_store.py -q
```

Expected: PASS.

- [ ] **Step 5: Checkpoint**

Commit only in an isolated clean worktree:

```powershell
git add freqtrade/markets/status_store.py freqtrade/markets/__init__.py tests/markets/test_status_store.py
git commit -m "feat: add a-share daily status store"
```

---

## Task 4: Market Rule Fill Eligibility

**Files:**
- Modify: `freqtrade/freqtrade/markets/rules.py`
- Modify: `freqtrade/tests/markets/test_rules.py`

**Interfaces:**
- Consumes:
  - `AShareDailyStatus`
  - `CachedAShareCalendar`
- Produces:
  - `AShareMarketRules.can_fill_order(side: str, price: float, status: AShareDailyStatus | None) -> bool`
  - `AShareMarketRules.can_sell(entry_date: Any, execution_date: Any, calendar: CachedAShareCalendar | None = None) -> bool`

- [ ] **Step 1: Add rule tests**

Append to `freqtrade/tests/markets/test_rules.py`:

```python
from freqtrade.markets import AShareDailyStatus, AShareMarketRules


def _status(**overrides) -> AShareDailyStatus:
    values = {
        "date": "2024-01-02",
        "instrument": "600519.SH",
        "suspended": False,
        "limit_up": 110.0,
        "limit_down": 90.0,
        "volume": 1000.0,
        "listed_date": "2001-08-27",
        "delisted_date": None,
        "source": "test",
    }
    values.update(overrides)
    return AShareDailyStatus(**values)


def test_market_rules_reject_suspended_and_zero_volume_fill() -> None:
    rules = AShareMarketRules()

    assert rules.can_fill_order("buy", 100.0, _status(suspended=True)) is False
    assert rules.can_fill_order("buy", 100.0, _status(volume=0.0)) is False


def test_market_rules_reject_limit_up_buy_and_limit_down_sell() -> None:
    rules = AShareMarketRules()

    assert rules.can_fill_order("buy", 110.0, _status()) is False
    assert rules.can_fill_order("sell", 90.0, _status()) is False
    assert rules.can_fill_order("buy", 109.99, _status()) is True
    assert rules.can_fill_order("sell", 90.01, _status()) is True


def test_market_rules_reject_unlisted_or_delisted_status() -> None:
    rules = AShareMarketRules()

    assert rules.can_fill_order("buy", 100.0, _status(listed_date="2024-01-03")) is False
    assert rules.can_fill_order("sell", 100.0, _status(delisted_date="2024-01-01")) is False
```

- [ ] **Step 2: Run failing rules tests**

```powershell
.\.venv\Scripts\python -m pytest tests/markets/test_rules.py -q
```

Expected: FAIL because `can_fill_order` does not exist.

- [ ] **Step 3: Implement fill rules**

Modify `freqtrade/freqtrade/markets/rules.py`:

```python
from freqtrade.markets.status_store import AShareDailyStatus
```

Add:

```python
def can_fill_order(
    self,
    side: str,
    price: float,
    status: AShareDailyStatus | None,
) -> bool:
    if status is None:
        return True
    if status.suspended:
        return False
    if status.volume is not None and status.volume <= 0:
        return False
    if status.listed_date is not None and status.date < status.listed_date:
        return False
    if status.delisted_date is not None and status.date > status.delisted_date:
        return False
    if side == "buy" and status.limit_up is not None and price >= status.limit_up:
        return False
    if side == "sell" and status.limit_down is not None and price <= status.limit_down:
        return False
    if side not in {"buy", "sell"}:
        raise ValueError(f"Unsupported A-share order side: {side}")
    return True
```

Update `can_sell` signature:

```python
def can_sell(self, entry_date: Any, execution_date: Any, calendar=None) -> bool:
    if calendar is not None:
        return calendar.next_trading_day(entry_date) <= self._trading_date(execution_date)
    return self._trading_date(execution_date) > self._trading_date(entry_date)
```

- [ ] **Step 4: Run rules tests**

```powershell
.\.venv\Scripts\python -m pytest tests/markets/test_rules.py tests/markets/test_calendar_store.py tests/markets/test_status_store.py -q
```

Expected: PASS.

- [ ] **Step 5: Checkpoint**

Commit only in an isolated clean worktree:

```powershell
git add freqtrade/markets/rules.py tests/markets/test_rules.py
git commit -m "feat: add a-share fill eligibility rules"
```

---

## Task 5: Apply Calendar And Status Rules In Research Backtest

**Files:**
- Modify: `freqtrade/freqtrade/research/backtesting.py`
- Modify: `freqtrade/freqtrade/rpc/api_server/api_research.py`
- Modify: `freqtrade/tests/research/test_backtesting.py`
- Create: `freqtrade/tests/research/test_a_share_phase2_market_correctness.py`

**Interfaces:**
- Produces:
  - `ResearchMarketContext(calendar: CachedAShareCalendar | None, status_store: AShareStatusStore | None)`
  - `run_research_backtest(..., market_context: ResearchMarketContext | None = None)`
- Consumes:
  - `AShareMarketRules.can_fill_order(...)`
  - `AShareMarketRules.can_sell(..., calendar=...)`

- [ ] **Step 1: Write backtest market-correctness tests**

Create `freqtrade/tests/research/test_a_share_phase2_market_correctness.py`:

```python
import pandas as pd

from freqtrade.markets import AShareStatusStore, CachedAShareCalendar
from freqtrade.research.backtesting import (
    ResearchBacktestConfig,
    ResearchMarketContext,
    run_research_backtest,
)


def _dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"], utc=True),
            "open": [100.0, 110.0, 100.0],
            "high": [101.0, 111.0, 101.0],
            "low": [99.0, 109.0, 99.0],
            "close": [100.0, 110.0, 100.0],
            "volume": [1000.0, 1000.0, 1000.0],
            "enter_long": [1, 0, 0],
            "exit_long": [0, 1, 0],
        }
    )


def test_research_backtest_blocks_buy_on_limit_up(tmp_path) -> None:
    status_path = tmp_path / "status.csv"
    status_path.write_text(
        "date,instrument,suspended,limit_up,limit_down,volume,listed_date,delisted_date,source\n"
        "2024-01-03,600519.SH,0,110.0,90.0,1000,2001-08-27,,test\n",
        encoding="utf-8",
    )
    context = ResearchMarketContext(
        status_store=AShareStatusStore.from_csv(status_path),
    )

    result = run_research_backtest(
        "600519.SH",
        _dataframe(),
        ResearchBacktestConfig(initial_cash=100000, fast=1, slow=2),
        market_context=context,
    )

    assert result.metrics["trade_count"] == 0
    assert "Blocked buy fill on 2024-01-03 00:00:00+00:00" in result.warnings


def test_research_backtest_uses_trading_day_t_plus_one(tmp_path) -> None:
    calendar_path = tmp_path / "calendar.csv"
    calendar_path.write_text(
        "date,is_open,source\n"
        "2024-01-02,1,test\n"
        "2024-01-03,0,test\n"
        "2024-01-04,1,test\n",
        encoding="utf-8",
    )
    context = ResearchMarketContext(
        calendar=CachedAShareCalendar.from_csv(calendar_path),
    )

    result = run_research_backtest(
        "600519.SH",
        _dataframe(),
        ResearchBacktestConfig(initial_cash=100000, fast=1, slow=2),
        market_context=context,
    )

    assert result.metrics["trade_count"] == 0
    assert any("T+1" in warning for warning in result.warnings)
```

- [ ] **Step 2: Run failing tests**

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_a_share_phase2_market_correctness.py -q
```

Expected: FAIL because `ResearchMarketContext` does not exist.

- [ ] **Step 3: Add market context and rule checks**

Modify `freqtrade/freqtrade/research/backtesting.py`:

```python
from freqtrade.markets import AShareStatusStore, CachedAShareCalendar
```

Add:

```python
class ResearchMarketContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    calendar: CachedAShareCalendar | None = None
    status_store: AShareStatusStore | None = None
```

Update signature:

```python
def run_research_backtest(
    instrument: str,
    dataframe: DataFrame,
    config: ResearchBacktestConfig,
    market_context: ResearchMarketContext | None = None,
) -> ResearchBacktestResult:
```

Inside buy branch, before buying:

```python
status = (
    market_context.status_store.get_status(instrument, row_date)
    if market_context and market_context.status_store
    else None
)
if not market_rules.can_fill_order("buy", open_price, status):
    warnings.append(f"Blocked buy fill on {_date_string(row_date)}")
    continue
```

Inside sell branch:

```python
if not market_rules.can_sell(
    entry["date"],
    row_date,
    calendar=market_context.calendar if market_context else None,
):
    warnings.append(f"Blocked sell fill by T+1 on {_date_string(row_date)}")
    continue
status = (
    market_context.status_store.get_status(instrument, row_date)
    if market_context and market_context.status_store
    else None
)
if not market_rules.can_fill_order("sell", open_price, status):
    warnings.append(f"Blocked sell fill on {_date_string(row_date)}")
    continue
```

Initialize `warnings: list[str] = []` before the loop and pass it into `ResearchBacktestResult`.

- [ ] **Step 4: Keep API behavior unchanged unless market files exist**

For this task, do not add automatic status/calendar loading in `api_research.py`. Existing API behavior remains unchanged unless tests call `run_research_backtest` directly with context. This prevents a broad config design from being smuggled into the rule implementation.

- [ ] **Step 5: Run focused tests**

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_a_share_phase2_market_correctness.py tests/research/test_backtesting.py tests/markets/test_rules.py -q
```

Expected: PASS.

- [ ] **Step 6: Checkpoint**

Commit only in an isolated clean worktree:

```powershell
git add freqtrade/research/backtesting.py tests/research/test_a_share_phase2_market_correctness.py tests/research/test_backtesting.py
git commit -m "feat: apply a-share market rules in research backtest"
```

---

## Task 6: Calendar And Status Seed Tools

**Files:**
- Create: `tools/download_a_share_market_calendar.py`
- Create: `tools/download_a_share_daily_status.py`
- Create: `freqtrade/tests/research/test_a_share_phase2_tools.py`
- Modify: `docs/a-share-market-correctness.md`

**Interfaces:**
- Produces:
  - Calendar CSV: `ft_userdata/user_data/research_data/a_share_meta/calendar/trade_dates.csv`
  - Status CSV: `ft_userdata/user_data/research_data/a_share_meta/status/daily_status.csv`
- Consumes:
  - Optional `akshare.tool_trade_date_hist_sina()`
  - Optional `akshare.stock_zh_a_spot_em()`

- [ ] **Step 1: Write tool import/help tests**

Create `freqtrade/tests/research/test_a_share_phase2_tools.py`:

```python
import importlib.util


PARENT_REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[3]


def _load_script(name: str):
    path = PARENT_REPO_ROOT / "tools" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_calendar_download_script_help_does_not_import_akshare(capsys) -> None:
    script = _load_script("download_a_share_market_calendar.py")

    result = script.main(["--help"])

    captured = capsys.readouterr()
    assert result == 0
    assert "Download A-share trading calendar" in captured.out


def test_daily_status_download_script_help_does_not_import_akshare(capsys) -> None:
    script = _load_script("download_a_share_daily_status.py")

    result = script.main(["--help"])

    captured = capsys.readouterr()
    assert result == 0
    assert "Download A-share daily status snapshot" in captured.out
```

- [ ] **Step 2: Run failing tool tests**

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_a_share_phase2_tools.py -q
```

Expected: FAIL because scripts do not exist.

- [ ] **Step 3: Implement calendar seed script**

Create `tools/download_a_share_market_calendar.py`:

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FREQTRADE_REPO = REPO_ROOT / "freqtrade"
sys.path.insert(0, str(FREQTRADE_REPO))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download A-share trading calendar.")
    parser.add_argument(
        "--output",
        default="ft_userdata/user_data/research_data/a_share_meta/calendar/trade_dates.csv",
    )
    args = parser.parse_args(argv)
    if argv is not None and "--help" in argv:
        return 0

    try:
        import akshare as ak
    except ImportError:
        print("Install optional dependency with `pip install -e .[research_ashare]`.", file=sys.stderr)
        return 2

    dataframe = ak.tool_trade_date_hist_sina()
    output = REPO_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    normalized = dataframe.rename(columns={"trade_date": "date"}).copy()
    normalized["is_open"] = 1
    normalized["source"] = "akshare.tool_trade_date_hist_sina"
    normalized.loc[:, ["date", "is_open", "source"]].to_csv(output, index=False)
    print(f"ok: {output.relative_to(REPO_ROOT)} rows={len(normalized)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Implement daily status seed script**

Create `tools/download_a_share_daily_status.py`:

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FREQTRADE_REPO = REPO_ROOT / "freqtrade"
sys.path.insert(0, str(FREQTRADE_REPO))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download A-share daily status snapshot.")
    parser.add_argument(
        "--output",
        default="ft_userdata/user_data/research_data/a_share_meta/status/daily_status.csv",
    )
    args = parser.parse_args(argv)
    if argv is not None and "--help" in argv:
        return 0

    try:
        import akshare as ak
    except ImportError:
        print("Install optional dependency with `pip install -e .[research_ashare]`.", file=sys.stderr)
        return 2

    dataframe = ak.stock_zh_a_spot_em()
    output = REPO_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_spot_snapshot(dataframe)
    normalized.to_csv(output, index=False)
    print(f"ok: {output.relative_to(REPO_ROOT)} rows={len(normalized)}")
    return 0


def _normalize_spot_snapshot(dataframe):
    import pandas as pd

    columns = {
        "代码": "instrument",
        "成交量": "volume",
        "涨停": "limit_up",
        "跌停": "limit_down",
    }
    normalized = dataframe.rename(columns=columns).copy()
    today = pd.Timestamp.utcnow().tz_convert("Asia/Shanghai").date().isoformat()
    normalized["date"] = today
    normalized["suspended"] = 0
    normalized["listed_date"] = ""
    normalized["delisted_date"] = ""
    normalized["source"] = "akshare.stock_zh_a_spot_em"
    normalized["instrument"] = normalized["instrument"].map(_instrument_key)
    return normalized.loc[
        :,
        [
            "date",
            "instrument",
            "suspended",
            "limit_up",
            "limit_down",
            "volume",
            "listed_date",
            "delisted_date",
            "source",
        ],
    ]


def _instrument_key(symbol: str) -> str:
    symbol = str(symbol).zfill(6)
    suffix = "SH" if symbol.startswith(("5", "6", "9")) else "SZ"
    return f"{symbol}.{suffix}"


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tool tests and ruff**

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_a_share_phase2_tools.py -q
.\.venv\Scripts\python -m ruff check ..\tools\download_a_share_market_calendar.py ..\tools\download_a_share_daily_status.py tests/research/test_a_share_phase2_tools.py
```

Expected: PASS and `All checks passed!`.

- [ ] **Step 6: Checkpoint**

Commit only in an isolated clean worktree:

```powershell
git add ../tools/download_a_share_market_calendar.py ../tools/download_a_share_daily_status.py tests/research/test_a_share_phase2_tools.py
git commit -m "feat: add a-share market metadata seed tools"
```

---

## Task 7: Operator Documentation And Browser Verification

**Files:**
- Create: `docs/a-share-market-correctness.md`
- Modify: `docs/a-share-research-data.md`

**Interfaces:**
- Documents:
  - `Phase 1 = 1d/raw OHLCV`
  - `Phase 2 = calendar/status/rules correctness`
  - `Phase 3+ = feature/event/document stores`

- [ ] **Step 1: Create market correctness documentation**

Create `docs/a-share-market-correctness.md`:

```markdown
# A-Share Market Correctness

This document describes the Phase 2 research-only market-correctness layer.

## Scope

Phase 2 improves research chart/backtest correctness. It does not enable live trading, dry-run
trading, broker execution, account synchronization, or order placement.

## Inputs

Calendar cache:

```text
ft_userdata/user_data/research_data/a_share_meta/calendar/trade_dates.csv
```

Columns:

```text
date,is_open,source
```

Daily status cache:

```text
ft_userdata/user_data/research_data/a_share_meta/status/daily_status.csv
```

Columns:

```text
date,instrument,suspended,limit_up,limit_down,volume,listed_date,delisted_date,source
```

## Rules

Research backtests must apply these conservative A-share rules:

- 100 shares per lot.
- Commission on entry and exit.
- Stamp tax on exit.
- T+1 based on trading days, not natural days.
- No fills while suspended.
- No fills when volume is zero.
- No buy fills at or above limit-up.
- No sell fills at or below limit-down.
- No fills before listing date or after delisting date.

## Provider Boundary

Chart/backtest requests read local canonical files only. They must not call akshare, Eastmoney,
Tencent, Sina, mootdx, cninfo, iwencai, or any other live provider.

Provider seed tools may call external providers and must write local CSV files before research APIs
consume them.
```

- [ ] **Step 2: Link docs from existing research data document**

Add to `docs/a-share-research-data.md` after the Phase 1 scope:

```markdown
For Phase 2 market-correctness rules, see [A-Share Market Correctness](a-share-market-correctness.md).
```

- [ ] **Step 3: Verify docs**

Run:

```powershell
rg -n "T\\+1|limit-up|suspended|Provider Boundary|a-share-market-correctness" docs/a-share-market-correctness.md docs/a-share-research-data.md
```

Expected: grep hits both documents.

- [ ] **Step 4: Browser/API verification checklist**

After executing Tasks 1-6:

1. Start backend:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m freqtrade webserver `
  --config ..\ft_userdata\user_data\config.research.example.json `
  --userdir ..\ft_userdata\user_data
```

2. Open FreqUI:

```text
http://127.0.0.1:8082/research
```

3. Confirm visible page state:

```text
Bot: A Share Local
Instrument: 600519
Timeframe: 1d
Adjustment: Raw
Data provenance: provider/run id/rows are visible or API-visible
Backtest summary: includes warnings when fills are blocked by Phase 2 rules
```

- [ ] **Step 5: Checkpoint**

Commit only in an isolated clean worktree:

```powershell
git add docs/a-share-market-correctness.md docs/a-share-research-data.md
git commit -m "docs: describe a-share market correctness"
```

---

## Full Verification

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
.\.venv\Scripts\python -m pytest tests/markets/test_calendar_store.py tests/markets/test_status_store.py tests/markets/test_rules.py tests/research/test_provenance.py tests/research/test_data_source.py tests/research/test_chart.py tests/research/test_backtesting.py tests/research/test_a_share_phase2_market_correctness.py tests/research/test_a_share_phase2_tools.py tests/rpc/test_api_research.py -q
```

Run lint:

```powershell
.\.venv\Scripts\python -m ruff check freqtrade/markets freqtrade/research freqtrade/rpc/api_server/api_research.py tests/markets tests/research tests/rpc/test_api_research.py ..\tools\download_a_share_market_calendar.py ..\tools\download_a_share_daily_status.py
```

Run tool help from `G:\AI_Trading\freqtrade-cn`:

```powershell
freqtrade\.venv\Scripts\python tools\download_a_share_market_calendar.py --help
freqtrade\.venv\Scripts\python tools\download_a_share_daily_status.py --help
```

Expected:

- All tests pass.
- Ruff reports `All checks passed!`.
- Tool help exits with code 0 without requiring network access.

## Execution Order

1. Task 1 first because provenance closes the Phase 0 reproducibility gap and gives later chart/backtest results an auditable data version.
2. Task 2 second because trading-day T+1 and session correctness depend on a real cached calendar.
3. Task 3 third because limit/suspension/listing status is side-channel data needed by rules.
4. Task 4 fourth because rules should be tested independently before they affect backtest results.
5. Task 5 fifth because backtest integration is where false research conclusions are actually prevented.
6. Task 6 sixth because provider seed tools should write local caches only after the canonical contracts are stable.
7. Task 7 last because operator docs should describe the actual final contracts and commands.

## Out Of Scope For This Plan

- Minute OHLCV ingestion (`1m`, `5m`).
- Weekly/monthly OHLCV (`1w`, `1M`).
- `qfq` and `hfq` chart/backtest support.
- Portfolio-level backtesting.
- Feature/event/document stores for funds flow, sectors, limit-up pools, financials, news, announcements, or reports.
- AI retrieval.
- Broker adapters, execution engines, live trading, dry-run trading, account sync, orders, and wallets.

## Follow-Up Plan Split

After this plan is complete, continue in this order:

1. `Phase 3: Feature/Event/Document Store`
   - Funds flow, sector/concept membership, limit-up pools, financials, announcements, news, reports.
   - Store as side-channel feature/event/document tables aligned by candle timestamp.
2. `Phase 4: Portfolio Research Backtest`
   - Historical universes, benchmark, position book, rebalance calendar, volume/slippage constraints.
3. `Phase 5: AI Evidence Retrieval`
   - EventStore + DocumentStore + Retrieval with `event_time`, `publish_time`, and `ingest_time`.
4. `Phase 6: BrokerAdapter/ExecutionEngine`
   - Separate live trading design, not using research provider adapters.

