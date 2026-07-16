# Runtime Registry v2 Phase 2C Task 4A Local Acceptance

**Acceptance date:** 2026-07-16

**Status:** Local implementation, independent review, local automated acceptance, Backend
publication, and Root gitlink integration complete. Root publication, GitHub Root Safety,
and Root merge remain pending.

**Scope:** Phase 2C Task 4A, closed launch authority, provider leases, and pure
`LaunchSnapshot` compilation.

## 1. Accepted local implementation

The reviewed local implementation commits are:

```text
Backend d2843d0d4b2fad53b0fcbdf204de8f29d6889355
feat(runtime): persist launch strategy authority

Root 793d54fee4ccec109c0e0be2a48d349684fec493
feat(runtime): compile closed launch snapshots

Root integration eb05fcb215f1988bb0bc9c255d2825ee1e881ef7
chore(runtime): integrate launch authority backend
```

Task 4A now provides:

- Backend-compatible persistence of the exact strategy class while retaining legacy
  RuntimeSpec readability and rejecting a legacy spec at launch compilation;
- one committed, fixed paper-probe executable launch policy rather than identifier-only
  policy references;
- committed-template, policy catalog, material, state, secret, attempt, image, component,
  and Driver identity correlations;
- provider-minted attempt-scoped material, managed-state, and version-pinned secret leases;
- one standard-library-only pure compiler that produces a deterministic
  `LaunchSnapshot` and a complete launch-authority digest;
- typed secret-path environment bindings containing container targets only;
- a typed rendered-container policy validator with fixed hardening and no arbitrary
  Compose mapping ingress;
- `ActiveLaunchAuthorityLease`, which retains the exact three provider leases required by
  Task 4B and revalidates all sources before a runtime action;
- an independent provider-held projection of every managed-state mount field, preventing
  a modified public DTO from changing the writable host source.

No Task 4A implementation starts Docker, accesses an exchange, places an order, or performs
an online runtime mutation.

## 2. Closed safety properties

The accepted local code fails closed for:

- arbitrary or shell command injection;
- mutable/custom mapping compiler ingress;
- subclass-based equality spoofing for DTOs, strings, tuples, paths, and scalar fields;
- policy or catalog digest drift;
- incomplete, extended, wrong-version, or non-fixed paper-probe templates;
- unapproved environment names and secret path aliases;
- raw Secret values or Secret host paths in argv, ordinary environment, digest, or repr;
- host networking, host PID/IPC, privileged mode, devices, added capabilities, published
  ports, writable inputs/secrets, missing capability drop, missing no-new-privileges, and
  writable root filesystems;
- material role/policy drift, overlapping mount targets, Secret targets outside
  `/run/secrets`, and State targets outside the managed layout;
- health probes invoking a shell and health/resource values above platform bounds;
- closed, changed, copied, forged, or retagged provider leases;
- forced modification of a minted State mount source or provenance metadata;
- partial lease cleanup when `KeyboardInterrupt`, `SystemExit`, or a normal close error is
  raised.

## 3. Independent review

Two independent read-only reviewers examined the final local implementation.

| Review | Findings during review | Final result |
|---|---|---|
| Architecture and security | Nested equality, template mapping/schema, live-lease handoff, repr, scalar subtype, and State provenance issues | Critical 0, Important 0, Minor 0 |
| Code and tests | Closed-policy drift, scalar/tuple equality spoofing, control-exception cleanup, and State mount DTO tampering | Critical 0, Important 0, Minor 0 |

Every reproducible finding was corrected, covered by a regression test, and independently
retested. The final reviewers specifically repeated the closed-policy mutations,
`AlwaysEqualStr`/`AlwaysEqualTuple` attacks, incomplete-template path, control-exception
cleanup, and real `ManagedStateProvider` mount tampering.

## 4. Local automated acceptance

The following gates passed against the final local file contents:

| Gate | Result |
|---|---:|
| Pure Snapshot + lease + policy + Driver suite | 55 passed |
| State + Snapshot + preparation lease + policy + Driver suite | 102 passed, 2 declared platform skips |
| Complete Task 4A / Supervisor focused suite | 234 passed, 6 declared platform skips |
| Backend RuntimeSpec/compiler/repository suite | 377 passed |
| Root full `unittest discover` suite | 658 passed, 11 declared environment/platform skips, 399.008 seconds |
| Post-format affected Root suite | 155 passed, 1 declared environment skip |
| Ruff check and format check for every changed Python file | passed |
| Root and Backend `git diff --check` | passed |
| Final architecture/security review | Critical 0, Important 0, Minor 0 |
| Final code/test review | Critical 0, Important 0, Minor 0 |

The 11 full-suite skips were inspected individually:

- nine POSIX-only permission, rename, symlink-parent, SQLite durability, and managed-state
  durability tests on Windows;
- one Backend lazy-binding test intentionally unavailable under `python -S`;
- one trading-profile path test requiring bootstrapped Backend dependencies under
  `python -S`.

No Task 4A compiler, provider, or rendered-policy acceptance test was skipped because its
implementation was missing. Windows ACL and share-lock counterparts ran on this host.

## 5. Publication boundary

Backend PR [#4](https://github.com/xrunmasterx/freqtrade/pull/4) merged the reviewed
Backend head `d2843d0d4b2fad53b0fcbdf204de8f29d6889355` into Backend `main` as merge commit
`637fcc661b650b10eec5ad1ebca1a5b6fa29c069`. The Root integration commit records that
exact Backend `main` commit as its `freqtrade` gitlink.

The Root changes are still local evidence only. Task 4A is not yet accepted by Root Safety
or merged to Root `main`.

The required publication sequence is:

1. publish the reviewed Root implementation, integration commit, and this report;
2. run Root Safety against the exact Root PR head with no PostgreSQL skip;
3. merge Root only after the exact-head Root Safety result is green;
4. perform a fresh recursive checkout of merged Root `main` and rerun the final static
   checkout checks.

Task 4B may begin locally only after Task 4A is committed on its isolated branch; production
or GitHub acceptance remains gated by the publication sequence above.
