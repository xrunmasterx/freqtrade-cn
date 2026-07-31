# Phase 1 Operator Entrypoint Truth Acceptance Report

**Acceptance date:** 2026-08-01

**Status:** accepted at an exact Root documentation implementation SHA; no frontend,
backend, strategy, route, service, port, Compose, Docker runtime, market-data, Backtest,
Lookahead Analysis, Recursive Analysis, retired-holdout, Runtime, Paper, Live, remote
push, merge, release, or deployment change

**Branch:** `xrunmasterx/phase1-complete-development`

**Worktree:**
`C:\Users\dezhengu\orca\workspaces\freqtrade-cn\phase1-complete-development`

**Plan:**
[Phase 1 Operator Entrypoint Truth](../plans/2026-08-01-phase1-operator-entrypoint-truth.md)

## 1. Exact implementation identity

| Repository | Exact accepted implementation SHA |
|---|---|
| Root | `783a412dabe2a935e1424a13a9fadc59c8961103` |
| `freqtrade/` backend | `8b1ec82765cc0eb59da0287cd62dd892b62f0f11` (unchanged) |
| `frequi/` frontend | `a084c1526ad7e65b0972c342a0a20c1871dd98f9` (unchanged) |
| `freqtrade-strategies/` | `dec5adb77f03b0c33ccfbc036ff0a3e57f7d571d` (unchanged) |

The Root implementation commit has tree
`5411533e28da5f1659904e10604f0cf786379072` and is
`docs: correct phase 1 operator entrypoints`. This report and final status updates are a
later documentation-only commit and do not replace that accepted implementation
identity.

## 2. Accepted user navigation

The current Docker quick-start now sends users to the product surfaces that answer the
accepted Phase 1 questions:

| Service | Route | Documented purpose |
|---|---|---|
| 8081 Spot | `/graph` | primary live watch and strategy review |
| 8081 Spot | `/trade` | runtime and trade observation |
| 8083 webserver | `/backtest` | authoritative standard Freqtrade backtest |
| 8083 webserver | `/lookahead_analysis` | existing lookahead safety analysis |
| 8083 webserver | `/recursive_analysis` | existing recursive indicator analysis |
| 8083 webserver | `/research` | retained simplified-SMA compatibility behavior; not the authoritative backtest |

The `freqtrade-research` service name, port 8083, start and stop commands, profiles,
credentials, secrets, and runtime contract remain unchanged. The port description is
now “offline validation/research webserver” so the label reflects both its standard
Freqtrade validation surfaces and its retained Research compatibility surface.

No new root `README.md` was created. `README.docker.md` remains the single tracked root
operator quick-start rather than being copied into a second authority.

## 3. Verification

This documentation-only acceptance used static route and repository inspection. It did
not start a service or claim runtime availability from the existence of a route.

| Check | Result |
|---|---:|
| Root tracked README inventory | only `README.docker.md`; no root `README.md` |
| FreqUI `/graph`, `/trade`, `/research`, `/backtest` routes | present |
| FreqUI `/lookahead_analysis`, `/recursive_analysis` routes | present |
| README.docker exact 8081/8083 URL scan | all six intended URLs present |
| Service, port, command, credential, and runtime-contract diff | unchanged |
| Backend, frontend, and strategy submodule status | clean and unchanged |
| Root `git diff --check` before commit | passed |

Route existence proves that the corrected links are not invented. It does not prove that
a service is currently running, authenticated, configured with data, or capable of
completing a particular Backtest or analysis run.

## 4. Orchestrated independent Gates

Read-only reviewers checked the plan, route facts, product authority, final diff, scope,
and status documents. They made no repository changes and ran no product workload.

| Review | Result |
|---|---|
| Initial documentation design Gate | one P1 stale “no active implementation” sentence |
| Documentation design re-Gate | PASS; P0/P1/P2 = 0 |
| Independent route/scope design Gate | PASS; P0/P1/P2 = 0 |
| Documentation implementation Gate | PASS; P0/P1/P2 = 0 |
| Acceptance-documentation Gate | PASS; P0/P1/P2 = 0 |

The single P1 was a lifecycle-status contradiction in `STRATEGY.md`, not a route or
product defect. Removing the obsolete sentence made the plan, README authority table,
and governing strategy agree that the documentation slice was active during execution.

## 5. Decision

Phase 1 Operator Entrypoint Truth is accepted at Root implementation SHA
`783a412dabe2a935e1424a13a9fadc59c8961103`. There is no unresolved P0, P1, or known
P2 inside its declared operator-documentation boundary.

This acceptance does not prove chart freshness, strategy correctness, Backtest
correctness, analysis sufficiency, robustness, Paper or Live eligibility, or current or
future profitability. No strategy candidate is active. The former
`20250702-20260702` holdout remains retired, and no replacement holdout is assigned.
