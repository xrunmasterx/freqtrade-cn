# Phase 1 DataSnapshot Binding Acceptance Report

**Acceptance date:** 2026-07-31

**Status:** accepted at exact implementation SHAs; local commits only; no subsequent
implementation slice activated by this report

**Plan:**
[Phase 1 DataSnapshot Binding](../plans/2026-07-31-phase1-data-snapshot-binding.md)

**Identity decision:**
[Content-address normalized logical market data](../decisions/2026-07-31-logical-data-snapshot-identity.md)

## 1. Accepted outcome

The existing FreqUI standard Backtest journey now distinguishes three evidence states
without adding a second backtest engine or a new data-management product:

1. API 2.52-or-newer standard non-FreqAI Backtests automatically request exact logical
   market-data capture together with a validated Experiment ID and disabled result-cache
   reuse;
2. the existing Freqtrade engine runs from the same normalized in-memory OHLCV frames
   whose content is hashed;
3. the retained result binds a schema-2 Backtest Revision Receipt to a schema-1
   DataSnapshot manifest and matching non-null `data_snapshot_id`;
4. result, history, selector, and comparison surfaces distinguish data-bound,
   receipt-only, and legacy/unbound results;
5. API 2.51 stays receipt-only, API 2.50 stays legacy-compatible, and FreqAI on API 2.52
   explicitly remains receipt-only because its model and prediction inputs are not yet
   bound.

This slice answers whether supported standard Backtests used the same normalized offline
market-data content. It does not archive the source rows, prove that deleted data can be
replayed, bind the complete environment or strategy release, make a result artifact
tamper-resistant, qualify Paper execution, or predict future profit.

## 2. Exact implementation identity

The accepted implementation Root is the parent of this documentation-only acceptance
commit. This report does not claim that its own later Markdown changes were present in
the accepted implementation commit.

| Repository | Accepted implementation commit |
|---|---|
| Root | `a933df5b80a56f00989f17c59a5271fe17ed7039` |
| Backend `freqtrade/` | `05f3d5845f692a2e8097a07144728f50f38b5a91` |
| Frontend `frequi/` | `a71cf5b1134a86e43a55eec7b46ec8093fd27e6c` |
| Strategies | `dbd5b0b21cfbf5ee80588d37458ace2467b7f8a4` |

All commits are local on branch `xrunmasterx/phase1-data-snapshot-binding`. This
acceptance run did not push the branch or create a pull request.

## 3. Accepted evidence boundary

DataSnapshot schema 1 binds the logical content actually admitted to one supported
Backtest execution:

- primary Spot or Futures OHLCV, including startup/warmup rows;
- optional detail-timeframe OHLCV;
- historical informative OHLCV loaded through DataProvider;
- raw Futures funding and the exchange-selected mark, index, or premium-index series.

Each logical series binds venue, pair, timeframe, candle type, fixed logical columns,
row count, UTC-millisecond bounds, and a domain-separated SHA-256 digest. Canonical rows
use increasing unique UTC millisecond timestamps, float64 OHLCV values, normalized
positive zero, and no NaN or Infinity. Series discovery order, storage path, filename,
mtime, compression, and source data format do not enter the identity.

The enclosing Backtest receipt still binds the requested selection and accepted request.
The DataSnapshot manifest contains the series that Freqtrade actually admitted; it does
not silently invent an empty series for a selected pair that the existing loader omitted.
If that pair later has admitted rows, the manifest and receipt identities change.

An equal DataSnapshot ID means only that the supported normalized standard market-data
inputs are equal. It does not prove equal strategy code, dependency environment, custom
strategy-owned file/network input, output result, execution behavior, or profitability.
These meanings follow the shared [domain glossary](../../../CONTEXT.md).

## 4. Backend acceptance

The backend adds one explicit `capture_data_snapshot` protocol capability and advertises
API version 2.52. For a capture request, the accepted implementation:

- requires an Experiment ID and forces `backtest_cache: none`;
- constructs a fresh Backtesting/DataProvider instance and forces a fresh data load;
- normalizes and captures supported frames at their existing loader/access boundaries;
- gives the Backtesting engine and DataProvider cache the normalized frame returned by
  the recorder, avoiding a later disk re-read for hashing;
- seals the manifest after `backtest_one_strategy()` and before result statistics,
  receipt binding, and artifact persistence;
- fails rather than storing a partial schema-2 result when canonicalization, strategy
  execution, an unsupported historical trade access, or finalization fails;
- rejects FreqAI, public-trade/orderflow configuration, and external producers for
  schema-2 capture while preserving their existing non-capture paths;
- retains schema-1 receipt parsing and legacy history compatibility;
- validates manifest inventory totals and the outer/nested snapshot-ID binding.

The serialized receipt is built from the validated Backtest request rather than the
credential-bearing operational configuration. Tests include a secret sentinel and path
checks to verify that credentials and local source paths are absent from the complete
schema-2 revision payload.

Verified commands and results:

| Gate | Result |
|---|---:|
| DataSnapshot/DataProvider/Backtesting/schema/API pytest selection | 294 passed, 1 deselected |
| Ruff check over all touched backend source and tests | passed |
| Backend `git diff --check` | passed |
| Independent 1,000,000-row capture measurement | 0.440 s; about 48.3 MiB retained; about 147.4 MiB peak |

The deselected test is the pre-existing optional `test_api_freqaimodels`, whose resolver
module is absent from the shared local virtual environment; an independent baseline run
confirmed that this is not introduced by the DataSnapshot change. The existing Starlette
TestClient deprecation warning remained non-failing.

The peak-memory measurement is intentionally recorded separately from retained memory.
`np.unique()` and row-byte materialization create temporary allocations, so the peak is
materially higher than the post-return delta. Runtime and memory remain approximately
linear in selected row count and are accepted for the current explicit research
Backtest scope. Streaming, chunk storage, CAS, and parallel hashing are not justified by
this evidence; a later measured scale problem may optimize the two temporary allocations
without changing the identity contract.

## 5. Frontend acceptance

FreqUI uses separate capability gates for the existing API-2.51 revision receipt and
the API-2.52 DataSnapshot binding. The accepted UI:

- sends `capture_data_snapshot: true` automatically for API-2.52 standard non-FreqAI
  Backtests and does not expose a snapshot picker or capture toggle;
- keeps API 2.51 receipt-only and sends no new fields to API 2.50;
- omits capture when FreqAI is enabled and visibly states that the result will be
  receipt-only because FreqAI inputs are not bound;
- accepts a data-bound state only when receipt schema 2 contains a valid-format outer
  snapshot ID, a nested manifest, and the same nested ID;
- shows full receipt and snapshot IDs plus series/row totals in result details;
- makes history searchable by snapshot ID and labels data-bound, receipt-only, and
  legacy entries distinctly;
- keeps two persisted files with the same receipt/snapshot independently loadable and
  unloadable;
- reports comparison state as same, different, or unknown without attributing result
  differences only to strategy code.

Verified commands and results:

| Gate | Result |
|---|---:|
| Focused Vitest suites | 2 files, 24 tests passed |
| `pnpm typecheck` | passed |
| Changed-file ESLint | zero errors |
| `pnpm build` | passed |
| Mocked Chromium Backtest journeys | 4 passed |
| Frontend `git diff --check` | passed |

The Chromium journeys cover API-2.52 data-bound execution and retained display,
API-2.52 FreqAI receipt-only behavior, API-2.51 receipt-only request shape, and API-2.50
legacy request shape. The existing incomplete background-job mock emitted non-failing
`data is not iterable` console noise. Production build retained dependency-only
`@vueuse/core` pure-annotation warnings. Neither warning was expanded into unrelated
cleanup.

## 6. Independent review

Orchestration coordinated three read-only review roles; review workers modified no
files:

| Review | Decision and effect |
|---|---|
| Backend boundary audit `snapshot_backend_audit` | Found a direct historical `DataProvider.trades()` bypass and Ruff failures; both were fixed and covered before acceptance |
| Frontend path audit `snapshot_frontend_map` | Found the API-2.52/FreqAI UX conflict; the final UI preserves an explicit schema-1 receipt-only path |
| Final diff Gate `data_snapshot_final_gate` | PASS; P0=0, P1=0, one non-blocking P2 peak-memory observation |

The final reviewer checked canonical identity, supported-input coverage, TOCTOU/cache
behavior, schema compatibility, failure ordering, credential/path containment,
performance proportionality, UI claims, legacy/API compatibility, and scope control.
The only remaining P2 is the approximately 147.4 MiB temporary peak measured for one
million rows; it is documented above and does not block the current bounded scope.

The domain-modeling pass also separated DataSnapshot identity, payload retention,
Backtest Revision Receipt, StrategyRelease, environment identity, RuntimeInstance, and
Paper Observation so that later work cannot treat one proof as another.

## 7. Safety and compatibility

- No Docker service, public exchange read, credential display, Live environment, real
  order, exchange write, listener change, runtime migration, or destructive operational
  state action was used for this slice.
- No raw-data CAS, snapshot upload/CRUD/picker, replay selector, cleanup policy,
  Experiment dashboard, scheduler, new backtest engine, or 8090 surface was added.
- No chart source, indicator, signal, crosshair, tooltip, or execution-marker behavior
  changed; the standing [chart source contract](../../chart-data-source-rules.md) remains
  authoritative.
- The preconfigured 8081 dry-run compatibility service is not a formal BotRelease or
  dynamic RuntimeInstance and is outside this acceptance flow.
- FreqAI, direct/public trades, external producers, arbitrary strategy-owned I/O, and
  complete environment/release identity remain visibly outside schema-2 support.

## 8. Acceptance decision and next boundary

The bounded Phase 1 DataSnapshot Binding slice is accepted at the exact implementation
SHAs above. There is no unresolved P0 or P1 finding within its stated contract.

No next implementation becomes active automatically. The next decision must compare the
smallest user-relevant correctness gaps separately: immutable StrategyRelease identity,
environment identity, or retained DataSnapshot payload/replay. This acceptance does not
authorize dynamic Runtime, Paper Observation, Live trading, exchange writes, CAS, or a
broad Experiment platform. Those tracks remain paused until one bounded journey and its
measurable acceptance gate are explicitly selected.
