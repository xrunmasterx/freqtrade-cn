# A-Share Phase 3B Minimal Feature-Aware Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the smallest safe A-share feature-aware research backtest path by letting `/research/backtest` run `sma_cross_feature_filter` against locally stored `fund_flow_daily` features.

**Architecture:** Keep OHLCV as the only execution coordinate system and keep the existing research backtest engine. Add `ResearchFeatureContext` as a separate local side-data input, align feature rows by `publish_time -> effective_candle_time`, filter only `enter_long` signals, and preserve current `sma_cross` behavior when the new feature-aware strategy is not requested.

**Tech Stack:** Python 3, Pydantic, pandas, FastAPI, pytest, ruff, existing `LocalResearchSideDataStore`, existing A-share calendar/status market-context code.

## Global Constraints

- Existing OHLCV CSV files must remain exactly `date,open,high,low,close,volume`.
- First supported A-share research timeframe remains `1d`.
- First supported A-share OHLCV adjustment remains `raw`.
- Research chart/backtest API requests must not call `akshare`, Eastmoney, Tencent, Sina, cninfo, mootdx, or any live provider.
- Provider calls may happen only from explicit collector tools or provider modules.
- `akshare` remains optional and must not be imported by route modules.
- Side datasets live under the configured `user_data_dir`; source-tree fixtures are test-only.
- Feature-aware backtests must read local standardized artifacts only.
- Feature values must be usable only from their `effective_candle_time`.
- `sma_cross` behavior must remain unchanged unless `sma_cross_feature_filter` is explicitly requested.
- `missing="block"` is the safe default for feature filters.
- Missing requested local feature artifacts return `404`.
- No FreqUI feature-expression builder is part of this phase.
- Current repository is a shared dirty worktree; do not commit during execution unless the user explicitly authorizes commits in that run.

---

## Assumptions And Decisions

- The first feature-aware strategy is exactly `sma_cross_feature_filter`.
- The only dataset supported by Phase 3B-minimal is `fund_flow_daily`.
- The first supported fields are `main_net_inflow`, `large_net_inflow`, `medium_net_inflow`, and `small_net_inflow`.
- Supported operators are `>`, `>=`, `<`, `<=`, and `==`.
- Missing feature values block entries by default; `missing="allow"` preserves the base SMA entry.
- Existing OHLCV provenance shape is preserved; a backward-compatible `features` section is added only when a feature context is used.
- Frontend work is deferred. Backend API, tests, and manual API/browser validation are sufficient for Phase 3B-minimal acceptance.

## File Structure

Backend files to create:

- `freqtrade/freqtrade/research/feature_context.py`  
  Owns `ResearchFeatureContext`, `ResearchFeatureFilterConfig`, local feature-context loading, feature artifact alignment, and feature provenance collection.

- `freqtrade/tests/research/test_feature_context.py`  
  Tests feature artifact loading, A-share calendar alignment, provenance, missing calendar rejection, and incompatible dataset rejection.

Backend files to modify:

- `freqtrade/freqtrade/rpc/api_server/api_schemas.py`  
  Adds `ResearchFeatureFilterRequest`, `ResearchSmaCrossFeatureFilterStrategyRequest`, and a discriminated union for research backtest strategies.

- `freqtrade/freqtrade/research/strategies.py`  
  Adds `apply_feature_filter(...)` while leaving `add_sma_cross_signals(...)` unchanged.

- `freqtrade/freqtrade/research/backtesting.py`  
  Accepts optional `ResearchFeatureContext` and `ResearchFeatureFilterConfig`, applies the feature filter before the execution loop, and sets result strategy/provenance warnings.

- `freqtrade/freqtrade/rpc/api_server/api_research.py`  
  Loads market context once, creates feature context only for feature-aware strategy requests, maps missing feature artifacts to `404`, and returns feature provenance.

Backend tests to modify:

- `freqtrade/tests/research/test_backtesting.py`  
  Adds feature-filter behavior tests and protects existing SMA behavior.

- `freqtrade/tests/rpc/test_api_research.py`  
  Adds request schema tests, API success/failure tests, and provider-import isolation tests.

No frontend files are modified in this phase.

---

## Task 1: Research Backtest Strategy Schema

**Files:**
- Modify: `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
- Test: `freqtrade/tests/rpc/test_api_research.py`

**Interfaces:**
- Produces: `ResearchFeatureFilterRequest`
- Produces: `ResearchSmaCrossFeatureFilterStrategyRequest`
- Produces: `ResearchBacktestStrategyRequest`
- Consumes: `ResearchBacktestRequest.strategy`
- Later tasks rely on: `request.strategy.type`, `request.strategy.fast`, `request.strategy.slow`, and `request.strategy.feature_filter`

- [ ] **Step 1: Write schema tests for the feature-aware request**

Add these imports in `freqtrade/tests/rpc/test_api_research.py`:

```python
from pydantic import ValidationError
```

Extend the existing API schema import block:

```python
from freqtrade.rpc.api_server.api_schemas import (
    ChartLayerMeta,
    ChartSeriesCoverage,
    ChartSeriesMeta,
    ResearchBacktestRequest,
    ResearchChartCandlesRequest,
    ResearchSideLayerSelection,
)
```

Add tests near the existing research schema tests:

```python
def test_research_backtest_schema_accepts_feature_filter_strategy() -> None:
    request = ResearchBacktestRequest.model_validate(
        {
            "bot_id": "a-share-local",
            "instrument": "600519.SH",
            "timeframe": "1d",
            "strategy": {
                "type": "sma_cross_feature_filter",
                "fast": 5,
                "slow": 20,
                "feature_filter": {
                    "dataset": "fund_flow_daily",
                    "field": "main_net_inflow",
                    "operator": ">",
                    "value": 0,
                    "missing": "block",
                },
            },
        }
    )

    assert request.strategy.type == "sma_cross_feature_filter"
    assert request.strategy.fast == 5
    assert request.strategy.slow == 20
    assert request.strategy.feature_filter.dataset == "fund_flow_daily"
    assert request.strategy.feature_filter.field == "main_net_inflow"
    assert request.strategy.feature_filter.operator == ">"
    assert request.strategy.feature_filter.value == 0
    assert request.strategy.feature_filter.missing == "block"


def test_research_backtest_schema_rejects_feature_strategy_without_filter() -> None:
    with pytest.raises(ValidationError):
        ResearchBacktestRequest.model_validate(
            {
                "bot_id": "a-share-local",
                "instrument": "600519.SH",
                "timeframe": "1d",
                "strategy": {
                    "type": "sma_cross_feature_filter",
                    "fast": 5,
                    "slow": 20,
                },
            }
        )


def test_research_backtest_schema_keeps_sma_cross_default_strategy() -> None:
    request = ResearchBacktestRequest.model_validate(
        {
            "bot_id": "a-share-local",
            "instrument": "600519.SH",
            "timeframe": "1d",
        }
    )

    assert request.strategy.type == "sma_cross"
    assert request.strategy.fast == 20
    assert request.strategy.slow == 60
```

- [ ] **Step 2: Run the schema tests and confirm they fail**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/rpc/test_api_research.py::test_research_backtest_schema_accepts_feature_filter_strategy tests/rpc/test_api_research.py::test_research_backtest_schema_rejects_feature_strategy_without_filter tests/rpc/test_api_research.py::test_research_backtest_schema_keeps_sma_cross_default_strategy -q
```

Expected: the first two tests fail because `sma_cross_feature_filter` and `feature_filter` are not defined yet. The default `sma_cross` test may already pass.

- [ ] **Step 3: Add schema models**

In `freqtrade/freqtrade/rpc/api_server/api_schemas.py`, replace the current `ResearchSmaCrossStrategyRequest` / `ResearchBacktestRequest.strategy` section with:

```python
class ResearchFeatureFilterRequest(BaseModel):
    dataset: Literal["fund_flow_daily"]
    field: Literal[
        "main_net_inflow",
        "large_net_inflow",
        "medium_net_inflow",
        "small_net_inflow",
    ]
    operator: Literal[">", ">=", "<", "<=", "=="]
    value: float = Field(allow_inf_nan=False)
    missing: Literal["block", "allow"] = "block"


class ResearchSmaCrossStrategyRequest(BaseModel):
    type: Literal["sma_cross"] = "sma_cross"
    fast: int = Field(default=20, ge=1)
    slow: int = Field(default=60, ge=2)

    @model_validator(mode="after")
    def validate_period_order(self):
        if self.fast >= self.slow:
            raise ValueError("SMA fast period must be less than slow period.")
        return self


class ResearchSmaCrossFeatureFilterStrategyRequest(BaseModel):
    type: Literal["sma_cross_feature_filter"] = "sma_cross_feature_filter"
    fast: int = Field(default=20, ge=1)
    slow: int = Field(default=60, ge=2)
    feature_filter: ResearchFeatureFilterRequest

    @model_validator(mode="after")
    def validate_period_order(self):
        if self.fast >= self.slow:
            raise ValueError("SMA fast period must be less than slow period.")
        return self


ResearchBacktestStrategyRequest = Annotated[
    ResearchSmaCrossStrategyRequest | ResearchSmaCrossFeatureFilterStrategyRequest,
    Field(discriminator="type"),
]
```

Then modify `ResearchBacktestRequest`:

```python
class ResearchBacktestRequest(BaseModel):
    bot_id: str
    instrument: str
    timeframe: str
    timerange: str | None = None
    strategy: ResearchBacktestStrategyRequest = Field(
        default_factory=ResearchSmaCrossStrategyRequest
    )
    initial_cash: float = Field(default=100000, gt=0, allow_inf_nan=False)
```

- [ ] **Step 4: Verify Task 1**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/rpc/test_api_research.py::test_research_backtest_schema_accepts_feature_filter_strategy tests/rpc/test_api_research.py::test_research_backtest_schema_rejects_feature_strategy_without_filter tests/rpc/test_api_research.py::test_research_backtest_schema_keeps_sma_cross_default_strategy -q
.\.venv\Scripts\python -m ruff check freqtrade/rpc/api_server/api_schemas.py tests/rpc/test_api_research.py
```

Expected: all selected tests pass and ruff is clean.

---

## Task 2: ResearchFeatureContext Loader

**Files:**
- Create: `freqtrade/freqtrade/research/feature_context.py`
- Test: `freqtrade/tests/research/test_feature_context.py`

**Interfaces:**
- Produces: `ResearchFeatureContext(instrument: str, datasets: list[str], frame: pd.DataFrame, provenance: dict[str, Any], warnings: list[str])`
- Produces: `ResearchFeatureFilterConfig(dataset, field, operator, value, missing)`
- Produces: `create_research_feature_context(profile, instrument, datasets, candle_frame, market_context) -> ResearchFeatureContext`
- Consumes: `LocalResearchSideDataStore.load_feature_frame(...)`
- Consumes: `LocalResearchSideDataStore.list_datasets(..., kind="feature")`
- Consumes: `effective_candle_time_for_publish_time(...)`
- Later tasks rely on: `ResearchFeatureContext.frame` containing `date` and reserved feature columns aligned to OHLCV candle timestamps

- [ ] **Step 1: Write feature-context tests**

Create `freqtrade/tests/research/test_feature_context.py`:

```python
import json

import pandas as pd
import pytest

from freqtrade.research.exceptions import ResearchConfigError
from freqtrade.research.feature_context import create_research_feature_context
from freqtrade.research.market_context import create_research_market_context
from freqtrade.research.profiles import load_research_profiles


def _write_calendar(root) -> None:
    (root / "calendar").mkdir(parents=True)
    (root / "calendar" / "trade_dates.csv").write_text(
        "date,is_open,source\n"
        "2026-07-07,1,test\n"
        "2026-07-08,1,test\n"
        "2026-07-09,1,test\n",
        encoding="utf-8",
    )


def _write_feature(root, *, publish_time: str = "2026-07-07T15:30:00+08:00") -> None:
    (root / "features" / "fund_flow_daily").mkdir(parents=True)
    (root / "features" / "fund_flow_daily" / "600519.SH.csv").write_text(
        "date,instrument,main_net_inflow,large_net_inflow,medium_net_inflow,"
        "small_net_inflow,source,publish_time,ingest_time\n"
        f"2026-07-07,600519.SH,1000,800,100,100,eastmoney,{publish_time},"
        "2026-07-07T16:00:00+08:00\n",
        encoding="utf-8",
    )


def _write_feature_manifest(root) -> None:
    (root / ".manifests").mkdir(parents=True)
    (root / ".manifests" / "fund-flow.json").write_text(
        json.dumps(
            {
                "run_id": "phase3b-fixture",
                "provider": "akshare",
                "provider_version": "1.17.0",
                "created_at": "2026-07-07T20:30:00+08:00",
                "files": [
                    {
                        "path": "features/fund_flow_daily/600519.SH.csv",
                        "dataset": "fund_flow_daily",
                        "kind": "feature",
                        "rows": 1,
                        "start": "2026-07-07",
                        "stop": "2026-07-07",
                        "status": "ok",
                        "warnings": ["fixture warning"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _profile(tmp_path, *, side_data: bool = True, market_data: bool = True):
    meta_root = tmp_path / "research_data" / "a_share_meta"
    _write_calendar(meta_root)
    _write_feature(meta_root)
    _write_feature_manifest(meta_root)
    profile = {
        "id": "a-share-local",
        "label": "A Share Local",
        "market": "a_share",
        "data_source": {"type": "local_csv", "root": "research_data/a_share"},
    }
    if market_data:
        profile["market_data"] = {"meta_root": "research_data/a_share_meta"}
    if side_data:
        profile["side_data"] = {
            "root": "research_data/a_share_meta",
            "enabled_datasets": ["fund_flow_daily"],
        }
    config = {
        "user_data_dir": tmp_path,
        "research_bots": [profile],
    }
    return load_research_profiles(config)[0]


def _candle_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-07-07", "2026-07-08", "2026-07-09"],
                utc=True,
            ),
            "open": [10.0, 11.0, 12.0],
            "high": [11.0, 12.0, 13.0],
            "low": [9.0, 10.0, 11.0],
            "close": [10.5, 11.5, 12.5],
            "volume": [1000.0, 1100.0, 1200.0],
        }
    )


def test_create_research_feature_context_aligns_post_close_feature_to_next_candle(
    tmp_path,
) -> None:
    profile = _profile(tmp_path)
    market_context = create_research_market_context(profile)

    context = create_research_feature_context(
        profile,
        "600519.SH",
        ["fund_flow_daily"],
        _candle_frame(),
        market_context,
    )

    assert context.instrument == "600519.SH"
    assert context.datasets == ["fund_flow_daily"]
    assert list(context.frame["date"]) == list(_candle_frame()["date"])
    column = "feature_fund_flow_daily_main_net_inflow"
    assert pd.isna(context.frame.loc[0, column])
    assert context.frame.loc[1, column] == 1000.0
    assert pd.isna(context.frame.loc[2, column])


def test_create_research_feature_context_returns_feature_provenance(tmp_path) -> None:
    profile = _profile(tmp_path)
    market_context = create_research_market_context(profile)

    context = create_research_feature_context(
        profile,
        "600519.SH",
        ["fund_flow_daily"],
        _candle_frame(),
        market_context,
    )

    provenance = context.provenance["fund_flow_daily"]
    assert provenance["provider"] == "akshare"
    assert provenance["provider_version"] == "1.17.0"
    assert provenance["manifest_run_id"] == "phase3b-fixture"
    assert provenance["start"] == "2026-07-07"
    assert provenance["stop"] == "2026-07-07"
    assert provenance["warnings"] == ["fixture warning"]


def test_create_research_feature_context_requires_side_data_config(tmp_path) -> None:
    profile = _profile(tmp_path, side_data=False)
    market_context = create_research_market_context(profile)

    with pytest.raises(
        ResearchConfigError,
        match=r"Feature-aware research backtest requires side_data config\.",
    ):
        create_research_feature_context(
            profile,
            "600519.SH",
            ["fund_flow_daily"],
            _candle_frame(),
            market_context,
        )


def test_create_research_feature_context_requires_market_calendar(tmp_path) -> None:
    profile = _profile(tmp_path, market_data=False)

    with pytest.raises(
        ResearchConfigError,
        match=r"Feature-aware research backtest requires market_data calendar\.",
    ):
        create_research_feature_context(
            profile,
            "600519.SH",
            ["fund_flow_daily"],
            _candle_frame(),
            None,
        )


def test_create_research_feature_context_rejects_incompatible_dataset_kind(
    tmp_path,
) -> None:
    profile = _profile(tmp_path)
    market_context = create_research_market_context(profile)

    with pytest.raises(ValueError, match=r"Unknown research side dataset: announcements"):
        create_research_feature_context(
            profile,
            "600519.SH",
            ["announcements"],
            _candle_frame(),
            market_context,
        )
```

- [ ] **Step 2: Run feature-context tests and confirm they fail**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_feature_context.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `freqtrade.research.feature_context`.

- [ ] **Step 3: Create `feature_context.py`**

Create `freqtrade/freqtrade/research/feature_context.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import pandas as pd
from pandas import DataFrame
from pydantic import BaseModel, ConfigDict, Field

from freqtrade.research.exceptions import ResearchConfigError
from freqtrade.research.profiles import ResearchBotProfile
from freqtrade.research.side_data.alignment import effective_candle_time_for_publish_time
from freqtrade.research.side_data.store import LocalResearchSideDataStore

if TYPE_CHECKING:
    from freqtrade.research.backtesting import ResearchMarketContext


SUPPORTED_FEATURE_DATASETS = {"fund_flow_daily"}
FEATURE_FIELD_COLUMNS = {
    "main_net_inflow": "feature_fund_flow_daily_main_net_inflow",
    "large_net_inflow": "feature_fund_flow_daily_large_net_inflow",
    "medium_net_inflow": "feature_fund_flow_daily_medium_net_inflow",
    "small_net_inflow": "feature_fund_flow_daily_small_net_inflow",
}


class ResearchFeatureContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    instrument: str
    datasets: list[str]
    frame: DataFrame
    provenance: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ResearchFeatureFilterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: Literal["fund_flow_daily"]
    field: Literal[
        "main_net_inflow",
        "large_net_inflow",
        "medium_net_inflow",
        "small_net_inflow",
    ]
    operator: Literal[">", ">=", "<", "<=", "=="]
    value: float = Field(allow_inf_nan=False)
    missing: Literal["block", "allow"] = "block"


def create_research_feature_context(
    profile: ResearchBotProfile,
    instrument: str,
    datasets: list[str],
    candle_frame: DataFrame,
    market_context: ResearchMarketContext | None,
) -> ResearchFeatureContext:
    if profile.side_data is None or profile.side_data_root is None:
        raise ResearchConfigError("Feature-aware research backtest requires side_data config.")
    if market_context is None or market_context.calendar is None:
        raise ResearchConfigError("Feature-aware research backtest requires market_data calendar.")

    unsupported = [dataset for dataset in datasets if dataset not in SUPPORTED_FEATURE_DATASETS]
    if unsupported:
        raise ValueError(f"Unknown research side dataset: {unsupported[0]}")

    store = LocalResearchSideDataStore(
        profile.side_data_root,
        enabled_datasets=profile.side_data.enabled_datasets,
    )
    raw_features = store.load_feature_frame(instrument, datasets)
    aligned_frame = _align_features_to_candles(
        raw_features,
        candle_frame,
        market_context.calendar,
    )
    provenance = _feature_provenance(store, instrument, datasets)
    warnings = [
        warning
        for dataset_provenance in provenance.values()
        for warning in dataset_provenance.get("warnings", [])
    ]

    return ResearchFeatureContext(
        instrument=instrument,
        datasets=list(datasets),
        frame=aligned_frame,
        provenance=provenance,
        warnings=warnings,
    )


def _align_features_to_candles(
    raw_features: DataFrame,
    candle_frame: DataFrame,
    calendar: Any,
) -> DataFrame:
    candle_dates = pd.to_datetime(candle_frame["date"], utc=True)
    value_columns = [
        column for column in raw_features.columns if column.startswith("feature_")
    ]
    aligned = pd.DataFrame({"date": candle_dates})
    for column in value_columns:
        aligned[column] = pd.NA

    if raw_features.empty or not value_columns:
        return aligned

    features = raw_features.copy()
    features["effective_candle_time"] = pd.to_datetime(
        features["publish_time"].map(
            lambda value: effective_candle_time_for_publish_time(value, calendar)
        ),
        utc=True,
    )
    by_effective_time = (
        features[["effective_candle_time", *value_columns]]
        .sort_values("effective_candle_time")
        .drop_duplicates("effective_candle_time", keep="last")
        .set_index("effective_candle_time")
    )
    reindexed = by_effective_time.reindex(candle_dates)
    reindexed.index.name = "date"
    return reindexed.reset_index()


def _feature_provenance(
    store: LocalResearchSideDataStore,
    instrument: str,
    datasets: list[str],
) -> dict[str, Any]:
    descriptors = {
        descriptor.dataset_id: descriptor
        for descriptor in store.list_datasets(instrument_key=instrument, kind="feature")
    }
    return {
        dataset: descriptors[dataset].model_dump(mode="json")
        for dataset in datasets
        if dataset in descriptors
    }
```

- [ ] **Step 4: Verify Task 2**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_feature_context.py tests/research/test_side_data_store.py tests/research/test_side_data_alignment.py -q
.\.venv\Scripts\python -m ruff check freqtrade/research/feature_context.py tests/research/test_feature_context.py
```

Expected: all selected tests pass and ruff is clean.

---

## Task 3: Feature Filter In The Research Backtest Engine

**Files:**
- Modify: `freqtrade/freqtrade/research/strategies.py`
- Modify: `freqtrade/freqtrade/research/backtesting.py`
- Test: `freqtrade/tests/research/test_backtesting.py`

**Interfaces:**
- Consumes: `ResearchFeatureContext`
- Consumes: `ResearchFeatureFilterConfig`
- Produces: `apply_feature_filter(dataframe, feature_context, filter_config) -> tuple[DataFrame, list[str]]`
- Extends: `run_research_backtest(..., feature_context=None, feature_filter=None) -> ResearchBacktestResult`
- Later tasks rely on: feature-aware backtest failing fast when `feature_filter` is provided without `feature_context`

- [ ] **Step 1: Add backtest feature-filter tests**

Add these imports in `freqtrade/tests/research/test_backtesting.py`:

```python
from freqtrade.research.feature_context import (
    ResearchFeatureContext,
    ResearchFeatureFilterConfig,
)
```

Add helper functions:

```python
def _manual_signal_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-07-07", "2026-07-08", "2026-07-09"],
                utc=True,
            ),
            "open": [10.0, 11.0, 12.0],
            "high": [11.0, 12.0, 13.0],
            "low": [9.0, 10.0, 11.0],
            "close": [10.0, 11.0, 12.0],
            "volume": [1000.0, 1100.0, 1200.0],
            "enter_long": [1, 0, 0],
            "exit_long": [0, 1, 0],
        }
    )


def _feature_context(values: list[float | None]) -> ResearchFeatureContext:
    return ResearchFeatureContext(
        instrument="600519.SH",
        datasets=["fund_flow_daily"],
        frame=pd.DataFrame(
            {
                "date": pd.to_datetime(
                    ["2026-07-07", "2026-07-08", "2026-07-09"],
                    utc=True,
                ),
                "feature_fund_flow_daily_main_net_inflow": values,
            }
        ),
        provenance={"fund_flow_daily": {"provider": "test"}},
    )


def _positive_fund_flow_filter(
    *,
    missing: str = "block",
) -> ResearchFeatureFilterConfig:
    return ResearchFeatureFilterConfig(
        dataset="fund_flow_daily",
        field="main_net_inflow",
        operator=">",
        value=0,
        missing=missing,
    )
```

Add tests:

```python
def test_research_backtest_feature_filter_allows_entry_when_condition_passes() -> None:
    result = run_research_backtest(
        "600519.SH",
        _manual_signal_dataframe(),
        ResearchBacktestConfig(initial_cash=10000, fast=1, slow=2),
        feature_context=_feature_context([1000.0, None, None]),
        feature_filter=_positive_fund_flow_filter(),
    )

    assert result.strategy == "sma_cross_feature_filter"
    assert result.metrics["position_shares"] == 0
    assert result.metrics["trade_count"] == 1
    assert result.trades[0]["entry_date"] == "2026-07-08 00:00:00+00:00"
    assert result.trades[0]["exit_date"] == "2026-07-09 00:00:00+00:00"
    assert [signal["type"] for signal in result.signals] == [
        "enter_long",
        "exit_long",
    ]


def test_research_backtest_feature_filter_blocks_entry_when_condition_fails() -> None:
    result = run_research_backtest(
        "600519.SH",
        _manual_signal_dataframe(),
        ResearchBacktestConfig(initial_cash=10000, fast=1, slow=2),
        feature_context=_feature_context([-1.0, None, None]),
        feature_filter=_positive_fund_flow_filter(),
    )

    assert result.strategy == "sma_cross_feature_filter"
    assert result.trades == []
    assert result.metrics["position_shares"] == 0
    assert [signal["type"] for signal in result.signals] == ["exit_long"]
    assert any("Feature filter blocked 1 enter_long signal" in warning for warning in result.warnings)


def test_research_backtest_feature_filter_missing_block_blocks_entry() -> None:
    result = run_research_backtest(
        "600519.SH",
        _manual_signal_dataframe(),
        ResearchBacktestConfig(initial_cash=10000, fast=1, slow=2),
        feature_context=_feature_context([None, None, None]),
        feature_filter=_positive_fund_flow_filter(missing="block"),
    )

    assert result.trades == []
    assert any("missing feature value" in warning for warning in result.warnings)


def test_research_backtest_feature_filter_missing_allow_preserves_entry() -> None:
    result = run_research_backtest(
        "600519.SH",
        _manual_signal_dataframe(),
        ResearchBacktestConfig(initial_cash=10000, fast=1, slow=2),
        feature_context=_feature_context([None, None, None]),
        feature_filter=_positive_fund_flow_filter(missing="allow"),
    )

    assert result.metrics["trade_count"] == 1
    assert [signal["type"] for signal in result.signals] == [
        "enter_long",
        "exit_long",
    ]


def test_research_backtest_feature_filter_requires_feature_context() -> None:
    with pytest.raises(ValueError, match=r"Feature filter requires ResearchFeatureContext"):
        run_research_backtest(
            "600519.SH",
            _manual_signal_dataframe(),
            ResearchBacktestConfig(initial_cash=10000, fast=1, slow=2),
            feature_filter=_positive_fund_flow_filter(),
        )
```

- [ ] **Step 2: Run the new backtest tests and confirm they fail**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_backtesting.py::test_research_backtest_feature_filter_allows_entry_when_condition_passes tests/research/test_backtesting.py::test_research_backtest_feature_filter_blocks_entry_when_condition_fails tests/research/test_backtesting.py::test_research_backtest_feature_filter_missing_block_blocks_entry tests/research/test_backtesting.py::test_research_backtest_feature_filter_missing_allow_preserves_entry tests/research/test_backtesting.py::test_research_backtest_feature_filter_requires_feature_context -q
```

Expected: FAIL because `run_research_backtest` does not accept `feature_context` or `feature_filter`.

- [ ] **Step 3: Add `apply_feature_filter`**

Modify `freqtrade/freqtrade/research/strategies.py`:

```python
from collections.abc import Callable
from operator import eq, ge, gt, le, lt

import pandas as pd
from pandas import DataFrame, Series

from freqtrade.research.feature_context import (
    FEATURE_FIELD_COLUMNS,
    ResearchFeatureContext,
    ResearchFeatureFilterConfig,
)


_OPERATORS: dict[str, Callable[[Series, float], Series]] = {
    ">": gt,
    ">=": ge,
    "<": lt,
    "<=": le,
    "==": eq,
}
```

Keep the existing `add_sma_cross_signals(...)` function unchanged.

Add below it:

```python
def apply_feature_filter(
    dataframe: DataFrame,
    feature_context: ResearchFeatureContext,
    filter_config: ResearchFeatureFilterConfig,
) -> tuple[DataFrame, list[str]]:
    if filter_config.dataset != "fund_flow_daily":
        raise ValueError(f"Unsupported feature dataset: {filter_config.dataset}")

    feature_column = FEATURE_FIELD_COLUMNS[filter_config.field]
    if feature_column not in feature_context.frame.columns:
        raise ValueError(f"Missing research feature column: {feature_column}")

    result = dataframe.copy()
    result["date"] = pd.to_datetime(result["date"], utc=True)
    features = feature_context.frame[["date", feature_column]].copy()
    features["date"] = pd.to_datetime(features["date"], utc=True)

    result = result.merge(features, on="date", how="left")
    enter_mask = result["enter_long"].astype(int) == 1
    feature_values = pd.to_numeric(result[feature_column], errors="coerce")
    present_mask = feature_values.notna()
    pass_mask = _OPERATORS[filter_config.operator](feature_values, filter_config.value)
    if filter_config.missing == "allow":
        pass_mask = pass_mask | ~present_mask

    blocked_mask = enter_mask & ~pass_mask
    missing_blocked_mask = enter_mask & ~present_mask & (filter_config.missing == "block")
    blocked_count = int(blocked_mask.sum())
    missing_blocked_count = int(missing_blocked_mask.sum())

    result.loc[blocked_mask, "enter_long"] = 0

    warnings: list[str] = []
    if blocked_count:
        warnings.append(
            f"Feature filter blocked {blocked_count} enter_long signal(s): "
            f"{feature_column} {filter_config.operator} {filter_config.value}"
        )
    if missing_blocked_count:
        warnings.append(
            f"Feature filter blocked {missing_blocked_count} enter_long signal(s) "
            f"with missing feature value: {feature_column}"
        )

    return result, warnings
```

- [ ] **Step 4: Extend `run_research_backtest`**

Modify imports in `freqtrade/freqtrade/research/backtesting.py`:

```python
from freqtrade.research.feature_context import (
    ResearchFeatureContext,
    ResearchFeatureFilterConfig,
)
from freqtrade.research.strategies import add_sma_cross_signals, apply_feature_filter
```

Change the signature:

```python
def run_research_backtest(
    instrument: str,
    dataframe: DataFrame,
    config: ResearchBacktestConfig,
    market_context: ResearchMarketContext | None = None,
    feature_context: ResearchFeatureContext | None = None,
    feature_filter: ResearchFeatureFilterConfig | None = None,
) -> ResearchBacktestResult:
```

Replace the top of the function with:

```python
    _validate_backtest_prices(dataframe)
    dataframe = _with_strategy_signals(dataframe, config)
    warnings: list[str] = []
    strategy = "sma_cross"
    if feature_filter is not None:
        if feature_context is None:
            raise ValueError("Feature filter requires ResearchFeatureContext")
        dataframe, feature_warnings = apply_feature_filter(
            dataframe,
            feature_context,
            feature_filter,
        )
        warnings.extend(feature_context.warnings)
        warnings.extend(feature_warnings)
        strategy = "sma_cross_feature_filter"
    market_rules = AShareMarketRules()
    cash = float(config.initial_cash)
    shares = 0
    entry: dict[str, Any] | None = None
    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    rows = list(dataframe.itertuples(index=False))
    signals = _build_signal_records(rows)
```

Remove the later duplicate line:

```python
    warnings: list[str] = []
```

Set the result strategy in the return object:

```python
    return ResearchBacktestResult(
        instrument=instrument,
        strategy=strategy,
        metrics={
```

- [ ] **Step 5: Verify Task 3**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research/test_backtesting.py -q
.\.venv\Scripts\python -m ruff check freqtrade/research/backtesting.py freqtrade/research/strategies.py tests/research/test_backtesting.py
```

Expected: all backtesting tests pass and ruff is clean. Existing `sma_cross` tests must still pass without changing their expected outputs.

---

## Task 4: `/research/backtest` Feature-Aware API Integration

**Files:**
- Modify: `freqtrade/freqtrade/rpc/api_server/api_research.py`
- Test: `freqtrade/tests/rpc/test_api_research.py`

**Interfaces:**
- Consumes: `ResearchBacktestRequest.strategy`
- Consumes: `create_research_market_context(profile)`
- Consumes: `create_research_feature_context(...)`
- Consumes: `ResearchFeatureFilterConfig`
- Produces: `/api/v1/research/backtest` support for `sma_cross_feature_filter`
- Produces: `data_provenance.features` when feature context is used

- [ ] **Step 1: Add API test fixtures and helper**

Add this helper in `freqtrade/tests/rpc/test_api_research.py` near the existing test helper functions:

```python
def _write_feature_backtest_side_data(tmp_path) -> None:
    meta_root = tmp_path / "research_data" / "a_share_meta"
    (meta_root / "calendar").mkdir(parents=True)
    (meta_root / "features" / "fund_flow_daily").mkdir(parents=True)
    (meta_root / ".manifests").mkdir(parents=True)
    (meta_root / "calendar" / "trade_dates.csv").write_text(
        "date,is_open,source\n"
        "2026-07-06,1,test\n"
        "2026-07-07,1,test\n"
        "2026-07-08,1,test\n",
        encoding="utf-8",
    )
    (meta_root / "features" / "fund_flow_daily" / "600519.SH.csv").write_text(
        "date,instrument,main_net_inflow,large_net_inflow,medium_net_inflow,"
        "small_net_inflow,source,publish_time,ingest_time\n"
        "2026-07-06,600519.SH,1000,800,100,100,eastmoney,"
        "2026-07-06T14:30:00+08:00,2026-07-06T16:00:00+08:00\n",
        encoding="utf-8",
    )
    (meta_root / ".manifests" / "fund-flow.json").write_text(
        (
            '{"run_id":"phase3b-api-fixture","provider":"akshare",'
            '"provider_version":"1.17.0","created_at":"2026-07-07T20:30:00+08:00",'
            '"files":[{"path":"features/fund_flow_daily/600519.SH.csv",'
            '"dataset":"fund_flow_daily","kind":"feature","rows":1,'
            '"start":"2026-07-06","stop":"2026-07-06","status":"ok","warnings":[]}]}'
        ),
        encoding="utf-8",
    )
```

- [ ] **Step 2: Add API integration tests**

Add these tests in `freqtrade/tests/rpc/test_api_research.py` near existing backtest tests:

```python
def test_research_backtest_accepts_feature_filter_strategy(
    default_conf,
    tmp_path,
    mocker,
) -> None:
    _write_feature_backtest_side_data(tmp_path)
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
                "side_data": {
                    "root": "research_data/a_share_meta",
                    "enabled_datasets": ["fund_flow_daily"],
                },
            }
        ],
    ) as client:
        response = client_post(
            client,
            f"{BASE_URI}/research/backtest",
            data={
                "bot_id": "a-share-local",
                "instrument": "600519.SH",
                "timeframe": "1d",
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
                    },
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["strategy"] == "sma_cross_feature_filter"
    assert body["metrics"]["initial_cash"] == 100000
    assert body["data_provenance"]["source_type"] == "local_csv"
    assert body["data_provenance"]["features"]["fund_flow_daily"]["provider"] == "akshare"
    assert (
        body["data_provenance"]["features"]["fund_flow_daily"]["manifest_run_id"]
        == "phase3b-api-fixture"
    )


def test_research_backtest_feature_strategy_requires_side_data_config(
    default_conf,
    tmp_path,
    mocker,
) -> None:
    _write_feature_backtest_side_data(tmp_path)
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
        response = client_post(
            client,
            f"{BASE_URI}/research/backtest",
            data={
                "bot_id": "a-share-local",
                "instrument": "600519.SH",
                "timeframe": "1d",
                "strategy": {
                    "type": "sma_cross_feature_filter",
                    "fast": 1,
                    "slow": 2,
                    "feature_filter": {
                        "dataset": "fund_flow_daily",
                        "field": "main_net_inflow",
                        "operator": ">",
                        "value": 0,
                    },
                },
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Feature-aware research backtest requires side_data config."


def test_research_backtest_feature_strategy_missing_artifact_returns_404(
    default_conf,
    tmp_path,
    mocker,
) -> None:
    meta_root = tmp_path / "research_data" / "a_share_meta"
    (meta_root / "calendar").mkdir(parents=True)
    (meta_root / "features" / "fund_flow_daily").mkdir(parents=True)
    (meta_root / "calendar" / "trade_dates.csv").write_text(
        "date,is_open,source\n"
        "2026-07-06,1,test\n"
        "2026-07-07,1,test\n"
        "2026-07-08,1,test\n",
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
                "market_data": {"meta_root": "research_data/a_share_meta"},
                "side_data": {
                    "root": "research_data/a_share_meta",
                    "enabled_datasets": ["fund_flow_daily"],
                },
            }
        ],
    ) as client:
        response = client_post(
            client,
            f"{BASE_URI}/research/backtest",
            data={
                "bot_id": "a-share-local",
                "instrument": "600519.SH",
                "timeframe": "1d",
                "strategy": {
                    "type": "sma_cross_feature_filter",
                    "fast": 1,
                    "slow": 2,
                    "feature_filter": {
                        "dataset": "fund_flow_daily",
                        "field": "main_net_inflow",
                        "operator": ">",
                        "value": 0,
                    },
                },
            },
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Research side data not found for 600519.SH fund_flow_daily"


def test_research_backtest_feature_strategy_does_not_import_provider_modules(
    default_conf,
    tmp_path,
    mocker,
) -> None:
    import sys

    sys.modules.pop("akshare", None)
    sys.modules.pop("freqtrade.research.side_data.providers.akshare_side_data", None)
    _write_feature_backtest_side_data(tmp_path)
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
                "side_data": {
                    "root": "research_data/a_share_meta",
                    "enabled_datasets": ["fund_flow_daily"],
                },
            }
        ],
    ) as client:
        response = client_post(
            client,
            f"{BASE_URI}/research/backtest",
            data={
                "bot_id": "a-share-local",
                "instrument": "600519.SH",
                "timeframe": "1d",
                "strategy": {
                    "type": "sma_cross_feature_filter",
                    "fast": 1,
                    "slow": 2,
                    "feature_filter": {
                        "dataset": "fund_flow_daily",
                        "field": "main_net_inflow",
                        "operator": ">",
                        "value": 0,
                    },
                },
            },
        )

    assert response.status_code == 200
    assert "akshare" not in sys.modules
    assert "freqtrade.research.side_data.providers.akshare_side_data" not in sys.modules
```

- [ ] **Step 3: Run API tests and confirm they fail**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/rpc/test_api_research.py::test_research_backtest_accepts_feature_filter_strategy tests/rpc/test_api_research.py::test_research_backtest_feature_strategy_requires_side_data_config tests/rpc/test_api_research.py::test_research_backtest_feature_strategy_missing_artifact_returns_404 tests/rpc/test_api_research.py::test_research_backtest_feature_strategy_does_not_import_provider_modules -q
```

Expected: FAIL because `/research/backtest` does not create a feature context or pass feature filters to the backtest engine.

- [ ] **Step 4: Integrate feature context into `api_research.py`**

Modify imports in `freqtrade/freqtrade/rpc/api_server/api_research.py`:

```python
from freqtrade.research.feature_context import (
    ResearchFeatureContext,
    ResearchFeatureFilterConfig,
    create_research_feature_context,
)
```

Inside `research_backtest(...)`, replace the current market-context/backtest block:

```python
        backtest_config = ResearchBacktestConfig(
            initial_cash=request.initial_cash,
            fast=request.strategy.fast,
            slow=request.strategy.slow,
        )
        result = run_research_backtest(
            request.instrument,
            dataframe,
            backtest_config,
            market_context=create_research_market_context(profile),
        )
        result.data_provenance = provenance.model_dump()
        return result.model_dump(mode="json")
```

with:

```python
        backtest_config = ResearchBacktestConfig(
            initial_cash=request.initial_cash,
            fast=request.strategy.fast,
            slow=request.strategy.slow,
        )
        market_context = create_research_market_context(profile)
        feature_context: ResearchFeatureContext | None = None
        feature_filter: ResearchFeatureFilterConfig | None = None
        if request.strategy.type == "sma_cross_feature_filter":
            feature_filter = ResearchFeatureFilterConfig(
                **request.strategy.feature_filter.model_dump()
            )
            try:
                feature_context = create_research_feature_context(
                    profile,
                    request.instrument,
                    [feature_filter.dataset],
                    dataframe,
                    market_context,
                )
            except FileNotFoundError as e:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"Research side data not found for "
                        f"{request.instrument} {feature_filter.dataset}"
                    ),
                ) from e

        result = run_research_backtest(
            request.instrument,
            dataframe,
            backtest_config,
            market_context=market_context,
            feature_context=feature_context,
            feature_filter=feature_filter,
        )
        result.data_provenance = _merge_backtest_provenance(
            provenance.model_dump(),
            feature_context,
        )
        return result.model_dump(mode="json")
```

Add helper near `_create_side_data_store(...)`:

```python
def _merge_backtest_provenance(
    ohlcv_provenance: dict[str, Any],
    feature_context: ResearchFeatureContext | None,
) -> dict[str, Any]:
    if feature_context is None:
        return ohlcv_provenance
    return {
        **ohlcv_provenance,
        "features": feature_context.provenance,
    }
```

- [ ] **Step 5: Verify Task 4**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/rpc/test_api_research.py -q
.\.venv\Scripts\python -m ruff check freqtrade/rpc/api_server/api_research.py tests/rpc/test_api_research.py
```

Expected: all research API tests pass and ruff is clean.

---

## Task 5: Final Verification And Manual Research Backtest Check

**Files:**
- Verify: `freqtrade/freqtrade/research/feature_context.py`
- Verify: `freqtrade/freqtrade/research/strategies.py`
- Verify: `freqtrade/freqtrade/research/backtesting.py`
- Verify: `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
- Verify: `freqtrade/freqtrade/rpc/api_server/api_research.py`
- Verify: `freqtrade/tests/research/test_feature_context.py`
- Verify: `freqtrade/tests/research/test_backtesting.py`
- Verify: `freqtrade/tests/rpc/test_api_research.py`

**Interfaces:**
- Consumes: all previous task outputs.
- Produces: a verified Phase 3B-minimal backend ready for browser/API validation.

- [ ] **Step 1: Run full backend test subset**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research tests/markets tests/rpc/test_api_research.py -q
```

Expected: PASS. Existing Phase 0, Phase 1, Phase 2, and Phase 3A tests must keep passing.

- [ ] **Step 2: Run ruff**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m ruff check freqtrade/research freqtrade/markets freqtrade/rpc/api_server tests/research tests/markets tests/rpc/test_api_research.py
```

Expected: `All checks passed!`

- [ ] **Step 3: Confirm route modules do not import provider modules**

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
rg -n "akshare|eastmoney|cninfo|mootdx|requests" freqtrade/rpc/api_server freqtrade/research/backtesting.py freqtrade/research/feature_context.py
```

Expected: no provider import in route/backtest/feature-context runtime paths. A match in tests, collector modules, or provider modules is acceptable outside this command's path set.

- [ ] **Step 4: Start or verify the research backend**

If the backend is already running, verify it:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v1/ping"
```

Expected:

```text
status = pong
```

If it is not running, start it in a dedicated terminal:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m freqtrade webserver --config ..\ft_userdata\user_data\config.research.example.json
```

Expected: the backend listens on `http://127.0.0.1:8080` because `ft_userdata/user_data/config.research.example.json` sets `api_server.listen_port` to `8080`.

- [ ] **Step 5: Verify feature-aware backtest by API**

Use the running backend and send a feature-aware backtest request:

```powershell
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("freqtrader:change-me"))
$headers = @{ Authorization = "Basic $basic" }
$body = @{
  bot_id = "a-share-local"
  instrument = "600519.SH"
  timeframe = "1d"
  initial_cash = 100000
  strategy = @{
    type = "sma_cross_feature_filter"
    fast = 5
    slow = 20
    feature_filter = @{
      dataset = "fund_flow_daily"
      field = "main_net_inflow"
      operator = ">"
      value = 0
      missing = "block"
    }
  }
} | ConvertTo-Json -Depth 6

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8080/api/v1/research/backtest" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

Expected response fields:

```text
strategy = sma_cross_feature_filter
metrics.initial_cash = 100000
data_provenance.features.fund_flow_daily exists
warnings is present as a list
```

- [ ] **Step 6: Start or verify the research frontend**

If the current in-app browser is already on `http://127.0.0.1:8082/research`, reuse it. If the frontend is not running, start it in a dedicated terminal:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
npm run dev -- --host 127.0.0.1 --port 8082
```

Expected: Vite serves the Research page at `http://127.0.0.1:8082/research`.

- [ ] **Step 7: Verify ordinary SMA still works through the browser**

Open the existing in-app browser page:

```text
http://127.0.0.1:8082/research
```

Run the current ordinary research backtest controls without feature filter UI.

Expected: existing chart/backtest behavior is unchanged because no frontend feature toggle is part of Phase 3B-minimal.

---

## Execution Notes

- Run tasks in order. Task 1 gives the API a valid request shape. Task 2 creates aligned local feature context. Task 3 makes the backtest engine feature-aware. Task 4 wires the public API. Task 5 verifies the whole slice.
- Keep `add_sma_cross_signals(...)` behavior unchanged. The feature filter is a post-signal filter over `enter_long`.
- Keep `exit_long` unchanged. A feature filter must not suppress exits.
- Keep provider imports out of `freqtrade/rpc/api_server`, `freqtrade/research/backtesting.py`, and `freqtrade/research/feature_context.py`.
- Do not write feature columns into OHLCV source CSVs.
- Do not add frontend feature-filter controls in this phase.

## Self-Review Checklist

- Spec coverage:
  - `ResearchFeatureContext`: Task 2.
  - local `fund_flow_daily` loading: Task 2.
  - A-share calendar `publish_time -> effective_candle_time` alignment: Task 2.
  - explicit `sma_cross_feature_filter` strategy: Task 1 and Task 4.
  - one numeric feature filter: Task 1 and Task 3.
  - preserve `sma_cross`: Task 1, Task 3, and Task 5.
  - feature provenance: Task 2 and Task 4.
  - no-future-leakage through post-close alignment: Task 2.
  - no provider call/import in API path: Task 4 and Task 5.
- Chosen open decisions:
  - Missing requested feature artifact returns `404`.
  - First UI exposure is deferred.
  - Existing OHLCV provenance shape is preserved and `features` is added as a sibling field.
- Residual risk:
  - `fund_flow_daily` publish-time semantics depend on collector quality. The loader treats missing calendar as invalid and maps every row through the explicit A-share calendar path to reduce future-data risk.
