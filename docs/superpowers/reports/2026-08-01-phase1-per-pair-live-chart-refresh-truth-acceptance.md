# Phase 1 Per-Pair Live Chart Refresh Truth Acceptance Report

**Acceptance date:** 2026-08-01

**Status:** accepted at exact implementation SHAs with frontend store/component tests;
no Docker start, market-data request, strategy execution, retired-holdout use, Backtest,
Recursive Analysis, Lookahead Analysis, exchange request, trading database, Runtime,
Paper, Live, remote push, merge, release, or deployment

**Branch:** `xrunmasterx/phase1-complete-development`

**Worktree:**
`C:\Users\dezhengu\orca\workspaces\freqtrade-cn\phase1-complete-development`

**Plan:**
[Phase 1 Per-Pair Live Chart Refresh Truth](../plans/2026-08-01-phase1-per-pair-live-chart-refresh-truth.md)

## 1. Exact implementation identity

| Repository | Exact accepted implementation SHA |
|---|---|
| Root | `064908fcf7168b53fad0c0d635889fd57072fea9` |
| `freqtrade/` backend | `8b1ec82765cc0eb59da0287cd62dd892b62f0f11` (unchanged) |
| `frequi/` frontend | `c74ad28d04fd9b71391faf600ba6af5cb9b53c48` |
| `freqtrade-strategies/` | `dec5adb77f03b0c33ccfbc036ff0a3e57f7d571d` (unchanged) |

The Root implementation commit has tree
`6a7c49159c025d0c2d457911ff98141a14d7a410` and pins the frontend implementation
SHA above. The frontend commit is `fix: isolate live chart refresh state`; the Root
implementation commit is `fix: preserve per-pair chart refresh truth`.

This report and the final status changes are a later documentation-only commit. They do
not replace the accepted implementation identity.

## 2. Accepted user outcome

The existing 8081 live chart can retain the last successful dataset after a transient
refresh failure without presenting that retained dataset as a successful current
refresh. The affected pair panel now shows a localized warning that refresh failed and
that the last successfully loaded chart data remains visible.

For a multi-pair chart, each `${pair}__${timeframe}` panel now receives its own:

- loading, success, or error state;
- backend `plot_config`;
- backend warnings; and
- retained-data refresh-failure warning.

A failure for pair B cannot make pair A appear failed, and pair A's plot configuration
or warnings cannot be attributed to pair B. A later successful refresh clears only the
recovered key's error state and retained-data warning.

When no successful dataset exists, the existing failed-to-load empty state remains in
place. A newly selected live key without a request status is explicitly `not_loaded`;
it does not inherit the legacy bot-wide candle status.

## 3. Concurrency and source-boundary contract

The public display identity remains the existing `${pair}__${timeframe}` key. Request
options can shape different responses for that same display slot, so the store keeps a
small private generation counter per display key. The latest started non-deduplicated
request is authoritative.

| Completion scenario | Accepted result |
|---|---|
| old success completes after newer success | newer data and success remain authoritative |
| old failure completes after newer success | old failure cannot contaminate the success state |
| old success completes after newer failure | retained previously accepted data stays visible; latest state remains error |
| A and B complete in either order | each key keeps its own status and dataset |
| failed B later succeeds | only B changes to success and clears its warning |

Exact duplicate in-flight requests continue to use the existing request deduplication
path and do not advance the generation. The generation map is private implementation
state; it adds no API, persistence format, scheduler, or general state-machine surface.

Presentation metadata remains response-owned. Each panel takes `plot_config` and backend
warnings from its own accepted `/chart_candles` response. The new retained-data warning
is UI-owned because it describes the state of the latest UI refresh, not a strategy or
market-data fact.

This acceptance does not add an exact freshness age. Candle timestamps and the explicit
failure warning are sufficient for the demonstrated defect. It also does not change the
approximately ten-second one-minute refresh schedule, forming-candle semantics,
strategy overlay source, or the separation between Strategy Signals and runtime Trades.

## 4. Automated verification

No check in this section read market data or executed a strategy or analysis workload.

| Check | Result |
|---|---:|
| Exact locale and parent-container focused Vitest | 2 files, 22 passed |
| Full FreqUI Vitest | 48 files, 316 passed |
| FreqUI typecheck | passed |
| FreqUI production build | passed |
| All changed FreqUI files ESLint with errors only | passed; 0 errors |
| Changed focused-test Prettier check | passed |
| Root and FreqUI `git diff --check` before commits | passed |

The test evidence covers the three same-slot response orderings, both cross-pair
completion orders, recovery after failure, data retention on the latest failure,
missing-key `not_loaded`, per-panel status/configuration/warnings, retained-data warning
visibility, no-data error presentation, view wiring, locale resolution, and legacy or
historic fallbacks.

The full Vitest process exited successfully while printing the project's existing Happy
DOM fetch-abort and `EPROTO` teardown noise. The production build retained existing
third-party pure-annotation, chunk-size, and plugin-timing warnings. None changed the
successful exit codes, and no warning was treated as evidence of runtime correctness.

## 5. Orchestrated independent Gates

Read-only reviewers independently examined the design, implementation semantics, test
coverage, and final documentation. They made no functional repository changes and did
not access market, strategy, holdout, Backtest, Paper, or Live data.

| Review | Result |
|---|---|
| Initial design Gate | one P1: same-slot response ordering and missing-key fallback were underspecified |
| Design re-Gate | PASS; P0/P1/P2 = 0 after latest-started-wins and explicit `not_loaded` were specified |
| Initial implementation Gate | functional behavior passed; two P2 documentation/locale-test gaps found |
| Initial test diff Gate | functional coverage passed; one P2 Prettier gap found |
| Final implementation re-Gate | PASS; P0/P1/P2 = 0 |
| Final test diff Gate | PASS; P0/P1/P2 = 0 |
| Acceptance-documentation Gate | PASS; P0/P1/P2 = 0 |

The implementation P2 findings were closed by aligning plan/README/STRATEGY lifecycle
language and adding exact English, Simplified Chinese, and bilingual locale assertions.
The test P2 was closed by applying the one-line Prettier form to the new component stub.

## 6. Evidence limits and decision

Acceptance is intentionally frontend-only. It proves the store and component contract
with deterministic mocked responses; it does not claim a packaged-browser, Docker,
exchange, network-failure, or long-duration soak result. Those stronger checks were not
required to close this local state-isolation defect and would have expanded the evidence
surface without changing the implementation decision.

This slice does not prove that displayed candles are globally fresh, that a backend
response is market-correct, that a strategy is correct or robust, or that any candidate
is eligible for Paper or Live. It makes one narrower claim: the accepted UI no longer
uses another pair's refresh result or response metadata as evidence for the current
panel, and retained data is not silently presented after the latest refresh fails.

Phase 1 Per-Pair Live Chart Refresh Truth is accepted at the exact implementation SHAs
in Section 1. There is no unresolved P0, P1, or known P2 inside its declared frontend
boundary. No strategy candidate is active. The former `20250702-20260702` holdout
remains retired, and no replacement holdout is assigned by this acceptance.
