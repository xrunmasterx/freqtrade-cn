# Phase 2C Task 7B Persisted Launch Authority Design

**Status:** implementation-approved continuation of the Phase 2C master design

**Production boundary:** production assembly remains disabled. This task performs no
Docker lifecycle action, makes no exchange connection, submits no order, and does not
retire the compatibility services.

## 1. Problem

Task 7A proved the Supervisor state machine, the safe Driver boundary and an offline
fixture-based `LaunchSnapshot`. It did not prove that a production Worker can recover
the same authority from PostgreSQL and committed source material after a process
restart.

The current production entry point is therefore correctly closed:

```text
PRODUCTION_ASSEMBLY_ENABLED = False
_assemble_supervisor() -> runtime_supervisor_not_enabled
```

The next required boundary is an immutable, repository-owned launch-authority read
model. It must correlate the current Runtime Instance, RuntimeSpec envelope, committed
Adapter Template, State Allocation and active Secret-version metadata in one database
snapshot. Root-side preparation must then revalidate that snapshot against the exact
committed Git material and construct typed compiler inputs without accepting a caller
mapping.

## 2. Scope

Task 7B delivers two layers:

1. **Backend launch-authority snapshot**
   - one typed immutable read model;
   - one exact repository query bound to the active Job lease and prepared attempt;
   - complete correlation and canonical-envelope validation;
   - no Secret values and no filesystem paths;
   - Supervisor-role PostgreSQL coverage with zero skips in Root Safety.
2. **Root persisted-authority preparation**
   - convert only the typed Backend snapshot into `RuntimeSpecLaunchAuthority`;
   - load the reviewed template, launch policy and committed artifacts from the exact
     root commit;
   - resolve exact attempt/image/state/Secret identities through injected typed ports;
   - hold material, state and Secret leases through snapshot compilation;
   - derive project, container and network identity; never accept those names from a
     public mapping;
   - revalidate the complete authority before every runtime action.

Task 7B does not implement the runtime-mutation bridge, production deployment, online
paper connectivity, Secret rotation, State backup/restore or compatibility-service
cutover. Those remain subsequent tasks.

Before either layer is connected, Task 7B repairs the existing cross-repository Secret
provider identifier drift and adds a lease-fenced State Allocation preparation
transaction. The offline fixture currently hides both production incompatibilities.

## 3. Assumptions and chosen trade-offs

- The first production assembly remains the already approved Bitget Spot paper probe.
  Multi-market generalization is not introduced in this safety-critical slice.
- RuntimeSpec and Adapter Template rows are immutable revisions. Their status and the
  active Secret-version selection may change, so every new attempt is revalidated in
  `begin_attempt()` after filesystem preparation.
- A repository snapshot is resolved in one database transaction. The mutable Job and
  Instance rows are locked first; one deterministic authority statement then reads the
  immutable revisions and current State/Secret metadata. The operation is bound to
  `job_id`, `attempt_id`, lease owner and lease generation, and rejects an expired or
  terminal lease.
  `begin_attempt()` remains the final transactional authority gate. This avoids giving
  the Supervisor UPDATE permission on template/Secret authority tables merely to obtain
  row locks.
- The Supervisor database role receives SELECT on the exact authority tables it must
  inspect. It receives no INSERT, UPDATE, DELETE, TRUNCATE, DDL, ownership or role
  membership on those tables.
- Missing or multiple active Secret versions are not guessed. The authority is not
  launch-ready and fails with a stable, non-secret error.
- The public production command remains disabled after Task 7B. Tests may assemble
  typed dependencies directly, but the CLI cannot claim a Job or call a Driver.
- Root and Backend must use one exact Secret provider ID. A cross-repository contract
  test prevents future drift; aliases are not accepted at the launch boundary.

## 4. Backend read model

The Backend exposes an immutable `PersistedLaunchAuthority` composed of:

- instance identity, owner scope, management mode, environment and optimistic version;
- RuntimeSpec revision ID, canonical payload and payload digest;
- Adapter Template revision ID, canonical payload, digest, status and component commits;
- State Allocation ID, instance binding, layout, provider, status and generation;
- ordered Secret references with provider, class, owner scope, reference status and one
  active version ID.

The repository rejects:

- missing or duplicate instance/spec/template/allocation rows;
- RuntimeSpec envelope or canonical JSON mismatch;
- instance/spec/template/allocation identity drift;
- non-Supervisor management mode or retired instance;
- revoked template for a new launch authority;
- Secret reference set mismatch;
- inactive, foreign-owner or wrong-provider Secret references;
- zero or more than one active version per reference;
- any raw Secret value or source path in the read model.

The query is read-only and deterministic. It does not expose an unscoped
`get_launch_authority(instance_id)` production entry point: instance identity is derived
from the leased Job, while the caller proves the already prepared attempt identity.
Results are ordered by Secret reference ID.

## 5. Root preparation boundary

The Root adapter accepts the typed snapshot as an object with exact fields. A `dict`,
JSON mapping, Pydantic mapping shortcut or deserialized `LaunchSnapshot` is rejected.

Preparation order is fixed:

```text
repository authority snapshot
  -> canonical RuntimeSpec revalidation
  -> committed template/policy/artifact revalidation
  -> exact image identity resolution
  -> deterministic attempt/project/container/network identity
  -> State proof + active mount lease
  -> Secret metadata match + active mount lease
  -> committed material lease
  -> LaunchCompilationAuthority
  -> compile + validate LaunchSnapshot
  -> final lease/authority revalidation
```

Any failure closes every lease already acquired. No Driver, Docker, network mutation or
health probe is called before the final authority passes.

## 6. PostgreSQL authority

`platform_supervisor` must be able to execute the real repository lifecycle with its
own file-backed password:

```text
claim -> renew -> read authority -> prepare attempt ID -> begin attempt
      -> reserve/record health -> terminal transition
```

It may read the exact authority tables:

- `alembic_version`
- `adapter_template_revisions`
- `state_allocations`
- `secret_references`
- `secret_version_metadata`
- `runtime_spec_revisions`

Its existing runtime-table mutations remain unchanged. State preparation adds only
column-level `UPDATE(status, ready_at)` on `state_allocations`; table-level `UPDATE` and
every other Authority write remain forbidden. The test suite proves that the role cannot
mutate any other Authority field and cannot gain DDL, DELETE, TRUNCATE, ownership,
membership or broad schema rights.

Before the first claim, assembly must also prove `current_user` is the exact Supervisor
role and the database is at the unique expected Alembic head. A broad/admin/operator
credential or a stale/ahead/branched schema fails before repository construction.

The expected head is `20260717_0008`. This migration persists the exact State
Allocation ID and generation on every Runtime Attempt. Active launch revalidation uses
that Attempt-owned binding; it never reconstructs the generation from the current
Instance or from process memory.

## 7. State Allocation transaction

The registered paper-probe allocation begins as `reserved`; a filesystem provider alone
cannot make that database authority `ready`. Task 7B therefore adds a fenced preparation
transaction:

```text
reserved -> provisioning -> ready
                       \-> quarantined
```

Every transition is bound to the claimed Job owner and lease generation. After a crash,
the next Worker revalidates the exact existing directory identity and allocation metadata;
it may complete the same provisioning operation or quarantine an inconsistency. It never
deletes, overwrites or silently adopts an unrecognized path. Backup, restore and rotation
remain later operational work.

## 7.1 Prepared and active launch authority

Prepared and active authority are separate repository contracts. The prepared contract
requires that no Attempt exists and serves only `begin_attempt()`. The active contract
locks the exact persisted Attempt under the current Job lease, requires the precise
`starting/launching` state tuple, validates the Attempt-owned resolved material and State
generation, and then rereads current Authority. A reclaimed Job continues to use the
persisted Attempt ID; it does not derive a new ID from the higher lease generation.

`begin_attempt()` is the atomic authorization point for one immutable Attempt material.
The same compilation authority and the same live State, Secret and material leases are
registered under `(DriverIdentity, launch_authority_digest)`. The SafeCompose Driver's
resolver repeats the active database fence and returns that exact
`ActiveLaunchAuthorityLease`; an in-memory registry entry alone is never sufficient.
Future revocation prevents new Attempts. Revoking an already begun Attempt requires an
explicit Attempt cancellation/fence transition and is not inferred from an unlocked
SELECT between two runtime operations.

## 8. Failure and confidentiality contract

- Public errors are stable identifiers and contain no DSN, password, Secret reference
  value, filesystem source path, raw SQL or Docker output.
- Database outage or ambiguous repository result poisons the daemon and causes zero
  Driver calls.
- Authority drift fails closed and creates no attempt unless the final Backend
  transaction independently validates the same material.
- Secret values never enter PostgreSQL, environment variables, logs, receipts or audit
  provenance.

## 9. Acceptance

Task 7B is accepted only when:

1. Backend unit and PostgreSQL tests cover the complete authority mutation matrix.
2. The real `platform_supervisor` role executes the focused lifecycle selector with zero
   skips and cannot mutate authority tables.
3. Root preparation tests reject mappings and every identity drift before Driver use.
4. Lease cleanup is proved for every failure boundary.
5. Root and Backend focused suites, Ruff, `git diff --check` and full Root regression pass.
6. Independent architecture/security/code reviews report no open Critical or Important
   finding.
7. `PRODUCTION_ASSEMBLY_ENABLED` remains `False` and both production commands still
   return exit code 78 without opening PostgreSQL or Docker.
