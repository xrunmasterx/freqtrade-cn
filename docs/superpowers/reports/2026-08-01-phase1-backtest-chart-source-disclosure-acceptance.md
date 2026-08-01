# Phase 1 Backtest Chart Source Disclosure Acceptance Report

**Acceptance date:** 2026-08-01

**Status:** accepted at exact implementation SHAs with deterministic backend API and
frontend store/component evidence; no Docker start, external or user market-data request,
candidate/user/holdout strategy workload, Backtest submission, exchange request, trading
database, Runtime, Paper, Live, remote push, merge, release, or deployment

**Branch:** `xrunmasterx/phase1-complete-development`

**Worktree:**
`C:\Users\dezhengu\orca\workspaces\freqtrade-cn\phase1-complete-development`

**Plan:**
[Phase 1 Backtest Chart Source Disclosure](../plans/2026-08-01-phase1-backtest-chart-source-disclosure.md)

## 1. Exact implementation identity

| Repository | Exact accepted implementation SHA |
|---|---|
| Root | `8daa16253de23487c79bcd0bd5a6c8ec13bad71b` |
| `freqtrade/` backend | `3823205239281af56c34f4ff07f1674edddbe6db` |
| `frequi/` frontend | `410018a1de9a65e97d8b8b3e12bdfb4d3926d404` |
| `freqtrade-strategies/` | `dec5adb77f03b0c33ccfbc036ff0a3e57f7d571d` (unchanged) |

The Root implementation commit has tree
`530ee8cf470aadccad30298ed37e978265ceb53a` and pins both changed submodule SHAs above.
The backend commit is `fix: preserve explicit pair history freqai context`; the frontend
commit is `fix: bind backtest chart to selected result`; the Root implementation commit is
`fix: disclose backtest chart source context`.

This report and the final lifecycle status changes are a later documentation-only commit.
They do not replace the implementation identity accepted here.

## 2. Accepted user outcome and evidence boundary

The selected Backtest result remains usable for visual review, but the chart no longer
implies that it is an exact replay of that historical execution. The UI permanently
distinguishes three sources:

- Trade markers come from the selected Backtest result;
- candles come from the local data available when the chart is requested; and
- indicators, strategy Signals, and chart annotations are recalculated with the strategy
  code installed when the chart is requested.

The exact accepted title is:

```text
Selected Backtest result trades on a recalculated chart
```

The permanent English warning is:

```text
Trade markers come from the selected Backtest result. Candles are loaded from the local
data available now. Indicators, strategy signals, and chart annotations are recalculated
with the strategy code installed now. The code or data may differ from that Backtest, so
this chart is a reference—not an exact replay.
```

The Simplified Chinese and bilingual locale paths carry the same meaning and are locked by
hard-coded locale tests. Matching strategy name or timeframe does not remove the warning.
An explicitly detected strategy/timeframe mismatch retains the existing fail-closed marker
hiding. Merely unverified revision, Strategy Evidence, or DataSnapshot identity retains
the basic Trade markers together with the permanent warning.

This acceptance does not claim that the current chart reproduces the Backtest's historical
analyzed dataframe, strategy revision, parameters, local data snapshot, execution
environment, or FreqAI state. It does not execute archived Python strategy source.

## 3. Selected-result context ownership

`BacktestingView` now passes one selected `backtestResult` to `BacktestResultChart` instead
of passing editable Backtest-form fields as independent chart authorities. On backend API
2.57+, the selected result owns these six weak context fields:

- strategy;
- timeframe;
- timerange;
- FreqAI model;
- trading mode; and
- margin mode.

Pair remains user-selected, requested columns remain Plot-Config-selected, and exchange
remains Webserver-owned. The result's Trades pass unchanged to the chart.

The Backtest chart explicitly requests the existing POST Pair-History transport. The Store
honors that request only when the backend advertises `reducedPairCalls`; API 2.57 always
has that capability. Therefore disabling the global reduced-call preference cannot make an
API 2.57 Backtest chart fall back to GET and silently lose result-owned trading or margin
mode. Other Pair-History callers keep their prior capability-plus-user-setting behavior.

A GET-only legacy backend may still show a selected result that carries a non-empty FreqAI
model, but that is limited compatibility and is not accepted as the complete six-field
contract. A no-model result on an older backend fails closed before mounting the history
chart and emits no unsafe request; the surrounding Pair Summary and Trade navigation
remain available.

## 4. Explicit no-FreqAI request contract

Backend API 2.57 gives the existing `freqaimodel` field a minimum three-state wire
contract without adding a route or schema field:

| Wire state | Accepted request-local behavior |
|---|---|
| omitted, or POST `null` | inherit service configuration for old-client compatibility |
| non-empty string | override only the request-local model name; it does not enable FreqAI |
| empty string `""` | explicitly select no FreqAI model for the chart recomputation |

For the explicit empty value, the backend writes `freqaimodel=None` only into the existing
deep-copied request configuration. If that copy already contains a `freqai` object, it also
sets the copied `freqai.enabled` to false. It does not mutate the service configuration and
does not synthesize an incomplete `freqai` object for ordinary non-FreqAI configurations.

The updated frontend advertises `pairHistoryExplicitNoFreqai` at API 2.57. Missing, `null`,
or empty selected-result model identity is sent as `""` only when the backend advertises
that meaning. Against an older backend, the chart remains unmounted and shows the exact
upgrade requirement instead of accidentally inheriting the Webserver's configured model.
An old FreqUI cannot be corrected retroactively, so the packaged local frontend/backend
pair must be upgraded together.

## 5. Automated verification

No check in this section accessed external or user market data, executed a candidate or
holdout strategy workload, submitted a Backtest, or exercised Paper or Live trading. The
existing Pair-History endpoint regressions used repository fixture or generated OHLCV and
executed the isolated test-strategy analysis path. That is deterministic API-contract
evidence, not a user/candidate product workload.

| Check | Result |
|---|---:|
| Backend Pair-History/API-version pytest | 12 passed, 131 deselected |
| Backend Ruff check on changed production and test files | passed |
| Backend Ruff format check on changed production files | passed |
| Focused frontend regression after the final transport fix | 4 files, 41 passed |
| Full FreqUI Vitest | 52 files, 364 passed |
| FreqUI typecheck | passed |
| FreqUI production build | passed |
| Changed FreqUI files ESLint | passed; 0 errors |
| Changed non-baseline-drift FreqUI files Prettier | passed |
| Root/backend/FreqUI working and staged `git diff --check` | passed |
| Strategy submodule status | unchanged and clean |

Backend tests exercise actual FastAPI GET and POST requests across nine configuration/wire
combinations: omitted, POST `null`, explicit empty, and explicit non-empty model values;
configured and absent `freqai` objects; request-local disablement; and global nested/key
presence immutability. The API-version test locks the capability at 2.57.

Frontend evidence covers the selected-result owner boundary, editable-form divergence,
permanent source copy, unchanged Trades, no-model and explicit-model contexts, API 2.56
versus 2.57 feature evaluation, old-backend no-model fail-closed behavior, old-backend
explicit-model compatibility, GET/POST empty-value serialization, transport/cache identity,
the API 2.57 forced-POST path while the global setting is disabled, warning composition,
and explicit marker mismatch behavior.

The backend pytest printed one existing Starlette/httpx deprecation warning. Successful
Vitest runs printed the project's existing Happy DOM fetch-abort/worker teardown noise.
The production build retained existing third-party pure-annotation, chunk-size, and
plugin-timing warnings. None changed a successful exit code or is used as product evidence.

ESLint reported four pre-existing locale Prettier warnings and two pre-existing `ftbot.ts`
Prettier warnings outside this slice's hunks, with zero errors. The same two Store lines and
the broader backend test file were already not full-file formatter-clean before this slice;
they were left unchanged under the surgical-change rule. All edited hunks pass
`git diff --check`, and the other changed frontend files pass Prettier.

## 6. Orchestrated independent Gates

Read-only reviewers independently examined source evidence, product scope, test design,
implementation semantics, cross-version behavior, and documentation. They made no
functional repository changes and did not access market, strategy, holdout, Backtest,
Paper, or Live data.

| Review | Result |
|---|---|
| Source/evidence audit | GO; P0/P1/P2 = 0 |
| Initial product Gate after three-state design | GO; P0/P1/P2 = 0 |
| Initial test Gate | GO with one P2 global-key-presence gap; assertion added |
| Initial documentation Gate | NO-GO; lifecycle wording and over-broad ownership wording corrected |
| Initial implementation diff Gate | NO-GO; cross-version empty-string semantics lacked an advertised capability |
| Capability re-Gates | GO after API 2.57 feature Gate and old-backend fail-closed behavior |
| Final documentation audit | found one P1: supported GET fallback ignored trading/margin mode |
| Final transport fix re-Gates: documentation, product, test, diff | GO; each P0/P1/P2 = 0 |

The final P1 was closed with a local `forcePost` call intent, not a new endpoint or global
transport policy. The Store still checks backend capability, ordinary callers still use the
existing default, and tests prove both the forced Backtest path and unchanged legacy
transport paths.

## 7. Evidence limits and decision

Acceptance proves a deterministic API/UI source-boundary contract. It does not prove
packaged-browser integration, Docker networking, local market-data availability, strategy
correctness, Backtest reproducibility, exact historical chart replay, performance,
profitability, Runtime readiness, Paper readiness, or Live readiness.

Exact historical indicator replay remains a separate possible design: a result-bound,
read-only chart snapshot retained in the existing Backtest artifact lifecycle. That future
work would need its own storage, serialization, ZIP-safety, legacy, and identity-binding
Gate. It is not implicitly authorized by this acceptance.

Phase 1 Backtest Chart Source Disclosure is accepted at the exact implementation SHAs in
Section 1. There is no unresolved P0, P1, or known code/product P2 inside its declared
source-disclosure and API 2.57 context boundary.

No strategy candidate is active. The former `20250702-20260702` holdout remains retired,
and no replacement holdout is assigned by this acceptance.
