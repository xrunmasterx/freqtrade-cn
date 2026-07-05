# A-Share Market Framework V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first research-only A-share market framework with local market data, chart display, watch indicators, and simple long-only backtesting, while preserving the existing contract trading bot path.

**Architecture:** Keep contract trading on the existing Freqtrade exchange/trade/wallet stack. Add a separate research stack with market profiles, instruments, data sources, calendars, and research backtesting. Reuse the existing chart response and FreqUI chart renderer by adapting research OHLCV into the existing chart candle shape.

**Tech Stack:** Python, pandas, Pydantic v2, FastAPI, pytest, TypeScript, Vue 3, Pinia, ECharts, Vitest.

---

## Branches

All feature work should happen on this branch in each modified repository:

```powershell
feature/a-share-market-framework-v1
```

Expected repositories:

- `G:\AI_Trading\freqtrade-cn`
- `G:\AI_Trading\freqtrade-cn\freqtrade`
- `G:\AI_Trading\freqtrade-cn\frequi`

Before implementation, verify:

```powershell
git -C G:\AI_Trading\freqtrade-cn branch --show-current
git -C G:\AI_Trading\freqtrade-cn\freqtrade branch --show-current
git -C G:\AI_Trading\freqtrade-cn\frequi branch --show-current
```

Expected output in all three repositories:

```text
feature/a-share-market-framework-v1
```

## File Structure

### Parent Repository

- Create: `docs/superpowers/specs/2026-07-05-a-share-market-framework-v1-design.md`
  - Architecture design and scope.
- Create: `docs/superpowers/plans/2026-07-05-a-share-market-framework-v1.md`
  - This implementation plan.

### Backend Submodule: `freqtrade`

- Create: `freqtrade/markets/__init__.py`
  - Exports research market domain objects.
- Create: `freqtrade/markets/instrument.py`
  - Market type enum, instrument identity, and parser/formatter helpers.
- Create: `freqtrade/markets/capabilities.py`
  - Capability model for trading bots and research bots.
- Create: `freqtrade/markets/calendar.py`
  - Base calendar interface and V1 A-share session calendar.
- Create: `freqtrade/research/__init__.py`
  - Research package exports.
- Create: `freqtrade/research/profiles.py`
  - Research bot profile loading from config.
- Create: `freqtrade/research/data_source.py`
  - Data source interface and local CSV A-share data source.
- Create: `freqtrade/research/chart.py`
  - Builds chart-compatible candle responses for research data.
- Create: `freqtrade/research/backtesting.py`
  - Simple long-only research backtest engine.
- Create: `freqtrade/research/strategies.py`
  - Built-in SMA crossover signal generator for V1.
- Create: `freqtrade/rpc/api_server/api_research.py`
  - FastAPI routes for research bots, instruments, charts, and backtests.
- Modify: `freqtrade/rpc/api_server/api_schemas.py`
  - Add research request/response DTOs.
- Modify: `freqtrade/rpc/api_server/webserver.py`
  - Register the research router.
- Test: `tests/markets/test_instrument.py`
- Test: `tests/markets/test_calendar.py`
- Test: `tests/research/test_profiles.py`
- Test: `tests/research/test_data_source.py`
- Test: `tests/research/test_chart.py`
- Test: `tests/research/test_backtesting.py`
- Test: `tests/rpc/test_api_research.py`

### Frontend Submodule: `frequi`

- Create: `src/types/research.ts`
  - Research bot, instrument, chart, and backtest types.
- Create: `src/stores/research.ts`
  - Pinia store for research profiles, instruments, chart data, and backtest data.
- Create: `src/views/ResearchView.vue`
  - Research bot selector, instrument selector, chart, and simple backtest controls.
- Modify: `src/router/index.ts`
  - Add `/research` route.
- Modify: `src/components/layout/NavBar.vue`
  - Add research navigation item.
- Modify: `src/locales/en.ts`
  - Add research labels.
- Modify: `src/locales/zh-CN.ts`
  - Add research labels.
- Test: `tests/unit/researchStore.spec.ts`
- Test: `tests/component/ResearchView.spec.ts`

## Task 1: Backend Market Domain Types

**Files:**
- Create: `freqtrade/markets/__init__.py`
- Create: `freqtrade/markets/instrument.py`
- Create: `freqtrade/markets/capabilities.py`
- Test: `tests/markets/test_instrument.py`

- [ ] **Step 1: Write failing instrument tests**

Create `tests/markets/test_instrument.py`:

```python
from freqtrade.markets.instrument import Instrument, MarketType, parse_instrument_key
from freqtrade.markets.capabilities import BotCapabilities


def test_parse_a_share_instrument_key():
    instrument = parse_instrument_key("600519.SH", market=MarketType.A_SHARE)

    assert instrument.key == "600519.SH"
    assert instrument.market == MarketType.A_SHARE
    assert instrument.venue == "SSE"
    assert instrument.symbol == "600519"
    assert instrument.currency == "CNY"
    assert instrument.asset_type == "equity"


def test_parse_szse_instrument_key():
    instrument = parse_instrument_key("000001.SZ", market=MarketType.A_SHARE)

    assert instrument.venue == "SZSE"
    assert instrument.symbol == "000001"


def test_research_capabilities_disable_trading():
    capabilities = BotCapabilities.research()

    assert capabilities.chart is True
    assert capabilities.backtest is True
    assert capabilities.live_trade is False
    assert capabilities.account is False
    assert capabilities.orders is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
.\.venv\Scripts\python -m pytest tests/markets/test_instrument.py -q
```

Expected: FAIL because `freqtrade.markets` does not exist.

- [ ] **Step 3: Implement market domain types**

Create `freqtrade/markets/instrument.py`:

```python
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class MarketType(StrEnum):
    CONTRACT = "contract"
    A_SHARE = "a_share"
    HK_STOCK = "hk_stock"
    US_STOCK = "us_stock"


class Instrument(BaseModel):
    key: str
    market: MarketType
    venue: str
    symbol: str
    currency: str
    asset_type: str = "equity"
    display_name: str | None = None


def parse_instrument_key(key: str, market: MarketType) -> Instrument:
    if market == MarketType.A_SHARE:
        return _parse_a_share_key(key)
    raise ValueError(f"Unsupported research instrument market: {market}")


def _parse_a_share_key(key: str) -> Instrument:
    parts = key.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid A-share instrument key: {key}")

    symbol, suffix = parts[0], parts[1].upper()
    venue_by_suffix = {
        "SH": "SSE",
        "SZ": "SZSE",
    }
    venue = venue_by_suffix.get(suffix)
    if venue is None:
        raise ValueError(f"Unsupported A-share venue suffix: {suffix}")

    return Instrument(
        key=f"{symbol}.{suffix}",
        market=MarketType.A_SHARE,
        venue=venue,
        symbol=symbol,
        currency="CNY",
    )
```

Create `freqtrade/markets/capabilities.py`:

```python
from __future__ import annotations

from pydantic import BaseModel


class BotCapabilities(BaseModel):
    chart: bool = True
    indicators: bool = True
    backtest: bool = True
    live_trade: bool = False
    account: bool = False
    orders: bool = False

    @classmethod
    def research(cls) -> "BotCapabilities":
        return cls(
            chart=True,
            indicators=True,
            backtest=True,
            live_trade=False,
            account=False,
            orders=False,
        )

    @classmethod
    def trading(cls) -> "BotCapabilities":
        return cls(
            chart=True,
            indicators=True,
            backtest=True,
            live_trade=True,
            account=True,
            orders=True,
        )
```

Create `freqtrade/markets/__init__.py`:

```python
from freqtrade.markets.capabilities import BotCapabilities
from freqtrade.markets.instrument import Instrument, MarketType, parse_instrument_key

__all__ = [
    "BotCapabilities",
    "Instrument",
    "MarketType",
    "parse_instrument_key",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/markets/test_instrument.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit backend market domain**

Run:

```powershell
git add freqtrade/markets tests/markets/test_instrument.py
git commit -m "feat: add research market domain types"
```

## Task 2: Backend A-Share Calendar and Local Data Source

**Files:**
- Create: `freqtrade/markets/calendar.py`
- Create: `freqtrade/research/__init__.py`
- Create: `freqtrade/research/data_source.py`
- Test: `tests/markets/test_calendar.py`
- Test: `tests/research/test_data_source.py`

- [ ] **Step 1: Write failing calendar tests**

Create `tests/markets/test_calendar.py`:

```python
from datetime import datetime, timezone

from freqtrade.markets.calendar import AShareCalendar


def test_a_share_calendar_marks_weekday_session_open():
    calendar = AShareCalendar()

    assert calendar.is_session_open(datetime(2026, 7, 6, 1, 45, tzinfo=timezone.utc))


def test_a_share_calendar_marks_lunch_break_closed():
    calendar = AShareCalendar()

    assert not calendar.is_session_open(datetime(2026, 7, 6, 4, 0, tzinfo=timezone.utc))


def test_a_share_calendar_marks_weekend_closed():
    calendar = AShareCalendar()

    assert not calendar.is_session_open(datetime(2026, 7, 5, 1, 45, tzinfo=timezone.utc))
```

The UTC times correspond to China local trading sessions on 2026-07-06.

- [ ] **Step 2: Write failing local data source tests**

Create `tests/research/test_data_source.py`:

```python
from pathlib import Path

import pandas as pd

from freqtrade.research.data_source import LocalCsvResearchDataSource


def test_local_csv_source_lists_a_share_instruments(tmp_path: Path):
    data_file = tmp_path / "600519.SH-1d.csv"
    data_file.write_text(
        "date,open,high,low,close,volume\n"
        "2026-07-01,100,110,99,108,1000\n",
        encoding="utf-8",
    )
    source = LocalCsvResearchDataSource(tmp_path)

    instruments = source.list_instruments()

    assert [item.key for item in instruments] == ["600519.SH"]


def test_local_csv_source_loads_normalized_ohlcv(tmp_path: Path):
    data_file = tmp_path / "600519.SH-1d.csv"
    data_file.write_text(
        "date,open,high,low,close,volume\n"
        "2026-07-01,100,110,99,108,1000\n"
        "2026-07-02,108,112,106,111,1200\n",
        encoding="utf-8",
    )
    source = LocalCsvResearchDataSource(tmp_path)

    dataframe = source.load_ohlcv("600519.SH", "1d")

    assert list(dataframe.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert len(dataframe) == 2
    assert pd.api.types.is_datetime64_any_dtype(dataframe["date"])
    assert dataframe.iloc[0]["close"] == 108.0
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/markets/test_calendar.py tests/research/test_data_source.py -q
```

Expected: FAIL because calendar and research data source modules do not exist.

- [ ] **Step 4: Implement A-share calendar**

Create `freqtrade/markets/calendar.py`:

```python
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo


class AShareCalendar:
    timezone = ZoneInfo("Asia/Shanghai")
    morning_open = time(9, 30)
    morning_close = time(11, 30)
    afternoon_open = time(13, 0)
    afternoon_close = time(15, 0)

    def __init__(self, closed_dates: set[str] | None = None) -> None:
        self.closed_dates = closed_dates or set()

    def is_session_open(self, timestamp: datetime) -> bool:
        local_time = timestamp.astimezone(self.timezone)
        if local_time.weekday() >= 5:
            return False
        if local_time.date().isoformat() in self.closed_dates:
            return False

        current_time = local_time.time()
        return (
            self.morning_open <= current_time < self.morning_close
            or self.afternoon_open <= current_time < self.afternoon_close
        )
```

- [ ] **Step 5: Implement local CSV research data source**

Create `freqtrade/research/data_source.py`:

```python
from __future__ import annotations

from pathlib import Path

import pandas as pd
from pandas import DataFrame

from freqtrade.markets.instrument import Instrument, MarketType, parse_instrument_key


RESEARCH_OHLCV_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


class LocalCsvResearchDataSource:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def list_instruments(self) -> list[Instrument]:
        keys = sorted({path.name.split("-")[0] for path in self.root.glob("*.csv")})
        return [parse_instrument_key(key, MarketType.A_SHARE) for key in keys]

    def load_ohlcv(self, instrument_key: str, timeframe: str) -> DataFrame:
        path = self.root / f"{instrument_key}-{timeframe}.csv"
        if not path.exists():
            raise FileNotFoundError(f"Research OHLCV file not found: {path}")

        dataframe = pd.read_csv(path)
        missing_columns = [column for column in RESEARCH_OHLCV_COLUMNS if column not in dataframe]
        if missing_columns:
            raise ValueError(f"Research OHLCV missing columns: {missing_columns}")

        result = dataframe.loc[:, RESEARCH_OHLCV_COLUMNS].copy()
        result["date"] = pd.to_datetime(result["date"], utc=True)
        for column in ["open", "high", "low", "close", "volume"]:
            result[column] = pd.to_numeric(result[column], errors="raise").astype(float)
        return result.sort_values("date").reset_index(drop=True)
```

Create `freqtrade/research/__init__.py`:

```python
from freqtrade.research.data_source import LocalCsvResearchDataSource

__all__ = ["LocalCsvResearchDataSource"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/markets/test_calendar.py tests/research/test_data_source.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit calendar and data source**

Run:

```powershell
git add freqtrade/markets/calendar.py freqtrade/research tests/markets/test_calendar.py tests/research/test_data_source.py
git commit -m "feat: add local research market data source"
```

## Task 3: Backend Research Profiles

**Files:**
- Create: `freqtrade/research/profiles.py`
- Modify: `freqtrade/research/__init__.py`
- Modify: `freqtrade/rpc/api_server/api_schemas.py`
- Test: `tests/research/test_profiles.py`

- [ ] **Step 1: Write failing profile tests**

Create `tests/research/test_profiles.py`:

```python
from pathlib import Path

from freqtrade.markets.instrument import MarketType
from freqtrade.research.profiles import load_research_profiles


def test_loads_default_a_share_profile_from_config(tmp_path: Path):
    config = {
        "user_data_dir": tmp_path,
        "research_bots": [
            {
                "id": "a-share-local",
                "label": "A Share Local",
                "market": "a_share",
                "data_source": {
                    "type": "local_csv",
                    "root": "research_data/a_share",
                },
            }
        ],
    }

    profiles = load_research_profiles(config)

    assert len(profiles) == 1
    assert profiles[0].id == "a-share-local"
    assert profiles[0].market == MarketType.A_SHARE
    assert profiles[0].capabilities.live_trade is False
    assert profiles[0].data_root == tmp_path / "research_data" / "a_share"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_profiles.py -q
```

Expected: FAIL because `freqtrade.research.profiles` does not exist.

- [ ] **Step 3: Implement research profiles**

Create `freqtrade/research/profiles.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from freqtrade.markets.capabilities import BotCapabilities
from freqtrade.markets.instrument import MarketType


class ResearchDataSourceConfig(BaseModel):
    type: Literal["local_csv"]
    root: str


class ResearchBotProfile(BaseModel):
    id: str
    label: str
    market: MarketType
    data_source: ResearchDataSourceConfig
    capabilities: BotCapabilities = BotCapabilities.research()
    data_root: Path


def load_research_profiles(config: dict[str, Any]) -> list[ResearchBotProfile]:
    user_data_dir = Path(config["user_data_dir"])
    profiles = []
    for raw_profile in config.get("research_bots", []):
        data_source = ResearchDataSourceConfig.model_validate(raw_profile["data_source"])
        profiles.append(
            ResearchBotProfile(
                id=raw_profile["id"],
                label=raw_profile["label"],
                market=MarketType(raw_profile["market"]),
                data_source=data_source,
                data_root=user_data_dir / data_source.root,
            )
        )
    return profiles
```

Update `freqtrade/research/__init__.py`:

```python
from freqtrade.research.data_source import LocalCsvResearchDataSource
from freqtrade.research.profiles import ResearchBotProfile, load_research_profiles

__all__ = ["LocalCsvResearchDataSource", "ResearchBotProfile", "load_research_profiles"]
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_profiles.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit research profiles**

Run:

```powershell
git add freqtrade/research/profiles.py freqtrade/research/__init__.py tests/research/test_profiles.py
git commit -m "feat: add research bot profiles"
```

## Task 4: Backend Research Chart Endpoint

**Files:**
- Create: `freqtrade/research/chart.py`
- Create: `freqtrade/rpc/api_server/api_research.py`
- Modify: `freqtrade/rpc/api_server/api_schemas.py`
- Modify: `freqtrade/rpc/api_server/webserver.py`
- Test: `tests/research/test_chart.py`
- Test: `tests/rpc/test_api_research.py`

- [ ] **Step 1: Write failing research chart service test**

Create `tests/research/test_chart.py`:

```python
from pathlib import Path

from freqtrade.rpc.api_server.api_schemas import ResearchChartCandlesRequest
from freqtrade.research.chart import build_research_chart_candles_response
from freqtrade.research.profiles import load_research_profiles


def test_research_chart_response_reuses_pair_history_shape(tmp_path: Path):
    data_root = tmp_path / "research_data" / "a_share"
    data_root.mkdir(parents=True)
    (data_root / "600519.SH-1d.csv").write_text(
        "date,open,high,low,close,volume\n"
        "2026-07-01,100,110,99,108,1000\n"
        "2026-07-02,108,112,106,111,1200\n",
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
            }
        ],
    }
    profile = load_research_profiles(config)[0]
    payload = ResearchChartCandlesRequest(
        bot_id="a-share-local",
        instrument="600519.SH",
        timeframe="1d",
        limit=100,
    )

    response = build_research_chart_candles_response(profile, payload)

    assert response["pair"] == "600519.SH"
    assert response["timeframe"] == "1d"
    assert response["columns"][:6] == ["date", "open", "high", "low", "close", "volume"]
    assert response["length"] == 2
    assert response["meta"]["layers"][0]["source"] == "market"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_chart.py -q
```

Expected: FAIL because research chart request and builder do not exist.

- [ ] **Step 3: Add research chart DTOs**

In `freqtrade/rpc/api_server/api_schemas.py`, add near chart schemas:

```python
class ResearchChartCandlesRequest(BaseModel):
    bot_id: str
    instrument: str
    timeframe: str
    limit: int = Field(default=500, ge=1, le=2000)
    timerange: str | None = None
    adjustment: Literal["raw", "qfq", "hfq"] = "raw"
    watch_indicators: ChartIndicatorRequest | None = None
```

- [ ] **Step 4: Implement research chart builder**

Create `freqtrade/research/chart.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from freqtrade.constants import DEFAULT_DATAFRAME_COLUMNS
from freqtrade.exchange import timeframe_to_msecs
from freqtrade.rpc.api_server.api_schemas import (
    ChartLayerMeta,
    ChartResponseMeta,
    ChartSeriesCoverage,
    ChartSeriesMeta,
    ChartWindowMeta,
    ResearchChartCandlesRequest,
)
from freqtrade.rpc.chart_indicators import add_watch_indicators, build_watch_plot_config
from freqtrade.research.data_source import LocalCsvResearchDataSource
from freqtrade.research.profiles import ResearchBotProfile
from freqtrade.util.datetime_helpers import dt_ts


def build_research_chart_candles_response(
    profile: ResearchBotProfile,
    payload: ResearchChartCandlesRequest,
) -> dict[str, Any]:
    source = LocalCsvResearchDataSource(profile.data_root)
    dataframe = source.load_ohlcv(payload.instrument, payload.timeframe)
    dataframe = dataframe.tail(payload.limit).reset_index(drop=True)
    dataframe = add_watch_indicators(dataframe, payload.watch_indicators)
    plot_config = build_watch_plot_config(payload.watch_indicators)
    columns = [*dataframe.columns]
    data = dataframe.values.tolist()

    meta = ChartResponseMeta(
        window=ChartWindowMeta(
            requested_count=payload.limit,
            returned_count=len(dataframe),
            warmup_count=0,
            data_start=str(dataframe.iloc[0]["date"]) if not dataframe.empty else None,
            data_stop=str(dataframe.iloc[-1]["date"]) if not dataframe.empty else None,
            last_candle_complete=True,
        ),
        layers=[
            _market_layer(dataframe, payload.timeframe),
        ],
    )

    data_start = dataframe.iloc[0]["date"] if not dataframe.empty else datetime.now(UTC)
    data_stop = dataframe.iloc[-1]["date"] if not dataframe.empty else datetime.now(UTC)
    return {
        "strategy": "Research",
        "pair": payload.instrument,
        "timeframe": payload.timeframe,
        "timeframe_ms": timeframe_to_msecs(payload.timeframe),
        "columns": columns,
        "all_columns": columns,
        "data": data,
        "annotations": [],
        "length": len(dataframe),
        "buy_signals": 0,
        "sell_signals": 0,
        "enter_long_signals": 0,
        "exit_long_signals": 0,
        "enter_short_signals": 0,
        "exit_short_signals": 0,
        "last_analyzed": datetime.now(UTC),
        "last_analyzed_ts": dt_ts(),
        "data_start_ts": dt_ts(data_start),
        "data_start": str(data_start),
        "data_stop": str(data_stop),
        "data_stop_ts": dt_ts(data_stop),
        "chart_timeframe": payload.timeframe,
        "strategy_timeframe": None,
        "overlay": None,
        "plot_config": plot_config,
        "warnings": [],
        "candle_mode": "closed",
        "last_candle_complete": True,
        "meta": meta.model_dump(),
    }


def _market_layer(dataframe, timeframe: str) -> ChartLayerMeta:
    series = [
        _series(dataframe, "open", "Open", "ohlcv", "main", timeframe),
        _series(dataframe, "high", "High", "ohlcv", "main", timeframe),
        _series(dataframe, "low", "Low", "ohlcv", "main", timeframe),
        _series(dataframe, "close", "Close", "ohlcv", "main", timeframe),
        _series(dataframe, "volume", "Volume", "bar", "volume", timeframe),
    ]
    return ChartLayerMeta(
        id="market.ohlcv",
        source="market",
        status="ok",
        label="Market Data",
        timeframe=timeframe,
        alignment="direct",
        series=series,
    )


def _series(dataframe, column: str, label: str, kind: str, panel: str, timeframe: str):
    return ChartSeriesMeta(
        column=column,
        label=label,
        source="market",
        kind=kind,
        panel=panel,
        timeframe=timeframe,
        visible=True,
        coverage=ChartSeriesCoverage(valid_points=len(dataframe), total_points=len(dataframe)),
    )
```

- [ ] **Step 5: Run service test**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_chart.py -q
```

Expected: PASS.

- [ ] **Step 6: Add research API route tests**

Create `tests/rpc/test_api_research.py` with a test using the existing API test client pattern in `tests/rpc`. The test should call:

```text
GET /api/v1/research/bots
POST /api/v1/research/chart_candles
```

Assert:

```python
assert response.status_code == 200
assert response.json()["pair"] == "600519.SH"
```

- [ ] **Step 7: Implement research router**

Create `freqtrade/rpc/api_server/api_research.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from freqtrade.rpc.api_server.api_schemas import ResearchChartCandlesRequest
from freqtrade.rpc.api_server.deps import get_config
from freqtrade.research.chart import build_research_chart_candles_response
from freqtrade.research.profiles import load_research_profiles


router = APIRouter(prefix="/research", tags=["Research"])


@router.get("/bots")
def research_bots(config=Depends(get_config)):
    return {"bots": [profile.model_dump() for profile in load_research_profiles(config)]}


@router.post("/chart_candles")
def research_chart_candles(payload: ResearchChartCandlesRequest, config=Depends(get_config)):
    profiles = {profile.id: profile for profile in load_research_profiles(config)}
    profile = profiles.get(payload.bot_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Research bot not found: {payload.bot_id}")
    return build_research_chart_candles_response(profile, payload)
```

Modify `freqtrade/rpc/api_server/webserver.py` to include the router beside existing API routers:

```python
from freqtrade.rpc.api_server.api_research import router as api_research
```

and include:

```python
api_research,
```

- [ ] **Step 8: Run API and chart tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_chart.py tests/rpc/test_api_research.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit research chart endpoint**

Run:

```powershell
git add freqtrade/research/chart.py freqtrade/rpc/api_server/api_research.py freqtrade/rpc/api_server/api_schemas.py freqtrade/rpc/api_server/webserver.py tests/research/test_chart.py tests/rpc/test_api_research.py
git commit -m "feat: add research chart endpoint"
```

## Task 5: Backend Simple Research Backtest

**Files:**
- Create: `freqtrade/research/strategies.py`
- Create: `freqtrade/research/backtesting.py`
- Modify: `freqtrade/rpc/api_server/api_schemas.py`
- Modify: `freqtrade/rpc/api_server/api_research.py`
- Test: `tests/research/test_backtesting.py`

- [ ] **Step 1: Write failing backtest tests**

Create `tests/research/test_backtesting.py`:

```python
import pandas as pd

from freqtrade.research.backtesting import ResearchBacktestConfig, run_research_backtest


def test_sma_cross_backtest_returns_trade_and_equity_curve():
    dataframe = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-06", "2026-07-07"],
                utc=True,
            ),
            "open": [10, 11, 12, 11, 10],
            "high": [11, 12, 13, 12, 11],
            "low": [9, 10, 11, 10, 9],
            "close": [10, 12, 13, 10, 9],
            "volume": [1000, 1000, 1000, 1000, 1000],
        }
    )
    config = ResearchBacktestConfig(
        initial_cash=10000,
        fast=1,
        slow=2,
        lot_size=100,
        commission_rate=0.0003,
        stamp_tax_rate=0.001,
    )

    result = run_research_backtest("600519.SH", dataframe, config)

    assert result.metrics["initial_cash"] == 10000
    assert len(result.equity_curve) == len(dataframe)
    assert result.metrics["final_equity"] > 0
    assert isinstance(result.trades, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_backtesting.py -q
```

Expected: FAIL because `freqtrade.research.backtesting` does not exist.

- [ ] **Step 3: Implement SMA signals**

Create `freqtrade/research/strategies.py`:

```python
from __future__ import annotations

from pandas import DataFrame


def add_sma_cross_signals(dataframe: DataFrame, fast: int, slow: int) -> DataFrame:
    if fast <= 0 or slow <= 0:
        raise ValueError("SMA periods must be positive.")
    if fast >= slow:
        raise ValueError("Fast SMA period must be smaller than slow SMA period.")

    result = dataframe.copy()
    result["sma_fast"] = result["close"].rolling(fast).mean()
    result["sma_slow"] = result["close"].rolling(slow).mean()
    previous_fast = result["sma_fast"].shift(1)
    previous_slow = result["sma_slow"].shift(1)
    result["enter_long"] = (
        (previous_fast <= previous_slow) & (result["sma_fast"] > result["sma_slow"])
    ).astype(int)
    result["exit_long"] = (
        (previous_fast >= previous_slow) & (result["sma_fast"] < result["sma_slow"])
    ).astype(int)
    return result
```

- [ ] **Step 4: Implement simple long-only backtest**

Create `freqtrade/research/backtesting.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field
from pandas import DataFrame

from freqtrade.research.strategies import add_sma_cross_signals


class ResearchBacktestConfig(BaseModel):
    initial_cash: float = Field(gt=0)
    fast: int = Field(default=20, ge=1)
    slow: int = Field(default=60, ge=2)
    lot_size: int = Field(default=100, ge=1)
    commission_rate: float = Field(default=0.0003, ge=0)
    stamp_tax_rate: float = Field(default=0.001, ge=0)


class ResearchBacktestResult(BaseModel):
    trades: list[dict]
    equity_curve: list[dict]
    metrics: dict[str, float]
    signals: list[dict]
    warnings: list[str] = []


def run_research_backtest(
    instrument: str,
    dataframe: DataFrame,
    config: ResearchBacktestConfig,
) -> ResearchBacktestResult:
    signals = add_sma_cross_signals(dataframe, config.fast, config.slow)
    cash = float(config.initial_cash)
    shares = 0
    entry_date = None
    entry_price = 0.0
    trades: list[dict] = []
    equity_curve: list[dict] = []

    for index, row in signals.iterrows():
        date = row["date"]
        open_price = float(row["open"])

        if shares > 0 and row["exit_long"] == 1 and entry_date is not None and date.date() > entry_date.date():
            gross = shares * open_price
            fee = gross * (config.commission_rate + config.stamp_tax_rate)
            cash += gross - fee
            trades.append(
                {
                    "instrument": instrument,
                    "entry_date": str(entry_date),
                    "exit_date": str(date),
                    "entry_price": entry_price,
                    "exit_price": open_price,
                    "shares": shares,
                    "profit": (open_price - entry_price) * shares - fee,
                }
            )
            shares = 0
            entry_date = None
            entry_price = 0.0

        if shares == 0 and row["enter_long"] == 1:
            affordable_lots = int(cash // (open_price * config.lot_size))
            buy_shares = affordable_lots * config.lot_size
            if buy_shares > 0:
                gross = buy_shares * open_price
                fee = gross * config.commission_rate
                cash -= gross + fee
                shares = buy_shares
                entry_date = date
                entry_price = open_price

        equity = cash + shares * float(row["close"])
        equity_curve.append({"date": str(date), "equity": equity, "cash": cash, "shares": shares})

    final_equity = equity_curve[-1]["equity"] if equity_curve else config.initial_cash
    return ResearchBacktestResult(
        trades=trades,
        equity_curve=equity_curve,
        metrics={
            "initial_cash": config.initial_cash,
            "final_equity": final_equity,
            "return_ratio": final_equity / config.initial_cash - 1,
            "trade_count": float(len(trades)),
        },
        signals=signals.loc[:, ["date", "enter_long", "exit_long"]].to_dict("records"),
    )
```

- [ ] **Step 5: Run backtest tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_backtesting.py -q
```

Expected: PASS.

- [ ] **Step 6: Add backtest API DTOs and route**

In `freqtrade/rpc/api_server/api_schemas.py`, add:

```python
class ResearchSmaCrossStrategyRequest(BaseModel):
    type: Literal["sma_cross"] = "sma_cross"
    fast: int = Field(default=20, ge=1)
    slow: int = Field(default=60, ge=2)


class ResearchBacktestRequest(BaseModel):
    bot_id: str
    instrument: str
    timeframe: str
    timerange: str | None = None
    strategy: ResearchSmaCrossStrategyRequest = Field(default_factory=ResearchSmaCrossStrategyRequest)
    initial_cash: float = Field(default=100000, gt=0)
```

In `freqtrade/rpc/api_server/api_research.py`, add:

```python
@router.post("/backtest")
def research_backtest(payload: ResearchBacktestRequest, config=Depends(get_config)):
    profiles = {profile.id: profile for profile in load_research_profiles(config)}
    profile = profiles.get(payload.bot_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Research bot not found: {payload.bot_id}")
    source = LocalCsvResearchDataSource(profile.data_root)
    dataframe = source.load_ohlcv(payload.instrument, payload.timeframe)
    backtest_config = ResearchBacktestConfig(
        initial_cash=payload.initial_cash,
        fast=payload.strategy.fast,
        slow=payload.strategy.slow,
    )
    return run_research_backtest(payload.instrument, dataframe, backtest_config).model_dump()
```

Add the required imports in `api_research.py`.

- [ ] **Step 7: Run research API tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/research/test_backtesting.py tests/rpc/test_api_research.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit research backtest**

Run:

```powershell
git add freqtrade/research/strategies.py freqtrade/research/backtesting.py freqtrade/rpc/api_server/api_schemas.py freqtrade/rpc/api_server/api_research.py tests/research/test_backtesting.py tests/rpc/test_api_research.py
git commit -m "feat: add simple research backtesting"
```

## Task 6: Frontend Research Types and Store

**Files:**
- Create: `src/types/research.ts`
- Create: `src/stores/research.ts`
- Test: `tests/unit/researchStore.spec.ts`

- [ ] **Step 1: Write failing store tests**

Create `tests/unit/researchStore.spec.ts`:

```ts
import { describe, expect, it, vi } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useResearchStore } from '@/stores/research';

describe('research store', () => {
  it('loads research bots', async () => {
    setActivePinia(createPinia());
    const store = useResearchStore();
    store.api = {
      get: vi.fn().mockResolvedValue({
        data: {
          bots: [
            {
              id: 'a-share-local',
              label: 'A Share Local',
              market: 'a_share',
              capabilities: { chart: true, backtest: true, live_trade: false },
            },
          ],
        },
      }),
    } as never;

    await store.loadBots();

    expect(store.bots[0]?.id).toBe('a-share-local');
    expect(store.bots[0]?.capabilities.live_trade).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run from `G:\AI_Trading\freqtrade-cn\frequi`:

```powershell
pnpm vitest run tests/unit/researchStore.spec.ts
```

Expected: FAIL because `@/stores/research` does not exist.

- [ ] **Step 3: Add research types**

Create `src/types/research.ts`:

```ts
import type { ChartCandlesResponse } from './candleTypes';

export type ResearchMarket = 'a_share' | 'hk_stock' | 'us_stock';

export interface ResearchCapabilities {
  chart: boolean;
  indicators: boolean;
  backtest: boolean;
  live_trade: boolean;
  account: boolean;
  orders: boolean;
}

export interface ResearchBotProfile {
  id: string;
  label: string;
  market: ResearchMarket;
  capabilities: ResearchCapabilities;
}

export interface ResearchInstrument {
  key: string;
  market: ResearchMarket;
  venue: string;
  symbol: string;
  currency: string;
  asset_type: string;
  display_name?: string | null;
}

export interface ResearchChartPayload {
  bot_id: string;
  instrument: string;
  timeframe: string;
  limit?: number;
}

export interface ResearchBacktestPayload {
  bot_id: string;
  instrument: string;
  timeframe: string;
  initial_cash: number;
  strategy: {
    type: 'sma_cross';
    fast: number;
    slow: number;
  };
}

export interface ResearchBacktestResult {
  trades: Record<string, unknown>[];
  equity_curve: Record<string, unknown>[];
  metrics: Record<string, number>;
  signals: Record<string, unknown>[];
  warnings: string[];
}

export type ResearchChartResponse = ChartCandlesResponse;
```

- [ ] **Step 4: Add research store**

Create `src/stores/research.ts`:

```ts
import type {
  ResearchBacktestPayload,
  ResearchBacktestResult,
  ResearchBotProfile,
  ResearchChartPayload,
  ResearchChartResponse,
  ResearchInstrument,
} from '@/types/research';
import axios from 'axios';

export const useResearchStore = defineStore('research', () => {
  const api = shallowRef(axios.create({ baseURL: '/api/v1' }));
  const bots = ref<ResearchBotProfile[]>([]);
  const instruments = ref<ResearchInstrument[]>([]);
  const selectedBotId = ref('');
  const selectedInstrument = ref('');
  const chartData = shallowRef<ResearchChartResponse | null>(null);
  const backtestResult = shallowRef<ResearchBacktestResult | null>(null);

  async function loadBots() {
    const { data } = await api.value.get<{ bots: ResearchBotProfile[] }>('/research/bots');
    bots.value = data.bots;
    selectedBotId.value = selectedBotId.value || data.bots[0]?.id || '';
  }

  async function loadInstruments() {
    const { data } = await api.value.get<{ instruments: ResearchInstrument[] }>(
      '/research/instruments',
      { params: { bot_id: selectedBotId.value } },
    );
    instruments.value = data.instruments;
    selectedInstrument.value = selectedInstrument.value || data.instruments[0]?.key || '';
  }

  async function loadChart(payload: ResearchChartPayload) {
    const { data } = await api.value.post<ResearchChartResponse>(
      '/research/chart_candles',
      payload,
    );
    chartData.value = data;
  }

  async function runBacktest(payload: ResearchBacktestPayload) {
    const { data } = await api.value.post<ResearchBacktestResult>('/research/backtest', payload);
    backtestResult.value = data;
  }

  return {
    api,
    bots,
    instruments,
    selectedBotId,
    selectedInstrument,
    chartData,
    backtestResult,
    loadBots,
    loadInstruments,
    loadChart,
    runBacktest,
  };
});
```

- [ ] **Step 5: Run store test**

Run:

```powershell
pnpm vitest run tests/unit/researchStore.spec.ts
```

Expected: PASS.

- [ ] **Step 6: Commit frontend research store**

Run:

```powershell
git add src/types/research.ts src/stores/research.ts tests/unit/researchStore.spec.ts
git commit -m "feat: add research market store"
```

## Task 7: Frontend Research View

**Files:**
- Create: `src/views/ResearchView.vue`
- Modify: `src/router/index.ts`
- Modify: `src/components/layout/NavBar.vue`
- Modify: `src/locales/en.ts`
- Modify: `src/locales/zh-CN.ts`
- Test: `tests/component/ResearchView.spec.ts`

- [ ] **Step 1: Write failing ResearchView component test**

Create `tests/component/ResearchView.spec.ts` following the existing component test setup:

```ts
import { mount } from '@vue/test-utils';
import { createTestingPinia } from '@pinia/testing';
import { describe, expect, it } from 'vitest';
import ResearchView from '@/views/ResearchView.vue';

describe('ResearchView', () => {
  it('renders research market controls without trading actions', () => {
    const wrapper = mount(ResearchView, {
      global: {
        plugins: [createTestingPinia()],
      },
    });

    expect(wrapper.text()).toContain('Research');
    expect(wrapper.text()).not.toContain('Force Entry');
    expect(wrapper.text()).not.toContain('Force Exit');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
pnpm vitest run tests/component/ResearchView.spec.ts
```

Expected: FAIL because `ResearchView.vue` does not exist.

- [ ] **Step 3: Implement ResearchView**

Create `src/views/ResearchView.vue`:

```vue
<script setup lang="ts">
import CandleChart from '@/components/charts/CandleChart.vue';
import type { PlotConfig } from '@/types';

const researchStore = useResearchStore();
const settingsStore = useSettingsStore();
const timeframe = ref('1d');
const fast = ref(20);
const slow = ref(60);
const initialCash = ref(100000);

const plotConfig = computed<PlotConfig>(() => researchStore.chartData?.plot_config ?? {
  main_plot: {},
  subplots: {},
});

async function refreshChart() {
  if (!researchStore.selectedBotId || !researchStore.selectedInstrument) return;
  await researchStore.loadChart({
    bot_id: researchStore.selectedBotId,
    instrument: researchStore.selectedInstrument,
    timeframe: timeframe.value,
    limit: settingsStore.chartDataCandleCount,
  });
}

async function runBacktest() {
  if (!researchStore.selectedBotId || !researchStore.selectedInstrument) return;
  await researchStore.runBacktest({
    bot_id: researchStore.selectedBotId,
    instrument: researchStore.selectedInstrument,
    timeframe: timeframe.value,
    initial_cash: initialCash.value,
    strategy: {
      type: 'sma_cross',
      fast: fast.value,
      slow: slow.value,
    },
  });
}

onMounted(async () => {
  await researchStore.loadBots();
  await researchStore.loadInstruments();
  await refreshChart();
});
</script>

<template>
  <div class="flex h-full flex-col gap-3 p-3">
    <div class="flex flex-wrap items-center gap-2">
      <h1 class="text-lg font-semibold">Research</h1>
      <USelect
        v-model="researchStore.selectedBotId"
        :items="researchStore.bots.map((bot) => ({ label: bot.label, value: bot.id }))"
        @change="researchStore.loadInstruments"
      />
      <USelect
        v-model="researchStore.selectedInstrument"
        :items="researchStore.instruments.map((item) => ({ label: item.key, value: item.key }))"
        @change="refreshChart"
      />
      <UInput v-model="timeframe" class="w-24" @change="refreshChart" />
      <UButton @click="refreshChart">Refresh</UButton>
    </div>

    <div class="min-h-[420px] flex-1">
      <CandleChart
        v-if="researchStore.chartData"
        :dataset="researchStore.chartData"
        :trades="[]"
        :heikin-ashi="false"
        :show-mark-area="false"
        :use-u-t-c="true"
        :plot-config="plotConfig"
        theme="light"
        color-up="#16a34a"
        color-down="#dc2626"
        label-side="right"
        :start-candle-count="settingsStore.chartDefaultCandleCount"
      />
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <UInput v-model.number="fast" class="w-24" type="number" />
      <UInput v-model.number="slow" class="w-24" type="number" />
      <UInput v-model.number="initialCash" class="w-32" type="number" />
      <UButton @click="runBacktest">Run Backtest</UButton>
      <span v-if="researchStore.backtestResult">
        Return:
        {{ ((researchStore.backtestResult.metrics.return_ratio ?? 0) * 100).toFixed(2) }}%
      </span>
    </div>
  </div>
</template>
```

Adjust component props if the existing `CandleChart` prop casing differs in tests or templates.

- [ ] **Step 4: Add route and nav item**

Modify `src/router/index.ts` to add:

```ts
{
  path: '/research',
  name: 'research',
  component: () => import('@/views/ResearchView.vue'),
}
```

Modify `src/components/layout/NavBar.vue` to add a research nav entry following the existing nav pattern:

```ts
{
  label: t('nav.research'),
  to: '/research',
  icon: 'i-lucide-chart-candlestick',
}
```

Add locale key `nav.research` in `src/locales/en.ts` and `src/locales/zh-CN.ts`.

- [ ] **Step 5: Run component and type checks**

Run:

```powershell
pnpm vitest run tests/component/ResearchView.spec.ts tests/unit/researchStore.spec.ts
pnpm typecheck
```

Expected: PASS.

- [ ] **Step 6: Commit research view**

Run:

```powershell
git add src/views/ResearchView.vue src/router/index.ts src/components/layout/NavBar.vue src/locales/en.ts src/locales/zh-CN.ts tests/component/ResearchView.spec.ts
git commit -m "feat: add research market view"
```

## Task 8: Configuration Example and End-to-End Verification

**Files:**
- Modify: `ft_userdata/user_data/config.example.json`
- Add: `ft_userdata/user_data/research_data/a_share/600519.SH-1d.csv`
- Test: backend and frontend focused commands.

- [ ] **Step 1: Add research bot example config**

Modify `ft_userdata/user_data/config.example.json` to add a top-level `research_bots` field:

```json
"research_bots": [
    {
        "id": "a-share-local",
        "label": "A Share Local",
        "market": "a_share",
        "data_source": {
            "type": "local_csv",
            "root": "research_data/a_share"
        }
    }
]
```

Place it near `bot_name` or before `exchange` so it is easy to discover.

- [ ] **Step 2: Add tiny sample A-share CSV**

Create `ft_userdata/user_data/research_data/a_share/600519.SH-1d.csv`:

```csv
date,open,high,low,close,volume
2026-06-29,100.0,102.0,99.5,101.0,1000000
2026-06-30,101.0,104.0,100.5,103.0,1200000
2026-07-01,103.0,105.0,102.0,104.0,1300000
2026-07-02,104.0,104.5,101.0,102.0,1100000
2026-07-03,102.0,106.0,101.5,105.0,1500000
```

- [ ] **Step 3: Run backend verification**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
.\.venv\Scripts\python -m pytest tests/markets tests/research tests/rpc/test_api_research.py -q
.\.venv\Scripts\python -m ruff check freqtrade/markets freqtrade/research freqtrade/rpc/api_server/api_research.py tests/markets tests/research tests/rpc/test_api_research.py
```

Expected: PASS.

- [ ] **Step 4: Run frontend verification**

Run from `G:\AI_Trading\freqtrade-cn\frequi`:

```powershell
pnpm vitest run tests/unit/researchStore.spec.ts tests/component/ResearchView.spec.ts
pnpm typecheck
pnpm build
```

Expected: PASS.

- [ ] **Step 5: Browser verification**

Run the local stack according to the repository guidelines, then open:

```text
http://127.0.0.1:8081/research
```

Verify:

- research route loads;
- A-share local bot appears;
- `600519.SH` can be selected;
- chart renders candles;
- trading actions are absent;
- SMA backtest returns a result summary.

- [ ] **Step 6: Commit parent repository docs/config and submodule pointers**

After backend and frontend submodule commits, run from `G:\AI_Trading\freqtrade-cn`:

```powershell
git status --short
git add docs/superpowers/specs/2026-07-05-a-share-market-framework-v1-design.md docs/superpowers/plans/2026-07-05-a-share-market-framework-v1.md ft_userdata/user_data/config.example.json ft_userdata/user_data/research_data/a_share/600519.SH-1d.csv freqtrade frequi
git commit -m "feat: plan a-share research market framework"
```

## Full Verification

Run backend:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/markets tests/research tests/rpc/test_api_research.py -q
.\.venv\Scripts\python -m ruff check freqtrade/markets freqtrade/research freqtrade/rpc/api_server/api_research.py tests/markets tests/research tests/rpc/test_api_research.py
```

Run frontend:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
pnpm vitest run tests/unit/researchStore.spec.ts tests/component/ResearchView.spec.ts
pnpm typecheck
pnpm build
```

Run parent status:

```powershell
cd G:\AI_Trading\freqtrade-cn
git status --short --branch
git -C freqtrade status --short --branch
git -C frequi status --short --branch
```

Expected:

- all three repositories are on `feature/a-share-market-framework-v1`;
- only intentional committed changes are present;
- pre-existing untracked `.superpowers/` in the parent repository remains untouched unless the user
  explicitly asks to clean or ignore it.

## Execution Notes

Use TDD for every production code task:

1. write the failing test;
2. run it and confirm the expected failure;
3. implement minimal code;
4. run the focused test;
5. run the relevant broader checks;
6. commit the task before moving on.

Do not modify `freqtrade-strategies` in V1 unless a separate example strategy task is added.
