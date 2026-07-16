# Runtime Registry v2 Phase 2C Task 7B Local Acceptance Report

**Acceptance date:** 2026-07-17

**Status:** local implementation and independent review accepted. Backend PR #9 is
merged. Root exact-SHA Root Safety, merge and fresh recursive checkout remain required
before closure.

**Scope:** persisted launch authority, Attempt-owned State Allocation generation,
lease-fenced State preparation, internal typed Supervisor assembly and fail-closed
production boundaries.

## 1. Accepted local outcome

Task 7B closes the gap between the offline Task 7A fixture and repository-owned launch
authority. The implemented path now provides:

- separate prepared and active Backend authority reads under the exact Job lease;
- an immutable Runtime Attempt binding for State Allocation ID and generation;
- restart-safe recovery of the exact Attempt material rather than reconstruction from
  mutable current records;
- a Root preparation adapter that accepts typed authority only and rejects mappings;
- exact evidence, image, State, Secret, material, network and Snapshot correlation;
- an active Driver resolver keyed by exact `DriverIdentity` and launch-authority digest;
- a second active database fence before each Driver action;
- resource cleanup before any durable healthy, blocked or failed result is recorded;
- an internal typed assembly seam that is not connected to the public CLI;
- Alembic 0008 fail-closed guards for unprovable legacy State generation and unsafe
  downgrade;
- a PostgreSQL `NOWAIT` quiescence gate that prevents migration/write TOCTOU without
  participating in a table-lock cycle.

Template revocation has two explicit meanings. A revoked template prevents a new
Attempt. Once `begin_attempt()` has frozen an Attempt, a later template status change
does not silently cancel it. Cancellation requires an explicit Job, Instance or Attempt
fence transition. Payload, digest, component commits, State generation and Secret
versions remain exact throughout.

## 2. Production boundary

Task 7B does not enable a production Runtime Supervisor. The authoritative flags remain:

```text
PRODUCTION_ASSEMBLY_ENABLED=False
INTERNAL_PERSISTED_ASSEMBLY_SEAM_AVAILABLE=True
HOST_RUNTIME_MUTATION_BRIDGE_ENABLED=False
```

Both `run` and `reconcile-once` still exit with code 78 and
`runtime_supervisor_not_enabled` before Backend import, database access, Job claim or
Driver construction. No exchange connection, order, live-trading write, production
Docker Runtime lifecycle or destructive State recovery was executed.

## 3. Backend result

The reviewed Backend feature commit is:

```text
644ff1327c236bd3c039ee304a6cb41778d4f0ba
feat(runtime): persist active launch authority
```

Backend publication:

```text
PR #9  https://github.com/xrunmasterx/freqtrade/pull/9
merge  c5730bbc5fa7c97a8c93d92b25ddfd9e80a8f7c4
```

Alembic 0008 acquires a single fail-fast quiescence gate before every binding guard,
backfill or DDL statement:

```text
runtime_instances, runtime_spec_revisions, state_allocations
  -> EXCLUSIVE MODE NOWAIT
runtime_attempts
  -> ACCESS EXCLUSIVE MODE NOWAIT
```

Any conflict returns SQLSTATE `55P03` and
`runtime_attempt_state_binding_quiescence_failed`; the complete migration transaction
rolls back. This replaces an earlier waiting lock sequence that could deadlock with the
real registration order `State -> RuntimeSpec -> Instance`.

## 4. Automated local acceptance

| Gate | Result |
|---|---:|
| Root persisted-authority and Driver-focused suite | 335 passed, 8 declared environment skips |
| Root full `unittest discover` | 875 passed, 14 declared platform/environment skips, 359.789 seconds |
| Backend Platform without PostgreSQL URL | 760 passed, 76 declared PostgreSQL/environment skips |
| Backend Platform with isolated PostgreSQL 17 | 835 passed, 1 pre-existing restricted-role URL skip |
| PostgreSQL migration suite | 61 passed, zero skips |
| New two-connection PostgreSQL concurrency cases | 3 passed |
| Ruff on affected Backend and Root Python | passed |
| Alembic offline 0007-to-0008 SQL | passed |
| Root and Backend `git diff --check` | passed |
| Independent reviews after reproduced fixes | P0 0, P1 0 |

The isolated PostgreSQL acceptance used a loopback-only PostgreSQL 17 container with
`tmpfs` data. It was removed by exact test-container identity after the tests. The one
remaining Backend skip requires the separately provisioned restricted Supervisor role;
GitHub Root Safety must execute that selector with zero PostgreSQL skips before closure.

## 5. Reproduced failures and repairs

The review process reproduced and repaired the following material defects:

1. Active validation originally reused the prepared-template revoked gate and therefore
   treated a later template revocation as an implicit Attempt cancellation.
2. Root conversion and full-object comparison repeated the same incorrect revocation
   behavior after Backend was repaired.
3. State Allocation generation initially existed only in process memory and could not
   be proven after restart; 0008 now stores it on the Attempt.
4. The first 0008 downgrade deleted Attempt-owned binding evidence; populated downgrade
   is now rejected before any destructive DDL.
5. Legacy generation greater than one was incorrectly projected backward as historical
   evidence; only the provable generation-one legacy case is migrated automatically.
6. A guard followed by a waiting table lock allowed an Attempt insert TOCTOU.
7. The first table-lock repair inverted the real registration write order and could
   deadlock. The final `NOWAIT` quiescence gate fails immediately and cannot form a
   waiting cycle.
8. Root resource cleanup could occur after a durable terminal result; the Reconciler
   now releases all launch resources before recording that result.

No failing gate was bypassed or weakened. Every accepted finding received a focused
regression test.

## 6. Remaining publication acceptance

Task 7B is not closed until all of the following are complete:

1. merge the Backend PR and verify Backend `main` at the exact reviewed merge;
2. update the Root `freqtrade` gitlink to that Backend `main` commit;
3. publish the reviewed Root commits and run exact-head Root Safety;
4. require the PostgreSQL and restricted-role selectors to report zero skips;
5. record the final workflow URL and exact Root SHA in the closure report;
6. merge the Root PR and verify a fresh recursive checkout.
