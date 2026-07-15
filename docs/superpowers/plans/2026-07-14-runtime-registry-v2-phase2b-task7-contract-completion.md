# Phase 2B Task 7 Contract Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` and execute one subtask at a time with a fresh implementer and a fresh reviewer. Use test-driven development. Do not push, merge, start a Bot/Worker, contact an exchange, place an order, or perform destructive recovery.

**Goal:** Complete the missing application, persistence, provenance, operator-authority, and CLI contracts needed to publish the reviewed paper-probe template, reserve its fixed inputs, compile one deterministic immutable RuntimeSpec, and register the stopped RuntimeInstance without enabling runtime lifecycle or trading.

**Architecture:** The trusted root CLI verifies exact committed Git blobs and invokes the backend `RuntimeApplicationService`. The service is the only business path and delegates one atomic registration/compile transaction to a PostgreSQL repository. Production commands run in a one-shot `platform-operator` container because PostgreSQL remains internal-only, `platform-control` remains read-only, and the host receives no database port. The operator container has a dedicated least-privilege database role, a fixed read-only Git object-store mount plus only the reviewed non-secret artifact paths needed for clean-check evidence, no host port, no Docker socket, no Bot state, no secret root, no trading secrets, and no lifecycle command surface.

**Why this plan supersedes the original Task 7 steps:** Tasks 1-6 delivered schema, committed templates/policies, template publication, secret/state providers, and the pure compiler. The original Task 7 assumed a registration service/repository and deployable database transport that do not exist. Implementing only `tools/runtime_registry_cli.py` would either be a fake preview or a second direct-SQL business path. This plan closes that gap before adding the CLI.

**Tech Stack:** Python 3.14, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 17, Git plumbing, Docker Compose v2, standard-library unittest, pytest, Ruff.

## Locked assumptions and success criteria

- `paper_probe` preserves the approved design/compiler identity: instance and owner ID `phase2-spot-paper-probe`, owner revision `phase2-spot-paper-probe-v1`, Digital Assets + Spot + Bitget, environment `paper`, `SampleStrategy`, and exact boolean `dry_run=true`.
- The selected strategy is the root-owned committed blob `ft_userdata/user_data/strategies/sample_strategy.py`; therefore its trusted commit is `root_commit`. `strategies_commit` remains component provenance and is not falsely used as the blob owner.
- The committed config is `ft_userdata/user_data/config.example.json`; the committed safety policy is `ops/config/trading-safety.json`. No caller may provide alternative paths, market/product/venue, strategy, environment, template, policy, state path, secret path, image, command, mount, port, network, privilege, Compose fragment, or Docker project.
- The compiler must use the exact immutable Catalog revision and exact active AdapterTemplate revision persisted in PostgreSQL. Bitget Spot paper capability must exist; Live remains denied.
- `register-paper-probe` and `compile` are two CLI names for one idempotent `ensure compiled registration` use case. They must not create a two-phase persisted workflow.
- One transaction ensures the exact Catalog revision, reserves one fixed StateAllocation and exactly three stable SecretReferences (`api_password`, `jwt_secret`, `ws_token`) as metadata, compiles/inserts the immutable RuntimeSpec, and inserts the stopped/registered RuntimeInstance. It never reads secret material, resolves a secret version, or creates the state directory.
- Repeating an identical command is idempotent. Reusing a fixed identity with different committed evidence or persisted context fails with a stable conflict and makes no partial write.
- Audit rows record identifiers, digests, commits, action, actor, and stable result only. No secret value/path, absolute host path, database DSN, or config content enters the database, stdout, stderr, or exception text.
- The operator database role has only the exact SELECT/INSERT authorities required by publication/registration/compile. It cannot update/delete Registry rows, create lifecycle jobs, claim jobs, mutate Runtime Access requests, create schema objects, or inherit another role.
- The one-shot operator transport may start only its own control-plane command container. It cannot start/stop/retry/retire a Bot/Worker and has no Docker socket. Phase 2B still performs no dynamic runtime Docker mutation.
- Success is proven by unit tests, PostgreSQL integration tests with zero PostgreSQL skips in the selected gate, Compose/root-contract tests, deterministic CLI output tests, Ruff, Alembic checks, and an independent review of every subtask.

---

## Task 1: Make the paper-probe Catalog and Git provenance truthful

**Backend files:**

- Modify `freqtrade/freqtrade/markets/default_catalog.py`
- Modify `freqtrade/freqtrade/platform/catalog_repository.py`
- Modify `freqtrade/freqtrade/platform/runtime_compiler.py`
- Modify `freqtrade/tests/markets/test_catalog.py`
- Modify `freqtrade/tests/rpc/test_api_catalog.py`
- Modify `freqtrade/tests/platform/test_catalog_repository.py`
- Modify `freqtrade/tests/platform/test_runtime_compiler.py`

**Required behavior:**

1. Publish `builtin-market-catalog-v2` as a new immutable built-in revision; do not change content under the v1 identity.
2. Add active venue `bitget` with Spot only. Do not advertise Perpetual, Delivery Future, Margin, or Option support. Product capability remains product-scoped: Spot paper is allowed and Spot live is denied by `live_lane_not_enabled`.
3. Add exact immutable lookup `CatalogRepository.get(revision_id)` to both static and SQL repositories. `current()` behavior remains unchanged.
4. Correct paper-probe strategy validation so the fixed root-owned `SampleStrategy` blob must match `components.root_commit`. Keep template/component commit equality checks intact; do not weaken checks for other owners.

**TDD gate:**

```powershell
cd freqtrade
python -m pytest tests/markets/test_catalog.py tests/rpc/test_api_catalog.py tests/platform/test_catalog_repository.py tests/platform/test_runtime_compiler.py -q -p no:cacheprovider
ruff check freqtrade/markets/default_catalog.py freqtrade/platform/catalog_repository.py freqtrade/platform/runtime_compiler.py tests/markets/test_catalog.py tests/rpc/test_api_catalog.py tests/platform/test_catalog_repository.py tests/platform/test_runtime_compiler.py
```

**Commit:** backend only, `fix(runtime): bind paper probe to available catalog and artifacts`.

---

## Task 2: Verify fixed committed paper-probe artifacts at the trust boundary

**Root files:**

- Create `docs/superpowers/plans/2026-07-14-runtime-registry-v2-phase2b-task7-contract-completion.md`
- Modify `.superpowers/sdd/progress.md`
- Create `tools/committed_git.py`
- Create `tools/runtime_artifacts.py`
- Create `tests/test_committed_git.py`
- Create `tests/test_runtime_artifacts.py`
- Modify `tools/runtime_templates.py`
- Modify `tests/test_runtime_templates.py`

**Required behavior:**

1. Create one shared `CommittedGitStore` used by both template/policy publication and runtime-artifact verification. It accepts only a fixed Git object-store location and a full lowercase commit ID; it never accepts a URL, remote, symbolic ref, credential helper, caller path, or caller digest.
2. Produce a frozen, serialization-safe `CommittedPaperProbeArtifacts` containing only root/backend/frontend/strategies commit IDs, config/strategy/safety SHA-256 digests, and strategy class name.
3. Read all trusted bytes with non-interactive Git plumbing from one exact root commit. Require root artifacts to be exact `100644 blob` entries and component gitlinks to be exact `160000 commit` entries. Derive backend, frontend, and strategies component commit IDs from the tree; bind the selected strategy blob itself to `root_commit`.
4. Require the reviewed paths to be clean in the index and the narrowly mounted non-secret worktree view before accepting the commit. Reject symlinks, submodules in blob positions, ordinary blobs in gitlink positions, missing blobs, dirty relevant paths, malformed Git output, and non-ancestor/unapproved commit selection according to the existing committed-template policy.
5. Parse config and safety JSON with duplicate-key and non-finite-number rejection. Require Bitget, Spot, exact boolean `dry_run=true`, and no exchange write credential value. Parse the strategy with `ast`; require exactly the fixed `SampleStrategy` class without importing or executing it.
6. Hash raw committed bytes. Replacing a worktree file after the commit is captured must not change the committed result, while a new invocation rejects the dirty reviewed path. Errors and `repr` expose only stable codes/identities, never content or absolute paths.

**TDD gate:**

```powershell
python -S -m unittest tests.test_committed_git tests.test_runtime_artifacts tests.test_runtime_templates -v
```

**Commit:** root only; explicitly do not stage the dirty backend gitlink. Commit `feat(runtime): verify committed paper probe artifacts`.

---

## Task 3: Add the single backend registration and compile transaction path

**Backend files:**

- Create `freqtrade/freqtrade/platform/runtime_registration.py`
- Create `freqtrade/freqtrade/platform/runtime_registration_repository.py`
- Modify `freqtrade/freqtrade/platform/runtime_service.py`
- Modify `freqtrade/freqtrade/platform/runtime_domain.py`
- Modify `freqtrade/freqtrade/platform/runtime_models.py`
- Modify `freqtrade/freqtrade/platform/__init__.py`
- Modify `freqtrade/freqtrade/platform/template_repository.py`
- Create `freqtrade/platform_migrations/versions/20260714_0004_runtime_registration.py`
- Create `freqtrade/tests/platform/test_runtime_registration.py`
- Create `freqtrade/tests/platform/test_runtime_registration_repository.py`
- Create `freqtrade/tests/platform/test_runtime_registration_repository_postgres.py`
- Modify `freqtrade/tests/platform/test_runtime_service.py`
- Modify `freqtrade/tests/platform/test_template_repository.py`
- Modify `freqtrade/tests/platform/test_template_repository_postgres.py`
- Modify `freqtrade/tests/platform/test_platform_migrations.py`
- Modify `freqtrade/tests/platform/test_template_migrations.py` only if the head-migration assertions require it

**Application interfaces:**

```text
RuntimeApplicationService.publish_template(publication, actor, occurred_at)
RuntimeApplicationService.ensure_paper_probe_registration(request, actor, occurred_at)
RuntimeApplicationService.registration_status(instance_id)
```

The existing positional `RuntimeApplicationService(repository)` lifecycle construction and `request()` behavior remain unchanged. Add keyword-only narrow `template_repository` and `registration_repository` dependencies; an operator-style service need not receive a lifecycle repository, and platform-control is not given the registration repository. A missing required dependency returns one stable configuration error rather than `AttributeError`.

`EnsurePaperProbeRegistrationRequest` exposes only exact template revision ID, component commits, the three committed artifact digests, literal `SampleStrategy`, and the closed policy snapshot. Owner, instance, Catalog, market/product/venue, environment, state/reference IDs, paths, dry-run, and raw runtime power remain backend constants. The stable result/status DTO excludes timestamps, content, paths, DSNs, secret values/versions, and caller choices.

Use deterministic backend-owned identities:

```text
instance/owner_id: phase2-spot-paper-probe
owner_revision: phase2-spot-paper-probe-v1
state_allocation_id: state-phase2-spot-paper-probe-v1
secret reference IDs:
  secret-phase2-spot-paper-probe-api-password-v1
  secret-phase2-spot-paper-probe-jwt-secret-v1
  secret-phase2-spot-paper-probe-ws-token-v1
audit_event_id: audit-register-phase2-spot-paper-probe
request_id: request-register-phase2-spot-paper-probe
```

The registration repository, not the service or CLI, constructs the fixed `CompileRuntimeRequest` from transaction-local typed rows and the trusted committed evidence.

**Repository transaction rules:**

- The transaction first acquires a deterministic PostgreSQL transaction-scoped advisory lock derived from the exact paper-probe template revision ID, then reads and validates the exact active template row. Registration must not use `SELECT ... FOR UPDATE`, because the one-shot operator role intentionally has no table UPDATE privilege.
- Template deprecate/revoke transitions acquire the same advisory lock before their existing row lock. This preserves serialization between registration and status transitions without expanding operator grants. SQLite uses an explicit no-op adapter only for unit tests; PostgreSQL integration proves the real lock.
- It inserts the exact built-in Catalog v2 only when absent; an existing JSON row must pass exact `CatalogSnapshot` validation and canonical semantic equality with the built-in v2 snapshot. Byte formatting is not compared because the JSON database type does not preserve it.
- Catalog insertion uses insert-if-absent/no-update semantics and then exact readback so a concurrent immutable Catalog publisher cannot abort or overwrite registration.
- It idempotently ensures one fresh/reserved `StateAllocationRecord` and exactly three active `SecretReferenceRecord`s for the fixed owner. Existing rows must exactly match every non-historical field; missing, extra-active, disabled, retired, restored, ready, alternate-generation, alternate-path, or alternate-owner metadata is a stable conflict.
- All ORM access occurs through one `Session.begin()`. Existing repository public methods that create another Session must not be called. Extract/reuse pure row-to-typed-view validation from `template_repository.py` rather than duplicating its canonical payload/digest/provenance checks.
- It invokes the pure compiler with those transaction-local typed records and committed artifact identities. SQLite tests prove sequential atomicity/replay/conflict only; PostgreSQL tests own advisory-lock and concurrent-idempotency guarantees.
- It inserts or exactly validates the immutable `RuntimeSpecRevisionRecord`, inserts or exactly validates the stopped/registered `RuntimeInstanceRecord`, and appends exactly one `register_paper_probe` audit event before commit.
- Registration does not create a directory, read a secret, resolve a secret version, create a lifecycle job, or leave a reserved half-state visible after failure.
- An identical digest/instance replay returns the same stable result without a second audit. Existing instance-without-audit or audit-without-instance is corruption and fails closed rather than being silently healed. A mismatching Catalog payload, digest, owner, allocation, secret set, template status, or component evidence fails with a stable conflict.
- `ensure` always requires the template to remain active; read-only `registration_status` returns the historical registered identity even if the template is later deprecated/revoked.
- Only expected uniqueness races are translated. Unexpected `IntegrityError` is re-raised. No broad exception swallowing or automatic retry.
- Add only the closed audit action `register_paper_probe`; Catalog/allocation/reference/spec/instance inserts are one atomic business action and do not manufacture misleading partial audit events. Existing revision `20260714_0003` belongs to template audit actions and must not be rewritten. New linear migration `20260714_0004` has `down_revision="20260714_0003"` and expands the database check constraint without weakening other values. Downgrade to `0003` succeeds only when no registration audit exists; otherwise it fails closed and preserves append-only evidence. Upgrade from `0001`, `0002`, `0003`, and head fixtures, empty downgrade, populated downgrade refusal, single head, and metadata drift must be tested on PostgreSQL.

**TDD gate:**

```powershell
cd freqtrade
python -m pytest tests/platform/test_runtime_registration.py tests/platform/test_runtime_registration_repository.py tests/platform/test_runtime_registration_repository_postgres.py tests/platform/test_runtime_service.py tests/platform/test_template_repository.py tests/platform/test_template_repository_postgres.py tests/platform/test_platform_migrations.py tests/platform/test_template_migrations.py -q -p no:cacheprovider
alembic -c alembic-platform.ini check
ruff check freqtrade/platform/runtime_registration.py freqtrade/platform/runtime_registration_repository.py freqtrade/platform/runtime_service.py freqtrade/platform/runtime_domain.py freqtrade/platform/template_repository.py platform_migrations/versions/20260714_0004_runtime_registration.py tests/platform/test_runtime_registration.py tests/platform/test_runtime_registration_repository.py tests/platform/test_runtime_registration_repository_postgres.py tests/platform/test_runtime_service.py tests/platform/test_template_repository.py tests/platform/test_template_repository_postgres.py
```

The PostgreSQL selector must run against `PLATFORM_TEST_POSTGRES_URL`; a skip is a gate failure, not a pass.

**Commit:** backend only, `feat(platform): register compiled runtime specifications`.

---

## Task 4: Add the least-privilege one-shot platform-operator boundary

**Root files:**

- Modify `docker-compose.yml`
- Modify `Dockerfile`
- Modify `docker/postgres/init-platform-roles.sh`
- Modify `tools/bootstrap_runtime.py`
- Modify `tools/runtime_contract.py`
- Modify `tests/test_bootstrap_runtime.py`
- Modify `tests/test_runtime_contract.py`
- Modify `tests/test_platform_control_contract.py`
- Modify `tests/test_root_safety_workflow.py` for role/Compose contract assertions only
- Modify `docs/operations/platform-control.md`

**Required behavior:**

1. Add fixed secret `platform_operator_db_password` and bootstrap it with the same non-printing, hardened secret-file rules as existing platform database credentials.
2. Add PostgreSQL role `platform_operator`: LOGIN, NOINHERIT, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS; no object ownership, schema create, database create/temp, or broad default privileges.
3. Grant only:
   - SELECT on Catalog, template, allocation, secret-reference, RuntimeSpec, instance, and audit tables needed to validate/idempotently read;
   - INSERT on Catalog revisions, template revisions, allocations, secret references, RuntimeSpecs, instances, and audit events;
   - no UPDATE/DELETE/TRUNCATE; no lifecycle-job, attempt, endpoint, Runtime Access request, or secret-version write.
4. Reconciliation is rerunnable after Alembic creates new tables. CI proves both allowed operations and denied mutations using the actual role.
5. Copy only the reviewed operator Python modules into a fixed image path. Add one-shot Compose service `platform-operator` with no `container_name`, `restart: "no"`, no ports, `read_only: true`, all capabilities dropped, no-new-privileges, `platform-db` only, and the exact operator DB secret only.
6. Mount the root Git object store read-only at a fixed location. To retain the existing dirty-template guard without exposing the repository, mount only the reviewed non-secret template/policy directories and the three fixed paper-probe artifact files read-only at their matching synthetic-worktree paths. Never mount the full repository, `ft_userdata/secrets`, `ft_userdata/runtime`, Bot configs, or a Docker socket.
7. Override entrypoint to the fixed image-owned operator CLI. The service may be invoked only with explicit typed CLI arguments. It cannot expose start/stop/retry/retire, shell, arbitrary module, arbitrary script, or raw Compose/Docker arguments.
8. Document that `docker compose run --rm --no-deps platform-operator ...` starts only this command carrier; the database must already be healthy. This is not a managed RuntimeInstance and does not grant Bot lifecycle authority. A normal recursive checkout is required; linked-worktree Git indirection is not silently followed across unmounted host paths.

**TDD gate:**

```powershell
python -S -m unittest tests.test_bootstrap_runtime tests.test_runtime_contract tests.test_platform_control_contract tests.test_root_safety_workflow -v
python tools/runtime_contract.py --platform
```

No actual Compose service is started in this subtask.

**Commit:** root only; explicitly do not stage the backend gitlink. Commit `feat(platform): add trusted operator boundary`.

---

## Task 5: Add the typed CLI, Root Safety gate, and reviewed gitlink

**Root files:**

- Create `tools/runtime_registry_cli.py`
- Create `tests/test_runtime_registry_cli.py`
- Modify `.github/workflows/root-safety.yml`
- Modify `tests/test_root_safety_workflow.py`
- Modify `.superpowers/sdd/progress.md`
- Update root `freqtrade` gitlink only after backend review passes

**CLI commands:**

```text
runtime-template validate
runtime-template publish
runtime-registry register-paper-probe
runtime-registry compile
runtime-registry status
```

**Required behavior:**

1. Use `argparse` subparsers and explicit flags only. The paper-probe identity and all policy choices are constants; callers may provide only the approved operator identity where required and the fixed instance ID selector where harmless.
2. `validate` is offline and verifies committed template/policy/artifact evidence without PostgreSQL.
3. `publish`, `register-paper-probe`, `compile`, and database-backed `status` construct backend repositories/compiler and call `RuntimeApplicationService`; CLI code never inserts/updates SQL directly.
4. `publish` publishes only the fixed committed paper-probe template. `register-paper-probe` and `compile` both call the same atomic `ensure_paper_probe_registration` service method, which ensures exact built-in Catalog v2; neither command implements a partial persistence path or selects the latest Catalog implicitly.
5. The atomic ensure operation is deterministic and persists the Catalog/allocation/references/spec/instance/audit together. It performs no state provisioning, secret resolution, Docker lifecycle, external network access, or exchange access.
6. Output is canonical JSON containing only fixed identifiers, status, commit IDs, and digests. Repeating identical commands produces the same semantic result; timestamps are not printed. Stable failures print a code only.
7. Unknown flags and all raw power flags (`--image`, `--command`, `--mount`, `--path`, `--port`, `--network`, `--compose`, `--project`, `--environment`, `--venue`, `--strategy`, `--secret`, and lifecycle verbs) exit 2 before service construction.
8. Root Safety adds explicit offline root/backend selectors plus a PostgreSQL operator integration selector. CI creates the operator role, upgrades to Alembic head, reconciles grants, executes publish/register/compile/status twice, proves deterministic/idempotent results, proves Live and raw-power rejection, and fails if PostgreSQL tests skip.

**Focused gate:**

```powershell
python -S -m unittest tests.test_runtime_registry_cli tests.test_runtime_artifacts tests.test_runtime_templates tests.test_runtime_secrets tests.test_runtime_state tests.test_bootstrap_runtime tests.test_runtime_contract tests.test_platform_control_contract tests.test_root_safety_workflow -v
Push-Location freqtrade
python -m pytest tests/markets/test_catalog.py tests/rpc/test_api_catalog.py tests/platform/test_catalog_repository.py tests/platform/test_template_domain.py tests/platform/test_template_repository.py tests/platform/test_runtime_compiler.py tests/platform/test_runtime_registration.py tests/platform/test_runtime_registration_repository.py tests/platform/test_runtime_registration_repository_postgres.py tests/platform/test_runtime_service.py tests/platform/test_platform_migrations.py tests/platform/test_template_migrations.py -q -p no:cacheprovider
ruff check freqtrade/markets/default_catalog.py freqtrade/platform tests/markets/test_catalog.py tests/rpc/test_api_catalog.py tests/platform
alembic -c alembic-platform.ini check
Pop-Location
```

**Affected regression gate:** run the Root Safety standard-library discovery command and all backend `markets`, `platform`, and `platform_control` tests. PostgreSQL-gated registration tests must run with zero skips.

**Commit:** after independent backend and root reviews, stage only CLI/tests/workflow/progress plus the exact reviewed backend gitlink. Commit `ci: gate phase2b runtime compiler`.

---

## Final Task 7 completion gate

1. Inspect root and backend diffs against their Task 7 bases; every changed line must trace to this plan.
2. Run the focused and affected regression gates from a clean tree, without cache.
3. Confirm no tests were skipped because PostgreSQL was unavailable in the mandatory integration selector.
4. Confirm `docker compose config` contains no PostgreSQL host port and the operator service contains no Docker socket, runtime state, trading secret, ingress network, or lifecycle command.
5. Confirm the operator role cannot write lifecycle jobs/attempts/endpoints/access requests and cannot update/delete any Registry row.
6. Confirm CLI help exposes no lifecycle or raw-container option and all outputs are non-secret.
7. Run an independent whole-Task-7 architecture/security/code-quality review. Fix all findings and rerun gates.
8. Leave both repositories clean. Do not push or create/merge a PR until the user separately requests publication.
