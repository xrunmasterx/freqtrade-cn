# Phase 1 Backtest Strategy Evidence Binding Plan

**Status:** active

**Branch:** `xrunmasterx/phase1-complete-development`

**Base acceptance:**
[Backtest Artifact Secret Redaction](../reports/2026-07-31-backtest-artifact-secret-redaction-acceptance.md)

**Identity decision:**
[Captured primary source and resolved parameters](../decisions/2026-07-31-backtest-strategy-evidence-boundary.md)

## 1. User outcome

Keep the existing authoritative 8083 Backtest journey. A researcher starting a
revision-bound Backtest on API 2.53 can see whether the result binds the same primary
strategy source and resolved Freqtrade parameters as another result. The result,
history, loaded-result selector, and comparison view report strategy evidence as same,
different, or unknown independently of DataSnapshot equality.

This closes the concrete concurrent-edit failure in which an AI or user changes a
strategy during a long Backtest and the executed class, Freqtrade Run ID, or archived
source/parameter member describes different file contents. It does not create a release
system or claim complete reproducibility, Paper eligibility, or future profit.

## 2. Assumptions and scope

- Freqtrade remains the sole Backtest engine and the current API journey runs one strategy
  at a time.
- API 2.53 adds `capture_strategy_evidence: true`. It requires an Experiment ID and is
  sent automatically by updated FreqUI when revision binding is available. Omission keeps
  API 2.52/2.51 and legacy behavior.
- Backtest Strategy Evidence is an optional, independently versioned field on the existing
  schema-1/schema-2 receipt. Data identity and strategy identity remain orthogonal.
- Primary source means the exact bytes compiled by `StrategyResolver` for the module that
  defines the selected strategy class. Imported base/helper modules are outside v1.
- Resolved parameters mean all final enumerated Freqtrade `BaseParameter` values plus
  effective ROI, stoploss, trailing, and max-open-trades values, captured after
  `ft_bot_start` and before indicator evaluation.
- The sidecar/receipt contains identities and scopes, not source text, local paths, or
  parameter values. The ZIP retains captured source, preserves an optional load-time
  parameter-file member, and adds a canonical resolved-evidence member.
- FreqAI may bind this narrow source/parameter evidence, but its model, training data, and
  predictions remain explicitly unbound.

## 3. Evidence contract

Evidence schema 1 contains:

| Field | Meaning |
|---|---|
| `schema_version` | Strategy-evidence manifest schema, initially `1` |
| `canonicalization` | `freqtrade-backtest-strategy-evidence-v1` |
| `hash_algorithm` | `sha256` |
| `strategy` | Selected strategy class name |
| `source_scope` | `primary_strategy_module` |
| `parameter_scope` | `resolved_freqtrade_strategy_parameters_v1` |
| `source_digest` | `strategy-source-` plus the exact captured source SHA-256 |
| `parameters_digest` | `strategy-parameters-` plus the exact canonical parameter-member SHA-256 |
| `evidence_id` | `strategy-evidence-` plus a domain-separated manifest SHA-256 |

Canonical parameter output is deterministic JSON using sorted object keys and finite JSON
primitive values. Unsupported or non-finite values fail capture rather than falling back
to stringification. The evidence ID binds the class name, scopes, canonicalization, and
both component digests; the Backtest revision ID in turn binds the complete evidence
submanifest.

The manifest proves equality of the captured components when the receipt is trusted. It
does not make the metadata/ZIP tamper-resistant: an actor able to rewrite both can still
forge both.

## 4. Capture and persistence sequence

1. Validate the Experiment ID and optional strategy-evidence capture request; revision-
   bound runs continue to bypass result-cache reuse. Core capture mode also refuses prior-
   result reuse so a multi-strategy export cannot mix cached results with missing evidence.
2. Read the primary module once at the resolver boundary, compile those same bytes, and
   retain them on the loaded strategy. Do not call `inspect.getsource` or reread the path
   to establish evidence.
3. After `ft_bot_start` resolves final strategy parameters and before
   `advise_all_indicators`, canonicalize parameters and seal the evidence/artifact.
4. Execute the normal Freqtrade Backtest.
5. Bind the evidence submanifest into the existing revision payload alongside either the
   schema-1 data-selection state or schema-2 DataSnapshot state.
6. Persist the normal metadata sidecar/history contract. When exporting trades, write the
   retained source bytes to the existing source member, a load-time semantic snapshot to
   the existing optional parameter member, and the resolved payload to a new
   `<backtest-result-stem>_<strategy>_evidence.json` member; never reread mutable strategy
   files.
7. If requested evidence is missing or cannot be canonicalized, fail the background job
   before storing a bound receipt or artifact.

Freqtrade Run ID will use the resolver-captured source rather than a later path read, but
its SHA-1 algorithm and native cache-fingerprint meaning remain unchanged.

## 5. User-visible states

- **Bound:** show full evidence/source/parameter IDs in result details and a compact,
  accessible evidence suffix in history and selectors.
- **Unknown:** any legacy receipt, omitted capture, or malformed/missing evidence remains
  loadable but is never inferred from strategy name, Run ID, filename, or current code.
- **Comparison:** fewer than two results or any unknown evidence is unknown; otherwise one
  unique evidence ID is same and multiple IDs are different. Keep this banner separate
  from the existing same/different/unknown DataSnapshot banner.

The result also labels the existing Freqtrade Run ID and engine version without claiming
they are Environment Identity. Visible warnings state that imported code, arbitrary I/O,
environment, artifact authenticity/replay, Paper acceptance, and future profit are not
proven.

## 6. Test-first acceptance

### Backend

- Resolver capture compiles and retains one source byte sequence; later file mutation or
  deletion cannot change the captured source, Run ID, evidence digest, or ZIP member.
- Evidence is deterministic across parameter discovery order; a source-only or effective-
  parameter-only change changes the appropriate component and aggregate identity.
- Parameter precedence/defaults, values created in `bot_start`, `load=False`, special
  settings, non-finite values, and unsupported values are covered explicitly.
- API 2.53 advertises the capability; capture requires Experiment ID, keeps cache bypass,
  persists identical receipt evidence through result/history/result-load, and fails closed
  when capture is unavailable.
- Receipt schema 1 and 2 accept valid optional evidence and remain compatible without it;
  malformed prefixes/scopes or an invalid aggregate digest are rejected.
- ZIP tests prove captured in-memory source/load-time-parameter/resolved-evidence payloads
  win over later disk edits, preserve existing member names, and keep the legacy
  storage-call contract compatible.
- Receipt and sidecar contain no source, path, raw parameter payload, or credential.

### Frontend

- API 2.53 sends strategy-evidence capture automatically; pre-2.53 request shapes stay
  unchanged, and FreqAI wording keeps model/data limits explicit.
- Strict helpers validate evidence and derive same/different/unknown without Run-ID or
  name fallback.
- Result, history, selector, and comparison render localized, accessible bound/unknown
  states and full identity details where appropriate.
- Existing DataSnapshot comparison and duplicate-artifact keying remain unchanged.
- Focused Vitest, localization parity, typecheck, build, and the mocked Backtest Chromium
  journey pass.

### Verification commands

```powershell
# backend
& 'G:\AI_Trading\freqtrade-cn\freqtrade\.venv\Scripts\python.exe' -m pytest `
  tests/strategy/test_strategy_loading.py tests/plugins/test_pairlist.py `
  tests/optimize/test_backtest_strategy_evidence.py tests/optimize/test_backtesting.py `
  tests/optimize/test_optimize_reports.py tests/rpc/test_backtest_data_snapshot_schema.py `
  tests/rpc/test_rpc_apiserver.py -q -k "not test_api_freqaimodels" -p no:cacheprovider
& 'G:\AI_Trading\freqtrade-cn\freqtrade\.venv\Scripts\python.exe' -m ruff check `
  freqtrade/resolvers freqtrade/optimize freqtrade/rpc tests/strategy tests/optimize tests/rpc

# frontend
pnpm vitest run tests/unit/backtestRevision.spec.ts tests/unit/appI18n.spec.ts
pnpm typecheck
pnpm build
pnpm exec eslint --no-fix --quiet `
  e2e/backtest.spec.ts `
  src/components/ftbot/BacktestHistoryLoad.vue `
  src/components/ftbot/BacktestResultAnalysis.vue `
  src/components/ftbot/BacktestResultComparison.vue `
  src/components/ftbot/BacktestResultSelectEntry.vue `
  src/components/ftbot/BacktestRun.vue src/locales/en.ts src/locales/zh-CN.ts `
  src/types/backtest.ts src/types/features.ts src/utils/backtestResultKey.ts `
  tests/unit/appI18n.spec.ts tests/unit/backtestRevision.spec.ts
pnpm exec playwright test e2e/backtest.spec.ts --project=chromium
pnpm exec playwright test e2e/backtest.spec.ts --project=msedge
```

### Pre-commit validation evidence (2026-07-31)

- Backend acceptance suite: `619 passed, 1 deselected, 1 warning`; the deselected
  `test_api_freqaimodels` collection requires the optional `datasieve` dependency absent
  from the shared virtual environment. The warning is the existing Starlette TestClient
  deprecation warning. Ruff and `git diff --check` pass.
- Frontend focused unit suite: `25 passed`; typecheck and production build pass. The
  changed-file ESLint command exits successfully with zero errors; Windows CRLF/Prettier
  warnings remain non-failing and are not bulk-formatted in this bounded change.
- Fully mocked Backtest browser acceptance: `5 passed` in Chromium and `5 passed` in
  installed Microsoft Edge. Firefox and WebKit executables are not installed locally.
- The build retains the existing third-party `@vueuse/core` pure-annotation warning and
  reports the entry chunk just over the configured 700 kB warning threshold. Mocked E2E
  startup retains the existing non-failing `recoverBgJobs` console noise.
- The independent backend, frontend, and minimality/documentation Gate decisions are
  PASS. Exact commit SHAs and the acceptance report remain intentionally pending until
  the submodule and root implementation commits exist.

An independent final Gate Review must inspect exact execute/capture equivalence,
parameter completeness and precedence, canonical identity, TOCTOU closure, legacy/API
compatibility, failure behavior, privacy, artifact consistency, UI claims, and accidental
expansion into StrategyRelease, Environment, Runtime, Paper, or Live scope.

## 7. Explicit non-goals

- no StrategyRelease, promotion/approval, CAS/object store, signing, encryption, or source
  and parameter browser;
- no transitive import/dependency closure, FreqAI model identity, arbitrary strategy file,
  network, environment-variable, or mutable runtime-state capture;
- no Environment Identity, data-payload retention/replay, result-artifact trust redesign,
  Experiment CRUD/UI, BotRelease, RuntimeInstance, Paper, Live, or exchange writes;
- no cache-key redesign, new Backtest engine, new comparison API, database, endpoint, or
  chart/indicator/signal work;
- no claim that equal evidence implies equal results, Paper eligibility, or profitability.

## 8. Implementation checklist

- [x] Add failing resolver/evidence/canonicalization/storage/API schema tests.
- [x] Capture and execute the same primary source bytes.
- [x] Capture final supported parameters and build the versioned evidence/artifact.
- [x] Bind/persist evidence and eliminate requested-capture ZIP rereads.
- [x] Add API 2.53 capability and strict legacy-compatible schemas.
- [x] Add result/history/selector/comparison UI and localization.
- [x] Run focused and broader regressions plus mocked browser acceptance.
- [ ] Complete independent Gate Review and exact-SHA acceptance report.
