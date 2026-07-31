# Phase 1 Retained DataSnapshot Replay Acceptance Report

**Acceptance date:** 2026-07-31

**Status:** accepted at exact implementation SHAs; local commits only; no subsequent
implementation slice activated by this report

**Branch:** `xrunmasterx/phase1-complete-development`

**Worktree:**
`C:\Users\dezhengu\orca\workspaces\freqtrade-cn\phase1-complete-development`

**Plan:**
[Phase 1 Retained DataSnapshot Replay](../plans/2026-07-31-phase1-retained-data-snapshot-replay.md)

**Decision:**
[Result-local retained DataSnapshot replay](../decisions/2026-07-31-retained-data-snapshot-replay-boundary.md)

**Preceding evidence gate:**
[Phase 1 Backtest Strategy Evidence Binding](2026-07-31-phase1-backtest-strategy-evidence-binding-acceptance.md)

## 1. Exact implementation identity

| Repository | Exact accepted implementation SHA |
|---|---|
| Root | `02563c1d2d40e9dea62788ecfb8e5264d031fe1d` |
| `freqtrade/` backend | `9baff126f77d952811ebaba187bb7008c44f8dab` |
| `frequi/` frontend | `e2b5e36ce29d0a30b49266c9c4222345dff4b896` |
| `freqtrade-strategies/` | `dbd5b0b21cfbf5ee80588d37458ace2467b7f8a4` (unchanged) |

The Root implementation commit records the exact backend and frontend submodule
pointers. This acceptance document is a later documentation-only commit and does not
change the accepted implementation identity.

## 2. Accepted user outcome

The existing authoritative API-2.54 Freqtrade Backtest journey can now retain the exact
normalized standard market rows used by an opted-in result and use those retained rows
for one later Backtest. The user selects a verified replayable item from ordinary
Backtest history; the next run still uses the existing Freqtrade engine, progress flow,
result storage, comparison view, and currently installed strategy.

This closes the specific research problem caused by mutable or removed historical
candle files. A user can run a compatible current strategy against the retained market
rows without silently reading the current history store.

The accepted promise is deliberately narrower than complete reproducibility:

> same retained standard market data under the current execution context

The replay may produce a different result because current strategy code, imported
helpers, Freqtrade/software versions, exchange simulation inputs, fees, precision,
options, Futures leverage tiers, configuration, and arbitrary strategy I/O are not all
frozen by this slice. Equal replay evidence does not prove equal results, Paper
eligibility, contract-trading safety, or future profitability.

## 3. Accepted capture and replay boundary

### Capture and identity

Retention is explicit and off by default. For a supported standard Backtest, the server
forces fresh DataSnapshot capture, current strategy-evidence capture, cache bypass, and
an Experiment ID even when a raw API-2.54 client omits the optional strategy-evidence
flag.

The enclosing result ZIP stores one result-local replay bundle containing:

- the unchanged DataSnapshot v1 manifest;
- the existing canonical big-endian 48-byte logical OHLCV rows, stored once per unique
  data-series digest;
- an ordered route manifest for `primary`, `detail`, `informative`, `funding`, and
  `mark` observations; and
- a domain-separated `replay-payload-...` identity bound to the receipt.

Source roles remain outside the accepted DataSnapshot v1 identity. Existing
`data-series-...` and `data-snapshot-...` identifiers therefore remain unchanged, while
the separate replay identity detects changed route order or membership.

### Publication and admission

The backend writes the result to a collision-resistant sibling temporary ZIP, closes
it, loads and strictly verifies the complete replay bundle, then atomically publishes
the ZIP before publishing its metadata sidecar and latest-result pointer. Failure before
ZIP publication leaves no accepted replay artifact. Exact result deletion removes the
embedded payload through the existing result lifecycle and repairs the latest pointer
without prefix-collision deletion.

The browser sends only the local result filename/stem and strategy name. It never sends
filesystem paths or row payloads. Before a Backtest job starts, the server confines the
resolved artifact to the configured result directory and verifies the receipt, source
strategy, DataSnapshot/replay binding, canonical manifest, complete member inventory,
member sizes, row encoding, every series digest, route references, and resource limits.
Malformed metadata maps to a stable admission error rather than a background-job
failure.

### Replay-only data access

Primary, detail, informative, funding, and mark OHLCV access is replay-only after
admission. The normal disk history loaders and latest/exchange OHLCV paths are not
fallbacks. Missing, corrupt, newly requested, or unconsumed routes fail the run.

Retained primary routes define the data universe. Every retained pair must still be
allowed by the current whitelist, so removing a retained pair fails admission. Extra
pairs later added to the current whitelist are not admitted and are not read. The same
rule applies to Futures combination: funding/mark frames are combined only for retained
routes, not for newly added current pairs.

A fresh recorder observes the replayed routes and must reproduce the retained
DataSnapshot identity. The new result captures the current strategy evidence and its
effective request. Replaying a source does not automatically retain another payload in
the new result; retention remains an independent explicit choice.

## 4. Compatibility and user-interface behavior

The accepted compatibility matrix is:

| State | Retention or replay behavior |
|---|---|
| API 2.54 standard Backtest | capability-gated, explicit retention and verified replay |
| API 2.53, API 2.52, API 2.51, and pre-receipt servers | existing request behavior; no replay control |
| Schema-2 receipt without valid replay evidence | identity remains visible; explicitly not replayable |
| Legacy, fingerprint-only, receipt-only, malformed, or path-like evidence | no replay action |
| FreqAI/model, public trades/orderflow, direct historical trades, or external producers | rejected or excluded from replay |

FreqUI exposes one off-by-default retention checkbox and one history-row action for a
strictly verified local source. Replay selection is one-shot: a rejected POST keeps the
selection and shows a persistent accessible error; an accepted POST clears it. Dynamic
capability and FreqAI blockers are associated with the disabled action, and the visible
retention label targets the real checkbox control.

Result details deliberately distinguish two states:

- a schema-2 DataSnapshot identity whose row payload was not archived; and
- a valid retained replay payload, which shows the replay-payload identity and the
  current-execution-context warning.

Neither state claims identical results or profit. Existing result loading, comparison,
and older API behavior remain available.

## 5. Resource, archive, and performance policy

Replay schema 1 accepts at most 1,000,000 unique canonical rows and 48,000,000 canonical
row bytes per result. ZIP members are read by exact name without filesystem extraction.
Duplicate or traversal-like names, unexpected replay-prefix members, duplicate JSON
keys, non-canonical manifests, malformed or non-finite rows, digest/binding mismatch,
CRC failure, oversized members, missing/orphan members, and total resource-limit
violations fail closed.

The exact one-million-row harness recorded:

| Phase | Wall time | Peak memory |
|---|---:|---:|
| Accepted capture-only baseline | 0.440 s | 147.4 MiB |
| Retained canonical capture | 0.512 s | 147.2 MiB |
| Atomic persistence plus strict verified load | 0.266 s | 238.6 MiB |
| End to end | 0.777 s | phase peaks both below 294.8 MiB gate |

The canonical row payload was exactly 48,000,000 bytes and the final ZIP was
48,001,343 bytes. Row members use ZIP `STORED`. A DEFLATE level-6 comparison required
1.334 seconds for the row write alone and missed the accepted CPU gate, so this slice
chooses explicit off-by-default disk cost instead of adding compression, streaming, or
a shared content-addressed store prematurely.

This measurement includes strict load verification in the persistence phase. It does
not claim power-loss durability or prove a separate cold post-publication load profile.

## 6. Verification evidence

### Backend

The final bounded selection was run after the Futures replay-universe repair:

```powershell
& 'G:\AI_Trading\freqtrade-cn\freqtrade\.venv\Scripts\python.exe' -m pytest `
  tests/data/history/test_data_snapshot.py tests/data/test_dataprovider.py `
  tests/data/test_btanalysis.py tests/data/test_data_snapshot_replay_archive.py `
  tests/optimize/test_backtesting.py tests/optimize/test_backtest_replay_storage.py `
  tests/optimize/test_optimize_reports.py `
  tests/rpc/test_backtest_data_snapshot_schema.py tests/rpc/test_rpc_apiserver.py `
  -q -k "not test_api_freqaimodels" -p no:cacheprovider
```

Result: `406 passed, 1 deselected, 2 warnings in 46.53 s`. The deselected test is the
optional `test_api_freqaimodels` path because the shared environment lacks its optional
`datasieve` dependency. The warnings are the existing Starlette TestClient deprecation
and the deliberately constructed duplicate ZIP-member archive case.

Ruff over the touched backend source and relevant test trees passed. Backend and Root
`git diff --check` passed.

The final pair-universe regression first produced RED against the old Futures loop with
`KeyError: 'ETH/USDT:USDT'`. With the retained-route loop restored, the same test passed;
the five related Spot/Futures capture and replay cases passed together. Current history
was patched to raise if reached, and the accepted replay returned only the retained pair.

### Frontend

| Check | Result |
|---|---:|
| Focused Vitest (`backtestRevision` and localization parity) | 27 passed |
| `pnpm typecheck` | passed |
| `pnpm build` | passed |
| Exact changed-file ESLint | zero errors; 6 known pre-existing formatting warnings |
| Mocked Chromium Backtest journeys | 6 passed |
| Mocked installed Microsoft Edge Backtest journeys | 6 passed |

The mocked journeys cover legacy/API capability behavior, retention, replay source
selection, rejected-start selection preservation, accepted retry, strict evidence
visibility, and the current-context result warning. The narrow mocked background-job
fixture still emits existing `recoverBgJobs` console noise; it is not a replay-path
failure.

Non-failing build and lint noise was not expanded into unrelated cleanup: the known
VueUse pure-annotation and chunk-size warnings remain, as do formatting warnings in two
locale files and two unrelated regions of `src/stores/ftbot.ts`.

## 7. Orchestrated Gate Review

Orca orchestration tracked independent read-only backend, frontend, and
minimality/documentation reviews. Review workers changed no files.

| Task | Result |
|---|---|
| `task_45535b026fd5` | Initial backend Gate identified pair-universe drift, latest-pointer deletion, measured performance, stable metadata admission, and missing archive/atomic/privacy coverage; the implementation and RED regressions were repaired |
| `task_eb4f623e5b37` | Backend re-review closed the prior High findings and isolated one remaining Medium: Futures still iterated the current full whitelist |
| `task_677c5d23e015` | Final Futures replay-universe re-review PASS; no Blocker, High, or Medium finding |
| `task_05e523e08448` | Initial frontend Gate identified rejected-POST visibility/selection, FreqAI evidence exclusion, and accessibility findings; all were repaired |
| `task_3480d04495b3` | Frontend re-review PASS; no Blocker, High, or Medium finding |
| `task_73531e3e9b57` | Initial minimality/documentation Gate identified identity-only versus retained visible-state ambiguity and missing server-forced strategy-evidence semantics |
| `task_1900bf243eb2` | Minimality/documentation re-review PASS; no Blocker, High, or Medium finding and no platform/runtime expansion |
| `task_050708b6bb4d` | Final exact-SHA acceptance-document audit PASS; Git identities, verification/performance numbers, historical exposure, status, and next-boundary wording are coherent |

The final accepted state has no unresolved Blocker, High, or Medium finding inside this
contract. The reviews materially tightened failure visibility, pair-universe semantics,
archive safety, and truthful user-facing claims without adding a dataset platform,
environment-restoration system, or release/runtime model.

## 8. Safety, privacy, and explicit non-goals

- No Docker service, database, exchange account, order path, Paper runtime, Live runtime,
  remote branch, or external operational system was mutated for this acceptance.
- Replay bundle evidence, receipt, and sidecar contain no exchange/API credential,
  local strategy path, archived config, raw resolved-parameter payload, or arbitrary
  strategy I/O. A sentinel test scans every ZIP member and sidecar for secret leakage.
- Existing explicitly supported strategy-evidence members in the enclosing result ZIP
  are never executed as replay authority.
- No external CAS, snapshot database, reference counting, garbage collector, upload,
  import, CRUD page, arbitrary picker, or automatic retention was added.
- No StrategyRelease, Environment Identity, effective-config identity, exchange-context
  snapshot, container/SBOM archive, signing, encryption, attestation, RuntimeInstance,
  BotRelease, Paper Observation, optimizer/ranker, AI daemon, scheduler, or 8090 cutover
  was added.
- Public trades/orderflow, FreqAI model/training/prediction data, arbitrary strategy I/O,
  and complete offline environment restoration remain outside this replay contract.

## 9. Historical artifact exposure remains open

The preceding security acceptance found 191 parseable local Backtest ZIPs, including
184 with non-placeholder API-session secrets. This work did not display, copy, rewrite,
delete, quarantine, rotate, or revoke any of them. They remain an operational exposure
until service-specific retention and credential-rotation actions are separately
authorized and completed.

## 10. Acceptance decision and next boundary

Phase 1 Retained DataSnapshot Replay is accepted at the exact implementation SHAs above
with no unresolved Blocker, High, or Medium finding inside its boundary. All accepted
implementation commits are local; no remote push or merge is implied by this report.

No next implementation plan becomes active automatically. The next first-principles
decision should reassess a small Backtest Environment Evidence slice whose purpose is to
explain the remaining current-execution-context variation without building a complete
environment-restoration platform. Revision-bound robustness/holdout evidence may be
reassessed after that. Optimization/ranking, continuous AI insight capture, dynamic
RuntimeInstance, formal Paper Observation, Experiment UI, platform cutover, and Live
trading remain paused.
