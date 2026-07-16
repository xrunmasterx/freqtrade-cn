# Phase 2C Task 7B Persisted Launch Authority Implementation Plan

**Goal:** Close the PostgreSQL and persisted-authority prerequisites for production
Supervisor assembly while keeping every production/runtime mutation entry point
disabled.

## Task 1: Cross-repository provider contract repair

- [x] Add a Root contract test that rejects Backend/Root Secret provider ID drift.
- [x] Select one closed provider ID and update the smaller compatible surface.
- [x] Run Secret, Snapshot, registration and migration regression selectors.
- [x] Commit the contract correction independently.

## Task 2: Backend typed authority snapshot

- [x] Add RED tests for the immutable authority DTO and exact repository correlations.
- [x] Add one read-only repository method that returns the complete typed snapshot and
      binds it to the active Job, prepared attempt ID, lease owner and lease generation.
- [x] Reject canonical-envelope, instance/spec/template/state/Secret/version drift.
- [x] Reject stale/expired/terminal/wrong-instance Job leases before returning authority.
- [x] Run SQLite and PostgreSQL repository selectors.
- [x] Commit the Backend change independently.

## Task 3: Supervisor-role database contract and startup identity gate

- [x] Add RED Root contract tests for the exact read-only authority-table grants.
- [x] Extend the role reconciler with the exact authority read inventory and only the
      fenced `state_allocations(status, ready_at)` column writes.
- [x] Add a PostgreSQL test that logs in as `platform_supervisor`, executes the complete
      focused lifecycle and proves authority-table mutations are denied.
- [x] Verify `current_user`, exact Alembic head and expected schema before any Job claim.
- [x] Keep JUnit zero-skip enforcement in Root Safety.
- [x] Commit Backend/Root role changes separately from preparation code.

## Task 4: State-allocation transactional preparation

- [x] Define and test lease-fenced `reserved -> provisioning -> ready` transitions.
- [x] Define crash recovery for files-created/DB-not-ready without deleting or overwriting
      an existing allocation.
- [x] Latch or quarantine identity drift; never perform destructive recovery.
- [x] Prove the Supervisor role has only the exact column mutations required for these
      transitions.

## Task 5: Root persisted-authority compiler adapter

- [x] Add RED dependency-free tests for typed ingress, canonical RuntimeSpec conversion,
      committed evidence correlation and deterministic identities.
- [x] Implement the minimal production `PreparationPort` adapter with injected typed
      repository/image/state/Secret/material ports.
- [x] Reject raw mappings and caller-supplied project/container/network names.
- [x] Prove all acquired leases close on every exception path.
- [x] Prove final revalidation occurs before a runtime action can be authorized.
- [x] Commit Root adapter/tests independently.

## Task 6: Disabled production assembly seam

- [x] Add a typed internal assembly factory for tests without enabling the public CLI.
- [x] Prove schema mismatch, database outage and authority drift cause zero Driver
      mutations (late drift may retain the required read-only occupancy inspection).
- [x] Prove `run` and `reconcile-once` still fail before Backend import/DB/Docker.
- [x] Update operations documentation and machine-readable boundary flags.

## Task 7: Verification and publication closure

- [x] Run Backend focused unit + PostgreSQL tests and Ruff.
- [x] Run Root focused Task 7B tests and full Root regression.
- [x] Run independent Backend, security and whole-branch reviews; repair real findings.
- [x] Commit the Task 7B report and exact test evidence.
- [ ] Publish Backend first, integrate the reviewed gitlink, then publish Root and run
      exact-SHA Root Safety.
- [ ] Fresh recursive checkout verification.

## Explicit non-goals

- No production enable flag change.
- No Docker lifecycle or network mutation in Task 7B acceptance.
- No exchange connection, trading credential use, order or exchange write.
- No destructive State recovery.
- No retirement or stop of the 8081/8082/8083 compatibility services.
