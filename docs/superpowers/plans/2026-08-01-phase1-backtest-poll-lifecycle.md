# Phase 1 Backtest Poll Lifecycle

**Status:** Completed; exact-SHA accepted

**Design Gate:** PASS; P0 = 0, P1 = 0, P2 = 0

**Implementation Gate:** PASS; P0 = 0, P1 = 0, P2 = 0

**Acceptance evidence:**
[Phase 1 Backtest Poll Lifecycle Acceptance](../reports/2026-08-01-phase1-backtest-poll-lifecycle-acceptance.md)

**Scope:** FreqUI only; no backend API, background-job protocol, Backtest engine,
strategy, market-data, Runtime, Paper, Live, deployment, or AI-worker changes

## User problem

`BacktestingView` starts a one-second interval while a backtest is running and clears it
when `backtestRunning` becomes false. It does not clear that view-owned interval when the
user navigates away.

The hidden page can therefore keep requesting `/backtest` and mutating shared store
state after its UI no longer exists. This wastes local work and makes the owner of the
polling lifecycle ambiguous. It does not stop or corrupt the server-side backtest, but
it is an avoidable client lifecycle leak in an existing Phase 1 journey.

## Assumptions and decisions

1. The backend job is independent of this view. Leaving the page stops only the local
   polling interval; it does not request cancellation of the running backtest.
2. The interval belongs to the active `BacktestingView` component scope. The lifecycle
   invariant is: exactly one interval while that scope is alive and its active bot reports
   `backtestRunning === true`; otherwise zero intervals.
3. A user may leave and return while the same backend job is still running. The watcher
   must therefore evaluate immediately on mount; waiting only for a future false-to-true
   transition would fail to resume observation after the leak is fixed.
4. The existing one-second cadence and `pollBacktest` action remain authoritative.
5. Clearing an interval does not cancel a request already in flight. Request
   cancellation, single-flight polling, retry/backoff, and cross-bot ownership are
   separate policies and are not inferred for this bounded repair.

## Minimal implementation

1. Add one local helper that clears `pollInterval` when it is not `null` and resets the
   ref to `null`.
2. Reuse that helper when `backtestRunning` becomes false and from `onUnmounted`.
3. Make the existing watcher immediate so a mounted view resumes polling when the store
   already knows that a backtest is running.
4. Guard interval creation with `pollInterval === null` so the mounted view owns at most
   one timer.

No composable, scheduler, timer registry, API field, store persistence, or new UI state
is needed for this single-view lifecycle rule.

## Acceptance criteria

1. A mounted view whose `backtestRunning` changes from false to true creates one
   one-second interval and calls the existing `pollBacktest` action on timer advance.
2. Unmounting that running view clears its interval; advancing fake timers afterwards
   produces no additional `pollBacktest` call.
3. Mounting while `backtestRunning` is already true immediately creates one interval,
   preserving observation when a user returns to a running job.
4. Changing `backtestRunning` to false clears the interval and resets the local timer
   ownership without requiring unmount.
5. A false-to-true-to-false-to-true sequence owns at most one interval at any moment and
   creates one new, non-overlapping interval after the second transition to true.
6. The existing mounted `getState` request remains unchanged.
7. Focused component Vitest, full FreqUI Vitest, `pnpm typecheck`, `pnpm build`,
   changed-file ESLint, Prettier for the new test, and `git diff --check` pass.
8. Backend and strategy submodules remain unchanged. No actual Backtest, market,
   strategy, holdout, Paper, or Live workload is run for acceptance.

## Explicit non-goals

- no server-side backtest cancellation on navigation;
- no change to the one-second poll cadence;
- no conversion from `setInterval` to a recursive timeout or WebSocket protocol;
- no abort controller for an already in-flight poll;
- no retry, backoff, notification, scheduler, or persistence;
- no change to result visualization, evidence identity, or Backtest semantics;
- no multi-bot polling redesign.

## Planned verification

```powershell
Set-Location frequi
pnpm vitest run tests/component/BacktestingViewPolling.spec.ts
pnpm vitest run
pnpm typecheck
pnpm build
pnpm exec prettier --check tests/component/BacktestingViewPolling.spec.ts
pnpm exec eslint --quiet src/views/BacktestingView.vue tests/component/BacktestingViewPolling.spec.ts
git diff --check
```

Acceptance uses fake timers and a mocked bot store. It does not start Docker or submit a
backtest job.
