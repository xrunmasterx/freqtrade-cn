# P0 Draft PR Safety Closure Design

**Status:** Approved

**Date:** 2026-07-11

**Branch:** `p0-current-system-safety-gate`

**Baseline:** root `01eef937d7979c39195435a65d7b713b130deb7e`, backend `acc87fbde7e63f13e04755abb18a14a9e3018c8d`, frontend `56ebcc4dc0d348163b9638984e2bf4371c48d1c1`

## 1. Background

The P0 branch is published, recursively cloneable, and has a green GitHub-hosted
Root Safety run. A final whole-branch review nevertheless rejected merge
readiness because several important contracts were either incomplete or tested
only through a probe that differed from the production path.

Independent read-only audits reproduced the findings:

1. Spot `trade`, Futures `trade`, and Research `webserver` all exit during
   configuration loading under a non-root UID different from image UID 1000.
   The default `/freqtrade/user_data` is not writable by that dynamic UID.
2. Safe-wrapper `start` and `restart` validate the current Compose render but
   operate on historical containers whose persisted configuration may differ.
3. Spot and Futures state bundles can be cross-restored. Existing verification
   and row-count comparison can still succeed when business contents differ.
4. The launch drift gate does not bind reviewed root/backend/frontend commits to
   Docker build input or the image actually started.
5. Root tests are no longer a standard-library-only gate because a workflow test
   imports PyYAML and the workflow installs backend dependencies first.
6. Backup and restore provide atomic visibility and ordinary process-crash
   safety, but do not establish an end-to-end POSIX power-loss durability
   barrier before reporting success.

Two minor findings were also confirmed:

- three multi-Bot frontend actions silently succeed when their captured target
  disappears;
- Docker base-image tags are mutable.

The frontend no-op is in scope because it is small and user-visible. Base-image
digest pinning is not a blocker for this P0 branch because it predates the
branch and is outside the current completion contract.

## 2. Goals

This design closes the verified P0 blockers without turning the Freqtrade-based
runtime into a new deployment platform.

The result must:

- make all three formal services safe under a dynamic non-root UID;
- keep configuration, strategies, research inputs, and secrets read-only;
- make `/freqtrade/state` the only writable service root;
- prevent safe-wrapper launch from reusing stale containers or stale images;
- build only from committed root/backend/frontend trees;
- bind the launched image to the reviewed commit combination;
- prevent cross-service backup/restore;
- provide POSIX power-loss durability and an honest, weaker Windows contract;
- restore a standard-library-only root gate before backend dependency install;
- make a disappeared frontend target an observable failure rather than a silent
  success;
- keep the PR in Draft until all automated and manual acceptance gates pass.

## 3. Non-goals

This change does not implement:

- live exchange order/fill/position reconciliation;
- a new multi-market research kernel;
- a new execution-adapter architecture;
- full database row-content canonical digests;
- image signing or an attestation service;
- Docker base-image digest maintenance;
- protection against an attacker who controls the same OS account and Docker
  daemon;
- a redesign of frontend `reloadConfig` stale-object behavior.

## 4. First-principles invariants

### 4.1 Runtime ownership

Every service has one writable root:

```text
/freqtrade/state
```

All service writes, including database, logs, home, market data, and backtest
results, remain below that root. The following inputs remain read-only:

```text
/freqtrade/config/**
/freqtrade/user_data/strategies/**
/freqtrade/user_data/research_data/**
/run/secrets/**
```

### 4.2 Launch identity

The following relationship must hold:

```text
reviewed committed trees
    == Docker build input
    == image provenance labels
    == image object used by Compose
```

### 4.3 State identity

For a formal service lane:

```text
bundle service
    == manifest lane service
    == legacy source owner
    == restore destination owner
```

### 4.4 Durability

On POSIX/Linux, a successful backup or restore means both file contents and
namespace changes have crossed the required file and directory `fsync`
barriers. On Windows, success means atomic visibility plus ordinary process
crash safety; it does not claim hard-reset or power-loss durability.

### 4.5 Test independence

The root safety gate must pass with Python standard-library imports only. It
must not depend on successful installation of the backend scientific stack.

## 5. Formal service runtime layout

### 5.1 Spot

Host root:

```text
ft_userdata/runtime/freqtrade
```

Container layout:

```text
/freqtrade/state/
├── trades.sqlite
├── logs/freqtrade.log
├── home/
├── data/
├── backtest_results/
└── other Freqtrade runtime output
```

The formal command explicitly includes:

```text
trade
--user-data-dir /freqtrade/state
--strategy-path /freqtrade/user_data/strategies
--logfile /freqtrade/state/logs/freqtrade.log
--db-url sqlite:////freqtrade/state/trades.sqlite
--config /freqtrade/config/runtime.json
--config /freqtrade/config/trading-safety.json
--strategy SampleStrategy
```

The safety overlay remains the last config.

### 5.2 Futures

Host root:

```text
ft_userdata/runtime/freqtrade-futures
```

The container layout mirrors Spot but remains backed by a distinct host root.
The command uses the same explicit userdata and read-only strategy paths, the
Futures logfile, the fixed service-local database, safety-last config ordering,
and `VolatilitySystem`.

### 5.3 Research

Host root:

```text
ft_userdata/runtime/freqtrade-research
```

The formal command includes:

```text
webserver
--user-data-dir /freqtrade/state
--logfile /freqtrade/state/logs/freqtrade-research.log
--config /freqtrade/config/runtime.json
```

Research inputs stay read-only at
`/freqtrade/user_data/research_data`. Writable `data` and
`backtest_results` live naturally below `/freqtrade/state`; the existing alias
mounts to `/freqtrade/user_data/data` and
`/freqtrade/user_data/backtest_results` are removed.

### 5.4 Bootstrap rules

Bootstrap creates and verifies these writable directories per service:

```text
state root
state root/home
state root/logs
state root/data
state root/backtest_results
```

It does not create `state root/strategies`, because that could hide a missing
explicit read-only strategy path.

No solution may use runtime sudo, runtime chown, chmod 0777, or a root-user
fallback.

## 6. Startup verification

### 6.1 Blocking offline contract

Root Safety runs with a dynamic UID different from 1000, ephemeral secrets,
dry-run safety, isolated project/container names, temporary state, and Docker
`--network none` isolation.

Spot and Futures execute their formal `trade` argv and must pass secret loading,
configuration loading, userdata access, strategy discovery, database setup, API
configuration, and the safety overlay. If isolation forces a stop at the
exchange network boundary, the test accepts only that precise failure category;
it never accepts an arbitrary non-zero exit.

If the formal process cannot expose a deterministic boundary, a backend-native
startup-contract command may be added. It must reuse Freqtrade's production
Configuration and directory code and must not duplicate a second validator.

Research must become healthy and answer `/api/v1/ping`, then stop cleanly.

### 6.2 Online dry-run acceptance

An online acceptance run uses only public market data and dry-run configuration.
It verifies Spot on 8081, Futures on 8082, and Research on 8083. It distinguishes
external network/exchange failure from local configuration failure. It is not
the sole blocking check for every commit, but it must succeed at least once
before the Draft PR becomes Ready.

## 7. Safe launch and provenance

### 7.1 Public actions

The wrapper exposes:

```text
config
up
down
stop
ps
logs
```

It removes `create`, `start`, and `restart`. `up` accepts exactly one approved
service and no user-controlled Docker flags.

### 7.2 Controlled `up`

`up <service>` internally performs:

1. manifest and runtime validation;
2. root/backend/frontend commit resolution;
3. committed-tree build-context assembly;
4. image build with provenance labels;
5. image inspection;
6. launch by inspected image ID with `--detach --force-recreate --no-build
   --no-deps`;
7. bounded readiness handling;
8. temporary-context cleanup.

### 7.3 Committed-tree build context

The wrapper does not build from the live worktree. It assembles a unique
temporary context from:

- root `HEAD` committed tree;
- backend tree at the root gitlink commit;
- frontend tree at the root gitlink commit.

It requires each submodule `HEAD` to equal its gitlink, rejects every tracked
change, and rejects every non-ignored untracked path reported by Git. Ignored
build outputs do not enter the committed-tree archive. Archive extraction rejects absolute paths, `..`
escape, and unsafe symlinks. Runtime secrets, SQLite files, user config,
strategies, and research output never enter the build context.

### 7.4 Image identity

The image uses a human-readable tag derived from short root/backend/frontend
SHAs and records complete SHAs in OCI labels. The wrapper inspects the labels,
captures the resulting image ID, and launches that image ID rather than a
mutable tag.

### 7.5 Emergency operations

`stop`, `down`, `ps`, and `logs` remain usable when source, manifest, or image
provenance validation fails. Launch fails closed; emergency stop and inspection
do not.

Raw Docker/Compose remains outside the supported formal deployment contract.
The wrapper does not claim to constrain an administrator who controls the Docker
daemon.

## 8. State lanes and bundle schema

### 8.1 Formal lane source of truth

`ops/runtime-services.json` defines Spot and Futures legacy sources, state roots,
and destination database names. Research has no formal trading-state lane.

### 8.2 Command split

Formal migration uses:

```text
backup-service --service <freqtrade|freqtrade-futures> --output-root <existing-dir>
restore-service --service <freqtrade|freqtrade-futures> --bundle <bundle>
```

Source and destination are derived from the manifest. The caller cannot provide
an arbitrary formal source or destination.

Non-promotable local files use:

```text
archive --label <label> --source <path> --output-root <existing-dir>
```

Archive bundles cannot be restored into a formal service lane.

### 8.3 Schema 2

Schema 2 records at least bundle purpose, formal service or archive label,
creation platform, and durability level in addition to current integrity and
metadata fields.

Schema 1 remains verifiable with durability reported as unknown. Formal restore
rejects it by default and requires an explicit legacy flag plus exact service
match.

### 8.4 Restore ordering

Before any parent, temporary file, or destination is created, restore verifies:

- approved formal service;
- manifest lane;
- bundle integrity;
- `purpose == service-state`;
- exact bundle/lane service match;
- expected legacy source filename;
- manifest-derived destination;
- destination non-existence.

Spot/Futures cross-restore must fail before any filesystem write.

### 8.5 Structural comparison

The old `compare` command becomes `compare-structure`. It proves schema,
`user_version`, table set, and selected row counts only. Documentation and output
must not describe it as row-level business-content equivalence.

## 9. Durability policy B

### 9.1 Shared requirements

Backup output root and restore destination parent must already exist. The tool
does not recursively create durability-sensitive parent hierarchies.

### 9.2 POSIX backup

The successful sequence is:

```text
online backup
→ sync database file
→ write and sync manifest
→ verify staging bundle
→ sync staging directory
→ atomic rename
→ sync output root
→ success
```

### 9.3 POSIX restore

The successful sequence is:

```text
copy temporary
→ sync temporary
→ verify temporary
→ no-clobber hard link
→ sync destination parent
→ unlink temporary
→ sync destination parent
→ success
```

Any failed sync prevents an OK result. If publication occurred before a later
sync failure, the published object remains quarantined for manual inspection;
the tool does not automatically overwrite or claim success.

### 9.4 Windows

Windows performs available regular-file flush/fsync and preserves atomic
no-clobber publication. It records and prints
`atomic-process-crash`, not `power-loss-posix`. It does not fake a directory
`fsync` guarantee.

## 10. Root CI layering

The workflow order is:

1. recursive checkout and gitlink assertions;
2. fixed Compose setup;
3. `python -S` standard-library root unit tests;
4. config-only validation, bootstrap, and standard-library runtime integration;
5. backend venv and targeted backend regressions;
6. fixed Node/pnpm frontend regressions, typecheck, and lint;
7. committed-tree image build and provenance inspection;
8. runtime privilege, mount, and secret checks;
9. formal startup contract;
10. state-lane, restore, and durability checks;
11. Gitleaks committed-tree scan.

The workflow semantic test no longer imports PyYAML. A small standard-library
step-block extractor verifies unique named steps, exact commands, SHA/version
pins, and relative ordering. GitHub itself remains responsible for full YAML
syntax parsing.

Failures are categorized as root, runtime configuration, backend, frontend,
build provenance, privilege, formal startup, state recovery, secret scan, or
external exchange availability.

## 11. Frontend disappeared-target behavior

`deleteTradeMulti`, `cancelOpenOrderMulti`, and `reloadTradeMulti` use the
existing `getBotOrThrow` behavior. A missing captured target rejects without an
API call and never falls back to the active Bot. UI callers surface that the
operation did not execute and the target is unavailable.

Tests cover target removal during confirmation, active-Bot change, no fallback,
visible failure, and unchanged correct routing when the target remains present.

## 12. Error handling and confidentiality

Errors may identify service, operation, stage, durability level, schema version,
or destination existence. They must not print secret values, JWT/WS tokens,
database rows, or complete trade/order content.

All launch, restore, and durability failures are fail closed. Emergency stop and
inspection remain available.

## 13. Acceptance criteria

The Draft PR can become Ready only when:

1. all six Important findings have RED-to-GREEN regression evidence;
2. the frontend silent no-op is fixed;
3. `python -S` root gates pass before backend install;
4. backend and frontend regression/type/lint gates pass;
5. committed-tree build and provenance validation pass;
6. all formal services pass the dynamic-UID local startup contract;
7. Research becomes healthy;
8. cross-service restore fails before any write;
9. POSIX durability-order and injected-failure tests pass;
10. Windows reports and meets the weaker approved durability contract;
11. Gitleaks scans all committed trees successfully;
12. a final remote recursive fresh clone is clean;
13. a new complete Root Safety run is green;
14. online dry-run acceptance has succeeded at least once;
15. final independent whole-branch review reports no Critical or Important
    findings.

Converting Draft to Ready does not authorize merging. Merge remains a separate
explicit user decision.

## 14. Implementation sequence

1. Formal userdata, strategy, and Research mount contract.
2. Dynamic-UID formal startup contract.
3. Remove `create/start/restart` and narrow safe `up`.
4. Committed-tree build context and image provenance.
5. Service-lane backup/restore and schema 2.
6. Durability policy B.
7. Standard-library root CI layering.
8. Frontend disappeared-target observable failure.
9. Integrated Root Safety, remote recursive checkout, online dry-run acceptance,
   and final whole-branch review.

Each implementation task follows test-first RED, minimal GREEN, local
verification, implementer self-review, and independent specification/code-quality
review before the next task begins.
