# Platform control plane operations

## Phase 2A boundary

> **Production platform start/stop is not exposed in Phase 2A.**
>
> **Raw `docker compose up` is unsupported and bypasses review gates.**
>
> **`compose_runtime` remains platform config-only.**
>
> **A Supervisor or dedicated infrastructure launcher must land before production use.**

This document records the reviewed architecture and acceptance procedure. It is
not a production launcher. Phase 2A exposes a read-only platform-control HTTP
surface backed by PostgreSQL; it does not expose Docker lifecycle mutation,
Runtime Access proxying, or start, stop, retry, or retire HTTP operations.

## Architecture and trust boundaries

The control plane has two fixed long-running services. `platform-postgres` is reachable only
on the internal `platform-db` network. `platform-control` joins that database
network plus the dedicated `platform-ingress` bridge, connects as the
least-privileged `platform_control` database role, binds inside its container in
`container_loopback_publish` mode, and is published only on host loopback port
8090. The ingress network contains no database. It exists because Docker does
not realize host-published ports for a container attached only to an internal
network. Platform-control runs as UID/GID 1000 with a read-only root filesystem,
all capabilities dropped, and `no-new-privileges`. It receives no Docker socket,
repository root, runtime state, Bot configuration, strategy, research data,
trading secret, or general secret-root mount.

`platform-operator` is a one-shot command carrier in its own
`platform-operator` profile. It is never started by the long-running `platform`
profile. It receives only the internal database network, its operator database
credential, the complete `.git` metadata directory, and the reviewed template,
policy, and three paper-probe artifact paths. All repository mounts are read-only;
the full worktree, runtime state, secret roots, trading configuration, Docker
socket, host ports, and lifecycle authority are absent.

Normal use starts with a normal recursive checkout; linked-worktree `.git`
indirection is unsupported. The mounted `.git` and reviewed paths must be
readable by UID 1000 and ownership-compatible with Git. CI prepares ownership
only inside its temporary checkout before running the carrier. PostgreSQL must
already be healthy before any database-backed command.

First run `python tools/image_provenance.py build-operator --print-image-id` and
capture its single verified image ID. Only after that command succeeds, create
the fixed Compose alias and invoke the typed surface:

```text
docker image tag <verified-image-id> freqtrade-cn-operator:local
docker compose --profile platform-operator run --rm --no-deps platform-operator runtime-template validate
docker compose --profile platform-operator run --rm --no-deps platform-operator runtime-template publish --actor platform-operator
docker compose --profile platform-operator run --rm --no-deps platform-operator runtime-registry compile --actor platform-operator
docker compose --profile platform-operator run --rm --no-deps platform-operator runtime-registry status --instance-id phase2-spot-paper-probe
```

`freqtrade-cn-operator:local` is only an alias of a verified image ID; it is not
a trusted provenance identity. The service uses `pull_policy: never`, so a
missing alias must fail rather than pull an image.

The image owns the reviewed root commit and CLI entrypoint. Docker administrators
remain platform root: they can replace an image, entrypoint, mount, or environment
and are outside the operator service isolation claim. Operators must use only the
reviewed invocation and typed CLI arguments above.

`platform-ingress` is a non-internal bridge, not a one-way ingress ACL. The
loopback publication restricts host-side inbound access, but the bridge also
gives platform-control a default route, outbound connectivity, and potential
reachability to its bridge gateway or any future peer mistakenly attached to
that network. PostgreSQL and all other project services must not join it. Phase
2A accepts this tradeoff because Docker 28 and 29 do not realize a host-published
port for a container attached only to an internal network. If a deployment must
also prohibit platform-control egress, its launcher must add a dedicated
publisher/proxy or infrastructure network policy; the `platform-ingress` name
alone does not enforce that property.

Root Safety is the sole Phase 2A start acceptance. It builds the reviewed
integrated image, starts an isolated PostgreSQL 17.10 instance on loopback,
upgrades the schema, reconciles database authority, runs PostgreSQL tests, and
starts the application in a hardened CI-only container. Cleanup runs even after
failure and proves that the acceptance created no Docker volume.

## Bootstrap and exact secret inventory

Run the reviewed host bootstrap before configuration validation. It owns exact
file creation, permissions, single-line and NUL checks, minimum lengths, and
global uniqueness. The platform inventory is exactly:

- `ft_userdata/secrets/platform/postgres_admin_password`
- `ft_userdata/secrets/platform/platform_control_db_password`
- `ft_userdata/secrets/platform/platform_supervisor_db_password`
- `ft_userdata/secrets/platform/platform_operator_db_password`
- `ft_userdata/secrets/platform/api_password`
- `ft_userdata/secrets/platform/jwt_secret_key`

Secret values are consumed through files. They must not be copied into ordinary
environment variables, DSNs, command arguments, logs, or artifacts. The admin
password is reserved for database administration and migration. The control and
supervisor database passwords belong only to their fixed roles. The operator
database password belongs only to `platform_operator`. It is mounted read-only
into `platform-postgres` for role reconciliation and into the one-shot
`platform-operator` carrier as `database_password`; no long-running service
receives it. The API password and JWT key belong only to
platform-control authentication.

Database-role password rotation is deliberately deferred in Phase 2A because it
requires a coordinated database transaction and service handoff. Do not add the
platform inventory to the legacy `rotate-secrets` route. The one narrow staging
exception is fixed: `rotate-secrets --service platform-operator` rotates only
`platform_operator_db_password`. This selector names one credential group; it
does not grant Docker or database authority. A reviewed Supervisor or
infrastructure launcher must define rotation, restart,
verification, and rollback as one operation before production use.

## Migration and reconciliation contract

The production-shaped database is `platform`. Upgrade it with the backend's
`alembic-platform.ini` only through reviewed automation that constructs the
admin SQLAlchemy URL in process memory from the exact admin password file.
Credentials must never be rendered in output. After the upgrade:

1. Verify the database revision equals the unique Alembic head.
2. Rerun `docker/postgres/init-platform-roles.sh` as the bootstrap superuser so
   grants are applied after all migrated tables exist.
3. Verify all three fixed roles have the exact negative role attributes, no inbound
   or outbound memberships, and no residual delegated column ACLs.
4. Verify effective privileges and actual allowed and denied SQL operations.

The initializer is idempotent. It removes at most one terminal LF or CRLF from
password files, preserves all other characters, resets dangerous role
attributes and memberships, fails closed if a fixed role owns an object or the
operator owns/receives default authority, removes database/schema/table/sequence/
column authority with downstream cascades, then applies the exact allowlist. Residual
ACL revocation executes as each ACL's recorded original grantor, including grants to
PostgreSQL's `PUBLIC` pseudo-role whose catalog grantee is OID 0. Null ACLs are
expanded with PostgreSQL 17's hard-wired defaults before reconciliation.

This dedicated cluster revokes `PUBLIC` CONNECT, CREATE, and TEMPORARY authority on
every database. In `platform`, it also removes `PUBLIC` authority from every
non-system schema and its relations, sequences, columns, functions, and procedures;
`pg_*` schemas and `information_schema` are not altered. PostgreSQL defaults for
future objects created by `postgres` are hardened globally for routines and within
`public` for tables, sequences, and routines. Remaining `PUBLIC` or operator default
ACLs fail closed. The initializer then grants only the reviewed `platform`/`public`
and table allowlists, so none of the fixed roles inherits database DDL or
temporary-table authority through `PUBLIC`.

## Least privilege

`platform_control` receives only CONNECT on `platform`, USAGE on `public`,
SELECT on the seven Catalog/Registry tables, INSERT on
`runtime_access_requests` and `runtime_audit_events`, and UPDATE of only
`status`, `result_code`, and `completed_at` on `runtime_access_requests`.
It cannot update lifecycle state such as `runtime_instances.desired_state`.

`platform_supervisor` receives CONNECT/USAGE, SELECT on the seven tables, and
INSERT/UPDATE on the six Registry tables. Neither role receives DELETE,
TRUNCATE, MAINTAIN, DDL, role-management, database-owner, broad default-table, or
platform-control lifecycle authority. Root Safety checks the effective database
matrix for both roles as `CONNECT=true`, `CREATE=false`, `TEMP=false`, then
checks exact schema, table, column, sequence, ownership, membership, grantable,
and residual-ACL inventories. Positive and negative SQL probes connect as each
fixed identity; administrator `SET ROLE` is not acceptance evidence.

`platform_operator` receives only CONNECT on `platform`, USAGE on `public`, and
SELECT plus INSERT on the seven fixed registration tables:
`platform_catalog_revisions`, `adapter_template_revisions`, `state_allocations`,
`secret_references`, `runtime_spec_revisions`, `runtime_instances`, and
`runtime_audit_events`. It receives no sequence privilege, UPDATE, DELETE,
TRUNCATE, REFERENCES, TRIGGER, MAINTAIN, secret-version authority, or lifecycle/Runtime
Access table authority. The initializer skips absent allowlisted tables and is
rerunnable after Alembic creates them.

Root Safety probes PostgreSQL 17 effective privileges, including authority
inherited through `PUBLIC`, using each fixed login identity rather than relying on
named-role ACL rows or administrator `SET ROLE` alone. Its database, schema, table,
column, sequence, routine, and default-ACL checks must cover both explicit ACLs and
hard-wired defaults represented by null catalog ACLs.
Root Safety must contaminate fixed roles with routine ownership, direct routine
`EXECUTE`, and table `MAINTAIN` authority. It must prove that a rerun fails closed
while a fixed role owns the routine; after an administrator restores ownership, a
rerun must remove the direct `EXECUTE` and `MAINTAIN` grants and each affected fixed
login must be denied those operations.

## Runtime identity-label migration

Before enabling dynamic Runtime access networks, recreate the fixed
`platform-control` container from the reviewed Compose contract. An existing
container does not acquire the identity labels merely because
`docker-compose.yml` changed. The replacement must retain the fixed name
`freqtrade-cn-platform-control` and must expose the exact Compose project,
service, role, identity-revision, full container ID, and reviewed image ID that
the Supervisor identity provider verifies. Stop if any value differs; do not
adopt, relabel, rename, or reconnect the old object in place. This migration is
an infrastructure deployment action and is not an automatic Supervisor
recovery operation.

## CI-only acceptance evidence

The `Root Safety` workflow is executable evidence for the migration and runtime
contract. Its fixed acceptance resources are the internal database network
`freqtrade-platform-ci`, ingress network `freqtrade-platform-ingress-ci`,
PostgreSQL container `platform-postgres-ci`, application container
`platform-control-ci`, production-shaped database `platform`, isolated test
database `platform_test_ci`, database endpoint `127.0.0.1:55432`, and control
endpoint `127.0.0.1:8090`.

Acceptance must show:

- PostgreSQL reaches bounded readiness and the isolated test database has zero
  PostgreSQL skips in migration and repository selectors.
- Alembic reaches current head and role reconciliation succeeds after migration.
- Injected dangerous attributes, bidirectional memberships, delegated column
  authority, and downstream authority are removed.
- Exact control-role SELECT, request/audit INSERT, and terminal request UPDATE
  operations succeed, while both fixed roles are denied temporary and persistent
  CREATE, ALTER, DROP, DELETE, TRUNCATE, and out-of-allowlist UPDATE operations.
- The application container is created directly on
  `freqtrade-platform-ingress-ci`, connected to the internal
  `freqtrade-platform-ci` database network, and inspected for exactly those two
  networks. The requested loopback mapping is checked before start and the
  realized runtime mapping is checked after start, before HTTP readiness.
- Platform-control reaches bounded `/api/v2/ping` readiness; authentication is
  obtained from a private file; Catalog and Registry reads succeed; `/docs`,
  `/redoc`, and `/openapi.json` return 404; lifecycle and Runtime Access routes
  are absent.
- Both containers, both exact networks, passfile, secret copies, token/probe
  artifacts, and all other transient files are removed. Cleanup computes the
  exact before/after volume set difference, deletes only volumes created by the
  acceptance, rechecks equality with the baseline, and preserves a non-zero
  cleanup result for any forbidden drift.

## Health, logs, and backup prerequisite

Health evidence is the bounded PostgreSQL `pg_isready` loop followed by the
bounded public `/api/v2/ping` probe. Operators must treat timeout, migration
revision mismatch, role reconciliation failure, permission-probe mismatch,
unexpected HTTP route, or cleanup drift as a failed acceptance. Logs may contain
stable status and permission-denial text, but never credentials, password-bearing
URLs, JWTs, passfile content, or secret-file content.

Before any future production migration, take and verify a restorable PostgreSQL
backup using the infrastructure owner's approved encrypted backup mechanism.
Record the database identity, current Alembic revision, application image ID,
root/backend commits, backup identifier, and restore verification. Phase 2A CI
uses tmpfs and intentionally produces no persistent backup artifact.

## Rollback order

If a future reviewed production deployment fails, preserve evidence and roll
back in this order:

1. Stop accepting control-plane traffic through the infrastructure-owned entry
   point; do not introduce an ad-hoc Compose start/stop path.
2. Stop the application container while leaving PostgreSQL available for
   diagnosis and backup.
3. Restore the previously reviewed application image and compatible root/backend
   commits if the schema remains forward-compatible.
4. If schema rollback is required, restore the verified pre-migration backup;
   do not improvise an Alembic downgrade against production data.
5. Rerun the reviewed role initializer, verify exact effective privileges, then
   repeat health/auth/read-only-route acceptance before reopening traffic.

Production recovery, start/stop, backup, and secret rotation remain blocked
until a reviewed Supervisor or dedicated infrastructure launcher owns these
steps end to end.
