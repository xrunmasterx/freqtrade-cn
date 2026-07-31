# Phase 1 Evidence-Guided Backtest Pair Acceptance Report

**Acceptance date:** 2026-07-31

**Status:** accepted at exact implementation SHAs; local commits only; no backend,
trading-runtime, Docker, exchange, Paper, Live, or remote state changed

**Branch:** `xrunmasterx/phase1-complete-development`

**Worktree:**
`C:\Users\dezhengu\orca\workspaces\freqtrade-cn\phase1-complete-development`

**Plan:**
[Phase 1 Evidence-Guided Backtest Pair](../plans/2026-07-31-phase1-evidence-guided-backtest-pair.md)

**Decision:**
[Backtest Pair Interpretation Boundary](../decisions/2026-07-31-backtest-pair-interpretation-boundary.md)

**Preceding evidence gate:**
[Phase 1 Backtest Execution Context Evidence](2026-07-31-phase1-backtest-execution-context-evidence-acceptance.md)

## 1. Exact implementation identity

| Repository | Exact accepted implementation SHA |
|---|---|
| Root | `bb769e459aa62d653ddc1f40ed4a29d42d024a54` |
| `freqtrade/` backend | `3209d437450fd1cc72903d9cc5ae8225bd7f8fb6` (unchanged) |
| `frequi/` frontend | `515b00cccb882c3f304bab18d0eb5520f934901e` |
| `freqtrade-strategies/` | `dbd5b0b21cfbf5ee80588d37458ace2467b7f8a4` (unchanged) |

The Root implementation commit records the exact frontend submodule pointer and the
accepted decision, plan, strategy, status, and glossary changes. This report is a later
documentation-only commit and does not change the accepted implementation identity.

## 2. Accepted user outcome

The existing authoritative 8083 Backtest comparison page can now interpret exactly two
loaded results without requiring the user to manually combine three independent evidence
cards and two hidden scored windows.

The accepted classifier recognizes only these two retrospective review shapes:

| Interpretation | DataSnapshot | Strategy evidence | Execution context | Effective scored windows |
|---|---|---|---|---|
| Same-window strategy-change review | same | different | same | exactly equal |
| Cross-window review | different | same | same | strictly disjoint |

The effective windows come directly from each in-memory strategy result's
`backtest_start_ts` and `backtest_end_ts` epoch-millisecond fields. They do not come from
request timeranges, optional history timestamps, data-coverage windows, warmup windows,
or run-start metadata. A shared endpoint is overlap, not strict disjointness.

Missing or malformed required evidence and invalid timestamps fail closed to `UNKNOWN`.
Every other fully known evidence combination is `NOT COMPARABLE FOR THESE REVIEWS`.
Cardinality other than two renders no pair interpretation.

The interpretation appears above the pre-existing independent DataSnapshot, Strategy
Evidence, and Execution Context cards and the unchanged full metric table. Result order
is preserved only for display and window association; classification is symmetric.

## 3. Claim and scope boundary

The accepted UI reports only whether the loaded pair matches one of the two evidence
shapes. It does not:

- prove strategy revision lineage or a shared experiment;
- assign baseline/candidate, calibration/holdout, or train/test roles;
- prove that either historical window was previously untouched or out of sample;
- prove causality, absence of lookahead or recursive bias, robustness, generalization,
  contract safety, Paper eligibility, or future performance;
- score, rank, recommend, promote, optimize, or automatically accept a result; or
- add a backend, API, schema, database, store, route, persisted split, trial ledger,
  scheduler, second engine, RuntimeInstance, BotRelease, or Paper workflow.

Different valid Strategy Evidence may represent entirely unrelated strategy names. The
positive same-window state is therefore deliberately called a strategy-change review,
not a strategy-revision comparison.

## 4. Implementation boundary

The production change is frontend-only:

- one pure fail-closed classifier beside the existing strict Backtest evidence helpers;
- one neutral, accessible interpretation section in the existing comparison component;
- English and Chinese copy; and
- focused utility, component, and locale tests.

The classifier reuses the accepted DataSnapshot, Strategy Evidence, and aggregate
Execution Context validators. It introduces no fallback to strategy name, revision ID,
run ID, filename, timerange, metric, or profit. Its scored-window relation remains an
internal implementation detail; the public assessment exposes only the state and the two
validated windows.

The UI uses neutral slate styling, a named section and heading, a polite status region,
semantic `dl`/`dt`/`dd` rows, and an explicit limitation statement. The Chinese
same-window label is `同一计分窗口策略变化复核`, avoiding the ambiguous abbreviation
`同窗` and preserving the neutral review meaning.

## 5. Development loop and evidence boundary

The implementation used focused RED-to-GREEN loops, but the transient output from the
pre-implementation RED commands was not retained as an acceptance artifact. Exact failure
counts from those runs are therefore intentionally not claimed here. The durable
acceptance authorities are the tests in the exact frontend commit, their final passing
results in Section 6, and the independent reviews in Section 7.

During development:

1. Classifier tests first exercised the absent
   `getBacktestResearchPairAssessment` surface; implementation then made the utility cases
   green.
2. UI and locale tests first exercised the absent pair section and locale keys; the
   component, English/Chinese copy, and locale assertions then made the focused suite
   green.
3. Low-finding closure tests exercised the unnecessary public `window_relation` field and
   the ambiguous Chinese label; removing that public surface and correcting the label
   made the focused suite green.
4. Independent re-Gate review identified missing regression locks, not production
   defects. Test-only additions now cover malformed-but-present Strategy and Execution
   Context evidence under a known confound, invalid end timestamps, representative known
   confounds, the exact strategy-timestamp input source, insertion order, and per-result
   rendered-window association.

## 6. Verification evidence

All final production checks used frontend
`515b00cccb882c3f304bab18d0eb5520f934901e`. The final two regression-lock additions are
part of that same frontend commit and were reviewed before the commit.

| Check | Result |
|---|---:|
| Focused Vitest (`backtestRevision`, component, locale) | 3 files, 36 passed |
| Full Vitest | 43 files, 274 passed |
| `pnpm typecheck` | passed |
| `pnpm build` | passed; 2,104 modules transformed |
| Core changed-file ESLint | zero errors and zero warnings |
| Changed locale ESLint | zero errors; four pre-existing formatting warnings |
| Core changed-file Prettier check | passed |
| Root and FreqUI `git diff --check` | passed |

The full Vitest command exits successfully but still prints existing Happy DOM
fetch-abort teardown messages and fork-termination `EPROTO` noise after reporting all 274
tests passed. Focused tests are clean. The production build retains existing VueUse
pure-annotation, large-chunk, and plugin-timing warnings.

The four locale warnings are unchanged base-file formatting findings: two in English and
two in Chinese. The Chinese warning whose current line number moved was shifted only by
the 17 inserted locale lines. Unrelated locale formatting was deliberately not rewritten.

No backend test was rerun because the backend SHA is unchanged and the slice adds no
backend call or contract. No Docker image, live 8083 service, browser session, database,
exchange request, Paper bot, Live bot, or order path was exercised. This report therefore
makes no Docker or live-runtime acceptance claim; frontend evidence consists of pure
classifier tests, component DOM tests, type checking, and the production build.

## 7. Orchestrated Gate review

Orca orchestration tracked independent first-principles research and the complete design,
implementation, and re-Gate loop. Review workers made no file changes.

| Task | Result |
|---|---|
| `task_998f122840fa` | User-outcome audit selected a bounded comparison decision before optimizer, AI daemon, or Paper |
| `task_8579da45823e` | Statistical audit constrained claims to observed behavior in exact historical scope |
| `task_372e79ca2c5e` | Backend audit confirmed zero backend change was sufficient |
| `task_3bf71f3278b8` | Evidence audit confirmed current identities support only a bounded retrospective interpretation |
| `task_6437e0a6bd24` | Frontend audit selected the existing comparison page as the smallest user journey |
| `task_1cfce860d755` | Design Gate initially rejected revision-lineage naming; neutral same-window strategy-change naming closed the finding |
| `task_6eff231bc9b1` | Implementation Gate PASS with no Blocker, High, or Medium; three Low minimality/test/copy findings were repaired |
| `task_0437c7c47517` | Focused re-Gate found one residual Low test-hardening gap; no production defect |
| `task_527c21f5a8e8` | Final focused re-Gate PASS with zero Blocker, High, Medium, or Low finding |

The review loop deliberately removed an unused public semantic field, strengthened the
truth-table and source-association tests, and corrected the Chinese label without adding
backend, persistence, roles, scoring, or workflow scope.

## 8. Acceptance decision and next boundary

Phase 1 Evidence-Guided Backtest Pair is accepted at the exact implementation SHAs above
with no unresolved Blocker, High, Medium, or Low finding inside its declared boundary.
All commits are local; no remote push, pull request, or merge is implied by this report.

No persisted split, optimizer, ranker, AI daemon, dynamic RuntimeInstance, formal Paper
Observation, Experiment UI, platform cutover, or Live trading is activated by this
acceptance.

The next bounded step is operational dogfood of the existing authoritative Backtest,
Lookahead Analysis, and Recursive Analysis routes using one explicit Futures-oriented
baseline/candidate protocol. That dogfood must record the exact data, strategy, context,
and scored-window evidence already available. Only observed gaps from that real journey
may justify a later persisted split/reveal contract or another implementation slice.
