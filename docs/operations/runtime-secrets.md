# Runtime credential bootstrap and rotation

This runbook covers the three formal P0 services: `freqtrade`,
`freqtrade-futures`, and `freqtrade-research`. Each service owns a distinct API
password, JWT secret, and WebSocket token. Operational configs keep sentinel
values; real credentials live only in ignored files below
`ft_userdata/secrets/<service>/` and are injected as file secrets.

The document itself grants no operational authority. Initializing an unused new
machine is safe to perform as part of setup. Rotating credentials used by a
current endpoint, stopping a current Bot, or restoring a current database each
requires explicit operator authorization at the time of execution. Approval for
one service or maintenance window does not authorize another.

## Bootstrap a new machine

From a recursive clone:

```powershell
Copy-Item .env.example .env
python tools/bootstrap_runtime.py init
python tools/bootstrap_runtime.py sanitize-api-configs
python tools/bootstrap_runtime.py verify
python tools/runtime_contract.py --check-configs-only
python tools/compose_runtime.py --profile trading --profile research config --quiet
```

`init` is idempotent and refuses to replace an existing operational config or
secret. `sanitize-api-configs` leaves sentinel values in config instead of real
credentials, and `verify` checks the per-service secret suite and runtime
ownership/permissions. Do not print or open secret files during verification.
The UI username may be supplied by a template, but there is no repository-default
password. Never put login information in logs, issues, chat, or screenshots.

QQE is outside the formal root runtime contract. It must not be added piecemeal;
formalization requires its manifest entry, template, strategy, tests, and Compose
service in one reviewed change.

## Rotate one service at a time

Before each subsection, obtain explicit operator authorization to invalidate and
replace that service's current credential suite. Keep the other two services
running and unchanged. A successful rotation invalidates old access and refresh
tokens; clients must authenticate again.

### Spot: `freqtrade`

```powershell
Set-Location G:\AI_Trading\freqtrade-cn

python tools/bootstrap_runtime.py rotate-secrets --service freqtrade
python tools/bootstrap_runtime.py verify
python tools/compose_runtime.py up --detach --force-recreate freqtrade
python tools/compose_runtime.py ps freqtrade
python tools/compose_runtime.py logs --tail 100 freqtrade
```

### Futures: `freqtrade-futures`

Do not continue until Spot has passed the checks below, then obtain separate
authorization for this endpoint.

```powershell
python tools/bootstrap_runtime.py rotate-secrets --service freqtrade-futures
python tools/bootstrap_runtime.py verify
python tools/compose_runtime.py up --detach --force-recreate freqtrade-futures
python tools/compose_runtime.py ps freqtrade-futures
python tools/compose_runtime.py logs --tail 100 freqtrade-futures
```

### Research: `freqtrade-research`

Do not continue until Futures has passed the checks below, then obtain separate
authorization for this endpoint.

```powershell
python tools/bootstrap_runtime.py rotate-secrets --service freqtrade-research
python tools/bootstrap_runtime.py verify
python tools/compose_runtime.py up --detach --force-recreate freqtrade-research
python tools/compose_runtime.py ps freqtrade-research
python tools/compose_runtime.py logs --tail 100 freqtrade-research
```

## Acceptance after every service

Complete all checks before rotating the next service:

1. Confirm the old access and refresh tokens are rejected. This is expected, not
   a rollback condition.
2. Sign in again to exactly that Bot endpoint in FreqUI.
3. Confirm the visible Bot name and ID, exchange, Spot/Futures mode, and DRY-RUN
   marker identify the intended target. For Research, confirm the endpoint is the
   Research service rather than a trading Bot.
4. Inspect `ps` and the bounded service logs for a healthy service. Never print,
   copy, hash, or otherwise expose a secret file as a health check.
5. If authentication or health verification fails, do not restore a previously
   leaked or retired value. Generate another fresh three-secret suite with the
   same rotation command, run `verify`, force-recreate that service, and repeat
   the checks.

## Current tree versus Git history

Sanitizing the current tracked tree and rotating deployed credentials are P0
work. Old values may still exist in Git history. History rewriting and notifying
every clone owner is a separate, coordinated security operation; this runbook
does not authorize it. Never add an old value to a secret-scanner allowlist to
manufacture a passing result.
