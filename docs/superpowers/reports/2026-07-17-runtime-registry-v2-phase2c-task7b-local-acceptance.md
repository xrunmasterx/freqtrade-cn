# Runtime Registry v2 Phase 2C Task 7B Local Acceptance Report

**Acceptance date:** 2026-07-17

**Status:** implementation, independent review and the Root code exact-SHA safety run
are accepted. Backend PR #9 is merged. The report commit must pass its own Root Safety
before Root PR #11 is merged and verified by a fresh recursive checkout.

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
| Root full `unittest discover` | 875 tests run, 14 declared platform/environment skips, 359.789 seconds |
| Backend Platform without PostgreSQL URL | 760 passed, 76 declared PostgreSQL/environment skips |
| Backend Platform with isolated PostgreSQL 17 | 835 passed, 1 pre-existing restricted-role URL skip |
| PostgreSQL migration suite | 61 passed, zero skips |
| New two-connection PostgreSQL concurrency cases | 3 passed |
| Ruff on affected Backend and Root Python | passed |
| Alembic offline 0007-to-0008 SQL | passed |
| Root and Backend `git diff --check` | passed |
| Independent reviews after reproduced fixes | P0 0, P1 0 |
| Root Safety on code SHA `56a4ccd6d24b69316e2914e3a3da08356c14069a` | all 36 primary steps passed |
| Root Safety standard-library suite | 875 tests run, 12 declared CI environment skips |
| Root Safety PostgreSQL integration | 234 passed, JUnit zero skips |
| Root Safety restricted Supervisor repository lifecycle | 15 passed, JUnit zero skips |
| Root Safety Secret scan | 20 reviewed fingerprints, zero unignored findings, one injected leak detected |

The isolated PostgreSQL acceptance used a loopback-only PostgreSQL 17 container with
`tmpfs` data. It was removed by exact test-container identity after the tests. GitHub
Root Safety separately provisioned the restricted Supervisor role and executed its
repository lifecycle selector with zero skips.

The accepted code-head workflow is:

```text
run  https://github.com/xrunmasterx/freqtrade-cn/actions/runs/29544612027
job  https://github.com/xrunmasterx/freqtrade-cn/actions/runs/29544612027/job/87774001301
SHA  56a4ccd6d24b69316e2914e3a3da08356c14069a
```

The workflow executed all 36 primary steps. In particular, it ran the PostgreSQL
selectors rather than skipping them, completed the restricted-role transaction and
denial probes, verified the dynamic-UID runtime contract, and scanned a fresh archive of
the Root plus all three submodules. The Secret gate first reproduced exactly 20 reviewed
fixture fingerprints, then reported no unignored leaks, and finally detected a random
64-character `api_key` mutation as one leak.

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
9. Linux Root Safety exposed three State recovery fixtures that inherited permissive
   temporary-directory modes; the fixtures now establish the production-required
   `0700` invariant explicitly without weakening the production check.
10. The least-privilege gate initially interpreted table-level `UPDATE` as effective
    access to every column and used a pre-0008 Attempt fixture. The gate now checks the
    intended State Allocation columns and creates a fully closed 0008 binding.
11. Disconnecting PostgreSQL from the default bridge before restricted Supervisor TCP
    transactions made the database unreachable. Isolation now occurs after every
    required TCP probe and before the platform-control container is created.
12. Alembic 0008 inserted 68 lines before four reviewed migration-test fixtures, so
    their exact Gitleaks fingerprints moved uniformly. The allowlist and its positive
    and negative audit cases were advanced by exactly 68 lines; no wildcard, path or
    detector exclusion was added.

No failing gate was bypassed or weakened. Every accepted finding received a focused
regression test.

## 6. Final publication acceptance

The implementation publication prerequisites are complete:

1. Backend PR #9 is merged and Backend `main` resolves to
   `c5730bbc5fa7c97a8c93d92b25ddfd9e80a8f7c4`.
2. The Root `freqtrade` gitlink resolves to that exact Backend merge commit.
3. Root code SHA `56a4ccd6d24b69316e2914e3a3da08356c14069a` passed all 36
   Root Safety steps, including zero-skip PostgreSQL and restricted-role selectors.

The publication closes only after this report commit passes its own Root Safety, Root
PR #11 is merged without changing the reviewed head, and a new remote recursive clone
proves the merged Root and all submodule identities are clean and reproducible.
