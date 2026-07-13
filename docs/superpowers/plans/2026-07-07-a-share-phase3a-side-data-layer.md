# A-Share Phase 3A Side-Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first A-share research side-data layer: Phase 2 market-context loading in the public Research backtest API, local feature/event/document stores, dataset discovery, optional chart side layers, collector tooling, and minimal FreqUI visibility.

**Architecture:** Keep OHLCV as the six-column candle coordinate system and add side data as separate local stores under `research_data/a_share_meta`. Provider calls happen only in collector/tooling paths; chart/backtest APIs read local artifacts and return side data through `ChartResponseMeta.layers`. Phase 3A supports feature/event/document schemas, ships real collection paths for fund flow, limit-pool events, and announcement index, and keeps sector membership behind the same provider/store interfaces with fake-provider coverage first.

**Tech Stack:** Python 3, Pydantic, pandas, FastAPI, pytest, ruff, Vue 3, Pinia, TypeScript, Vitest, existing Freqtrade/FreqUI chart metadata contracts.

## Global Constraints

- Existing OHLCV CSV files must remain exactly `date,open,high,low,close,volume`.
- First supported A-share research timeframe remains `1d`.
- First supported A-share OHLCV adjustment remains `raw`.
- Research chart/backtest API requests must not call `akshare`, Eastmoney, Tencent, Sina, cninfo, mootdx, or any live provider.
- Provider calls may happen only from explicit collector tools or provider modules.
- `akshare` remains optional and must not be imported by route modules.
- Side datasets live under the configured `user_data_dir`; source-tree fixtures are test-only.
- Configs without `market_data` or `side_data` must keep working.
- Do not add A-share live trading, dry-run trading, broker execution, wallets, orders, account state, force entry, or force exit.
- Do not implement AI retrieval, embeddings, summarization, RAG, PDF parsing, or strategy feature consumption in Phase 3A.
- Current repository is a shared dirty worktree; do not commit during execution unless the user explicitly authorizes commits in that run.

---

## File Structure

Backend files to create:

- `freqtrade/freqtrade/research/market_context.py`  
  Builds `ResearchMarketContext` from optional research profile metadata config.

- `freqtrade/freqtrade/research/side_data/__init__.py`  
  Public exports for side-data models, stores, and layer helpers.

- `freqtrade/freqtrade/research/side_data/models.py`  
  Pydantic models for dataset descriptors, feature rows, events, documents, and side-layer requests.

- `freqtrade/freqtrade/research/side_data/alignment.py`  
  Timestamp normalization, candle timestamp mapping, and future-data availability helpers.

- `freqtrade/freqtrade/research/side_data/provenance.py`  
  Manifest lookup for side-data artifacts.

- `freqtrade/freqtrade/research/side_data/store.py`  
  Local side-data readers for feature CSV, event JSONL, document JSONL, and dataset descriptors.

- `freqtrade/freqtrade/research/side_data/chart_layers.py`  
  Converts local side data into `ChartLayerMeta` plus reserved-prefix feature columns.

- `freqtrade/freqtrade/research/side_data/collectors/a_share_side_data.py`  
  Collector orchestration, fake-provider test seam, atomic writes, and manifest creation.

- `freqtrade/freqtrade/research/side_data/providers/akshare_side_data.py`  
  Optional `akshare` provider adapter imported only by collector/tooling paths.

- `freqtrade/freqtrade/research/side_data/providers/a_stock_data_direct.py`  
  Small direct HTTP adapter for `a-stock-data` style sector membership if enabled.

- `tools/download_a_share_side_data.py`  
  Parent-repo CLI for collecting side-data artifacts.

Backend files to modify:

- `freqtrade/freqtrade/research/profiles.py`  
  Add optional `market_data` and `side_data` config models.

- `freqtrade/freqtrade/research/chart.py`  
  Load optional requested side layers and append chart metadata.

- `freqtrade/freqtrade/rpc/api_server/api_schemas.py`  
  Add side-layer request/response schemas and extend chart layer source literals.

- `freqtrade/freqtrade/rpc/api_server/api_research.py`  
  Add `/research/datasets`, pass market context into `/research/backtest`, and route side-layer chart requests.

- `freqtrade/freqtrade/research/__init__.py`  
  Export new market-context helper only if useful to tests.

Backend tests to create or modify:

- `freqtrade/tests/research/test_profiles.py`
- `freqtrade/tests/research/test_market_context.py`
- `freqtrade/tests/research/test_side_data_alignment.py`
- `freqtrade/tests/research/test_side_data_store.py`
- `freqtrade/tests/research/test_side_data_chart_layers.py`
- `freqtrade/tests/research/test_a_share_side_data_collector.py`
- `freqtrade/tests/research/test_akshare_side_data_provider.py`
- `freqtrade/tests/research/test_a_stock_data_direct_provider.py`
- `freqtrade/tests/rpc/test_api_research.py`

Frontend files to modify:

- `frequi/src/types/candleTypes.ts`
- `frequi/src/types/research.ts`
- `frequi/src/stores/research.ts`
- `frequi/src/views/ResearchView.vue`
- `frequi/src/composables/useCandleChartTooltip.ts`

Frontend tests to create or modify:

- `frequi/src/stores/__tests__/research.spec.ts`
- `frequi/src/composables/__tests__/useCandleChartTooltip.spec.ts`
- `frequi/src/views/__tests__/ResearchView.spec.ts`

Docs to modify:

- `docs/a-share-market-correctness.md`
- `docs/a-share-research-data.md`
- `docs/a-share-side-data.md`
- `ft_userdata/user_data/config.research.example.json`

---

## Task 1: Optional Research Market Context In Public Backtest API

**Files:**
- Modify: `freqtrade/freqtrade/research/profiles.py`
- Create: `freqtrade/freqtrade/research/market_context.py`
- Modify: `freqtrade/freqtrade/rpc/api_server/api_research.py`
- Test: `freqtrade/tests/research/test_profiles.py`
- Test: `freqtrade/tests/research/test_market_context.py`
- Test: `freqtrade/tests/rpc/test_api_research.py`

**Interfaces:**
- Produces: `ResearchMarketDataConfig(meta_root: str, calendar: str = "calendar/trade_dates.csv", daily_status: str = "status/daily_status.csv")`
- Produces: `ResearchSideDataConfig(root: str, enabled_datasets: list[str] = [])`
- Produces: `ResearchBotProfile.market_data: ResearchMarketDataConfig | None`
- Produces: `ResearchBotProfile.side_data: ResearchSideDataConfig | None`
- Produces: `ResearchBotProfile.market_data_root: Path | None`
- Produces: `ResearchBotProfile.side_data_root: Path | None`
- Produces: `create_research_market_context(profile: ResearchBotProfile) -> ResearchMarketContext | None`
- Consumes: `CachedAShareCalendar.from_csv`, `AShareStatusStore.from_csv`, `ResearchMarketContext`

- [ ] **Step 1: Write profile config tests**

Add to `freqtrade/tests/research/test_profiles.py`:

```python
def test_load_research_profiles_accepts_optional_market_and_side_data(tmp_path) -> None:
    config = {
        "user_data_dir": tmp_path,
        "research_bots": [
            {
                "id": "a-share-local",
                "label": "A Share Local",
                "market": "a_share",
                "data_source": {"type": "local_csv", "root": "research_data/a_share"},
                "market_data": {
                    "meta_root": "research_data/a_share_meta",
                    "calendar": "calendar/trade_dates.csv",
                    "daily_status": "status/daily_status.csv",
                },
                "side_data": {
                    "root": "research_data/a_share_meta",
                    "enabled_datasets": ["fund_flow_daily", "limit_pool"],
                },
            }
        ],
    }

    profile = load_research_profiles(config)[0]

    assert profile.market_data is not None
    assert profile.market_data_root == tmp_path / "research_data" / "a_share_meta"
    assert profile.market_data.calendar == "calendar/trade_dates.csv"
    assert profile.market_data.daily_status == "status/daily_status.csv"
    assert profile.side_data is not None
    assert profile.side_data_root == tmp_path / "research_data" / "a_share_meta"
    assert profile.side_data.enabled_datasets == ["fund_flow_daily", "limit_pool"]
```

- [ ] **Step 2: Run profile test and confirm it fails**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_profiles.py::test_load_research_profiles_accepts_optional_market_and_side_data -q
```

Expected: FAIL because `ResearchBotProfile` does not expose `market_data` and `side_data`.

- [ ] **Step 3: Implement profile config models**

Modify `freqtrade/freqtrade/research/profiles.py`:

```python
class ResearchMarketDataConfig(BaseModel):
    meta_root: str
    calendar: str = "calendar/trade_dates.csv"
    daily_status: str = "status/daily_status.csv"


class ResearchSideDataConfig(BaseModel):
    root: str
    enabled_datasets: list[str] = Field(default_factory=list)
```

Extend `ResearchBotProfile`:

```python
class ResearchBotProfile(BaseModel):
    id: str
    label: str
    market: MarketType
    data_source: ResearchDataSourceConfig
    market_data: ResearchMarketDataConfig | None = None
    side_data: ResearchSideDataConfig | None = None
    capabilities: BotCapabilities = Field(default_factory=BotCapabilities.research)
    data_root: Path
    market_data_root: Path | None = None
    side_data_root: Path | None = None
```

Inside `load_research_profiles`, after `data_source` parsing:

```python
        raw_market_data = raw_profile.get("market_data")
        try:
            market_data = (
                ResearchMarketDataConfig(**raw_market_data)
                if raw_market_data is not None
                else None
            )
        except (TypeError, ValidationError) as e:
            raise ResearchConfigError(
                _invalid_config_message(f"{profile_location}.market_data", e)
            ) from e

        raw_side_data = raw_profile.get("side_data")
        try:
            side_data = (
                ResearchSideDataConfig(**raw_side_data)
                if raw_side_data is not None
                else None
            )
        except (TypeError, ValidationError) as e:
            raise ResearchConfigError(
                _invalid_config_message(f"{profile_location}.side_data", e)
            ) from e
```

When constructing `ResearchBotProfile`, pass:

```python
                    market_data=market_data,
                    side_data=side_data,
                    market_data_root=(
                        user_data_dir / market_data.meta_root if market_data is not None else None
                    ),
                    side_data_root=(
                        user_data_dir / side_data.root if side_data is not None else None
                    ),
```

- [ ] **Step 4: Write market-context tests**

Create `freqtrade/tests/research/test_market_context.py`:

```python
from freqtrade.research.market_context import create_research_market_context
from freqtrade.research.profiles import load_research_profiles


def _profile(tmp_path):
    meta_root = tmp_path / "research_data" / "a_share_meta"
    (meta_root / "calendar").mkdir(parents=True)
    (meta_root / "status").mkdir(parents=True)
    (meta_root / "calendar" / "trade_dates.csv").write_text(
        "date,is_open,source\n"
        "2026-07-06,1,test\n"
        "2026-07-07,1,test\n",
        encoding="utf-8",
    )
    (meta_root / "status" / "daily_status.csv").write_text(
        "date,instrument,suspended,limit_up,limit_down,volume,listed_date,delisted_date,source\n"
        "2026-07-07,600519.SH,0,1800,1600,100000,2001-08-27,,test\n",
        encoding="utf-8",
    )
    config = {
        "user_data_dir": tmp_path,
        "research_bots": [
            {
                "id": "a-share-local",
                "label": "A Share Local",
                "market": "a_share",
                "data_source": {"type": "local_csv", "root": "research_data/a_share"},
                "market_data": {"meta_root": "research_data/a_share_meta"},
            }
        ],
    }
    return load_research_profiles(config)[0]


def test_create_research_market_context_loads_configured_cache_files(tmp_path) -> None:
    context = create_research_market_context(_profile(tmp_path))

    assert context is not None
    assert context.calendar is not None
    assert context.calendar.is_trading_day("2026-07-07")
    assert context.status_store is not None
    assert context.status_store.get_status("600519.SH", "2026-07-07").limit_up == 1800


def test_create_research_market_context_returns_none_without_market_data(tmp_path) -> None:
    config = {
        "user_data_dir": tmp_path,
        "research_bots": [
            {
                "id": "a-share-local",
                "label": "A Share Local",
                "market": "a_share",
                "data_source": {"type": "local_csv", "root": "research_data/a_share"},
            }
        ],
    }
    profile = load_research_profiles(config)[0]

    assert create_research_market_context(profile) is None
```

- [ ] **Step 5: Implement `create_research_market_context`**

Create `freqtrade/freqtrade/research/market_context.py`:

```python
from freqtrade.markets import AShareStatusStore, CachedAShareCalendar
from freqtrade.research.backtesting import ResearchMarketContext
from freqtrade.research.profiles import ResearchBotProfile


def create_research_market_context(
    profile: ResearchBotProfile,
) -> ResearchMarketContext | None:
    if profile.market_data is None or profile.market_data_root is None:
        return None

    calendar_path = profile.market_data_root / profile.market_data.calendar
    status_path = profile.market_data_root / profile.market_data.daily_status
    calendar = CachedAShareCalendar.from_csv(calendar_path) if calendar_path.is_file() else None
    status_store = AShareStatusStore.from_csv(status_path) if status_path.is_file() else None
    if calendar is None and status_store is None:
        return None
    return ResearchMarketContext(calendar=calendar, status_store=status_store)
```

- [ ] **Step 6: Pass context through API backtest**

Modify `freqtrade/freqtrade/rpc/api_server/api_research.py`:

```python
from freqtrade.research.market_context import create_research_market_context
```

Replace:

```python
        result = run_research_backtest(request.instrument, dataframe, backtest_config)
```

with:

```python
        result = run_research_backtest(
            request.instrument,
            dataframe,
            backtest_config,
            market_context=create_research_market_context(profile),
        )
```

- [ ] **Step 7: Add API regression test for context pass-through**

Add to `freqtrade/tests/rpc/test_api_research.py`:

```python
def test_research_backtest_passes_market_context_when_configured(
    default_conf,
    tmp_path,
    mocker,
) -> None:
    meta_root = tmp_path / "research_data" / "a_share_meta"
    (meta_root / "calendar").mkdir(parents=True)
    (meta_root / "status").mkdir(parents=True)
    (meta_root / "calendar" / "trade_dates.csv").write_text(
        "date,is_open,source\n2026-07-06,1,test\n2026-07-07,1,test\n",
        encoding="utf-8",
    )
    (meta_root / "status" / "daily_status.csv").write_text(
        "date,instrument,suspended,limit_up,limit_down,volume,listed_date,delisted_date,source\n"
        "2026-07-07,600519.SH,0,1800,1600,100000,2001-08-27,,test\n",
        encoding="utf-8",
    )
    captured = {}

    def capture_backtest(instrument, dataframe, config, market_context=None):
        captured["market_context"] = market_context
        from freqtrade.research.backtesting import run_research_backtest

        return run_research_backtest(instrument, dataframe, config, market_context=market_context)

    with make_research_client(
        default_conf,
        tmp_path,
        mocker,
        research_bots=[
            {
                "id": "a-share-local",
                "label": "A Share Local",
                "market": "a_share",
                "data_source": {"type": "local_csv", "root": "research_data/a_share"},
                "market_data": {"meta_root": "research_data/a_share_meta"},
            }
        ],
    ) as client:
        mocker.patch(
            "freqtrade.rpc.api_server.api_research.run_research_backtest",
            side_effect=capture_backtest,
        )
        response = client_post(
            client,
            f"{BASE_URI}/research/backtest",
            data={
                "bot_id": "a-share-local",
                "instrument": "600519.SH",
                "timeframe": "1d",
                "strategy": {"type": "sma_cross", "fast": 1, "slow": 2},
            },
        )

    assert response.status_code == 200
    assert captured["market_context"] is not None
    assert captured["market_context"].calendar is not None
    assert captured["market_context"].status_store is not None
```

- [ ] **Step 8: Verify Task 1**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_profiles.py tests/research/test_market_context.py tests/rpc/test_api_research.py -q
```

Expected: PASS.

---

## Task 2: Side-Data Models, Alignment, And Provenance

**Files:**
- Create: `freqtrade/freqtrade/research/side_data/__init__.py`
- Create: `freqtrade/freqtrade/research/side_data/models.py`
- Create: `freqtrade/freqtrade/research/side_data/alignment.py`
- Create: `freqtrade/freqtrade/research/side_data/provenance.py`
- Test: `freqtrade/tests/research/test_side_data_alignment.py`
- Test: `freqtrade/tests/research/test_side_data_store.py`

**Interfaces:**
- Produces: `ResearchDatasetDescriptor`
- Produces: `ResearchFeatureFrame = pd.DataFrame`
- Produces: `ResearchEvent`
- Produces: `ResearchDocument`
- Produces: `ResearchSideLayerSelection`
- Produces: `effective_candle_time_for_publish_time(value: object, calendar: CachedAShareCalendar | None) -> str`
- Produces: `is_available_at(publish_time: object | None, decision_time: object) -> bool`
- Produces: `find_side_data_provenance(root: Path, artifact_path: str) -> dict[str, Any]`

- [ ] **Step 1: Write alignment tests**

Create `freqtrade/tests/research/test_side_data_alignment.py`:

```python
from pathlib import Path

from freqtrade.markets import CachedAShareCalendar
from freqtrade.research.side_data.alignment import (
    effective_candle_time_for_publish_time,
    is_available_at,
)


def _calendar(tmp_path: Path) -> CachedAShareCalendar:
    path = tmp_path / "trade_dates.csv"
    path.write_text(
        "date,is_open,source\n"
        "2026-07-03,1,test\n"
        "2026-07-04,0,test\n"
        "2026-07-05,0,test\n"
        "2026-07-06,1,test\n",
        encoding="utf-8",
    )
    return CachedAShareCalendar.from_csv(path)


def test_effective_candle_time_uses_same_trading_day_before_close(tmp_path) -> None:
    result = effective_candle_time_for_publish_time(
        "2026-07-03T14:59:00+08:00",
        _calendar(tmp_path),
    )

    assert result == "2026-07-03 00:00:00+00:00"


def test_effective_candle_time_moves_after_close_to_next_trading_day(tmp_path) -> None:
    result = effective_candle_time_for_publish_time(
        "2026-07-03T19:30:00+08:00",
        _calendar(tmp_path),
    )

    assert result == "2026-07-06 00:00:00+00:00"


def test_effective_candle_time_moves_closed_day_to_next_trading_day(tmp_path) -> None:
    result = effective_candle_time_for_publish_time(
        "2026-07-04T10:00:00+08:00",
        _calendar(tmp_path),
    )

    assert result == "2026-07-06 00:00:00+00:00"


def test_is_available_at_uses_publish_time_not_ingest_time() -> None:
    assert is_available_at("2026-07-07T09:00:00+08:00", "2026-07-07T10:00:00+08:00")
    assert not is_available_at(
        "2026-07-07T11:00:00+08:00",
        "2026-07-07T10:00:00+08:00",
    )
    assert is_available_at(None, "2026-07-07T10:00:00+08:00")
```

- [ ] **Step 2: Write model validation tests**

Create initial `freqtrade/tests/research/test_side_data_store.py`:

```python
import pytest
from pydantic import ValidationError

from freqtrade.research.side_data.models import ResearchDocument, ResearchEvent


def test_research_event_requires_stable_identity_and_effective_time() -> None:
    event = ResearchEvent(
        event_id="a-share-limit-pool:2026-07-07:600519.SH:limit_up",
        dataset="limit_pool",
        market="a_share",
        instrument="600519.SH",
        event_type="limit_up",
        event_time="2026-07-07T15:00:00+08:00",
        publish_time="2026-07-07T15:05:00+08:00",
        ingest_time="2026-07-07T16:00:00+08:00",
        effective_candle_time="2026-07-08 00:00:00+00:00",
        title="Limit up",
        source="eastmoney",
        payload={"reason": "sector theme"},
    )

    assert event.schema_version == 1
    assert event.instrument == "600519.SH"
    assert event.payload["reason"] == "sector theme"


def test_research_document_rejects_invalid_market() -> None:
    with pytest.raises(ValidationError):
        ResearchDocument(
            document_id="bad",
            dataset="announcements",
            market="crypto",
            instrument="600519.SH",
            document_type="announcement",
            title="Announcement",
            publish_time="2026-07-07T19:30:00+08:00",
            ingest_time="2026-07-07T20:00:00+08:00",
            effective_candle_time="2026-07-08 00:00:00+00:00",
            source="cninfo",
        )
```

- [ ] **Step 3: Implement side-data models**

Create `freqtrade/freqtrade/research/side_data/models.py`:

```python
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator


ResearchSideDataKind = Literal["feature", "event", "document"]
ResearchSideDataScope = Literal["instrument", "market", "sector"]
ResearchSideDataFormat = Literal["csv", "jsonl"]


class ResearchDatasetDescriptor(BaseModel):
    dataset_id: str
    kind: ResearchSideDataKind
    market: Literal["a_share"] = "a_share"
    scope: ResearchSideDataScope
    storage_format: ResearchSideDataFormat
    timeframe: str | None = None
    available: bool = False
    start: str | None = None
    stop: str | None = None
    provider: str | None = None
    provider_version: str | None = None
    manifest_run_id: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ResearchSideLayerSelection(BaseModel):
    features: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)


class ResearchEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    event_id: str
    dataset: str
    market: Literal["a_share"]
    instrument: str
    event_type: str
    event_time: str
    publish_time: str
    ingest_time: str
    effective_candle_time: str
    title: str
    payload: dict[str, Any] = Field(default_factory=dict)
    source: str

    @field_validator("event_time", "publish_time", "ingest_time", "effective_candle_time")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        pd.to_datetime(value, utc=True)
        return value


class ResearchDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    document_id: str
    dataset: str
    market: Literal["a_share"]
    instrument: str
    document_type: str
    title: str
    publish_time: str
    ingest_time: str
    effective_candle_time: str
    url: str | None = None
    source: str
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("publish_time", "ingest_time", "effective_candle_time")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        pd.to_datetime(value, utc=True)
        return value


ResearchFeatureFrame = pd.DataFrame
```

- [ ] **Step 4: Implement alignment helpers**

Create `freqtrade/freqtrade/research/side_data/alignment.py`:

```python
from datetime import time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from freqtrade.markets import CachedAShareCalendar


_ASIA_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MARKET_CLOSE = time(15, 0)


def candle_time_for_trading_date(value: Any) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        trading_date = timestamp.tz_convert(_ASIA_SHANGHAI).date()
    else:
        trading_date = timestamp.date()
    return str(pd.Timestamp(trading_date, tz="UTC"))


def effective_candle_time_for_publish_time(
    value: Any,
    calendar: CachedAShareCalendar | None,
) -> str:
    timestamp = pd.to_datetime(value, utc=True).tz_convert(_ASIA_SHANGHAI)
    publish_date = timestamp.date()
    if calendar is None:
        return str(pd.Timestamp(publish_date, tz="UTC"))

    if calendar.is_trading_day(publish_date) and timestamp.time() <= _MARKET_CLOSE:
        effective_date = publish_date
    else:
        effective_date = calendar.next_trading_day(publish_date)
    return str(pd.Timestamp(effective_date, tz="UTC"))


def is_available_at(publish_time: object | None, decision_time: object) -> bool:
    if publish_time is None or publish_time == "":
        return True
    return pd.to_datetime(publish_time, utc=True) <= pd.to_datetime(decision_time, utc=True)
```

- [ ] **Step 5: Implement side-data provenance lookup**

Create `freqtrade/freqtrade/research/side_data/provenance.py`:

```python
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def find_side_data_provenance(root: Path, artifact_path: str) -> dict[str, Any]:
    manifest_dir = root / ".manifests"
    best: tuple[datetime | None, str, Path, dict[str, Any], dict[str, Any]] | None = None
    if manifest_dir.is_dir():
        for path in manifest_dir.glob("*.json"):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            created_at_text = str(manifest.get("created_at", ""))
            parsed_created_at = _parse_created_at(manifest.get("created_at"))
            for file_summary in manifest.get("files", []):
                if file_summary.get("path") != artifact_path or file_summary.get("status") != "ok":
                    continue
                candidate = (parsed_created_at, created_at_text, path, manifest, file_summary)
                if best is None or _is_better(candidate, best):
                    best = candidate

    if best is None:
        return {"artifact_path": artifact_path, "manifest_run_id": None}

    _, _, manifest_path, manifest, file_summary = best
    return {
        "artifact_path": artifact_path,
        "manifest_run_id": manifest.get("run_id"),
        "manifest_path": str(manifest_path.relative_to(root)),
        "provider": manifest.get("provider"),
        "provider_version": manifest.get("provider_version"),
        "rows": file_summary.get("rows"),
        "start": file_summary.get("start"),
        "stop": file_summary.get("stop"),
        "dataset": file_summary.get("dataset"),
        "kind": file_summary.get("kind"),
        "created_at": manifest.get("created_at"),
        "warnings": file_summary.get("warnings") or [],
    }


def _parse_created_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _is_better(
    candidate: tuple[datetime | None, str, Path, dict[str, Any], dict[str, Any]],
    current: tuple[datetime | None, str, Path, dict[str, Any], dict[str, Any]],
) -> bool:
    candidate_dt, candidate_text, _, _, _ = candidate
    current_dt, current_text, _, _, _ = current
    if candidate_dt is not None:
        if current_dt is None:
            return True
        if candidate_dt != current_dt:
            return candidate_dt > current_dt
    elif current_dt is not None:
        return False
    return candidate_text > current_text
```

- [ ] **Step 6: Export side-data primitives**

Create `freqtrade/freqtrade/research/side_data/__init__.py`:

```python
from freqtrade.research.side_data.alignment import (
    candle_time_for_trading_date,
    effective_candle_time_for_publish_time,
    is_available_at,
)
from freqtrade.research.side_data.models import (
    ResearchDatasetDescriptor,
    ResearchDocument,
    ResearchEvent,
    ResearchFeatureFrame,
    ResearchSideLayerSelection,
)

__all__ = [
    "ResearchDatasetDescriptor",
    "ResearchDocument",
    "ResearchEvent",
    "ResearchFeatureFrame",
    "ResearchSideLayerSelection",
    "candle_time_for_trading_date",
    "effective_candle_time_for_publish_time",
    "is_available_at",
]
```

- [ ] **Step 7: Verify Task 2**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_side_data_alignment.py tests/research/test_side_data_store.py -q
.\.venv\Scripts\python -m ruff check freqtrade/research/side_data tests/research/test_side_data_alignment.py tests/research/test_side_data_store.py
```

Expected: PASS and ruff clean.

---

## Task 3: Local Side-Data Store And Dataset Discovery

**Files:**
- Create: `freqtrade/freqtrade/research/side_data/store.py`
- Modify: `freqtrade/tests/research/test_side_data_store.py`

**Interfaces:**
- Consumes: `ResearchDatasetDescriptor`, `ResearchEvent`, `ResearchDocument`, `find_side_data_provenance`
- Produces: `LocalResearchSideDataStore(root: Path, enabled_datasets: list[str] | None = None)`
- Produces: `LocalResearchSideDataStore.list_datasets(instrument_key: str | None = None, kind: str | None = None) -> list[ResearchDatasetDescriptor]`
- Produces: `LocalResearchSideDataStore.load_feature_frame(instrument_key: str, datasets: list[str]) -> pd.DataFrame`
- Produces: `LocalResearchSideDataStore.load_events(instrument_key: str, datasets: list[str]) -> list[ResearchEvent]`
- Produces: `LocalResearchSideDataStore.load_documents(instrument_key: str, datasets: list[str]) -> list[ResearchDocument]`

- [ ] **Step 1: Add store tests for feature/event/document artifacts**

Append to `freqtrade/tests/research/test_side_data_store.py`:

```python
from pathlib import Path

from freqtrade.research.side_data.store import LocalResearchSideDataStore


def _write_side_data_fixture(root: Path) -> None:
    (root / "features" / "fund_flow_daily").mkdir(parents=True)
    (root / "events" / "limit_pool").mkdir(parents=True)
    (root / "documents" / "announcements").mkdir(parents=True)
    (root / "features" / "fund_flow_daily" / "600519.SH.csv").write_text(
        "date,instrument,main_net_inflow,large_net_inflow,medium_net_inflow,"
        "small_net_inflow,source,publish_time,ingest_time\n"
        "2026-07-07,600519.SH,1000,800,100,100,eastmoney,"
        "2026-07-07T15:30:00+08:00,2026-07-07T16:00:00+08:00\n",
        encoding="utf-8",
    )
    (root / "events" / "limit_pool" / "2026-07-07.jsonl").write_text(
        '{"schema_version":1,"event_id":"limit:2026-07-07:600519.SH",'
        '"dataset":"limit_pool","market":"a_share","instrument":"600519.SH",'
        '"event_type":"limit_up","event_time":"2026-07-07T15:00:00+08:00",'
        '"publish_time":"2026-07-07T15:05:00+08:00",'
        '"ingest_time":"2026-07-07T16:00:00+08:00",'
        '"effective_candle_time":"2026-07-07 00:00:00+00:00",'
        '"title":"Limit up","payload":{"reason":"theme"},"source":"eastmoney"}\n',
        encoding="utf-8",
    )
    (root / "documents" / "announcements" / "600519.SH.jsonl").write_text(
        '{"schema_version":1,"document_id":"cninfo:600519.SH:1",'
        '"dataset":"announcements","market":"a_share","instrument":"600519.SH",'
        '"document_type":"announcement","title":"Announcement",'
        '"publish_time":"2026-07-07T19:30:00+08:00",'
        '"ingest_time":"2026-07-07T20:00:00+08:00",'
        '"effective_candle_time":"2026-07-08 00:00:00+00:00",'
        '"url":"https://example.invalid/a.pdf","source":"cninfo","payload":{"category":"notice"}}\n',
        encoding="utf-8",
    )


def test_local_side_data_store_lists_available_datasets(tmp_path) -> None:
    _write_side_data_fixture(tmp_path)
    store = LocalResearchSideDataStore(tmp_path)

    datasets = store.list_datasets(instrument_key="600519.SH")

    assert [item.dataset_id for item in datasets] == [
        "fund_flow_daily",
        "limit_pool",
        "announcements",
    ]
    assert datasets[0].kind == "feature"
    assert datasets[0].available is True


def test_local_side_data_store_loads_feature_frame(tmp_path) -> None:
    _write_side_data_fixture(tmp_path)
    store = LocalResearchSideDataStore(tmp_path)

    frame = store.load_feature_frame("600519.SH", ["fund_flow_daily"])

    assert list(frame.columns) == [
        "date",
        "instrument",
        "feature_fund_flow_daily_main_net_inflow",
        "feature_fund_flow_daily_large_net_inflow",
        "feature_fund_flow_daily_medium_net_inflow",
        "feature_fund_flow_daily_small_net_inflow",
        "source",
        "publish_time",
        "ingest_time",
    ]
    assert frame.iloc[0]["feature_fund_flow_daily_main_net_inflow"] == 1000.0


def test_local_side_data_store_loads_events_and_documents(tmp_path) -> None:
    _write_side_data_fixture(tmp_path)
    store = LocalResearchSideDataStore(tmp_path)

    events = store.load_events("600519.SH", ["limit_pool"])
    documents = store.load_documents("600519.SH", ["announcements"])

    assert events[0].event_type == "limit_up"
    assert events[0].payload == {"reason": "theme"}
    assert documents[0].document_type == "announcement"
    assert documents[0].title == "Announcement"


def test_local_side_data_store_rejects_unknown_dataset(tmp_path) -> None:
    store = LocalResearchSideDataStore(tmp_path)

    try:
        store.load_feature_frame("600519.SH", ["unknown"])
    except ValueError as exc:
        assert str(exc) == "Unknown research side dataset: unknown"
    else:
        raise AssertionError("Expected unknown dataset to be rejected")
```

- [ ] **Step 2: Run store tests and confirm failure**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_side_data_store.py -q
```

Expected: FAIL because `LocalResearchSideDataStore` does not exist.

- [ ] **Step 3: Implement local store**

Create `freqtrade/freqtrade/research/side_data/store.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pandas as pd

from freqtrade.markets import MarketType, parse_instrument_key
from freqtrade.research.side_data.models import (
    ResearchDatasetDescriptor,
    ResearchDocument,
    ResearchEvent,
)
from freqtrade.research.side_data.provenance import find_side_data_provenance


_FEATURE_DATASETS = {"fund_flow_daily"}
_EVENT_DATASETS = {"limit_pool"}
_DOCUMENT_DATASETS = {"announcements"}
_ALL_DATASETS = _FEATURE_DATASETS | _EVENT_DATASETS | _DOCUMENT_DATASETS


class LocalResearchSideDataStore:
    def __init__(self, root: Path, enabled_datasets: list[str] | None = None) -> None:
        self.root = root
        self.enabled_datasets = set(enabled_datasets or _ALL_DATASETS)

    def list_datasets(
        self,
        instrument_key: str | None = None,
        kind: Literal["feature", "event", "document"] | None = None,
    ) -> list[ResearchDatasetDescriptor]:
        instrument = _normalize_instrument(instrument_key) if instrument_key else None
        descriptors = [
            self._feature_descriptor("fund_flow_daily", instrument),
            self._event_descriptor("limit_pool", instrument),
            self._document_descriptor("announcements", instrument),
        ]
        return [
            descriptor
            for descriptor in descriptors
            if descriptor.dataset_id in self.enabled_datasets
            and (kind is None or descriptor.kind == kind)
        ]

    def load_feature_frame(self, instrument_key: str, datasets: list[str]) -> pd.DataFrame:
        instrument = _normalize_instrument(instrument_key)
        frames = []
        for dataset in datasets:
            self._require_dataset(dataset, _FEATURE_DATASETS)
            path = self._feature_path(dataset, instrument)
            if not path.is_file():
                raise FileNotFoundError(path)
            frame = pd.read_csv(path)
            frame = _normalize_feature_frame(dataset, frame)
            frames.append(frame)
        if not frames:
            return pd.DataFrame({"date": pd.Series(dtype="datetime64[ns, UTC]")})
        result = frames[0]
        for frame in frames[1:]:
            result = result.merge(frame, on=["date", "instrument"], how="outer")
        return result.sort_values("date").reset_index(drop=True)

    def load_events(self, instrument_key: str, datasets: list[str]) -> list[ResearchEvent]:
        instrument = _normalize_instrument(instrument_key)
        events = []
        for dataset in datasets:
            self._require_dataset(dataset, _EVENT_DATASETS)
            for path in sorted((self.root / "events" / dataset).glob("*.jsonl")):
                for record in _read_jsonl(path):
                    event = ResearchEvent(**record)
                    if event.instrument == instrument:
                        events.append(event)
        return sorted(events, key=lambda item: (item.effective_candle_time, item.event_id))

    def load_documents(self, instrument_key: str, datasets: list[str]) -> list[ResearchDocument]:
        instrument = _normalize_instrument(instrument_key)
        documents = []
        for dataset in datasets:
            self._require_dataset(dataset, _DOCUMENT_DATASETS)
            path = self._document_path(dataset, instrument)
            if not path.is_file():
                raise FileNotFoundError(path)
            for record in _read_jsonl(path):
                document = ResearchDocument(**record)
                if document.instrument == instrument:
                    documents.append(document)
        return sorted(documents, key=lambda item: (item.effective_candle_time, item.document_id))

    def _feature_descriptor(
        self,
        dataset: str,
        instrument: str | None,
    ) -> ResearchDatasetDescriptor:
        path = self._feature_path(dataset, instrument or "600519.SH")
        return self._descriptor(dataset, "feature", "instrument", "csv", path if instrument else None)

    def _event_descriptor(
        self,
        dataset: str,
        instrument: str | None,
    ) -> ResearchDatasetDescriptor:
        event_root = self.root / "events" / dataset
        path = next(iter(sorted(event_root.glob("*.jsonl"))), None) if event_root.is_dir() else None
        return self._descriptor(dataset, "event", "market", "jsonl", path)

    def _document_descriptor(
        self,
        dataset: str,
        instrument: str | None,
    ) -> ResearchDatasetDescriptor:
        path = self._document_path(dataset, instrument or "600519.SH")
        return self._descriptor(dataset, "document", "instrument", "jsonl", path if instrument else None)

    def _descriptor(
        self,
        dataset: str,
        kind: Literal["feature", "event", "document"],
        scope: Literal["instrument", "market", "sector"],
        storage_format: Literal["csv", "jsonl"],
        path: Path | None,
    ) -> ResearchDatasetDescriptor:
        provenance = (
            find_side_data_provenance(self.root, str(path.relative_to(self.root)).replace("\\", "/"))
            if path is not None and path.is_file()
            else {}
        )
        return ResearchDatasetDescriptor(
            dataset_id=dataset,
            kind=kind,
            scope=scope,
            storage_format=storage_format,
            timeframe="1d" if kind == "feature" else None,
            available=path is not None and path.is_file(),
            start=provenance.get("start"),
            stop=provenance.get("stop"),
            provider=provenance.get("provider"),
            provider_version=provenance.get("provider_version"),
            manifest_run_id=provenance.get("manifest_run_id"),
            warnings=provenance.get("warnings") or [],
        )

    def _feature_path(self, dataset: str, instrument: str) -> Path:
        return (self.root / "features" / dataset / f"{instrument}.csv").resolve()

    def _document_path(self, dataset: str, instrument: str) -> Path:
        return (self.root / "documents" / dataset / f"{instrument}.jsonl").resolve()

    def _require_dataset(self, dataset: str, allowed: set[str]) -> None:
        if dataset not in _ALL_DATASETS or dataset not in self.enabled_datasets:
            raise ValueError(f"Unknown research side dataset: {dataset}")
        if dataset not in allowed:
            raise ValueError(f"Research side dataset {dataset} has incompatible kind")


def _normalize_instrument(instrument_key: str) -> str:
    return parse_instrument_key(instrument_key, market=MarketType.A_SHARE).key


def _normalize_feature_frame(dataset: str, frame: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "instrument", "source", "publish_time", "ingest_time"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Missing side feature columns: {sorted(missing)}")
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"], utc=True)
    value_columns = [column for column in frame.columns if column not in required]
    rename = {column: f"feature_{dataset}_{column}" for column in value_columns}
    frame = frame.rename(columns=rename)
    for column in rename.values():
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
    return frame


def _read_jsonl(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records
```

- [ ] **Step 4: Verify Task 3**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_side_data_store.py -q
.\.venv\Scripts\python -m ruff check freqtrade/research/side_data tests/research/test_side_data_store.py
```

Expected: PASS and ruff clean.

---

## Task 4: Research API Schemas And Dataset Route

**Files:**
- Modify: `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
- Modify: `freqtrade/freqtrade/rpc/api_server/api_research.py`
- Test: `freqtrade/tests/rpc/test_api_research.py`

**Interfaces:**
- Consumes: `ResearchSideLayerSelection`, `LocalResearchSideDataStore`
- Produces: `ResearchDatasetsResponse`
- Produces: `GET /api/v1/research/datasets`
- Produces: `ResearchChartCandlesRequest.side_layers: ResearchSideLayerSelection | None`
- Produces: extended chart source literals: `feature`, `event`, `document`

- [ ] **Step 1: Add API tests for dataset listing and source literals**

Append to `freqtrade/tests/rpc/test_api_research.py`:

```python
def test_research_datasets_lists_local_side_data(default_conf, tmp_path, mocker) -> None:
    side_root = tmp_path / "research_data" / "a_share_meta"
    (side_root / "features" / "fund_flow_daily").mkdir(parents=True)
    (side_root / "features" / "fund_flow_daily" / "600519.SH.csv").write_text(
        "date,instrument,main_net_inflow,large_net_inflow,medium_net_inflow,"
        "small_net_inflow,source,publish_time,ingest_time\n"
        "2026-07-07,600519.SH,1000,800,100,100,eastmoney,"
        "2026-07-07T15:30:00+08:00,2026-07-07T16:00:00+08:00\n",
        encoding="utf-8",
    )
    with make_research_client(
        default_conf,
        tmp_path,
        mocker,
        research_bots=[
            {
                "id": "a-share-local",
                "label": "A Share Local",
                "market": "a_share",
                "data_source": {"type": "local_csv", "root": "research_data/a_share"},
                "side_data": {
                    "root": "research_data/a_share_meta",
                    "enabled_datasets": ["fund_flow_daily"],
                },
            }
        ],
    ) as client:
        response = client_get(
            client,
            f"{BASE_URI}/research/datasets?bot_id=a-share-local&instrument=600519.SH",
        )

    assert response.status_code == 200
    body = response.json()
    assert body["datasets"][0]["dataset_id"] == "fund_flow_daily"
    assert body["datasets"][0]["kind"] == "feature"
    assert body["datasets"][0]["available"] is True


def test_research_datasets_returns_empty_without_side_data_config(research_client) -> None:
    response = client_get(
        research_client,
        f"{BASE_URI}/research/datasets?bot_id=a-share-local&instrument=600519.SH",
    )

    assert response.status_code == 200
    assert response.json() == {"datasets": []}
```

- [ ] **Step 2: Run dataset API tests and confirm failure**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/rpc/test_api_research.py::test_research_datasets_lists_local_side_data tests/rpc/test_api_research.py::test_research_datasets_returns_empty_without_side_data_config -q
```

Expected: FAIL because `/research/datasets` does not exist.

- [ ] **Step 3: Extend API schemas**

Modify `freqtrade/freqtrade/rpc/api_server/api_schemas.py`:

```python
class ResearchSideLayerRequest(BaseModel):
    features: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)
```

Add to `ResearchChartCandlesRequest`:

```python
    side_layers: ResearchSideLayerRequest | None = None
```

Add response models:

```python
class ResearchDatasetResponse(BaseModel):
    dataset_id: str
    kind: Literal["feature", "event", "document"]
    market: Literal["a_share"]
    scope: Literal["instrument", "market", "sector"]
    storage_format: Literal["csv", "jsonl"]
    timeframe: str | None = None
    available: bool = False
    start: str | None = None
    stop: str | None = None
    provider: str | None = None
    provider_version: str | None = None
    manifest_run_id: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ResearchDatasetsResponse(BaseModel):
    datasets: list[ResearchDatasetResponse]
```

Extend the `source` literal in both `ChartSeriesMeta` and `ChartLayerMeta`:

```python
        "feature",
        "event",
        "document",
```

- [ ] **Step 4: Add dataset route**

Modify imports in `freqtrade/freqtrade/rpc/api_server/api_research.py`:

```python
from typing import Literal

from freqtrade.research.side_data.store import LocalResearchSideDataStore
from freqtrade.rpc.api_server.api_schemas import ResearchDatasetsResponse
```

Add helper:

```python
def _create_side_data_store(profile: ResearchBotProfile) -> LocalResearchSideDataStore | None:
    if profile.side_data is None or profile.side_data_root is None:
        return None
    return LocalResearchSideDataStore(
        profile.side_data_root,
        enabled_datasets=profile.side_data.enabled_datasets,
    )
```

Add route:

```python
@router.get("/research/datasets", response_model=ResearchDatasetsResponse)
def research_datasets(
    bot_id: str,
    instrument: str | None = None,
    kind: Literal["feature", "event", "document"] | None = None,
    config=Depends(get_config),
):
    profile = _get_research_profile(config, bot_id)
    try:
        store = _create_side_data_store(profile)
        if store is None:
            return {"datasets": []}
        return {
            "datasets": [
                descriptor.model_dump(mode="json")
                for descriptor in store.list_datasets(instrument_key=instrument, kind=kind)
            ]
        }
    except ResearchConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid research dataset request")
```

- [ ] **Step 5: Verify Task 4**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/rpc/test_api_research.py -q
.\.venv\Scripts\python -m ruff check freqtrade/rpc/api_server/api_research.py freqtrade/rpc/api_server/api_schemas.py tests/rpc/test_api_research.py
```

Expected: PASS and ruff clean.

---

## Task 5: Backend Chart Side Layers

**Files:**
- Create: `freqtrade/freqtrade/research/side_data/chart_layers.py`
- Modify: `freqtrade/freqtrade/research/chart.py`
- Test: `freqtrade/tests/research/test_side_data_chart_layers.py`
- Test: `freqtrade/tests/research/test_chart.py`
- Test: `freqtrade/tests/rpc/test_api_research.py`

**Interfaces:**
- Consumes: `LocalResearchSideDataStore`, `ResearchSideLayerSelection`
- Produces: `apply_side_data_chart_layers(dataframe, store, instrument_key, selection) -> tuple[pd.DataFrame, dict[str, Any], list[ChartLayerMeta]]`
- Produces: feature columns using `feature_{dataset_id}_{field}`
- Produces: event/document layers using `ChartLayerPoint`

- [ ] **Step 1: Write chart layer unit tests**

Create `freqtrade/tests/research/test_side_data_chart_layers.py`:

```python
import pandas as pd

from freqtrade.research.side_data.chart_layers import apply_side_data_chart_layers
from freqtrade.research.side_data.models import ResearchSideLayerSelection
from freqtrade.research.side_data.store import LocalResearchSideDataStore


def test_apply_side_data_chart_layers_adds_feature_columns_and_event_points(tmp_path) -> None:
    (tmp_path / "features" / "fund_flow_daily").mkdir(parents=True)
    (tmp_path / "events" / "limit_pool").mkdir(parents=True)
    (tmp_path / "features" / "fund_flow_daily" / "600519.SH.csv").write_text(
        "date,instrument,main_net_inflow,large_net_inflow,medium_net_inflow,"
        "small_net_inflow,source,publish_time,ingest_time\n"
        "2026-07-07,600519.SH,1000,800,100,100,eastmoney,"
        "2026-07-07T15:30:00+08:00,2026-07-07T16:00:00+08:00\n",
        encoding="utf-8",
    )
    (tmp_path / "events" / "limit_pool" / "2026-07-07.jsonl").write_text(
        '{"schema_version":1,"event_id":"limit:2026-07-07:600519.SH",'
        '"dataset":"limit_pool","market":"a_share","instrument":"600519.SH",'
        '"event_type":"limit_up","event_time":"2026-07-07T15:00:00+08:00",'
        '"publish_time":"2026-07-07T15:05:00+08:00",'
        '"ingest_time":"2026-07-07T16:00:00+08:00",'
        '"effective_candle_time":"2026-07-07 00:00:00+00:00",'
        '"title":"Limit up","payload":{"reason":"theme"},"source":"eastmoney"}\n',
        encoding="utf-8",
    )
    dataframe = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-06", "2026-07-07"], utc=True),
            "open": [1.0, 1.0],
            "high": [1.0, 1.0],
            "low": [1.0, 1.0],
            "close": [1.0, 1.0],
            "volume": [1000.0, 1000.0],
        }
    )

    result, plot_update, layers = apply_side_data_chart_layers(
        dataframe,
        LocalResearchSideDataStore(tmp_path),
        "600519.SH",
        ResearchSideLayerSelection(features=["fund_flow_daily"], events=["limit_pool"]),
    )

    assert "feature_fund_flow_daily_main_net_inflow" in result.columns
    assert pd.isna(result.iloc[0]["feature_fund_flow_daily_main_net_inflow"])
    assert result.iloc[1]["feature_fund_flow_daily_main_net_inflow"] == 1000.0
    assert plot_update["subplots"]["Fund Flow"]["feature_fund_flow_daily_main_net_inflow"]["type"] == "bar"
    assert [layer.source for layer in layers] == ["feature", "event"]
    assert layers[1].points[0].payload["reason"] == "theme"
```

- [ ] **Step 2: Run chart layer tests and confirm failure**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_side_data_chart_layers.py -q
```

Expected: FAIL because `chart_layers.py` does not exist.

- [ ] **Step 3: Implement chart layer helpers**

Create `freqtrade/freqtrade/research/side_data/chart_layers.py`:

```python
from __future__ import annotations

from typing import Any

import pandas as pd
from pandas import DataFrame

from freqtrade.research.side_data.models import ResearchDocument, ResearchEvent, ResearchSideLayerSelection
from freqtrade.research.side_data.store import LocalResearchSideDataStore
from freqtrade.rpc.api_server.api_schemas import (
    ChartLayerMeta,
    ChartLayerPoint,
    ChartSeriesCoverage,
    ChartSeriesMeta,
)


def apply_side_data_chart_layers(
    dataframe: DataFrame,
    store: LocalResearchSideDataStore,
    instrument_key: str,
    selection: ResearchSideLayerSelection,
) -> tuple[DataFrame, dict[str, Any], list[ChartLayerMeta]]:
    result = dataframe.copy()
    plot_update: dict[str, Any] = {"main_plot": {}, "subplots": {}}
    layers: list[ChartLayerMeta] = []

    if selection.features:
        feature_frame = store.load_feature_frame(instrument_key, selection.features)
        result, feature_columns = _merge_feature_frame(result, feature_frame)
        plot_update["subplots"]["Fund Flow"] = {
            column: {"type": "bar"} for column in feature_columns
        }
        layers.extend(_feature_layers(result, selection.features, feature_columns))

    if selection.events:
        events = store.load_events(instrument_key, selection.events)
        layers.extend(_event_layers(events, selection.events))

    if selection.documents:
        documents = store.load_documents(instrument_key, selection.documents)
        layers.extend(_document_layers(documents, selection.documents))

    return result, plot_update, layers


def _merge_feature_frame(
    dataframe: DataFrame,
    feature_frame: DataFrame,
) -> tuple[DataFrame, list[str]]:
    if feature_frame.empty:
        return dataframe, []
    left = dataframe.copy()
    left["date"] = pd.to_datetime(left["date"], utc=True)
    right = feature_frame.copy()
    right["date"] = pd.to_datetime(right["date"], utc=True)
    feature_columns = [column for column in right.columns if column.startswith("feature_")]
    merged = left.merge(right[["date", *feature_columns]], on="date", how="left")
    for column in feature_columns:
        merged[column] = merged[column].where(merged[column].notna(), None)
    return merged, feature_columns


def _feature_layers(
    dataframe: DataFrame,
    datasets: list[str],
    feature_columns: list[str],
) -> list[ChartLayerMeta]:
    if not feature_columns:
        return []
    return [
        ChartLayerMeta(
            id=f"feature.{dataset}",
            source="feature",
            status=_feature_layer_status(dataframe, feature_columns),
            label=_label(dataset),
            timeframe="1d",
            alignment="candle_open",
            series=[
                ChartSeriesMeta(
                    column=column,
                    label=_label(column.removeprefix("feature_")),
                    source="feature",
                    kind="bar",
                    panel="fund_flow",
                    timeframe="1d",
                    visible=True,
                    coverage=_coverage(dataframe, column),
                )
                for column in feature_columns
                if column.startswith(f"feature_{dataset}_")
            ],
        )
        for dataset in datasets
    ]


def _event_layers(events: list[ResearchEvent], datasets: list[str]) -> list[ChartLayerMeta]:
    return [
        ChartLayerMeta(
            id=f"event.{dataset}",
            source="event",
            status="ok" if any(event.dataset == dataset for event in events) else "unavailable",
            label=_label(dataset),
            timeframe="1d",
            alignment="effective_candle_time",
            points=[
                ChartLayerPoint(
                    timestamp=_timestamp_ms(event.effective_candle_time),
                    label=event.event_type,
                    payload={
                        "event_type": event.event_type,
                        "title": event.title,
                        "publish_time": event.publish_time,
                        "source": event.source,
                        **event.payload,
                    },
                )
                for event in events
                if event.dataset == dataset
            ],
        )
        for dataset in datasets
    ]


def _document_layers(
    documents: list[ResearchDocument],
    datasets: list[str],
) -> list[ChartLayerMeta]:
    return [
        ChartLayerMeta(
            id=f"document.{dataset}",
            source="document",
            status="ok" if any(document.dataset == dataset for document in documents) else "unavailable",
            label=_label(dataset),
            timeframe="1d",
            alignment="effective_candle_time",
            points=[
                ChartLayerPoint(
                    timestamp=_timestamp_ms(document.effective_candle_time),
                    label=document.document_type,
                    payload={
                        "document_type": document.document_type,
                        "title": document.title,
                        "publish_time": document.publish_time,
                        "source": document.source,
                        "url": document.url,
                        **document.payload,
                    },
                )
                for document in documents
                if document.dataset == dataset
            ],
        )
        for dataset in datasets
    ]


def _coverage(dataframe: DataFrame, column: str) -> ChartSeriesCoverage:
    total = len(dataframe)
    valid = int(dataframe[column].notna().sum()) if column in dataframe.columns else 0
    if valid == 0:
        return ChartSeriesCoverage(total_points=total, reason="no aligned side-data values")
    valid_dates = dataframe.loc[dataframe[column].notna(), "date"]
    return ChartSeriesCoverage(
        first_valid=str(pd.to_datetime(valid_dates.iloc[0], utc=True)),
        last_valid=str(pd.to_datetime(valid_dates.iloc[-1], utc=True)),
        valid_points=valid,
        total_points=total,
        reason="partial coverage" if valid < total else None,
    )


def _feature_layer_status(dataframe: DataFrame, columns: list[str]) -> str:
    return "partial" if any(_coverage(dataframe, column).valid_points < len(dataframe) for column in columns) else "ok"


def _timestamp_ms(value: str) -> int:
    return int(pd.to_datetime(value, utc=True).timestamp() * 1000)


def _label(value: str) -> str:
    return value.replace("_", " ").title()
```

- [ ] **Step 4: Integrate chart helper into research chart**

Modify imports in `freqtrade/freqtrade/research/chart.py`:

```python
from freqtrade.research.side_data.chart_layers import apply_side_data_chart_layers
from freqtrade.research.side_data.models import ResearchSideLayerSelection
from freqtrade.research.side_data.store import LocalResearchSideDataStore
```

In `build_research_chart_candles_response`, after `plot_config = build_watch_plot_config(...)`:

```python
    side_layers = []
    if payload.side_layers and profile.side_data is not None and profile.side_data_root is not None:
        dataframe, side_plot_config, side_layers = apply_side_data_chart_layers(
            dataframe,
            LocalResearchSideDataStore(
                profile.side_data_root,
                enabled_datasets=profile.side_data.enabled_datasets,
            ),
            payload.instrument,
            ResearchSideLayerSelection.model_validate(payload.side_layers.model_dump()),
        )
        _merge_plot_config(plot_config, side_plot_config)
```

Pass `side_layers` into `_build_research_chart_response_meta` and append them:

```python
def _build_research_chart_response_meta(..., side_layers: list[ChartLayerMeta] | None = None) -> ChartResponseMeta:
    layers = [
        _build_market_layer_meta(dataframe, payload.timeframe),
        _build_watch_layer_meta(dataframe, plot_config, payload.timeframe),
        *(side_layers or []),
    ]
```

Add helper:

```python
def _merge_plot_config(target: dict[str, Any], update: dict[str, Any]) -> None:
    for key in ("main_plot", "subplots"):
        target_section = target.setdefault(key, {})
        for name, value in update.get(key, {}).items():
            if isinstance(value, dict) and isinstance(target_section.get(name), dict):
                target_section[name].update(value)
            else:
                target_section[name] = value
```

- [ ] **Step 5: Add API chart side-layer regression**

Append to `freqtrade/tests/rpc/test_api_research.py`:

```python
def test_research_chart_returns_requested_side_layers(default_conf, tmp_path, mocker) -> None:
    side_root = tmp_path / "research_data" / "a_share_meta"
    (side_root / "features" / "fund_flow_daily").mkdir(parents=True)
    (side_root / "events" / "limit_pool").mkdir(parents=True)
    (side_root / "features" / "fund_flow_daily" / "600519.SH.csv").write_text(
        "date,instrument,main_net_inflow,large_net_inflow,medium_net_inflow,"
        "small_net_inflow,source,publish_time,ingest_time\n"
        "2026-07-07,600519.SH,1000,800,100,100,eastmoney,"
        "2026-07-07T15:30:00+08:00,2026-07-07T16:00:00+08:00\n",
        encoding="utf-8",
    )
    (side_root / "events" / "limit_pool" / "2026-07-07.jsonl").write_text(
        '{"schema_version":1,"event_id":"limit:2026-07-07:600519.SH",'
        '"dataset":"limit_pool","market":"a_share","instrument":"600519.SH",'
        '"event_type":"limit_up","event_time":"2026-07-07T15:00:00+08:00",'
        '"publish_time":"2026-07-07T15:05:00+08:00",'
        '"ingest_time":"2026-07-07T16:00:00+08:00",'
        '"effective_candle_time":"2026-07-07 00:00:00+00:00",'
        '"title":"Limit up","payload":{"reason":"theme"},"source":"eastmoney"}\n',
        encoding="utf-8",
    )
    with make_research_client(
        default_conf,
        tmp_path,
        mocker,
        research_bots=[
            {
                "id": "a-share-local",
                "label": "A Share Local",
                "market": "a_share",
                "data_source": {"type": "local_csv", "root": "research_data/a_share"},
                "side_data": {
                    "root": "research_data/a_share_meta",
                    "enabled_datasets": ["fund_flow_daily", "limit_pool"],
                },
            }
        ],
    ) as client:
        response = client_post(
            client,
            f"{BASE_URI}/research/chart_candles",
            data={
                "bot_id": "a-share-local",
                "instrument": "600519.SH",
                "timeframe": "1d",
                "limit": 10,
                "side_layers": {"features": ["fund_flow_daily"], "events": ["limit_pool"]},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert "feature_fund_flow_daily_main_net_inflow" in body["columns"]
    sources = [layer["source"] for layer in body["meta"]["layers"]]
    assert "feature" in sources
    assert "event" in sources
```

- [ ] **Step 6: Verify Task 5**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_side_data_chart_layers.py tests/research/test_chart.py tests/rpc/test_api_research.py -q
.\.venv\Scripts\python -m ruff check freqtrade/research tests/research/test_side_data_chart_layers.py tests/research/test_chart.py tests/rpc/test_api_research.py
```

Expected: PASS and ruff clean.

---

## Task 6: Side-Data Collector Core And CLI

**Files:**
- Create: `freqtrade/freqtrade/research/side_data/collectors/a_share_side_data.py`
- Create: `tools/download_a_share_side_data.py`
- Test: `freqtrade/tests/research/test_a_share_side_data_collector.py`

**Interfaces:**
- Produces: `AShareSideDataRequest`
- Produces: `AShareSideDataCollector.collect(request) -> AShareSideDataRunSummary`
- Produces: provider protocol with `fetch_fund_flow_daily`, `fetch_limit_pool`, `fetch_announcements`
- Produces: CLI `tools/download_a_share_side_data.py --config ... --bot-id ... --datasets ... --instruments ... --timerange ...`

- [ ] **Step 1: Write collector tests with a fake provider**

Create `freqtrade/tests/research/test_a_share_side_data_collector.py`:

```python
import json

import pandas as pd

from freqtrade.research.side_data.collectors.a_share_side_data import (
    AShareSideDataCollector,
    AShareSideDataRequest,
)


class FakeSideDataProvider:
    provider_name = "fake"
    provider_version = "1.0"

    def fetch_fund_flow_daily(self, instrument_key: str, start_date: str | None, end_date: str | None):
        return pd.DataFrame(
            {
                "date": ["2026-07-07"],
                "instrument": [instrument_key],
                "main_net_inflow": [1000.0],
                "large_net_inflow": [800.0],
                "medium_net_inflow": [100.0],
                "small_net_inflow": [100.0],
                "source": ["fake"],
                "publish_time": ["2026-07-07T15:30:00+08:00"],
                "ingest_time": ["2026-07-07T16:00:00+08:00"],
            }
        )

    def fetch_limit_pool(self, trade_date: str):
        return [
            {
                "schema_version": 1,
                "event_id": f"limit:{trade_date}:600519.SH",
                "dataset": "limit_pool",
                "market": "a_share",
                "instrument": "600519.SH",
                "event_type": "limit_up",
                "event_time": f"{trade_date}T15:00:00+08:00",
                "publish_time": f"{trade_date}T15:05:00+08:00",
                "ingest_time": f"{trade_date}T16:00:00+08:00",
                "effective_candle_time": f"{trade_date} 00:00:00+00:00",
                "title": "Limit up",
                "payload": {"reason": "theme"},
                "source": "fake",
            }
        ]

    def fetch_announcements(self, instrument_key: str, start_date: str | None, end_date: str | None):
        return [
            {
                "schema_version": 1,
                "document_id": f"fake:{instrument_key}:1",
                "dataset": "announcements",
                "market": "a_share",
                "instrument": instrument_key,
                "document_type": "announcement",
                "title": "Announcement",
                "publish_time": "2026-07-07T19:30:00+08:00",
                "ingest_time": "2026-07-07T20:00:00+08:00",
                "effective_candle_time": "2026-07-08 00:00:00+00:00",
                "url": "https://example.invalid/a.pdf",
                "source": "fake",
                "payload": {"category": "notice"},
            }
        ]


def test_side_data_collector_writes_artifacts_and_manifest(tmp_path) -> None:
    collector = AShareSideDataCollector(tmp_path, FakeSideDataProvider())
    summary = collector.collect(
        AShareSideDataRequest(
            instruments=["600519.SH"],
            datasets=["fund_flow_daily", "limit_pool", "announcements"],
            start_date="2026-07-07",
            end_date="2026-07-07",
        )
    )

    assert summary.failed == 0
    assert (tmp_path / "features" / "fund_flow_daily" / "600519.SH.csv").is_file()
    assert (tmp_path / "events" / "limit_pool" / "2026-07-07.jsonl").is_file()
    assert (tmp_path / "documents" / "announcements" / "600519.SH.jsonl").is_file()
    manifests = list((tmp_path / ".manifests").glob("*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["provider"] == "fake"
    assert manifest["datasets"] == ["fund_flow_daily", "limit_pool", "announcements"]
    assert all(not file_summary["path"].startswith("G:") for file_summary in manifest["files"])
```

- [ ] **Step 2: Run collector test and confirm failure**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_a_share_side_data_collector.py -q
```

Expected: FAIL because collector module does not exist.

- [ ] **Step 3: Implement collector core**

Create `freqtrade/freqtrade/research/side_data/collectors/a_share_side_data.py` with dataclasses, provider protocol, atomic writes, manifest writing, and dataset dispatch:

```python
from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import pandas as pd

from freqtrade.markets import MarketType, parse_instrument_key


class AShareSideDataCollectionError(ValueError):
    pass


@dataclass(frozen=True)
class AShareSideDataRequest:
    instruments: list[str]
    datasets: list[str]
    start_date: str | None = None
    end_date: str | None = None


@dataclass(frozen=True)
class AShareSideDataFileSummary:
    path: str
    dataset: str
    kind: str
    rows: int
    start: str | None
    stop: str | None
    status: str
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class AShareSideDataRunSummary:
    run_id: str
    provider: str
    succeeded: int
    failed: int
    files: list[AShareSideDataFileSummary]
    warnings: list[str]


class AShareSideDataProvider(Protocol):
    provider_name: str
    provider_version: str

    def fetch_fund_flow_daily(
        self,
        instrument_key: str,
        start_date: str | None,
        end_date: str | None,
    ) -> pd.DataFrame: ...

    def fetch_limit_pool(self, trade_date: str) -> list[dict]: ...

    def fetch_announcements(
        self,
        instrument_key: str,
        start_date: str | None,
        end_date: str | None,
    ) -> list[dict]: ...


class AShareSideDataCollector:
    def __init__(self, root: Path, provider: AShareSideDataProvider) -> None:
        self._root = root
        self._provider = provider

    def collect(self, request: AShareSideDataRequest) -> AShareSideDataRunSummary:
        instruments = [
            parse_instrument_key(instrument, market=MarketType.A_SHARE).key
            for instrument in request.instruments
        ]
        created_at = datetime.now(UTC)
        run_id = f"{created_at.strftime('%Y%m%dT%H%M%S%fZ')}-{self._provider.provider_name}-a-share-side-data"
        self._root.mkdir(parents=True, exist_ok=True)
        files: list[AShareSideDataFileSummary] = []
        for dataset in request.datasets:
            if dataset == "fund_flow_daily":
                files.extend(self._collect_fund_flow(instruments, request))
            elif dataset == "limit_pool":
                files.extend(self._collect_limit_pool(request))
            elif dataset == "announcements":
                files.extend(self._collect_announcements(instruments, request))
            else:
                raise AShareSideDataCollectionError(f"Unsupported A-share side dataset: {dataset}")
        succeeded = sum(item.status == "ok" for item in files)
        failed = len(files) - succeeded
        warnings = [warning for item in files for warning in item.warnings]
        summary = AShareSideDataRunSummary(
            run_id=run_id,
            provider=self._provider.provider_name,
            succeeded=succeeded,
            failed=failed,
            files=files,
            warnings=warnings,
        )
        self._write_manifest(run_id, created_at, request, instruments, summary)
        return summary

    def _collect_fund_flow(
        self,
        instruments: list[str],
        request: AShareSideDataRequest,
    ) -> list[AShareSideDataFileSummary]:
        summaries = []
        for instrument in instruments:
            artifact_path = f"features/fund_flow_daily/{instrument}.csv"
            try:
                frame = self._provider.fetch_fund_flow_daily(
                    instrument,
                    request.start_date,
                    request.end_date,
                )
                required = {
                    "date",
                    "instrument",
                    "main_net_inflow",
                    "large_net_inflow",
                    "medium_net_inflow",
                    "small_net_inflow",
                    "source",
                    "publish_time",
                    "ingest_time",
                }
                missing = required - set(frame.columns)
                if missing:
                    raise AShareSideDataCollectionError(
                        f"Missing fund flow columns: {sorted(missing)}"
                    )
                _write_csv_atomic(frame, self._root / artifact_path)
                summaries.append(_ok_file_summary(artifact_path, "fund_flow_daily", "feature", frame))
            except Exception as exc:
                summaries.append(_error_file_summary(artifact_path, "fund_flow_daily", "feature", exc))
        return summaries

    def _collect_limit_pool(self, request: AShareSideDataRequest) -> list[AShareSideDataFileSummary]:
        trade_date = request.end_date or request.start_date
        if trade_date is None:
            raise AShareSideDataCollectionError("limit_pool requires start_date or end_date")
        artifact_path = f"events/limit_pool/{trade_date}.jsonl"
        try:
            records = self._provider.fetch_limit_pool(trade_date)
            _write_jsonl_atomic(records, self._root / artifact_path)
            return [_ok_records_summary(artifact_path, "limit_pool", "event", records)]
        except Exception as exc:
            return [_error_file_summary(artifact_path, "limit_pool", "event", exc)]

    def _collect_announcements(
        self,
        instruments: list[str],
        request: AShareSideDataRequest,
    ) -> list[AShareSideDataFileSummary]:
        summaries = []
        for instrument in instruments:
            artifact_path = f"documents/announcements/{instrument}.jsonl"
            try:
                records = self._provider.fetch_announcements(
                    instrument,
                    request.start_date,
                    request.end_date,
                )
                _write_jsonl_atomic(records, self._root / artifact_path)
                summaries.append(_ok_records_summary(artifact_path, "announcements", "document", records))
            except Exception as exc:
                summaries.append(_error_file_summary(artifact_path, "announcements", "document", exc))
        return summaries

    def _write_manifest(
        self,
        run_id: str,
        created_at: datetime,
        request: AShareSideDataRequest,
        instruments: list[str],
        summary: AShareSideDataRunSummary,
    ) -> None:
        manifest_dir = self._root / ".manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "market": "a_share",
            "provider": self._provider.provider_name,
            "provider_version": self._provider.provider_version,
            "created_at": created_at.isoformat(),
            "datasets": request.datasets,
            "instruments": instruments,
            "timerange": {"start": request.start_date, "end": request.end_date},
            "files": [asdict(file_summary) for file_summary in summary.files],
            "warnings": summary.warnings,
        }
        (manifest_dir / f"{run_id}.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
```

Also add helper functions in the same file:

```python
def _write_csv_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = tempfile.NamedTemporaryFile(delete=False, dir=path.parent, suffix=".tmp")
    temp_path = Path(temp_file.name)
    temp_file.close()
    try:
        frame.to_csv(temp_path, index=False)
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _write_jsonl_atomic(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = tempfile.NamedTemporaryFile(delete=False, dir=path.parent, suffix=".tmp")
    temp_path = Path(temp_file.name)
    temp_file.close()
    try:
        temp_path.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _ok_file_summary(
    artifact_path: str,
    dataset: str,
    kind: str,
    frame: pd.DataFrame,
) -> AShareSideDataFileSummary:
    return AShareSideDataFileSummary(
        path=artifact_path,
        dataset=dataset,
        kind=kind,
        rows=len(frame),
        start=str(frame["date"].iloc[0]) if not frame.empty and "date" in frame else None,
        stop=str(frame["date"].iloc[-1]) if not frame.empty and "date" in frame else None,
        status="ok",
    )


def _ok_records_summary(
    artifact_path: str,
    dataset: str,
    kind: str,
    records: list[dict],
) -> AShareSideDataFileSummary:
    effective_times = [record.get("effective_candle_time") for record in records if record.get("effective_candle_time")]
    return AShareSideDataFileSummary(
        path=artifact_path,
        dataset=dataset,
        kind=kind,
        rows=len(records),
        start=min(effective_times) if effective_times else None,
        stop=max(effective_times) if effective_times else None,
        status="ok",
    )


def _error_file_summary(
    artifact_path: str,
    dataset: str,
    kind: str,
    exc: Exception,
) -> AShareSideDataFileSummary:
    return AShareSideDataFileSummary(
        path=artifact_path,
        dataset=dataset,
        kind=kind,
        rows=0,
        start=None,
        stop=None,
        status="error",
        error=str(exc),
    )
```

- [ ] **Step 4: Add CLI**

Create `tools/download_a_share_side_data.py`:

```python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FREQTRADE_REPO = REPO_ROOT / "freqtrade"
sys.path.insert(0, str(FREQTRADE_REPO))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download A-share side-data artifacts.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--datasets", nargs="+", required=True)
    parser.add_argument("--instruments", nargs="+", required=True)
    parser.add_argument("--timerange")
    args = parser.parse_args(argv)

    config_path = Path(args.config).expanduser().resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if "user_data_dir" not in config:
        config["user_data_dir"] = str(config_path.parent)

    from freqtrade.research import load_research_profiles
    from freqtrade.research.side_data.collectors.a_share_side_data import (
        AShareSideDataCollector,
        AShareSideDataRequest,
    )
    from freqtrade.research.side_data.providers.akshare_side_data import (
        AkshareAshareSideDataProvider,
    )

    profiles = {profile.id: profile for profile in load_research_profiles(config)}
    profile = profiles.get(args.bot_id)
    if profile is None:
        print(f"Unknown research bot: {args.bot_id}", file=sys.stderr)
        return 2
    if profile.side_data_root is None:
        print(f"Research bot has no side_data root: {args.bot_id}", file=sys.stderr)
        return 2

    start_date, end_date = _parse_timerange(args.timerange)
    collector = AShareSideDataCollector(profile.side_data_root, AkshareAshareSideDataProvider())
    summary = collector.collect(
        AShareSideDataRequest(
            instruments=args.instruments,
            datasets=args.datasets,
            start_date=start_date,
            end_date=end_date,
        )
    )
    for file_summary in summary.files:
        print(f"{file_summary.status}: {file_summary.path} rows={file_summary.rows}")
    return 1 if summary.failed else 0


def _parse_timerange(timerange: str | None) -> tuple[str | None, str | None]:
    if not timerange:
        return None, None
    if timerange.count("-") != 1:
        raise ValueError("Timerange must use YYYYMMDD-YYYYMMDD format.")
    start, end = timerange.split("-", maxsplit=1)
    return start or None, end or None


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Verify Task 6**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_a_share_side_data_collector.py -q
.\.venv\Scripts\python -m ruff check freqtrade/research/side_data/collectors tests/research/test_a_share_side_data_collector.py ..\tools\download_a_share_side_data.py
cd G:\AI_Trading\freqtrade-cn
freqtrade\.venv\Scripts\python tools\download_a_share_side_data.py --help
```

Expected: pytest PASS, ruff clean, help command exits `0`.

---

## Task 7: Optional Provider Adapters

**Files:**
- Create: `freqtrade/freqtrade/research/side_data/providers/__init__.py`
- Create: `freqtrade/freqtrade/research/side_data/providers/akshare_side_data.py`
- Create: `freqtrade/freqtrade/research/side_data/providers/a_stock_data_direct.py`
- Test: `freqtrade/tests/research/test_akshare_side_data_provider.py`
- Test: `freqtrade/tests/research/test_a_stock_data_direct_provider.py`

**Interfaces:**
- Consumes: `AShareSideDataProvider`
- Produces: `AkshareAshareSideDataProvider`
- Produces: `AStockDataDirectSideDataProvider`
- Constraint: provider modules may import network libraries; route modules must not import provider modules.

- [ ] **Step 1: Write lazy import tests for akshare provider**

Create `freqtrade/tests/research/test_akshare_side_data_provider.py`:

```python
import pandas as pd

from freqtrade.research.side_data.providers.akshare_side_data import (
    AkshareAshareSideDataProvider,
)


class FakeAkshare:
    def stock_individual_fund_flow(self, stock, market):
        assert stock == "600519"
        assert market == "sh"
        return pd.DataFrame(
            {
                "日期": ["2026-07-07"],
                "主力净流入-净额": [1000.0],
                "大单净流入-净额": [800.0],
                "中单净流入-净额": [100.0],
                "小单净流入-净额": [100.0],
            }
        )

    def stock_zt_pool_em(self, date):
        assert date == "20260707"
        return pd.DataFrame(
            {
                "代码": ["600519"],
                "名称": ["贵州茅台"],
                "涨停统计": ["1/1"],
                "封板资金": [123.0],
                "首次封板时间": ["09:35:00"],
                "最后封板时间": ["14:50:00"],
                "所属行业": ["白酒"],
            }
        )

    def stock_individual_notice_report(self, security, symbol="全部", begin_date=None, end_date=None):
        assert security == "600519"
        return pd.DataFrame(
            {
                "公告标题": ["Announcement"],
                "公告类型": ["重大事项"],
                "公告日期": ["2026-07-07"],
                "网址": ["https://example.invalid/a.pdf"],
            }
        )


def test_akshare_provider_normalizes_fund_flow(mocker) -> None:
    mocker.patch(
        "freqtrade.research.side_data.providers.akshare_side_data.import_module",
        return_value=FakeAkshare(),
    )

    frame = AkshareAshareSideDataProvider().fetch_fund_flow_daily(
        "600519.SH",
        "20260701",
        "20260707",
    )

    assert frame.iloc[0]["instrument"] == "600519.SH"
    assert frame.iloc[0]["main_net_inflow"] == 1000.0
    assert "ingest_time" in frame.columns


def test_akshare_provider_normalizes_limit_pool(mocker) -> None:
    mocker.patch(
        "freqtrade.research.side_data.providers.akshare_side_data.import_module",
        return_value=FakeAkshare(),
    )

    records = AkshareAshareSideDataProvider().fetch_limit_pool("20260707")

    assert records[0]["dataset"] == "limit_pool"
    assert records[0]["instrument"] == "600519.SH"
    assert records[0]["event_type"] == "limit_up"


def test_akshare_provider_normalizes_announcements(mocker) -> None:
    mocker.patch(
        "freqtrade.research.side_data.providers.akshare_side_data.import_module",
        return_value=FakeAkshare(),
    )

    records = AkshareAshareSideDataProvider().fetch_announcements(
        "600519.SH",
        "20260701",
        "20260707",
    )

    assert records[0]["dataset"] == "announcements"
    assert records[0]["document_type"] == "announcement"
    assert records[0]["title"] == "Announcement"
```

- [ ] **Step 2: Implement akshare provider**

Create `freqtrade/freqtrade/research/side_data/providers/akshare_side_data.py`:

```python
from __future__ import annotations

from importlib import import_module, metadata
from typing import Any

import pandas as pd

from freqtrade.markets import MarketType, parse_instrument_key
from freqtrade.research.side_data.alignment import effective_candle_time_for_publish_time


class AkshareAshareSideDataProvider:
    provider_name = "akshare"

    @property
    def provider_version(self) -> str:
        try:
            return metadata.version("akshare")
        except metadata.PackageNotFoundError:
            return "not-installed"

    def fetch_fund_flow_daily(
        self,
        instrument_key: str,
        start_date: str | None,
        end_date: str | None,
    ) -> pd.DataFrame:
        instrument = parse_instrument_key(instrument_key, market=MarketType.A_SHARE)
        akshare = _import_akshare()
        frame = akshare.stock_individual_fund_flow(
            stock=instrument.symbol,
            market="sh" if instrument.venue == "SSE" else "sz",
        )
        frame = frame.rename(
            columns={
                "日期": "date",
                "主力净流入-净额": "main_net_inflow",
                "大单净流入-净额": "large_net_inflow",
                "中单净流入-净额": "medium_net_inflow",
                "小单净流入-净额": "small_net_inflow",
            }
        )
        result = frame[
            ["date", "main_net_inflow", "large_net_inflow", "medium_net_inflow", "small_net_inflow"]
        ].copy()
        result["date"] = pd.to_datetime(result["date"]).dt.strftime("%Y-%m-%d")
        if start_date:
            result = result[result["date"] >= _compact_to_iso(start_date)]
        if end_date:
            result = result[result["date"] <= _compact_to_iso(end_date)]
        result.insert(1, "instrument", instrument.key)
        result["source"] = self.provider_name
        result["publish_time"] = result["date"] + "T15:30:00+08:00"
        result["ingest_time"] = str(pd.Timestamp.now(tz="UTC"))
        return result.reset_index(drop=True)

    def fetch_limit_pool(self, trade_date: str) -> list[dict[str, Any]]:
        akshare = _import_akshare()
        frame = akshare.stock_zt_pool_em(date=trade_date)
        records = []
        trade_date_iso = _compact_to_iso(trade_date)
        for row in frame.to_dict("records"):
            instrument = parse_instrument_key(f"{row['代码']}.SH" if str(row["代码"]).startswith("6") else f"{row['代码']}.SZ", market=MarketType.A_SHARE)
            publish_time = f"{trade_date_iso}T15:05:00+08:00"
            records.append(
                {
                    "schema_version": 1,
                    "event_id": f"akshare:limit_pool:{trade_date_iso}:{instrument.key}:limit_up",
                    "dataset": "limit_pool",
                    "market": "a_share",
                    "instrument": instrument.key,
                    "event_type": "limit_up",
                    "event_time": f"{trade_date_iso}T15:00:00+08:00",
                    "publish_time": publish_time,
                    "ingest_time": str(pd.Timestamp.now(tz="UTC")),
                    "effective_candle_time": effective_candle_time_for_publish_time(publish_time, None),
                    "title": str(row.get("名称", "Limit up")),
                    "payload": {
                        "limit_stat": row.get("涨停统计"),
                        "sealed_amount": _optional_float(row.get("封板资金")),
                        "first_seal_time": row.get("首次封板时间"),
                        "last_seal_time": row.get("最后封板时间"),
                        "industry": row.get("所属行业"),
                    },
                    "source": self.provider_name,
                }
            )
        return records

    def fetch_announcements(
        self,
        instrument_key: str,
        start_date: str | None,
        end_date: str | None,
    ) -> list[dict[str, Any]]:
        instrument = parse_instrument_key(instrument_key, market=MarketType.A_SHARE)
        akshare = _import_akshare()
        frame = akshare.stock_individual_notice_report(
            security=instrument.symbol,
            begin_date=start_date,
            end_date=end_date,
        )
        records = []
        for index, row in enumerate(frame.to_dict("records")):
            publish_time = f"{pd.Timestamp(row['公告日期']).date().isoformat()}T19:30:00+08:00"
            records.append(
                {
                    "schema_version": 1,
                    "document_id": f"akshare:announcement:{instrument.key}:{index}",
                    "dataset": "announcements",
                    "market": "a_share",
                    "instrument": instrument.key,
                    "document_type": "announcement",
                    "title": str(row.get("公告标题", "")),
                    "publish_time": publish_time,
                    "ingest_time": str(pd.Timestamp.now(tz="UTC")),
                    "effective_candle_time": effective_candle_time_for_publish_time(publish_time, None),
                    "url": row.get("网址"),
                    "source": self.provider_name,
                    "payload": {"category": row.get("公告类型")},
                }
            )
        return records


def _import_akshare():
    try:
        return import_module("akshare")
    except ImportError as exc:
        raise RuntimeError(
            "Install optional dependency with `pip install -e .[research_ashare]` before using A-share side-data collectors."
        ) from exc


def _compact_to_iso(value: str) -> str:
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return str(pd.Timestamp(value).date())


def _optional_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)
```

- [ ] **Step 3: Add direct-provider smoke tests for sector membership**

Create `freqtrade/tests/research/test_a_stock_data_direct_provider.py`:

```python
from freqtrade.research.side_data.providers.a_stock_data_direct import (
    AStockDataDirectSideDataProvider,
)


def test_a_stock_data_direct_provider_normalizes_sector_membership(mocker) -> None:
    response = mocker.Mock()
    response.json.return_value = {
        "data": {
            "diff": [
                {"f12": "BK0420", "f14": "白酒", "f3": 1.2, "f128": "600519"},
                {"f12": "BK1000", "f14": "贵州板块", "f3": 0.5, "f128": "600519"},
            ]
        }
    }
    response.raise_for_status.return_value = None
    mocker.patch("requests.Session.get", return_value=response)

    records = AStockDataDirectSideDataProvider().fetch_sector_membership("600519.SH")

    assert records[0]["dataset"] == "sector_membership"
    assert records[0]["instrument"] == "600519.SH"
    assert records[0]["payload"]["sector_name"] == "白酒"
```

- [ ] **Step 4: Implement direct sector provider**

Create `freqtrade/freqtrade/research/side_data/providers/a_stock_data_direct.py`:

```python
from __future__ import annotations

from typing import Any

import pandas as pd
import requests

from freqtrade.markets import MarketType, parse_instrument_key
from freqtrade.research.side_data.alignment import effective_candle_time_for_publish_time


class AStockDataDirectSideDataProvider:
    provider_name = "a-stock-data-direct"
    provider_version = "local"

    def __init__(self) -> None:
        self._session = requests.Session()

    def fetch_sector_membership(self, instrument_key: str) -> list[dict[str, Any]]:
        instrument = parse_instrument_key(instrument_key, market=MarketType.A_SHARE)
        response = self._session.get(
            "https://29.push2.eastmoney.com/api/qt/slist/get",
            params={
                "spt": "3",
                "secid": f"{1 if instrument.venue == 'SSE' else 0}.{instrument.symbol}",
                "fields": "f12,f14,f3,f128",
            },
            timeout=15,
        )
        response.raise_for_status()
        rows = response.json().get("data", {}).get("diff", []) or []
        ingest_time = str(pd.Timestamp.now(tz="UTC"))
        records = []
        for row in rows:
            publish_time = ingest_time
            records.append(
                {
                    "schema_version": 1,
                    "event_id": f"a-stock-data-direct:sector_membership:{instrument.key}:{row.get('f12')}",
                    "dataset": "sector_membership",
                    "market": "a_share",
                    "instrument": instrument.key,
                    "event_type": "sector_membership",
                    "event_time": publish_time,
                    "publish_time": publish_time,
                    "ingest_time": ingest_time,
                    "effective_candle_time": effective_candle_time_for_publish_time(publish_time, None),
                    "title": str(row.get("f14", "")),
                    "payload": {
                        "sector_code": row.get("f12"),
                        "sector_name": row.get("f14"),
                        "change_pct": row.get("f3"),
                        "leading_stock": row.get("f128"),
                    },
                    "source": self.provider_name,
                }
            )
        return records
```

- [ ] **Step 5: Verify Task 7**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_akshare_side_data_provider.py tests/research/test_a_stock_data_direct_provider.py -q
.\.venv\Scripts\python -m ruff check freqtrade/research/side_data/providers tests/research/test_akshare_side_data_provider.py tests/research/test_a_stock_data_direct_provider.py
```

Expected: PASS and ruff clean. These tests must use mocked provider/network objects and must not hit the network.

---

## Task 8: Minimal Frontend Dataset Selection And Point Inspection

**Files:**
- Modify: `frequi/src/types/candleTypes.ts`
- Modify: `frequi/src/types/research.ts`
- Modify: `frequi/src/stores/research.ts`
- Modify: `frequi/src/views/ResearchView.vue`
- Modify: `frequi/src/composables/useCandleChartTooltip.ts`
- Test: `frequi/src/stores/__tests__/research.spec.ts`
- Test: `frequi/src/composables/__tests__/useCandleChartTooltip.spec.ts`

**Interfaces:**
- Consumes: `/research/datasets`
- Produces: `ResearchDatasetDescriptor`
- Produces: `ResearchChartPayload.side_layers`
- Produces: generic tooltip rows for `event` and `document` layer points

- [ ] **Step 1: Extend TypeScript types**

Modify `frequi/src/types/candleTypes.ts`:

```ts
export type ChartLayerSource =
  | 'market'
  | 'watch'
  | 'strategy'
  | 'execution'
  | 'decision_snapshot'
  | 'recomputed'
  | 'feature'
  | 'event'
  | 'document';
```

Modify `frequi/src/types/research.ts`:

```ts
export type ResearchSideDataKind = 'feature' | 'event' | 'document';

export interface ResearchDatasetDescriptor {
  dataset_id: string;
  kind: ResearchSideDataKind;
  market: ResearchMarket;
  scope: 'instrument' | 'market' | 'sector';
  storage_format: 'csv' | 'jsonl';
  timeframe?: string | null;
  available: boolean;
  start?: string | null;
  stop?: string | null;
  provider?: string | null;
  provider_version?: string | null;
  manifest_run_id?: string | null;
  warnings: string[];
}

export interface ResearchDatasetsResponse {
  datasets: ResearchDatasetDescriptor[];
}

export interface ResearchSideLayersPayload {
  features?: string[];
  events?: string[];
  documents?: string[];
}
```

Add to `ResearchChartPayload`:

```ts
  side_layers?: ResearchSideLayersPayload | null;
```

- [ ] **Step 2: Extend research store**

Modify `frequi/src/stores/research.ts` imports to include `ResearchDatasetsResponse` and `ResearchDatasetDescriptor`.

Add refs and request state:

```ts
  const datasets = shallowRef<ResearchDatasetDescriptor[]>([]);
  const datasetsRequestState = createRequestState();
  const datasetsRequestTracker: KeyedRequestTracker<ResearchDatasetDescriptor[]> = {
    requests: new Map(),
    latestKey: null,
  };
```

Add action:

```ts
  async function loadDatasets(instrument?: string) {
    const requestBotId = selectedBotId.value;
    const requestInstrument = instrument ?? selectedInstrument.value;
    const requestKey = serializeResearchPayload({ requestBotId, requestInstrument });

    return startKeyedResearchRequest(
      datasetsRequestState,
      datasetsRequestTracker,
      requestKey,
      async () => {
        const { data } = await getResearchApi().get<ResearchDatasetsResponse>(
          '/research/datasets',
          {
            params: {
              bot_id: requestBotId,
              instrument: requestInstrument || undefined,
            },
          },
        );
        return data.datasets;
      },
      (data) => {
        if (selectedBotId.value !== requestBotId) {
          return;
        }
        datasets.value = data;
      },
    );
  }
```

Return `datasets`, `datasetsRequestState`, and `loadDatasets`.

- [ ] **Step 3: Add Research page side-layer state**

Modify `frequi/src/views/ResearchView.vue` script:

```ts
const selectedFeatureDatasets = ref<string[]>([]);
const selectedEventDatasets = ref<string[]>([]);
const selectedDocumentDatasets = ref<string[]>([]);

const featureDatasetOptions = computed(() =>
  researchStore.datasets
    .filter((dataset) => dataset.kind === 'feature' && dataset.available)
    .map((dataset) => ({ label: dataset.dataset_id, value: dataset.dataset_id })),
);

const eventDatasetOptions = computed(() =>
  researchStore.datasets
    .filter((dataset) => dataset.kind === 'event' && dataset.available)
    .map((dataset) => ({ label: dataset.dataset_id, value: dataset.dataset_id })),
);

const documentDatasetOptions = computed(() =>
  researchStore.datasets
    .filter((dataset) => dataset.kind === 'document' && dataset.available)
    .map((dataset) => ({ label: dataset.dataset_id, value: dataset.dataset_id })),
);
```

After loading instruments and after instrument changes, call:

```ts
  await researchStore.loadDatasets();
```

Add `side_layers` to `refreshChart` payload:

```ts
      side_layers: {
        features: selectedFeatureDatasets.value,
        events: selectedEventDatasets.value,
        documents: selectedDocumentDatasets.value,
      },
```

Add compact controls near the existing chart controls:

```vue
<label class="flex flex-col gap-1 text-sm md:col-span-2">
  <span>{{ t('research.sideData') }}</span>
  <div class="grid grid-cols-3 gap-1">
    <USelectMenu
      v-model="selectedFeatureDatasets"
      :items="featureDatasetOptions"
      multiple
      data-test="feature-side-layers"
    />
    <USelectMenu
      v-model="selectedEventDatasets"
      :items="eventDatasetOptions"
      multiple
      data-test="event-side-layers"
    />
    <USelectMenu
      v-model="selectedDocumentDatasets"
      :items="documentDatasetOptions"
      multiple
      data-test="document-side-layers"
    />
  </div>
</label>
```

If `USelectMenu` is not available in this UI stack, use the existing select component pattern and single-select each kind for Phase 3A.

- [ ] **Step 4: Add generic point tooltip support**

In `frequi/src/composables/useCandleChartTooltip.ts`, keep `decision_snapshot` behavior and add generic handling for `event` and `document` sources.

Add helper:

```ts
  function appendGenericPointPayloadRows(
    rows: CandleTooltipRow[],
    payload: Record<string, unknown>,
  ) {
    for (const [key, value] of Object.entries(payload)) {
      if (isRenderableTooltipValue(value)) {
        rows.push({
          label: key,
          value: formatDecisionSnapshotPointValue(value),
        });
      }
    }
  }
```

Add formatter:

```ts
  function formatGenericPointRows(timestamp: number): CandleTooltipGroup[] {
    const groups: CandleTooltipGroup[] = [];
    for (const layer of getChartResponseMeta()?.layers ?? []) {
      if (layer.source !== 'event' && layer.source !== 'document') {
        continue;
      }
      const rows: CandleTooltipRow[] = [];
      for (const point of layer.points ?? []) {
        if (point.timestamp !== timestamp || !point.payload) {
          continue;
        }
        appendGenericPointPayloadRows(rows, point.payload);
      }
      if (rows.length > 0) {
        groups.push({
          title: layer.label,
          source: layer.source,
          lines: rows,
          firstIndex: Number.MAX_SAFE_INTEGER,
        });
      }
    }
    return groups;
  }
```

In the main tooltip assembly, after `appendDecisionSnapshotPointGroup(...)`, append groups from `formatGenericPointRows(timestamp)` when a timestamp is available.

- [ ] **Step 5: Verify frontend**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
npm run test:unit -- --run
npm run typecheck
```

Expected: PASS.

---

## Task 9: Docs, Example Config, And Full Verification

**Files:**
- Create: `docs/a-share-side-data.md`
- Modify: `docs/a-share-market-correctness.md`
- Modify: `docs/a-share-research-data.md`
- Modify: `ft_userdata/user_data/config.research.example.json`

**Interfaces:**
- Consumes: all previous task outputs.
- Produces: operator documentation and full verification commands.

- [ ] **Step 1: Add example config**

Modify the A-share research bot in `ft_userdata/user_data/config.research.example.json` to include:

```json
"market_data": {
  "meta_root": "research_data/a_share_meta",
  "calendar": "calendar/trade_dates.csv",
  "daily_status": "status/daily_status.csv"
},
"side_data": {
  "root": "research_data/a_share_meta",
  "enabled_datasets": [
    "fund_flow_daily",
    "limit_pool",
    "announcements"
  ]
}
```

Keep existing fields unchanged.

- [ ] **Step 2: Create side-data docs**

Create `docs/a-share-side-data.md` with these sections:

```markdown
# A-Share Side Data

Phase 3A adds local research side data for A-share feature, event, and document datasets.

## Scope

Supported:

- public `/research/backtest` can load configured Phase 2 calendar/status context;
- local side-data stores under `research_data/a_share_meta`;
- dataset discovery through `/api/v1/research/datasets`;
- optional `/research/chart_candles.side_layers`;
- collector-driven local artifacts and manifests.

Not supported:

- live trading;
- provider-backed chart/backtest requests;
- AI retrieval or embeddings;
- PDF parsing;
- strategy feature consumption.

## Local Layout

```text
research_data/a_share_meta/
  calendar/trade_dates.csv
  status/daily_status.csv
  features/fund_flow_daily/{instrument}.csv
  events/limit_pool/{date}.jsonl
  documents/announcements/{instrument}.jsonl
  .manifests/{run_id}.json
```

## Collect

```powershell
cd G:\AI_Trading\freqtrade-cn
freqtrade\.venv\Scripts\python tools\download_a_share_side_data.py `
  --config ft_userdata\user_data\config.research.example.json `
  --bot-id a-share-local `
  --datasets fund_flow_daily limit_pool announcements `
  --instruments 600519.SH `
  --timerange 20260701-20260707
```

## Verify API

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8080/api/v1/research/datasets?bot_id=a-share-local&instrument=600519.SH" `
  -Headers $headers
```

Chart/backtest API requests read local artifacts only. They do not call provider APIs.
```

- [ ] **Step 3: Update existing docs**

Add links to `docs/a-share-market-correctness.md` and `docs/a-share-research-data.md`:

```markdown
For Phase 3A feature/event/document side data, see [A-Share Side Data](a-share-side-data.md).
```

- [ ] **Step 4: Run full backend verification**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research tests/markets tests/rpc/test_api_research.py -q
.\.venv\Scripts\python -m ruff check freqtrade/research freqtrade/markets freqtrade/rpc/api_server tests/research tests/markets tests/rpc/test_api_research.py ..\tools\download_a_share_side_data.py
```

Expected: PASS and ruff clean.

- [ ] **Step 5: Run full frontend verification**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
npm run test:unit -- --run
npm run typecheck
```

Expected: PASS.

- [ ] **Step 6: Verify CLI help**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
freqtrade\.venv\Scripts\python tools\download_a_share_side_data.py --help
```

Expected: exits `0` and prints usage without importing `akshare`.

---

## Execution Notes

- Run tasks in order. Task 1 is a prerequisite for correct market-context behavior. Tasks 2 and 3 form the side-data foundation. Tasks 4 and 5 expose the foundation to APIs/charts. Task 6 adds reproducible artifacts. Task 7 adds optional provider adapters behind tests. Task 8 exposes the new data in FreqUI. Task 9 closes docs and verification.
- Use test-first execution for each task.
- Keep provider imports out of route modules. This can be checked with `rg "akshare|requests|eastmoney|cninfo|mootdx" freqtrade/rpc/api_server freqtrade/research/chart.py`.
- Do not change existing OHLCV validation to accept side-data columns.
- Do not add strategy consumption of side features in this phase.

## Self-Review Checklist

- Spec coverage:
  - Phase 2.5 public backtest context: Task 1.
  - Feature/event/document models: Task 2.
  - Local stores and dataset descriptors: Task 3.
  - `/research/datasets`: Task 4.
  - `/research/chart_candles.side_layers`: Task 5.
  - Collector artifacts and manifests: Task 6.
  - Provider adapters behind collector path: Task 7.
  - Frontend side-data selection and point inspection: Task 8.
  - Docs and verification: Task 9.
- Chosen open decisions:
  - Phase 3A implements schemas for feature/event/document and ships collection for `fund_flow_daily`, `limit_pool`, and `announcements`.
  - Side-data artifacts use CSV for feature datasets and JSONL for event/document datasets.
  - Numeric feature chart values are added to legacy `columns/data` only with the reserved `feature_{dataset_id}_{field}` prefix.
- Residual risk:
  - The direct sector-membership provider is kept separate from acceptance-critical collector output because the direct Eastmoney endpoint can drift. Its unit test uses mocked network responses.
