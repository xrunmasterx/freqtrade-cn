# Phase 1 Backtest Execution Context Evidence Plan

**Status:** active; implementation complete, exact-SHA acceptance pending

**Branch:** `xrunmasterx/phase1-complete-development`

**Base acceptance:**
[Phase 1 Retained DataSnapshot Replay](../reports/2026-07-31-phase1-retained-data-snapshot-replay-acceptance.md)

**Boundary decision:**
[Bounded Backtest execution-context evidence](../decisions/2026-07-31-backtest-execution-context-evidence-boundary.md)

## 1. User outcome

Keep the existing authoritative 8083 Backtest journey. A researcher comparing a retained-
data baseline with a candidate can see whether the core runtime versions, effective
simulation configuration, and admitted-pair exchange simulation facts matched within the
declared v1 scope.

The comparison answers one actionable question:

> May this metric delta remain eligible for attribution to the intended strategy change,
> or is it confounded by changed or unknown execution context?

`DIFFERENT` or `UNKNOWN` is ineligible for attribution, ranking, learning, or promotion as
strategy improvement. `SAME CAPTURED SCOPE` only makes the pair eligible for later
robustness/holdout analysis; it does not prove causal improvement, equal results, contract-
trading safety, or future profit.

## 2. Assumptions and scope

- Freqtrade remains the sole Backtest authority; no second engine or comparison endpoint
  is added.
- API 2.55 adds `capture_execution_context_evidence: true`. Updated FreqUI sends it
  automatically for non-FreqAI revision-bound runs; server admission rejects unsupported
  modes with stable, user-visible errors.
- Retention and replay force current execution-context capture server-side, matching their
  existing forced DataSnapshot and strategy-evidence boundaries. Context capture also
  server-forces Strategy Evidence v2.
- V1 covers static-PairList Spot and Futures only. `enable_dynamic_pairlist=true` fails
  admission with `execution_context_evidence_dynamic_pairlist_unsupported`; FreqAI and
  Margin are also outside v1.
- Futures Cross Margin admits scalar `dry_run_wallet`, or object form containing at most
  the engine's effective proxy currency. Any other currency fails before wallet
  construction; v1 does not snapshot mutable conversion tickers or rates.
- The one initial free balance for that effective proxy currency is bound from the
  already-constructed Backtest `Wallets`; this preserves the real
  `available_capital` stake clamp without persisting the raw wallet map.
- V1 serializes only values already loaded by the current Backtesting instance and adds no
  exchange call, market reload, optional-module import, package scan, or external service.
- Spot serializes `margin_mode: null`. Futures binds the exact dry-run liquidation taker
  rate only for the base and Bitget formulas that consume it; Binance, Bybit, and
  Hyperliquid serialize `null`.
- The field is optional on the existing schema-1/schema-2 receipt. Older clients and
  results remain valid and report context `UNKNOWN`.
- FreqAI remains outside v1 because model, feature, training-data, and prediction identity
  are not bound.
- Only component scopes and IDs are persisted. Canonical component payloads are generated
  from positive allowlists in memory and discarded after hashing.
- Evidence is self-reported correlation metadata, not signature, attestation, complete
  Environment Identity, dependency closure, or restoration authority.

## 3. Evidence contract

The receipt field `execution_context_evidence` contains:

| Field | Required value |
|---|---|
| `schema_version` | `1` |
| `canonicalization` | `freqtrade-backtest-execution-context-evidence-v1` |
| `hash_algorithm` | `sha256` |
| `core_runtime_scope` | `freqtrade_python_numeric_exchange_versions_v1` |
| `effective_config_scope` | `standard_backtest_effective_config_v1` |
| `exchange_simulation_scope` | `admitted_pair_exchange_simulation_v1` |
| `core_runtime_id` | `core-runtime-` plus 64 lowercase hex |
| `effective_config_id` | `effective-config-` plus 64 lowercase hex |
| `exchange_simulation_id` | `exchange-simulation-` plus 64 lowercase hex |
| `evidence_id` | `execution-context-evidence-` plus 64 lowercase hex |

The aggregate ID binds every preceding manifest field. Backend and frontend validation use
exact literals, prefixes, and recomputed aggregate identity; extra or missing keys fail
schema validation. The writer includes the manifest when deriving `revision_id`, but
current read paths do not recompute the outer ID, so this plan makes no read-side outer-
binding or integrity claim.

### Normative payloads and ownership

The ADR's
[normative v1 identity contract](../decisions/2026-07-31-backtest-execution-context-evidence-boundary.md#appendix-a-normative-v1-identity-contract)
defines every serialized key, in-memory source, type, null/default behavior, Spot/Futures
rule, order rule, bound, and digest domain byte. Implementation may not infer extra fields
from the category names.

The ADR's
[normative Strategy Evidence v2 contract](../decisions/2026-07-31-backtest-execution-context-evidence-boundary.md#appendix-b-normative-strategy-evidence-v2-contract)
likewise defines the exact v2 manifest, parameter-payload nesting, setting sources and
types, post-`ft_bot_start`/protection lifecycle, digest domains, and v1 compatibility.

The ownership partition is:

1. **DataSnapshot:** admitted standard route metadata and exact rows.
2. **Strategy Evidence v2:** primary source, named hyperopt parameters, and every exact
   Freqtrade-resolved strategy execution setting listed in the ADR.
3. **Execution context:** fixed runtime versions, static evaluated-pair order, external
   fee/capital/protection/position/reserve/Futures controls, and loaded admitted-pair
   exchange facts.

Execution context contains no strategy-resolved value. Existing Strategy Evidence v1 is
loadable, but every new context-bound receipt must carry
`resolved_freqtrade_strategy_parameters_v2`. Market entries sort by pair; evaluated-pair
order and parsed leverage-tier order remain semantic and are preserved. Every numeric
value is finite, bool is not a number, and fallback stringification is forbidden.

## 4. Capture and binding sequence

1. Validate Experiment ID, capability, non-FreqAI scope, Spot/Futures mode, static
   PairList, and forced retention/replay semantics before scheduling the job.
2. Force a fresh Backtesting instance and disable prior-result reuse whenever capture is
   requested; force Strategy Evidence v2 in the effective request.
3. After the engine resolves its execution Exchange but before constructing `Wallets`,
   resolve and retain `exchange.get_proxy_coin()`. If Futures Cross Margin uses an object
   `dry_run_wallet` containing any other currency, fail with
   `execution_context_evidence_cross_margin_wallet_conversion_unsupported`. Do not call
   `get_conversion_rate()` or `get_tickers()`.
4. Let the normal engine initialize the admitted wallet and load standard data.
5. Both `Backtesting.start()` and the active API `__run_backtest_bg` path call the same
   engine-owned, single-assignment `seal_execution_context(data)` immediately after their
   `load_bt_data()` returns. It seals `list(data.keys())` and the existing Exchange before
   `load_prior_backtest`, `_set_strategy`, `ft_bot_start`, or indicator evaluation. For
   the base and Bitget Futures formulas, this also freezes the already-loaded
   per-pair liquidation taker rate through the same helper later consumed by simulation;
   it performs no exchange request. The seal also reads the already-constructed Wallets'
   initial free balance for the once-resolved proxy currency.
6. Run the normal Backtest. Strategy Evidence v2 takes its pending post-`ft_bot_start`
   snapshot before indicators and finalizes with literal `[]`, or with the one exact
   protection list evaluated and passed to `ProtectionManager` at the existing protection
   lifecycle point. Then finalize DataSnapshot/replay.
7. Retrieve only the engine-owned sealed context and finalized v2 strategy artifact; API
   binding must not reconstruct, reread, reload, query, or fill either artifact.
8. Bind both submanifests into the revision and persist them through the existing metadata
   sidecar, result API, and history API. Reject a context-bound receipt containing v1
   strategy evidence.
9. Publish every context-bound export using ZIP-first temporary creation/verification,
   final ZIP replacement, then atomic metadata and latest-pointer replacement. Apply this
   to ordinary capture, replay without re-retention, and retained replay.
10. If requested capture, archive creation/replacement, sidecar publication, or latest-
   pointer publication fails, leave no new bound result/sidecar/ZIP and preserve the prior
   latest pointer.

## 5. User-visible states

- **Bound detail:** show the full aggregate and three component IDs plus the declared v1
  scope. State that the evidence is partial and self-reported.
- **History/selector:** show a compact context suffix or `Unknown`; include valid IDs in
  history search.
- **Comparison:** add one independent overall context card and component breakdown beside
  DataSnapshot and Strategy Evidence.
- **Same captured scope:** explain that listed components matched but equal results,
  causality, robustness, authenticity, Paper eligibility, contract safety, and profit are
  unproven.
- **Different:** explain that metrics may include context drift and must not be attributed
  only to strategy or data.
- **Unknown:** explain that at least one result lacks valid evidence; engine version, Run
  ID, current installation, filename, Experiment ID, or equal profit is not a fallback.
- **Replay:** retain the warning that rows are restored but the source environment is not;
  compare the new run's captured context separately.
- **Unsupported dynamic mode:** preserve the completed Backtest form and show that v1
  requires `enable_dynamic_pairlist=false`; do not silently downgrade to `UNKNOWN`.

There is no capture checkbox, environment picker, dashboard, restore action, or aggregate
“reproducible” badge.

## 6. Test-first acceptance

### Backend RED-to-GREEN

- Pure builder tests independently recompute each component ID while its payload is in
  memory and recompute the persisted aggregate ID.
- Mutating each included runtime/config/exchange/tier field changes only its component and
  aggregate ID. Changing source-map insertion order does not; reversing evaluated-pair or
  leverage-tier order does.
- Credentials, unknown nested config, paths, raw market `info`, unrelated markets,
  timestamps, export/notes/logging, Docker/Runtime metadata, and other exclusions do not
  change IDs and never appear in serialized evidence.
- NaN, infinities, bool numerics, malformed types, duplicate evaluated pairs, missing
  markets/dependency versions, over-bound payloads, and capture failure fail closed.
  Duplicate tier rows are preserved positionally rather than silently deduplicated.
- Strategy Evidence v2 independently recomputes its domain-separated parameter and
  aggregate IDs. A mutation test covers every owned setting, including `use_custom_roi`
  and enabled/disabled `protections`; mutating one owned setting never changes execution
  context unless an independently owned context input also changes.
- Fixed-map tests cover every allowed `order_types`, `order_time_in_force`, and
  `unfilledtimeout` key and literal. Decimal `max_open_trades`,
  `ignore_buying_expired_candle_after`, and `max_entry_position_adjustment` remain
  schema-compatible finite numbers; bool, NaN, and infinities fail.
- V2 lifecycle tests prove `bot_start` mutations are captured, hyperopt values are loaded,
  disabled protections serialize `[]`, an enabled `protections` property is evaluated
  exactly once, and the identical validated list is supplied to `ProtectionManager`.
  Every allowed field of all four built-in methods is covered. Unknown setting keys,
  protection methods, and protection keys fail with their stable errors before artifact
  creation. A context-bound result cannot bind v1 evidence. Exact v1 fixtures remain
  loadable.
- Dynamic-PairList admission tests include candle-frequency `ShuffleFilter` with no seed
  and prove no receipt can report a captured context for an unbound later pair order.
- Engine ownership tests prove both CLI and the currently active API background path call
  the single-assignment seal exactly once with the execution Exchange and exact
  `list(data.keys())`, after their data load and before prior reuse/strategy callbacks.
  A second requested seal fails. The builder performs no lazy-market access, reload,
  fetch, second Exchange, optional-module import, or package enumeration.
- Futures Cross Margin admission covers scalar wallet, proxy-only object, overridden
  Binance proxy currency, and multi-currency rejection. Rejection happens before
  `Wallets(...)`; spies prove no `get_conversion_rate()` or `get_tickers()` call. Changing
  the admitted proxy currency changes only effective-config and aggregate IDs.
- Holding `available_capital` constant while moving the proxy-currency `dry_run_wallet`
  below and above the engine's stake-clamp boundary changes only effective-config and
  aggregate IDs. The captured finite value equals `Wallets.get_free(proxy_currency)` at
  the seal point; no raw wallet map or non-proxy amount is serialized.
- Spot verifies `margin_mode: null`. Futures tests cover base/Bitget finite
  `liquidation_taker_rate`, Binance/Bybit/Hyperliquid `null`, market-rate and local
  `describe()` fallback paths, and an undeclared formula override failing closed. The
  context builder and later formula consume the same frozen value; spies prove no network
  call or lazy `markets` access.
- Requested capture forces fresh Backtesting and prior-cache bypass. API binding consumes
  the sealed evidence rather than rebuilding it.
- API 2.55 is advertised; capture requires Experiment ID; omission preserves compatibility;
  every newly captured strategy artifact is v2, and context/retention/replay force its
  effective capture flag and evidence.
- Schema-1/schema-2/legacy results without evidence remain valid. Invalid literals,
  prefixes, extra fields, and aggregate mismatch are rejected.
- Replay tests hold DataSnapshot/strategy evidence constant and vary fee, precision,
  limits/options/tiers, dependency version, or pair order to prove context changes are
  detected without restoring current context.
- Archive-write, ZIP-replace, sidecar-write, and latest-pointer-write fault injection pass
  for ordinary capture, replay without re-retention, and retained capture; no partial
  publication or prior-latest corruption remains.
- Real ZIP/sidecar/history/API privacy sentinels pass. A sentinel secret placed in an
  unknown order-setting or protection field makes capture fail and appears in no staged or
  final ZIP byte. Receipt load validates aggregate identity only and does not claim
  component-payload or outer-revision recomputation.

### Performance/resource Gate

- Enforce the ADR limits: at most 1,000 evaluated pairs, 50,000 total parsed tiers, and
  16 MiB combined canonical component bytes.
- Prove construction is `O(pairs + tiers)` with fixed-depth positive projections.
- After one warm-up, record five-run medians for 1,000-pair Spot and
  1,000-pair/50,000-tier Futures synthetic builders. Target extra builder time is at most
  250 ms Spot and 750 ms Futures, with peak Python allocation above the supplied fixture
  at most 64 MiB.
- On the same representative Spot and Futures Backtest fixtures, enabled median wall time
  must be no more than disabled median × 1.10 + 50 ms. Wall-clock figures are recorded
  acceptance evidence rather than brittle cross-machine unit-test thresholds.
- Spy assertions prove zero exchange reload/fetch/second-Exchange calls and fixed
  `importlib.metadata` lookup only.
- Enforce Strategy Evidence v2 limits independently: 4,096 named parameters, 64
  protections, depth 8, 16,384 recursive nodes, 16 KiB per UTF-8 string, and 1 MiB
  canonical parameter bytes. Every over-limit case fails before artifact/ZIP creation.
- After one warm-up, record a five-run median for a maximum-shape synthetic v2 builder.
  Target time is at most 100 ms and peak Python allocation above the supplied fixture is
  at most 16 MiB.

### Frontend RED-to-GREEN

- API 2.55 automatically sends capture for non-FreqAI revision runs; API 2.54 and below
  omit the property exactly. The server's static-PairList admission error remains visible.
- Strict Strategy Evidence helpers accept legacy v1 and new v2, while context-bound
  receipts require v2.
- Strict helpers validate exact literals, component IDs, aggregate ID, and derive
  same/different/unknown without fallback.
- Component comparison identifies runtime/config/exchange drift independently of
  DataSnapshot and strategy states.
- Result, history, selector, search, comparison, replay warning, localization, and
  accessibility render the bounded/confounded semantics.
- The mocked Backtest journey covers a same-context pair, a changed-context pair, and an
  older unknown result while existing data/strategy/replay behavior remains intact.

## 7. Verification commands

```powershell
# backend
& 'G:\AI_Trading\freqtrade-cn\freqtrade\.venv\Scripts\python.exe' -m pytest `
  tests/optimize/test_backtest_execution_context_evidence.py `
  tests/optimize/test_backtest_strategy_evidence.py `
  tests/optimize/test_backtesting.py tests/optimize/test_optimize_reports.py `
  tests/rpc/test_backtest_data_snapshot_schema.py tests/rpc/test_rpc_apiserver.py `
  -q -k "not test_api_freqaimodels" -p no:cacheprovider
& 'G:\AI_Trading\freqtrade-cn\freqtrade\.venv\Scripts\python.exe' -m ruff check `
  freqtrade/optimize freqtrade/rpc tests/optimize tests/rpc

# frontend
pnpm vitest run tests/unit/backtestRevision.spec.ts tests/unit/appI18n.spec.ts
pnpm typecheck
pnpm build
pnpm exec eslint --no-fix --quiet `
  e2e/backtest.spec.ts src/components/ftbot/BacktestHistoryLoad.vue `
  src/components/ftbot/BacktestResultAnalysis.vue `
  src/components/ftbot/BacktestResultComparison.vue `
  src/components/ftbot/BacktestResultSelectEntry.vue `
  src/components/ftbot/BacktestRun.vue src/locales/en.ts src/locales/zh-CN.ts `
  src/types/backtest.ts src/types/features.ts src/utils/backtestResultKey.ts `
  tests/unit/appI18n.spec.ts tests/unit/backtestRevision.spec.ts
pnpm exec playwright test e2e/backtest.spec.ts --project=chromium
pnpm exec playwright test e2e/backtest.spec.ts --project=msedge
```

## 8. Explicit non-goals

- no complete Environment Identity, environment restoration, container/image archive,
  host fingerprint, SBOM, package enumeration, lockfile attestation, or exchange emulator;
- no raw/full/sanitized config persistence, raw exchange response, unrelated market,
  credential, URL, path, environment variable, user/host/network/container identifier;
- no imported-helper closure, arbitrary strategy I/O, FreqAI/model identity,
  random/time/network determinism, signing, encryption, or authenticity guarantee;
- no dynamic PairList context claim, PairList config/seed/RNG capture, or per-candle order
  trace/replay;
- no new database, CAS, registry, migration, endpoint, Backtest engine, environment page,
  picker, capture checkbox, restore action, or platform/Runtime dependency;
- no robustness/holdout, optimizer/ranker, AI journal/daemon, automatic tuning/promotion,
  StrategyRelease, BotRelease, RuntimeInstance, Paper, Live, or exchange write;
- no claim of equal results, causal improvement, generalization, Paper eligibility,
  contract-trading safety, stable profitability, or future profit.

## 9. Implementation checklist

- [x] Pass independent design Gate and accept the boundary decision.
- [x] Add failing backend canonicalization, ownership, schema, API, dynamic-admission,
      replay, privacy, atomicity, and resource-bound tests.
- [x] Upgrade newly captured Strategy Evidence to the exact v2 ownership scope while
      retaining v1 load compatibility.
- [x] Implement the pure allowlist builder and engine-owned seal point.
- [x] Bind API 2.55 request/receipt/history while preserving legacy behavior.
- [x] Add failing frontend capability, strict-state, localization, and journey tests.
- [x] Add the third result/history/selector/comparison axis without a new form control.
- [x] Run focused and broader verification plus Chromium/Edge journeys.
- [ ] Pass independent backend, frontend, security/minimality, and documentation Gates.
- [ ] Commit backend and frontend first, then root pointers/docs and exact-SHA acceptance.
