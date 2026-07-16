# Runtime Registry v2 Phase 2C Task 3B Reconciliation State Machine

**Status:** Approved implementation clarification

## 1. Scope

Task 3B adds the driver-neutral reconciliation policy and one bounded reconciliation run.
It consumes narrow structural ports so the root package remains importable under `python -S`
without importing Backend, Pydantic, SQLAlchemy, Compose, or Docker.

Task 3B does not implement the Task 4 snapshot compiler or concrete Driver, the Task 6
health retry/ambiguous-outcome/offline-identity policy, or the Task 7 daemon and CLI.

## 2. Pure decision contract

`retry` is normalized to `START`; `retire` is not a reconciliation action. Decisions are
closed to `adopt`, `launch`, `continue_observing`, `stop_exact`, `already_absent`,
`fail_latched`, and `identity_mismatch`.

Decision order is fail-closed:

1. `UNKNOWN` always returns `fail_latched`, even when its partial labels appear exact.
2. `ABSENT` returns `launch` for `START` and `already_absent` for `STOP`.
3. Every known present state compares the complete identity. Any difference returns
   `identity_mismatch`.
4. `STOP` plus an exact known present object returns `stop_exact`.
5. Exact `START` observations return:
   - `continue_observing` for `CREATED`, `STARTING`, and `RUNNING/STARTING`;
   - `adopt` for `RUNNING/HEALTHY`;
   - `fail_latched` for `RUNNING` with any other health and for `EXITED`.

Complete identity means project name, container name, instance ID, attempt ID, RuntimeSpec
digest, state-allocation ID, exact image ID, and exact canonical network-name tuple.

## 3. Persisted-attempt gate

The repository's latest attempt is inspected before a new candidate attempt ID is prepared.

- An active latest attempt is reconciled against its persisted identity.
- A terminal latest attempt is only an identity gate. It may never be adopted. `ABSENT`
  permits a later `START` candidate; any present or unknown observation is an out-of-band
  resurrection and records `needs_reconciliation` without Driver mutation.
- A claimed `STOP` without an active latest attempt is a repository-contract inconsistency;
  it is blocked without Driver mutation.
- After `prepare_attempt_id()`, the candidate locator must still be `ABSENT`. Any occupied or
  unknown locator is blocked before `begin_attempt()` and before Driver mutation.

These rules prevent an old-attempt container and a new-attempt container from coexisting.

## 4. Launch ordering

The single-run coordinator exposes every trust boundary through narrow structural ports and
enforces this order:

```text
load latest persisted attempt
-> revalidate immutable spec/template/catalog/material
-> inspect persisted identity gate
-> prepare candidate attempt ID
-> revalidate candidate immutable material
-> provision or verify managed state
-> resolve version-pinned secret handles
-> compile an internal LaunchSnapshot through the Task 4 seam
-> inspect the exact candidate identity
-> re-inspect any terminal predecessor identity after the costly preparation window
-> begin_attempt with the exact prepared ID and unchanged resolved material
-> driver.launch
-> classify and record the returned observation when definitive
```

Secret handles are context-managed and close on compilation, repository, Driver, or result
handling failure. A snapshot must carry the exact revalidated identity; mappings are never
accepted or deserialized.

## 5. Side-effect policy

- `adopt`: record the active attempt healthy; no Driver mutation.
- `continue_observing`: retain the active attempt; no Driver mutation or invented result.
- `already_absent`: record an active stop with `exit_code=None`; no Driver mutation.
- `stop_exact`: an exact `EXITED` observation is recorded directly; otherwise invoke only
  `driver.stop(expected_identity)` and record the truthful returned terminal result. A
  non-terminal or ambiguous return is blocked, not guessed.
- `identity_mismatch` and `UNKNOWN`: atomically record reconciliation blocked; no Driver
  mutation. A known, exact definitive failure records the active attempt failed.
- `launch`: write the exact candidate attempt before `driver.launch(snapshot)`. A definitive
  exact healthy result is recorded healthy; a transitional result remains observable for the
  later bounded-health loop; an exact unhealthy/exited/absent result records the attempt failed;
  a mismatched or unknown result is blocked. Task 6 will add ambiguous exception recovery and
  bounded probing.

The coordinator never restarts, deletes, rebuilds, removes, or discovers arbitrary runtime
objects.

## 6. Verification

- Table-driven tests cover the complete action/state/health/identity matrix.
- Orchestration spies prove the exact ordering and latest-attempt gate.
- Tests prove no Driver mutation for unknown, mismatch, terminal resurrection, candidate
  collision, or revalidation/state/secret/compiler failure.
- Tests prove `begin_attempt()` precedes launch and uses the exact prepared ID and unchanged
  resolved-material object.
- Tests prove a terminal predecessor is re-inspected after state/secret preparation and before
  `begin_attempt()` to narrow the out-of-band resurrection race. Final single-writer authority
  remains a Task 7 deployment invariant; the coordinator does not claim a cross-system lock.
- Tests prove all secret handles close on success and every failing boundary.
- Import-purity tests run with `python -S` and forbid import-time I/O.
