# A-Share Phase 3B Minimal Feature-Aware Backtest Design

## Status

Draft created on 2026-07-07.

This spec defines Phase 3B-minimal for the research-only A-share stack. It builds on
Phase 3A side-data artifacts and adds the smallest safe path for using local feature
data inside research backtests.

The design intentionally keeps the existing research backtest engine. AkShare remains a
data-source/provider dependency for collector paths; AKQuant, Backtrader, and PyBroker
are treated as future engine-adapter candidates, not Phase 3B-minimal runtime
dependencies.

## Background

Phase 3A established the side-data foundation:

- OHLCV remains local canonical candle data.
- `LocalCsvResearchDataSource` still accepts only:

```text
date,open,high,low,close,volume
```

- `LocalResearchSideDataStore` can discover and load feature/event/document artifacts.
- `/research/datasets` lists local side-data descriptors.
- `/research/chart_candles.side_layers` can render feature series and event/document
  points.
- `tools/download_a_share_side_data.py` collects side-data artifacts and writes
  manifests.
- Research chart/backtest/datasets API paths do not call providers.

The remaining gap is backtesting. The current research backtest path accepts OHLCV and
optional market rules, but no feature context:

```python
def run_research_backtest(
    instrument: str,
    dataframe: DataFrame,
    config: ResearchBacktestConfig,
    market_context: ResearchMarketContext | None = None,
) -> ResearchBacktestResult:
    ...
```

Phase 3B-minimal closes only that gap: it lets a feature-aware strategy use local
`fund_flow_daily` feature data without changing the OHLCV contract or replacing the
backtest engine.

## AkShare And External Backtest Engine Findings

`G:\AI_Trading\data\akshare` was reviewed for reusable backtest components.

Findings:

- AkShare itself is primarily a data interface library.
- The AkShare repository recommends AKQuant in `README.md`.
- `docs/demo.md` demonstrates AKQuant, PyBroker, and Backtrader usage.
- The local `akshare/` package does not contain a reusable in-package backtest engine
  that can be directly embedded into `freqtrade-cn`.

Design implication:

- Use AkShare as a provider/data source through existing collector boundaries.
- Do not import AkShare or any live provider from research API/backtest requests.
- Do not replace the current research backtest with AKQuant, Backtrader, or PyBroker in
  Phase 3B-minimal.
- Leave external engine adapters for a later phase after the local feature-context
  contract is proven.

## Goal

Add a minimal feature-aware research backtest capability:

1. Introduce `ResearchFeatureContext` for local feature data.
2. Load local `fund_flow_daily` from `LocalResearchSideDataStore`.
3. Align feature rows to candle timestamps using A-share calendar semantics.
4. Add a feature-aware strategy type:

```text
sma_cross_feature_filter
```

5. Apply one numeric feature filter to SMA enter signals.
6. Preserve existing `sma_cross` behavior exactly when no feature-aware strategy is
   requested.
7. Return feature provenance in the backtest result.
8. Prove with tests that feature data cannot be used before it is publicly available.

## Non-Goals

Phase 3B-minimal does not:

- replace the current research backtest engine;
- import or depend on AKQuant, Backtrader, or PyBroker;
- add portfolio-level backtesting;
- add multi-symbol selection, rebalancing, benchmark, or index constituents;
- add a generic factor expression language;
- add event/document strategy consumption;
- add AI/RAG, embeddings, summarization, or document retrieval;
- parse full PDFs or news text;
- support minute-level A-share features;
- support provider-backed backtest requests;
- write feature columns into OHLCV CSV files;
- build a full FreqUI strategy-expression builder.

## First Principles

### 1. OHLCV Stays The Price Coordinate System

The candle dataframe remains the execution coordinate system. Features are separate
research evidence and must not be added to source OHLCV CSV files.

### 2. Feature Visibility Is A Market-Time Contract

Daily feature rows are not automatically visible on their `date`. For example, a full
day's fund-flow row published after close on 2026-07-07 cannot be used for a decision
that was made before it was published.

Feature rows must be mapped to an `effective_candle_time` before backtest use.

### 3. Feature-Aware Strategies Must Be Explicit

Existing `sma_cross` backtests must not change simply because side-data exists on disk.
Feature data is used only when the request asks for a feature-aware strategy.

### 4. Local Artifacts Are The Source Of Truth

Backtests must read local standardized artifacts only. Provider responses are raw input
to collectors, not backtest-time research data.

### 5. Missing Feature Data Must Not Be Silent

If a feature-aware strategy requests a feature dataset that is missing or unavailable,
the result must either fail fast or block entries according to explicit policy. It must
not silently degrade to ordinary SMA behavior.

## Recommended Approach

Use the existing research backtest engine and add one feature-context path:

```text
OHLCV CSV
  -> LocalCsvResearchDataSource
  -> OHLCV DataFrame

side-data artifacts
  -> LocalResearchSideDataStore
  -> ResearchFeatureContext

OHLCV DataFrame + ResearchMarketContext + ResearchFeatureContext
  -> SMA signal generation
  -> feature filter over enter_long signals
  -> existing execution loop and A-share market rules
  -> ResearchBacktestResult
```

This is preferred over introducing an external backtest engine now because it keeps the
behavior small, testable, and compatible with the current public Research API.

## Components

### ResearchFeatureContext

Create:

```text
freqtrade/freqtrade/research/feature_context.py
```

Proposed model:

```python
class ResearchFeatureContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    instrument: str
    datasets: list[str]
    frame: pd.DataFrame
    provenance: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
```

The frame contains OHLCV-aligned feature columns with Phase 3A reserved prefixes:

```text
feature_fund_flow_daily_main_net_inflow
feature_fund_flow_daily_large_net_inflow
feature_fund_flow_daily_medium_net_inflow
feature_fund_flow_daily_small_net_inflow
```

`ResearchFeatureContext` does not call providers and does not own strategy logic.

### Feature Context Loader

Create a helper:

```python
def create_research_feature_context(
    profile: ResearchBotProfile,
    instrument: str,
    datasets: list[str],
    candle_frame: pd.DataFrame,
    market_context: ResearchMarketContext | None,
) -> ResearchFeatureContext:
    ...
```

Responsibilities:

- require `profile.side_data` and `profile.side_data_root`;
- create `LocalResearchSideDataStore`;
- load only feature datasets;
- support only `fund_flow_daily` in Phase 3B-minimal;
- require `market_context.calendar` for effective-date alignment;
- map feature `publish_time` to `effective_candle_time`;
- merge or reindex features onto candle timestamps;
- collect provenance from side-data manifests.

Failure policy:

- missing `side_data` config for a feature-aware strategy: `ResearchConfigError`;
- missing feature artifact: `FileNotFoundError` or a converted API 404/400;
- missing A-share calendar: `ValueError` or `ResearchConfigError`;
- unsupported feature dataset: `ValueError`.

### Feature Filter Config

Add backend model:

```python
class ResearchFeatureFilterConfig(BaseModel):
    dataset: Literal["fund_flow_daily"]
    field: Literal[
        "main_net_inflow",
        "large_net_inflow",
        "medium_net_inflow",
        "small_net_inflow",
    ]
    operator: Literal[">", ">=", "<", "<=", "=="]
    value: float
    missing: Literal["block", "allow"] = "block"
```

`missing="block"` is the safe default. It prevents a feature-aware strategy from
turning into ordinary SMA when feature coverage is incomplete.

### Strategy Request Schema

Current schema supports only:

```text
sma_cross
```

Add:

```text
sma_cross_feature_filter
```

Recommended API schema:

```python
class ResearchSmaCrossFeatureFilterStrategyRequest(BaseModel):
    type: Literal["sma_cross_feature_filter"] = "sma_cross_feature_filter"
    fast: int = Field(default=20, ge=1)
    slow: int = Field(default=60, ge=2)
    feature_filter: ResearchFeatureFilterRequest
```

Use a discriminated union if it fits the local API schema style:

```python
ResearchBacktestStrategyRequest = Annotated[
    ResearchSmaCrossStrategyRequest | ResearchSmaCrossFeatureFilterStrategyRequest,
    Field(discriminator="type"),
]
```

If local style makes that too invasive, use one backward-compatible strategy model:

```python
type: Literal["sma_cross", "sma_cross_feature_filter"]
feature_filter: ResearchFeatureFilterRequest | None = None
```

Validation must enforce:

- `sma_cross` must not require `feature_filter`;
- `sma_cross_feature_filter` must provide `feature_filter`;
- SMA `fast < slow` remains required.

### Backtest Function Signature

Extend `run_research_backtest` conservatively:

```python
def run_research_backtest(
    instrument: str,
    dataframe: DataFrame,
    config: ResearchBacktestConfig,
    market_context: ResearchMarketContext | None = None,
    feature_context: ResearchFeatureContext | None = None,
    feature_filter: ResearchFeatureFilterConfig | None = None,
) -> ResearchBacktestResult:
    ...
```

Behavior:

- `feature_filter is None`: current behavior.
- `feature_filter is not None and feature_context is None`: fail fast.
- SMA signals are generated first.
- Feature filter applies only to `enter_long`.
- Existing execution loop, fees, whole-lot sizing, T+1, suspension, limit-up/limit-down,
  and market-context checks remain unchanged.

### Strategy Helper

Keep `add_sma_cross_signals` unchanged.

Add:

```python
def apply_feature_filter(
    dataframe: DataFrame,
    feature_context: ResearchFeatureContext,
    filter_config: ResearchFeatureFilterConfig,
) -> tuple[pd.DataFrame, list[str]]:
    ...
```

This helper:

- locates the reserved feature column;
- joins feature values by candle `date`;
- evaluates the configured operator;
- sets `enter_long = 0` when the filter fails;
- records summary warnings for blocked or missing-feature signals.

It must not modify `exit_long`. Exit behavior remains controlled by the base strategy
and market rules.

## Time Alignment Rules

Phase 3B-minimal must not compare raw `publish_time` directly against candle rows
stored at midnight. Daily candle timestamps are candle coordinates, not the exact
decision timestamp.

Use the Phase 3A alignment helper:

```python
effective_candle_time_for_publish_time(publish_time, calendar)
```

For `fund_flow_daily`:

- provider rows include `date`, `publish_time`, and `ingest_time`;
- `publish_time` is mapped to `effective_candle_time`;
- feature values become usable only on that `effective_candle_time`;
- a fund-flow row published after close maps to the next trading candle.

Example:

```text
publish_time = 2026-07-07T15:30:00+08:00
effective_candle_time = 2026-07-08 00:00:00+00:00
```

This means:

- the 2026-07-07 signal cannot use that feature;
- the 2026-07-08 signal can use it.

Feature-aware backtests require an A-share calendar. Without the calendar, there is no
correct way to map post-close publication to the next trading candle.

## API Flow

### Backtest Request

Example:

```json
{
  "bot_id": "a-share-local",
  "instrument": "600519.SH",
  "timeframe": "1d",
  "initial_cash": 100000,
  "strategy": {
    "type": "sma_cross_feature_filter",
    "fast": 5,
    "slow": 20,
    "feature_filter": {
      "dataset": "fund_flow_daily",
      "field": "main_net_inflow",
      "operator": ">",
      "value": 0,
      "missing": "block"
    }
  }
}
```

### API Handler Behavior

`/research/backtest` should:

1. validate the strategy request;
2. load OHLCV through `create_research_data_source(profile)`;
3. apply timerange and row limit exactly as today;
4. create `ResearchMarketContext`;
5. if strategy is feature-aware, create `ResearchFeatureContext`;
6. call `run_research_backtest(..., feature_context=..., feature_filter=...)`;
7. return the current result shape with enriched provenance.

### Response Provenance

Use the existing `data_provenance` field. Recommended nested shape:

```json
{
  "data_provenance": {
    "ohlcv": {
      "provider": "...",
      "manifest_run_id": "..."
    },
    "features": {
      "fund_flow_daily": {
        "provider": "akshare",
        "provider_version": "...",
        "manifest_run_id": "...",
        "start": "2026-07-01",
        "stop": "2026-07-07"
      }
    }
  }
}
```

The exact existing OHLCV provenance object may be preserved; Phase 3B only needs to
add a `features` section without breaking existing clients.

## Error Handling

Feature-aware backtest errors should be explicit:

- missing feature config: `400`;
- unknown dataset: `400`;
- incompatible dataset kind: `400`;
- missing local feature artifact: `404` or `400` with a precise message;
- missing calendar for feature alignment: `400`;
- provider unavailable: not applicable in API path because providers are not called.

Non-feature `sma_cross` requests must preserve current error behavior.

## Frontend Scope

FreqUI changes are optional for Phase 3B-minimal.

Recommended first version:

- no frontend change; validate through API and tests first.

Optional small UI after backend is stable:

- a fixed checkbox or preset:

```text
Use positive fund-flow filter
```

Do not build a generic strategy-expression UI in Phase 3B-minimal.

## External Engine Future Path

AKQuant, Backtrader, and PyBroker may be evaluated later behind an engine interface:

```python
class ResearchBacktestEngine(Protocol):
    def run(self, job: ResearchBacktestJob) -> ResearchBacktestResult:
        ...
```

Potential implementations:

```text
LocalResearchBacktestEngine
AkQuantResearchBacktestEngine
BacktraderResearchBacktestEngine
PyBrokerResearchBacktestEngine
```

This is not part of Phase 3B-minimal. It should be considered only after:

- feature-context semantics are proven;
- A-share market rule parity requirements are written;
- external engine result schemas are mapped to `ResearchBacktestResult`;
- dependency and packaging costs are accepted.

## Testing Strategy

### Backend Unit Tests

Add:

```text
tests/research/test_feature_context.py
```

Cover:

- loads `fund_flow_daily` from local side-data root;
- maps `publish_time` to `effective_candle_time` using calendar;
- rejects missing calendar;
- rejects non-feature datasets;
- returns provenance.

Modify:

```text
tests/research/test_backtesting.py
```

Cover:

- current `sma_cross` results remain unchanged;
- feature filter allows entries when condition passes;
- feature filter blocks entries when condition fails;
- `missing="block"` blocks entries with missing feature values;
- `missing="allow"` preserves entries when feature is missing;
- feature filter does not modify exit signals.

### No-Future-Leakage Test

Required test:

```text
feature publish_time = 2026-07-07T15:30:00+08:00
calendar next trading day = 2026-07-08
signal on 2026-07-07 must not see the feature
signal on 2026-07-08 may see the feature
```

This test is mandatory acceptance coverage.

### API Tests

Modify:

```text
tests/rpc/test_api_research.py
```

Cover:

- `sma_cross_feature_filter` request parses;
- API loads feature context from local side-data;
- API does not import provider modules;
- missing side-data config returns a controlled error for feature-aware strategy;
- ordinary `sma_cross` behavior remains unchanged.

### Verification Commands

Run:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research tests/rpc/test_api_research.py -q
.\.venv\Scripts\python -m ruff check freqtrade/research freqtrade/rpc/api_server tests/research tests/rpc/test_api_research.py
```

If frontend is changed:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
npm run test:unit -- --run
npm run typecheck
```

## Acceptance Criteria

Phase 3B-minimal is complete when:

1. Existing `sma_cross` backtests produce the same behavior as before.
2. `sma_cross_feature_filter` is accepted by `/research/backtest`.
3. `fund_flow_daily` feature data is loaded only from local artifacts.
4. Backtest API requests do not call or import live provider modules.
5. Feature-aware backtest requires a calendar for `publish_time` alignment.
6. Feature values are usable only from their `effective_candle_time`.
7. At least one no-future-leakage test proves post-close feature data cannot affect the
   same-day signal.
8. Missing requested feature data does not silently degrade to ordinary SMA.
9. Result provenance identifies feature dataset source/manifest when available.
10. Backend pytest and ruff checks pass.

## Risks

- `fund_flow_daily` provider publish-time semantics may vary by source. The collector
  should keep explicit `publish_time` and the feature loader should treat missing or
  malformed publish times as unsafe.
- Current research backtest uses a simplified single-instrument execution model. Feature
  support should not be mistaken for portfolio-level validation.
- External engines may offer richer metrics, but introducing them before the local
  feature contract is proven would expand scope and obscure correctness failures.

## Open Decisions

The implementation plan should make these choices explicit:

1. Whether missing local feature artifact returns `400` or `404`.
2. Whether the first UI exposure is deferred or implemented as a fixed preset.
3. Whether `data_provenance` nests existing OHLCV provenance under `ohlcv` immediately,
   or preserves current shape and adds only a `features` sibling.

Recommended defaults:

1. Missing requested feature artifact returns `404`.
2. Defer UI until backend behavior is verified.
3. Preserve current OHLCV provenance shape as much as possible and add a backward-compatible
   `features` section.
