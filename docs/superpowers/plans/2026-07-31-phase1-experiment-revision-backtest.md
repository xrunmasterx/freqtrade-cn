# Phase 1 Experiment Revision Backtest

**Status:** Implementation complete; automated verification and independent Gate Review
passed; exact-SHA acceptance receipt pending

**Date:** 2026-07-31

**Branch:** `xrunmasterx/phase1-experiment-revision-backtest`

**Committed components:** backend `73a7431f2e51abd472d30aad0a36d234aec8fd0b`,
frontend `3c0f0dbc6675ef5cf90c20b13641d69ca3a97a5f`, strategies
`dbd5b0b21cfbf5ee80588d37458ace2467b7f8a4`. The Root implementation identity is
recorded by the documentation-only acceptance receipt that follows the integration
commit.

**Depends on:** the accepted
[Phase 1 Baseline Capability Gate](2026-07-30-phase1-baseline-capability-gate.md)

## 1. Outcome

Add one bounded researcher journey to the existing 8083/FreqUI Backtest surface:

1. enter a stable Experiment ID beside the existing strategy and backtest parameters;
2. create a deterministic revision receipt and run the standard Freqtrade backtest;
3. retain the receipt in the standard result artifact and history contract;
4. show the Experiment ID, revision digest, and current evidence boundary in result and
   history views.

This slice improves provenance without creating a second backtest engine, an Experiment
dashboard, a scheduler, a RuntimeInstance, or a Paper workflow.

## 2. First-principles boundary

The repository does not yet have a content-addressed offline `DataSnapshot`, immutable
strategy artifact store, or platform-owned Experiment ledger. Therefore this plan does
not claim formal reproducibility.

The current `experiment_revision` response object is a deterministic **Backtest Revision
Receipt**. It binds:

- a caller-supplied stable Experiment ID;
- the standard Freqtrade strategy/cache fingerprint, which already includes effective
  strategy config, loaded parameter-file values, and strategy source bytes;
- the validated Backtest request and engine version;
- the selected timeframe/timerange/config context represented by those inputs.

It deliberately records `data_snapshot_id: null`. The UI must state that exact candle
content is not captured and that the result is not eligible for formal reproducibility
or Paper acceptance. Revision-bound runs bypass Freqtrade result caching until exact data
content can be verified.

## 3. User journey

On an API 2.51-or-newer webserver Bot:

- the existing Backtest form shows a required Experiment ID field;
- valid IDs contain 1-128 ASCII letters, digits, `.`, `_`, or `-`, and start with a letter
  or digit;
- the action reads **Create receipt and start backtest**;
- the request includes the trimmed `experiment_id` and `backtest_cache: none`;
- the existing Freqtrade Backtesting engine, polling, summary, trades, comparison, and
  visualization remain unchanged;
- the result receipt and history row show the Experiment ID and revision identity;
- legacy results remain loadable and are visibly marked legacy/unbound.

Older API versions retain their existing Backtest form and request shape.

## 4. API contract

`POST /api/v1/backtest` adds one optional field:

| Field | Meaning |
|---|---|
| `experiment_id` | Stable user-chosen research intent key; not a release or runtime ID |

When present, result metadata and `GET /api/v1/backtest/history` include:

| Receipt field | Meaning |
|---|---|
| `schema_version` | Receipt schema version, initially `1` |
| `revision_id` | `experiment-revision-` plus SHA-256 of the canonical receipt payload |
| `experiment_id` | Validated Experiment ID from the request |
| `engine` / `engine_version` | Standard Freqtrade engine and exact version string |
| `strategy` | Loaded strategy class name |
| `strategy_run_id` | Native deterministic Freqtrade strategy/cache fingerprint |
| `backtest_request` | JSON-safe validated request with cache forced to `none` |
| `data_snapshot_id` | `null` until exact candle content is content-addressed |
| `identity_scope` | `strategy_config_and_data_selection` |

The receipt is stored inside each strategy's normal backtest metadata before the normal
result ZIP/sidecar is written. The legacy request and result shapes remain valid when no
Experiment ID is supplied.

## 5. Acceptance criteria

### Backend

- A legacy request produces no synthesized revision receipt.
- A valid Experiment ID creates a deterministic receipt in the in-memory result and
  persisted history.
- Repeating identical semantic inputs yields the same revision ID.
- Changing a result-affecting request field yields a different revision ID.
- Invalid Experiment IDs fail request validation with HTTP 422.
- Revision-bound requests bypass result caching.
- API version 2.51 advertises the optional capability.

### Frontend

- API 2.51 requires a valid Experiment ID before the start action is enabled.
- The POST body includes the Experiment ID and `backtest_cache: none`.
- Result analysis visibly shows the full revision ID and the missing-DataSnapshot warning.
- History and in-memory result keys distinguish different revisions of the same strategy.
- Legacy results remain usable and visibly unbound.
- API versions below 2.51 keep the legacy journey.

### Verification

Run at minimum:

```powershell
# backend
& 'G:\AI_Trading\freqtrade-cn\freqtrade\.venv\Scripts\python.exe' -m pytest `
  tests/rpc/test_rpc_apiserver.py -k 'api_backtesting or api_backtest_history' `
  -q -p no:cacheprovider
& 'G:\AI_Trading\freqtrade-cn\freqtrade\.venv\Scripts\python.exe' -m ruff check `
  freqtrade/rpc freqtrade/data/btanalysis freqtrade/ft_types tests/rpc

# frontend
pnpm vitest run tests/unit/backtestRevision.spec.ts tests/unit/appI18n.spec.ts
pnpm typecheck
pnpm build
pnpm exec playwright test e2e/backtest.spec.ts --project=chromium
```

An independent Gate Review must check cache behavior, canonical identity, persistence,
legacy compatibility, visible evidence limits, and accidental expansion into Paper or
Runtime scope.

### Verification result

- Backend focused receipt/history selection: 3 passed, 107 deselected.
- Backend broader chart/backtest/history/analysis selection: 15 passed, 95 deselected;
  one existing Starlette TestClient deprecation warning.
- Backend Ruff check and focused Ruff format check: passed.
- Frontend focused Vitest: 2 files, 23 tests passed.
- Frontend typecheck and production build: passed. The build retained existing
  third-party `@vueuse/core` pure-annotation warnings.
- Changed-file frontend ESLint: zero errors; existing Prettier warnings outside this
  slice's changed hunks remain non-failing.
- Mocked Chromium Backtest journeys: 2 passed, including duplicate-receipt artifact
  load/unload and API 2.50 request compatibility. Existing incomplete background-job
  mock noise remained non-failing.
- Independent full re-review verified canonicalization, cache bypass, persistence,
  artifact-aware keys, legacy compatibility, evidence warnings, and scope. Its only
  remaining terminology finding was fixed, and narrow re-review task
  `task_efaeb5abc783` returned PASS with no findings.

No Docker service, public exchange read, Live environment, real order, or exchange write
was used for this bounded contract slice.

## 6. Non-goals

- no DataSnapshot implementation or claim of exact candle-byte replay;
- no StrategyExperiment CRUD/dashboard or PostgreSQL Experiment ledger;
- no BacktestRun scheduler, retry model, generic workflow framework, or second engine;
- no Lookahead/Recursive revision binding in this slice;
- no StrategyRelease, BotRelease, dynamic RuntimeInstance, Paper Observation, 8090, Phase
  2D/2E, Live trading, real orders, or exchange writes;
- no chart data-source or overlay behavior change.

## 7. Required next decision

After this slice is accepted, the next smallest correctness step is to content-address the
exact offline candle inputs as a `DataSnapshot` and fail closed on missing or changed
content. Only after DataSnapshot and trusted result/artifact binding exist may the product
call a backtest formally reproducible or use it for governed comparison. Dynamic Paper
Runtime work remains separately paused.
