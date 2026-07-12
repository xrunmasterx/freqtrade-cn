
# Phase 2A Registry and Platform Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the PostgreSQL/Alembic control plane, immutable Runtime Registry state, job/audit persistence, trusted local application service, and authenticated `platform-control:8090` query surface without Docker mutation.

**Architecture:** Move `PlatformBase` into a shared platform database module, replace production `create_all()` with Alembic, and keep repositories behind protocols. `platform-control` is a separate FastAPI process with a least-privilege database role: Registry/Catalog SELECT plus gateway-request/audit ownership only; lifecycle writes remain local CLI application-service calls.

**Tech Stack:** Python 3.11-3.14, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, psycopg 3, pytest, Ruff, Docker Compose v2, standard-library unittest.

## Global Constraints

- Follow every constraint in `docs/superpowers/plans/2026-07-12-runtime-registry-v2-master.md`.
- This phase performs no Docker lifecycle mutation and enables no Runtime Access forwarding.
- Production schema startup never calls `PlatformBase.metadata.create_all()`.
- SQLite is allowed only for dialect-neutral repository unit tests; PostgreSQL is mandatory for migration, JSON, uniqueness, row-lock, lease, and transaction tests.
- API v2 exposes GET/HEAD only for lifecycle/control-plane resources.
- Unknown owner kinds, states, actions, and management modes fail before persistence.

---

## File Structure

### Backend submodule `freqtrade/`

- Create `freqtrade/platform/database.py`: shared `PlatformBase`, engine/session factories, role-neutral database settings.
- Modify `freqtrade/platform/catalog_repository.py`: import shared base and remove production schema initialization.
- Create `freqtrade/platform/runtime_domain.py`: immutable enums and Pydantic contracts.
- Create `freqtrade/platform/runtime_models.py`: SQLAlchemy Registry, attempt, job, endpoint, access-request, and audit records.
- Create `freqtrade/platform/runtime_repository.py`: repository protocol and SQL implementation.
- Create `freqtrade/platform/runtime_service.py`: lifecycle command validation and transactional job creation.
- Create `freqtrade/platform_control/settings.py`: secret-file and loopback-only service settings.
- Create `freqtrade/platform_control/auth.py`: platform-owned Basic/JWT authentication.
- Create `freqtrade/platform_control/app.py`: FastAPI factory and query-only routers.
- Create `freqtrade/platform_control/__main__.py`: Uvicorn entry point.
- Create `platform_migrations/env.py`, `platform_migrations/script.py.mako`, `platform_migrations/versions/20260712_0001_registry.py`, and `alembic-platform.ini`.
- Modify `pyproject.toml` and `requirements.txt`: add Alembic and psycopg runtime dependencies.
- Create tests under `tests/platform/` and `tests/platform_control/`.

### Root repository

- Create `docker/postgres/init-platform-roles.sh`: least-privilege fixed roles.
- Modify `docker-compose.yml`: internal PostgreSQL and loopback platform-control services.
- Modify `tools/bootstrap_runtime.py`: provision only the exact new platform secret files.
- Modify `tools/runtime_contract.py`: validate fixed control-plane services without adding them to the old exact-three migration manifest.
- Modify `.github/workflows/root-safety.yml` and `tests/test_root_safety_workflow.py`: migration/PostgreSQL/platform-control gates.

---

### Task 1: Shared platform database boundary and dependencies

**Files:**
- Create: `freqtrade/freqtrade/platform/database.py`
- Modify: `freqtrade/freqtrade/platform/catalog_repository.py`
- Modify: `freqtrade/freqtrade/platform/__init__.py`
- Modify: `freqtrade/pyproject.toml`
- Modify: `freqtrade/requirements.txt`
- Test: `freqtrade/tests/platform/test_database.py`
- Test: `freqtrade/tests/platform/test_catalog_repository.py`

**Interfaces:**
- Produces: `PlatformBase`, `PlatformDatabaseSettings`, `create_platform_engine(settings)`, and `platform_session(engine)`.
- Removes: `SqlCatalogRepository.initialize_schema()` from production API.
- Preserves: `SqlCatalogRepository.publish()` and `current()` behavior after migrated schema exists.

- [ ] **Step 1: Write failing database-boundary tests**

Create `freqtrade/tests/platform/test_database.py`:

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from freqtrade.platform.database import PlatformDatabaseSettings


def test_database_settings_build_url_from_exact_secret_file(tmp_path: Path) -> None:
    secret = tmp_path / "password"
    secret.write_text("correct-horse-battery-staple\n", encoding="utf-8")

    settings = PlatformDatabaseSettings(
        host="platform-postgres",
        port=5432,
        database="platform",
        username="platform_control",
        password_file=secret,
    )

    assert settings.sqlalchemy_url().render_as_string(hide_password=True) == (
        "postgresql+psycopg://platform_control:***@platform-postgres:5432/platform"
    )


def test_database_settings_reject_non_postgres_production_settings(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="PostgreSQL is required"):
        PlatformDatabaseSettings(
            host="sqlite",
            port=1,
            database="test",
            username="test",
            password_file=tmp_path / "password",
        )
```

Modify `test_catalog_repository.py` so tests create the catalog table explicitly with test-only metadata and assert `SqlCatalogRepository` has no `initialize_schema` attribute.

- [ ] **Step 2: Run RED**

```powershell
cd freqtrade
python -m pytest tests/platform/test_database.py tests/platform/test_catalog_repository.py -q -p no:cacheprovider
```

Expected: import failure for `freqtrade.platform.database` and failure because `initialize_schema` still exists.

- [ ] **Step 3: Implement the shared database module**

Create `freqtrade/freqtrade/platform/database.py` with this public shape:

```python
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine, URL, create_engine
from sqlalchemy.orm import DeclarativeBase, Session


class PlatformBase(DeclarativeBase):
    pass


class PlatformDatabaseSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    database: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    username: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    password_file: Path

    @model_validator(mode="after")
    def require_postgres_host(self) -> "PlatformDatabaseSettings":
        if self.host == "sqlite":
            raise ValueError("PostgreSQL is required for production platform settings")
        return self

    def read_password(self) -> str:
        value = self.password_file.read_text(encoding="utf-8").rstrip("\r\n")
        if not value or "\n" in value or "\r" in value or "\x00" in value:
            raise ValueError("platform database password file is invalid")
        return value

    def sqlalchemy_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.username,
            password=self.read_password(),
            host=self.host,
            port=self.port,
            database=self.database,
        )


def create_platform_engine(settings: PlatformDatabaseSettings) -> Engine:
    return create_engine(settings.sqlalchemy_url(), pool_pre_ping=True, future=True)


@contextmanager
def platform_session(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        yield session
```

Move `PlatformBase` imports to this module and delete `initialize_schema()` from `SqlCatalogRepository`.

Add project dependencies:

```toml
  "alembic>=1.16,<2",
  "psycopg[binary]>=3.2,<4",
```

Add these exact constrained entries to `requirements.txt` in the same dependency update commit:

```text
alembic>=1.16,<2
psycopg[binary]>=3.2,<4
```

Verify installation on Python 3.11 and the repository's Python 3.14 image before accepting the dependency commit.

- [ ] **Step 4: Run GREEN and lint**

```powershell
python -m pytest tests/platform/test_database.py tests/platform/test_catalog_repository.py -q -p no:cacheprovider
ruff check freqtrade/platform/database.py freqtrade/platform/catalog_repository.py tests/platform/test_database.py tests/platform/test_catalog_repository.py
```

Expected: all tests pass and Ruff exits 0.

- [ ] **Step 5: Commit backend task**

```powershell
git add pyproject.toml requirements.txt freqtrade/platform/database.py freqtrade/platform/catalog_repository.py freqtrade/platform/__init__.py tests/platform/test_database.py tests/platform/test_catalog_repository.py
git commit -m "feat(platform): establish production database boundary"
```

---

### Task 2: Runtime domain contracts and state machine

**Files:**
- Create: `freqtrade/freqtrade/platform/runtime_domain.py`
- Modify: `freqtrade/freqtrade/platform/__init__.py`
- Test: `freqtrade/tests/platform/test_runtime_domain.py`

**Interfaces:**
- Produces closed enums: `RuntimeOwnerKind`, `RuntimeManagementMode`, `RuntimeDesiredState`, `RuntimeLifecycleStatus`, `RuntimeAttemptStatus`, `RuntimeAction`, `RuntimeJobStatus`.
- Produces frozen models: `RuntimeOwnerRef`, `RuntimeInstanceView`, `RuntimeAttemptView`, `RuntimeJobView`, `RuntimeLifecycleCommand`.

- [ ] **Step 1: Write failing state-machine tests**

```python
import pytest
from pydantic import ValidationError

from freqtrade.platform.runtime_domain import (
    RuntimeAction,
    RuntimeLifecycleCommand,
    RuntimeOwnerKind,
    RuntimeOwnerRef,
)


def test_owner_ref_is_closed_and_immutable() -> None:
    owner = RuntimeOwnerRef(
        owner_kind=RuntimeOwnerKind.MIGRATION_BOT,
        owner_id="spot-migration",
        owner_revision="spot-migration-v1",
    )
    with pytest.raises(ValidationError):
        owner.owner_id = "other"
    with pytest.raises(ValidationError):
        RuntimeOwnerRef(owner_kind="unknown", owner_id="x", owner_revision="v1")


def test_lifecycle_command_requires_idempotency_and_expected_version() -> None:
    command = RuntimeLifecycleCommand(
        instance_id="runtime-1",
        action=RuntimeAction.START,
        idempotency_key="operator-20260712-start-1",
        expected_instance_version=3,
    )
    assert command.expected_instance_version == 3
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/platform/test_runtime_domain.py -q -p no:cacheprovider
```

Expected: import failure for `runtime_domain`.

- [ ] **Step 3: Implement exact closed contracts**

Create enums with these exact values:

```python
class RuntimeOwnerKind(StrEnum):
    MIGRATION_BOT = "migration_bot"
    PAPER_PROBE = "paper_probe"
    WORKSPACE_WORKER = "workspace_worker"


class RuntimeManagementMode(StrEnum):
    SUPERVISOR = "supervisor"


class RuntimeDesiredState(StrEnum):
    STOPPED = "stopped"
    RUNNING = "running"
    RETIRED = "retired"


class RuntimeLifecycleStatus(StrEnum):
    REGISTERED = "registered"
    PROVISIONING = "provisioning"
    STOPPED = "stopped"
    STARTING = "starting"
    HEALTHY = "healthy"
    STOPPING = "stopping"
    FAILED = "failed"
    RETIRED = "retired"


class RuntimeAttemptStatus(StrEnum):
    PENDING = "pending"
    VALIDATING = "validating"
    LAUNCHING = "launching"
    HEALTHY = "healthy"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class RuntimeAction(StrEnum):
    START = "start"
    STOP = "stop"
    RETRY = "retry"
    RETIRE = "retire"


class RuntimeJobStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_RECONCILIATION = "needs_reconciliation"
```

Use one frozen Pydantic base model with identifier pattern `^[a-z0-9][a-z0-9_-]{0,127}$`. `RuntimeLifecycleCommand` contains only `instance_id`, `action`, `idempotency_key`, and non-negative `expected_instance_version`; it has no raw arguments field.

Use `AwareDatetime` for every timestamp and `Literal["paper", "live"]` for
the closed environment field. The query contracts are exact summaries:

```text
RuntimeInstanceView
- instance_id: Identifier
- instance_kind: Identifier
- owner_ref: RuntimeOwnerRef
- management_mode: RuntimeManagementMode
- runtime_spec_revision_id: Identifier
- environment: Literal["paper", "live"]
- state_allocation_id: Identifier
- desired_state: RuntimeDesiredState
- lifecycle_status: RuntimeLifecycleStatus
- failure_latched: bool
- optimistic_version: int >= 0
- created_at: AwareDatetime
- retired_at: AwareDatetime | None

RuntimeAttemptView
- attempt_id: Identifier
- instance_id: Identifier
- attempt_number: int >= 1
- runtime_spec_revision_id: Identifier
- adapter_template_revision_id: Identifier
- status: RuntimeAttemptStatus
- health_result: Identifier | None
- started_at: AwareDatetime | None
- stopped_at: AwareDatetime | None
- exit_code: int | None
- failure_code: Identifier | None

RuntimeJobView
- job_id: Identifier
- instance_id: Identifier
- requested_action: RuntimeAction
- idempotency_key: Identifier
- expected_instance_version: int >= 0
- status: RuntimeJobStatus
- lease_owner: Identifier | None
- lease_expires_at: AwareDatetime | None
- requested_at: AwareDatetime
- started_at: AwareDatetime | None
- completed_at: AwareDatetime | None
- failure_code: Identifier | None
```

These views do not include arbitrary payloads, secret identities/versions,
secret or host paths, Docker project internals, or request/response bodies.
The complete immutable attempt provenance remains a persistence concern for
Task 3 and later purpose-specific read contracts. Repository/application rules
in Task 4 must treat `needs_reconciliation` as blocking a new lifecycle command
until explicit reconciliation has established external state.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest tests/platform/test_runtime_domain.py -q -p no:cacheprovider
ruff check freqtrade/platform/runtime_domain.py tests/platform/test_runtime_domain.py
git add freqtrade/platform/runtime_domain.py freqtrade/platform/__init__.py tests/platform/test_runtime_domain.py
git commit -m "feat(platform): define runtime lifecycle contracts"
```

Expected: tests and Ruff pass; commit succeeds.

---

### Task 3: Registry ORM models and Alembic migration

**Files:**
- Create: `freqtrade/freqtrade/platform/runtime_models.py`
- Create: `freqtrade/alembic-platform.ini`
- Create: `freqtrade/platform_migrations/env.py`
- Create: `freqtrade/platform_migrations/script.py.mako`
- Create: `freqtrade/platform_migrations/versions/20260712_0001_registry.py`
- Test: `freqtrade/tests/platform/test_platform_migrations.py`

**Interfaces:**
- Creates tables: `platform_catalog_revisions`, `runtime_instances`, `runtime_attempts`, `runtime_lifecycle_jobs`, `runtime_endpoints`, `runtime_access_requests`, `runtime_audit_events`.
- Enforces one active attempt and one active job per instance with PostgreSQL partial unique indexes.
- Enforces unique `(instance_id, attempt_number)` and `(instance_id, idempotency_key)`.

- [ ] **Step 1: Write failing migration tests**

```python
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


EXPECTED_TABLES = {
    "platform_catalog_revisions",
    "runtime_instances",
    "runtime_attempts",
    "runtime_lifecycle_jobs",
    "runtime_endpoints",
    "runtime_access_requests",
    "runtime_audit_events",
}


def test_empty_postgres_upgrades_to_registry_head(postgres_url: str) -> None:
    config = Config(str(Path(__file__).parents[2] / "alembic-platform.ini"))
    config.set_main_option("sqlalchemy.url", postgres_url)
    command.upgrade(config, "head")

    assert EXPECTED_TABLES <= set(inspect(create_engine(postgres_url)).get_table_names())
```

Add tests for downgrade/upgrade, non-empty catalog fixture preservation, active-attempt/job partial uniqueness, and startup source paths containing no `metadata.create_all()` call.

Define the `postgres_url` fixture in this test module. It reads only
`PLATFORM_TEST_POSTGRES_URL`, requires the database name to match
`^platform_test[a-z0-9_]*$`, and resets only that database's `public` schema
before and after each test. If the variable is absent, the PostgreSQL tests
skip with one stable reason; Task 3 acceptance itself must set the variable and
run with zero skips against an isolated PostgreSQL instance. Never reset a URL
that fails the test-database name guard. The fixture and test logs must not print
the URL or password.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/platform/test_platform_migrations.py -q -p no:cacheprovider
```

Expected: missing Alembic configuration/migration.

- [ ] **Step 3: Implement ORM records**

Define records using `PlatformBase` and typed SQLAlchemy mappings. Identity columns are `String(128)`, timestamps are timezone-aware, payload/provenance fields use `JSON`, and optimistic version is a non-negative integer. Use nullable terminal timestamps/codes only where the state machine allows them.

Use these exact record fields and nullability:

```text
RuntimeInstanceRecord
- instance_id PK String(128)
- instance_kind String(128)
- owner_kind String(128)
- owner_id String(128)
- owner_revision String(128)
- management_mode String(128)
- runtime_spec_revision_id String(128)
- environment String(16)
- state_allocation_id String(128)
- desired_state String(32)
- lifecycle_status String(32)
- failure_latched Boolean
- optimistic_version Integer >= 0
- created_at DateTime(timezone=True)
- retired_at nullable DateTime(timezone=True)

RuntimeAttemptRecord
- attempt_id PK String(128)
- instance_id restrictive FK
- attempt_number Integer >= 1
- runtime_spec_revision_id String(128)
- adapter_template_revision_id String(128)
- resolved_secret_versions non-null JSON
- image_id String(256)
- root_commit/backend_commit/frontend_commit/strategies_commit String(64)
- project_identity/container_identity String(128)
- status String(32)
- health_result nullable JSON
- started_at nullable DateTime(timezone=True)
- stopped_at nullable DateTime(timezone=True)
- exit_code nullable Integer
- failure_code nullable String(128)

RuntimeLifecycleJobRecord
- job_id PK String(128)
- instance_id restrictive FK
- requested_action String(32)
- idempotency_key String(128)
- expected_instance_version Integer >= 0
- status String(32)
- lease_owner nullable String(128)
- lease_expires_at nullable DateTime(timezone=True)
- requested_at DateTime(timezone=True)
- started_at/completed_at nullable DateTime(timezone=True)
- failure_code nullable String(128)

RuntimeEndpointRecord
- endpoint_id PK String(128)
- instance_id restrictive FK
- attempt_id restrictive FK
- endpoint_kind String(128)
- internal_port Integer in 1..65535
- protocol String(16)
- exposure_policy String(32)
- created_at DateTime(timezone=True)

RuntimeAccessRequestRecord
- request_id PK String(128)
- instance_id restrictive FK
- attempt_id restrictive FK
- route_policy_revision String(128)
- method String(16)
- idempotency_key nullable String(128)
- status String(32)
- result_code nullable String(128)
- requested_at DateTime(timezone=True)
- completed_at nullable DateTime(timezone=True)

RuntimeAuditEventRecord
- audit_event_id PK String(128)
- actor_type String(128)
- request_id String(128)
- idempotency_key nullable String(128)
- owner_kind/owner_id/owner_revision nullable String(128)
- instance_id nullable restrictive FK
- runtime_spec_revision_id/adapter_template_revision_id nullable String(128)
- action String(128)
- previous_state/next_state nullable JSON
- result_code String(128)
- occurred_at DateTime(timezone=True)
- provenance non-null JSON
```

All unspecified fields above are non-null. Add named check constraints for the
closed Phase 2 owner kinds, management mode, environment, desired/lifecycle/
attempt/job states, lifecycle actions, non-negative versions, positive attempt
numbers, endpoint ports, endpoint protocols (`http`, `https`), and exposure
policies (`internal_only`, `none`). Add unique `(attempt_id, endpoint_kind)`.
The JSON columns store identities/evidence only and reject secret values at the
application boundary; no request/response body or Authorization/Cookie header
column exists.

Define PostgreSQL partial indexes:

```python
Index(
    "uq_runtime_attempt_active",
    RuntimeAttemptRecord.instance_id,
    unique=True,
    postgresql_where=RuntimeAttemptRecord.status.in_(
        ("pending", "validating", "launching", "healthy", "stopping")
    ),
)
Index(
    "uq_runtime_job_active",
    RuntimeLifecycleJobRecord.instance_id,
    unique=True,
    postgresql_where=RuntimeLifecycleJobRecord.status.in_(
        ("pending", "claimed", "running")
    ),
)
```

`RuntimeAccessRequestRecord` stores no request/response body or Authorization/Cookie headers. Include `request_id`, `instance_id`, `attempt_id`, `route_policy_revision`, `method`, `idempotency_key`, `status`, `result_code`, `requested_at`, and `completed_at`.

- [ ] **Step 4: Implement explicit Alembic migration**

The migration `upgrade()` calls `op.create_table()` and `op.create_index()` for every expected table/index. `downgrade()` drops indexes and tables in reverse dependency order. It never calls `PlatformBase.metadata.create_all()`.

Use `platform_migrations/env.py` with:

```python
from freqtrade.platform.database import PlatformBase
from freqtrade.platform import catalog_repository, runtime_models

target_metadata = PlatformBase.metadata
```

`alembic-platform.ini` contains no DSN or credential. `env.py` accepts a URL
already set programmatically on the Alembic `Config`. For test-only CLI drift
checking, it may fall back to `PLATFORM_TEST_POSTGRES_URL`; if neither is
present it fails closed. Production migration invocation later constructs the
URL from `PlatformDatabaseSettings` and never copies a password into an
ordinary environment variable.

- [ ] **Step 5: Run PostgreSQL GREEN**

```powershell
python -m pytest tests/platform/test_platform_migrations.py -q -p no:cacheprovider
$env:PLATFORM_TEST_POSTGRES_URL = "<isolated platform_test database URL>"
alembic -c alembic-platform.ini upgrade head
alembic -c alembic-platform.ini check
ruff check freqtrade/platform/runtime_models.py platform_migrations tests/platform/test_platform_migrations.py
```

Expected: empty upgrade, downgrade/upgrade, constraints, and Alembic drift checks pass with zero PostgreSQL skips; command output contains no database URL or password. Remove the test-only environment value after the commands.

- [ ] **Step 6: Commit backend task**

```powershell
git add alembic-platform.ini platform_migrations freqtrade/platform/runtime_models.py tests/platform/test_platform_migrations.py
git commit -m "feat(platform): add registry alembic schema"
```

---

### Task 4: SQL repository, leases, optimistic commands, and audits

**Files:**
- Create: `freqtrade/freqtrade/platform/runtime_repository.py`
- Create: `freqtrade/freqtrade/platform/runtime_service.py`
- Modify: `freqtrade/freqtrade/platform/__init__.py`
- Create: `freqtrade/tests/platform/postgres_test_support.py`
- Create: `freqtrade/tests/platform/conftest.py`
- Modify: `freqtrade/tests/platform/test_platform_migrations.py`
- Test: `freqtrade/tests/platform/test_runtime_repository.py`
- Test: `freqtrade/tests/platform/test_runtime_service.py`

**Interfaces:**
- Produces read-only `RuntimeQueryRepository` protocol with `get_instance()`,
  `list_instances()`, `list_attempts()`, and `list_jobs()`.
- Produces `RuntimeRepository` protocol extending the query contract with
  `create_job()`, `claim_next_job()`, `complete_job()`, and `append_audit()`.
- Produces `SqlRuntimeRepository(engine, clock, id_factory)` as the sole SQL
  implementation. Every public call owns a short SQLAlchemy `Session`
  transaction; no global or long-lived mutable Session is stored.
- Produces stable exceptions `RuntimeNotFound`, `RuntimeConflict`, and
  `RuntimeInvalidTransition`; their messages are stable codes without caller
  payload, database details, or secrets.
- Produces frozen, extra-forbidding `RuntimeInstanceAuditState` and
  `RuntimeAuditEvent` inputs. Audit state contains only desired/lifecycle state,
  failure latch, and optimistic version; provenance is a closed source value,
  not caller-supplied JSON. `append_audit(event)` cannot accept bodies, headers,
  credentials, tokens, paths, DSNs, secret identity/version, or arbitrary
  provenance.
- Produces `RuntimeApplicationService.request(command, actor) -> RuntimeJobView`;
  actor is one identifier-pattern actor type such as `operator_cli` and is
  validated before repository access.
- `claim_next_job()` uses `SELECT ... FOR UPDATE SKIP LOCKED` on PostgreSQL.
- Exact mutating signatures are:

```text
create_job(command: RuntimeLifecycleCommand, actor: Identifier) -> RuntimeJobView
claim_next_job(lease_owner: Identifier, lease_seconds: int[1..3600]) -> RuntimeJobView | None
complete_job(job_id: Identifier, status: succeeded|failed, failure_code: Identifier|None) -> RuntimeJobView
append_audit(event: RuntimeAuditEvent) -> None
```

- [ ] **Step 1: Write RED tests for idempotency, stale versions, and lease claim**

```python
def test_create_job_is_idempotent_for_same_instance_key(repository, stopped_instance) -> None:
    first = repository.create_job(command(stopped_instance, "start", "key-1", version=0), "operator_cli")
    second = repository.create_job(command(stopped_instance, "start", "key-1", version=0), "operator_cli")
    assert second.job_id == first.job_id


def test_stale_expected_version_fails_without_job(repository, stopped_instance) -> None:
    with pytest.raises(RuntimeConflict, match="stale_instance_version"):
        repository.create_job(command(stopped_instance, "start", "key-2", version=9), "operator_cli")
    assert repository.list_jobs(stopped_instance.instance_id) == ()


def test_postgres_claimers_skip_locked_jobs(postgres_repository) -> None:
    first = postgres_repository.claim_next_job("supervisor-a", lease_seconds=30)
    second = postgres_repository.claim_next_job("supervisor-b", lease_seconds=30)
    assert first.job_id != second.job_id
```

Add RED coverage for: conflicting reuse of an idempotency key; exactly one
version increment and audit; rollback of job/instance/audit on injected audit
failure; active-job and `needs_reconciliation` blocking; all start/stop/retry/
retire rules; terminal no-op stop and retire; read-view ordering and unknown
instance behavior; closed actor/audit inputs; lease bounds; stale lease reclaim;
late completion reconciliation; completion failure-code invariants; two real
PostgreSQL claimers skipping locked rows; and zero SQLite claims of PostgreSQL
locking semantics.

Add a read regression for a persisted non-null attempt health evidence object.
`RuntimeAttemptView.health_result` is the validated Identifier stored at
`health_result["result_code"]`, not the JSON object. Missing, non-string, or
invalid result codes raise stable `RuntimeDataError("invalid_health_result")`;
the complete evidence object remains private persistence data.

Move the hardened Task 3 test-PostgreSQL URL validation/reset helpers into
`tests/platform/postgres_test_support.py` and expose the `postgres_url` fixture
from `tests/platform/conftest.py`. Refactor the migration test to import those
helpers. This is a mechanical single-source move: preserve the pre-connect
`dbname`/`database` rejection, `SELECT current_database()` pre-DDL guard,
redacted representation, stable skip reason, `platform_test*` exact match, and
all existing guard regressions. Task 4 and later tests must not copy a second
schema-reset implementation.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/platform/test_runtime_repository.py tests/platform/test_runtime_service.py -q -p no:cacheprovider
```

Expected: missing repository/service imports.

- [ ] **Step 3: Implement transactional repository**

Use a repository-owned `Session` transaction. `create_job()` locks the instance row, checks optimistic version and action/state rules, returns the existing row for an identical idempotency key, rejects a conflicting key payload, increments instance optimistic version once, and inserts job plus append-only audit in one commit.

The idempotency lookup is before the version check so replay of the original
command still returns the original job after the first request incremented the
instance version. Identical means the same instance, action, idempotency key,
and expected version. Replays add no audit. New accepted commands use these
exact rules:

```text
start  : desired=stopped, lifecycle in {registered,stopped}, latch=false,
         no active attempt -> desired=running, pending job
stop   : any non-retired instance -> desired=stopped, pending job;
         if already desired=stopped, lifecycle in {registered,stopped}, and no
         active attempt -> immediately succeeded no-op job
retry  : desired=running, lifecycle=failed, latch=true
         -> latch=false, pending job
retire : desired=stopped, lifecycle in {registered,stopped,failed}, no active
         attempt -> retain allocation, desired/lifecycle=retired,
         retired_at=now, immediately succeeded job
```

Every new accepted command increments optimistic version once, including
terminal no-op stop/retire. Active attempt states are exactly
`pending/validating/launching/healthy/stopping`. Existing active jobs
`pending/claimed/running` reject with `active_job_exists`; an existing
`needs_reconciliation` rejects with `reconciliation_required`. Retired, latch,
retry, start, and retire failures use stable action-specific transition codes.
Rejected commands persist no job, audit, or instance mutation.

`RuntimeAuditEvent` maps only its typed fields into `RuntimeAuditEventRecord`.
Internally generated state JSON has the exact four keys in
`RuntimeInstanceAuditState`; provenance JSON has only the closed `source` key.
Job IDs, audit IDs, and UTC-aware timestamps come from injected factories for
deterministic tests; production defaults use collision-resistant UUID-based
identifiers and UTC time.

`claim_next_job()` uses:

```python
statement = (
    select(RuntimeLifecycleJobRecord)
    .where(RuntimeLifecycleJobRecord.status == "pending")
    .order_by(
        RuntimeLifecycleJobRecord.requested_at,
        RuntimeLifecycleJobRecord.job_id,
    )
    .with_for_update(skip_locked=True)
    .limit(1)
)
```

Lease reclaim returns the stale row as `needs_reconciliation`; it never directly creates another attempt.

Before pending claim, lock the oldest expired `claimed`/`running` row ordered by
lease expiry and job ID. Reclaim sets status `needs_reconciliation`,
`completed_at=now`, and stable `failure_code=stale_lease`, appends an audit, and
returns that row without claiming another. Otherwise claim the oldest pending
row, set status `claimed`, `started_at` once, lease owner/expiry, append an audit,
and commit. `complete_job()` accepts only claimed/running jobs. If its lease is
expired, it records and returns `needs_reconciliation` rather than accepting the
late result. `succeeded` requires no failure code; `failed` requires one. It
sets terminal time, clears lease fields, and appends an audit in the same
transaction. Phase 2C adds attempt/instance observed-state transitions; Task 4
does not guess them.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest tests/platform/test_runtime_repository.py tests/platform/test_runtime_service.py -q -p no:cacheprovider
$env:PLATFORM_TEST_POSTGRES_URL = "<isolated platform_test database URL>"
python -m pytest tests/platform/test_platform_migrations.py tests/platform/test_runtime_repository.py tests/platform/test_runtime_service.py -q -p no:cacheprovider
ruff check freqtrade/platform/runtime_repository.py freqtrade/platform/runtime_service.py tests/platform/postgres_test_support.py tests/platform/conftest.py tests/platform/test_platform_migrations.py tests/platform/test_runtime_repository.py tests/platform/test_runtime_service.py
git add freqtrade/platform/runtime_repository.py freqtrade/platform/runtime_service.py freqtrade/platform/__init__.py tests/platform/postgres_test_support.py tests/platform/conftest.py tests/platform/test_platform_migrations.py tests/platform/test_runtime_repository.py tests/platform/test_runtime_service.py
git commit -m "feat(platform): persist idempotent runtime jobs"
```

Expected: dialect-neutral tests pass on SQLite; locking, claim concurrency,
lease, rollback, and constraint semantics pass on PostgreSQL with zero skips;
the complete platform suite and Task 3 migration safety regressions remain
green. Remove the test-only environment value and all uniquely named temporary
PostgreSQL containers/anonymous volumes after verification.

---

### Task 5: Standalone authenticated platform-control service

**Files:**
- Create: `freqtrade/freqtrade/platform_control/__init__.py`
- Create: `freqtrade/freqtrade/platform_control/settings.py`
- Create: `freqtrade/freqtrade/platform_control/auth.py`
- Create: `freqtrade/freqtrade/platform_control/api_runtime.py`
- Create: `freqtrade/freqtrade/platform_control/app.py`
- Create: `freqtrade/freqtrade/platform_control/__main__.py`
- Test: `freqtrade/tests/platform_control/test_app.py`
- Test: `freqtrade/tests/platform_control/test_auth.py`

**Interfaces:**
- Produces `create_platform_app(settings, repository) -> FastAPI`.
- Native/default execution uses `host_loopback` mode and binds only configured
  loopback; production defaults exactly `127.0.0.1:8090`. The reviewed Compose
  deployment uses explicit `container_loopback_publish` mode with an internal
  `0.0.0.0:8090` bind and exact host publication `127.0.0.1:8090`.
- Exposes `/api/v2/ping`, `/api/v2/catalog`, `/api/v2/runtime-instances`, `/api/v2/runtime-instances/{instance_id}` and GET-only child views.
- Mounts no lifecycle POST/PUT/PATCH/DELETE route and no Runtime Access forwarding in 2A.
- Produces read-only `PlatformControlQueryRepository` with `ready()`,
  `current_catalog()`, and the four `RuntimeQueryRepository` methods. Produces
  `SqlPlatformControlQueryRepository(engine)` by composition; it does not expose
  `create_job`, claim, complete, audit append, Session, Engine, or a lifecycle
  repository property.
- Exact protected response wrappers are `RuntimeInstancesResponse(instances)`,
  `RuntimeAttemptsResponse(instance_id, attempts)`, and
  `RuntimeJobsResponse(instance_id, jobs)`; models are frozen and extra-forbid.

- [ ] **Step 1: Write failing API/auth tests**

```python
def test_registry_requires_auth_and_has_no_lifecycle_methods(client) -> None:
    assert client.get("/api/v2/runtime-instances").status_code == 401
    authenticated = auth_headers(client)
    assert client.get(
        "/api/v2/runtime-instances", headers=authenticated
    ).status_code == 200
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)(
            "/api/v2/runtime-instances", headers=authenticated
        ).status_code == 405


def test_openapi_contains_no_lifecycle_write(client, auth_headers) -> None:
    paths = client.app.openapi()["paths"]
    assert set(paths["/api/v2/runtime-instances"]) == {"get"}
```

Add RED tests for the exact route set and shapes; hidden-schema HEAD support;
public ping readiness and protected Catalog/Registry reads; SQL Catalog rather
than default snapshot behavior; unknown instance, invalid Registry data,
Catalog unavailable, and database unavailable stable errors; absence of any
lifecycle/Runtime Access/raw proxy route; no arbitrary query credential; and a
repository object whose public surface contains no lifecycle method.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/platform_control/test_auth.py tests/platform_control/test_app.py -q -p no:cacheprovider
```

Expected: missing `platform_control` package.

- [ ] **Step 3: Implement settings and auth**

`PlatformControlSettings` contains bind mode, listen host/port, username, API
password file, JWT secret file, and `PlatformDatabaseSettings`. Secret files use
constant-time comparison and the existing HS256 access/refresh token payload
contract so FreqUI can authenticate without Bot credentials.

Use a frozen, extra-forbidding settings model. `bind_mode` is closed to
`host_loopback` and `container_loopback_publish`, defaulting to `host_loopback`.
In `host_loopback` mode, `listen_host` accepts only literal `127.0.0.1` or `::1`,
defaulting to `127.0.0.1`; it rejects names such as `localhost` and every
non-loopback/wildcard address. In `container_loopback_publish` mode,
`listen_host` must be exactly `0.0.0.0`; this mode is reserved for the reviewed
Compose service whose host port is published only at `127.0.0.1:8090`. Port
defaults to 8090 and is bounded to 1..65535. Username follows the platform
Identifier contract. API/JWT secret paths must be absolute and distinct from
one another and the database password path.

`PlatformControlSettings.from_env()` reads only these fixed names:

```text
PLATFORM_CONTROL_BIND_MODE           optional, default host_loopback
PLATFORM_CONTROL_LISTEN_HOST          optional, default 127.0.0.1
PLATFORM_CONTROL_LISTEN_PORT          optional, default 8090
PLATFORM_CONTROL_USERNAME             required
PLATFORM_CONTROL_API_PASSWORD_FILE    required absolute path
PLATFORM_CONTROL_JWT_SECRET_FILE      required absolute path
PLATFORM_DATABASE_HOST                required
PLATFORM_DATABASE_PORT                required
PLATFORM_DATABASE_NAME                required
PLATFORM_DATABASE_USERNAME            required
PLATFORM_DATABASE_PASSWORD_FILE       required absolute path
```

No environment variable contains a secret value or DSN. Missing/invalid values
raise stable errors that do not echo environment values or paths.

The sole exact secret reader removes trailing CR/LF only and rejects empty,
embedded CR/LF, or NUL content. JWT secrets are at least 32 characters. File,
decode, and validation errors contain neither path nor content. App construction
loads the two platform secrets once into a private redacted container; settings
model dump/repr and OpenAPI never contain their values. Reject equal API/JWT
secret values as well as equal paths.

Auth routes are exactly:

```text
POST /api/v2/token/login
POST /api/v2/token/refresh
```

Do not accept credentials in query parameters or log request headers.

Reuse the existing HS256 token functions/payload, not the legacy global
`get_api_config` dependency. Login and direct Basic reads compare both username
and password with `secrets.compare_digest`. Bearer decode permits only HS256,
requires the configured identity, and enforces token type. Access lifetime is
15 minutes; refresh lifetime is 30 days. Login returns the existing
`AccessAndRefreshToken` shape; refresh returns only `AccessToken`. Wrong token
type, identity, algorithm, expiry, signature, Basic value, or query-only
credential returns 401 without reflecting input.

- [ ] **Step 4: Implement app and query routes**

Use dependency injection rather than global Bot state:

```python
def create_platform_app(
    settings: PlatformControlSettings,
    repository: RuntimeQueryRepository,
) -> FastAPI:
    app = FastAPI(title="Platform Control", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.runtime_repository = repository
    app.include_router(auth_router, prefix="/api/v2")
    app.include_router(
        runtime_router,
        prefix="/api/v2",
        dependencies=[Depends(require_platform_user)],
    )
    return app
```

The exact routes and responses are:

```text
GET/HEAD /ping                                      {"status":"pong"}, public;
                                                    503 if repository.ready false/errors
GET/HEAD /catalog                                   existing CatalogResponse, authenticated
GET/HEAD /runtime-instances                         {"instances":[...]}, authenticated
GET/HEAD /runtime-instances/{instance_id}           RuntimeInstanceView, authenticated
GET/HEAD /runtime-instances/{instance_id}/attempts  {"instance_id":...,"attempts":[...]}
GET/HEAD /runtime-instances/{instance_id}/jobs      {"instance_id":...,"jobs":[...]}
```

Register HEAD with `include_in_schema=False`; OpenAPI for each read path contains
only `get`, while token paths contain only `post`. All protected routes use the
same auth dependency. Resolve the instance before child queries. Stable errors:
404 `runtime_instance_not_found`; 500 `invalid_registry_data` for
`RuntimeDataError`; 503 `catalog_unavailable` for an uninitialized Catalog; 503
`control_plane_unavailable` for SQLAlchemy/database readiness failures. Never
return exception text, SQL, evidence, URL, file path, or credentials.

`SqlPlatformControlQueryRepository` composes `SqlRuntimeRepository` and
`SqlCatalogRepository` privately and delegates reads only. `current_catalog()`
therefore reads the latest PostgreSQL revision and preserves the Phase 1 API
shape without importing the legacy Catalog route or Bot API dependency.

`__main__.py` loads settings from fixed environment variable names pointing to exact secret files, builds the engine/repository, and runs Uvicorn. It does not initialize schema.

Importing `freqtrade.platform_control` or `__main__` has no startup side effect.
`main()` creates `PlatformDatabaseSettings` through `from_env()`, creates the
engine and read-only SQL composition, builds the app, and calls Uvicorn with the
validated host/port. It never imports Docker tooling, reads Bot config/state,
calls `create_all()`, runs Alembic, or copies a secret value into an environment
variable.

- [ ] **Step 5: Run GREEN, import audit, and commit**

```powershell
python -m pytest tests/platform_control/test_auth.py tests/platform_control/test_app.py -q -p no:cacheprovider
ruff check freqtrade/platform_control tests/platform_control
python -c "from freqtrade.platform_control.app import create_platform_app; print(create_platform_app.__name__)"
git add freqtrade/platform_control tests/platform_control
git commit -m "feat(platform): add authenticated control service"
```

Expected: tests/Ruff/import pass; token compatibility and secret non-disclosure
pass; every protected route rejects unauthenticated/query-only credentials;
HEAD works but is hidden from schema; API schema contains no lifecycle mutation
or Runtime Access forwarding; imports and app construction perform no schema,
Docker, Bot-state, or service-start side effect.

---

### Task 6: Root PostgreSQL/platform-control runtime and least privilege

**Files:**
- Create: `docker/postgres/init-platform-roles.sh`
- Modify: `docker-compose.yml`
- Modify: `tools/bootstrap_runtime.py`
- Modify: `tools/compose_runtime.py`
- Modify: `tools/runtime_contract.py`
- Test: `tests/test_platform_control_contract.py`
- Test: `tests/test_bootstrap_runtime.py`
- Test: `tests/test_compose_runtime.py`
- Test: `tests/test_runtime_contract.py`

**Interfaces:**
- Fixed services: `platform-postgres` internal only and `platform-control` whose
  container process binds `0.0.0.0:8090` in explicit
  `container_loopback_publish` mode while the host publishes only
  `127.0.0.1:8090`.
- Fixed secret files: PostgreSQL admin password, platform-control DB password,
  platform-supervisor DB password, platform API password, and platform JWT
  secret. Values never appear in ordinary environment variables or DSNs.
- No platform-control Docker socket, repository root, Bot state, trading secret, or general secret-root mount.

- [ ] **Step 1: Write failing root contract tests**

```python
class PlatformControlContractTests(unittest.TestCase):
    def test_platform_control_is_only_fixed_loopback_application_port(self) -> None:
        compose = render_compose(root=REPO_ROOT)
        service = compose["services"]["platform-control"]
        self.assertEqual(
            service["ports"],
            [{
                "target": 8090,
                "published": "8090",
                "host_ip": "127.0.0.1",
                "protocol": "tcp",
            }],
        )

    def test_platform_control_has_no_docker_or_runtime_state_mount(self) -> None:
        service = render_compose(root=REPO_ROOT)["services"]["platform-control"]
        rendered = json.dumps(service, sort_keys=True)
        self.assertNotIn("docker.sock", rendered)
        self.assertNotIn("ft_userdata/runtime", rendered)
```

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_platform_control_contract -v
```

Expected: missing platform services.

- [ ] **Step 3: Add fixed Compose services and entrypoints**

Add `platform-postgres` with `expose: [5432]`, no `ports`, fixed health check, fixed named volume, and secret-file password. Override the image's Bot-specific ENTRYPOINT for `platform-control` with:

```yaml
entrypoint: ["python", "-m", "freqtrade.platform_control"]
environment:
  PLATFORM_CONTROL_BIND_MODE: container_loopback_publish
  PLATFORM_CONTROL_LISTEN_HOST: 0.0.0.0
ports:
  - target: 8090
    published: "8090"
    host_ip: 127.0.0.1
    protocol: tcp
```

The wildcard address is container-internal only; the exact host publication is
the external trust boundary. The service mounts only its exact password/JWT/DB
secret files. Add no Docker socket and no runtime state mount. Secret values are
never copied into ordinary environment variables. Host bootstrap owns exact
inventory, permissions, single-line/NUL/sentinel, and cross-service uniqueness;
`PlatformControlSettings` owns the API/JWT/database file-identity and API/JWT
content checks inside the service.

The exact Compose deployment contract is:

- PostgreSQL image is pinned to `postgres:17.10-alpine`, matching the Phase 2A
  migration acceptance major/minor. It has profile `platform`, joins only the
  internal `platform-db` network, exposes container port 5432 without a host
  publication, and stores data only in named volume `platform-postgres-data` at
  `/var/lib/postgresql/data`.
- PostgreSQL receives exactly the admin, platform-control-role, and
  platform-supervisor-role password files. `POSTGRES_PASSWORD_FILE` is a fixed
  file path; no password or DSN value is present in environment. Its fixed
  health check is `pg_isready` against database `platform` and user `postgres`.
- `platform-control` uses the already reviewed repository runtime image/build,
  profile `platform`, only `platform-db`, and waits for PostgreSQL health. It is
  explicitly non-root (`1000:1000`), `read_only`, `init: true`, drops all
  capabilities, enables `no-new-privileges`, has no `extra_hosts`, and has no
  volumes. It receives exactly API password, JWT secret, and platform-control DB
  password files. A fixed tmpfs is allowed only if a focused runtime test proves
  Python needs it.
- The exact top-level platform inventory is one internal network, one named data
  volume, and five secrets. Platform-control must not receive the admin or
  supervisor password, trading/exchange secrets, Docker socket, root repository,
  runtime state, Bot configuration/state, strategy, research data, or a general
  secret-root mount.

`init-platform-roles.sh` is idempotent and safe to rerun after Alembic creates
tables. It creates fixed LOGIN roles `platform_control` and
`platform_supervisor`, obtains their passwords from the two exact role-password
files,
and uses `pg_read_file` plus `format(..., %L)`/`\gexec` or an equivalently safe
psql-variable mechanism. Passwords must never be shell-interpolated into SQL,
placed on process arguments, printed, or included in ordinary environment.
Secret normalization removes at most one terminal LF or CRLF sequence and
preserves every other character, including leading/trailing spaces and tabs;
generic `trim`/`btrim` is forbidden.

The script revokes PUBLIC database/schema creation privileges and grants only:

- `platform_control`: CONNECT on database `platform`, USAGE on schema `public`,
  SELECT on the seven Phase 2A Catalog/Registry tables, INSERT on
  `runtime_access_requests` and `runtime_audit_events`, and column-limited UPDATE
  of only `status`, `result_code`, and `completed_at` on
  `runtime_access_requests`;
- `platform_supervisor`: CONNECT/USAGE, SELECT on all seven tables, and
  INSERT/UPDATE on the six Registry tables (`runtime_instances`,
  `runtime_attempts`, `runtime_lifecycle_jobs`, `runtime_endpoints`,
  `runtime_access_requests`, and `runtime_audit_events`);
- neither role receives DELETE, TRUNCATE, DDL, role-management, database-owner,
  broad default-table, or platform-control lifecycle authority.

The script conditionally grants table privileges only when migrated tables
exist; Task 7 reruns it after Alembic upgrade and verifies effective privileges.
Before regrant, every rerun resets both fixed roles to `NOSUPERUSER`,
`NOCREATEDB`, `NOCREATEROLE`, `NOREPLICATION`, `NOBYPASSRLS`, and `NOINHERIT`;
removes every inbound/outbound role membership; and revokes table-, sequence-,
schema-, database-, and residual column-level privileges with downstream grant
cleanup before applying the exact allowlist. Membership and residual-column
revocation enumerate and quote each original grantor and use `GRANTED BY ...
CASCADE`, so delegated grants cannot survive a rerun. Do not use broad
`ALTER DEFAULT PRIVILEGES` for future tables.

- [ ] **Step 4: Extend bootstrap and contract validation**

Add the exact five platform secret specifications under
`ft_userdata/secrets/platform/` to `bootstrap_runtime.py` without adding a
directory scan:

```text
postgres_admin_password
platform_control_db_password
platform_supervisor_db_password
api_password
jwt_secret_key
```

`init_runtime()` creates missing files atomically with host permission 0600,
hardens existing regular files without overwriting their values, and keeps all
five values unique from each other and from all legacy service secrets.
`verify_runtime()` validates the exact five paths, regular-file/permission,
single-line/NUL/sentinel/minimum-length, and global uniqueness rules. Platform
secret rotation is intentionally unsupported in Phase 2A because database-role
password rotation requires a coordinated transaction; do not add `platform` to
legacy `rotate-secrets`.

Extend `runtime_contract.py` with `validate_platform_compose()` and a closed
`--platform` CLI selector separate from `validate_compose()` and
`ops/runtime-services.json`; the old validator/manifest remain migration input
for exactly three current processes. The platform validator enforces exact two
services, exact five top-level secrets, exact internal network/named volume,
the container-bind/host-loopback pair, fixed `_FILE` paths, no direct secret or
DSN environment values, exact secret allocation, and every least-privilege
mount/process rule above. Mutation tests must prove it rejects an admin or
supervisor secret on platform-control, a wildcard host publication, a loopback
container bind in container mode, Docker/root/state mounts, direct passwords or
DSNs, extra services/secrets/networks/volumes, and any role-script byte drift.
The reviewed role script is a closed artifact whose SHA-256 is pinned by the
validator. Only LF and CRLF line endings are equivalent: validation converts
CRLF to LF and rejects every remaining CR, NUL, BOM, invalid UTF-8, or other
byte drift. Semantic checks additionally require exact hardening/revocation
clauses. Mutation tests must reject narrow extra column grants, a valid grant
retargeted to `PUBLIC` or another role, changed SELECT/INSERT/UPDATE inventory,
required text moved into comments, duplicate grants, and missing role-attribute,
membership, or residual-column cleanup.
Residual-column mutation tests must also reject missing/incorrect original
grantor joins or `GRANTED BY`, and artifact tests must accept LF/CRLF while
rejecting lone-CR and mixed shell-invalid line endings.

Extend `compose_runtime.py` only enough to permit the exact read-only command
`--profile platform config [--quiet] [--format json]`. It must reject platform
`up`, mixed platform/legacy profiles, arbitrary services/flags, and must not add
platform services to the reviewed legacy launch/emergency path or weaken its
image provenance gates. Add a separate `render_platform_compose()` helper;
preserve legacy `render_compose()` behavior and exact-three validation.

- [ ] **Step 5: Run GREEN and commit root task**

```powershell
python -S -m unittest tests.test_platform_control_contract tests.test_bootstrap_runtime tests.test_compose_runtime tests.test_runtime_contract -v
python tools/compose_runtime.py --profile platform config --format json > $env:TEMP\platform-compose.json
python tools/runtime_contract.py --platform --compose-json $env:TEMP\platform-compose.json
git add docker-compose.yml docker/postgres/init-platform-roles.sh tools/bootstrap_runtime.py tools/compose_runtime.py tools/runtime_contract.py tests/test_platform_control_contract.py tests/test_bootstrap_runtime.py tests/test_compose_runtime.py tests/test_runtime_contract.py
git commit -m "feat(platform): add isolated control-plane services"
```

Expected: root unit/Compose contract tests pass; commit contains root files only.

---

### Task 7: PostgreSQL integration and Root Safety gate

**Files:**
- Modify: `.github/workflows/root-safety.yml`
- Modify: `tests/test_root_safety_workflow.py`
- Create: `docs/operations/platform-control.md`
- Update: root `freqtrade` gitlink after backend reviews pass.

**Interfaces:**
- CI upgrades an empty PostgreSQL database to Alembic head, runs PostgreSQL
  repository tests, starts platform-control in a hardened test-only container
  without Docker/root/state mounts, and asserts the reviewed read-only HTTP
  surface. This is acceptance infrastructure, not a production launch path.
- Phase 2A keeps platform `compose_runtime` config-only. The runbook must not
  instruct operators to bypass it with raw `docker compose up`; production
  start/stop remains fail-closed until the reviewed Supervisor/dedicated
  infrastructure launcher lands.

- [ ] **Step 1: Write failing workflow-structure tests**

Add constants and tests requiring executable steps named exactly:

```text
Start platform PostgreSQL
Upgrade platform schema
Run platform PostgreSQL integration tests
Verify platform-control least privilege
Run Phase 2A backend regressions
```

Also require an `if: always()` cleanup step named `Clean platform control plane`.
Mutation tests prove selectors, secret-file handling, hardening flags, cleanup,
or denial probes in comments/unrelated steps do not satisfy the gate.

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_root_safety_workflow -v
```

Expected: missing named steps/selectors.

- [ ] **Step 3: Add CI and runbook**

After the reviewed integrated image is built, the workflow:

- uses the exact five secrets produced by the existing ephemeral bootstrap;
- creates one fixed CI-only Docker network and starts
  `postgres:17.10-alpine` with loopback-only host port 55432, tmpfs database
  storage, exact three secret-file mounts, and the reviewed role initializer;
- writes a 0600 libpq passfile and exposes only its path plus a password-free
  `platform_test_ci` URL to backend tests;
- upgrades production-shaped database `platform` to Alembic head by constructing
  the admin SQLAlchemy URL in Python memory from the exact password file, creates
  isolated `platform_test_ci`, then reruns the role initializer after migration;
- runs PostgreSQL migration/repository selectors against `platform_test_ci`;
- contaminates fixed roles inside the ephemeral `platform` database with
  dangerous attributes, inbound/outbound memberships, and a delegated
  non-admin-grantor column privilege; reruns reconciliation; and proves through
  catalogs plus actual SQL that only the exact grants remain;
- proves platform-control SELECT, request/audit INSERT and terminal-column UPDATE
  succeed while lifecycle-column UPDATE fails with permission denied;
- starts the reviewed application image as `platform-control` with read-only
  root, UID/GID 1000, dropped capabilities, no-new-privileges, only the CI
  internal network, exact three secret-file mounts, and loopback host 8090;
  then probes public readiness, token authentication, protected Catalog/Registry
  reads, closed schema/docs, and absence of lifecycle/Runtime Access routes;
- always removes both containers, the CI network, passfiles, and transient probe
  files. No named or anonymous Docker volume is created.

The workflow executes:

```powershell
alembic -c alembic-platform.ini upgrade head
python -m pytest tests/platform/test_platform_migrations.py tests/platform/test_runtime_repository.py tests/platform_control -q -p no:cacheprovider
ruff check freqtrade/platform freqtrade/platform_control tests/platform tests/platform_control
```

The least-privilege step must never put a password or password-bearing DSN in
workflow YAML, process arguments, ordinary environment, logs, or artifacts.
Secrets are read only from mounted/bootstrap files; libpq receives a passfile
path. Failure output is checked for stable permission denial without echoing a
secret.

Document bootstrap, migration, CI-only start acceptance, health, logs, backup,
rollback, secret rotation deferral, and the fact that Phase 2A application APIs
perform no Docker lifecycle mutation. Explicitly document that production
platform start/stop is not yet exposed and raw Compose bypass is unsupported.

- [ ] **Step 4: Verify Phase 2A and commit root integration**

```powershell
python -S -m unittest discover -s tests -p "test_*.py" -v
Push-Location freqtrade
python -m pytest tests/markets/test_catalog.py tests/platform tests/platform_control tests/rpc/test_api_catalog.py -q -p no:cacheprovider
ruff check freqtrade/markets freqtrade/platform freqtrade/platform_control tests/markets tests/platform tests/platform_control
Pop-Location
git add .github/workflows/root-safety.yml tests/test_root_safety_workflow.py docs/operations/platform-control.md freqtrade
git commit -m "ci: gate phase2a platform control plane"
```

Expected: all offline gates pass, backend gitlink is the reviewed commit, and root worktree is clean.
