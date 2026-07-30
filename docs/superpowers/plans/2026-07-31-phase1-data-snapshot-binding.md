# Phase 1 DataSnapshot Binding Plan

**Status:** active

**Branch:** `xrunmasterx/phase1-data-snapshot-binding`

**Base acceptance:**
[Phase 1 Backtest Revision Receipt](../reports/2026-07-31-phase1-backtest-revision-receipt-acceptance.md)

**Identity decision:**
[Content-address normalized logical market data](../decisions/2026-07-31-logical-data-snapshot-identity.md)

## 1. User outcome

Keep the existing 8083 Backtest journey. On API 2.52 or newer, FreqUI automatically asks
the backend to bind the exact normalized standard offline market-data inputs when the
user starts a non-FreqAI Backtest with an Experiment ID. There is no snapshot picker,
CRUD page, new engine, scheduler, or Experiment dashboard.

The result, retained history, selector, and comparison view answer one practical
research question: did these Backtests use the same market data? This prevents a user or
an AI strategy-iteration loop from attributing a metric change only to strategy code
when the selected candle content also changed.

This is an integrity/equality gate, not a profitability claim. It does not make a
Backtest a forecast, archive the source rows, prove a complete software environment,
make the result artifact tamper-resistant, or qualify a strategy for Paper execution.

## 2. Assumptions and scope

- Freqtrade remains the only Backtest engine.
- The active API journey runs one strategy at a time.
- Capture is an explicit protocol capability, `capture_data_snapshot: true`, sent
  automatically by FreqUI only to API 2.52+. It is not a user-configurable option and the
  browser never supplies a snapshot ID.
- Schema-1 receipt requests remain valid when capture is omitted. Requests without an
  Experiment ID retain the legacy Backtest contract.
- Snapshot capture supports primary Spot/Futures OHLCV, startup/warmup rows, optional
  detail timeframe, actual historical DataProvider informative accesses, and Futures
  funding plus the exchange-selected mark/index/premium input.
- FreqAI, `exchange.use_public_trades`, direct historical `DataProvider.trades()` access,
  and configured external data producers are rejected for schema-2 capture. FreqUI
  preserves existing FreqAI use by omitting capture and stating that the result is
  receipt-only; all unsupported paths can still use the existing schema-1 or legacy path.
- Arbitrary strategy-owned files/network calls are outside the observable standard-data
  boundary. The UI must not call the result fully reproducible.

## 3. DataSnapshot contract

Snapshot schema 1 contains:

| Field | Meaning |
|---|---|
| `schema_version` | DataSnapshot manifest schema, initially `1` |
| `canonicalization` | `freqtrade-logical-ohlcv-v1` |
| `hash_algorithm` | `sha256` |
| `series_count` / `row_count` | Derived inventory totals |
| `series` | Canonically sorted logical-series manifest |
| `snapshot_id` | `data-snapshot-` plus the manifest SHA-256 |

Each series contains venue, pair, timeframe, candle type, fixed logical columns,
selected row count and UTC millisecond bounds, plus a `data-series-...` digest. It never
contains a path, filename, mtime, provider URL, account identity, or credential.

Canonicalization operates on the frame returned by Freqtrade after its normal selected
window/startup trimming, UTC conversion, duplicate aggregation, ordering, and missing
candle fill. The capture step owns a normalized copy used by the engine: ordered
`date/open/high/low/close/volume`, timezone-aware millisecond timestamps, float64 numeric
values, positive zero, unique increasing dates, and finite values. Empty observed required input,
naive/sub-millisecond timestamps, duplicate final timestamps, missing required columns or
dtypes, and non-finite values fail capture rather than produce a partial schema-2 receipt.

Freqtrade's existing loader may omit a selected pair that has no rows while continuing
with other pairs. Capture preserves that behavior: the manifest contains every series
actually admitted to the engine, while the enclosing revision still binds the complete
requested pair selection. If data for an omitted pair later becomes available, its new
series changes both the snapshot and revision identities.

Exact repeated observations are deduplicated in the manifest. Manifest discovery order
does not affect `snapshot_id`; pair-processing order and other execution configuration
remain bound by the enclosing request/Freqtrade Run ID rather than being misclassified as
market-data content.

## 4. Capture and receipt sequence

1. Validate Experiment ID and capture capability; reject known unsupported data paths at
   request time and reject direct historical trade-data access again at the DataProvider
   boundary before any read.
2. Keep normal schema-1 behavior when capture is absent.
3. For capture, construct a fresh Backtesting/DataProvider instance and load fresh data.
4. Normalize, hash, and retain primary/detail/funding/mark frames at their current loader
   boundaries. Normalize/hash a historical informative frame on its first DataProvider
   cache population.
5. Run indicator calculation and the standard Backtest from those admitted frames.
6. Seal the manifest immediately after `backtest_one_strategy`; any unseen historical
   access after sealing is an error.
7. Create receipt schema 2 with the full manifest, matching non-null
   `data_snapshot_id`, and `identity_scope: strategy_config_and_data_content`.
8. Hash that payload into the revision ID, then use existing result/history persistence.
9. On capture/canonicalization failure, the background job fails and no schema-2 result
   artifact is stored. It never silently falls back to a null snapshot.

The existing result-cache bypass remains. Snapshot-aware cache reuse is a later concern.

## 5. User-visible states

### Data-bound receipt

- full Backtest receipt and DataSnapshot IDs;
- series and row totals;
- history and selector show short snapshot digests with full IDs in titles;
- warning says exact standard offline market-data identity is bound, while payload
  retention, environment/artifact identity, Paper acceptance, and profitability are not.

### Receipt only

Schema 1 remains loadable and states that exact data is not captured.

### Legacy / unbound

Results without a receipt remain loadable and visibly unbound.

The comparison view derives three states: same bound snapshot, different bound
snapshots, or unknown because at least one result lacks a schema-2 snapshot. Different or
unknown data visibly prevents a strategy-only causal interpretation.

## 6. Test-first acceptance

### Backend

- Equal logical frames with different indexes/dtypes/discovery order produce one ID.
- A selected timestamp, OHLCV value, venue, pair, timeframe, candle type, startup row,
  detail row, informative row, funding row, or mark row changes identity.
- Naive/sub-millisecond dates, duplicates, missing columns, non-finite values, and
  mutation of one observed input key fail closed.
- Paths, formats, mtimes, unrelated files, and unselected rows do not enter the manifest.
- Snapshot capture uses the normalized in-memory frame and performs no second disk read.
- DataProvider captures lazy informative cache population once.
- API 2.52 advertises the capability; capture requires Experiment ID, fresh load, and
  cache bypass.
- Receipt schema 2 is deterministic, persists to history, and binds the manifest; schema
  1 and no-receipt behavior remain compatible.
- FreqAI, public trades, direct historical trade access, and external producers reject
  capture without storing a bound result.
- Serialized receipt/manifest contains no local path or credential-bearing config.

### Frontend

- API 2.52 sends capture automatically for standard non-FreqAI runs; FreqAI stays on the
  explicitly labelled receipt-only path. API 2.51 sends the accepted receipt-only shape;
  API 2.50 sends neither Experiment ID nor capture/cache fields.
- Result/history/selector distinguish data-bound, receipt-only, and legacy states.
- Same/different/unknown comparison status is deterministic and tested.
- Duplicate artifacts sharing receipt/snapshot identity remain independent.
- Warnings explicitly separate data identity from payload retention, environment/release
  proof, Paper acceptance, and future profit.

### Verification commands

```powershell
# backend
& 'G:\AI_Trading\freqtrade-cn\freqtrade\.venv\Scripts\python.exe' -m pytest `
  tests/data/history/test_data_snapshot.py tests/data/test_dataprovider.py `
  tests/optimize/test_backtesting.py tests/rpc/test_backtest_data_snapshot_schema.py `
  tests/rpc/test_rpc_apiserver.py `
  -q -p no:cacheprovider
& 'G:\AI_Trading\freqtrade-cn\freqtrade\.venv\Scripts\python.exe' -m ruff check `
  freqtrade/data/history/data_snapshot.py freqtrade/data/dataprovider.py `
  freqtrade/optimize/backtesting.py freqtrade/rpc tests/data tests/optimize tests/rpc

# frontend
pnpm vitest run tests/unit/backtestRevision.spec.ts tests/unit/appI18n.spec.ts
pnpm typecheck
pnpm build
pnpm exec playwright test e2e/backtest.spec.ts --project=chromium
```

An independent final Gate Review must inspect canonical identity, complete supported
input capture, TOCTOU/cache behavior, schema compatibility, failure behavior, privacy,
performance proportionality, UI claims, and accidental expansion into data archival,
Experiment, Runtime, Paper, or Live scope.

## 7. Implementation checklist

- [x] Add focused failing canonicalization/capture/API tests.
- [x] Implement the manifest builder and per-run recorder.
- [x] Wire primary/detail/futures/informative capture into the exact existing paths.
- [x] Add schema-2 receipt binding and API 2.52 compatibility.
- [x] Add the three-state result/history/selector/comparison UI.
- [x] Run focused and broader regressions plus performance evidence.
- [ ] Complete independent Gate Review and exact-SHA acceptance report.

## 8. Explicit non-goals

- no raw-data CAS, dataset upload, snapshot CRUD, snapshot picker, cleanup policy, or
  rerun-from-old-snapshot flow;
- no trusted/signed result-artifact redesign or sidecar migration;
- no Environment Identity, StrategyRelease, BotRelease, RuntimeInstance, scheduler,
  Paper Observation, 8090 surface, Live trading, real orders, or exchange writes;
- no FreqAI model/prediction identity or public-trade/orderflow snapshot support;
- no Lookahead/Recursive binding in this slice;
- no change to chart sources, overlays, signals, crosshair, or tooltip behavior.
