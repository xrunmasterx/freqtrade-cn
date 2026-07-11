# Docker local run

This repository is organized as a top-level Docker project around the `freqtrade`,
`frequi`, and `freqtrade-strategies` submodules. The supported P0 runtime services
are `freqtrade`, `freqtrade-futures`, and `freqtrade-research`.

## First setup

Clone with submodules, create the ignored environment file, and bootstrap the
local operational configuration, per-service credentials, and writable state:

```powershell
git clone --recurse-submodules https://github.com/xrunmasterx/freqtrade-cn.git
Set-Location freqtrade-cn

Copy-Item .env.example .env
python tools/bootstrap_runtime.py init
python tools/bootstrap_runtime.py migrate-research-paths
python tools/bootstrap_runtime.py sanitize-api-configs
python tools/bootstrap_runtime.py verify
python tools/runtime_contract.py --check-configs-only
python tools/compose_runtime.py --profile trading --profile research config --quiet
```

Bootstrap is idempotent: it does not overwrite an existing operational config or
secret. API credential fields in operational config must retain the repository
sentinel; the real API password, JWT secret, and WebSocket token are separate
ignored files below `ft_userdata/secrets/<service>/`. A UI username may come from
the template, but the repository provides no UI password. Never write login
information to logs or paste it into an issue, chat, or screenshot.

`migrate-research-paths` is the explicit, idempotent migration for an existing
ignored `config.research.json`. It changes only the known legacy A-share data,
metadata, and side-data roots to their absolute paths below the read-only
Research input mount. Unknown or customized values are rejected without writing
the file; neither `init` nor `sanitize-api-configs` performs this migration.

QQE is not part of the formal root runtime contract. Adding it requires one
reviewed change that includes its manifest entry, template, strategy, tests, and
Compose service. Do not treat a local QQE service or database as P0 runtime state.

If the host HTTP proxy is not on port `12639`, update the ignored local
operational config. Docker Desktop on Windows/macOS reaches a host proxy through
`host.docker.internal`; a native virtual environment normally uses `127.0.0.1`.

See [Runtime secrets](docs/operations/runtime-secrets.md) before rotating
credentials and [SQLite backup and restore](docs/operations/sqlite-backup-and-restore.md)
before migrating state.

## Run

Build and start Spot, then inspect its status:

```powershell
python tools/compose_runtime.py up --detach --build freqtrade
python tools/compose_runtime.py ps freqtrade
```

Open the trading UI at `http://127.0.0.1:8081/trade`.

Build and start Futures independently:

```powershell
python tools/compose_runtime.py up --detach --build freqtrade-futures
python tools/compose_runtime.py ps freqtrade-futures
```

Open the Futures trading UI at `http://127.0.0.1:8082/trade`. Acceptance must
show the `freqtrade-futures` endpoint identity, Futures mode, and DRY-RUN marker;
do not treat a healthy Spot endpoint on port `8081` as Futures acceptance.

Build and start only the research webserver:

```powershell
python tools/compose_runtime.py up --detach --build freqtrade-research
python tools/compose_runtime.py ps freqtrade-research
```

Open the research UI at `http://127.0.0.1:8083/research`.

Services are assigned to profiles. To build and start all formal services, use:

```powershell
python tools/compose_runtime.py --profile trading --profile research up --detach --build
python tools/compose_runtime.py --profile trading --profile research ps
```

The wrapper verifies bootstrap state and permits only the supported project,
profiles, services, actions, and options. It is the formal runtime entrypoint.
Every formal service uses `/freqtrade/state` as its writable userdata directory.
Trading services load strategies from the read-only
`/freqtrade/user_data/strategies` mount; Research has no strategy path.

## Stop

Stopping active Bots is an operational action and requires explicit approval for
that maintenance window. After approval, stop and inspect all formal services:

```powershell
python tools/compose_runtime.py --profile trading --profile research stop
python tools/compose_runtime.py --profile trading --profile research ps
```

## Current defaults

- Exchange: `bitget`
- Trading mode: Spot for `freqtrade`; Futures for `freqtrade-futures`
- Run mode: `dry_run` for every P0 trading service
- Main trading UI port: `8081`
- Futures trading UI port: `8082`
- Research UI port: `8083`
- Container API/UI port: `8080`
