# Phase 1 Backtest Revision Receipt Acceptance Report

**Acceptance date:** 2026-07-31

**Status:** accepted at exact implementation SHAs; local commits only; no subsequent
development slice activated

**Plan:**
[Phase 1 Experiment Revision Backtest](../plans/2026-07-31-phase1-experiment-revision-backtest.md)

## 1. Accepted outcome

The existing 8083/FreqUI standard Backtest journey now supports a bounded, pre-formal
provenance receipt:

1. an API 2.51-or-newer user supplies a validated stable Experiment ID;
2. the existing Freqtrade engine runs with result-cache reuse disabled;
3. the result metadata and retained history store a deterministic Backtest Revision
   Receipt;
4. result, selector, and history surfaces show the Experiment ID, receipt digest, and
   missing-DataSnapshot state;
5. API versions below 2.51 and legacy results retain their previous request and load
   behavior.

This slice does not create an Experiment ledger, a new backtest engine, a release,
RuntimeInstance, Paper Observation, scheduler, or Live authority.

## 2. Exact implementation identity

The accepted implementation Root is the parent of this documentation-only report
commit. The report does not claim that its own later Markdown changes were present in the
accepted implementation commit.

| Repository | Accepted implementation commit |
|---|---|
| Root | `f7f294c33681ab701a0f0effaef0c9015018f4dd` |
| Backend `freqtrade/` | `73a7431f2e51abd472d30aad0a36d234aec8fd0b` |
| Frontend `frequi/` | `3c0f0dbc6675ef5cf90c20b13641d69ca3a97a5f` |
| Strategies | `dbd5b0b21cfbf5ee80588d37458ace2467b7f8a4` |

All commits are local on branch
`xrunmasterx/phase1-experiment-revision-backtest`. This acceptance run did not push a
branch or create a pull request.

## 3. Evidence boundary

The accepted receipt binds:

- the caller-supplied Experiment ID;
- the native Freqtrade strategy/cache fingerprint;
- the validated Backtest request after effective `stake_amount` normalization and forced
  `backtest_cache: none`;
- the strategy name and Freqtrade engine version.

It deliberately stores `data_snapshot_id: null` and
`identity_scope: strategy_config_and_data_selection`. The native run ID and this receipt
do not hash the exact historical candle bytes. Consequently:

- the UI states that exact candle content is not captured;
- the result is not accepted as formally reproducible;
- the result is not eligible for Paper acceptance;
- two separate persisted result artifacts may legitimately share a receipt, so their
  in-memory identity also includes filename and strategy.

These meanings follow the shared [domain glossary](../../../CONTEXT.md). No chart source,
indicator, signal, crosshair, tooltip, or execution-marker behavior changed; the standing
[chart source contract](../../chart-data-source-rules.md) remains authoritative.

## 4. Backend acceptance

The backend adds one optional `experiment_id` request field and API version 2.51. When the
field is absent, no receipt is synthesized. When present, the implementation:

- validates the ID as 1-128 ASCII letters, digits, `.`, `_`, or `-`, starting with a
  letter or digit;
- removes the field before building the normal Backtesting config;
- forces cache policy `none` before Backtesting starts;
- normalizes equivalent accepted `stake_amount` forms against the effective config;
- attaches the receipt to normal strategy metadata before the normal result is stored;
- exposes the optional metadata through normal result history without breaking legacy
  entries.

Verified commands and results:

| Gate | Result |
|---|---:|
| Focused Backtest/history pytest selection | 3 passed, 107 deselected |
| Broader chart/Backtest/history/Lookahead/Recursive RPC selection | 15 passed, 95 deselected |
| Ruff check for RPC, backtest analysis/types, and RPC tests | passed |
| Focused Ruff format check | passed |

The focused test proves that numeric `100` and string `"100.0"` produce the same receipt,
that effective value `101` produces a different digest, that receipt-bound requests do
not call the result-cache lookup, that history retains the receipt, and that invalid IDs
return HTTP 422. The existing Starlette TestClient deprecation warning remained
non-failing.

## 5. Frontend acceptance

FreqUI capability-gates the new form and request behavior on API 2.51. The accepted UI:

- requires a valid Experiment ID before starting a receipt-bound backtest;
- sends the trimmed ID and `backtest_cache: none`;
- uses **Backtest revision receipt / 回测修订回执** consistently;
- displays the full digest and explicit DataSnapshot/formal-reproducibility/Paper
  boundary;
- marks legacy results as unbound;
- keeps two files with the same receipt independently loaded and unloadable;
- sends no new fields to API 2.50.

Verified commands and results:

| Gate | Result |
|---|---:|
| Focused Vitest suites | 2 files, 23 tests passed |
| `pnpm typecheck` | passed |
| Changed-file ESLint | zero errors |
| `pnpm build` | passed |
| Mocked Chromium Backtest journeys | 2 passed |
| Frontend `git diff --check` | passed |

The Chromium journey covers the API 2.51 request and receipt warning, retained history,
two artifacts sharing one receipt loading and unloading independently, a legacy history
row, and the API 2.50 request shape. The existing incomplete background-job mock emitted
non-failing `data is not iterable` console noise. Production build retained existing
third-party `@vueuse/core` pure-annotation warnings. Existing Prettier warnings outside
the changed hunks remained non-failing and were not expanded into unrelated cleanup.

## 6. Independent review

Orca orchestration provided read-only review provenance:

| Review | Decision |
|---|---|
| Initial Gate Review `task_46002e6b4e51` | Required canonical identity, artifact-aware keys, pre-formal terminology, and compatibility tests |
| Full re-review `task_2ca0a289c784` | All functional findings passed; one remaining user-facing terminology inconsistency |
| Narrow re-review `task_efaeb5abc783` | PASS; no actionable findings |

The final reviewer confirmed canonicalization, cache bypass, persistence, credential
containment, artifact-aware keys, duplicate load/unload behavior, legacy compatibility,
pre-2.51 request shape, visible evidence limits, minimal scope, and named verification
coverage. Review workers modified no files.

## 7. Safety and compatibility

- The persisted request comes from the Backtest API schema rather than the operational
  config, so exchange credentials and unrelated secret-bearing config are not copied
  into the receipt.
- No Docker service, public exchange read, credential display, Live environment, real
  order, exchange write, listener change, runtime migration, or destructive state action
  was used.
- 8081 remains only the existing preconfigured compatibility Runtime and is outside this
  receipt flow.
- The accepted implementation remains on the standard Freqtrade Backtesting engine and
  existing FreqUI Backtest surface.

## 8. Acceptance decision and next boundary

The bounded Backtest Revision Receipt slice is accepted at the exact implementation SHAs
above. There is no unresolved finding within its stated contract.

No next implementation begins automatically. The recommended next correctness decision
is a separate, smallest-possible slice that content-addresses exact offline candle inputs
as a `DataSnapshot` and fails closed when content is absent or changed. Until that slice
and trusted artifact/environment binding are accepted, this project must not call these
backtests formally reproducible or use them as governed Paper evidence. Dynamic Runtime,
Paper Observation, Live trading, and exchange-write work remain paused.
