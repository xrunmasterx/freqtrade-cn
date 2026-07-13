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

The control plane has two fixed services. `platform-postgres` is reachable only
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
- `ft_userdata/secrets/platform/api_password`
- `ft_userdata/secrets/platform/jwt_secret_key`

Secret values are consumed through files. They must not be copied into ordinary
environment variables, DSNs, command arguments, logs, or artifacts. The admin
password is reserved for database administration and migration. The control and
supervisor database passwords belong only to their fixed roles. The API password
and JWT key belong only to platform-control authentication.

Database-role password rotation is deliberately deferred in Phase 2A because it
requires a coordinated database transaction and service handoff. Do not add the
platform inventory to the legacy `rotate-secrets` route. A reviewed Supervisor
or infrastructure launcher must define rotation, restart, verification, and
rollback as one operation before production use.

## Migration and reconciliation contract

The production-shaped database is `platform`. Upgrade it with the backend's
`alembic-platform.ini` only through reviewed automation that constructs the
admin SQLAlchemy URL in process memory from the exact admin password file.
Credentials must never be rendered in output. After the upgrade:

1. Verify the database revision equals the unique Alembic head.
2. Rerun `docker/postgres/init-platform-roles.sh` as the bootstrap superuser so
   grants are applied after all migrated tables exist.
3. Verify both fixed roles have the exact negative role attributes, no inbound
   or outbound memberships, and no residual delegated column ACLs.
4. Verify effective privileges and actual allowed and denied SQL operations.

The initializer is idempotent. It removes at most one terminal LF or CRLF from
password files, preserves all other characters, resets dangerous role
attributes and memberships, removes database/schema/table/sequence/column
authority with downstream cascades, then applies the exact allowlist. Residual
column revocation executes as each ACL's recorded original grantor. It also
revokes `TEMPORARY` and `CREATE` on `platform` from `PUBLIC`, so neither fixed
role inherits database DDL or temporary-table authority through PostgreSQL's
default grants.

## Least privilege

`platform_control` receives only CONNECT on `platform`, USAGE on `public`,
SELECT on the seven Catalog/Registry tables, INSERT on
`runtime_access_requests` and `runtime_audit_events`, and UPDATE of only
`status`, `result_code`, and `completed_at` on `runtime_access_requests`.
It cannot update lifecycle state such as `runtime_instances.desired_state`.

`platform_supervisor` receives CONNECT/USAGE, SELECT on the seven tables, and
INSERT/UPDATE on the six Registry tables. Neither role receives DELETE,
TRUNCATE, DDL, role-management, database-owner, broad default-table, or
platform-control lifecycle authority. Root Safety checks the effective database
matrix for both roles as `CONNECT=true`, `CREATE=false`, `TEMP=false`, then
checks exact schema, table, column, sequence, ownership, membership, grantable,
and residual-ACL inventories. Positive and negative SQL probes connect as each
fixed identity; administrator `SET ROLE` is not acceptance evidence.

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
