# SQLite backup, migration, restore, and rollback

This runbook migrates only the dry-run SQLite state of the formal Spot and
Futures services. `sqlite_state.py backup-service` uses SQLite's online backup API, so a
source may remain online for the initial read-only backup; committed WAL state is
included and uncommitted work is excluded. `verify` checks the bundle hash,
SQLite integrity, foreign keys, and core table counts.

The document itself grants no operational authority. Read-only backup and bundle
verification may be automated. Stopping a current Bot or restoring/replacing its
current database requires explicit operator authorization for that exact
maintenance window at execution time.

## 1. Create and verify online backups

Run the sections in order from the repository root. Define this fail-fast helper
once in the current PowerShell session. Every native command below captures
`$LASTEXITCODE` on the immediately following line, before calling the helper or
running any other command.

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

$backupRoot = 'G:\AI_Trading\freqtrade-backups'
```

The backup root must be outside the repository. Capture exactly one bundle path,
validate it as a non-empty existing directory, then verify the bundle:

```powershell
$spotBundleOutput = @(python tools/sqlite_state.py backup-service `
  --service freqtrade `
  --output-root $backupRoot `
  --print-path)
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Spot rehearsal backup'
if ($spotBundleOutput.Count -ne 1) {
  throw 'Spot rehearsal backup did not return exactly one bundle path'
}
$spotBundleCandidate = ([string] $spotBundleOutput[0]).Trim()
if ([string]::IsNullOrWhiteSpace($spotBundleCandidate)) {
  throw 'Spot rehearsal backup returned an empty bundle path'
}
if (-not (Test-Path -LiteralPath $spotBundleCandidate -PathType Container)) {
  throw 'Spot rehearsal bundle directory does not exist'
}
$spotBundle = $spotBundleCandidate

python tools/sqlite_state.py verify --bundle $spotBundle
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Spot rehearsal verification'
```

Back up and verify Futures independently:

```powershell
$futuresBundleOutput = @(python tools/sqlite_state.py backup-service `
  --service freqtrade-futures `
  --output-root $backupRoot `
  --print-path)
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Futures rehearsal backup'
if ($futuresBundleOutput.Count -ne 1) {
  throw 'Futures rehearsal backup did not return exactly one bundle path'
}
$futuresBundleCandidate = ([string] $futuresBundleOutput[0]).Trim()
if ([string]::IsNullOrWhiteSpace($futuresBundleCandidate)) {
  throw 'Futures rehearsal backup returned an empty bundle path'
}
if (-not (Test-Path -LiteralPath $futuresBundleCandidate -PathType Container)) {
  throw 'Futures rehearsal bundle directory does not exist'
}
$futuresBundle = $futuresBundleCandidate

python tools/sqlite_state.py verify --bundle $futuresBundle
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Futures rehearsal verification'
```

These rehearsal bundles prove the procedure before downtime. Do not move,
delete, or modify either legacy DB or its `-wal` and `-shm` companions.

## 2. Archive local QQE/LSRI databases without promoting them

Existing local QQE/LSRI databases may be archived, but an archive label does not
add a service to the P0 runtime contract. Any archive failure stops the loop:

```powershell
$archiveSources = @(
  @{ Label = 'freqtrade-qqe-base-futures-archive'; Path = 'ft_userdata\user_data\tradesv3-qqe-base-futures.sqlite' },
  @{ Label = 'freqtrade-qqe-daily-regime-futures-archive'; Path = 'ft_userdata\user_data\tradesv3-qqe-daily-regime-futures.sqlite' },
  @{ Label = 'freqtrade-qqe-4h-fullstake-futures-archive'; Path = 'ft_userdata\user_data\tradesv3-qqe-4h-fullstake-futures.sqlite' },
  @{ Label = 'lsri-shadow-archive'; Path = 'ft_userdata\user_data\tradesv3-lsri-shadow.sqlite' }
)

foreach ($item in $archiveSources) {
  if (Test-Path -LiteralPath $item.Path -PathType Leaf) {
    python tools/sqlite_state.py archive `
      --label $item.Label `
      --source $item.Path `
      --output-root $backupRoot
    $exitCode = $LASTEXITCODE
    Assert-NativeSuccess -ExitCode $exitCode -Operation "Archive backup for $($item.Label)"
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
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Stop formal runtime services'

python tools/compose_runtime.py --profile trading --profile research ps
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Inspect stopped runtime services'
```

Both commands must succeed before the manual check. The safe wrapper intentionally
does not support `ps --status` or `--quiet`. Inspect the complete `ps` output and
confirm manually that none of `freqtrade`, `freqtrade-futures`, or
`freqtrade-research` has a running status. If any remains running, abort; do not
back up final state, restore, or start a second writer.

With all three stopped, create and verify new final migration bundles. The
distinct final variable names prevent a failed final backup from falling back to
an earlier rehearsal bundle:

```powershell
$spotFinalBundleOutput = @(python tools/sqlite_state.py backup-service `
  --service freqtrade `
  --output-root $backupRoot `
  --print-path)
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Spot final backup'
if ($spotFinalBundleOutput.Count -ne 1) {
  throw 'Spot final backup did not return exactly one bundle path'
}
$spotFinalBundleCandidate = ([string] $spotFinalBundleOutput[0]).Trim()
if ([string]::IsNullOrWhiteSpace($spotFinalBundleCandidate)) {
  throw 'Spot final backup returned an empty bundle path'
}
if (-not (Test-Path -LiteralPath $spotFinalBundleCandidate -PathType Container)) {
  throw 'Spot final bundle directory does not exist'
}
$spotFinalBundle = $spotFinalBundleCandidate

python tools/sqlite_state.py verify --bundle $spotFinalBundle
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Spot final verification'

$futuresFinalBundleOutput = @(python tools/sqlite_state.py backup-service `
  --service freqtrade-futures `
  --output-root $backupRoot `
  --print-path)
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Futures final backup'
if ($futuresFinalBundleOutput.Count -ne 1) {
  throw 'Futures final backup did not return exactly one bundle path'
}
$futuresFinalBundleCandidate = ([string] $futuresFinalBundleOutput[0]).Trim()
if ([string]::IsNullOrWhiteSpace($futuresFinalBundleCandidate)) {
  throw 'Futures final backup returned an empty bundle path'
}
if (-not (Test-Path -LiteralPath $futuresFinalBundleCandidate -PathType Container)) {
  throw 'Futures final bundle directory does not exist'
}
$futuresFinalBundle = $futuresFinalBundleCandidate

python tools/sqlite_state.py verify --bundle $futuresFinalBundle
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Futures final verification'
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

python tools/sqlite_state.py restore-service `
  --service freqtrade `
  --bundle $spotFinalBundle
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Restore Spot final bundle'

python tools/sqlite_state.py restore-service `
  --service freqtrade-futures `
  --bundle $futuresFinalBundle
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Restore Futures final bundle'
```

Compare each restored candidate with its stopped legacy source:

```powershell
python tools/sqlite_state.py compare-structure `
  --source ft_userdata\user_data\tradesv3.sqlite `
  --candidate ft_userdata\runtime\freqtrade\trades.sqlite
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Compare restored Spot state'

python tools/sqlite_state.py compare-structure `
  --source ft_userdata\user_data\tradesv3-futures.sqlite `
  --candidate ft_userdata\runtime\freqtrade-futures\trades.sqlite
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Compare restored Futures state'
```

After the bundle checks succeed, use the fixed safe wrapper action to prove that
Freqtrade itself can read both restored databases:

```powershell
python tools/compose_runtime.py check-state freqtrade
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Read restored Spot state through Freqtrade'

python tools/compose_runtime.py check-state freqtrade-futures
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Read restored Futures state through Freqtrade'
```

`check-state` fixes the service command, database URL, JSON output mode, runtime
identity, mounts, and environment. It does not accept an entrypoint, volume,
user, environment, capability, database URL, or Research service override. The
JSON output can contain trade rows from a non-empty database. Inspect it only in
the authorized terminal; do not paste it into logs, tickets, chat, or reports.

## 5. Start and accept one service at a time

Start Spot first:

```powershell
python tools/compose_runtime.py up freqtrade
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Start Spot service'
python tools/compose_runtime.py ps freqtrade
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Inspect Spot service'
python tools/compose_runtime.py logs --tail 100 freqtrade
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Read Spot service logs'
```

Pause and confirm Spot is healthy and visibly identifies the correct Bot name,
ID, exchange, mode, and DRY-RUN endpoint. Only then start Futures:

```powershell
python tools/compose_runtime.py up freqtrade-futures
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Start Futures service'
python tools/compose_runtime.py ps freqtrade-futures
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Inspect Futures service'
python tools/compose_runtime.py logs --tail 100 freqtrade-futures
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Read Futures service logs'
```

Pause and perform the same target and health checks for Futures. Only then start
Research:

```powershell
python tools/compose_runtime.py up freqtrade-research
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Start Research service'
python tools/compose_runtime.py ps freqtrade-research
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Inspect Research service'
python tools/compose_runtime.py logs --tail 100 freqtrade-research
$exitCode = $LASTEXITCODE
Assert-NativeSuccess -ExitCode $exitCode -Operation 'Read Research service logs'
```

Confirm Research is healthy and is the intended Research endpoint. Keep the
untouched legacy DB, `-wal`, and `-shm` files for the entire acceptance period.
Do not let an old and a new service write different database versions.

## 6. Rollback without dual writers

Rollback also requires explicit operator authorization because it stops Bots and
changes the current database selection.

1. Stop the new topology and gate both native operations:

   ```powershell
   python tools/compose_runtime.py --profile trading --profile research stop
   $exitCode = $LASTEXITCODE
   Assert-NativeSuccess -ExitCode $exitCode -Operation 'Rollback stop of new topology'
   python tools/compose_runtime.py --profile trading --profile research ps
   $exitCode = $LASTEXITCODE
   Assert-NativeSuccess -ExitCode $exitCode -Operation 'Rollback inspection of new topology'
   ```

   Inspect the complete output and manually confirm no new service is running.
   Do not continue on a nonzero exit or a running status.
2. Preserve the failed new state root, including its DB/WAL/SHM. Do not overwrite
   it with a restore retry.
3. Restore the approved prior repository revision and image through the normal
   deployment process, then use that revision's verified safe wrapper.
4. Point the prior topology back to the untouched legacy databases. Start each
   old service with the same gated `up`, `ps`, and bounded `logs` sequence from
   section 5, pausing for endpoint acceptance after each service.
5. Never start an old writer until every new writer is stopped. Never run old
   and new services concurrently against either database generation.

## 7. Static runbook self-check

Run this non-native PowerShell check after editing the runbook. It verifies that
every documented Python native command is immediately followed by exit-code
capture and an assertion after its multiline command ends. It also checks every
`--print-path` output has explicit cardinality, trimming/non-empty, directory,
and single-string assignment gates, and that restore uses only final bundles.

```powershell
$runbookPath = 'docs\operations\sqlite-backup-and-restore.md'
$runbookText = Get-Content -Raw -LiteralPath $runbookPath
$runbookLines = Get-Content -LiteralPath $runbookPath
$nativePattern = 'py' + 'thon tools/(?:sqlite_state|compose_runtime)\.py'
$nativeCount = 0

for ($index = 0; $index -lt $runbookLines.Count; $index++) {
  if ($runbookLines[$index] -notmatch $nativePattern) {
    continue
  }

  $nativeCount++
  $commandEnd = $index
  while ($runbookLines[$commandEnd].TrimEnd().EndsWith('`')) {
    $commandEnd++
  }
  if ($runbookLines[$commandEnd + 1].Trim() -ne '$exitCode = $LASTEXITCODE') {
    throw "Missing immediate exit capture after native command at line $($index + 1)"
  }
  if ($runbookLines[$commandEnd + 2].Trim() -notlike 'Assert-NativeSuccess *') {
    throw "Missing fail-fast assertion after native command at line $($index + 1)"
  }
}

if ($nativeCount -eq 0) {
  throw 'No native commands found in runbook'
}

$bundleChecks = @(
  @{ Output = 'spotBundleOutput'; Candidate = 'spotBundleCandidate'; Single = 'spotBundle' },
  @{ Output = 'futuresBundleOutput'; Candidate = 'futuresBundleCandidate'; Single = 'futuresBundle' },
  @{ Output = 'spotFinalBundleOutput'; Candidate = 'spotFinalBundleCandidate'; Single = 'spotFinalBundle' },
  @{ Output = 'futuresFinalBundleOutput'; Candidate = 'futuresFinalBundleCandidate'; Single = 'futuresFinalBundle' }
)

foreach ($bundleCheck in $bundleChecks) {
  $countGate = '$' + $bundleCheck.Output + '.Count -ne 1'
  $trimGate = '$' + $bundleCheck.Candidate + ' = ([string] $' + $bundleCheck.Output + '[0]).Trim()'
  $emptyGate = '[string]::IsNullOrWhiteSpace($' + $bundleCheck.Candidate + ')'
  $pathGate = 'Test-Path -LiteralPath $' + $bundleCheck.Candidate + ' -PathType Container'
  $singleGate = '$' + $bundleCheck.Single + ' = $' + $bundleCheck.Candidate
  foreach ($requiredGate in @($countGate, $trimGate, $emptyGate, $pathGate, $singleGate)) {
    if (-not $runbookText.Contains($requiredGate)) {
      throw "Missing bundle gate: $requiredGate"
    }
  }
}

if (-not $runbookText.Contains('--bundle $spotFinalBundle')) {
  throw 'Spot restore is not pinned to the final bundle'
}
if (-not $runbookText.Contains('--bundle $futuresFinalBundle')) {
  throw 'Futures restore is not pinned to the final bundle'
}
```

## Recovery claim boundary

This drill proves that the dry-run SQLite state is internally consistent and readable.
It does not prove that a live exchange account is reconciled.
Live recovery requires open-order, fill, position, unknown-order and late-fill reconciliation.

本演练只证明 dry-run SQLite 状态内部一致且可读取；它不证明 live 交易所账户已经完成对账。live 恢复必须核对未完成订单、成交、持仓、未知订单和延迟成交。任何 live 数据库恢复后都必须由人工与交易所核对，并保持禁止自动恢复交易，直到 P11 Reconciliation Gate 完成。
