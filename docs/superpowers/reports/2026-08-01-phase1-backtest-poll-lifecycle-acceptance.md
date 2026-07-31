# Phase 1 Backtest Poll Lifecycle Acceptance Report

**Acceptance date:** 2026-08-01

**Status:** accepted at exact implementation SHAs with a real-component fake-timer
test; no Docker start, backtest submission, market-data request, strategy execution,
retired-holdout use, exchange request, trading database, Runtime, Paper, Live, remote
push, merge, release, or deployment

**Branch:** `xrunmasterx/phase1-complete-development`

**Worktree:**
`C:\Users\dezhengu\orca\workspaces\freqtrade-cn\phase1-complete-development`

**Plan:**
[Phase 1 Backtest Poll Lifecycle](../plans/2026-08-01-phase1-backtest-poll-lifecycle.md)

## 1. Exact implementation identity

| Repository | Exact accepted implementation SHA |
|---|---|
| Root | `b99bba8852ef700e05379d4646ac5fa682baac4d` |
| `freqtrade/` backend | `8b1ec82765cc0eb59da0287cd62dd892b62f0f11` (unchanged) |
| `frequi/` frontend | `a084c1526ad7e65b0972c342a0a20c1871dd98f9` |
| `freqtrade-strategies/` | `dec5adb77f03b0c33ccfbc036ff0a3e57f7d571d` (unchanged) |

The Root implementation commit has tree
`63f73c9c17c5b0b0dd909593ee2a0adb3c646e64` and pins the frontend implementation
SHA above. The frontend commit is `fix: scope backtest polling to view`; the Root
implementation commit is `fix: scope backtest polling lifecycle`.

This report and the final lifecycle status changes are a later documentation-only
commit. They do not replace the implementation identity accepted here.

## 2. Reproduced defect

Before the repair, a real shallow-mounted `BacktestingView` produced two independent
test failures:

1. after one running poll, unmounting the view and advancing two more seconds increased
   `pollBacktest` calls from one to three; and
2. mounting while `backtestRunning` was already true created no interval.

The first failure proves that the view-owned interval survived component destruction.
The second proves that adding cleanup alone would be incomplete: when a user returned
to a still-running backend job, the watcher would wait for a new false-to-true transition
that might never occur.

The unrelated component-library timer count was deliberately removed from the test
oracle. Final assertions observe only `window.setInterval` creation and the actual
`pollBacktest` action, so unrelated timeouts cannot manufacture a pass.

## 3. Accepted lifecycle contract

The active `BacktestingView` component scope owns exactly one interval when its active
bot reports `backtestRunning === true`, and no interval otherwise.

- false to true starts one one-second interval;
- true to false clears that interval and resets local ownership;
- unmount clears the same interval without cancelling the server-side job;
- mounting while the store already reports true starts one interval immediately; and
- false to true to false to true creates two sequential, non-overlapping intervals.

The existing `getState` call on mount, one-second cadence, and `pollBacktest` store action
remain unchanged. The repair adds one local idempotent cleanup function, one null guard,
an immediate watcher option, and one unmount hook. It adds no composable, timer registry,
scheduler, store field, API, or UI state.

## 4. Evidence limits

Clearing an interval prevents future ticks. It does not abort a request that was already
in flight when navigation occurred, and such a request may still complete and update the
shared store. This acceptance does not define request cancellation, single-flight
polling, retry/backoff, or cross-bot timer ownership.

The server-side backtest continues independently when the user leaves the page. The
repair does not cancel, pause, restart, or otherwise change the Backtest engine or its
result semantics.

## 5. Automated verification

No check in this section submitted a backtest or read market, strategy, holdout, Paper,
or Live data.

| Check | Result |
|---|---:|
| Pre-fix focused component test | 1 file; 2 failed and 1 passed, reproducing both lifecycle gaps |
| Post-fix focused component test | 1 file, 3 passed |
| Backtest-related frontend regression set | 3 files, 19 passed |
| Full FreqUI Vitest | 49 files, 319 passed |
| FreqUI typecheck | passed |
| FreqUI production build | passed |
| Changed-file ESLint with `--quiet` | passed; 0 errors |
| New test Prettier check | passed |
| Root and FreqUI `git diff --check` before commits | passed |

The full Vitest process exited successfully while printing the existing Happy DOM
fetch-abort and `EPROTO` teardown noise. The production build retained existing
third-party pure-annotation, chunk-size, and plugin-timing warnings. These were not
treated as product evidence and did not change the successful exit codes.

## 6. Orchestrated independent Gates

Read-only reviewers checked the lifecycle design, implementation diff, real-component
test semantics, scope, and final documentation. They made no functional repository
changes and did not run Docker or an actual Backtest.

| Review | Result |
|---|---|
| Initial design Gate | PASS; P0/P1 = 0; two wording/verification P2 findings |
| Design re-Gate | PASS; P0/P1/P2 = 0 after component-scope wording and full commands were added |
| Implementation diff Gate | PASS; P0/P1/P2 = 0 |
| Independent test Gate | PASS; P0/P1/P2 = 0 |
| Acceptance-documentation Gate | PASS; P0/P1/P2 = 0 |

The first design P2 aligned the lifecycle invariant with the setup-time immediate
watcher. The second made the planned verification block match its full acceptance
criteria. Neither required a broader implementation.

## 7. Decision

Phase 1 Backtest Poll Lifecycle is accepted at the exact implementation SHAs in Section
1. There is no unresolved P0, P1, or known P2 inside its declared FreqUI lifecycle
boundary.

This acceptance does not prove strategy correctness, Backtest correctness, representative
coverage, robustness, Paper or Live eligibility, or current or future profitability. No
strategy candidate is active. The former `20250702-20260702` holdout remains retired,
and no replacement holdout is assigned by this acceptance.
