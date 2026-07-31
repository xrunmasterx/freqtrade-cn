# Phase 1 Pair-History Context Truth Acceptance Report

**Acceptance date:** 2026-08-01

**Status:** accepted at exact implementation SHAs with deterministic frontend
store/component tests; no Docker start, market-data request, strategy execution,
Backtest submission, retired-holdout use, exchange request, trading database, Runtime,
Paper, Live, remote push, merge, release, or deployment

**Branch:** `xrunmasterx/phase1-complete-development`

**Worktree:**
`C:\Users\dezhengu\orca\workspaces\freqtrade-cn\phase1-complete-development`

**Plan:**
[Phase 1 Pair-History Context Truth](../plans/2026-08-01-phase1-pair-history-context-truth.md)

## 1. Exact implementation identity

| Repository | Exact accepted implementation SHA |
|---|---|
| Root | `6005903c55603bb19515eccb062b1c03316f90c3` |
| `freqtrade/` backend | `8b1ec82765cc0eb59da0287cd62dd892b62f0f11` (unchanged) |
| `frequi/` frontend | `69fa10cae618f7ed6cc8d19b7084ff9696845d64` |
| `freqtrade-strategies/` | `dec5adb77f03b0c33ccfbc036ff0a3e57f7d571d` (unchanged) |

The Root implementation commit has tree
`1d3ef44aa952639825d5c4dd6104783bd7d6d0a9` and pins the frontend implementation
SHA above. The frontend commit is `fix: bind pair history to request context`; the Root
implementation commit is `fix: preserve pair history context truth`.

This report and the final lifecycle status changes are a later documentation-only
commit. They do not replace the implementation identity accepted here.

## 2. Accepted user outcome

The 8081 webserver/history chart and 8083 Backtest visualizer no longer treat
`pair + timeframe` as sufficient proof that cached `/pair_history` data belongs to the
currently visible controls.

Each historic panel now renders an accepted dataset only when its complete frontend
request identity matches the user's current selection. That identity contains, in fixed
order:

- pair;
- timeframe;
- timerange;
- strategy;
- FreqAI model;
- requested columns, preserving their order;
- live mode;
- exchange;
- trading mode; and
- margin mode.

Changing strategy, timerange, FreqAI model, live mode, exchange/modes, or requested
columns immediately makes the prior dataset ineligible for rendering. Until the user
requests that context, the empty state is `not_loaded`; it cannot inherit another
context's success, error, slow-request state, or warning.

This does not add an automatic request for every strategy or timerange edit. The 8081
history journey retains its explicit refresh interaction. The existing Backtest
pair-switch refresh remains unchanged.

## 3. Request ordering and retained-data contract

`pair + timeframe` remains the display slot. The store now maintains the latest
requested key, status, slow-request state, and a private generation counter per slot.
Only the latest request started for a slot may mutate that slot.

| Completion or navigation scenario | Accepted presentation |
|---|---|
| old context succeeds after newer context | old result is ignored |
| old Axios failure arrives after newer success | data/status remain successful; no stale alert |
| two identical-key requests complete out of order | newer-started response remains authoritative |
| pair A and pair B overlap | each pair owns its status and slow state |
| same-context refresh fails after a success | retained matching chart remains visible with the existing refresh-failure warning |
| another context fails while accepted A remains cached | switching back to A shows A without the other context's error/slow/warning |
| selected context has never been requested | old chart is hidden and state is `not_loaded` |

The ten-second slow timer, success path, failure path, and `finally` cleanup all check
the slot generation. A stale completion cannot clear or set the current request's slow
indicator. Existing bot-wide history status refs remain for compatibility, but historic
panels do not use them as presentation authority.

## 4. Preserved chart behavior and source boundary

The live `/chart_candles` owner path is unchanged: a real `ChartsView` refresh event in
live mode still calls the live-chart composable and does not call `/pair_history` or the
ordinary candle store action.

The reduced-column Plot Config behavior is also preserved. When an explicit Plot Config
change requests a column advertised by a retained response's `all_columns` but absent
from its loaded `columns`, the parent emits the existing refresh request. Raw retained
column metadata is used only to decide whether to request; the old dataset remains
hidden unless its complete request key equals the new desired key.

Backtest historical Trades continue to pass unchanged into the chart. This acceptance
does not claim that those Trades and the current `/pair_history` candles, indicators,
or strategy Signals share the same historical revision or data snapshot. That mixed
source disclosure remains the next separate bounded slice.

## 5. Automated verification

No check in this section read market data or executed a strategy, Backtest, analysis,
holdout, Paper, or Live workload.

| Check | Result |
|---|---:|
| Pair-history owner/store/container focused Vitest | 5 files, 43 passed |
| Full FreqUI Vitest | 51 files, 354 passed |
| FreqUI typecheck | passed |
| FreqUI production build | passed |
| Changed FreqUI files ESLint | passed; 0 errors |
| New and otherwise changed files Prettier | passed |
| Root and FreqUI `git diff --check` before commits | passed |

Focused evidence includes all ten request-key fields, ordered columns, `false` versus
missing, empty columns versus missing, explicit `undefined` normalization, different-key
and identical-key out-of-order responses, a real mocked Axios stale failure, staggered
slow timers, per-pair isolation, same-context retained data, current-context empty/error
states, switching back to an accepted context, live owner routing, both historic owner
payloads, and reduced-column Plot Config refresh without mismatched rendering.

The successful Vitest process printed the project's existing Happy DOM fetch-abort and
occasional `EPROTO` teardown output. The production build retained existing third-party
pure-annotation, chunk-size, and plugin-timing warnings. None changed the successful exit
codes or is used as product evidence.

Full-file Prettier inspection of `ftbot.ts` reports two lines that predate and lie
outside this slice's diff. They were independently traced to baseline commits and left
unchanged under the repository's surgical-change rule. All other changed files pass
Prettier, ESLint reports no error, and `git diff --check` reports no changed-line issue.

## 6. Orchestrated independent Gates

Read-only reviewers independently examined the state model, product scope, test design,
implementation semantics, test sufficiency, and documentation. They made no functional
repository changes and did not access market, strategy, holdout, Backtest, Paper, or Live
data.

| Review | Result |
|---|---|
| Initial state-model design Gate | three P1 findings; complete key ownership, desired-state derivation, and retained-failure semantics were underspecified |
| State-model design re-Gate | PASS; P0/P1 = 0 |
| Initial product design Gate | one P1; current-context failure/retention behavior was underspecified |
| Product design re-Gate | PASS; P0/P1 = 0 |
| Initial test-design Gate | NO-GO; owner wiring, real Axios failure, same-key race, and staggered timer proof were incomplete |
| Test-design re-Gate | PASS; P0/P1 = 0 |
| Initial implementation diff Gate | P0/P1 = 0; one Plot Config behavior P2 and one baseline Prettier waiver |
| Implementation re-Gate | PASS; code P0/P1/P2 = 0 after Plot Config behavior was preserved |
| Initial test-sufficiency Gate | three P1 coverage gaps plus teardown-noise P2 |
| Test-sufficiency re-Gate | PASS; P0/P1 = 0; pre-existing teardown-noise P2 remains non-blocking |
| Product/documentation implementation Gate | PASS; P0/P1/P2 = 0 |

The test P1 findings were closed by directly locking all ten helper fields and
normalization rules, exercising the real live refresh owner, and covering the accepted-A
versus latest-requested-B switch-back state. The implementation P2 was closed with a
RED/green reduced-column regression that never permits mismatched data to render.

## 7. Evidence limits and decision

Acceptance is intentionally frontend-only. It proves deterministic request ordering and
presentation filtering with mocked HTTP responses; it does not prove backend market-data
correctness, packaged-browser behavior, Docker integration, network soak behavior, or
strategy correctness.

In particular, the accepted request key is not a Backtest revision, Strategy Evidence,
DataSnapshot, Execution Context Evidence, StrategyRelease, or historical reproduction
receipt. A matching key means only that the frontend response-shaping request fields
match the current visible context.

Phase 1 Pair-History Context Truth is accepted at the exact implementation SHAs in
Section 1. There is no unresolved P0, P1, or known code/product P2 inside its declared
frontend boundary. The remaining test teardown output and baseline Prettier lines are
recorded environmental/codebase hygiene facts, not acceptance evidence.

No strategy candidate is active. The former `20250702-20260702` holdout remains retired,
and no replacement holdout is assigned by this acceptance.
