# SQLite backup, migration, restore, and rollback

This runbook migrates only the dry-run SQLite state of the formal Spot and
Futures services. `sqlite_state.py backup` uses SQLite's online backup API, so a
source may remain online for the initial read-only backup; committed WAL state is
included and uncommitted work is excluded. `verify` checks the bundle hash,
SQLite integrity, foreign keys, and core table counts.

The document itself grants no operational authority. Read-only backup and bundle
verification may be automated. Stopping a current Bot or restoring/replacing its
current database requires explicit operator authorization for that exact
maintenance window at execution time.

## 1. Create and verify online backups

Run from the repository root. The backup root must be outside the repository:

```powershell
$backupRoot = 'G:\AI_Trading\freqtrade-backups'

$spotBundle = python tools/sqlite_state.py backup `
  --service freqtrade `
  --source ft_userdata\user_data\tradesv3.sqlite `
  --output-root $backupRoot `
  --print-path

python tools/sqlite_state.py verify --bundle $spotBundle
```

Back up and verify Futures independently:

```powershell
$futuresBundle = python tools/sqlite_state.py backup `
  --service freqtrade-futures `
  --source ft_userdata\user_data\tradesv3-futures.sqlite `
  --output-root $backupRoot `
  --print-path

python tools/sqlite_state.py verify --bundle $futuresBundle
```

These initial bundles prove the procedure before downtime. Do not move, delete,
or modify either legacy DB or its `-wal` and `-shm` companions.

## 2. Archive local QQE/LSRI databases without promoting them

Existing local QQE/LSRI databases may be archived, but an archive label does not
add a service to the P0 runtime contract:

```powershell
$archiveSources = @(
  @{ Service = 'freqtrade-qqe-base-futures-archive'; Path = 'ft_userdata\user_data\tradesv3-qqe-base-futures.sqlite' },
  @{ Service = 'freqtrade-qqe-daily-regime-futures-archive'; Path = 'ft_userdata\user_data\tradesv3-qqe-daily-regime-futures.sqlite' },
  @{ Service = 'freqtrade-qqe-4h-fullstake-futures-archive'; Path = 'ft_userdata\user_data\tradesv3-qqe-4h-fullstake-futures.sqlite' },
  @{ Service = 'lsri-shadow-archive'; Path = 'ft_userdata\user_data\tradesv3-lsri-shadow.sqlite' }
)

foreach ($item in $archiveSources) {
  if (Test-Path $item.Path) {
    python tools/sqlite_state.py backup `
      --service $item.Service `
      --source $item.Path `
      --output-root $backupRoot
  }
}
```

QQE and LSRI remain archive-only here. They must not be started or wired into the
formal Spot/Futures/Research topology by this drill.

## 3. Authorized stop and final consistent backups

> **Maintenance-window gate:** The following commands stop the Bots. Execute
> them only after an operator explicitly approves this maintenance window. That
> approval must also explicitly cover restoring the current databases before
> proceeding to section 4.

```powershell
python tools/compose_runtime.py --profile trading --profile research stop
python tools/compose_runtime.py --profile trading --profile research ps
```

The safe wrapper intentionally does not support `ps --status` or `--quiet`.
Inspect the complete `ps` output and confirm manually that none of
`freqtrade`, `freqtrade-futures`, or `freqtrade-research` has a running status.
If any remains running, abort; do not restore or start a second writer.

With all three stopped, create the final migration bundles and verify them. These
assignments intentionally replace the variables that pointed to the earlier
online rehearsal bundles:

```powershell
$spotBundle = python tools/sqlite_state.py backup `
  --service freqtrade `
  --source ft_userdata\user_data\tradesv3.sqlite `
  --output-root $backupRoot `
  --print-path
python tools/sqlite_state.py verify --bundle $spotBundle

$futuresBundle = python tools/sqlite_state.py backup `
  --service freqtrade-futures `
  --source ft_userdata\user_data\tradesv3-futures.sqlite `
  --output-root $backupRoot `
  --print-path
python tools/sqlite_state.py verify --bundle $futuresBundle
```

## 4. Restore into new isolated state and compare

Restore is no-clobber. The intended destinations must not exist. If either check
below fails, stop and investigate the previous migration state; do not delete,
rename, or overwrite it under this runbook.

```powershell
$spotDestination = 'ft_userdata\runtime\freqtrade\trades.sqlite'
$futuresDestination = 'ft_userdata\runtime\freqtrade-futures\trades.sqlite'

if (Test-Path -LiteralPath $spotDestination) {
  throw "Restore destination already exists: $spotDestination"
}
if (Test-Path -LiteralPath $futuresDestination) {
  throw "Restore destination already exists: $futuresDestination"
}

python tools/sqlite_state.py restore `
  --bundle $spotBundle `
  --destination $spotDestination

python tools/sqlite_state.py restore `
  --bundle $futuresBundle `
  --destination $futuresDestination
```

Compare each restored candidate with its stopped legacy source:

```powershell
python tools/sqlite_state.py compare `
  --source ft_userdata\user_data\tradesv3.sqlite `
  --candidate ft_userdata\runtime\freqtrade\trades.sqlite

python tools/sqlite_state.py compare `
  --source ft_userdata\user_data\tradesv3-futures.sqlite `
  --candidate ft_userdata\runtime\freqtrade-futures\trades.sqlite
```

The verified bundle plus successful restore and comparison are the supported
dry-run database readability proof. The old raw Compose `show-trades` probe is
prohibited: it requires unsupported `run` behavior and can override the service
command or entrypoint. Do not copy or reconstruct that command. A future
Freqtrade-native probe requires a dedicated, reviewed safe wrapper action.

## 5. Start and accept one service at a time

Start each service only after the previous one is healthy and visibly identifies
the correct endpoint:

```powershell
python tools/compose_runtime.py up --detach freqtrade
python tools/compose_runtime.py ps freqtrade

python tools/compose_runtime.py up --detach freqtrade-futures
python tools/compose_runtime.py ps freqtrade-futures

python tools/compose_runtime.py up --detach freqtrade-research
python tools/compose_runtime.py ps freqtrade-research
```

For each endpoint, inspect health and bounded logs, sign in again if needed, and
confirm Bot name/ID, exchange, mode, and DRY-RUN marker before continuing. Keep
the untouched legacy DB, `-wal`, and `-shm` files for the entire acceptance
period. Do not let an old and a new service write different database versions.

## 6. Rollback without dual writers

Rollback also requires explicit operator authorization because it stops Bots and
changes the current database selection.

1. Stop the new topology, then inspect the wrapper's `ps` output and manually
   confirm no service is running:

   ```powershell
   python tools/compose_runtime.py --profile trading --profile research stop
   python tools/compose_runtime.py --profile trading --profile research ps
   ```

2. Preserve the failed new state root, including its DB/WAL/SHM. Do not overwrite
   it with a restore retry.
3. Restore the approved prior repository revision and image through the normal
   deployment process, then run that revision's verified `compose_runtime.py`.
4. Point the prior topology back to the untouched legacy databases and start one
   service at a time, checking `ps` and endpoint identity after each start.
5. Never start an old writer until every new writer is stopped. Never run old
   and new services concurrently against either database generation.

## Recovery claim boundary

This drill proves that the dry-run SQLite state is internally consistent and readable.
It does not prove that a live exchange account is reconciled.
Live recovery requires open-order, fill, position, unknown-order and late-fill reconciliation.

本演练只证明 dry-run SQLite 状态内部一致且可读取；它不证明 live 交易所账户已经完成对账。live 恢复必须核对未完成订单、成交、持仓、未知订单和延迟成交。任何 live 数据库恢复后都必须由人工与交易所核对，并保持禁止自动恢复交易，直到 P11 Reconciliation Gate 完成。
