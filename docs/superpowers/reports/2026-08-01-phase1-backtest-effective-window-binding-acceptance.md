# Phase 1 Backtest Effective Window Binding Acceptance Report

**Acceptance date:** 2026-08-01

**Status:** accepted at exact implementation SHAs with deterministic frontend
component/locale evidence; no Docker or service start, external or user market-data
request, strategy candidate or holdout workload, Backtest submission, exchange request,
trading database, Runtime, Paper, Live, remote push, merge, release, or deployment

**Branch:** `xrunmasterx/phase1-complete-development`

**Worktree:**
`C:\Users\dezhengu\orca\workspaces\freqtrade-cn\phase1-complete-development`

**Plan:**
[Phase 1 Backtest Effective Window Binding](../plans/2026-08-01-phase1-backtest-effective-window-binding.md)

## 1. Exact implementation identity

| Repository | Exact accepted implementation SHA |
|---|---|
| Root | `30793b226588914ae3ce3ab600ab45aef9824027` |
| `freqtrade/` backend | `3823205239281af56c34f4ff07f1674edddbe6db` (unchanged) |
| `frequi/` frontend | `820bcc81d8665f22969aa0f888fa1d3c548bac4d` |
| `freqtrade-strategies/` | `dec5adb77f03b0c33ccfbc036ff0a3e57f7d571d` (unchanged) |

The Root implementation commit has tree
`55f2972d1b265c39beac2f0f79eea80a9b4250d1` and pins the three exact submodule SHAs
above. The frontend implementation commit has tree
`9fead2f88c11da394bbf77dcb8daee01cfe9ccf5`. Both implementation commits are named
`fix: bind backtest chart to effective window`.

This report and the final lifecycle-status changes are a later documentation-only commit.
They do not replace the implementation identity accepted here.

## 2. Accepted user outcome

When a selected Backtest result contains one unambiguous effective scored window, the
Backtest chart now requests that concrete interval instead of reopening the original,
possibly open-ended requested timerange. The same effective window owns the visible
`Actual Backtest window` label, so historical Trade markers are reviewed against current
reference candles narrowed to the interval that was actually scored.

The actual-window interpretation is accepted only when both `backtest_start_ts` and
`backtest_end_ts` are JavaScript numbers, safe integers, positive 13-digit Unix
milliseconds, exactly second-aligned, valid dates, and ordered with start before end.
The Pair-History request is then exactly:

```text
<backtest_start_ts>-<backtest_end_ts>
```

The display renders both endpoints in the configured timezone and includes timezone
identity. Changing the configured timezone while the component remains mounted updates
the label but does not change the numeric request or request context.

If either endpoint is missing, null, a string, non-finite, unsafe, not 13 digits,
sub-second, equal to the other endpoint, or reversed, the interpretation fails closed as
one atomic unit: the chart retains `backtestResult.timerange` unchanged and uses the
legacy `Timerange` label. It does not round, guess units, or combine endpoints from
different authorities.

## 3. Preserved source and compatibility boundaries

This slice changes only the selected-result chart's timerange selection and label. The
permanent warning that the chart mixes selected-result Trades with current local candles
and currently recalculated indicators, Signals, and annotations remains unchanged. It
does not claim exact historical replay.

The selected result continues to own strategy, timeframe, FreqAI model presence, trading
mode, margin mode, and Trade markers under the previously accepted source-disclosure
contract. Pair remains user-selected, columns remain Plot-Config-selected, exchange
remains Webserver-owned, and the supported chart path continues to force POST. The
existing explicit-no-FreqAI capability guard and older-backend behavior are unchanged.

No backend route, API version, result schema, result artifact, persistence format,
strategy, configuration, or runtime topology changed.

## 4. Test-first and deterministic verification

No check in this section accessed external or user market data, ran a strategy candidate,
used the retired holdout, submitted a Backtest, or exercised Runtime, Paper, or Live
trading.

| Check | Result |
|---|---:|
| Focused RED test before implementation | expected failure: 5 failed, 29 passed |
| Focused component and locale GREEN test | 2 files, 34 passed |
| Expanded chart/store/locale regression at exact frontend SHA | 5 files, 75 passed |
| FreqUI typecheck | passed |
| FreqUI production build | passed |
| Changed-file ESLint | passed with 0 errors; 4 pre-existing locale warnings |
| Root and frontend `git diff --check` | passed |
| Root gitlink and all four repository identities | exact SHA match |

The RED failures proved that the old component still requested the original timerange and
lacked the actual-window locale contract. The GREEN coverage proves the valid exact
request, visible timezone-bearing label, mounted CET-to-UTC reaction without request
drift, the complete invalid-value fallback matrix, the permanent mixed-source warning,
unchanged Trades, all other request fields, forced POST, explicit-no-FreqAI behavior, and
English, Simplified Chinese, and bilingual locale resolution.

The successful expanded Vitest run printed existing Happy DOM fetch-abort teardown noise.
The production build retained existing third-party pure-annotation, chunk-size, and
plugin-timing warnings. ESLint reported four pre-existing Prettier warnings in untouched
locale lines, with zero errors and no warning introduced by this slice. None changed a
successful exit code or is used as product evidence.

## 5. Orchestrated independent Gates

Read-only reviewers examined the design boundary, timestamp protocol facts, product
scope, tests, implementation diff, reactive settings behavior, and documentation. They
made no repository changes and did not access market, strategy, holdout, Backtest, Paper,
or Live data.

| Review | Result |
|---|---|
| Design Gate (`task_3d1dc3398c9f`) | two P1 requirements found: strict second-aligned 13-digit validation and timezone-explicit display; both incorporated before implementation |
| Initial diff Gate (`task_2dae3d10aa32`) | one P1 found: the mounted label could cache a stale timezone; repaired with an explicit reactive settings-store dependency and lifecycle test |
| Final re-Gate (`task_ca8e3e8d3e08`) | PASS; P0/P1/P2 = 0 |
| Final documentation-to-implementation Gate (`task_b0c419f8abcd`) | PASS; P0/P1/P2 = 0; exact identities, behavior, tests, lifecycle, source boundaries, and non-scope agree |

The final Gate specifically confirmed that changing the configured timezone updates the
mounted label while the exact millisecond request and request context remain unchanged.

## 6. Evidence limits and decision

Acceptance proves a deterministic frontend ownership and disclosure contract. It does
not prove packaged-browser integration, Docker networking, local market-data availability,
strategy correctness, Backtest reproducibility, exact historical indicator replay,
performance, profitability, Runtime readiness, Paper readiness, or Live readiness.

Phase 1 Backtest Effective Window Binding is accepted at the exact implementation SHAs in
Section 1. There is no unresolved P0, P1, or known code/product P2 inside its declared
frontend-only boundary.

No strategy candidate is active. The former `20250702-20260702` holdout remains retired,
and no replacement holdout is assigned or authorized by this acceptance. Dynamic Paper
and continuous AI operation remain a NO-GO until separately selected and governed.
