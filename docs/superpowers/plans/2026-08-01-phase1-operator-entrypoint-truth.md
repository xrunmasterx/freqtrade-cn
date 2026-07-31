# Phase 1 Operator Entrypoint Truth

**Status:** Implemented; acceptance Gate pending

**Documentation design Gate:** PASS; P0 = 0, P1 = 0, P2 = 0

**Documentation implementation Gate:** PASS; P0 = 0, P1 = 0, P2 = 0

**Scope:** current operator documentation only; no route, frontend, backend, Compose,
service, port, market-data, strategy, Backtest execution, Runtime, Paper, or Live change

## User problem

`README.docker.md` currently sends a Spot user only to 8081 `/trade` and sends an
offline-validation user only to 8083 `/research`.

Both routes exist, but the guidance does not match the accepted Phase 1 user journey:

- 8081 `/graph` is the primary live-watch and strategy-overlay page, while `/trade`
  remains the runtime/trade-observation page; and
- 8083 `/backtest` is the authoritative standard Freqtrade backtest, while `/research`
  is retained compatibility behavior with a simplified SMA calculation.

The result is a navigation/documentation defect, not a missing route or product feature.

## Minimal correction

1. Keep the valid 8081 `/trade` link and add `/graph` as the primary live-watch entry.
2. Make 8083 `/backtest` the documented offline-validation entry and list the existing
   `/lookahead_analysis` and `/recursive_analysis` safety-analysis routes.
3. Keep `/research` visible only as a compatibility route and state that it is not the
   authoritative standard backtest.
4. Describe port 8083 as the offline-validation/research webserver port without renaming
   the existing `freqtrade-research` service.

Do not add a new root `README.md`: the repository currently has no such tracked file,
and duplicating `README.docker.md` would create a second operator authority.

## Acceptance criteria

1. A new user can identify 8081 `/graph` for live watch and `/trade` for runtime trades.
2. A new user can identify 8083 `/backtest` as standard Freqtrade validation.
3. Lookahead and Recursive Analysis routes are listed as existing safety-analysis tools.
4. `/research` remains documented but cannot be mistaken for the authoritative backtest.
5. Ports, service names, build/start/stop commands, credential guidance, and runtime
   contracts remain unchanged.
6. FreqUI router inspection proves that every documented route exists.
7. Root `git diff --check` passes; backend, frontend, and strategy submodules remain
   unchanged and clean.

## Explicit non-goals

- no route redirect or navigation-menu change;
- no Research feature deletion;
- no actual Backtest, Lookahead, Recursive, market, strategy, Paper, or Live run;
- no rewrite of historical plans, reports, or specifications;
- no new quick-start abstraction or duplicate README.

## Planned verification

```powershell
rg -n "path: '/(trade|graph|research|backtest|lookahead_analysis|recursive_analysis)'" frequi/src/router/index.ts
rg -n "8081/(graph|trade)|8083/(backtest|lookahead_analysis|recursive_analysis|research)" README.docker.md
git diff --check
```
