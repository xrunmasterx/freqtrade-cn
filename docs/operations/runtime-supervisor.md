# Runtime Supervisor operations

## Task 7A Offline Foundation

Task 7A establishes an offline, fail-closed foundation. It does not enable the
production Runtime Supervisor and does not authorize an online paper or live
trading session.

Root Safety runs the following acceptance immediately after producing the
reviewed integrated image:

```text
python -S -m tools.runtime_supervisor.offline_acceptance --root-commit "${GITHUB_SHA}" --image-id "${REVIEWED_IMAGE_ID}"
```

The acceptance binds the exact root commit and reviewed image ID, loads the
committed Bitget Spot paper-probe template, SampleStrategy, launch policies and
material digests, creates disposable state and non-production secret fixtures,
compiles and validates one `LaunchSnapshot`, then renders and validates its
container policy without invoking a runtime manager. Its receipt proves exact
`dry_run: true`, zero host-published ports, one writable state mount and three
read-only secret mounts. Every rendered mount source must exist while its
material or secret lease is held. The disposable secret fixture proves
Supervisor-side metadata and source integrity only; production runtime-user
readability remains unverified. Any missing or mismatched input fails the step.

The acceptance does not start the daemon, connect to an exchange, submit an
order, or grant production lifecycle authority. No real order is submitted,
and no exchange write operation is attempted. A passing receipt is build
evidence only; it is not online acceptance or cutover approval.

## Production entry points remain fail-closed

The command surface is intentionally present before its production dependency
assembly:

```text
python -m tools.runtime_supervisor run
python -m tools.runtime_supervisor reconcile-once
```

`PRODUCTION_ASSEMBLY_ENABLED` remains false and `_assemble_supervisor()` has no
production implementation. Both commands therefore exit with code 78 and the
stable error `runtime_supervisor_not_enabled`. They must do so before opening a
database connection, claiming a job, preparing state or secrets, or invoking a
runtime Driver. Operators must not work around this gate.

## Lifecycle CLI boundary

`start`, `stop`, `retry` and `retire` retain their closed typed argument
contracts, but Task 7A rejects every valid invocation with exit code 78 and
`runtime_supervisor_not_enabled`. Rejection occurs before Backend imports,
database credentials, a connection or a lifecycle Job. This prevents an old
trading intent from remaining pending during the disabled period and executing
after a future cutover.

`status` is read-only and reports paper-probe registration status only; Task 7A
does not expose lifecycle Job status. A future change that enables lifecycle
mutations must add an operator-specific least-privilege database boundary and
define activation epoch, expiry and explicit reauthorization semantics before
accepting any Job. It must not give the Operator the Supervisor credential.

## Serial ownership, lock and poison policy

The safety contract is one process, one Worker, and one runtime-mutation writer.

- The process must hold the absolute, owner-protected
  `/run/freqtrade-runtime-supervisor/supervisor.lock`. A second process fails
  closed.
- The `SupervisorDockerWriterGuard` is activated by that exact held process
  authority. Revocation or authority mismatch blocks mutation before the
  Driver runner.
- The daemon processes one active job at a time and renews the current lease
  before reconciliation. Lease loss clears local ownership and forbids further
  mutation under the old generation.
- Unexpected repository, reconciliation, identity or invariant failures poison
  the daemon. A poisoned daemon must be replaced; it must not resume mutation
  in-process.
- Stale leases are explicitly rediscovered and reclaimed with a higher lease
  generation. The higher generation fences the previous Worker.

These controls reduce split-brain risk but do not by themselves make the
production assembly complete.

## Seven production blockers

Production must remain disabled until all seven blockers are closed by reviewed
code, tests and operational evidence:

1. **Production dependency assembly.** Implement `_assemble_supervisor()` with
   the exact SQL repository, reconciler, preparation ports, compiler, network
   driver and safe runtime Driver; only then may the enable flag change.
2. **Production database wiring.** Provision the Supervisor-only PostgreSQL
   role and secret, verify the exact schema revision, exercise claim, lease,
   attempt and terminal transactions against PostgreSQL, and define database
   outage recovery without broadening privileges.
3. **Persisted launch-authority assembly.** Reload and revalidate the exact
   RuntimeSpec revision and attempt material, resolve reviewed image, policy,
   state, secret and network identities, then compile the only admissible
   `LaunchSnapshot`. No caller-supplied runtime mapping may enter this path.
4. **Single-writer deployment boundary.** Deploy exactly one Supervisor replica
   with a durable protected lock and one audited runtime-mutation bridge. Prove
   that restart, lock loss, guard revocation and competing replicas cannot
   produce a second writer.
5. **State and secret operations.** Complete production provisioning, ownership,
   rotation, backup and non-destructive recovery procedures for per-instance
   state and versioned secret mounts without placing secret values in the
   database, environment, logs or receipts.
6. **Observability and emergency operations.** Add bounded job, lease, attempt,
   health and failure-latch telemetry; define alerts and retained evidence; and
   verify database-down status, inspect, logs and exact-identity emergency stop
   without enabling emergency start, rebuild or deletion.
7. **Controlled cutover and authorized acceptance.** Rehearse backup, rollback
   and identity-bound migration; pass exact-SHA Root Safety and a fresh recursive
   checkout; then perform separately authorized online paper acceptance with no
   real orders before retiring the 8081/8082/8083 compatibility services.

Closing an individual blocker does not authorize production enablement. The
enable flag changes only in the reviewed change that closes and verifies all
remaining blockers.

## Recommended production topology

The recommended target is an independent `runtime-supervisor` control-plane
container, separate from `platform-control` and every Bot or Research Worker:

- run exactly one Supervisor replica with no HTTP listener and no published
  port;
- give it only the Supervisor database role, read-only reviewed policy and
  provenance inputs, its protected lock/coordination mount, and the narrowly
  scoped state and secret preparation roots it needs;
- do not give `platform-control`, FreqUI, Bots or Research Workers any runtime
  mutation authority;
- keep each managed Bot or Worker in its own instance container and networks;
  attach only the verified `platform-control` identity to an instance access
  network when policy requires it;
- keep exchange credentials inside the target runtime's read-only secret mounts;
  the Supervisor control-plane container itself has no trading account and
  submits no orders.

An independent container still needs a reviewed way to reach the host runtime
manager. Do not solve that boundary by casually mounting a general host socket.
Use a separately reviewed, auditable host-local broker or dedicated rootless
runtime endpoint whose accepted operations preserve the existing exact-snapshot
and exact-identity Driver contract. Until that bridge and the single-writer proof
exist, blocker 4 remains open and the current entry points stay disabled.

## Current operator decision table

| Operation | Task 7A status |
|---|---|
| Compile and validate the offline paper probe in Root Safety | Supported |
| Create a typed lifecycle database job | Disabled, stable fail-closed |
| Read paper-probe registration status | Supported |
| Read lifecycle Job status | Not supported in Task 7A |
| Run the production Supervisor loop | Disabled, stable fail-closed |
| Reconcile one production job | Disabled, stable fail-closed |
| Online paper connectivity | Separately authorized and not part of Task 7A |
| Live trading or a real order | Not authorized |
