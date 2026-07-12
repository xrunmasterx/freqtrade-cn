# Runtime Registry v2 Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved Phase 2 Runtime Registry, platform-control, trusted compiler, Supervisor, market-data compatibility, Runtime Access Gateway, and controlled removal of fixed 8081/8082/8083 services without losing existing product behavior.

**Architecture:** Build one modular-monolith control plane backed by PostgreSQL and a host-local Supervisor that is the only dynamic Docker actor. Run Bots and Workers as isolated RuntimeInstances compiled from committed closed templates; expose one loopback `platform-control:8090`, independent base market data, and exact instance-scoped Runtime Access routes.

**Tech Stack:** Python 3.11-3.14, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, psycopg 3, Docker Compose v2, Vue 3, Pinia 3, Axios, Vitest, pytest, Ruff, standard-library unittest, Git submodules, GitHub Actions.

## Global Constraints

- Approved specifications: `docs/superpowers/specs/2026-07-12-runtime-registry-v2-design.md` and `docs/superpowers/specs/2026-07-12-multi-market-research-trading-platform-design.md`.
- Ordinary future BotRelease identity is exactly one Market + one Product + one primary AccountRevision + one Environment; ordinary releases never cross products.
- `platform-control` is the only fixed loopback application API and binds exactly `127.0.0.1:8090`.
- PostgreSQL is internal-only and has no host port.
- Runtime lifecycle HTTP remains read-only in Phase 2; only the trusted local Operator CLI creates lifecycle jobs.
- The Runtime Supervisor is the only dynamic Docker actor.
- Runtime Access never accepts caller-selected URL, IP, port, hostname, container, project, network, service, image, command, mount, or Compose input.
- `platform-control` can query Registry data and write only gateway-owned request/audit records; it has no Registry lifecycle mutation, Docker, secret-root, or Bot-state authority.
- Each managed application runtime receives a private access network shared only with the verified `platform-control` identity.
- Dynamic runtimes use `restart: "no"`, one active attempt maximum, failure latching, and explicit operator retry.
- No destructive recovery, overwrite restore, automatic state reuse/deletion, or unknown-container deletion.
- Secret values never enter PostgreSQL, RuntimeSpec, API, audit, log, error, or ordinary environment variables.
- Base candles are independent of Bot health; strategy overlays may degrade independently.
- Refresh compatibility is exact: 1m/10s, 3m/30s, 5m-30m/60s, 1h/180s, 2h-4h/300s, 6h-12h/600s, 1d-or-higher/900s; `60m` aliases `1h`; unknown API v2 timeframes fail closed.
- Chart/AI refresh never evaluates a strategy, creates an OrderIntent, invokes risk approval, or submits an order.
- Ambiguous lifecycle or application-write outcomes are reconciled and never blindly retried.
- Use strict RED -> GREEN TDD for every behavior change.
- Commit backend tasks inside `freqtrade/`, frontend tasks inside `frequi/`, then update root gitlinks only after task review.
- Publishing, pushing, PR mutation, online exchange access, and any live/order write require separate explicit authorization.

---

## Plan Set and Dependency Order

1. [Phase 2A: Registry and Platform Control](2026-07-12-runtime-registry-v2-phase2a-control-plane.md)
2. [Phase 2B: Trusted Template and RuntimeSpec Compiler](2026-07-12-runtime-registry-v2-phase2b-compiler.md)
3. [Phase 2C: Supervisor and Safe Runtime Driver](2026-07-12-runtime-registry-v2-phase2c-supervisor.md)
4. [Phase 2D: Market Data, Runtime Access Reads, and UI](2026-07-12-runtime-registry-v2-phase2d-market-data-ui.md)
5. [Phase 2E: Compatibility Writes, Controlled Cutover, and Operations](2026-07-12-runtime-registry-v2-phase2e-cutover.md)

Do not start a later phase until the previous phase has:

- a clean worktree in every repository touched by that phase;
- focused tests, full affected-suite tests, lint/typecheck, and Root Safety selectors passing;
- a fresh architecture review and code/security review;
- immutable reviewed component commit IDs recorded;
- no unresolved P0/P1 review finding.

## Specification Coverage Matrix

| Approved requirement | Implementing tasks |
|---|---|
| PostgreSQL-only production control plane, Alembic, no production `create_all()` | 2A Tasks 1 and 3 |
| Closed runtime owner/state/action contracts | 2A Task 2 |
| Instance/attempt/job/audit persistence, optimistic version, leases, idempotency | 2A Tasks 3 and 4; 2C Task 2 |
| Fixed authenticated `platform-control:8090`, least privilege, no lifecycle HTTP | 2A Tasks 5-7 |
| Committed immutable AdapterTemplates and closed policy IDs | 2B Tasks 1-3 |
| `local-file-v1` secret references/versions without value persistence | 2B Task 4 |
| Platform-derived isolated StateAllocation | 2B Task 5 |
| Deterministic RuntimeSpec compilation and paper-probe restrictions | 2B Tasks 6 and 7 |
| Reused P0 Compose launch kernel, exact image/provenance, no Docker SDK | 2C Tasks 1 and 4 |
| Supervisor-only Docker, attempts, failure latch, explicit retry, ambiguity reconciliation | 2C Tasks 2, 3, 6, and 7 |
| Private per-instance access network shared only with platform-control | 2C Task 5 |
| Emergency exact stop/inspect independent of PostgreSQL | 2C Task 6 |
| Full multi-timeframe refresh policy, canonical candles, freshness, coalescing | 2D Tasks 1-4 |
| No-credential OKX/Bitget public market data and Bitget catalog correction | 2D Task 3 |
| Instance-bound Runtime Access read authentication and closed routes | 2D Tasks 5 and 6 |
| Bot-independent base chart, optional strategy overlay, forming/closed semantics | 2D Tasks 7 and 9 |
| UI/Research migration to 8090 and server-published cadence | 2D Tasks 8-10 |
| Governed compatibility application writes, target isolation, no ambiguous retry | 2E Tasks 2 and 3 |
| Existing-process import as migration Bot/Workspace Worker identities | 2E Task 1 |
| Identity-bound backup/new-allocation restore and one-writer state copy | 2E Tasks 4 and 5 |
| Removal of active fixed services and 8081/8082/8083 listeners | 2E Task 6 |
| Offline acceptance, separately authorized paper-online acceptance, recursive checkout | 2E Tasks 7 and 8 |

The following approved non-goals remain outside these plans: production BotRelease/AccountRevision models, CompositeBot, central risk gateway, new live lane, full RBAC lifecycle API, AI model/agent execution, immutable Bot decision-snapshot production, broker/options execution, and destructive/automatic recovery. Phase 2D supplies the canonical market-data read contract that those consumers use; it does not implement their business loops.

## Execution Preflight

- [ ] Record immutable bases before Phase 2A:

```powershell
$env:PHASE2_ROOT_BASE = (git rev-parse HEAD).Trim()
$env:PHASE2_BACKEND_BASE = (git -C freqtrade rev-parse HEAD).Trim()
$env:PHASE2_FRONTEND_BASE = (git -C frequi rev-parse HEAD).Trim()
$env:PHASE2_STRATEGIES_BASE = (git -C freqtrade-strategies rev-parse HEAD).Trim()
"root=$env:PHASE2_ROOT_BASE"
"backend=$env:PHASE2_BACKEND_BASE"
"frontend=$env:PHASE2_FRONTEND_BASE"
"strategies=$env:PHASE2_STRATEGIES_BASE"
```

Expected starting root commit after the approved Gateway amendment:

```text
cbcf0c7
```

If any component is dirty or differs from the reviewed base, stop and reconcile before editing.

- [ ] Run the baseline gates and retain their output:

```powershell
python -S -m unittest discover -s tests -p "test_*.py" -v
Push-Location freqtrade
python -m pytest tests/markets/test_catalog.py tests/platform/test_catalog_repository.py tests/rpc/test_api_catalog.py -q -p no:cacheprovider
ruff check freqtrade/markets freqtrade/platform freqtrade/rpc/api_server/api_catalog.py tests/markets tests/platform tests/rpc/test_api_catalog.py
Pop-Location
Push-Location frequi
pnpm exec vitest run tests/unit/tradeChartRefresh.spec.ts tests/unit/useLiveChartDataset.spec.ts tests/unit/useResearchChartAutoRefresh.spec.ts
pnpm typecheck
Pop-Location
```

Expected: all commands exit 0. Any baseline failure is recorded and resolved outside Phase 2 before implementation.

## Review and Commit Protocol

For each task:

1. dispatch a fresh implementation subagent when using Subagent-Driven execution;
2. run the task's RED command and retain the expected failure;
3. implement only the task scope;
4. run GREEN and affected regression commands;
5. run a requirements/spec compliance review;
6. run a code-quality/security review;
7. fix findings and rerun verification;
8. commit in the owning repository;
9. record commit ID and verification output before the next task.

Never combine backend, frontend, and root code in one component commit. A root commit may update reviewed gitlinks and root-owned files only.

## Final Phase 2 Gate

- [ ] Run offline verification from a clean recursive checkout at the exact root SHA:

```powershell
git status --short
git submodule status --recursive
python -S -m unittest discover -s tests -p "test_*.py" -v
Push-Location freqtrade
python -m pytest tests/platform tests/markets tests/rpc/test_api_catalog.py tests/rpc/test_api_market_data.py tests/rpc/test_api_runtime_access.py -q -p no:cacheprovider
ruff check freqtrade/platform freqtrade/platform_control tests/platform tests/rpc/test_api_market_data.py tests/rpc/test_api_runtime_access.py
Pop-Location
Push-Location frequi
pnpm exec vitest run tests/unit/marketDataStore.spec.ts tests/unit/platformApi.spec.ts tests/unit/useLiveChartDataset.spec.ts tests/unit/useResearchChartAutoRefresh.spec.ts tests/component/TradingViewLiveChart.spec.ts tests/component/ResearchView.spec.ts
pnpm typecheck
pnpm lint-ci
pnpm build
Pop-Location
```

Expected: clean worktree, exact submodule SHAs, zero test failures, zero Ruff/ESLint/type errors, and successful frontend build.

- [ ] Run the separately authorized paper-only online acceptance only after offline gates pass. It must prove no real order, no exchange write, independent state, exact provenance, complete refresh cadence, Runtime Access isolation, and no listeners on 8081/8082/8083.

- [ ] Do not push, open/update a PR, mark a PR ready, merge, or enable live trading without a new explicit instruction.
