# Repository Guidelines

## Project Structure & Module Organization

This repository packages a local Freqtrade stack. The root contains Docker orchestration and runtime data wiring. Backend source and tests live in the `freqtrade/` submodule (`freqtrade/freqtrade/`, `freqtrade/tests/`). Frontend source and tests live in the `frequi/` submodule (`frequi/src/`, `frequi/tests/`, `frequi/e2e/`). Strategy examples and user configuration are under `freqtrade-strategies/` and `ft_userdata/user_data/`. Project design notes and implementation plans are stored in `docs/superpowers/`.

For chart indicators, strategy overlays, decision evidence, or crosshair/tooltip work, read `docs/chart-data-source-rules.md` before designing or coding. These rules are the standing source-boundary contract for future indicators and strategies.

## Build, Test, and Development Commands

Run backend commands from `freqtrade/`:

```powershell
.\.venv\Scripts\python -m pytest tests/rpc/test_chart_data.py -q
.\.venv\Scripts\python -m ruff check freqtrade/rpc tests/rpc
```

Run frontend commands from `frequi/`:

```powershell
pnpm vitest run tests/unit/candleChartTooltip.spec.ts
pnpm typecheck
pnpm build
```

Run the full local stack from the repository root:

```powershell
docker compose build freqtrade
docker compose up -d freqtrade
```

The main UI is served at `http://127.0.0.1:8081`.

## Coding Style & Naming Conventions

Python uses Ruff with a 100-character line limit. Keep RPC and persistence changes small, typed, and covered by pytest. TypeScript uses Vue 3, Pinia, ECharts, Vitest, and `vue-tsc`; prefer explicit exported interfaces in `frequi/src/types/`. Follow existing naming patterns: backend test files use `test_*.py`, frontend tests use `*.spec.ts`, chart metadata columns use source prefixes such as `watch_` and `strategy_<timeframe>_` only when they are part of the API contract.

## Testing Guidelines

Add focused tests beside the changed module. For chart work, verify both data shape and metadata: `columns`, `data`, `plot_config`, `meta.layers`, and tooltip behavior. Keep legacy payload compatibility tests when adding metadata or sidecar evidence. For frontend chart changes, run the relevant Vitest spec plus `pnpm typecheck`.

## Commit & Pull Request Guidelines

History uses short conventional prefixes, for example `feat: add chart decision snapshots`, `docs: add ... design`, `chore: package ...`, and `config: add ... config`. Commit submodule changes inside `freqtrade/` or `frequi/` first, then commit updated submodule pointers and docs in the root repository. Pull requests should describe backend/frontend impact, list test commands run, mention Docker verification when relevant, and include screenshots for visible chart/UI changes.

## Security & Configuration Tips

Do not commit `.env`, generated `.superpowers/` state, runtime logs, database files, or exchange credentials. Keep local user data under `ft_userdata/user_data/`. Treat API tokens, exchange keys, and strategy configuration as private operational data.
