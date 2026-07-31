# Phase 1 Evidence-Guided Backtest Pair

**Status:** Completed

**Decision authority:**
[Backtest Pair Interpretation Boundary](../decisions/2026-07-31-backtest-pair-interpretation-boundary.md)

## Assumptions and tradeoffs

- The accepted DataSnapshot, Strategy Evidence v2, and Execution Context Evidence v1
  validators remain the only identity authorities.
- `StrategyBacktestResult.backtest_start_ts` and `backtest_end_ts` are the effective
  scored-window timestamps used for this UI interpretation. Request timerange strings
  and optional history timestamps are not substitutes.
- Exactly two loaded results are required. This avoids inventing roles, pair selection,
  or a matrix UI.
- A neutral interpretation card is more useful than documentation alone, but a persisted
  holdout workflow would be premature.

## Scope

Frontend only:

- one pure pair classifier beside the existing Backtest identity helpers;
- one neutral interpretation and scored-window block in the existing comparison page;
- English and Chinese locale text;
- focused utility, component, and locale tests;
- governing status/documentation updates after acceptance.

No backend, API, schema, database, store, route, chart, scoring rule, threshold, ranking,
optimizer, Paper, or Runtime work is included.

## Execution

1. Add RED truth-table tests for cardinality, both supported interpretations, overlap,
   confounding, malformed identities, and invalid timestamps.
2. Implement the smallest fail-closed classifier and make the focused utility tests
   green.
3. Add the existing-page interpretation block, window rows, neutral copy, and a focused
   component test; keep the three evidence cards and metric table intact.
4. Run focused Vitest, locale tests, typecheck, build, changed-file ESLint, and
   `git diff --check`.
5. Complete an independent Gate review, record exact SHAs, commit the FreqUI submodule
   first, then commit the root pointer and documentation.

## Acceptance

- A same-data, different-strategy-evidence, same-context, exactly same-window pair is
  labeled only as a same-window strategy-change review.
- A different-data, same-strategy-evidence, same-context, strictly disjoint-window pair
  is labeled only as a cross-window review.
- Unknown evidence or invalid windows fail to `unknown`; all other known combinations
  fail to `not_comparable`.
- Reversing the two results does not change the classification.
- A shared endpoint is overlap.
- No pair block renders unless exactly two results are loaded.
- The UI makes no winner, improvement, untouched-window, robustness, Paper, or future
  performance claim.
