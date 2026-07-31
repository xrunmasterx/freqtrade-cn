# Phase 1 Retained DataSnapshot Replay Plan

**Status:** completed; exact-SHA accepted

**Branch:** `xrunmasterx/phase1-complete-development`

**Base acceptance:**
[Phase 1 Backtest Strategy Evidence Binding](../reports/2026-07-31-phase1-backtest-strategy-evidence-binding-acceptance.md)

**Boundary decision:**
[Result-local retained DataSnapshot replay](../decisions/2026-07-31-retained-data-snapshot-replay-boundary.md)

**Acceptance:**
[Phase 1 Retained DataSnapshot Replay](../reports/2026-07-31-phase1-retained-data-snapshot-replay-acceptance.md)

**Accepted implementation:** Root `02563c1d2d40e9dea62788ecfb8e5264d031fe1d`,
backend `9baff126f77d952811ebaba187bb7008c44f8dab`, frontend
`e2b5e36ce29d0a30b49266c9c4222345dff4b896`, and unchanged strategies
`dbd5b0b21cfbf5ee80588d37458ace2467b7f8a4`.

## 1. User outcome

Keep the existing authoritative 8083 Backtest journey. On API 2.54, a supported
standard Backtest retains its exact canonical DataSnapshot rows inside the normal result
ZIP. A verified replayable history row exposes one "use retained data" action. The next
Backtest uses only that retained standard market data while executing the current
installed strategy through the same Freqtrade engine and existing progress/result flow.

This lets a user or AI iteration loop compare a compatible strategy change after the
original history files have drifted or been deleted. Missing or incompatible data access
fails explicitly; no fresh candle fallback is allowed.

The outcome improves research reproducibility and causal comparison. It does not promise
the same result, bind the complete software/exchange context, qualify a strategy for
Paper, establish contract-trading safety, or imply future profit.

## 2. Assumptions and scope

- Freqtrade remains the sole Backtest engine and the active API journey runs one strategy
  at a time.
- Retention supports the same non-FreqAI standard inputs already accepted by
  DataSnapshot v1: primary/startup, optional detail, actual informative access, and
  Futures funding plus selected mark/index/premium rows.
- API 2.54 adds an explicit `retain_data_snapshot: true` opt-in and an optional
  `replay_data_snapshot: {filename, strategy}` selector. FreqUI exposes one retention
  checkbox only when the new capability is advertised; it is off by default because
  payload retention has material disk cost.
- Retention and replay imply server-enforced current strategy-evidence capture, fresh
  DataSnapshot capture, cache bypass, and an Experiment ID, even when a raw API client
  omits `capture_strategy_evidence`. They do not imply retaining another copy in the new
  result. FreqAI, public
  trades/orderflow, external producers, and direct historical trade data remain
  unsupported.
- The selected ZIP and metadata sidecar are local files below the configured
  `backtest_results` directory. Upload/import and arbitrary paths are out of scope.
- The current strategy source and resolved parameters may differ, but it must consume the
  complete retained route set and no additional route. The new result binds its current
  strategy evidence independently.
- Retained primary routes define the replay data universe. Extra entries in the current
  configured whitelist are not admitted and never trigger current-history reads; a
  retained pair removed from the current whitelist fails. Distinguishing a newly added
  configured pair from a pair that was already configured but had no source rows would
  require a separate pairlist/config identity and remains outside this data-only slice.
- Current exchange simulation metadata, fee/precision/options/leverage tiers, dependency
  environment, imported code, and arbitrary strategy I/O remain current and unbound.
  Replay can fail when those current dependencies are unavailable; it must never replace
  a missing retained OHLCV route with current data.

## 3. Replay bundle contract

The result ZIP adds fixed members:

```text
data_snapshot/manifest.json
data_snapshot/series/<64-lowercase-hex>.rows
```

The manifest contains replay schema 1, row encoding
`freqtrade-logical-ohlcv-rows-v1`, the exact unchanged DataSnapshot v1 manifest, ordered
admission routes, and a `replay-payload-...` identity. A route contains only its ordinal,
source role, pair, timeframe, candle type, and referenced `data-series-...` digest.

Each `.rows` member is the exact big-endian DataSnapshot v1 byte representation: UTC
millisecond int64 plus open/high/low/close/volume float64. Identical series referenced by
multiple routes have one member. No path, filename, mtime, credential, provider URL,
config, strategy source, or parameter value enters the replay manifest.

The optional receipt evidence contains only replay schema, snapshot ID, row encoding,
and replay-payload ID. Old schema-2 receipts without that evidence remain valid and
display as exact-data identity captured but payload not retained.

## 4. Capture, publication, and replay sequence

### Capture and retention

1. Validate Experiment ID, retention/capture combination, standard-input exclusions,
   row quota, and exported-result requirement; force current strategy-evidence capture
   for every retained result.
2. At every existing DataSnapshot capture boundary, retain the exact canonical row bytes
   and first-observation route while continuing to return the normalized frame used by
   Backtesting/DataProvider.
3. Seal the unchanged DataSnapshot and build the route-bound replay manifest after the
   strategy run.
4. Bind replay evidence into the new revision receipt.
5. Write the complete result ZIP to a unique same-directory temporary path, including
   canonical rows and replay manifest.
6. Close and fully load/verify the temporary replay bundle, then atomically publish the
   ZIP. Only afterwards publish the metadata sidecar and latest pointer.
7. Any retention, verification, or publication failure stores no bound result.

### Replay

1. Resolve the selected history stem and source strategy below `backtest_results`.
   Force current strategy-evidence capture for the new run.
2. Require a valid schema-2 receipt and replay evidence; legacy or fingerprint-only
   results fail explicitly.
3. Inspect exact ZIP member names and bounded sizes without extracting anything.
4. Parse a bounded canonical manifest; verify its replay identity, route inventory,
   binary member inventory and lengths, every series digest, reconstructed DataSnapshot
   manifest/ID, and receipt bindings.
5. Reconstruct normalized DataFrames in memory and pass a replay source into Backtesting
   and DataProvider.
6. Primary/detail/funding/mark loading consumes retained role data; informative access
   requires its exact retained route. Normal history loaders are unreachable in replay
   mode.
7. A fresh recorder must consume every retained route and reproduce the source
   DataSnapshot ID. Otherwise the job fails and no result is stored.
8. The successful new result records its new request, strategy evidence, Run ID, engine
   version, DataSnapshot, and replay lineage. It embeds another payload only when the
   user also selected retention.

## 5. Storage and failure policy

- Hard v1 quota: at most 1,000,000 unique rows and 48,000,000 canonical row bytes per
  retained result. Reject before publication.
- Exact names only; no `extract` or `extractall`, no path-derived member name, no duplicate
  replay member, and no unexpected member under `data_snapshot/`.
- Validate central-directory uncompressed sizes before reading and bound every read by
  receipt-derived expected length plus the hard quota.
- Reject corrupt ZIP/CRC, non-canonical or duplicate-key JSON, unknown schema/encoding,
  invalid role/ordinal/key, missing/orphan series, size mismatch, non-finite or
  non-canonical rows, digest mismatch, snapshot mismatch, or replay-evidence mismatch.
- Result deletion owns payload deletion because the payload is inside the existing ZIP.
- No automatic eviction, background GC, shared deduplication, upload, or migration of old
  artifacts.
- Existing historical ZIP credential exposure remains a separately authorized cleanup
  and rotation issue. Replay implementation must not copy, parse as authority, or rewrite
  those old configs.

## 6. User-visible states

### Retained and replayable

History shows the verified retained-data state and a single action to use that result’s
data for the next run. Result details and the Backtest form show the selected source
result and full snapshot/replay identity. Result details distinguish a retained row
payload from an identity-only DataSnapshot. Wording says the current strategy will run
against retained standard market data under the current execution context.

### Exact identity only

API-2.52/2.53 schema-2 results still show exact DataSnapshot identity but state that row
payload was not retained. They expose no replay action.

### Receipt only or legacy

Existing receipt-only and legacy/unbound states remain unchanged and are not inferred as
replayable from filename, timerange, Run ID, or current files.

### Replay failure

Missing, corrupt, over-limit, or incompatible retained data produces a stable visible
error. The UI must not retry as an ordinary Backtest or imply that current data was used.

## 7. Test-first acceptance

### Backend

- Retained canonical bytes round-trip to normalized frames and reproduce every existing
  series/snapshot ID; the original `finalize()` payload and identity remain unchanged.
- One logical series observed through multiple roles stores one member and preserves each
  ordered route.
- Missing, extra, duplicate, truncated, oversized, non-canonical, corrupt, or digest-
  mismatched members fail with stable errors before a result is published.
- ZIP traversal-like names, duplicate JSON keys, zip-bomb sizes, inventory/route/replay-
  ID/receipt mismatches, and quota exhaustion fail closed.
- Atomic publication fault tests prove manifest/member/verification failure leaves no
  final ZIP, sidecar, or latest pointer. Concurrent API result names cannot overwrite.
- Replay reconstructs primary, detail, informative, funding, and mark rows while normal
  OHLCV disk loaders are patched to fail if called.
- A missing/new route or an unconsumed old route fails; a compatible changed strategy
  keeps the DataSnapshot ID while changing its strategy evidence/revision as appropriate.
- Removing or mutating original history files after capture does not affect replayed rows
  or DataSnapshot identity.
- API 2.54 admission, history persistence, local path confinement, cache bypass, and
  failure-to-no-artifact behavior are covered. API 2.53/2.52/2.51 and legacy contracts
  remain compatible.
- Retention and replay requests that omit `capture_strategy_evidence` still record the
  server-forced flag and a valid current strategy-evidence binding in the new receipt.
- Receipt/replay manifest/sidecar contains no credential, local source path, archived
  config, raw strategy source, or resolved parameter payload.

### Frontend

- API 2.54 exposes an off-by-default retention control for supported standard runs;
  older API and FreqAI request shapes remain unchanged.
- Strict helpers expose replay only when receipt replay evidence is structurally valid
  and bound to the same DataSnapshot.
- Result details preserve the identity-only warning for schema-2 receipts without replay
  evidence and show the replay-payload ID plus current-execution-context boundary only
  for a strictly valid retained binding.
- The history action selects one local retained result for the next run; the form shows
  and clears it, sends only `{filename, strategy}`, and never sends rows or paths.
- Fingerprint-only, receipt-only, legacy, malformed, FreqAI, and pre-2.54 states expose no
  replay action.
- The mocked browser journey selects a retained result, starts replay, verifies the
  request and visible current-context warning, and preserves existing result/comparison
  behavior.

### Performance gate

Repeat the accepted 1,000,000-row harness. Capture plus ZIP retention and verified load
must remain below twice the accepted 0.440-second capture wall time for the in-process
payload stage, below twice the accepted 147.4 MiB peak attributable to snapshot handling,
and at or below 48,000,000 canonical row bytes plus bounded ZIP/manifest overhead. Row
members may use ZIP `STORED` when measured CPU cost makes compression miss this gate; the
off-by-default retention control is the corresponding disk-cost policy. If measured
storage or memory violates the gate, stop and rescope rather than add streaming/CAS
speculatively.

Uncommitted 2026-07-31 measurement at the exact one-million-row limit passed this gate.
The harness retained one unique OHLCV series through
`DataSnapshotRecorder.finalize_replay_payload()` and the atomic
`store_backtest_results()` path, whose temporary ZIP is strictly loaded and verified
before publication:

- accepted capture-only baseline: 0.440 s wall, 147.4 MiB peak;
- retained canonical capture: 0.512 s wall, 147.2 MiB peak;
- atomic persistence including strict verification load: 0.266 s wall, 238.6 MiB peak;
- end to end: 0.777 s, below the 0.880 s gate; both measured peaks are below
  294.8 MiB;
- canonical rows: exactly 48,000,000 bytes; final ZIP: 48,001,343 bytes.

The row members use ZIP `STORED`. A DEFLATE level-6 comparison required 1.334 s for the
row write alone, so compression was rejected in favor of the explicit off-by-default
disk-cost policy. This evidence does not claim power-loss durability or a separate
post-publication load phase; strict verified loading is included in the measured
persistence phase.

## 8. Verification commands

```powershell
# backend
& 'G:\AI_Trading\freqtrade-cn\freqtrade\.venv\Scripts\python.exe' -m pytest `
  tests/data/history/test_data_snapshot.py tests/data/test_dataprovider.py `
  tests/data/test_btanalysis.py tests/data/test_data_snapshot_replay_archive.py `
  tests/optimize/test_backtesting.py tests/optimize/test_backtest_replay_storage.py `
  tests/optimize/test_optimize_reports.py `
  tests/rpc/test_backtest_data_snapshot_schema.py tests/rpc/test_rpc_apiserver.py `
  -q -k "not test_api_freqaimodels" -p no:cacheprovider
& 'G:\AI_Trading\freqtrade-cn\freqtrade\.venv\Scripts\python.exe' -m ruff check `
  freqtrade/data/history/data_snapshot.py freqtrade/data/dataprovider.py `
  freqtrade/optimize/backtesting.py freqtrade/optimize/optimize_reports/bt_storage.py `
  freqtrade/rpc tests/data tests/optimize tests/rpc

# frontend
pnpm vitest run tests/unit/backtestRevision.spec.ts tests/unit/appI18n.spec.ts
pnpm typecheck
pnpm exec eslint e2e/backtest.spec.ts src/components/ftbot/BacktestHistoryLoad.vue `
  src/components/ftbot/BacktestResultAnalysis.vue src/components/ftbot/BacktestRun.vue `
  src/components/general/BaseCheckbox.vue src/locales/en.ts src/locales/zh-CN.ts `
  src/stores/btStore.ts src/stores/ftbot.ts src/types/backtest.ts src/types/features.ts `
  src/utils/backtestResultKey.ts tests/unit/appI18n.spec.ts `
  tests/unit/backtestRevision.spec.ts
pnpm build
pnpm exec playwright test e2e/backtest.spec.ts --project=chromium
pnpm exec playwright test e2e/backtest.spec.ts --project=msedge
```

The final uncommitted-tree run on 2026-07-31 produced:

- backend: 406 passed, 1 deselected, and 2 warnings in 46.53 s. The deselected test is
  the environment-limited optional `test_api_freqaimodels`; warnings are the existing
  Starlette TestClient deprecation and the intentionally constructed duplicate ZIP-member
  archive case;
- backend Ruff: all checks passed;
- frontend: 27 focused Vitest tests passed; `vue-tsc --build --noEmit` and the production
  build passed;
- changed-file ESLint: 0 errors and 6 pre-existing formatting warnings in two locale
  files and two unrelated regions of `src/stores/ftbot.ts`; no adjacent formatting was
  changed;
- mocked browsers: Chromium 6/6 and Edge 6/6 passed. The existing mocked background-job
  response still emits `recoverBgJobs` console noise and is not a replay-path failure.

Independent backend, frontend, and minimality/documentation Gate Reviews inspected
identity preservation, route completeness, zero OHLCV fallback, archive/member safety,
resource bounds, publication ordering, legacy compatibility, privacy, UI claims, and
accidental expansion into environment, exchange-context, StrategyRelease, Runtime,
Paper, or Live scope. All final reviews passed with no unresolved Blocker, High, or
Medium finding; the acceptance report records their task evidence.

## 9. Implementation checklist

- [x] Add RED canonical-row, route, verifier, storage, API, and UI tests.
- [x] Retain canonical bytes and build the replay-evidence contract without changing
  DataSnapshot v1 identity.
- [x] Implement bounded ZIP persistence, verification, and atomic publication.
- [x] Route Backtesting/DataProvider standard OHLCV exclusively through verified replay.
- [x] Add API 2.54 admission/history compatibility and the minimal FreqUI history action.
- [x] Run focused and broader regressions plus the 1,000,000-row performance gate.
- [x] Complete independent Gate Review, submodule/root commits, and exact-SHA acceptance.

## 10. Explicit non-goals

- no external CAS, snapshot database, reference counting, garbage collector, upload,
  import, generic catalog, CRUD page, arbitrary picker, or automatic deletion;
- no archived-strategy execution, StrategyRelease, transitive import closure, signing,
  encryption, attestation, or result-artifact authenticity redesign;
- no Environment Identity, effective-config identity, exchange-context snapshot,
  container/SBOM archive, deterministic-result claim, or fully offline Backtest promise;
- no FreqAI/model/prediction, public-trade/orderflow, arbitrary strategy-I/O, Lookahead,
  or Recursive payload replay in this slice;
- no Experiment dashboard, optimizer/ranker, AI daemon/journal, scheduler, BotRelease,
  RuntimeInstance, Supervisor, Paper Observation, 8090 cutover, Live trading, real orders,
  or exchange writes;
- no claim of stable profitability, contract-trading safety, or automatic promotion.
