# A-Share Phase 3A Side-Data Layer Design

## Status

Draft created on 2026-07-07.

This spec defines the first side-channel data layer for the research-only A-share stack. It builds
on the existing Phase 1 local OHLCV ingestion and Phase 2 market-correctness work. The design keeps
OHLCV, market rules, feature data, event data, and document data as separate contracts.

## Background

The current A-share research path is intentionally narrow:

- `ResearchMarketDataSource` loads local normalized OHLCV.
- `LocalCsvResearchDataSource` accepts only:

```text
date,open,high,low,close,volume
```

- Research chart responses expose market and watch-indicator layers.
- Research backtests can use `ResearchMarketContext` when called directly, but the public
  `/research/backtest` API does not yet automatically load cached A-share calendar/status data.
- Phase 2 calendar and status files are documented as side-channel market metadata and must not be
  mixed into OHLCV CSV files.

This is the right foundation. A-share research cannot become credible by adding random columns to
the candle table. Funds flow, sectors, limit-up pools, dragon-tiger board data, announcements,
news, and reports each have different time semantics, update cadence, source reliability, and
future-data risk. They need their own storage, provenance, and chart/backtest alignment rules.

## Goal

Phase 3A adds the first local side-data layer for A-share research:

1. Load Phase 2 calendar/status cache files from the public Research backtest API path.
2. Add local stores for feature, event, and document side data.
3. Add a minimal set of A-share side-data collectors and provider adapters.
4. Normalize side data to versioned local files with manifests and provenance.
5. Expose available side datasets through Research APIs.
6. Allow `/research/chart_candles` to include optional feature/event/document chart layers.
7. Verify that chart/backtest behavior remains reproducible from local files without provider calls.

## Non-Goals

- Do not add live trading, dry-run trading, broker execution, account state, wallets, orders, or
  force-entry/force-exit behavior for A-shares.
- Do not route A-share side data through the existing crypto `Exchange` or ccxt model.
- Do not add side-data columns to the six-column OHLCV CSV contract.
- Do not enable provider-backed chart or backtest requests.
- Do not implement AI retrieval, embeddings, summarization, or RAG in Phase 3A.
- Do not parse full report PDFs or announcement PDFs in Phase 3A.
- Do not support minute-level A-share research features in Phase 3A.
- Do not build a production portfolio backtest engine in Phase 3A.
- Do not ingest every available `akshare` or `a-stock-data` endpoint.

## Assumptions

- Research APIs remain read-only over local normalized files.
- Provider calls only happen from explicit collector tools or collector modules.
- `a-stock-data` is a source-reference project, not a package that should be imported wholesale.
- `akshare` remains optional and is imported only by provider/collector code paths.
- The first supported A-share timeframe remains `1d`.
- The first supported OHLCV adjustment remains `raw`.
- Side datasets are stored under the configured user data directory, not inside the source tree.
- Phase 3A can add API schema fields in a backward-compatible way.

## Current Code Findings

### Existing OHLCV Boundary

`freqtrade/research/data_source.py` defines:

```text
ResearchMarketDataSource
LocalCsvResearchDataSource
RESEARCH_OHLCV_COLUMNS = ["date", "open", "high", "low", "close", "volume"]
SUPPORTED_A_SHARE_RESEARCH_TIMEFRAMES = {"1d"}
```

`LocalCsvResearchDataSource.load_ohlcv` validates the exact CSV columns. Phase 3A must preserve
that invariant.

### Existing Chart Boundary

`freqtrade/research/chart.py` builds:

- `market.ohlcv`
- `watch.indicators`

through `ChartResponseMeta.layers`.

`ChartLayerMeta` already supports:

```text
series: list[ChartSeriesMeta]
points: list[ChartLayerPoint]
warnings: list[str]
```

This is enough to add feature series and event/document points without changing the legacy
`columns/data` candle shape.

### Existing Point-Layer Precedent

The trading chart path already has a `decision_snapshot` layer that loads non-OHLCV evidence and
attaches it as `ChartLayerPoint` records. Phase 3A should generalize that pattern for research
side data instead of reusing the `decision_snapshot` source for unrelated A-share events.

### Existing Market-Correctness Gap

`ResearchMarketContext` supports cached A-share calendar/status rules, but public
`/research/backtest` currently calls `run_research_backtest` without a market context. Phase 3A
must close this gap before adding side-data visibility, because event/feature alignment depends on
the same calendar semantics.

## First Principles

### 1. OHLCV Is The Price Coordinate System, Not The Data Lake

Candles define the chart/backtest x-axis. They are not the container for all research evidence.

### 2. Side Data Has Independent Time Semantics

An announcement can have a report period, publish time, ingest time, and effective candle time. A
fund-flow row can have an observed trading date. A sector-membership row can be valid over a date
range. These must not be collapsed into a single ambiguous `date` field.

### 3. Backtests May Only See Publicly Available Past Information

Any feature or event used by a backtest must satisfy:

```text
available_time <= decision_time
```

For documents, `available_time` is normally `publish_time`. `ingest_time` is operational metadata,
not market availability.

### 4. Provider Data Is Not Research Data

Provider responses are raw observations from one source. Research data is normalized, validated,
versioned, and reproducible from local artifacts.

### 5. Collectors Can Fail Partially

Side-data collector jobs must write manifests with per-artifact success/error status. One failed
dataset must not corrupt already collected datasets.

## Recommended Approach

Use a side-data foundation with three separate store interfaces:

```text
ResearchFeatureStore
ResearchEventStore
ResearchDocumentStore
```

Each store reads local standardized files. Collectors fetch provider data, normalize it, write
local artifacts atomically, and write manifests. Chart/backtest APIs consume only the local stores.

This is preferred over two alternatives:

1. Adding optional columns to OHLCV CSV files. This is rejected because it breaks Phase 1/2
   reproducibility, schema validation, and separation of concerns.
2. Calling providers from chart/backtest requests. This is rejected because it makes research
   results non-reproducible and exposes API latency, provider schema drift, rate limits, and IP
   throttling to interactive requests.

## Scope

### Phase 2.5 Prerequisite Inside Phase 3A

Add a small API-level market-context loader:

- Resolve a research bot profile.
- Locate optional A-share metadata root.
- Load cached calendar/status stores if configured and present.
- Pass `ResearchMarketContext` into public `/research/backtest`.
- Preserve current behavior when the metadata root is missing or not configured.

This task must not make chart requests depend on market metadata.

### Phase 3A Side Datasets

Phase 3A should implement a small set of high-value, daily-compatible datasets:

1. Daily fund flow feature:
   - per instrument;
   - daily rows;
   - usable by future strategy/backtest feature contexts.

2. Sector/concept membership feature:
   - per instrument;
   - valid as of collection time or effective date;
   - useful for chart context and later portfolio filters.

3. Limit-up / limit-down / broken-board event data:
   - per trading date;
   - market-wide and per instrument;
   - useful as chart event points and market sentiment.

4. Announcement index document/event data:
   - per instrument;
   - title, publish time, URL, source, document id;
   - no full PDF parsing in Phase 3A.

At least three of the four datasets above must be implemented for Phase 3A acceptance. The
preferred first three are daily fund flow, sector/concept membership, and limit-up events. The
announcement index may be included if the implementation remains bounded.

## Data Layout

Side data lives next to existing A-share metadata:

```text
ft_userdata/user_data/research_data/a_share_meta/
  calendar/
    trade_dates.csv
  status/
    daily_status.csv
  features/
    fund_flow_daily/
      600519.SH.csv
    sector_membership/
      600519.SH.jsonl
  events/
    limit_pool/
      2026-07-07.jsonl
  documents/
    announcements/
      600519.SH.jsonl
  .manifests/
    {run_id}.json
```

The existing OHLCV files remain unchanged:

```text
ft_userdata/user_data/research_data/a_share/
  600519.SH-1d.csv
```

## Data Models

### Dataset Descriptor

Each readable side dataset is described by:

```text
dataset_id: fund_flow_daily
kind: feature | event | document
market: a_share
scope: instrument | market | sector
storage_format: csv | jsonl
timeframe: 1d | none
available: true | false
start: YYYY-MM-DD | null
stop: YYYY-MM-DD | null
provider: string | null
provider_version: string | null
manifest_run_id: string | null
warnings: list[str]
```

### Feature Row

Feature CSV files must include:

```text
date,instrument,dataset,field,value,source,publish_time,ingest_time
```

For dense numeric datasets, a wide format is allowed if the store normalizes it into the same
logical model:

```text
date,instrument,main_net_inflow,large_net_inflow,medium_net_inflow,small_net_inflow,source,publish_time,ingest_time
```

Rules:

- `date` is the observed trading date.
- `publish_time` is optional for same-day market features when the source does not provide it.
- `ingest_time` is required.
- Numeric values must be finite when present.

### Event Record

Event JSONL records must use:

```json
{
  "schema_version": 1,
  "event_id": "a-share-limit-pool:2026-07-07:600519.SH:limit_up",
  "dataset": "limit_pool",
  "market": "a_share",
  "instrument": "600519.SH",
  "event_type": "limit_up",
  "event_time": "2026-07-07T15:00:00+08:00",
  "publish_time": "2026-07-07T15:05:00+08:00",
  "ingest_time": "2026-07-07T16:00:00+08:00",
  "effective_candle_time": "2026-07-07T00:00:00+00:00",
  "title": "Limit up",
  "payload": {
    "reason": "sector theme",
    "consecutive_boards": 2,
    "sealed_amount": 123456789.0
  },
  "source": "eastmoney"
}
```

Rules:

- `event_id` must be stable and deterministic.
- `effective_candle_time` must align to the OHLCV candle timestamp.
- `publish_time` must be present when the event can affect backtest visibility.

### Document Record

Document JSONL records must use:

```json
{
  "schema_version": 1,
  "document_id": "cninfo:600519.SH:announcement:123456",
  "dataset": "announcements",
  "market": "a_share",
  "instrument": "600519.SH",
  "document_type": "announcement",
  "title": "Announcement title",
  "publish_time": "2026-07-07T19:30:00+08:00",
  "ingest_time": "2026-07-07T20:00:00+08:00",
  "effective_candle_time": "2026-07-08T00:00:00+00:00",
  "url": "https://example.invalid/announcement.pdf",
  "source": "cninfo",
  "payload": {
    "category": "annual_report"
  }
}
```

Rules:

- Phase 3A stores index metadata only.
- `text`, embeddings, summaries, and downloaded binary files are out of scope.
- `effective_candle_time` must be computed from `publish_time` and the A-share calendar.

### Manifest

Phase 3A manifests extend the Phase 1 collector pattern:

```json
{
  "schema_version": 1,
  "run_id": "20260707T120000000000Z-a-stock-data-a-share-side-data",
  "market": "a_share",
  "provider": "a-stock-data",
  "provider_version": "local",
  "created_at": "2026-07-07T12:00:00+00:00",
  "datasets": ["fund_flow_daily", "limit_pool"],
  "instruments": ["600519.SH"],
  "timerange": {"start": "20260701", "end": "20260707"},
  "files": [
    {
      "path": "features/fund_flow_daily/600519.SH.csv",
      "dataset": "fund_flow_daily",
      "kind": "feature",
      "rows": 5,
      "start": "2026-07-01",
      "stop": "2026-07-07",
      "status": "ok",
      "warnings": []
    }
  ],
  "warnings": []
}
```

Manifest paths must be relative to the side-data root and must never expose local absolute paths.

## Backend Components

### Research Side-Data Package

Add:

```text
freqtrade/research/side_data/
  __init__.py
  models.py
  store.py
  alignment.py
  provenance.py
  chart_layers.py
  collectors/
    a_share_side_data.py
  providers/
    a_stock_data_direct.py
    akshare_side_data.py
```

Responsibilities:

- `models.py`: Pydantic/dataclass models for dataset descriptors, features, events, documents.
- `store.py`: local file readers and validation.
- `alignment.py`: candle timestamp and availability-time alignment helpers.
- `provenance.py`: manifest lookup for side-data artifacts.
- `chart_layers.py`: convert feature/event/document records into `ChartLayerMeta`.
- `collectors/`: explicit offline collection flows.
- `providers/`: network/provider adapters used only by collectors.

### Store Interfaces

Use small interfaces instead of extending `ResearchMarketDataSource`:

```python
class ResearchFeatureStore(Protocol):
    def list_datasets(self) -> list[ResearchDatasetDescriptor]: ...
    def load_features(
        self,
        instrument_key: str,
        datasets: list[str],
        timerange: str | None,
    ) -> FeatureFrame: ...


class ResearchEventStore(Protocol):
    def list_datasets(self) -> list[ResearchDatasetDescriptor]: ...
    def load_events(
        self,
        instrument_key: str,
        datasets: list[str],
        timerange: str | None,
    ) -> list[ResearchEvent]: ...


class ResearchDocumentStore(Protocol):
    def list_datasets(self) -> list[ResearchDatasetDescriptor]: ...
    def load_documents(
        self,
        instrument_key: str,
        datasets: list[str],
        timerange: str | None,
    ) -> list[ResearchDocument]: ...
```

### Research Config Extension

Extend research bot config with optional side-data configuration:

```json
{
  "research_bots": [
    {
      "id": "a-share-local",
      "label": "A Share Local Research",
      "market": "a_share",
      "data_source": {
        "type": "local_csv",
        "root": "research_data/a_share"
      },
      "market_data": {
        "meta_root": "research_data/a_share_meta",
        "calendar": "calendar/trade_dates.csv",
        "daily_status": "status/daily_status.csv"
      },
      "side_data": {
        "root": "research_data/a_share_meta",
        "enabled_datasets": [
          "fund_flow_daily",
          "sector_membership",
          "limit_pool",
          "announcements"
        ]
      }
    }
  ]
}
```

Rules:

- Existing configs without `market_data` or `side_data` remain valid.
- Missing optional side-data files do not break chart/backtest unless a request explicitly asks for
  that dataset.
- Invalid side-data config returns a sanitized `400` response.

## API Design

### GET `/api/v1/research/datasets`

Parameters:

```text
bot_id: string
instrument: string | optional
kind: feature | event | document | optional
```

Response:

```json
{
  "datasets": [
    {
      "dataset_id": "fund_flow_daily",
      "kind": "feature",
      "market": "a_share",
      "scope": "instrument",
      "storage_format": "csv",
      "timeframe": "1d",
      "available": true,
      "start": "2026-07-01",
      "stop": "2026-07-07",
      "provider": "a-stock-data",
      "provider_version": "local",
      "manifest_run_id": "20260707T120000000000Z-a-stock-data-a-share-side-data",
      "warnings": []
    }
  ]
}
```

### POST `/api/v1/research/chart_candles`

Extend the existing request with an optional `side_layers` field:

```json
{
  "bot_id": "a-share-local",
  "instrument": "600519.SH",
  "timeframe": "1d",
  "limit": 500,
  "adjustment": "raw",
  "side_layers": {
    "features": ["fund_flow_daily"],
    "events": ["limit_pool"],
    "documents": ["announcements"]
  }
}
```

Response remains `ChartCandlesResponse`. New information is carried in `meta.layers`.

Feature layer example:

```json
{
  "id": "feature.fund_flow_daily",
  "source": "feature",
  "status": "partial",
  "label": "Fund Flow Daily",
  "timeframe": "1d",
  "alignment": "candle_open",
  "series": [
    {
      "column": "feature_fund_flow_daily_main_net_inflow",
      "label": "Main Net Inflow",
      "source": "feature",
      "kind": "bar",
      "panel": "fund_flow",
      "timeframe": "1d",
      "visible": true,
      "coverage": {
        "valid_points": 10,
        "total_points": 20,
        "reason": "partial coverage"
      },
      "provisional": false
    }
  ],
  "warnings": []
}
```

Event layer example:

```json
{
  "id": "event.limit_pool",
  "source": "event",
  "status": "ok",
  "label": "Limit Pool",
  "timeframe": "1d",
  "alignment": "effective_candle_time",
  "series": [],
  "points": [
    {
      "timestamp": 1783382400000,
      "label": "limit_up",
      "payload": {
        "event_type": "limit_up",
        "title": "Limit up",
        "publish_time": "2026-07-07T15:05:00+08:00",
        "source": "eastmoney",
        "reason": "sector theme"
      }
    }
  ],
  "warnings": []
}
```

### POST `/api/v1/research/backtest`

Phase 3A only changes the API path to load Phase 2 market context when configured. It does not add
strategy feature consumption yet.

Future Phase 3B may add:

```json
{
  "feature_context": {
    "datasets": ["fund_flow_daily"]
  }
}
```

That is out of scope for Phase 3A.

## Chart Metadata Changes

Extend backend and frontend chart layer sources:

```text
feature
event
document
```

Existing source values remain valid:

```text
market
watch
strategy
execution
decision_snapshot
recomputed
```

The legacy `columns/data` contract remains backward compatible. Feature series that need plotted
values may add columns to the returned chart dataframe, but those columns must use a reserved
prefix:

```text
feature_{dataset_id}_{field}
```

Event and document layers should normally use `points`, not dataframe columns.

## Frontend Changes

Phase 3A frontend work is intentionally small:

- Add `feature | event | document` to `ChartLayerSource`.
- Add optional side-layer selection to the Research page.
- Display dataset availability from `/research/datasets`.
- Render feature series through existing plot config behavior where practical.
- Show event/document point payloads in chart tooltip or a compact event list.

The first UI does not need a full document reader, PDF viewer, AI answer panel, or advanced filter
builder.

## Provider Strategy

### a-stock-data Reference

Use `G:/AI_Trading/data/a-stock-data` as a reference for direct public APIs and provider-priority
rules. Do not import the project wholesale.

Recommended first provider extractions:

- daily fund flow;
- sector/concept membership;
- limit-up/limit-down/broken-board pools;
- announcement index only if scope remains small.

Provider adapters must be rewritten or wrapped under `freqtrade/research/side_data/providers`.

### akshare Reference

Use `G:/AI_Trading/data/akshare` as an optional provider where it already has stable A-share
coverage, especially for:

- stock fund flow;
- announcements/notices;
- financial indicators;
- board/industry/concept data;
- limit-up pools.

`akshare` must remain optional and must not be imported by API route modules.

### Rate Limits

Eastmoney-like provider calls must use:

- serial throttling;
- bounded retry for transient network errors, `429`, and `5xx`;
- no retry for clear anti-bot `403`;
- per-file error summaries in manifests;
- no absolute local paths in public errors.

## Data Flow

### Collection Flow

```text
Operator command
  -> load research bot profile
  -> resolve side_data.root
  -> provider adapter fetches raw source data
  -> normalizer validates schema and timestamps
  -> atomic local artifact write
  -> manifest write
```

### Chart Flow

```text
FreqUI Research page
  -> POST /api/v1/research/chart_candles with side_layers
  -> load local OHLCV through ResearchMarketDataSource
  -> apply timerange and limit
  -> load requested side datasets from local side stores
  -> align features/events/documents to returned candles
  -> return ChartCandlesResponse with side layers in meta
```

### Backtest Flow

```text
FreqUI Research page
  -> POST /api/v1/research/backtest
  -> load OHLCV through ResearchMarketDataSource
  -> load optional Phase 2 calendar/status stores
  -> run_research_backtest(..., market_context=...)
```

Phase 3A does not feed side features into the strategy runtime.

## Error Handling

Research API errors remain sanitized:

| Case | Status |
| --- | --- |
| Unknown research bot | `404` |
| Invalid research config | `400` |
| Unknown side dataset | `400` |
| Missing requested side artifact | `404` or layer `unavailable`, depending on endpoint |
| Unsupported timeframe or adjustment | `501` |
| Chart input too large | `413` if a limit is introduced |
| Provider error during collection | collector exit `2`, manifest file status `error` |
| Unexpected route error | `502` with sanitized public message |

Route responses and logs must not leak:

- local absolute paths;
- user data root internals;
- provider secrets;
- raw provider stack traces.

## Future-Data Rules

Phase 3A must define and test these invariants:

1. A document or event with `publish_time` after a candle decision time is not available to that
   candle for backtest feature usage.
2. `ingest_time` never determines market availability.
3. Financial report `period_end` is not an availability timestamp.
4. If `effective_candle_time` cannot be computed because the calendar is missing, the record may be
   displayed as an event point only when the requested chart timestamp matches an explicit
   provider timestamp; otherwise the layer must be marked `unavailable` or `partial`.
5. Closed-day publications align to the next trading day for future feature consumption. Phase 3A
   may display them on chart points, but must preserve the computed effective candle timestamp.

## Testing Strategy

### Unit Tests

Add focused tests for:

- side-data config parsing;
- side-data root path traversal rejection;
- feature CSV validation;
- event JSONL validation;
- document JSONL validation;
- manifest lookup and provenance ordering;
- calendar-based effective candle alignment;
- future-data filtering helpers.

### API Tests

Extend research API tests to prove:

- existing `/research/bots`, `/research/instruments`, `/research/chart_candles`, and
  `/research/backtest` still work without side-data config;
- `/research/datasets` returns dataset descriptors;
- `/research/chart_candles` returns feature/event/document layers when requested;
- unknown datasets return sanitized errors;
- API routes do not call provider modules.

### Collector Tests

Use fake providers to prove:

- atomic artifact writes;
- manifest schema;
- partial failure behavior;
- no absolute paths in manifests;
- provider import happens only in collector/provider code paths.

### Frontend Tests

Add small TypeScript/Vitest coverage for:

- new `ChartLayerSource` values;
- research store dataset loading;
- tooltip or event-list rendering for event/document points;
- Research page behavior when side datasets are unavailable.

### Verification Commands

Backend:

```powershell
cd G:\AI_Trading\freqtrade-cn\freqtrade
.\.venv\Scripts\python -m pytest tests/research tests/markets tests/rpc/test_api_research.py -q
.\.venv\Scripts\python -m ruff check freqtrade/research freqtrade/markets freqtrade/rpc/api_server tests/research tests/markets tests/rpc/test_api_research.py
```

Frontend:

```powershell
cd G:\AI_Trading\freqtrade-cn\frequi
npm run test:unit -- --run
npm run typecheck
```

Collector help:

```powershell
cd G:\AI_Trading\freqtrade-cn
freqtrade\.venv\Scripts\python tools\download_a_share_side_data.py --help
```

## Acceptance Criteria

1. Existing six-column OHLCV files remain the only accepted OHLCV artifact shape.
2. Existing Research chart/backtest requests continue to work without side-data config.
3. Public `/research/backtest` uses Phase 2 market context when configured and available.
4. Side-data config is optional and backward compatible.
5. At least three Phase 3A side datasets can be collected into local standardized artifacts.
6. Each collector run writes a manifest with relative paths, provider metadata, per-file status,
   row counts, date coverage, and warnings.
7. `/research/datasets` lists available local side datasets.
8. `/research/chart_candles` can return requested feature/event/document layers in
   `meta.layers`.
9. Chart side layers align to returned candle timestamps and report coverage/warnings.
10. Event/document payloads are visible in the frontend tooltip or an event list.
11. Chart/backtest API requests do not import or call `akshare`, Eastmoney, Tencent, Sina,
    cninfo, mootdx, or any other live provider.
12. Missing side data does not change existing OHLCV chart/backtest behavior unless explicitly
    requested.
13. Future-data alignment helpers are covered by tests.
14. Public API errors and manifests do not leak absolute local paths.
15. The design leaves a clear path for Phase 3B strategy feature consumption and Phase 5 AI
    retrieval.

## Risks

- Side-data scope can grow too quickly. Phase 3A must stay limited to a small dataset set.
- Provider APIs may drift or throttle. This is contained by collector-only provider access and
  manifests.
- Timestamp semantics are easy to get wrong. Explicit `publish_time`, `ingest_time`, and
  `effective_candle_time` are mandatory for event/document records.
- Frontend chart support for point layers is currently specialized for `decision_snapshot`. Phase
  3A must avoid overbuilding while still making event/document payloads inspectable.
- Financial statements and report periods are high future-data risk. Full financial feature
  consumption should wait until Phase 3B or later.

## Recommended Implementation Order

1. Add config models for optional `market_data` and `side_data` roots.
2. Load Phase 2 market context in public `/research/backtest`.
3. Add side-data models, local stores, and manifest provenance helpers.
4. Add dataset listing API.
5. Add chart-layer source values and backend layer builders for feature/event/document.
6. Add optional `side_layers` to `/research/chart_candles`.
7. Add one collector command with fake-provider tests first.
8. Add real provider adapters for the selected Phase 3A datasets.
9. Add minimal frontend dataset selection and event/point inspection.
10. Document operator commands and run full backend/frontend verification.

## Open Decisions Before Implementation

1. Whether Phase 3A should include announcement index as the third shipped dataset, or ship only
   fund flow, sector membership, and limit-pool events first.
2. Whether side-data artifacts should use CSV for all feature datasets and JSONL for all
   event/document datasets, or allow Parquet later. Phase 3A should use CSV/JSONL only.
3. Whether chart feature values should be added to legacy `columns/data` with a reserved prefix, or
   exposed only through `meta.layers`. The recommended Phase 3A approach is to add reserved-prefix
   feature columns only for plotted numeric feature series.
