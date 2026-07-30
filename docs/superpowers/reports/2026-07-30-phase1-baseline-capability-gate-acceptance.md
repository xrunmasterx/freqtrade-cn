# Phase 1 Baseline Capability Gate Acceptance Report

**Acceptance date:** 2026-07-31

**Gate decision date:** 2026-07-30

**Status:** accepted at exact implementation SHAs; compatibility services stopped after
acceptance; no next development journey activated

**Scope:** the minimum useful strategy-validation loop across the existing 8081
watch/trade compatibility service and 8083 standard Freqtrade webserver-mode validation
service.

## 1. Accepted outcome

Gate A passed without introducing a new page, API, backtest engine, runtime abstraction,
or formal Paper model. The accepted user loop is:

1. observe the one-minute market view at the normal approximately ten-second cadence;
2. distinguish the provisional Forming Candle from official closed-candle strategy
   indicators and signals;
3. keep Strategy Signals separate from recorded or simulated execution markers;
4. suppress and visibly report execution markers whose available strategy name or
   timeframe mismatches the chart;
5. run and inspect the standard Freqtrade Backtest, Lookahead Analysis, and Recursive
   Analysis on the Research webserver compatibility service.

8081 remains a preconfigured dry-run Spot compatibility service. It is not a fixed Bot
domain concept, a BotRelease-owned RuntimeInstance, or formal dynamic Paper acceptance.
8083 `/research` remains a frozen simplified SMA compatibility capability and is not the
authoritative backtest engine.

## 2. Exact implementation identity

The accepted implementation Root is the parent of this documentation-only report
commit. The report does not claim that its own later Markdown commit was present in the
runtime image.

| Repository | Accepted implementation commit |
|---|---|
| Root | `ec1026a10dea6bff58fc1f4ff011f7ba397cc5f0` |
| Backend `freqtrade/` | `455455980902113002df3d391eb38c2b954881f5` |
| Frontend `frequi/` | `ce0df358f915d7cbfb69ff35aaf9d6e72ab37201` |
| Strategies | `dbd5b0b21cfbf5ee80588d37458ace2467b7f8a4` |

The three implementation commits are local on branch
`phase1-baseline-capability-gate`. They were not pushed by this acceptance run.

## 3. Image and service provenance

Docker 29.6.2, Compose 5.3.1, and the `desktop-linux` daemon were used. Docker is
installed at a fixed local path but is not on the coordinator PowerShell `PATH`; test and
formal commands temporarily prepended the installed directory without changing the user
environment.

`image_provenance.py build --print-image-id` produced committed build image:

```text
sha256:6f4747f487889229ea7e2689a87f3f91b66dace2a457df2321332b4eda9561c4
```

`formal_startup.py verify-all` passed against that immutable ID. The formal service
launcher then created service-specific immutable images and containers:

| Service | Endpoint | Container image ID | Pre-stop health |
|---|---|---|---|
| `freqtrade` | `http://127.0.0.1:8081` | `sha256:f1c73daa6bac9ba2ad66a67c661a245286380c9b2efd9ce64e37212e637ac645` | healthy |
| `freqtrade-research` | `http://127.0.0.1:8083` | `sha256:bce7f8ae7e49a287f87300d4d12a20ae3224875dd2225e9afddc8bbfdc86d670` | healthy |

Both containers carried the exact Root/backend/frontend revision labels above. The
formal launcher's temporary-image cleanup may prune an image object after use; the
recorded build output, successful formal-startup run, container immutable Image fields,
and container revision labels are the provenance evidence. No mutable tag is used as the
acceptance identity.

## 4. Configuration identity and safety

Only non-secret configuration facts were inspected:

| Service | Accepted identity |
|---|---|
| 8081 | `dry_run=true`, Spot, OKX, `SampleStrategy`, 1m, runmode `dry_run`, bot name `freqtrade-cn-okx-spot` |
| 8083 | `dry_run=true`, Spot, OKX, runmode `webserver`, no preselected strategy |

8083 resolves user-selected trusted strategies through the fixed
`/freqtrade/user_data/strategies` path. The mount is read-only, the operational config
must contain exactly that path, and callers cannot provide another filesystem path. The
service command still has no `--strategy`, `--strategy-path`, or trading database
argument. `/freqtrade/state` remains the only general writable service root.

No secret value, secret file content, credential hash, or authentication token was
printed or included in screenshots.

## 5. Local deterministic data

The exact backtest used a temporary ignored copy of the repository fixture:

```text
source: freqtrade/tests/testdata/BTC_USDT-5m.feather
temporary target: ft_userdata/runtime/freqtrade-research/data/okx/BTC_USDT-5m.feather
size: 102362 bytes
SHA256: 38F89DD1E8A116E5F451E24F7022E1213AB17336DA98EF9ABC1C38F9BF1850CC
rows: 3106
available range: 2025-11-24 through 2025-12-04
accepted timerange: 20251124-20251204
```

After service acceptance, the temporary target was resolved inside the workspace,
hash-verified, and deleted with an exact non-recursive operation. The source fixture
remains present. Ignored backtest result/history artifacts were retained as local
evidence.

## 6. Automated acceptance

| Gate | Result |
|---|---:|
| Root bootstrap/runtime/Compose/formal-startup selection | 159 passed, 2 Windows-inapplicable POSIX skips, 174 subtests passed |
| Root Ruff on changed Python | passed |
| Operational bootstrap verify | passed |
| Runtime contract config check | passed |
| Compose render check | passed |
| Backend chart composition/indicator selection | 62 passed |
| Backend chart/backtest/analysis API selection | 17 passed, 92 deselected |
| Backend Ruff | passed |
| Frontend focused chart and locale suites | 13 files, 98 tests passed |
| Frontend typecheck | passed |
| Frontend changed-file ESLint | passed |
| Frontend production build | passed |
| Mocked Chromium Backtest/Lookahead/Recursive journeys | 4 passed |
| Markdown relative links and fences | 14 changed Markdown files, zero missing links, zero unbalanced fences |
| Root/backend/frontend `git diff --check` | passed |
| Independent final Gate Review | P0 0, P1 0, P2 0 — PASS |
| Committed-image formal startup | passed |

One existing Starlette TestClient deprecation warning did not fail the backend API
selection. Successful frontend runs emitted intermittent Happy DOM teardown
`AbortError`/`EPROTO`, third-party pure-annotation build warnings, and mocked
background-job `data is not iterable` console noise. The commands exited successfully;
these were recorded rather than expanded into unrelated toolchain work.

## 7. Exact 8081 acceptance

The committed 8081 container authenticated and rendered both `/graph` and `/trade`.

On `/graph`:

- three successful `POST /api/v1/chart_candles` responses were observed;
- intervals were 9,991 ms and 10,026 ms;
- chart and strategy timeframes were both 1m;
- `candle_mode=live` and `last_candle_complete=false`;
- provisional layer sources were exactly Market and Watch;
- seven strategy columns were present and remained official closed-candle evidence;
- two entry signals were visible in the accepted window;
- one ECharts canvas rendered Watch and strategy overlays;
- the Forming Candle observation/watch-only trust message was visible;
- no strategy-context mismatch warning appeared for the matching compatibility data.

On `/trade`, the same strategy chart, pairs, signal layers, and empty open-trade state
rendered without a context warning. The authenticated `show_config` response—not a
literal UI label—was the authority for `dry_run=true` and Spot identity.

No live Paper trade was required or manufactured. Signal-versus-execution separation,
styling, legacy fallback, different-name suppression, and same-name/different-timeframe
suppression were accepted through deterministic component tests.

## 8. Exact 8083 acceptance

The committed 8083 container returned the Research webserver identity, listed
`SampleStrategy`, and returned its strategy detail through the fixed read-only strategy
path.

The standard Freqtrade backtest API completed with:

```text
strategy: SampleStrategy
timeframe: 5m
timerange: 20251124-20251204
status: ended
simulated trades: 1
profit_total: 0.00057346868
profit_total_abs: 5.7346868 USDT
effective start: 2025-11-24 16:40:00
effective end: 2025-12-04 00:00:00
```

FreqUI rendered the strategy summary, 0.057% / 5.735 USDT total profit, one simulated
trade, signal chart, simulated trade marker, and trade navigation. The exact rerun
naturally created a second history entry; both `SampleStrategy` rows were visible and
selectable. No extra run was created solely to exercise comparison, and multi-result
comparison is not elevated to a new P0 claim.

Lookahead Analysis and Recursive Analysis used the same strategy, timeframe, and data
window:

- Lookahead ended with `has_bias=false`, zero biased entry/exit signals, and
  `total_signals=0` after explicitly allowing the strategy's configured limit orders.
  This accepts the analysis execution/result contract; it is not a claim about strategy
  quality or statistically meaningful signal coverage.
- Recursive ended for startup candle counts 50, 100, and 200, reported the strategy's
  startup count as 200, and returned 15 indicators.

## 9. Local visual evidence

Screenshots are intentionally ignored runtime evidence rather than versioned product
files:

| Screenshot | Size |
|---|---:|
| `ft_userdata/runtime/phase1-receipts/2026-07-30-baseline-gate/8081-graph-exact.png` | 305677 bytes |
| `ft_userdata/runtime/phase1-receipts/2026-07-30-baseline-gate/8081-trade-exact.png` | 258504 bytes |
| `ft_userdata/runtime/phase1-receipts/2026-07-30-baseline-gate/8083-backtest-result-exact.png` | 115938 bytes |
| `ft_userdata/runtime/phase1-receipts/2026-07-30-baseline-gate/8083-backtest-visual-exact.png` | 135556 bytes |

Visual inspection confirmed non-empty charts, the trust message, Watch and strategy
indicator separation, signal points, result metrics, the simulated trade marker, and
trade navigation. The screenshots contain no credentials.

## 10. Reproduced defects and bounded repairs

1. The first real 8083 backtest could not load `SampleStrategy` because the existing
   Research operational config had no strategy search path.
2. A proposed CLI `--strategy-path` repair was reproduced as invalid because Freqtrade
   `webserver` does not accept that argument. It was fully reverted before acceptance.
3. The accepted repair uses Freqtrade's native config field, the existing shared
   read-only mount, an atomic/idempotent migration, and fail-closed verification.
4. Independent review found that name-only Trade filtering could display a same-name,
   different-timeframe Runtime Trade. A RED test reproduced it; the final local predicate
   compares name and available strategy timeframe and drives both filtering and warning
   count.
5. The first Lookahead attempt with limit orders disallowed hit the strategy/config order
   compatibility guard. No operational pricing config was weakened. The accepted run
   explicitly allowed the strategy's configured limit orders and recorded that boundary.

No failing test or runtime guard was disabled. Every material repair received focused
regression coverage.

## 11. Stop, cleanup, and roadmap decision

After acceptance:

- `freqtrade` and `freqtrade-research` were stopped through the existing bounded
  non-destructive wrapper;
- their final container states were `exited`, with no published ports;
- the isolated browser was closed;
- the one temporary market-data copy was hash-verified and removed;
- the source fixture, ignored screenshots, and ignored backtest result/history evidence
  were retained.

No Live environment, exchange write, real order, listener removal, state migration,
Futures service, 8090 service, platform service, or formal Paper RuntimeInstance was used.

The post-Gate decision is to stop. Phase 2D Tasks 5-8, Phase 2E, Runtime Access,
Experiment UI, dynamic Runtime, Paper Observation, and 8090 remain paused. The default
recommendation for a future separately authorized journey is the smallest immutable
Experiment revision plus authoritative Freqtrade backtest slice; this report does not
activate it.
