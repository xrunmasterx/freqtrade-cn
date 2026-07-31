# Phase 1 Backtest Strategy Evidence Binding Acceptance Report

**Acceptance date:** 2026-07-31

**Status:** accepted at exact implementation SHAs; local commits only; no subsequent
implementation slice activated by this report

**Branch:** `xrunmasterx/phase1-complete-development`

**Worktree:**
`C:\Users\dezhengu\orca\workspaces\freqtrade-cn\phase1-complete-development`

**Plan:**
[Phase 1 Backtest Strategy Evidence Binding](../plans/2026-07-31-phase1-backtest-strategy-evidence-binding.md)

**Decision:**
[Captured primary source and resolved parameters](../decisions/2026-07-31-backtest-strategy-evidence-boundary.md)

**Security prerequisite:**
[Backtest Artifact Secret Redaction](2026-07-31-backtest-artifact-secret-redaction-acceptance.md)

## 1. Exact implementation identity

| Repository | Exact accepted implementation SHA |
|---|---|
| Root | `091a797a339381477f18149e4487b2093f42ce90` |
| `freqtrade/` backend | `d254eed9642d798aabc7334cc1e70a7af305bf61` |
| `frequi/` frontend | `29097e95beaa00a6b522c7e33a01f5eff54aa5bd` |
| `freqtrade-strategies/` | `dbd5b0b21cfbf5ee80588d37458ace2467b7f8a4` (unchanged) |

The Root implementation commit records the exact backend and frontend submodule
pointers. This acceptance document is a later documentation-only commit and does not
change the accepted implementation identity.

## 2. Accepted user outcome

The existing authoritative Freqtrade Backtest journey now lets a local researcher tell
whether two revision-bound results captured the same supported strategy evidence,
independently of whether their DataSnapshot identities match.

For API 2.53, FreqUI requests `capture_strategy_evidence: true` when the capability is
advertised. Result details, history, the loaded-result selector, and comparison view show
strategy evidence as bound, same, different, or unknown. Unknown legacy or malformed
evidence is never inferred from a display name, filename, or Freqtrade Run ID.

This acceptance preserves the existing journey and engine. It does not add an editor,
StrategyRelease registry, CAS, Experiment CRUD, RuntimeInstance, Paper workflow, or a
second Backtest engine.

## 3. Evidence boundary accepted

The implementation closes the mutable-file race at the source boundary:

1. `StrategyResolver` reads the defining primary module bytes, compiles those same
   bytes, and restores the captured value after custom strategy construction.
2. `Backtesting` seals an engine-owned copy before strategy lifecycle callbacks. When
   the API replaces the constructor-loaded strategy with its execution strategy, the
   strategy list and sealed source map are replaced together.
3. The native Freqtrade Run ID, receipt evidence, and exported ZIP source member receive
   the same sealed bytes explicitly; they do not reread the mutable path.
4. After `ft_bot_start` and before indicator evaluation, the engine canonicalizes all
   enumerated Freqtrade `BaseParameter` values plus effective ROI, stoploss,
   max-open-trades, and trailing settings.
5. Unsupported or non-finite evidence values fail capture. Canonical payload and
   domain-separated SHA-256 identities are validated by both backend schemas and the
   frontend comparison helper.
6. Capture mode bypasses prior-result reuse and rejects incomplete strategy-artifact
   maps before writing any bound artifact.

The evidence schema identifies only `primary_strategy_module` and
`resolved_freqtrade_strategy_parameters_v1`. Imported helpers, transitive dependencies,
FreqAI model/training/prediction content, arbitrary strategy I/O, environment identity,
artifact authenticity, and retained replay payloads are not included.

## 4. Compatibility and persistence

The accepted request matrix is:

| Server capability | Standard Backtest | FreqAI Backtest |
|---|---|---|
| API 2.53 | DataSnapshot plus strategy evidence | strategy evidence only; model/data/predictions explicitly unbound |
| API 2.52 | DataSnapshot only | revision receipt only |
| API 2.51 | revision receipt only | revision receipt only |
| pre-2.51 | unchanged legacy request | unchanged legacy request |

Receipt schema 1 and schema 2 accept the optional evidence submanifest while remaining
compatible without it. History and result loading retain the exact receipt. When trade
export is enabled, the ZIP contains the same captured source, the optional canonical
load-time parameter-file snapshot, and
`<backtest-result-stem>_<strategy>_evidence.json` for the resolved parameter payload.

The evidence and outer revision identities are deterministic correlation evidence, not
a signature. An actor who can rewrite both artifact and metadata can still forge them.

## 5. Verification evidence

### Backend

The bounded acceptance command covered strategy loading, PairList compatibility,
canonical evidence, Backtesting, result storage, receipt schemas, and the Backtest API:

```powershell
& 'G:\AI_Trading\freqtrade-cn\freqtrade\.venv\Scripts\python.exe' -m pytest `
  tests/strategy/test_strategy_loading.py tests/plugins/test_pairlist.py `
  tests/optimize/test_backtest_strategy_evidence.py tests/optimize/test_backtesting.py `
  tests/optimize/test_optimize_reports.py tests/rpc/test_backtest_data_snapshot_schema.py `
  tests/rpc/test_rpc_apiserver.py -q -k "not test_api_freqaimodels" -p no:cacheprovider
```

Result: `619 passed, 1 deselected, 1 warning`. The single deselection is the optional
`test_api_freqaimodels` path because the shared virtual environment lacks `datasieve`.
The warning is the existing Starlette TestClient deprecation warning. Ruff over all
touched backend source/tests and backend/Root `git diff --check` passed.

The final API regression forces two same-name strategy loads with different captured
source buffers. It proves that the first object actually executes and that its exact
bytes drive the Run ID, receipt source digest, and ZIP source member.

### Frontend

| Check | Result |
|---|---:|
| Focused Vitest (`backtestRevision` and localization parity) | 25 passed |
| `pnpm typecheck` | passed |
| `pnpm build` | passed |
| Exact changed-file ESLint with `--no-fix --quiet` | passed; zero errors |
| Mocked Chromium Backtest journeys | 5 passed |
| Mocked installed Microsoft Edge Backtest journeys | 5 passed |

The five journeys cover API 2.53 standard capture, API 2.53 FreqAI strategy-only
capture, API 2.52 data-only capture, API 2.51 receipt-only behavior, and pre-2.51 legacy
behavior.

The Playwright Firefox and WebKit projects could not start because the browser revisions
required by the installed Playwright package were unavailable locally. Stale cache
directories for other revisions do not satisfy that requirement, and no browser package
was installed as part of this bounded acceptance.

Non-failing environment noise was retained rather than expanded into adjacent cleanup:

- Windows CRLF/Prettier warnings from changed-file ESLint;
- the existing third-party `@vueuse/core` pure-annotation build warning;
- an entry-chunk size warning just above the configured 700 kB threshold;
- mocked E2E `recoverBgJobs` console noise caused by the intentionally narrow fixtures.

## 6. Orchestrated review and fixes

Orca orchestration tracked independent, read-only backend, frontend, and
minimality/documentation reviews. Review workers changed no files.

| Task | Result |
|---|---|
| `task_221f4ca27ac0` / `task_ad7af1cbe1c9` | Found mutable source ownership, capture-cache completeness, and the API double-load execution/evidence race; all were fixed with RED regressions |
| `task_ecec7d460a5e` | Final backend re-review PASS; no Blocker, High, or Medium finding |
| `task_22a32028f154` | Found missing client aggregate recomputation, misleading unknown labels/copy, and missing API 2.52 browser coverage; all were fixed |
| `task_a9534712af0e` | Final frontend re-review PASS; no Blocker, High, or Medium finding |
| `task_f7db29788b16` | Found an over-broad resolver path, receipt strategy mismatch, and inaccurate command/member documentation; all were fixed |
| `task_e35598cbf934` / `task_984d7f3ba12c` | Minimality and documentation closure PASS after independently confirming the final evidence |

The reviews materially kept the slice smaller: no release model or environment capture
was added, while the exact execute/capture invariant and strict unknown semantics were
made stronger.

## 7. Safety, privacy, and non-goals

- No Docker service, database, exchange account, order path, Paper runtime, Live runtime,
  or external operational system was mutated.
- No credential, strategy source, raw resolved-parameter payload, or local path is placed
  in the receipt or history metadata.
- No StrategyRelease, BotRelease, RuntimeInstance, signing, encryption, CAS, promotion,
  approval, snapshot browser, payload-retention service, or Environment Identity was
  created.
- Equal evidence means only that the captured v1 source/parameter components match. It
  does not prove equal results, complete reproducibility, Paper eligibility, or future
  profitability.
- This slice did not change chart indicators, signals, trade overlays, Lookahead
  Analysis, Recursive Analysis, or compatibility runtime behavior.

## 8. Historical artifact exposure remains open

The preceding security acceptance found 191 parseable local Backtest ZIPs, including
184 with non-placeholder API-session secrets. This work did not display, copy, rewrite,
delete, quarantine, rotate, or revoke any of them. They remain an operational exposure
until service-specific retention and credential-rotation actions are explicitly
authorized and completed.

## 9. Acceptance decision and next boundary

Phase 1 Backtest Strategy Evidence Binding is accepted at the exact implementation SHAs
above with no unresolved Blocker, High, or Medium finding inside its contract.

No next implementation plan becomes active automatically. The next explicit decision
should choose one bounded offline evidence gap: retained DataSnapshot payload/replay or
Environment Identity. Dynamic RuntimeInstance and formal Paper Observation work remain
paused until the user separately selects that journey.
