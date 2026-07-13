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

## Versioned RuntimeAttempt secret resolution

Phase 2B adds the `local-file-v1` provider for an exact set of secrets required
by one RuntimeAttempt. Its production root and fixed layout are:

```text
ft_userdata/secrets/runtime/<reference-id>/<version-id>/value
```

Reference IDs, version IDs, and secret classes are closed platform identifiers;
the caller cannot supply a path, filename, length, or permission policy. The
supported classes are `api_password`, `jwt_secret`, and `ws_token`, with fixed
minimum character lengths of 32, 48, and 32. Material is strict UTF-8, one
non-empty NUL-free line, at most 4096 bytes and characters, and every required
value for the attempt must be distinct.

The provider rejects symlinks, Windows reparse points, hardlinks, non-regular
files, replacement races, POSIX ownership/mode other than the approved runtime
UID and `0600`, and Windows files that fail the protected owner-only ACL proof.
It returns an already-open, non-inheritable descriptor at offset zero. The
consumer owns that descriptor and must close the handle, preferably with its
context-manager boundary. Peer and failed descriptors are closed by the
provider.

Secret material is not read from environment variables or PostgreSQL and must
never be logged, printed, hashed, persisted, enumerated, or exposed through
serialization. The provider does not cache material. This phase resolves only
already-provisioned versioned files; it does not create, migrate, rotate, or
delete secrets and does not change the legacy bootstrap/rotation process below.

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

Define the native-command fail-fast helper once in the current PowerShell
session. Every rotation, verification, recreate, status, and log command below
captures and checks its exit code before the next command runs:

```powershell
function Assert-NativeSuccess {
  param(
    [Parameter(Mandatory = $true)]
    [int] $ExitCode,
    [Parameter(Mandatory = $true)]
    [string] $Operation
  )

  if ($ExitCode -ne 0) {
    throw "$Operation failed with native exit code $ExitCode"
  }
}
```

The endpoint mapping is fixed for this runbook:

| Service | Endpoint | Acceptance identity |
|---|---|---|
| `freqtrade` | `http://127.0.0.1:8081` | Spot, DRY-RUN |
| `freqtrade-futures` | `http://127.0.0.1:8082` | Futures, DRY-RUN |
| `freqtrade-research` | `http://127.0.0.1:8083` | Research webserver |

### Spot: `freqtrade`

```powershell
Set-Location G:\AI_Trading\freqtrade-cn

python tools/bootstrap_runtime.py rotate-secrets --service freqtrade
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Rotate Spot credentials'
python tools/bootstrap_runtime.py verify
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Verify Spot credential rotation'
python tools/compose_runtime.py up freqtrade
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Recreate Spot service'
python tools/compose_runtime.py ps freqtrade
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Inspect Spot service'
python tools/compose_runtime.py logs --tail 100 freqtrade
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Read Spot service logs'
```

### Futures: `freqtrade-futures`

Do not continue until Spot has passed the checks below, then obtain separate
authorization for this endpoint.

```powershell
python tools/bootstrap_runtime.py rotate-secrets --service freqtrade-futures
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Rotate Futures credentials'
python tools/bootstrap_runtime.py verify
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Verify Futures credential rotation'
python tools/compose_runtime.py up freqtrade-futures
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Recreate Futures service'
python tools/compose_runtime.py ps freqtrade-futures
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Inspect Futures service'
python tools/compose_runtime.py logs --tail 100 freqtrade-futures
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Read Futures service logs'
```

### Research: `freqtrade-research`

Do not continue until Futures has passed the checks below, then obtain separate
authorization for this endpoint.

```powershell
python tools/bootstrap_runtime.py rotate-secrets --service freqtrade-research
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Rotate Research credentials'
python tools/bootstrap_runtime.py verify
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Verify Research credential rotation'
python tools/compose_runtime.py up freqtrade-research
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Recreate Research service'
python tools/compose_runtime.py ps freqtrade-research
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Inspect Research service'
python tools/compose_runtime.py logs --tail 100 freqtrade-research
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Read Research service logs'
```

## Acceptance after every service

Complete all checks before rotating the next service:

1. Confirm the old access and refresh tokens are rejected. This is expected, not
   a rollback condition.
2. Sign in again to exactly that Bot endpoint in FreqUI.
3. Confirm the visible Bot name and ID, exchange, Spot/Futures mode, and DRY-RUN
   marker identify the intended target. Futures acceptance must be performed at
   `http://127.0.0.1:8082`, not the Spot endpoint. For Research, confirm the
   endpoint is the Research service rather than a trading Bot.
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
