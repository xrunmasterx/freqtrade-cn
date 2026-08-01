# Phase 1 Backtest Chart Source Disclosure

**Status:** Accepted at Root `8daa16253de23487c79bcd0bd5a6c8ec13bad71b`, backend
`3823205239281af56c34f4ff07f1674edddbe6db`, and frontend
`410018a1de9a65e97d8b8b3e12bdfb4d3926d404`

**Scope:** FreqUI selected-result chart ownership, Backtest-result chart title,
permanent source warning, exact locale copy, existing `/pair_history` `freqaimodel`
presence semantics, API 2.57 capability negotiation, focused frontend/backend tests,
and lifecycle documentation only; no new API field or route, Backtest engine, result
artifact, strategy, market-data, Runtime, Paper, Live, or AI-worker change

**Standing contract:** [Chart Data Source Rules](../../chart-data-source-rules.md)

## User problem

The Backtest visualizer currently draws two different evidence sources in one chart:

1. Trade markers come from `backtestResult.trades` in the selected Backtest result;
2. candles are loaded from the local market-data store available when `/pair_history`
   is requested;
3. indicators, entry/exit signal columns, and strategy chart annotations are computed
   then with the currently installed strategy.

The request carries strategy name, timeframe, timerange, FreqAI model, modes, and
columns, but it carries no selected-result filename, Backtest revision, Strategy
Evidence, DataSnapshot, or retained replay selector. The backend loads the strategy
currently installed under that name, loads the current local OHLCV, and computes the
analyzed dataframe and annotations then.

There is also a smaller but concrete ownership defect. The selected result owns the
result Trades, timeframe, strategy name, timerange, FreqAI model, and trading modes,
but `BacktestingView` currently passes some of the chart request fields from the editable
Backtest run form. After selecting a result, a user can edit that form and make the
chart request drift away from the result whose Trades remain visible.

A selected result without a FreqAI model exposed a second ownership leak. JavaScript
`undefined` is omitted from GET and POST transport, while the existing backend used a
truthy fallback to the Webserver's configured model. The chart could therefore combine
non-FreqAI result Trades with a current FreqAI recomputation. Merely clearing the model
name is also insufficient when the copied service config still has `freqai.enabled=true`:
the strategy startup path then enters the model resolver without a model and fails.
An updated FreqUI also cannot assume that an older backend understands the new empty-string
meaning: old backends apply the same truthy fallback and would silently reintroduce the
leak. The semantic change therefore needs an advertised capability and an old-backend
fail-closed path, not merely correct serialization.

The current sentence, "Graph will always show the latest values for the selected
strategy," does not say which objects are historical, which are recomputed, or that
their exact provenance has not been verified. A user can therefore mistake a useful
reference overlay for a faithful replay of what the result's strategy saw when it
created those Trades.

## First-principles invariant

> When one view combines evidence from sources whose exact context equality has not
> been proved, the view must permanently identify each source and the missing proof at
> the point where the evidence is interpreted.

Strategy name and timeframe are useful compatibility checks, but they are not exact
result identity. Even a newly completed result or a result with strong metadata on
the historical side cannot close the comparison because the current `/pair_history`
response has no corresponding revision, Strategy Evidence, or DataSnapshot identity.

## Minimal product decision

Phase 1 retains the existing result Trade markers and current recalculated chart.
Removing Trade markers merely because exact identity is unverified would remove an
existing basic Backtest review capability. Pretending the chart is an exact replay is
unacceptable. The smallest truthful behavior has two parts:

1. on API 2.57+, the selected `backtestResult` becomes the sole weak-context authority for
   strategy, timeframe, timerange, FreqAI model, trading mode, and margin mode; and
2. the mixed-source view receives a permanent, precise disclosure.

`BacktestResultChart` therefore accepts the selected result instead of separate,
form-derived context props. Its request, chart props, and title all derive from that one
result. This removes an invalid source of state without adding a new store or abstraction.

The Backtest chart forces the existing POST `/pair_history` transport on API 2.57+ even
when the user's global reduced-call setting is disabled. This is required because the
legacy GET route does not accept trading mode or margin mode and would silently inherit
those fields from the Webserver configuration. The transport override is local to this
chart call; other Pair-History callers retain their configured GET/POST behavior.

The existing `freqaimodel` request field carries the minimum three-state protocol needed
to preserve that authority without adding a schema field:

| Wire value | Request-local behavior |
| --- | --- |
| omitted, or POST `null` | inherit the Webserver configuration for old-client compatibility |
| non-empty string | override the request-local `freqaimodel` name; existing FreqAI enablement/config still determines execution |
| empty string `""` | explicitly use no FreqAI model for this chart recomputation |

This intentionally changes the former behavior of an explicit empty string, which used
to inherit through Python truthiness. Repository callers previously either omitted the
field or sent a non-empty model, so omitted/null inheritance preserves their compatibility;
an external caller that deliberately sent `""` expecting inheritance must now omit it.

A non-empty model name does not enable FreqAI or synthesize its remaining configuration.
It preserves the existing service-owned `freqai.enabled` and related configuration, while
preventing the selected model name from being replaced by another configured name.

When the selected result omits the field or returns `null`, FreqUI sends `""` rather than
letting transport omit it. The backend normalizes that explicit empty value to local
`freqaimodel=None` and disables FreqAI only when the already-deep-copied configuration
contains a `freqai` object. It neither mutates the service configuration nor creates an
incomplete `freqai` object for an ordinary non-FreqAI service. A genuinely FreqAI-dependent
strategy without result-bound model identity consequently fails closed instead of silently
using the current service model.

Backend API 2.57 advertises the explicit no-FreqAI meaning. Updated FreqUI renders the
recalculated chart when the selected result has a non-empty model or the backend advertises
that capability. If the result has no model and the backend is older, FreqUI does not mount
the history chart and therefore emits no unsafe request; it keeps the surrounding result
review UI and shows this actionable message:

```text
This Backtest result has no FreqAI model. Backend API 2.57 or newer is required to load
its recalculated chart without inheriting the backend's configured model. Update the
backend to view this chart safely.
```

```text
该回测结果没有 FreqAI 模型。需要后端 API 2.57 或更高版本，才能在不继承后端已配置模型的
情况下加载其重算图。请更新后端后再安全查看此图。
```

This capability protects the updated FreqUI when it connects to old backends and allows a
non-empty result model to retain legacy chart compatibility. That fallback does not claim
the complete six-field ownership contract because a GET-only legacy backend cannot apply
result-owned trading and margin modes. It cannot retroactively change an old FreqUI's
behavior; the packaged local stack must update FreqUI and backend together to obtain the
complete disclosure, context ownership, and no-model safety behavior.

The chart header becomes:

```text
Selected Backtest result trades on a recalculated chart
所选回测结果中的交易与当前重算图
```

Every Backtest chart panel receives this non-dismissible warning through the existing
`chartWarningText` path:

```text
Trade markers come from the selected Backtest result. Candles are loaded from the local
data available now. Indicators, strategy signals, and chart annotations are recalculated
with the strategy code installed now. The code or data may differ from that Backtest, so
this chart is a reference—not an exact replay.
```

```text
交易标记来自所选回测结果。K 线读取自当前可用的本地数据；指标、策略信号和图表
标注由当前安装的策略代码重新计算。代码或数据可能与该次回测不同，因此本图仅供对照，
并非精确回放。
```

The warning is unconditional while this mixed-source chart is shown:

- a matching strategy name or timeframe does not remove it;
- historical metadata on only one side does not remove it;
- legacy results without metadata still receive it;
- a transient refresh-failure warning may be appended, not substituted for it; and
- it remains visible when no current recomputation has loaded yet, because it describes
  what the chart requests and will combine.

No new alert component, dismiss state, metadata comparison, API field, API route, or
persistence is needed. The existing amber per-panel warning presentation is sufficient
and keeps the copy adjacent to the rendered evidence.

The user-facing copy deliberately avoids internal evidence-model terminology. In this
design, “reference—not an exact replay” means that Backtest revision, Strategy Evidence,
and DataSnapshot equality cannot be verified against the current `/pair_history` side.

Unverified exact identity and an explicitly detected mismatch are different states.
Unverified identity retains the basic result Trade markers with the permanent
warning. Existing strategy/timeframe mismatch checks remain fail-closed: when a Trade
has explicit incompatible context, that marker remains hidden and the existing mismatch
message remains visible. This slice does not weaken or replace that rule.

## Test-first acceptance criteria

1. A real `BacktestResultChart` mount passes the exact permanent source warning to its
   `CandleChartContainer` owner boundary.
2. The same mount proves result-owned `backtestResult.trades` pass unchanged when exact
   identity is merely unverified.
3. On API 2.57+, the selected `backtestResult` is the sole authority for strategy,
   timeframe, timerange, FreqAI model, trading mode, and margin mode. A regression deliberately
   gives the editable Backtest form different values and proves the request, chart
   props, and title still use the selected result. A result with a model sends that model;
   a result with a missing or `null` model sends the explicit no-model value `""`. The
   chart forces POST even when the global reduced-call setting is disabled, so trading
   mode and margin mode reach the backend instead of being ignored by GET.
4. Backend API 2.57 advertises the explicit no-FreqAI contract. On older backends, a
   no-model result does not mount the recalculated chart, emits no Pair-History request,
   and shows the exact upgrade message; a result with a non-empty model remains compatible.
5. The header no longer says only that the graph shows latest values. It identifies
   the selected Backtest result's Trades on a recalculated chart.
6. The source warning explicitly states all source boundaries:
   - displayed Trade markers are from the selected Backtest result;
   - candles are loaded from the local data available now;
   - indicators, strategy Signals, and chart annotations are recalculated with the
     strategy code installed now; and
   - code or data may differ, so the chart is a reference rather than an exact replay.
7. Matching strategy name/timeframe does not suppress the warning. No test may infer
   exact revision, Strategy Evidence, or DataSnapshot equality from those fields.
8. Existing explicit strategy/timeframe mismatch coverage stays fail-closed and keeps
   its marker-hidden explanation.
9. Permanent source disclosure and a transient same-context refresh-failure warning
   compose; neither replaces the other.
10. Exact English, Simplified Chinese, and bilingual locale resolution is covered.
11. Existing Pair-History context, chart warning composition, Backtest navigation,
   Backtest-result analysis, and full FreqUI tests remain green.
12. FreqUI typecheck, production build, changed-file ESLint/Prettier, and Root/backend/
   FreqUI working-tree plus staged `git diff --check` pass.
13. Actual HTTP GET and POST tests fix the three-state `freqaimodel` contract: omitted or
   POST `null` inherits, a non-empty value overrides, and `""` normalizes to no model and
   disables only an existing request-local FreqAI config. The global configuration remains
   semantically unchanged, and ordinary configs do not gain a `freqai` key.
14. The strategy submodule remains unchanged and clean. No actual Backtest, market,
   strategy, holdout, Paper, or Live workload is run.

## Focused test ownership

The implementation starts with the following deterministic tests:

1. `BacktestingViewChartAuthority.spec.ts` mounts the real `BacktestingView`, renders the
   `visualize` slot, and observes only the `BacktestResultChart` owner boundary. The
   selected result and editable `btStore` form are deliberately different before and
   after mount. Strategy, timeframe, timerange, and FreqAI must remain result-owned; a
   result with no FreqAI model must not inherit an enabled form model.
2. `BacktestResultChartContext.spec.ts` mounts the real `BacktestResultChart` and observes
   a child boundary that declares, but does not render, `chartWarningText`. It uses
   matching result/Trade strategy and timeframe, then asserts the full warning, full new
   title, absence of the old title, unchanged result Trades, and the exact
   result-owned `/pair_history` payload. It also proves that API 2.57 capability permits
   missing/null no-model requests, old backends retain explicit-model compatibility, and
   old backends fail closed without mounting the chart or issuing a no-model request.
3. `ftbotPairHistory.spec.ts` proves omitted, explicit empty, and explicit model values
   have different request keys where appropriate, that both API 2.57 POST and GET
   transports retain the explicit empty value for their existing callers, and that the
   Backtest caller's transport override still selects POST when the global setting is off.
4. `test_rpc_apiserver.py` exercises actual GET and POST parsing for the three-state
   protocol, including POST `null`, enabled FreqAI configuration, ordinary configuration
   without a `freqai` object, global-config immutability, and the API 2.57 advertisement.
5. `backtestRevision.spec.ts` proves the capability is absent at API 2.56 and present at
   API 2.57.
6. `appI18n.spec.ts` hard-codes the exact English, Simplified Chinese, and bilingual
   title and warning expectations. It does not import expected copy from production
   locale objects.
7. `CandleChartContainerHistoricView.spec.ts` is a real-container characterization:
   every panel renders the permanent warning; a same-context retained-data panel in
   refresh error appends the refresh-failure warning, while a second panel is explicitly
   `not_loaded`, has no current-context dataset, and keeps only the permanent warning.
   Existing composition infrastructure may already make this test green before the new
   owner wiring.
8. Existing `CandleChart.spec.ts` explicit strategy/timeframe mismatch tests remain in
   the focused Gate to prove incompatible execution markers are still hidden.

The locale keys are named for their actual meaning (`graphSourceTitle` and
`graphMixedSourceWarning`); the misleading `graphLatestValues` key is removed because it
has only this one call site.

## Explicit non-goals

- no exact historical indicator or signal replay in this slice;
- no execution of archived strategy source;
- no historical environment or dependency restoration;
- no result-bound analyzed-data snapshot or new ZIP member;
- no `/pair_history` request/response schema change;
- no new FreqAI request boolean, enum, or sentinel field;
- no comparison algorithm for revision, Strategy Evidence, or DataSnapshot identity;
- no new marker-comparison engine and no synthesized Trade, Signal, Order, or Fill
  markers;
- identity merely being unverified does not hide Trade markers; an explicitly detected
  strategy or timeframe mismatch remains fail-closed under the standing chart contract;
- no generic provenance platform, catalog, CAS, database, or evidence service;
- no strategy candidate, performance run, retired holdout, Runtime, Paper, Live, or AI
  loop.

## Deferred exact-replay option

If a later product requirement demands the exact historical candles, complete
indicators, Signals, and Trades used by a selected result, that is a separate design.
The healthy direction is a result-bound, read-only chart snapshot created during the
Backtest and retained in the existing result lifecycle. It must not execute archived
Python. Storage size, multi-pair volume, serialization, ZIP safety, legacy fallback, and
identity binding require their own Gate and are not pre-authorized by this disclosure.

## Planned verification

```powershell
Set-Location freqtrade
.\.venv\Scripts\python -m pytest tests/rpc/test_rpc_apiserver.py::test_api_pair_history_freqaimodel_presence_semantics -q
.\.venv\Scripts\python -m pytest tests/rpc/test_rpc_apiserver.py::test_show_config_api_version_has_pair_history_explicit_no_freqai -q
.\.venv\Scripts\python -m pytest tests/rpc/test_rpc_apiserver.py -k pair_history -q
.\.venv\Scripts\python -m ruff check freqtrade/rpc/api_server/api_pair_history.py tests/rpc/test_rpc_apiserver.py

Set-Location ..\frequi
pnpm vitest run tests/unit/ftbotPairHistory.spec.ts
pnpm vitest run tests/component/BacktestResultChartContext.spec.ts tests/unit/appI18n.spec.ts tests/unit/backtestRevision.spec.ts
pnpm vitest run tests/component/BacktestingViewChartAuthority.spec.ts tests/component/CandleChartContainerHistoricView.spec.ts tests/component/CandleChart.spec.ts tests/component/SingleCandleChartContainer.spec.ts
pnpm vitest run
pnpm typecheck
pnpm build
pnpm eslint src/views/BacktestingView.vue src/components/ftbot/BacktestResultChart.vue src/locales/en.ts src/locales/zh-CN.ts tests/component/BacktestingViewChartAuthority.spec.ts tests/component/BacktestResultChartContext.spec.ts tests/component/CandleChartContainerHistoricView.spec.ts tests/unit/appI18n.spec.ts tests/unit/ftbotPairHistory.spec.ts
pnpm prettier --check src/views/BacktestingView.vue src/components/ftbot/BacktestResultChart.vue src/locales/en.ts src/locales/zh-CN.ts tests/component/BacktestingViewChartAuthority.spec.ts tests/component/BacktestResultChartContext.spec.ts tests/component/CandleChartContainerHistoricView.spec.ts tests/unit/appI18n.spec.ts tests/unit/ftbotPairHistory.spec.ts

Set-Location ..
git -C freqtrade diff --check
git -C frequi diff --check
git diff --check
# After staging the new files, repeat with `diff --cached --check` in each changed repo.
```

All acceptance evidence is deterministic API-contract, UI, and locale evidence. No Docker
or product workload is required for this source-disclosure slice.
