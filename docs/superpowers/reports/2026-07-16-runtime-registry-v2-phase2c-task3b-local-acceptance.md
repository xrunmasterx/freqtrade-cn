# Runtime Registry v2 Phase 2C Task 3B Local Acceptance

**Acceptance date:** 2026-07-16
**Status:** Local implementation, independent review, local automated acceptance, GitHub
publication, and Root Safety acceptance complete.
**Scope:** Phase 2C Task 3B, Driver-neutral reconciliation state machine.

## 1. Accepted implementation

The accepted Task 3B implementation commit is:

```text
3b24d171868c6c46c1f08f75e1a7572d9ec4270b
feat(runtime): reconcile supervised attempts
```

It contains exactly these implementation and test files:

- `tools/runtime_supervisor/__init__.py`
- `tools/runtime_supervisor/domain.py`
- `tools/runtime_supervisor/reconciler.py`
- `tests/test_runtime_supervisor_reconciler.py`

The implementation supplies a dependency-free reconciliation domain and one bounded
supervisor reconciliation run. It has no Compose, Docker, database, network, daemon, CLI,
or exchange authority.

## 2. Accepted behavior

- The pure decision matrix is action-aware for `START` and `STOP`; `retry` is normalized by a
  future composition root.
- `UNKNOWN` always fails closed before identity comparison and performs no Driver mutation.
- Every known present runtime object must match the full identity: project, container, instance,
  attempt, RuntimeSpec digest, state allocation, image, and canonical network tuple.
- An active persisted Attempt is reconciled before any new candidate Attempt is prepared.
- A terminal Attempt is only an identity gate. A present terminal runtime is blocked and is never
  adopted; its identity is checked again immediately before `begin_attempt()`.
- A candidate runtime that is already present is blocked even when labels appear exact.
- A candidate uses the exact repository-prepared Attempt ID; `begin_attempt()` precedes exactly
  one launch attempt.
- Active Attempt revalidation must preserve both the complete Driver identity and the exact
  persisted resolved material. Material drift blocks with `revalidated_material_mismatch` before
  State, Secret, Snapshot, or Driver operations.
- Secret contexts close on compilation, repository, Driver, and result-recording failures.
- The Task 4 compiler and concrete Driver, Task 6 ambiguous/health recovery, and Task 7 daemon
  remain explicit future work.

## 3. Independent review

Two independent read-only reviews were run against the complete Task 3B change set.

| Review | Initial result | Final result |
|---|---|---|
| Architecture and security | Critical 0, Important 0, Minor 0 | Ready |
| Code and tests | Critical 0, Important 1, Minor 0 | Ready after correction and re-review |

The code/test review found that an active Attempt could be revalidated with a different
`resolved_material` while retaining the same Driver identity. The correction adds an exact
material gate bound to the active Attempt and a regression test proving no State, Secret,
Snapshot, inspection, or launch operation occurs after the mismatch.

## 4. Local automated acceptance

All following commands ran after the material-drift correction:

| Gate | Result |
|---|---:|
| Task 3B reconciliation suite | 30 passed |
| Driver + State + Secrets + Task 3B focused suite | 106 passed, 3 declared platform skips |
| Root full suite | 574 passed, 8 declared platform/environment skips, 322.696 seconds |
| Ruff for Task 3B source and tests | passed |
| `git diff --check` | passed |

The full Root suite ran with:

```text
python -S -m unittest discover -s tests -p "test_*.py" -v
```

No acceptance command placed an order, performed an exchange write, or invoked a real Docker
lifecycle action.

## 5. GitHub publication and Root Safety evidence

The reviewed Backend and Root branches were published in that order:

- Backend draft PR [#3](https://github.com/xrunmasterx/freqtrade/pull/3),
  `feat(runtime): repair supervisor lifecycle contracts`, exact Backend SHA
  `ccaf070a6cfbfd6cf76b5947caf0b2cdbf8ceffc`.
- Root draft PR [#4](https://github.com/xrunmasterx/freqtrade-cn/pull/4),
  `feat(runtime): reconcile supervised attempts`, exact Root SHA
  `a4cea844e356c2a7aa63f88f0334dc274d874ab3`.

Root Safety run
[29476423671](https://github.com/xrunmasterx/freqtrade-cn/actions/runs/29476423671)
completed successfully against the exact Root SHA above. All functional steps 1–35 passed,
including standard-library and bootstrapped Root tests, Backend and FreqUI P0 regressions,
Compose rendering and integrated image builds, PostgreSQL schema and integration tests,
least-privilege checks, runtime UID/secret/mount checks, and committed-tree secret scanning.

This report correction is documentation-only. Root Safety triggered by this report-bearing
commit is the final authoritative check for the current PR head; it does not alter the accepted
code or claim an impossible self-referential SHA.

## 6. Repository state and next boundary

The Root code commit intentionally does not update the `freqtrade` gitlink. The isolated
Backend worktree remains at reviewed Task 3A commit
`ccaf070a6cfbfd6cf76b5947caf0b2cdbf8ceffc`, while the Root commit continues to record
`3bfcb49f3f5388ad4ed6525e22be8a54e0e736b8`. This is the expected reviewed delta until the
separate Backend/Root publication sequence is explicitly performed.

The next implementation boundary is Task 4A: a pure, closed-policy `LaunchSnapshot` compiler.
