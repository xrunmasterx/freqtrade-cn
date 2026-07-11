# SQLite backup, migration, restore, and rollback

This runbook migrates only the dry-run SQLite state of the formal Spot and
Futures services. `sqlite_state.py backup-service` uses SQLite's online backup API, so a
source may remain online for the initial read-only backup; committed WAL state is
included and uncommitted work is excluded. `verify` checks the bundle hash,
SQLite integrity, foreign keys, and core table counts.

Formal service source and destination paths are fixed by the repository's
`ops/runtime-services.json`; the public API and CLI provide no root, manifest,
source, or destination override for those lanes. The tool records the resolved
path and filesystem identity, then revalidates the formal source immediately
before backup I/O and the destination parent before temporary-file creation and
again before publication. If a checked path changes, the operation fails without
printing success. Once restore creates its unique temporary file, the tool never
searches for or unlinks that name through a mutable pathname. Failures therefore
leave the file quarantined wherever the original directory identity resides.
Successful restore publishes a no-clobber hard link only after revalidating the
temporary inode captured from its creation handle, and retains that same inode
under the unique temporary name as a post-publication quarantine. These checks
close supported same-process mutation windows; they do not claim protection
against a continuously racing, same-authority privileged local actor between
boundaries.

Every schema 2 manifest records only the weaker `atomic-process-crash` baseline.
On POSIX, `verify` derives `power-loss-posix` only from a separate
`durability-complete.json` record whose exact schema binds it to the manifest
hash, POSIX creation platform, final bundle directory name, and transaction
nonce. The database and weak manifest files are synced first, the staged bundle
verifies, and the staging directory is synced.
Publication then renames the uniquely owned staging directory into its final
name and syncs the output root while the bundle is still weak. A hidden
completion candidate is written and file-synced, atomically renamed to
`durability-complete.json`, and followed by a final bundle-directory sync. Only
then is the completed bundle verified and returned. A missing, malformed,
changed, or identity-mismatched completion record cannot promote the weak
manifest to `power-loss-posix`.

The persistent hidden sidecar named for the intended final bundle is both the
operating-system lock and the authoritative transaction receipt. Creation holds
its exclusive lock across construction, publication, every completion barrier,
receipt transition, and failure-state transition. Before construction it writes
and fsyncs an exact `pending` receipt containing a new transaction nonce and the
original final basename. Only after all bundle and completion barriers succeed
does it replace the receipt contents through the already locked descriptor with
an exact, fsynced `success` receipt bound to the same nonce, manifest hash,
platform, and original basename. Any pre-success failure first attempts an exact,
fsynced `failed` receipt. A partial, missing, pending, failed, malformed, or
unmatched receipt fails closed.

`verify` first accepts only an exact normal bundle basename or the exact hidden
`.<original>.quarantine-<16 lowercase hex>` form and derives the original identity
without reading bundle state. It then opens the corresponding existing sidecar
without following symlinks, requires the opened object and pathname entry to be
the same regular file, and requests a shared nonblocking lock. Only while that
lock is held does it read the receipt through the descriptor and then read the
bundle. Strong POSIX verification requires an exact `success` receipt and exact
completion record with matching nonce, manifest hash, platform, and original
basename. The sidecar and bundle are one verification unit; copying or moving a
bundle without its matching sidecar is not a verified backup.

If a creator still holds the lock, verification fails with the fixed
creation-in-progress result. A missing sidecar or unavailable lock implementation
also fails closed. POSIX uses `flock` and Windows uses `msvcrt.locking`; no
in-process-only fallback exists. An explicit unlock error followed by successful
descriptor close is a safe release. If creator-side close fails, the still-open
descriptor is used to downgrade any success receipt to failed before another
close attempt, and the command fails closed.

If any explicit barrier or completion check fails after final-name publication,
the tool writes and file-syncs an exact `creation-failed.json` record and syncs
the bundle directory before atomically moving the bundle to a new
unique hidden quarantine name and syncing the output root. Verification
rejects this intrinsic failure record even if the quarantine directory is later
renamed back to the intended final basename; it does not rely on a quarantine
substring. A failure in a failure-record barrier still returns failure, retains
the installed failure evidence where possible, attempts quarantine, and never
reports strong durability because the authoritative sidecar remains pending,
failed, or malformed. The intrinsic record is defense in depth, not the sole
failure authority. The tool tracks whether final publication occurred and never
recursively deletes the vacated staging pathname; an unrelated replacement at
that old name is left untouched. Failures before final publication retain the
unique hidden staging artifact for identity-aware disposition rather than
performing pathname-based recursive cleanup under ambiguity.

The backup root must be a local or mounted filesystem that documents reliable
cross-process support for the host locking primitive and must exclude every
concurrent actor capable of replacing, unlinking, or renaming entries in that
directory. Network, distributed, or userspace filesystems without the locking
guarantee are unsupported. `O_NOFOLLOW` where available plus regular-file
identity checks reject sidecar symlinks and replacement already visible at open
time, but this tool does
not claim protection against a same-authority or privileged actor that can race
directory-entry replacement after those checks.

A POSIX restore syncs the temporary database before verification, creates the
no-clobber hard link, syncs the destination parent, retains the temporary name
as the binding Scheme A same-inode quarantine, and then performs the approved
second parent-directory sync. The historical durability-plan step that said
"unlink" does not apply: restore never removes the quarantine through a pathname,
and the second barrier records the deliberately retained namespace state rather
than claiming an unlink occurred.

On Windows, the database, manifest, and restore temporary files are synced, but
directories are not. Schema 2 therefore reports only `atomic-process-crash` and
does not claim power-loss or hard-reset durability. Any failed barrier makes the
operation fail. Backup failures retain a uniquely named non-promotable staging
or intrinsically failed quarantine artifact instead of leaving a normal bundle
with a strong claim.
Restore failures retain any created temporary quarantine, and failures after
hard-link publication retain both names. A failed command is never a durability
success, even when quarantined evidence remains.

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

Each restore that reaches temporary-file creation intentionally leaves one
hidden `.trades.sqlite.*.tmp` quarantine name in the original destination
directory identity. After a successful restore it is a second hard link to the
published database, not a second copy. After a failed restore it may contain a
partial or complete candidate and the CLI prints only the fixed failure message.
Do not automate quarantine cleanup by pathname or recursively search for moved
files: a substituted directory or filename could make such cleanup delete
unrelated data. Quarantine disposition requires a separately authorized,
identity-aware operator procedure outside this migration command.

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
