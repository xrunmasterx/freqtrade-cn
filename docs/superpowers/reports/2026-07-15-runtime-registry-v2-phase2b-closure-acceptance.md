# Phase 2B RuntimeSpec Compiler Closure and Acceptance Report

**Acceptance date:** 2026-07-15  
**Status:** Implementation and acceptance complete; GitHub merge pending  
**Scope:** Phase 2B Tasks 1-7, including the Task 7 contract-completion plan

## 1. Outcome

Phase 2B now provides one trusted path from committed platform artifacts to a
deterministic, immutable RuntimeSpec and a stopped, registered RuntimeInstance.
The accepted path is intentionally narrower than a runtime supervisor:

- it validates exact committed Git blobs and component gitlinks;
- it publishes one reviewed AdapterTemplate revision;
- it atomically ensures the exact Catalog revision, one StateAllocation, three
  stable SecretReferences, one RuntimeSpec, one stopped RuntimeInstance, and one
  audit event;
- it exposes only the closed `validate`, `publish`, `register-paper-probe`,
  `compile`, and `status` operator commands;
- it does not provision state, resolve secret versions, start a Bot or Worker,
  create a lifecycle job, access an exchange, or place an order.

The accepted paper probe remains fixed to Digital Assets, Spot, Bitget, paper
mode, and `SampleStrategy`. Both the committed trading configuration and the
safety policy require exact boolean dry-run behavior.

## 2. Reviewed revisions

| Repository boundary | Base or prior identity | Accepted implementation identity |
|---|---|---|
| Root PR | `5a97ccb993a0d86db88e3fff8a56bd5ed65648fe` | `38cc1b5376ada530f7f7a784fe3bd29d0b25e49c` |
| Backend PR | `5ce51f64987a4517219fc8f81606336061ecd31d` | `3bfcb49f3f5388ad4ed6525e22be8a54e0e736b8` |
| Root's prior backend gitlink | `9fcab2f21d0fe2af14bfa9d1864d7c5ebb937168` | `3bfcb49f3f5388ad4ed6525e22be8a54e0e736b8` |

The root acceptance run was executed against the exact implementation identity
listed above. This report and the progress update are documentation-only changes
made after that run. The authoritative acceptance for the report-bearing PR head
is the Root Safety check attached to that head; this avoids embedding a
self-referential commit identity in the report itself.

## 3. Automated acceptance evidence

GitHub Root Safety run
[`29400133575`](https://github.com/xrunmasterx/freqtrade-cn/actions/runs/29400133575)
completed successfully against root SHA
`38cc1b5376ada530f7f7a784fe3bd29d0b25e49c`.

All functional steps 1-35 succeeded. The principal results were:

| Gate | Result |
|---|---|
| Root standard-library suite | 518 tests run; 7 declared environment/platform skips; suite passed |
| Backend P0 regressions | 86 passed |
| FreqUI P0 regressions | 50 passed across 7 test files |
| PostgreSQL integration selector | 100 passed; zero skipped |
| Phase 2B backend regressions | 170 passed |
| Platform-operator CLI acceptance | Passed, including deterministic replay and invalid-argument completion marker |
| Platform-operator least privilege | Passed, including post-reconciliation checkpoints and final denial probes |
| Platform-control least privilege | Passed, including delegated ACL contamination and reconciliation |
| Runtime image and mount gates | Passed, including unprivileged image, missing-secret fail-closed, read-only inputs, writable state, empty state, and dynamic UID |
| Committed-tree secret scan | Passed: reviewed findings matched exactly, filtered scan was clean, and injected mutation was detected |
| Cleanup | Passed for containers, networks, temporary artifacts, images, and volume-drift assertions |

The PostgreSQL selector writes a JUnit report and fails when its skip count is
non-zero. Its successful result therefore proves that the mandatory PostgreSQL
tests ran against PostgreSQL 17 rather than passing through an unavailable-DB
skip path.

## 4. Defects exposed and closed by online Root Safety

The online gate found test-harness defects that offline tests could not fully
exercise. Each was reproduced, fixed with a focused regression, independently
reviewed, and rerun on a new exact SHA:

1. Compose lifecycle output was mixed with the invalid-argument application's
   output. The probe now captures the immutable full container ID, reads only
   that container's logs, cleans it by ID, and verifies absence before checking
   the exact application contract.
2. Structured-output validation treated the word used in a stable secret
   reference identifier as if it were a secret-value field. Validation now
   parses JSON and checks exact sensitive keys and prohibited path values.
3. PostgreSQL `VACUUM` reports a permission warning but exits successfully when
   it skips an unauthorized table. The MAINTAIN denial probe now uses
   `REINDEX TABLE`, which performs a hard ACL_MAINTAIN failure.
4. The temporary delegated-ACL test role lacked public-schema lookup authority.
   It now receives only the non-grantable `USAGE` required to resolve the test
   objects; no fixed platform role gained authority.
5. The platform-control permission fixtures referenced pre-Phase-2B placeholder
   foreign keys. They now derive the real RuntimeSpec, StateAllocation, and
   AdapterTemplate revisions from the already registered paper probe.
6. Four reviewed Gitleaks fingerprints moved when backend migration tests gained
   lines. Old and new lines were proven byte-for-byte identical and unique; only
   the four exact path/rule/line fingerprints were refreshed. The mutation gate
   continued to detect a newly injected credential.

## 5. Accepted architecture and security invariants

- `register-paper-probe` and `compile` are aliases for one application use case
  and one atomic repository transaction; there is no direct-SQL CLI path.
- RuntimeSpec compilation is deterministic and bound to exact Catalog,
  AdapterTemplate, policy, artifact digest, and component commit identities.
- Replaying identical evidence is idempotent. Reusing a fixed identity with
  conflicting persisted or committed evidence fails closed without partial
  writes.
- The operator role is LOGIN/NOINHERIT and has only the required table SELECT and
  INSERT grants. It has no Registry UPDATE/DELETE/TRUNCATE, lifecycle, attempt,
  endpoint, Runtime Access, secret-version, DDL, sequence, routine, ownership,
  database-create, schema-create, temporary-table, or MAINTAIN authority.
- The one-shot operator container has no host port, ingress network, Docker
  socket, runtime state, secret root, or trading credential. Its filesystem,
  capabilities, entrypoint, network, and mounts are closed by Compose contract.
- Platform-control remains an authenticated, read-only query surface bound to
  loopback port 8090. It is not given the registration repository or lifecycle
  command surface.
- No acceptance action contacted an exchange, performed an exchange write,
  placed an order, started a managed Bot/Worker, or used destructive recovery.

## 6. Independent whole-task review

Three fresh reviews evaluated the complete Task 7 changes rather than only the
last CI fixes:

These were independent review agents in the closure execution session, not
GitHub approval reviews. This section is the durable summary of their results;
an empty GitHub `reviewDecision` at report creation is therefore expected.

| Review | Result |
|---|---|
| Architecture and domain contracts | PASS; zero blocking findings |
| Security and operations boundaries | PASS; zero material findings |
| Code quality, transactions, migrations, and tests | PASS; zero P1/P2 correctness findings |

The reviews confirmed that the Phase 2 paper probe cannot become a bypass for a
future ordinary BotRelease. Production `BotRelease` and `AccountRevision` models
remain a Phase 3 concern; when introduced, an ordinary release must enforce the
already approved invariant of exactly one Market, one Product, one primary
AccountRevision, and one Environment. Phase 2B does not add a `bot_release`
owner kind or a cross-product execution entry point.

## 7. Compatibility and deferred work

Phase 2B does not cut over existing Spot, Futures, or Research runtimes and does
not remove their compatibility listeners. The existing 8081, 8082, and 8083
surfaces remain temporary migration scaffolding until the controlled Phase 2E
cutover.

The next delivery stage is Phase 2C Supervisor and Safe Runtime Driver. Phase 2C
may consume the immutable registration created here, resolve attempt-scoped
secret versions, provision isolated runtime state, and manage lifecycle jobs. It
must not weaken any accepted Phase 2B trust or least-privilege boundary.

## 8. Publication state

At report creation, Backend PR #2 and Root PR #2 are mergeable draft PRs. The
publication closure order is:

1. require the report-bearing Root PR head to pass Root Safety;
2. mark Backend PR #2 ready and merge it first;
3. verify backend main contains the reviewed backend identity;
4. mark Root PR #2 ready and merge it;
5. verify the merged root main from a fresh recursive checkout with no reuse of
   the development worktree's submodule object or worktree state.
