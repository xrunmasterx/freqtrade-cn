# A-Share Phase 1B Multi-Timeframe OHLCV Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the research-only A-share OHLCV path from raw `1d` data to raw `1m/5m/15m/30m/60m/1d` local artifacts that can be charted and bounded-backtested from the Research UI.

**Architecture:** Keep A-share data outside the ccxt `Exchange` and trading `DataProvider` stack. Provider adapters fetch data only in collector/tooling paths, `AShareOhlcvCollector` normalizes and validates provider frames, local CSV artifacts remain the chart/backtest source of truth, and research APIs continue to read through `ResearchMarketDataSource`.

**Tech Stack:** Python 3.11+, pandas, Pydantic v2, FastAPI, pytest, optional `akshare`, local CSV files, PowerShell.

## Global Constraints

- Repository root: `G:\AI_Trading\freqtrade-cn`.
- Backend package root: `G:\AI_Trading\freqtrade-cn\freqtrade`.
- Phase 1B supported timeframes: `1m`, `5m`, `15m`, `30m`, `60m`, `1d`.
- Phase 1B does not add `1h` as an alias for `60m`.
- Phase 1B is raw-only. `qfq` and `hfq` stay unsupported.
- Canonical OHLCV columns stay exactly: `date,open,high,low,close,volume`.
- Daily artifact timestamps remain date-only values such as `2026-07-07`.
- Minute artifact timestamps must be UTC ISO strings such as `2026-07-07T01:30:00Z`.
- Provider calls must happen only in collector/tooling paths, never in `/research/chart_candles` or `/research/backtest`.
- Do not route A-share data through `freqtrade.exchange.Exchange`, ccxt, trading wallets, or order models.
- Do not add runtime dependency on `G:\AI_Trading\data\a-stock-data`.
- Do not add `mootdx`, Tencent quote, Eastmoney side data, order book, tick data, news, announcements, research reports, or AI retrieval in this plan.
- Feature-aware backtest strategy `sma_cross_feature_filter` remains `1d` only.
- Minute side-data chart layers remain unsupported until a separate minute side-data alignment design exists.
- Collector-generated out-of-session minute rows must fail validation. Silent filtering is not allowed.
- CI tests must mock provider calls. Live `akshare` smoke is manual only.
- Do not revert unrelated workspace changes. If executing in the current dirty workspace, treat commit steps as checkpoints and only commit if the user explicitly asks for commits.

---

## Assumptions

- Phase 1, Phase 2, Phase 3A, and Phase 3B-minimal code already exist in this workspace.
- `ResearchMarketDataSource`, `LocalCsvResearchDataSource`, `AShareOhlcvCollector`, `AkshareAshareOhlcvProvider`, and `tools/download_a_share_research_data.py` already exist from Phase 1.
- `ResearchUnsupportedFeatureError` already maps to HTTP `501` in research API routes.
- The current A-share research webserver may run on a non-default local port; implementation verification can use the active app browser URL.
- `akshare.stock_zh_a_minute` timestamps are treated as candle-close labels in Phase 1B. The collector converts them to canonical candle-open timestamps by subtracting the timeframe duration.

## Success Criteria

- `LocalCsvResearchDataSource.available_timeframes("688017.SH")` returns collected supported timeframes in registry order: `["1m", "5m", "15m", "30m", "60m", "1d"]`.
- `LocalCsvResearchDataSource.load_ohlcv("688017.SH", "1m")` returns timezone-aware UTC timestamps.
- `AShareOhlcvCollector` can write `688017.SH-1m.csv`, `688017.SH-5m.csv`, `688017.SH-15m.csv`, `688017.SH-30m.csv`, `688017.SH-60m.csv`, and `688017.SH-1d.csv`.
- Minute files preserve intraday timestamps and never collapse same-day rows into duplicate dates.
- Manifests record provider endpoint, source timestamp semantics, canonical timestamp semantics, timezone, history-depth policy, and row counts.
- `AkshareAshareOhlcvProvider` routes daily requests to `stock_zh_a_hist` and minute requests to `stock_zh_a_minute`.
- `/research/chart_candles` renders local minute files.
- `/research/backtest` runs ordinary `sma_cross` on local minute files within the row limit.
- `/research/backtest` rejects feature-aware strategy requests on minute timeframes with `501`.
- `/research/chart_candles` rejects side-data layer requests on minute timeframes with `501`.
- Existing daily raw behavior remains compatible.

## File Structure

### Backend Package

- Create: `freqtrade/freqtrade/research/a_share_timeframes.py`
  - Single source of truth for supported A-share research OHLCV timeframes.
- Create: `freqtrade/freqtrade/research/a_share_sessions.py`
  - Regular-session validation for minute OHLCV timestamps.
- Modify: `freqtrade/freqtrade/research/data_source.py`
  - Use shared timeframe registry, support minute file discovery and loading, validate minute sessions.
- Modify: `freqtrade/freqtrade/research/collectors/a_share_ohlcv.py`
  - Accept supported minute timeframes, normalize timestamp semantics, validate minute sessions, enrich manifests.
- Modify: `freqtrade/freqtrade/research/data_sources/akshare_ashare.py`
  - Route minute timeframes to `akshare.stock_zh_a_minute`, convert symbols to Sina format, post-filter timeranges.
- Modify: `freqtrade/freqtrade/research/chart.py`
  - Reject side-data layer requests on non-`1d` timeframes.
- Modify: `freqtrade/freqtrade/rpc/api_server/api_research.py`
  - Reject feature-aware strategy requests on non-`1d` timeframes before loading side-data.
- Modify: `freqtrade/freqtrade/research/backtesting.py`
  - Guard execution rows with regular-session checks for intraday timestamps.

### Tests

- Create: `freqtrade/tests/research/test_a_share_timeframes.py`
- Create: `freqtrade/tests/research/test_a_share_sessions.py`
- Modify: `freqtrade/tests/research/test_data_source.py`
- Modify: `freqtrade/tests/research/test_a_share_ohlcv_collector.py`
- Modify: `freqtrade/tests/research/test_akshare_ashare_data_source.py`
- Modify: `freqtrade/tests/research/test_backtesting.py`
- Modify: `freqtrade/tests/rpc/test_api_research.py`

### Tooling And Docs

- Modify: `tools/download_a_share_research_data.py`
  - Help text and examples should allow supported minute timeframes.
- Modify: `docs/a-share-research-data.md`
  - Replace Phase 1 daily-only notes with Phase 1B multi-timeframe operator contract.

---

## Task 1: Shared Timeframe And Session Utilities

**Files:**
- Create: `freqtrade/freqtrade/research/a_share_timeframes.py`
- Create: `freqtrade/freqtrade/research/a_share_sessions.py`
- Create: `freqtrade/tests/research/test_a_share_timeframes.py`
- Create: `freqtrade/tests/research/test_a_share_sessions.py`

**Interfaces:**
- Produces: `SUPPORTED_A_SHARE_OHLCV_TIMEFRAMES: tuple[str, ...]`
- Produces: `MINUTE_A_SHARE_OHLCV_TIMEFRAMES: tuple[str, ...]`
- Produces: `validate_a_share_ohlcv_timeframe(timeframe: str) -> str`
- Produces: `is_a_share_minute_timeframe(timeframe: str) -> bool`
- Produces: `timeframe_to_minutes(timeframe: str) -> int`
- Produces: `sort_a_share_ohlcv_timeframes(timeframes: Iterable[str]) -> list[str]`
- Produces: `is_a_share_regular_session_timestamp(value: Any) -> bool`
- Produces: `validate_a_share_regular_session_frame(dataframe: pd.DataFrame, timeframe: str) -> None`

- [ ] **Step 1: Write failing timeframe registry tests**

Create `freqtrade/tests/research/test_a_share_timeframes.py`:

```python
import pytest

from freqtrade.research.a_share_timeframes import (
    MINUTE_A_SHARE_OHLCV_TIMEFRAMES,
    SUPPORTED_A_SHARE_OHLCV_TIMEFRAMES,
    is_a_share_minute_timeframe,
    sort_a_share_ohlcv_timeframes,
    timeframe_to_minutes,
    validate_a_share_ohlcv_timeframe,
)
from freqtrade.research.exceptions import ResearchUnsupportedFeatureError


def test_supported_a_share_timeframe_registry_order() -> None:
    assert SUPPORTED_A_SHARE_OHLCV_TIMEFRAMES == ("1m", "5m", "15m", "30m", "60m", "1d")
    assert MINUTE_A_SHARE_OHLCV_TIMEFRAMES == ("1m", "5m", "15m", "30m", "60m")


@pytest.mark.parametrize("timeframe", ["1m", "5m", "15m", "30m", "60m", "1d"])
def test_validate_a_share_ohlcv_timeframe_accepts_supported_values(timeframe: str) -> None:
    assert validate_a_share_ohlcv_timeframe(timeframe) == timeframe


@pytest.mark.parametrize("timeframe", ["3m", "2h", "4h", "1w", "1M"])
def test_validate_a_share_ohlcv_timeframe_rejects_unsupported_values(timeframe: str) -> None:
    with pytest.raises(
        ResearchUnsupportedFeatureError,
        match=f"Research timeframe {timeframe} is not supported yet.",
    ):
        validate_a_share_ohlcv_timeframe(timeframe)


@pytest.mark.parametrize("timeframe", ["", "../1d", "1-day", "abc"])
def test_validate_a_share_ohlcv_timeframe_rejects_invalid_syntax(timeframe: str) -> None:
    with pytest.raises(ValueError, match="Invalid research timeframe"):
        validate_a_share_ohlcv_timeframe(timeframe)


def test_minute_timeframe_detection_and_duration() -> None:
    assert is_a_share_minute_timeframe("1m") is True
    assert is_a_share_minute_timeframe("60m") is True
    assert is_a_share_minute_timeframe("1d") is False
    assert timeframe_to_minutes("1m") == 1
    assert timeframe_to_minutes("5m") == 5
    assert timeframe_to_minutes("15m") == 15
    assert timeframe_to_minutes("30m") == 30
    assert timeframe_to_minutes("60m") == 60
    assert timeframe_to_minutes("1d") == 1440


def test_sort_a_share_ohlcv_timeframes_uses_registry_order() -> None:
    assert sort_a_share_ohlcv_timeframes({"60m", "1d", "1m", "15m", "5m"}) == [
        "1m",
        "5m",
        "15m",
        "60m",
        "1d",
    ]
```

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_a_share_timeframes.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'freqtrade.research.a_share_timeframes'`.

- [ ] **Step 2: Add the timeframe registry**

Create `freqtrade/freqtrade/research/a_share_timeframes.py`:

```python
from collections.abc import Iterable
import re

from freqtrade.research.exceptions import ResearchUnsupportedFeatureError


SUPPORTED_A_SHARE_OHLCV_TIMEFRAMES = ("1m", "5m", "15m", "30m", "60m", "1d")
MINUTE_A_SHARE_OHLCV_TIMEFRAMES = ("1m", "5m", "15m", "30m", "60m")

_TIMEFRAME_RE = re.compile(r"^[0-9]+[mhdwM]$")
_TIMEFRAME_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "60m": 60,
    "1d": 1440,
}
_TIMEFRAME_ORDER = {
    timeframe: index for index, timeframe in enumerate(SUPPORTED_A_SHARE_OHLCV_TIMEFRAMES)
}


def validate_a_share_ohlcv_timeframe(timeframe: str) -> str:
    if not timeframe or not _TIMEFRAME_RE.fullmatch(timeframe):
        raise ValueError("Invalid research timeframe")
    if timeframe not in SUPPORTED_A_SHARE_OHLCV_TIMEFRAMES:
        raise ResearchUnsupportedFeatureError(
            f"Research timeframe {timeframe} is not supported yet."
        )
    return timeframe


def is_a_share_minute_timeframe(timeframe: str) -> bool:
    return timeframe in MINUTE_A_SHARE_OHLCV_TIMEFRAMES


def timeframe_to_minutes(timeframe: str) -> int:
    validate_a_share_ohlcv_timeframe(timeframe)
    return _TIMEFRAME_MINUTES[timeframe]


def sort_a_share_ohlcv_timeframes(timeframes: Iterable[str]) -> list[str]:
    return sorted(timeframes, key=lambda timeframe: _TIMEFRAME_ORDER[timeframe])
```

- [ ] **Step 3: Verify timeframe tests pass**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_a_share_timeframes.py -q
```

Expected: PASS.

- [ ] **Step 4: Write failing session utility tests**

Create `freqtrade/tests/research/test_a_share_sessions.py`:

```python
import pandas as pd
import pytest

from freqtrade.research.a_share_sessions import (
    is_a_share_regular_session_timestamp,
    validate_a_share_regular_session_frame,
)


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-07-07T01:30:00Z",  # 09:30 Asia/Shanghai
        "2026-07-07T03:29:00Z",  # 11:29 Asia/Shanghai
        "2026-07-07T05:00:00Z",  # 13:00 Asia/Shanghai
        "2026-07-07T06:59:00Z",  # 14:59 Asia/Shanghai
    ],
)
def test_is_a_share_regular_session_timestamp_accepts_open_minutes(timestamp: str) -> None:
    assert is_a_share_regular_session_timestamp(timestamp) is True


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-07-07T01:29:00Z",  # before 09:30 Asia/Shanghai
        "2026-07-07T03:30:00Z",  # lunch break boundary
        "2026-07-07T04:00:00Z",  # lunch break
        "2026-07-07T07:00:00Z",  # 15:00 Asia/Shanghai
    ],
)
def test_is_a_share_regular_session_timestamp_rejects_closed_minutes(timestamp: str) -> None:
    assert is_a_share_regular_session_timestamp(timestamp) is False


def test_validate_a_share_regular_session_frame_allows_daily_timeframe() -> None:
    frame = pd.DataFrame({"date": pd.to_datetime(["2026-07-07"], utc=True)})

    validate_a_share_regular_session_frame(frame, "1d")


def test_validate_a_share_regular_session_frame_rejects_out_of_session_minute_row() -> None:
    frame = pd.DataFrame(
        {"date": pd.to_datetime(["2026-07-07T03:30:00Z"], utc=True)}
    )

    with pytest.raises(ValueError, match="A-share minute OHLCV contains out-of-session rows"):
        validate_a_share_regular_session_frame(frame, "1m")
```

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_a_share_sessions.py -q
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 5: Add session utility implementation**

Create `freqtrade/freqtrade/research/a_share_sessions.py`:

```python
from datetime import time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from pandas import DataFrame

from freqtrade.research.a_share_timeframes import is_a_share_minute_timeframe


_ASIA_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MORNING_START = time(9, 30)
_MORNING_END = time(11, 30)
_AFTERNOON_START = time(13, 0)
_AFTERNOON_END = time(15, 0)


def is_a_share_regular_session_timestamp(value: Any) -> bool:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(_ASIA_SHANGHAI)
    else:
        timestamp = timestamp.tz_convert(_ASIA_SHANGHAI)

    local_time = timestamp.time()
    return (
        _MORNING_START <= local_time < _MORNING_END
        or _AFTERNOON_START <= local_time < _AFTERNOON_END
    )


def validate_a_share_regular_session_frame(dataframe: DataFrame, timeframe: str) -> None:
    if not is_a_share_minute_timeframe(timeframe):
        return

    dates = pd.to_datetime(dataframe["date"], utc=True, errors="raise")
    invalid = [
        str(value)
        for value in dates
        if not is_a_share_regular_session_timestamp(value)
    ]
    if invalid:
        raise ValueError(
            "A-share minute OHLCV contains out-of-session rows: "
            + ", ".join(invalid[:3])
        )
```

- [ ] **Step 6: Run utility tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_a_share_timeframes.py tests/research/test_a_share_sessions.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit checkpoint**

Run only if the user wants commits:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
git add freqtrade/research/a_share_timeframes.py freqtrade/research/a_share_sessions.py tests/research/test_a_share_timeframes.py tests/research/test_a_share_sessions.py
git commit -m "feat: add a-share research timeframe registry"
```

---

## Task 2: Local CSV Data Source Multi-Timeframe Read Support

**Files:**
- Modify: `freqtrade/freqtrade/research/data_source.py`
- Modify: `freqtrade/tests/research/test_data_source.py`

**Interfaces:**
- Consumes: `validate_a_share_ohlcv_timeframe(timeframe: str) -> str`
- Consumes: `sort_a_share_ohlcv_timeframes(timeframes: Iterable[str]) -> list[str]`
- Consumes: `validate_a_share_regular_session_frame(dataframe: DataFrame, timeframe: str) -> None`
- Produces: `LocalCsvResearchDataSource.available_timeframes()` returns registry-ordered supported timeframes.
- Produces: `LocalCsvResearchDataSource.load_ohlcv()` supports minute files with UTC timestamps.

- [ ] **Step 1: Update data source tests to expect minute support**

Modify `freqtrade/tests/research/test_data_source.py`.

Replace `test_local_csv_research_data_source_lists_available_timeframes` with:

```python
def test_local_csv_research_data_source_lists_available_timeframes(tmp_path) -> None:
    for filename in [
        "600519.SH-60m.csv",
        "600519.SH-15m.csv",
        "600519.SH-1m.csv",
        "600519.SH-5m.csv",
        "600519.SH-1d.csv",
        "600519.SH-bad.csv",
        "000001.SZ-1d.csv",
    ]:
        (tmp_path / filename).write_text(
            "date,open,high,low,close,volume\n2026-07-07T01:30:00Z,1,1,1,1,1\n",
            encoding="utf-8",
        )
    data_source = LocalCsvResearchDataSource(tmp_path)

    assert data_source.available_timeframes("600519.SH") == [
        "1m",
        "5m",
        "15m",
        "60m",
        "1d",
    ]
```

Replace `test_local_csv_research_data_source_skips_unsupported_timeframe_files` with:

```python
def test_local_csv_research_data_source_lists_supported_minute_timeframe_files(tmp_path) -> None:
    (tmp_path / "600519.SH-5m.csv").write_text(
        "date,open,high,low,close,volume\n2026-07-07T01:30:00Z,1700,1710,1690,1705,100000\n",
        encoding="utf-8",
    )

    data_source = LocalCsvResearchDataSource(tmp_path)

    assert [instrument.key for instrument in data_source.list_instruments()] == ["600519.SH"]
    assert data_source.available_timeframes("600519.SH") == ["5m"]
```

Replace the unsupported timeframe parametrization with:

```python
@pytest.mark.parametrize("timeframe", ["3m", "1w", "1M"])
def test_local_csv_research_data_source_rejects_unsupported_timeframe_even_if_file_exists(
    tmp_path,
    timeframe,
) -> None:
    (tmp_path / f"600519.SH-{timeframe}.csv").write_text(
        "date,open,high,low,close,volume\n2026-07-06,1700,1710,1690,1705,100000\n",
        encoding="utf-8",
    )
    data_source = LocalCsvResearchDataSource(tmp_path)

    with pytest.raises(
        ResearchUnsupportedFeatureError,
        match=f"Research timeframe {timeframe} is not supported yet.",
    ):
        data_source.load_ohlcv("600519.SH", timeframe)
```

Append this minute load test:

```python
def test_local_csv_research_data_source_loads_minute_ohlcv_with_utc_timestamps(tmp_path) -> None:
    (tmp_path / "688017.SH-1m.csv").write_text(
        "date,open,high,low,close,volume\n"
        "2026-07-07T01:31:00Z,461,462,460,461.5,1200\n"
        "2026-07-07T01:30:00Z,460,461,459,460.5,1000\n",
        encoding="utf-8",
    )
    data_source = LocalCsvResearchDataSource(tmp_path)

    dataframe = data_source.load_ohlcv("688017.SH", "1m")

    assert dataframe["date"].tolist() == [
        pd.Timestamp("2026-07-07T01:30:00Z"),
        pd.Timestamp("2026-07-07T01:31:00Z"),
    ]
    assert pd.api.types.is_float_dtype(dataframe["open"])
```

Append this out-of-session read test:

```python
def test_local_csv_research_data_source_rejects_out_of_session_minute_ohlcv(tmp_path) -> None:
    (tmp_path / "688017.SH-1m.csv").write_text(
        "date,open,high,low,close,volume\n"
        "2026-07-07T03:30:00Z,460,461,459,460.5,1000\n",
        encoding="utf-8",
    )
    data_source = LocalCsvResearchDataSource(tmp_path)

    with pytest.raises(ValueError, match="A-share minute OHLCV contains out-of-session rows"):
        data_source.load_ohlcv("688017.SH", "1m")
```

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_data_source.py -q
```

Expected: FAIL because `5m` is still skipped and rejected.

- [ ] **Step 2: Use registry and session validation in `data_source.py`**

Modify `freqtrade/freqtrade/research/data_source.py`.

Replace the local timeframe constants:

```python
SUPPORTED_A_SHARE_RESEARCH_TIMEFRAMES = {"1d"}
```

and local validation logic with imports:

```python
from freqtrade.research.a_share_sessions import validate_a_share_regular_session_frame
from freqtrade.research.a_share_timeframes import (
    sort_a_share_ohlcv_timeframes,
    validate_a_share_ohlcv_timeframe,
)
```

Change `available_timeframes` return:

```python
        return sort_a_share_ohlcv_timeframes(timeframes)
```

Change `load_ohlcv` after numeric conversion:

```python
        validate_a_share_regular_session_frame(dataframe, timeframe)

        return dataframe.sort_values("date").reset_index(drop=True)
```

Change `_parse_a_share_csv_stem` timeframe validation:

```python
    timeframe = match.group("timeframe")
    try:
        timeframe = validate_a_share_ohlcv_timeframe(timeframe)
    except (ResearchUnsupportedFeatureError, ValueError):
        return None
```

Change `_validate_timeframe`:

```python
def _validate_timeframe(timeframe: str) -> str:
    return validate_a_share_ohlcv_timeframe(timeframe)
```

- [ ] **Step 3: Run data source tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_data_source.py tests/research/test_a_share_timeframes.py tests/research/test_a_share_sessions.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit checkpoint**

Run only if the user wants commits:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
git add freqtrade/research/data_source.py tests/research/test_data_source.py
git commit -m "feat: load a-share minute research csv files"
```

---

## Task 3: Collector Normalization, Timestamp Semantics, And Manifest Metadata

**Files:**
- Modify: `freqtrade/freqtrade/research/collectors/a_share_ohlcv.py`
- Modify: `freqtrade/tests/research/test_a_share_ohlcv_collector.py`

**Interfaces:**
- Consumes: `validate_a_share_ohlcv_timeframe`, `is_a_share_minute_timeframe`, `timeframe_to_minutes`
- Consumes: `validate_a_share_regular_session_frame`
- Produces: `provider_period_for_timeframe(timeframe: str) -> str` supports minute provider periods.
- Produces: `normalize_provider_ohlcv(provider_dataframe, *, timeframe, source_timestamp_semantics, source_timezone="Asia/Shanghai")`
- Produces: collector manifests include provider endpoint, timestamp semantics, and history-depth fields when available.

- [ ] **Step 1: Update collector tests for supported minute periods**

Modify `freqtrade/tests/research/test_a_share_ohlcv_collector.py`.

Replace `test_provider_period_for_daily_timeframe` with:

```python
@pytest.mark.parametrize(
    ("timeframe", "provider_period"),
    [
        ("1m", "1"),
        ("5m", "5"),
        ("15m", "15"),
        ("30m", "30"),
        ("60m", "60"),
        ("1d", "daily"),
    ],
)
def test_provider_period_for_supported_timeframes(timeframe: str, provider_period: str) -> None:
    assert provider_period_for_timeframe(timeframe) == provider_period
```

Replace the unsupported timeframe parametrization with:

```python
@pytest.mark.parametrize("timeframe", ["3m", "1w", "1M"])
def test_provider_period_rejects_unsupported_timeframe(timeframe: str) -> None:
    with pytest.raises(
        AShareOhlcvCollectionError,
        match=f"Unsupported A-share OHLCV timeframe: {timeframe}",
    ):
        provider_period_for_timeframe(timeframe)
```

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_a_share_ohlcv_collector.py::test_provider_period_for_supported_timeframes -q
```

Expected: FAIL for minute timeframes.

- [ ] **Step 2: Add minute normalizer tests**

Append to `freqtrade/tests/research/test_a_share_ohlcv_collector.py`:

```python
def test_normalize_provider_ohlcv_preserves_minute_timestamps_as_utc_candle_open() -> None:
    provider_dataframe = pd.DataFrame(
        {
            "day": ["2026-07-07 09:31:00", "2026-07-07 09:32:00"],
            "open": [460, 461],
            "high": [461, 462],
            "low": [459, 460],
            "close": [460.5, 461.5],
            "volume": [1000, 1200],
            "amount": [460500, 553800],
        }
    )

    dataframe, warnings = normalize_provider_ohlcv(
        provider_dataframe,
        timeframe="1m",
        source_timestamp_semantics="candle_close",
    )

    assert warnings == []
    assert dataframe["date"].tolist() == [
        "2026-07-07T01:30:00Z",
        "2026-07-07T01:31:00Z",
    ]
    assert list(dataframe.columns) == RESEARCH_OHLCV_COLUMNS
```

Append duplicate minute tests:

```python
def test_normalize_provider_ohlcv_rejects_conflicting_duplicate_minute_timestamps() -> None:
    provider_dataframe = pd.DataFrame(
        {
            "day": ["2026-07-07 09:31:00", "2026-07-07 09:31:00"],
            "open": [460, 461],
            "high": [461, 462],
            "low": [459, 460],
            "close": [460.5, 461.5],
            "volume": [1000, 1200],
        }
    )

    with pytest.raises(AShareOhlcvCollectionError, match="Conflicting duplicate OHLCV timestamps"):
        normalize_provider_ohlcv(
            provider_dataframe,
            timeframe="1m",
            source_timestamp_semantics="candle_close",
        )


def test_normalize_provider_ohlcv_rejects_out_of_session_minute_timestamp() -> None:
    provider_dataframe = pd.DataFrame(
        {
            "day": ["2026-07-07 11:31:00"],
            "open": [460],
            "high": [461],
            "low": [459],
            "close": [460.5],
            "volume": [1000],
        }
    )

    with pytest.raises(ValueError, match="A-share minute OHLCV contains out-of-session rows"):
        normalize_provider_ohlcv(
            provider_dataframe,
            timeframe="1m",
            source_timestamp_semantics="candle_close",
        )
```

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_a_share_ohlcv_collector.py -q
```

Expected: FAIL because normalizer still has no timeframe or timestamp semantics.

- [ ] **Step 3: Update fake providers in collector tests**

In `freqtrade/tests/research/test_a_share_ohlcv_collector.py`, add these methods to fake provider classes that inherit from `FakeOhlcvProvider`:

```python
    def source_timestamp_semantics(self, timeframe: str) -> str:
        return "candle_open"

    def provider_endpoint(self, timeframe: str) -> str:
        return "fake_ohlcv"

    def history_depth_metadata(self, timeframe: str) -> dict[str, object]:
        return {}
```

For a fake minute provider test, use:

```python
class FakeMinuteOhlcvProvider(FakeOhlcvProvider):
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
                "day": ["2026-07-07 09:31:00", "2026-07-07 09:32:00"],
                "open": [460, 461],
                "high": [461, 462],
                "low": [459, 460],
                "close": [460.5, 461.5],
                "volume": [1000, 1200],
            }
        )

    def source_timestamp_semantics(self, timeframe: str) -> str:
        return "candle_close"

    def provider_endpoint(self, timeframe: str) -> str:
        return "stock_zh_a_minute"

    def history_depth_metadata(self, timeframe: str) -> dict[str, object]:
        return {"history_depth_policy": "provider_latest_bars", "provider_row_limit": 1970}
```

Append this collector minute manifest test:

```python
def test_collector_writes_minute_csv_and_manifest_timestamp_metadata(tmp_path) -> None:
    collector = AShareOhlcvCollector(tmp_path, FakeMinuteOhlcvProvider())

    summary = collector.collect(
        AShareOhlcvRequest(instruments=["688017.SH"], timeframes=["1m"])
    )

    assert summary.failed == 0
    csv_text = (tmp_path / "688017.SH-1m.csv").read_text(encoding="utf-8")
    assert "2026-07-07T01:30:00Z,460.0,461.0,459.0,460.5,1000.0" in csv_text

    manifest_path = next((tmp_path / ".manifests").glob("*.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["files"][0]["path"] == "688017.SH-1m.csv"
    assert manifest["provider_endpoint"] == "stock_zh_a_minute"
    assert manifest["timestamp_semantics"] == {
        "source_timezone": "Asia/Shanghai",
        "source_timestamp_semantics": "candle_close",
        "canonical_timezone": "UTC",
        "canonical_timestamp_semantics": "candle_open",
    }
    assert manifest["history_depth_policy"] == "provider_latest_bars"
    assert manifest["provider_row_limit"] == 1970
```

- [ ] **Step 4: Update provider period mapping and request validation**

Modify `freqtrade/freqtrade/research/collectors/a_share_ohlcv.py`.

Replace `_PROVIDER_PERIOD_BY_TIMEFRAME` with:

```python
_PROVIDER_PERIOD_BY_TIMEFRAME = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "60m": "60",
    "1d": "daily",
}
```

Import shared utilities:

```python
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from freqtrade.research.a_share_sessions import validate_a_share_regular_session_frame
from freqtrade.research.a_share_timeframes import (
    is_a_share_minute_timeframe,
    timeframe_to_minutes,
    validate_a_share_ohlcv_timeframe,
)
```

In `AShareOhlcvCollector.collect`, replace the timeframe validation loop with:

```python
        for timeframe in request.timeframes:
            validate_a_share_ohlcv_timeframe(timeframe)
            provider_period_for_timeframe(timeframe)
```

- [ ] **Step 5: Update normalizer signature and timestamp handling**

Modify `normalize_provider_ohlcv` signature:

```python
def normalize_provider_ohlcv(
    provider_dataframe: pd.DataFrame,
    *,
    timeframe: str = "1d",
    source_timestamp_semantics: str = "candle_open",
    source_timezone: str = "Asia/Shanghai",
) -> tuple[pd.DataFrame, list[str]]:
```

Update date normalization call:

```python
    dataframe["date"] = _normalize_dates(
        dataframe["date"],
        timeframe=timeframe,
        source_timestamp_semantics=source_timestamp_semantics,
        source_timezone=source_timezone,
    )
```

Add or replace `_normalize_dates` with:

```python
def _normalize_dates(
    dates: pd.Series,
    *,
    timeframe: str,
    source_timestamp_semantics: str,
    source_timezone: str,
) -> pd.Series:
    try:
        parsed_dates = pd.to_datetime(dates, errors="raise")
    except (TypeError, ValueError) as exc:
        raise AShareOhlcvCollectionError("OHLCV dates must be valid.") from exc

    if parsed_dates.isna().any():
        raise AShareOhlcvCollectionError("OHLCV dates must be valid.")

    if not is_a_share_minute_timeframe(timeframe):
        return parsed_dates.dt.strftime("%Y-%m-%d")

    if source_timestamp_semantics not in {"candle_open", "candle_close"}:
        raise AShareOhlcvCollectionError(
            f"Unsupported source timestamp semantics: {source_timestamp_semantics}"
        )

    if parsed_dates.dt.tz is None:
        localized = parsed_dates.dt.tz_localize(ZoneInfo(source_timezone))
    else:
        localized = parsed_dates.dt.tz_convert(ZoneInfo(source_timezone))

    if source_timestamp_semantics == "candle_close":
        localized = localized - timedelta(minutes=timeframe_to_minutes(timeframe))

    return localized.dt.tz_convert(UTC).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
```

Update `_PROVIDER_COLUMN_ALIASES["date"]`:

```python
    "date": ("date", "\u65e5\u671f", "day", "\u65f6\u95f4"),
```

Rename duplicate helper message from date-specific to timestamp-specific:

```python
def _reject_or_drop_duplicate_timestamps(dataframe: pd.DataFrame) -> list[str]:
    duplicate_rows = dataframe[dataframe.duplicated("date", keep=False)]
    if duplicate_rows.empty:
        return []

    for _, rows_for_date in duplicate_rows.groupby("date", sort=False):
        if len(rows_for_date.drop_duplicates(subset=RESEARCH_OHLCV_COLUMNS)) > 1:
            raise AShareOhlcvCollectionError("Conflicting duplicate OHLCV timestamps.")

    duplicate_count = len(dataframe) - len(
        dataframe.drop_duplicates(subset=RESEARCH_OHLCV_COLUMNS, keep="first")
    )
    return [f"Dropped {duplicate_count} identical duplicate OHLCV rows."]
```

After duplicate handling and sorting, validate sessions:

```python
    dataframe = dataframe.drop_duplicates(subset=RESEARCH_OHLCV_COLUMNS, keep="first")
    dataframe = dataframe.sort_values("date", kind="stable").reset_index(drop=True)
    session_frame = dataframe.copy()
    session_frame["date"] = pd.to_datetime(session_frame["date"], utc=True)
    validate_a_share_regular_session_frame(session_frame, timeframe)

    return dataframe, warnings
```

- [ ] **Step 6: Pass provider timestamp metadata into normalization**

In `_collect_one`, replace:

```python
            dataframe, warnings = normalize_provider_ohlcv(provider_dataframe)
```

with:

```python
            source_timestamp_semantics = _provider_source_timestamp_semantics(
                self._provider,
                timeframe,
            )
            dataframe, warnings = normalize_provider_ohlcv(
                provider_dataframe,
                timeframe=timeframe,
                source_timestamp_semantics=source_timestamp_semantics,
            )
```

Add helpers near the bottom of the file:

```python
def _provider_source_timestamp_semantics(
    provider: AShareOhlcvProvider,
    timeframe: str,
) -> str:
    method = getattr(provider, "source_timestamp_semantics", None)
    if method is not None:
        return method(timeframe)
    if is_a_share_minute_timeframe(timeframe):
        raise AShareOhlcvCollectionError(
            "Minute OHLCV provider must declare source timestamp semantics."
        )
    return "candle_open"


def _provider_endpoint(provider: AShareOhlcvProvider, timeframe: str) -> str | None:
    method = getattr(provider, "provider_endpoint", None)
    return method(timeframe) if method is not None else None


def _provider_history_depth_metadata(
    provider: AShareOhlcvProvider,
    timeframe: str,
) -> dict[str, object]:
    method = getattr(provider, "history_depth_metadata", None)
    return method(timeframe) if method is not None else {}
```

- [ ] **Step 7: Enrich manifest metadata**

In `_write_manifest`, compute metadata from the first requested timeframe:

```python
        primary_timeframe = request.timeframes[0] if request.timeframes else "1d"
        history_depth_metadata = _provider_history_depth_metadata(
            self._provider,
            primary_timeframe,
        )
        provider_endpoint = _provider_endpoint(self._provider, primary_timeframe)
        timestamp_semantics = {
            "source_timezone": "Asia/Shanghai",
            "source_timestamp_semantics": _provider_source_timestamp_semantics(
                self._provider,
                primary_timeframe,
            ),
            "canonical_timezone": "UTC",
            "canonical_timestamp_semantics": "candle_open",
        }
```

Add fields to `manifest`:

```python
            "timeframe_registry_version": "a_share_ohlcv_v1b",
            "timestamp_semantics": timestamp_semantics,
            "provider_endpoint": provider_endpoint,
            "session_filter": "a_share_regular_session"
            if is_a_share_minute_timeframe(primary_timeframe)
            else None,
            **history_depth_metadata,
```

Keep old manifest fields unchanged so `find_local_csv_provenance()` remains compatible.

- [ ] **Step 8: Run collector tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_a_share_ohlcv_collector.py tests/research/test_a_share_timeframes.py tests/research/test_a_share_sessions.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit checkpoint**

Run only if the user wants commits:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
git add freqtrade/research/collectors/a_share_ohlcv.py tests/research/test_a_share_ohlcv_collector.py
git commit -m "feat: normalize a-share minute ohlcv"
```

---

## Task 4: AkShare Minute Provider Adapter

**Files:**
- Modify: `freqtrade/freqtrade/research/data_sources/akshare_ashare.py`
- Modify: `freqtrade/tests/research/test_akshare_ashare_data_source.py`

**Interfaces:**
- Consumes: `provider_period_for_timeframe(timeframe: str) -> str`
- Produces: `AkshareAshareOhlcvProvider.fetch_ohlcv()` routes daily and minute requests.
- Produces: `AkshareAshareOhlcvProvider.source_timestamp_semantics(timeframe: str) -> str`
- Produces: `AkshareAshareOhlcvProvider.provider_endpoint(timeframe: str) -> str`
- Produces: `AkshareAshareOhlcvProvider.history_depth_metadata(timeframe: str) -> dict[str, object]`

- [ ] **Step 1: Add failing daily and minute provider tests**

Modify `freqtrade/tests/research/test_akshare_ashare_data_source.py`.

Keep the existing daily test and add this minute test:

```python
def test_akshare_provider_maps_sse_minute_request_to_sina_symbol(monkeypatch) -> None:
    calls = []

    def stock_zh_a_minute(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            {
                "day": ["2026-07-07 09:31:00"],
                "open": [460],
                "high": [461],
                "low": [459],
                "close": [460.5],
                "volume": [1000],
                "amount": [460500],
            }
        )

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(stock_zh_a_minute=stock_zh_a_minute),
    )

    provider = AkshareAshareOhlcvProvider()
    dataframe = provider.fetch_ohlcv("688017.SH", "1m", None, None, "raw")

    assert len(dataframe) == 1
    assert calls == [{"symbol": "sh688017", "period": "1", "adjust": ""}]
    assert provider.source_timestamp_semantics("1m") == "candle_close"
    assert provider.provider_endpoint("1m") == "stock_zh_a_minute"
    assert provider.history_depth_metadata("1m") == {
        "history_depth_policy": "provider_latest_bars",
        "provider_row_limit": 1970,
    }
```

Add the Shenzhen test:

```python
def test_akshare_provider_maps_szse_minute_request_to_sina_symbol(monkeypatch) -> None:
    calls = []

    def stock_zh_a_minute(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            {
                "day": ["2026-07-07 09:31:00"],
                "open": [10],
                "high": [10.1],
                "low": [9.9],
                "close": [10.0],
                "volume": [1000],
            }
        )

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(stock_zh_a_minute=stock_zh_a_minute),
    )

    provider = AkshareAshareOhlcvProvider()
    provider.fetch_ohlcv("000001.SZ", "5m", None, None, "raw")

    assert calls == [{"symbol": "sz000001", "period": "5", "adjust": ""}]
```

Add timerange post-filter test:

```python
def test_akshare_provider_post_filters_minute_timerange(monkeypatch) -> None:
    def stock_zh_a_minute(**kwargs):
        return pd.DataFrame(
            {
                "day": [
                    "2026-07-01 09:31:00",
                    "2026-07-02 09:31:00",
                    "2026-07-03 09:31:00",
                ],
                "open": [1, 2, 3],
                "high": [1, 2, 3],
                "low": [1, 2, 3],
                "close": [1, 2, 3],
                "volume": [100, 200, 300],
            }
        )

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(stock_zh_a_minute=stock_zh_a_minute),
    )

    provider = AkshareAshareOhlcvProvider()
    dataframe = provider.fetch_ohlcv("688017.SH", "1m", "20260702", "20260702", "raw")

    assert dataframe["day"].tolist() == ["2026-07-02 09:31:00"]
```

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_akshare_ashare_data_source.py -q
```

Expected: FAIL because minute routing is not implemented.

- [ ] **Step 2: Implement minute routing**

Modify `freqtrade/freqtrade/research/data_sources/akshare_ashare.py`.

Add imports:

```python
from freqtrade.research.a_share_timeframes import is_a_share_minute_timeframe
```

Replace `fetch_ohlcv` body after provider import with:

```python
        if is_a_share_minute_timeframe(timeframe):
            dataframe = akshare.stock_zh_a_minute(
                symbol=_to_sina_symbol(instrument),
                period=period,
                adjust="",
            )
            return _filter_minute_timerange(dataframe, start_date, end_date)

        return akshare.stock_zh_a_hist(
            symbol=instrument.symbol,
            period=period,
            start_date=start_date or "19700101",
            end_date=end_date or "22220101",
            adjust="",
        )
```

Add methods to `AkshareAshareOhlcvProvider`:

```python
    def source_timestamp_semantics(self, timeframe: str) -> str:
        if is_a_share_minute_timeframe(timeframe):
            return "candle_close"
        return "candle_open"

    def provider_endpoint(self, timeframe: str) -> str:
        if is_a_share_minute_timeframe(timeframe):
            return "stock_zh_a_minute"
        return "stock_zh_a_hist"

    def history_depth_metadata(self, timeframe: str) -> dict[str, object]:
        if is_a_share_minute_timeframe(timeframe):
            return {
                "history_depth_policy": "provider_latest_bars",
                "provider_row_limit": 1970,
            }
        return {}
```

Add helper functions:

```python
def _to_sina_symbol(instrument) -> str:
    if instrument.venue == "SSE":
        return f"sh{instrument.symbol}"
    if instrument.venue == "SZSE":
        return f"sz{instrument.symbol}"
    raise AShareOhlcvCollectionError(f"Unsupported A-share venue: {instrument.venue}")


def _filter_minute_timerange(
    dataframe: pd.DataFrame,
    start_date: str | None,
    end_date: str | None,
) -> pd.DataFrame:
    if dataframe.empty or (start_date is None and end_date is None):
        return dataframe

    timestamp_column = "day" if "day" in dataframe.columns else "\u65f6\u95f4"
    dates = pd.to_datetime(dataframe[timestamp_column], errors="raise").dt.strftime("%Y%m%d")
    mask = pd.Series(True, index=dataframe.index)
    if start_date is not None:
        mask &= dates >= start_date
    if end_date is not None:
        mask &= dates <= end_date
    return dataframe.loc[mask].reset_index(drop=True)
```

- [ ] **Step 3: Run provider tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_akshare_ashare_data_source.py tests/research/test_a_share_ohlcv_collector.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit checkpoint**

Run only if the user wants commits:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
git add freqtrade/research/data_sources/akshare_ashare.py tests/research/test_akshare_ashare_data_source.py
git commit -m "feat: add akshare a-share minute provider"
```

---

## Task 5: Research API, Chart Side-Layer Guard, And Minute Backtest Guardrails

**Files:**
- Modify: `freqtrade/freqtrade/research/chart.py`
- Modify: `freqtrade/freqtrade/rpc/api_server/api_research.py`
- Modify: `freqtrade/freqtrade/research/backtesting.py`
- Modify: `freqtrade/tests/research/test_backtesting.py`
- Modify: `freqtrade/tests/rpc/test_api_research.py`

**Interfaces:**
- Consumes: `is_a_share_minute_timeframe(timeframe: str) -> bool`
- Consumes: `is_a_share_regular_session_timestamp(value: Any) -> bool`
- Produces: minute chart/backtest through local data.
- Produces: `ResearchUnsupportedFeatureError` for minute side-layer and feature-aware requests.

- [ ] **Step 1: Add API tests for minute chart and minute backtest**

Modify `freqtrade/tests/rpc/test_api_research.py`.

Add helper fixture data inside each test by writing a local minute file. Add:

```python
def test_research_instruments_exposes_minute_timeframes(research_client, tmp_path) -> None:
    data_root = tmp_path / "research_data" / "a_share"
    (data_root / "688017.SH-1m.csv").write_text(
        "date,open,high,low,close,volume\n"
        "2026-07-07T01:30:00Z,460,461,459,460.5,1000\n",
        encoding="utf-8",
    )
    (data_root / "688017.SH-5m.csv").write_text(
        "date,open,high,low,close,volume\n"
        "2026-07-07T01:30:00Z,460,461,459,460.5,1000\n",
        encoding="utf-8",
    )

    response = client_get(
        research_client,
        f"{BASE_URI}/research/instruments?bot_id=a-share-local",
    )

    assert response.status_code == 200
    item = next(item for item in response.json()["instruments"] if item["key"] == "688017.SH")
    assert item["available_timeframes"][:2] == ["1m", "5m"]
```

Add minute chart test:

```python
def test_research_chart_candles_returns_minute_local_ohlcv(research_client, tmp_path) -> None:
    data_root = tmp_path / "research_data" / "a_share"
    (data_root / "688017.SH-1m.csv").write_text(
        "date,open,high,low,close,volume\n"
        "2026-07-07T01:30:00Z,460,461,459,460.5,1000\n"
        "2026-07-07T01:31:00Z,460.5,462,460,461.5,1200\n",
        encoding="utf-8",
    )

    response = client_post(
        research_client,
        f"{BASE_URI}/research/chart_candles",
        data={
            "bot_id": "a-share-local",
            "instrument": "688017.SH",
            "timeframe": "1m",
            "limit": 10,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pair"] == "688017.SH"
    assert body["chart_timeframe"] == "1m"
    assert body["length"] == 2
```

Add minute backtest test:

```python
def test_research_backtest_runs_plain_sma_on_minute_local_ohlcv(research_client, tmp_path) -> None:
    data_root = tmp_path / "research_data" / "a_share"
    (data_root / "688017.SH-1m.csv").write_text(
        "date,open,high,low,close,volume\n"
        "2026-07-07T01:30:00Z,10,10.5,9.5,10,1000\n"
        "2026-07-07T01:31:00Z,9,9.5,8.5,9,1000\n"
        "2026-07-07T01:32:00Z,11,11.5,10.5,11,1000\n"
        "2026-07-07T01:33:00Z,12,12.5,11.5,12,1000\n"
        "2026-07-08T01:30:00Z,10,10.5,9.5,10,1000\n"
        "2026-07-08T01:31:00Z,8,8.5,7.5,8,1000\n",
        encoding="utf-8",
    )

    response = client_post(
        research_client,
        f"{BASE_URI}/research/backtest",
        data={
            "bot_id": "a-share-local",
            "instrument": "688017.SH",
            "timeframe": "1m",
            "initial_cash": 100000,
            "strategy": {"type": "sma_cross", "fast": 1, "slow": 2},
        },
    )

    assert response.status_code == 200
    assert response.json()["strategy"] == "sma_cross"
    assert "return_ratio" in response.json()["metrics"]
```

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/rpc/test_api_research.py -q
```

Expected: minute tests fail until data source/API changes are complete.

- [ ] **Step 2: Add feature-aware and side-layer rejection tests**

Add to `freqtrade/tests/rpc/test_api_research.py`:

```python
def test_research_backtest_rejects_feature_filter_on_minute_timeframe(
    research_client,
    tmp_path,
) -> None:
    data_root = tmp_path / "research_data" / "a_share"
    (data_root / "688017.SH-1m.csv").write_text(
        "date,open,high,low,close,volume\n"
        "2026-07-07T01:30:00Z,10,10.5,9.5,10,1000\n"
        "2026-07-07T01:31:00Z,11,11.5,10.5,11,1000\n",
        encoding="utf-8",
    )

    response = client_post(
        research_client,
        f"{BASE_URI}/research/backtest",
        data={
            "bot_id": "a-share-local",
            "instrument": "688017.SH",
            "timeframe": "1m",
            "initial_cash": 100000,
            "strategy": {
                "type": "sma_cross_feature_filter",
                "fast": 1,
                "slow": 2,
                "feature_filter": {
                    "dataset": "fund_flow_daily",
                    "field": "main_net_inflow",
                    "operator": ">",
                    "value": 0,
                    "missing": "block",
                },
            },
        },
    )

    assert response.status_code == 501
    assert "Feature-aware research backtest supports 1d only" in response.json()["detail"]
```

Add chart side-layer test:

```python
def test_research_chart_rejects_side_layers_on_minute_timeframe(
    research_client,
    tmp_path,
) -> None:
    data_root = tmp_path / "research_data" / "a_share"
    (data_root / "688017.SH-1m.csv").write_text(
        "date,open,high,low,close,volume\n"
        "2026-07-07T01:30:00Z,10,10.5,9.5,10,1000\n",
        encoding="utf-8",
    )

    response = client_post(
        research_client,
        f"{BASE_URI}/research/chart_candles",
        data={
            "bot_id": "a-share-local",
            "instrument": "688017.SH",
            "timeframe": "1m",
            "side_layers": {"features": ["fund_flow_daily"], "events": [], "documents": []},
        },
    )

    assert response.status_code == 501
    assert "Research side layers support 1d only" in response.json()["detail"]
```

- [ ] **Step 3: Add backtest session guard test**

Modify `freqtrade/tests/research/test_backtesting.py`.

Append:

```python
def test_research_backtest_blocks_out_of_session_intraday_execution_row() -> None:
    dataframe = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2026-07-07T01:30:00Z",
                    "2026-07-07T01:31:00Z",
                    "2026-07-07T01:32:00Z",
                    "2026-07-07T03:30:00Z",
                ],
                utc=True,
            ),
            "open": [10.0, 9.0, 11.0, 12.0],
            "high": [10.5, 9.5, 11.5, 12.5],
            "low": [9.5, 8.5, 10.5, 11.5],
            "close": [10.0, 9.0, 11.0, 12.0],
            "volume": [1000.0, 1000.0, 1000.0, 1000.0],
        }
    )

    result = run_research_backtest(
        "688017.SH",
        dataframe,
        ResearchBacktestConfig(initial_cash=10000, fast=1, slow=2),
    )

    assert any("Blocked fill outside A-share session" in warning for warning in result.warnings)
```

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_backtesting.py::test_research_backtest_blocks_out_of_session_intraday_execution_row -q
```

Expected: FAIL until backtest guard is implemented.

- [ ] **Step 4: Reject side layers on minute charts**

Modify `freqtrade/freqtrade/research/chart.py`.

Add imports:

```python
from freqtrade.research.a_share_timeframes import is_a_share_minute_timeframe
from freqtrade.research.exceptions import ResearchUnsupportedFeatureError
```

Before applying side layers, add:

```python
    if payload.side_layers and is_a_share_minute_timeframe(payload.timeframe):
        raise ResearchUnsupportedFeatureError("Research side layers support 1d only.")
```

- [ ] **Step 5: Reject feature-aware minute backtests in API**

Modify `freqtrade/freqtrade/rpc/api_server/api_research.py`.

Add import:

```python
from freqtrade.research.a_share_timeframes import is_a_share_minute_timeframe
```

Before creating `ResearchFeatureFilterConfig`, add:

```python
        if (
            request.strategy.type == "sma_cross_feature_filter"
            and is_a_share_minute_timeframe(request.timeframe)
        ):
            raise ResearchUnsupportedFeatureError(
                "Feature-aware research backtest supports 1d only."
            )
```

- [ ] **Step 6: Add backtest intraday session guard**

Modify `freqtrade/freqtrade/research/backtesting.py`.

Add import:

```python
from freqtrade.research.a_share_sessions import is_a_share_regular_session_timestamp
```

Modify `_can_execute_on_row`:

```python
def _can_execute_on_row(
    row_date: Any,
    market_context: ResearchMarketContext | None,
    warnings: list[str],
) -> bool:
    if _is_intraday_timestamp(row_date) and not is_a_share_regular_session_timestamp(row_date):
        warnings.append(f"Blocked fill outside A-share session on {_date_string(row_date)}")
        return False

    if market_context is None or market_context.calendar is None:
        return True
    if market_context.calendar.is_trading_day(row_date):
        return True
    warnings.append(f"Blocked fill on non-trading day {_date_string(row_date)}")
    return False
```

Add helper:

```python
def _is_intraday_timestamp(value: Any) -> bool:
    timestamp = pd.to_datetime(value, utc=True)
    return any(
        (
            timestamp.hour != 0,
            timestamp.minute != 0,
            timestamp.second != 0,
            timestamp.microsecond != 0,
        )
    )
```

Daily rows parsed as UTC midnight remain treated as daily bars and skip the
session-time guard.

- [ ] **Step 7: Run focused API and backtest tests**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_backtesting.py tests/rpc/test_api_research.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit checkpoint**

Run only if the user wants commits:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
git add freqtrade/research/chart.py freqtrade/rpc/api_server/api_research.py freqtrade/research/backtesting.py tests/research/test_backtesting.py tests/rpc/test_api_research.py
git commit -m "feat: support a-share minute research chart and backtest"
```

---

## Task 6: Tooling, Docs, And Real `688017.SH` Smoke

**Files:**
- Modify: `tools/download_a_share_research_data.py`
- Modify: `docs/a-share-research-data.md`
- Modify: `freqtrade/tests/research/test_a_share_phase1_smoke.py`

**Interfaces:**
- Consumes: Phase 1B collector/provider/local reader behavior.
- Produces: operator docs and a local smoke test proving collector output can feed chart/backtest.

- [ ] **Step 1: Update tool help test manually**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn
.\freqtrade\.venv\Scripts\python tools\download_a_share_research_data.py --help
```

Expected before editing: help may still imply only `1d` support.

- [ ] **Step 2: Update script help text**

Modify `tools/download_a_share_research_data.py`.

If the parser has a `--timeframes` help value like `"Supported value: 1d."`, replace it with:

```python
    parser.add_argument(
        "--timeframes",
        nargs="+",
        default=["1d"],
        help="Supported values: 1m 5m 15m 30m 60m 1d.",
    )
```

If the script prints per-file summaries, no behavior change is required. The collector summary will include minute paths and manifest metadata after previous tasks.

- [ ] **Step 3: Add or update smoke test for minute collector output**

Modify `freqtrade/tests/research/test_a_share_phase1_smoke.py`.

Add a fake minute provider:

```python
class FakeMinuteOhlcvProvider:
    provider_name = "fake-minute"
    provider_version = "test"

    def fetch_ohlcv(self, *args, **kwargs) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "day": [
                    "2026-07-07 09:31:00",
                    "2026-07-07 09:32:00",
                    "2026-07-07 09:33:00",
                    "2026-07-07 09:34:00",
                    "2026-07-08 09:31:00",
                    "2026-07-08 09:32:00",
                ],
                "open": [10, 9, 11, 12, 10, 8],
                "high": [10.5, 9.5, 11.5, 12.5, 10.5, 8.5],
                "low": [9.5, 8.5, 10.5, 11.5, 9.5, 7.5],
                "close": [10, 9, 11, 12, 10, 8],
                "volume": [1000, 1000, 1000, 1000, 1000, 1000],
            }
        )

    def source_timestamp_semantics(self, timeframe: str) -> str:
        return "candle_close"

    def provider_endpoint(self, timeframe: str) -> str:
        return "stock_zh_a_minute"

    def history_depth_metadata(self, timeframe: str) -> dict[str, object]:
        return {"history_depth_policy": "provider_latest_bars", "provider_row_limit": 1970}
```

Add smoke test:

```python
def test_minute_collector_output_feeds_research_chart_and_backtest(tmp_path) -> None:
    collector = AShareOhlcvCollector(root=tmp_path, provider=FakeMinuteOhlcvProvider())
    collector.collect(AShareOhlcvRequest(instruments=["688017.SH"], timeframes=["1m"]))
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
            instrument="688017.SH",
            timeframe="1m",
            limit=10,
        ),
    )
    assert chart["pair"] == "688017.SH"
    assert chart["chart_timeframe"] == "1m"
    assert chart["length"] == 6

    data_source = LocalCsvResearchDataSource(tmp_path)
    dataframe = data_source.load_ohlcv("688017.SH", "1m")
    result = run_research_backtest(
        "688017.SH",
        dataframe,
        ResearchBacktestConfig(initial_cash=100000, fast=1, slow=2),
    )
    assert result.metrics["initial_cash"] == 100000
    assert "return_ratio" in result.metrics
```

Add imports if absent:

```python
from freqtrade.research import LocalCsvResearchDataSource
```

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_a_share_phase1_smoke.py -q
```

Expected: PASS.

- [ ] **Step 4: Update operator documentation**

Modify `docs/a-share-research-data.md`.

Replace daily-only scope with:

```markdown
## Supported In Phase 1B

Phase 1B downloads raw A-share OHLCV into local research CSV files for:

```text
1m, 5m, 15m, 30m, 60m, 1d
```

Research chart and backtest read these local files through `local_csv`. They do
not call `akshare`, Eastmoney, Sina, Tencent, or `mootdx` during API requests.
```

Add command example:

```markdown
## Download Raw Multi-Timeframe OHLCV

Run from `G:\AI_Trading\freqtrade-cn`:

```powershell
.\freqtrade\.venv\Scripts\python tools\download_a_share_research_data.py `
  --config ft_userdata\user_data\config.research.example.json `
  --bot-id a-share-local `
  --instruments 688017.SH `
  --timeframes 1m 5m 15m 30m 60m 1d `
  --adjustment raw
```

Minute data from `akshare.stock_zh_a_minute` is recent-history data. The
provider returns about `1970` bars per requested minute period, and timerange is
applied as a local post-filter.
```

Replace unsupported-input section with:

```markdown
## Unsupported Inputs

`qfq` and `hfq` remain unsupported in Phase 1B. Feature-aware backtest and
side-data layers remain `1d`-only until minute side-data alignment is designed.
```

- [ ] **Step 5: Run full backend verification**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest `
  tests/research/test_a_share_timeframes.py `
  tests/research/test_a_share_sessions.py `
  tests/research/test_data_source.py `
  tests/research/test_a_share_ohlcv_collector.py `
  tests/research/test_akshare_ashare_data_source.py `
  tests/research/test_a_share_phase1_smoke.py `
  tests/research/test_backtesting.py `
  tests/rpc/test_api_research.py `
  -q
```

Expected: PASS.

- [ ] **Step 6: Run lint for changed surfaces**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m ruff check `
  freqtrade/research `
  freqtrade/rpc/api_server/api_research.py `
  tests/research `
  tests/rpc/test_api_research.py
```

Expected: PASS.

- [ ] **Step 7: Run optional live provider smoke for `688017.SH`**

Run only after unit/API tests pass and only when live network access is acceptable:

```powershell
cd G:\AI_Trading\freqtrade-cn
.\freqtrade\.venv\Scripts\python tools\download_a_share_research_data.py `
  --config ft_userdata\user_data\config.research.example.json `
  --bot-id a-share-local `
  --instruments 688017.SH `
  --timeframes 1m 5m 15m 30m 60m 1d `
  --adjustment raw
```

Expected output includes `ok` rows for these files:

```text
688017.SH-1m.csv
688017.SH-5m.csv
688017.SH-15m.csv
688017.SH-30m.csv
688017.SH-60m.csv
688017.SH-1d.csv
```

Expected local artifacts:

```text
G:\AI_Trading\freqtrade-cn\ft_userdata\user_data\research_data\a_share\688017.SH-1m.csv
G:\AI_Trading\freqtrade-cn\ft_userdata\user_data\research_data\a_share\688017.SH-5m.csv
G:\AI_Trading\freqtrade-cn\ft_userdata\user_data\research_data\a_share\688017.SH-15m.csv
G:\AI_Trading\freqtrade-cn\ft_userdata\user_data\research_data\a_share\688017.SH-30m.csv
G:\AI_Trading\freqtrade-cn\ft_userdata\user_data\research_data\a_share\688017.SH-60m.csv
G:\AI_Trading\freqtrade-cn\ft_userdata\user_data\research_data\a_share\688017.SH-1d.csv
```

- [ ] **Step 8: Browser verification**

Open the active Research page, such as:

```text
http://127.0.0.1:8082/research
```

Verify:

- research bot is `a-share-local` or the active A-share research bot;
- instrument `688017.SH` appears;
- timeframe selector includes collected minute timeframes;
- chart renders `1m`, `5m`, `15m`, `30m`, `60m`, and `1d`;
- ordinary `sma_cross` backtest runs on a minute timeframe;
- feature-aware backtest on minute timeframe returns unsupported behavior.

- [ ] **Step 9: Commit checkpoint**

Run only if the user wants commits:

```powershell
cd G:\AI_Trading\freqtrade-cn
git add tools/download_a_share_research_data.py docs/a-share-research-data.md freqtrade/tests/research/test_a_share_phase1_smoke.py
git commit -m "docs: describe a-share multi-timeframe research data"
```

---

## Full Verification

Run all focused backend tests:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest `
  tests/research/test_a_share_timeframes.py `
  tests/research/test_a_share_sessions.py `
  tests/research/test_data_source.py `
  tests/research/test_a_share_ohlcv_collector.py `
  tests/research/test_akshare_ashare_data_source.py `
  tests/research/test_a_share_phase1_smoke.py `
  tests/research/test_backtesting.py `
  tests/rpc/test_api_research.py `
  -q
```

Run lint:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m ruff check `
  freqtrade/research `
  freqtrade/rpc/api_server/api_research.py `
  tests/research `
  tests/rpc/test_api_research.py
```

Run script help:

```powershell
cd G:\AI_Trading\freqtrade-cn
.\freqtrade\.venv\Scripts\python tools\download_a_share_research_data.py --help
```

Run manual live smoke for `688017.SH` only after mocked tests pass:

```powershell
cd G:\AI_Trading\freqtrade-cn
.\freqtrade\.venv\Scripts\python tools\download_a_share_research_data.py `
  --config ft_userdata\user_data\config.research.example.json `
  --bot-id a-share-local `
  --instruments 688017.SH `
  --timeframes 1m 5m 15m 30m 60m 1d `
  --adjustment raw
```

## Execution Order

1. Task 1 first because every other task needs one timeframe registry and one session policy.
2. Task 2 second because chart/backtest reads must accept local minute files before provider work matters.
3. Task 3 third because collector normalization owns timestamp semantics and manifest metadata.
4. Task 4 fourth because the real `akshare` minute adapter should plug into the tested collector boundary.
5. Task 5 fifth because API/backtest guards depend on minute read support.
6. Task 6 last because docs and live smoke should reflect the final behavior.

## Out Of Scope For This Plan

- A-share live trading, dry-run trading, broker connectivity, wallet state, order state, force entry, or force exit.
- ccxt `Exchange` integration.
- Main Freqtrade crypto/futures downloader changes.
- Replacing the research backtest engine.
- `qfq` or `hfq` chart/backtest support.
- Full historical minute coverage.
- `mootdx`, Tencent quote, Eastmoney side data, order book, tick data, news, announcements, research reports, and AI retrieval.
- Minute side-data alignment.
- Portfolio-level A-share backtesting.
- Historical universes, delisting metadata, and full corporate-action adjustment.
