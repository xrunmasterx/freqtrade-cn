
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

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/platform/test_platform_migrations.py -q -p no:cacheprovider
```

Expected: missing Alembic configuration/migration.

- [ ] **Step 3: Implement ORM records**

Define records using `PlatformBase` and typed SQLAlchemy mappings. Identity columns are `String(128)`, timestamps are timezone-aware, payload/provenance fields use `JSON`, and optimistic version is a non-negative integer. Use nullable terminal timestamps/codes only where the state machine allows them.

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

- [ ] **Step 5: Run PostgreSQL GREEN**

```powershell
python -m pytest tests/platform/test_platform_migrations.py -q -p no:cacheprovider
alembic -c alembic-platform.ini check
ruff check freqtrade/platform/runtime_models.py platform_migrations tests/platform/test_platform_migrations.py
```

Expected: empty upgrade, downgrade/upgrade, constraints, and Alembic drift checks pass.

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
- Test: `freqtrade/tests/platform/test_runtime_repository.py`
- Test: `freqtrade/tests/platform/test_runtime_service.py`

**Interfaces:**
- Produces `RuntimeRepository.get_instance()`, `list_instances()`, `create_job()`, `claim_next_job()`, `complete_job()`, `append_audit()`.
- Produces `RuntimeApplicationService.request(command, actor) -> RuntimeJobView`.
- `claim_next_job()` uses `SELECT ... FOR UPDATE SKIP LOCKED` on PostgreSQL.

- [ ] **Step 1: Write RED tests for idempotency, stale versions, and lease claim**

```python
def test_create_job_is_idempotent_for_same_instance_key(repository, stopped_instance) -> None:
    first = repository.create_job(stopped_instance, command("start", "key-1", version=0))
    second = repository.create_job(stopped_instance, command("start", "key-1", version=0))
    assert second.job_id == first.job_id


def test_stale_expected_version_fails_without_job(repository, stopped_instance) -> None:
    with pytest.raises(RuntimeConflict, match="stale_instance_version"):
        repository.create_job(stopped_instance, command("start", "key-2", version=9))
    assert repository.list_jobs(stopped_instance.instance_id) == ()


def test_postgres_claimers_skip_locked_jobs(postgres_repository) -> None:
    first = postgres_repository.claim_next_job("supervisor-a", lease_seconds=30)
    second = postgres_repository.claim_next_job("supervisor-b", lease_seconds=30)
    assert first.job_id != second.job_id
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/platform/test_runtime_repository.py tests/platform/test_runtime_service.py -q -p no:cacheprovider
```

Expected: missing repository/service imports.

- [ ] **Step 3: Implement transactional repository**

Use a repository-owned `Session` transaction. `create_job()` locks the instance row, checks optimistic version and action/state rules, returns the existing row for an identical idempotency key, rejects a conflicting key payload, increments instance optimistic version once, and inserts job plus append-only audit in one commit.

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

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest tests/platform/test_runtime_repository.py tests/platform/test_runtime_service.py -q -p no:cacheprovider
ruff check freqtrade/platform/runtime_repository.py freqtrade/platform/runtime_service.py tests/platform/test_runtime_repository.py tests/platform/test_runtime_service.py
git add freqtrade/platform/runtime_repository.py freqtrade/platform/runtime_service.py freqtrade/platform/__init__.py tests/platform/test_runtime_repository.py tests/platform/test_runtime_service.py
git commit -m "feat(platform): persist idempotent runtime jobs"
```

Expected: dialect-neutral tests pass on SQLite and lock/constraint semantics pass on PostgreSQL.

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
- Binds only configured loopback; production defaults exactly `127.0.0.1:8090`.
- Exposes `/api/v2/ping`, `/api/v2/catalog`, `/api/v2/runtime-instances`, `/api/v2/runtime-instances/{instance_id}` and GET-only child views.
- Mounts no lifecycle POST/PUT/PATCH/DELETE route and no Runtime Access forwarding in 2A.

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

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/platform_control/test_auth.py tests/platform_control/test_app.py -q -p no:cacheprovider
```

Expected: missing `platform_control` package.

- [ ] **Step 3: Implement settings and auth**

`PlatformControlSettings` contains listen host/port, username, API password file, JWT secret file, and `PlatformDatabaseSettings`. It rejects non-loopback listen addresses in Phase 2. Secret files use constant-time comparison and the existing HS256 access/refresh token payload contract so FreqUI can authenticate without Bot credentials.

Auth routes are exactly:

```text
POST /api/v2/token/login
POST /api/v2/token/refresh
```

Do not accept credentials in query parameters or log request headers.

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

`__main__.py` loads settings from fixed environment variable names pointing to exact secret files, builds the engine/repository, and runs Uvicorn. It does not initialize schema.

- [ ] **Step 5: Run GREEN, import audit, and commit**

```powershell
python -m pytest tests/platform_control/test_auth.py tests/platform_control/test_app.py -q -p no:cacheprovider
ruff check freqtrade/platform_control tests/platform_control
python -c "from freqtrade.platform_control.app import create_platform_app; print(create_platform_app.__name__)"
git add freqtrade/platform_control tests/platform_control
git commit -m "feat(platform): add authenticated control service"
```

Expected: tests/Ruff/import pass and API schema contains no lifecycle mutation.

---

### Task 6: Root PostgreSQL/platform-control runtime and least privilege

**Files:**
- Create: `docker/postgres/init-platform-roles.sh`
- Modify: `docker-compose.yml`
- Modify: `Dockerfile`
- Modify: `tools/bootstrap_runtime.py`
- Modify: `tools/runtime_contract.py`
- Test: `tests/test_platform_control_contract.py`
- Test: `tests/test_bootstrap_runtime.py`

**Interfaces:**
- Fixed services: `platform-postgres` internal only and `platform-control` loopback 8090.
- Fixed secrets: admin DB password, platform-control DB password, platform API password, platform JWT secret.
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
ports:
  - target: 8090
    published: "8090"
    host_ip: 127.0.0.1
    protocol: tcp
```

It mounts only its exact password/JWT/DB secret files. Add no Docker socket and no runtime state mount. Secret values are never copied into ordinary environment variables; `PlatformControlSettings` is the single owner that reads and validates exact files for regular-file/permission/single-line/NUL/sentinel/distinct-value rules.

`init-platform-roles.sh` creates fixed `platform_control` and `platform_supervisor` roles using mounted secret files, grants schema usage, grants platform-control SELECT plus `runtime_access_requests` terminal-field update and audit INSERT only, and grants Supervisor/Operator the reviewed Registry application permissions. The script uses `psql` variables, never shell-interpolated SQL passwords.

- [ ] **Step 4: Extend bootstrap and contract validation**

Add exact platform secret specifications to `bootstrap_runtime.py` without adding a directory scan. Extend `runtime_contract.py` with fixed platform service validation separate from `ops/runtime-services.json`; the old manifest remains migration input for exactly three current processes.

- [ ] **Step 5: Run GREEN and commit root task**

```powershell
python -S -m unittest tests.test_platform_control_contract tests.test_bootstrap_runtime tests.test_runtime_contract -v
python tools/compose_runtime.py --profile platform config --format json > $env:TEMP\platform-compose.json
python tools/runtime_contract.py --compose-json $env:TEMP\platform-compose.json
git add Dockerfile docker-compose.yml docker/postgres/init-platform-roles.sh tools/bootstrap_runtime.py tools/runtime_contract.py tests/test_platform_control_contract.py tests/test_bootstrap_runtime.py tests/test_runtime_contract.py
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
- CI upgrades an empty PostgreSQL database to Alembic head, runs PostgreSQL repository tests, starts platform-control without Docker/state mounts, and asserts lifecycle OpenAPI is GET-only.

- [ ] **Step 1: Write failing workflow-structure tests**

Add constants and tests requiring executable steps named exactly:

```text
Start platform PostgreSQL
Upgrade platform schema
Run platform PostgreSQL integration tests
Verify platform-control least privilege
Run Phase 2A backend regressions
```

Mutation tests prove selectors in comments or unrelated steps do not satisfy the gate.

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_root_safety_workflow -v
```

Expected: missing named steps/selectors.

- [ ] **Step 3: Add CI and runbook**

The workflow starts a pinned PostgreSQL service, loads secrets from ephemeral CI files, and executes:

```powershell
alembic -c alembic-platform.ini upgrade head
python -m pytest tests/platform/test_platform_migrations.py tests/platform/test_runtime_repository.py tests/platform_control -q -p no:cacheprovider
ruff check freqtrade/platform freqtrade/platform_control tests/platform tests/platform_control
```

The least-privilege test connects as `platform_control`, proves SELECT and gateway audit/request writes succeed, and proves UPDATE of `runtime_instances.desired_state` fails with permission denied.

Document bootstrap, migration, start, health, logs, backup, rollback, and the fact that Phase 2A performs no Docker lifecycle mutation.

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
