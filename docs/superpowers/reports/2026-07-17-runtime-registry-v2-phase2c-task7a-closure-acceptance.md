# Runtime Registry v2 Phase 2C Task 7A Closure and Acceptance Report

**Acceptance date:** 2026-07-17

**Status:** Task 7A offline Supervisor foundation implemented, independently
reviewed, published, accepted by GitHub Root Safety, and merged to Root `main`.
Production Runtime Supervisor assembly and online runtime acceptance remain disabled.

**Scope:** Phase 2C Task 7A: serial Supervisor daemon contracts, repository lease
recovery, process-bound single-writer authority, typed fail-closed command surfaces,
pure offline paper-probe acceptance, and publication gates.

## 1. Accepted outcome

Task 7A establishes the control-plane foundation needed to assemble a future Runtime
Supervisor without authorizing that production assembly today. The accepted code now
provides:

- one serial daemon that retains at most one active lifecycle Job;
- renewal-before-reconciliation and monotonic lease-generation fencing;
- deterministic rediscovery of an already exposed stale Job before newly expired or
  pending work;
- process poison after ambiguous repository, identity, lease, or reconciliation
  failures;
- an owner-protected process lock and an irreversible, exact-lock-bound Docker writer
  guard;
- guarded Safe Compose and access-network mutation boundaries;
- a public pure renderer from the exact `LaunchSnapshot` and launch authority to the
  expected `RenderedContainerPolicy`;
- an offline Bitget Spot paper-probe acceptance that validates committed material,
  fixed policy, three versioned Secret mounts, one writable State mount, no published
  port, and `dry_run: true` without executing a runtime action;
- stable `run` and `reconcile-once` production entry points that fail closed with exit
  code 78 and `runtime_supervisor_not_enabled`;
- stable typed `start`, `stop`, `retry`, and `retire` CLI contracts that also fail
  closed before Backend imports, database credentials, database connections, or Job
  creation while production assembly is disabled;
- a Root Safety acceptance proving a valid disabled-period `start` leaves the
  lifecycle Job count unchanged.

No Task 7A code connects to an exchange, submits an order, starts a dynamic production
runtime, or authorizes live trading.

## 2. Production boundary

The following machine-readable statements are the authoritative Task 7A production
boundary:

```text
production_assembly_status=not_enabled
dynamic_runtime_started_by_supervisor=false
production_state_recovery_verified=false
production_secret_version_provisioning_verified=false
production_deployment_topology_verified=false
```

The offline acceptance proves Supervisor-side compilation, material identity, mount
identity, and policy validation. It deliberately reports
`secret_runtime_readability_verified=false`: its disposable Secret fixture does not
claim that a production runtime user has read production Secret material.

The seven production blockers in `docs/operations/runtime-supervisor.md` remain
binding. Closing Task 7A does not enable `_assemble_supervisor()`, activate a Worker,
create a lifecycle Job, provide a host runtime-management bridge, retire compatibility
services, or authorize online paper or live acceptance.

## 3. Published commits and pull requests

Backend publication:

```text
PR #7  https://github.com/xrunmasterx/freqtrade/pull/7
merge  df0b7f5cc798d7859267289724dbc3b2b6e0b0b9

PR #8  https://github.com/xrunmasterx/freqtrade/pull/8
merge  f57370cb7642dadcf2e8499edc870fbf6c41c3e4
```

The Backend changes add stale-Job rediscovery priority, the deterministic composite
index `(status, failure_code, completed_at, job_id)`, direct populated
`0005 -> 0006 -> 0005 -> head` migration coverage, and independent owner and generation
fence assertions.

Root publication:

```text
PR #9  https://github.com/xrunmasterx/freqtrade-cn/pull/9
merge  10ddb1dd8fc98518cbc6c9eb0327874ed9e38180
```

Root `main` records Backend merge `f57370cb7642dadcf2e8499edc870fbf6c41c3e4`
as the exact `freqtrade` gitlink.

## 4. Automated acceptance

| Gate | Result |
|---|---:|
| Root focused Task 7A suite | 168 passed, 2 declared environment skips |
| Fingerprint audit plus Root Safety contract suite | 81 passed |
| Root full local `unittest discover` | 805 passed, 13 declared platform/environment skips, 365.910 seconds |
| Backend focused repository/migration suite | 155 passed, 52 local PostgreSQL-only skips |
| GitHub PostgreSQL integration selector | 218 passed, zero skips, 25.42 seconds |
| Ruff on every affected Python file | passed |
| Root and Backend `git diff --check` | passed |
| Fresh recursive unfiltered leak scan | 20 reviewed findings, expected status 1 |
| Exact fingerprint audit | passed |
| Fresh recursive filtered leak scan | zero findings, status 0 |
| Final independent reviews | P0 0, P1 0, P2 0, P3 0 |

Local PostgreSQL tests were explicitly reported as skipped because the Windows host did
not provide `PLATFORM_TEST_POSTGRES_URL`. They were not accepted on that basis. GitHub
Root Safety supplied PostgreSQL 17, executed all selected tests, and enforced a JUnit
zero-skip assertion.

The final successful Root Safety run was attached to Root PR head
`9947e2f7f92c9e758e487d9c2b8afc8bb3a096d7`:

```text
https://github.com/xrunmasterx/freqtrade-cn/actions/runs/29528479476
```

All 42 workflow steps completed successfully. The offline receipt recorded
`dry_run=true`, `exchange=bitget`, `product=spot`, `published_ports=0`,
`runtime_action_executed=false`, three Secret mounts, one writable mount, and
`secret_runtime_readability_verified=false`.

## 5. Failure discovery and correction evidence

The publication gate was allowed to fail closed and reveal real defects. No failing
gate was bypassed or weakened.

1. The first PostgreSQL run showed that an old Worker carrying both an old owner and
   old generation is rejected by the owner gate first. The test was corrected to prove
   both independent contracts: old owner produces `lease_owner_mismatch`, and the
   winning owner with an old generation produces `lease_generation_mismatch`.
2. The next run reached the final Secret scan and detected four stale reviewed
   fingerprints after migration-test insertions moved existing fixtures. A fresh
   recursive scan proved the finding content was unchanged and the four exact line
   identities were updated.
3. The next run correctly failed an earlier root-unit contract that still expected the
   old fingerprint lines. The positive assertions were updated to the four new lines,
   while all four old lines were added as negative assertions.
4. The final exact-head run passed the root-unit gate, unfiltered fingerprint audit,
   filtered zero-finding scan, PostgreSQL zero-skip gate, lifecycle no-Job probe, and
   every remaining Root Safety stage.

## 6. Independent review

Three independent read-only reviewers examined the Backend transaction changes, Root
daemon and security boundaries, and offline Snapshot acceptance. Review findings that
were reproduced included stale-Job starvation, parameterized partial-index planning,
migration boundary coverage, incorrect lifecycle database authority, disabled-period
pending intent replay, detached offline command projection, Secret-readability
overstatement, and AST dependency-gate bypasses.

Every reproduced finding was repaired and retested. Final reviews reported:

```text
P0=0
P1=0
P2=0
P3=0
```

## 7. Closure statement

Phase 2C Task 7A is closed as an offline, fail-closed Supervisor foundation. The merged
result is suitable for continued development of the seven explicitly listed production
blockers. It is not a production Supervisor, does not dynamically run a Bot, and does
not expand the authorization for exchange or trading operations.
