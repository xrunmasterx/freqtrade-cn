# P0 Draft PR Safety Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every verified P0 Draft PR merge blocker while preserving dynamic non-root execution, service isolation, recovery correctness, and evidence-backed CI.

**Architecture:** Formal services use `/freqtrade/state` as their only writable root and explicit read-only inputs. Controlled launch builds a temporary context from committed root/backend/frontend trees, verifies image provenance, and recreates exactly one service by inspected image ID. State migration is manifest-lane driven with POSIX durability barriers and an explicit weaker Windows contract; root CI becomes standard-library-first.

**Tech Stack:** Python standard library and `unittest`, Docker Engine, Docker Compose v5.1.4, Git submodules/archives, Freqtrade CLI, GitHub Actions, Vue 3/Pinia/TypeScript, Vitest, pnpm 11.9.0.

## Global Constraints

- The approved specification is `docs/superpowers/specs/2026-07-11-p0-draft-pr-safety-closure-design.md`.
- No runtime sudo, runtime chown, chmod `0777`, root fallback, arbitrary Docker flags, raw Compose launch, or mutable-tag launch is allowed.
- `/freqtrade/state` is the only writable service root.
- `/freqtrade/config/**`, `/freqtrade/user_data/strategies/**`, `/freqtrade/user_data/research_data/**`, and `/run/secrets/**` remain read-only.
- Trading config order is runtime config followed by the safety overlay; the safety overlay remains last.
- Formal startup tests use UID:GID `12345:12345`, dry-run config, ephemeral secrets/state, and Docker `--network none`; they never contact a live account.
- Root tools and the first root test gate use Python standard-library dependencies only.
- Formal backup source and restore destination are derived from `ops/runtime-services.json`; callers cannot override them.
- POSIX success may claim `power-loss-posix` only after every approved file/directory sync barrier. Windows reports only `atomic-process-crash`.
- Tests and errors must not print secret values, trade/order rows, full environments, JWTs, or WS tokens.
- User-owned QQE/chart/indicator work must not be modified, cleaned, or staged.
- Docker base-image digest pinning, `reloadConfig` stale-reference redesign, live reconciliation, row-content canonical digests, signing, and attestation are out of scope.
- Every production change is preceded by a test that fails for the intended reason, followed by focused GREEN, self-review, independent spec review, and independent quality/security review.

---

## File and interface map

### Runtime layout and startup

- `docker-compose.yml`: formal commands and mount layout.
- `tools/bootstrap_runtime.py`: writable state directory inventory.
- `tools/runtime_contract.py`: exact command/mount contract.
- `tools/compose_runtime.py`: fixed state probe and public control surface.
- `tools/formal_startup.py`: production-argv offline startup verifier.
- `tests/test_bootstrap_runtime.py`, `tests/test_runtime_contract.py`, `tests/test_compose_runtime.py`, `tests/test_formal_startup.py`: RED/GREEN coverage.

### Build provenance

- `tools/committed_build.py`: commit identity and safe archive assembly.
- `tools/image_provenance.py`: tag/labels/build/inspect result.
- `Dockerfile`: full revision labels.
- `tests/test_committed_build.py`, `tests/test_image_provenance.py`: archive and image contract.

### Recovery

- `tools/sqlite_state.py`: service lanes, schema 2, archive separation, durability helpers.
- `tests/test_sqlite_state.py`: cross-lane, compatibility, barrier ordering, and fault injection.
- `docs/operations/sqlite-backup-and-restore.md`: exact operator commands and platform claims.

### CI and frontend

- `.github/workflows/root-safety.yml`: standard-library-first gates and final integrations.
- `tests/test_root_safety_workflow.py`: dependency-free named-step/order contract.
- `frequi/src/stores/ftbotwrapper.ts`, `frequi/src/components/ftbot/TradeList.vue`: disappeared-target failure.
- `frequi/tests/unit/ftbotwrapperTradeRouting.spec.ts`, `frequi/tests/component/TradeListTradeActions.spec.ts`: routing/UI races.

---

### Task 1: Make the formal runtime layout dynamic-UID safe

**Files:**
- Modify: `docker-compose.yml`
- Modify: `tools/bootstrap_runtime.py`
- Modify: `tools/runtime_contract.py`
- Modify: `tools/compose_runtime.py`
- Test: `tests/test_bootstrap_runtime.py`
- Test: `tests/test_runtime_contract.py`
- Test: `tests/test_compose_runtime.py`
- Modify: `README.docker.md`

**Interfaces:**
- Produces constants in `tools/runtime_contract.py`:

```python
EXPECTED_USER_DATA_DIR = "/freqtrade/state"
EXPECTED_STRATEGY_PATH = "/freqtrade/user_data/strategies"
```

- Trading commands contain exactly one userdata option and one strategy-path option.
- Research contains exactly one userdata option and no strategy-path option.
- `_service_writable_directories(state_root: Path) -> tuple[Path, ...]` is the single bootstrap directory inventory.

- [ ] **Step 1: Add failing bootstrap layout tests**

Add tests named:

```text
test_init_creates_complete_state_layout_for_every_service
test_init_never_creates_state_strategy_directory
test_verify_requires_data_and_backtest_directories_for_every_service
```

Assert each state root has `home`, `logs`, `data`, and `backtest_results`, and never `strategies`.

- [ ] **Step 2: Add failing exact Compose contract tests**

Add tests named:

```text
test_requires_state_userdata_and_read_only_strategy_path
test_rejects_duplicate_or_wrong_userdata_and_strategy_paths
test_research_uses_state_userdata_without_strategy_path
test_research_removes_writable_userdata_alias_mounts
test_state_check_reuses_formal_userdata_contract
```

Mutations must cover missing, duplicate, wrong, and reordered options plus the two obsolete Research alias mounts.

- [ ] **Step 3: Run focused RED**

```powershell
python -m unittest `
  tests.test_bootstrap_runtime `
  tests.test_runtime_contract `
  tests.test_compose_runtime -v
```

Expected: new directory and argv assertions fail because formal commands still default to `/freqtrade/user_data` and Research still has alias mounts.

- [ ] **Step 4: Implement the minimum runtime layout**

Formal command fragments become:

```text
Spot/Futures:
--user-data-dir /freqtrade/state
--strategy-path /freqtrade/user_data/strategies

Research:
--user-data-dir /freqtrade/state
```

Remove Research mounts targeting `/freqtrade/user_data/data` and `/freqtrade/user_data/backtest_results`. Expand bootstrap's one writable-directory helper; do not duplicate lists in `init` and `verify`. Make `check-state` consume the same userdata constant rather than a probe-only literal.

- [ ] **Step 5: Run focused GREEN and contract checks**

```powershell
python -m unittest tests.test_bootstrap_runtime tests.test_runtime_contract tests.test_compose_runtime -v
python tools/runtime_contract.py
python tools/compose_runtime.py --profile trading --profile research config --quiet
git diff --check
```

Expected: all exit `0`; rendered config has one writable state root per service and no writable strategy/research input.

- [ ] **Step 6: Commit Task 1**

```powershell
git add docker-compose.yml tools/bootstrap_runtime.py tools/runtime_contract.py tools/compose_runtime.py tests/test_bootstrap_runtime.py tests/test_runtime_contract.py tests/test_compose_runtime.py README.docker.md
git diff --cached --check
git commit -m "fix(runtime): make formal service paths dynamic-uid safe"
```

---

### Task 2: Verify formal startup under a non-1000 UID

**Files:**
- Create: `tools/formal_startup.py`
- Create: `tests/test_formal_startup.py`
- Modify: `.github/workflows/root-safety.yml`
- Modify: `README.docker.md`

**Interfaces:**

```python
@dataclass(frozen=True)
class StartupExpectation:
    service: str
    command: tuple[str, ...]
    requires_healthcheck: bool
    accepted_network_error_markers: tuple[str, ...]

def formal_command(compose: Mapping[str, Any], service: str) -> tuple[str, ...]: ...
def build_offline_docker_command(*, image: str, expectation: StartupExpectation,
                                 runtime_uid: int, runtime_gid: int,
                                 repo_root: Path, probe_root: Path) -> list[str]: ...
def verify_startup_result(expectation: StartupExpectation,
                          completed: subprocess.CompletedProcess[str]) -> None: ...
def verify_formal_startup(service: str, *, image: str, repo_root: Path,
                          runtime_uid: int = 12345, runtime_gid: int = 12345,
                          timeout_seconds: int = 45) -> None: ...
```

- [ ] **Step 1: Add failing unit tests for production-argv reuse and isolation**

Tests:

```text
test_formal_command_reads_rendered_production_argv
test_offline_command_uses_non_1000_uid_network_none_and_ephemeral_inputs
test_trading_rejects_userdata_strategy_secret_and_database_failures
test_trading_accepts_only_the_named_external_network_boundary
test_research_requires_ping_and_bounded_clean_stop
test_failure_output_is_secret_and_row_safe
```

- [ ] **Step 2: Run unit RED**

```powershell
python -m unittest tests.test_formal_startup -v
```

Expected: import failure because `tools.formal_startup` does not exist.

- [ ] **Step 3: Implement the fixed offline verifier**

It must read rendered production `command`, mount ephemeral state/secrets, preserve read-only config/strategy/research inputs, use `--network none --user 12345:12345`, run the real entrypoint, classify only fixed local-contract results, poll Research ping from inside its isolated container, and stop/remove in `finally`. If exchange error text is not stable enough, add one backend-native command that reuses production Configuration/directory code and does not instantiate the exchange.

- [ ] **Step 4: Add and run the Docker integration RED/GREEN**

Test name:

```text
FormalStartupDockerTests.test_all_formal_services_pass_dynamic_uid_contract
```

```powershell
python -m unittest tests.test_formal_startup.FormalStartupDockerTests.test_all_formal_services_pass_dynamic_uid_contract -v
```

Before Task 1 it reproduces `/freqtrade/user_data` R/W/X failure. After GREEN, Spot/Futures pass the local contract without arbitrary non-zero acceptance and Research answers ping.

- [ ] **Step 5: Add a blocking Root Safety startup step and run GREEN**

```powershell
python -m unittest tests.test_formal_startup -v
python tools/formal_startup.py verify-all --image freqtrade-cn:local
git diff --check
```

- [ ] **Step 6: Commit Task 2**

```powershell
git add tools/formal_startup.py tests/test_formal_startup.py .github/workflows/root-safety.yml README.docker.md
git diff --cached --check
git commit -m "test(runtime): gate formal dynamic-uid startup"
```

---

### Task 3: Narrow the public Compose control surface

**Files:**
- Modify: `tools/compose_runtime.py`
- Test: `tests/test_compose_runtime.py`
- Modify: `README.docker.md`
- Modify: `docs/operations/runtime-secrets.md`
- Modify: `docs/operations/sqlite-backup-and-restore.md`

**Interfaces:**

```python
LaunchService = Callable[[str, Path], subprocess.CompletedProcess[str]]

def launch_service_pending_provenance(service: str, root: Path) -> subprocess.CompletedProcess[str]: ...
```

Public actions are exactly `config/up/down/stop/ps/logs`. `up` accepts one service and no flags.

- [ ] **Step 1: Add parser/dispatch RED tests**

```text
test_parser_exposes_only_approved_public_actions
test_parser_requires_up_with_exactly_one_approved_service_and_no_flags
test_parser_rejects_create_start_and_restart_before_docker
test_up_delegates_to_internal_launcher_with_frozen_service
test_non_launch_actions_never_call_internal_launcher
test_stop_down_ps_and_logs_remain_available_when_launch_validation_fails
```

- [ ] **Step 2: Run RED**

```powershell
python -m unittest tests.test_compose_runtime -v
```

Expected: old parser accepts forbidden actions/flags and has no launcher seam.

- [ ] **Step 3: Implement the minimum surface reduction**

Remove `create/start/restart`, reject caller `up` flags/profiles, require exactly one service, and route only `up` to the injected internal launcher. Leave committed context and image provenance for Tasks 4-5.

- [ ] **Step 4: Update all supported runbook commands and run GREEN**

```powershell
python -m unittest tests.test_compose_runtime -v
rg -n "compose_runtime.py .*\b(create|start|restart)\b|compose_runtime.py up --" README.docker.md docs/operations
git diff --check
```

Expected: tests pass and `rg` finds no supported use of removed verbs or user-controlled `up` flags.

- [ ] **Step 5: Commit Task 3**

```powershell
git add tools/compose_runtime.py tests/test_compose_runtime.py README.docker.md docs/operations/runtime-secrets.md docs/operations/sqlite-backup-and-restore.md
git diff --cached --check
git commit -m "fix(runtime): narrow compose control actions"
```

---

### Task 4: Assemble Docker context from committed trees only

**Files:**
- Create: `tools/committed_build.py`
- Create: `tests/test_committed_build.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class CommitIdentity:
    root: str
    backend: str
    frontend: str

    def short_tag(self, length: int = 12) -> str: ...

def resolve_commit_identity(root: Path) -> CommitIdentity: ...
def verify_committed_checkout(root: Path, identity: CommitIdentity) -> None: ...
def validate_archive_member(name: str, linkname: str | None = None) -> None: ...
def extract_git_archive(stream: BinaryIO, destination: Path) -> None: ...

@contextmanager
def committed_build_context(root: Path, identity: CommitIdentity) -> Iterator[Path]: ...
```

- [ ] **Step 1: Add real temporary-Git RED tests**

```text
test_resolves_root_and_exact_gitlink_commits
test_rejects_submodule_head_mismatch
test_rejects_tracked_root_backend_or_frontend_changes
test_rejects_nonignored_untracked_root_backend_or_frontend_paths
test_ignored_outputs_do_not_enter_context
test_context_contains_root_backend_and_frontend_committed_bytes_only
test_context_excludes_runtime_secrets_configs_databases_and_dirty_strategies
test_rejects_archive_absolute_traversal_control_and_special_entries
test_rejects_escaping_symlink_and_hardlink_targets
test_context_is_removed_after_success_and_exception
```

- [ ] **Step 2: Run RED**

```powershell
python -m unittest tests.test_committed_build -v
```

Expected: module import failure.

- [ ] **Step 3: Implement commit resolution and safe archive extraction**

Use list-form Git subprocesses. Resolve root `HEAD`, `HEAD:freqtrade`, and `HEAD:frequi`; require mode `160000`, full SHA, submodule HEAD equality, no tracked changes, and no non-ignored untracked paths. Validate tar members before writing: reject absolute/drive/UNC paths, `..`, control characters, special files, path-type conflicts, and escaping symlink/hardlink targets. Never call unvalidated `extractall()`.

- [ ] **Step 4: Implement context lifecycle and run GREEN**

Assemble root, backend, and frontend archives in a unique OS temp directory and remove it after normal or exceptional exit.

```powershell
python -m unittest tests.test_committed_build tests.test_compose_runtime -v
python -m compileall -q tools/committed_build.py
git diff --check
```

- [ ] **Step 5: Commit Task 4**

```powershell
git add tools/committed_build.py tests/test_committed_build.py
git diff --cached --check
git commit -m "security: build from committed trees only"
```

---

### Task 5: Bind launch to inspected image provenance

**Files:**
- Create: `tools/image_provenance.py`
- Create: `tests/test_image_provenance.py`
- Modify: `Dockerfile`
- Modify: `tools/compose_runtime.py`
- Modify: `tools/runtime_contract.py`
- Test: `tests/test_compose_runtime.py`
- Test: `tests/test_runtime_contract.py`
- Modify: `.github/workflows/root-safety.yml`
- Modify: `README.docker.md`

**Interfaces:**

```python
@dataclass(frozen=True)
class InspectedImage:
    image_id: str
    tag: str
    labels: Mapping[str, str]

def provenance_tag(identity: CommitIdentity) -> str: ...
def expected_labels(identity: CommitIdentity) -> dict[str, str]: ...
def build_committed_image(context: Path, identity: CommitIdentity,
                          *, timeout_seconds: int = 1800) -> str: ...
def inspect_image(reference: str) -> InspectedImage: ...
def verify_image_provenance(image: InspectedImage, identity: CommitIdentity) -> None: ...
def build_and_inspect_image(context: Path, identity: CommitIdentity) -> InspectedImage: ...
def launch_reviewed_service(service: str, root: Path) -> subprocess.CompletedProcess[str]: ...
```

Labels are complete root/backend/frontend SHAs; actual launch uses the inspected `sha256:` image ID.

- [ ] **Step 1: Add image and launch RED tests**

```text
test_tag_contains_three_short_committed_revisions
test_build_uses_committed_context_and_complete_revision_labels
test_inspect_requires_sha256_image_id_and_exact_complete_labels
test_rejects_missing_mismatched_or_extra_identity_labels
test_accepts_launch_render_with_exact_image_id_and_no_build
test_rejects_mutable_tag_or_build_in_launch_render
test_up_builds_context_inspects_labels_and_launches_exact_image_id
test_up_uses_fixed_recreate_no_build_no_deps_flags
test_up_never_launches_when_build_inspect_or_label_validation_fails
test_up_cleans_context_after_every_failure
test_emergency_actions_do_not_require_image_provenance
```

- [ ] **Step 2: Run RED**

```powershell
python -m unittest tests.test_image_provenance tests.test_runtime_contract tests.test_compose_runtime -v
```

Expected: provenance module absent and current render accepts only the mutable source image/build definition.

- [ ] **Step 3: Implement build, labels, inspect, and launch override**

Use tag `freqtrade-cn:p0-<root12>-<backend12>-<frontend12>` and full revision labels. Build only Task 4's context. Validate exact labels and one `sha256:` ID. Render a launch override with that image ID and no selected-service build source. Internally run exactly:

```text
up --detach --force-recreate --no-build --no-deps <service>
```

Never fall back to `freqtrade-cn:local`, a tag, or an existing container.

- [ ] **Step 4: Replace raw workflow build and run GREEN**

```powershell
python -m unittest tests.test_committed_build tests.test_image_provenance tests.test_compose_runtime tests.test_runtime_contract tests.test_formal_startup -v
python tools/runtime_contract.py
python tools/image_provenance.py build --print-image-id
git diff --check
```

Expected: exact labels, launch-render contract, fixed flags, and cleanup all pass.

- [ ] **Step 5: Commit Task 5**

```powershell
git add Dockerfile tools/image_provenance.py tools/compose_runtime.py tools/runtime_contract.py tests/test_image_provenance.py tests/test_compose_runtime.py tests/test_runtime_contract.py .github/workflows/root-safety.yml README.docker.md
git diff --cached --check
git commit -m "security: bind runtime launch to reviewed image"
```

---

### Task 6: Bind SQLite bundles to formal service lanes

**Files:**
- Modify: `tools/sqlite_state.py`
- Test: `tests/test_sqlite_state.py`
- Modify: `docs/operations/sqlite-backup-and-restore.md`

**Interfaces:**

```python
BundlePurpose = Literal["service-state", "archive"]
CreationPlatform = Literal["posix", "windows"]
DurabilityLevel = Literal["unknown", "atomic-process-crash", "power-loss-posix"]

@dataclass(frozen=True)
class ServiceLane:
    service: str
    legacy_source: Path
    destination: Path

@dataclass(frozen=True)
class VerifiedBundle:
    schema_version: int
    purpose: BundlePurpose
    service: str | None
    archive_label: str | None
    source_filename: str
    creation_platform: CreationPlatform | None
    durability: DurabilityLevel
    database_sha256: str
    database_size: int
    metadata: dict[str, object]

def resolve_service_lane(*, service: str, root: Path = REPO_ROOT,
                         manifest_path: Path | None = None) -> ServiceLane: ...
def create_service_backup(*, service: str, output_root: Path, now: datetime,
                          root: Path = REPO_ROOT,
                          manifest_path: Path | None = None) -> Path: ...
def create_archive(*, label: str, source: Path, output_root: Path,
                   now: datetime) -> Path: ...
def restore_service(*, service: str, bundle: Path, root: Path = REPO_ROOT,
                    manifest_path: Path | None = None,
                    allow_legacy_schema1: bool = False) -> Path: ...
def compare_structure(source: Path, candidate: Path) -> None: ...
```

Do not retain public generic source/destination escape hatches.

- [ ] **Step 1: Add schema/lane/cross-restore RED tests**

Cover exact schema 2 fields, Spot/Futures lane derivation, Research/unknown/path escape rejection, archive non-promotability, schema 1 unknown durability, explicit legacy flag, source filename match, destination no-clobber, missing parent, and both cross-service restores rejected before `mkstemp/copy/link`.

- [ ] **Step 2: Run focused RED**

```powershell
python -m unittest tests.test_sqlite_state.SQLiteStateTests.test_restore_service_rejects_futures_bundle_for_spot_before_any_write tests.test_sqlite_state.SQLiteStateTests.test_restore_service_rejects_spot_bundle_for_futures_before_any_write tests.test_sqlite_state.SQLiteStateTests.test_schema2_service_bundle_has_exact_fields_and_identity tests.test_sqlite_state.SQLiteStateTests.test_archive_bundle_cannot_restore_to_formal_service -v
```

Expected: missing APIs or current cross-service restore succeeds.

- [ ] **Step 3: Implement schema 2 and formal lane commands**

Add `backup-service`, `restore-service`, `archive`, `verify`, and `compare-structure`; remove old generic `backup/restore/compare`. Formal source/destination come only from the strict runtime manifest. Task 6 records `atomic-process-crash` on all platforms; Task 7 upgrades POSIX after barriers exist. Keep `--print-path` stdout exactly one path line.

- [ ] **Step 4: Update runbook and run GREEN**

```powershell
python -m unittest tests.test_sqlite_state tests.test_bootstrap_runtime -v
python tools/runtime_contract.py
git diff --check
```

- [ ] **Step 5: Commit Task 6**

```powershell
git add tools/sqlite_state.py tests/test_sqlite_state.py docs/operations/sqlite-backup-and-restore.md
git diff --cached --check
git commit -m "security: bind SQLite bundles to service lanes"
```

---

### Task 7: Enforce durability policy B

**Files:**
- Modify: `tools/sqlite_state.py`
- Test: `tests/test_sqlite_state.py`
- Modify: `docs/operations/sqlite-backup-and-restore.md`

**Interfaces:**

```python
def _is_posix() -> bool: ...
def _sync_file(path: Path) -> None: ...
def _sync_directory(path: Path) -> None: ...
def _new_bundle_durability() -> DurabilityLevel: ...
```

- [ ] **Step 1: Add exact barrier-order and failure-injection RED tests**

Cover POSIX database/manifest/staging/output sync order, temporary/link/two-parent-sync restore order, every sync failure, quarantine after post-publication failure, Windows file sync without directory sync, Windows `atomic-process-crash`, POSIX `power-loss-posix`, and a POSIX real-helper smoke skipped elsewhere.

- [ ] **Step 2: Run focused RED**

```powershell
python -m unittest tests.test_sqlite_state.SQLiteStateTests.test_posix_backup_orders_file_and_directory_sync_before_success tests.test_sqlite_state.SQLiteStateTests.test_posix_restore_orders_file_and_directory_sync_before_success tests.test_sqlite_state.SQLiteStateTests.test_posix_backup_output_root_sync_failure_raises_and_quarantines_published_bundle tests.test_sqlite_state.SQLiteStateTests.test_posix_restore_first_parent_sync_failure_raises_and_quarantines_destination tests.test_sqlite_state.SQLiteStateTests.test_windows_schema2_reports_atomic_process_crash -v
```

- [ ] **Step 3: Implement approved file/directory barriers**

POSIX backup order is DB sync, manifest sync, verify, staging-dir sync, rename, output-root sync. POSIX restore order is temp sync, verify, link, parent sync, unlink, parent sync. Windows calls regular-file sync only and never claims directory durability. Pre-publication failures clean uncommitted artifacts; post-publication failures retain quarantine and return failure.

- [ ] **Step 4: Run GREEN on the host and POSIX CI selector**

```powershell
python -m unittest tests.test_sqlite_state -v
python -m unittest discover -s tests -p "test_*.py" -v
git diff --check
```

On POSIX:

```bash
python -m unittest tests.test_sqlite_state.SQLiteStateTests.test_posix_real_file_and_directory_sync_helpers_accept_temp_paths -v
```

- [ ] **Step 5: Commit Task 7**

```powershell
git add tools/sqlite_state.py tests/test_sqlite_state.py docs/operations/sqlite-backup-and-restore.md
git diff --cached --check
git commit -m "security: enforce SQLite durability barriers"
```

---

### Task 8: Restore the standard-library-first Root CI gate

**Files:**
- Modify: `.github/workflows/root-safety.yml`
- Modify: `tests/test_root_safety_workflow.py`
- Modify only if proven necessary: `tests/test_trading_config_safety.py`

**Interfaces:**

```python
def named_workflow_step(workflow: str, step_name: str) -> str:
    """Return exactly one six-space-indented GitHub Actions step block."""
```

- [ ] **Step 1: Replace PyYAML use in tests and add mutation-resistant RED tests**

The helper finds exactly one `      - name: <step>` marker and extracts until the next peer step. It raises on zero/duplicates. Add tests proving correct text in comments or unrelated steps cannot satisfy action/version/command assertions.

- [ ] **Step 2: Add ordering and isolated-interpreter RED tests**

```text
test_root_unit_gate_precedes_bootstrap_and_all_dependency_installs
test_workflow_test_module_imports_with_standard_library_only
```

The child runs `python -S -m unittest tests.test_root_safety_workflow -v` with `ROOT_STDLIB_CHILD=1` to prevent recursion.

- [ ] **Step 3: Run RED**

```powershell
python -m unittest tests.test_root_safety_workflow.RootSafetyWorkflowTests.test_root_unit_gate_precedes_bootstrap_and_all_dependency_installs tests.test_root_safety_workflow.RootSafetyWorkflowTests.test_workflow_test_module_imports_with_standard_library_only -v
```

Expected: ordering failure and/or `ModuleNotFoundError: yaml`.

- [ ] **Step 4: Reorder workflow gates**

After checkout/tool setup run `python -S` root unit tests, then config-only/bootstrap/runtime integration, then backend venv, backend regressions, frontend, committed image/probes/startup, state recovery/durability, and Gitleaks. If a root test is environment-dependent, place only that selector in a separately named standard-library runtime-integration step; never move backend install before the root unit gate.

- [ ] **Step 5: Run GREEN**

```powershell
python -S -m unittest discover -s tests -p "test_*.py" -v
python -S -m unittest tests.test_root_safety_workflow -v
git diff --check
```

- [ ] **Step 6: Commit Task 8**

```powershell
git add .github/workflows/root-safety.yml tests/test_root_safety_workflow.py
git diff --quiet -- tests/test_trading_config_safety.py
if ($LASTEXITCODE -ne 0) { git add tests/test_trading_config_safety.py }
git diff --cached --check
git commit -m "ci: restore the standard-library root safety gate"
```

---

### Task 9: Make disappeared frontend targets visibly fail closed

**Files:**
- Modify: `frequi/src/stores/ftbotwrapper.ts`
- Modify: `frequi/src/components/ftbot/TradeList.vue`
- Test: `frequi/tests/unit/ftbotwrapperTradeRouting.spec.ts`
- Test: `frequi/tests/component/TradeListTradeActions.spec.ts`
- Modify root gitlink: `frequi`

**Interfaces:**

```typescript
function getBotOrThrow(botId: string): BotSubStore;

function isUnknownBotTarget(error: unknown): boolean {
  return error instanceof Error && error.message.startsWith('Unknown bot target:');
}
```

- [ ] **Step 1: Add store RED tests for delete/cancel/reload**

Each explicit missing Bot ID rejects with `Unknown bot target: bot-b`; no Bot A/B API mock is called.

- [ ] **Step 2: Run store RED**

```powershell
Set-Location frequi
pnpm exec vitest run tests/unit/ftbotwrapperTradeRouting.spec.ts
```

Expected: the three current methods resolve `undefined`.

- [ ] **Step 3: Replace optional lookups with `getBotOrThrow`**

```typescript
async function deleteTradeMulti({ botId, tradeid }: MultiDeletePayload) {
  return getBotOrThrow(botId).deleteTrade(tradeid);
}

async function cancelOpenOrderMulti({ botId, tradeid }: MultiCancelOpenOrderPayload) {
  return getBotOrThrow(botId).cancelOpenOrder(tradeid);
}

async function reloadTradeMulti({ botId, tradeid }: MultiReloadTradePayload) {
  return getBotOrThrow(botId).reloadTrade(tradeid);
}
```

- [ ] **Step 4: Add component RED tests for confirmation races**

Open delete/cancel confirmation for Bot B, remove Bot B before resolving, resolve `true`, assert no API call and exactly one localized error alert. For reload, remove target immediately before dispatch and assert the same. Do not cover `BotControls.reloadConfig()`.

- [ ] **Step 5: Await and classify only missing-target errors in `TradeList.vue`**

Use `showAlert(t('trade.targetBotUnavailable'), 'error')` only for `isUnknownBotTarget`; preserve existing API/network error ownership and avoid duplicate alerts.

- [ ] **Step 6: Run frontend GREEN**

```powershell
pnpm exec vitest run tests/unit/ftbotwrapperTradeRouting.spec.ts tests/component/TradeListTradeActions.spec.ts
pnpm typecheck
pnpm exec eslint --quiet src/stores/ftbotwrapper.ts src/components/ftbot/TradeList.vue tests/unit/ftbotwrapperTradeRouting.spec.ts tests/component/TradeListTradeActions.spec.ts
```

- [ ] **Step 7: Commit frontend and root gitlink separately**

```powershell
git add src/stores/ftbotwrapper.ts src/components/ftbot/TradeList.vue tests/unit/ftbotwrapperTradeRouting.spec.ts tests/component/TradeListTradeActions.spec.ts
git diff --cached --check
git commit -m "fix(ui): report disappeared trade action targets"
Set-Location ..
git add frequi
git diff --cached --submodule=short
git commit -m "chore: advance frontend target safety"
```

---

### Task 10: Integrate, publish, and prove final merge readiness

**Files:**
- Create ignored evidence: `.superpowers/sdd/p0-closure-integration-report.md`
- Modify only if verified drift exists: `README.docker.md`, `docs/operations/runtime-secrets.md`, `docs/operations/sqlite-backup-and-restore.md`
- Do not modify production code in this task.

**Interfaces:**
- Consumes all reviewed Tasks 1-9 commits.
- Produces final local/CI/remote evidence for the exact final SHA.

- [ ] **Step 1: Verify exact clean repository state**

```powershell
git status --short
git submodule status
git -C freqtrade status --short
git -C frequi status --short
git diff --check
git log --oneline --decorate -20
```

- [ ] **Step 2: Run gates in final workflow order**

```powershell
python -S -m unittest discover -s tests -p "test_*.py" -v
python tools/runtime_contract.py --check-configs-only
python tools/bootstrap_runtime.py init
python tools/bootstrap_runtime.py sanitize-api-configs
python tools/bootstrap_runtime.py verify
python tools/runtime_contract.py
```

Then run backend targeted/Ruff, frontend focused/typecheck/ESLint, committed-context/provenance build, privilege/mount/secret probes, formal startup, state-lane/durability, and Gitleaks exactly as the workflow specifies.

- [ ] **Step 3: Push backend/frontend/root reviewed commits in dependency order**

Verify remote containment before root push. Do not merge any main branch.

- [ ] **Step 4: Run a final no-local recursive remote clone**

Clone the final root branch from HTTPS into a verified system temp directory with recursive submodules, assert exact root/backend/frontend/strategies SHAs and clean status, then safely delete only that verified temp path.

- [ ] **Step 5: Require a complete Root Safety run for the final SHA**

Record run URL/ID, exact SHA, every step result, test counts, Docker provenance, formal startup, state/durability, and Gitleaks. An older green SHA is invalid evidence.

- [ ] **Step 6: Run online dry-run acceptance only with explicit authorization**

If authorization is absent, record `NOT EXECUTED — authorization required`; do not start endpoints or infer success. If authorized, validate Spot 8081, Futures 8082, Research 8083 and the approved dry-run UI/routing matrix without live orders, exchange mutations, secret output, or destructive recovery.

- [ ] **Step 7: Dispatch final whole-branch independent review**

Review the full pre-closure merge-base-to-HEAD package and all evidence. Any Critical/Important finding returns to its owning task with RED-first fix and re-review.

- [ ] **Step 8: Convert Draft to Ready only when all 15 spec gates pass**

Do not merge. Draft-to-Ready and merge are separate external actions; merge requires a new explicit user instruction.

---

## Final verification checklist

- [ ] Six verified Important findings have RED/GREEN evidence.
- [ ] Frontend disappeared-target no-op is fixed and visible.
- [ ] Root `python -S` gate precedes backend install.
- [ ] Backend and frontend gates pass.
- [ ] Formal dynamic-UID startup passes without live trading.
- [ ] Committed-tree context and complete image labels are verified.
- [ ] Launch uses inspected image ID and force-recreate semantics.
- [ ] Spot/Futures cross-restore fails before writes.
- [ ] POSIX durability barriers and Windows weaker contract pass.
- [ ] Gitleaks scans all committed trees and mutation canary passes.
- [ ] Final remote recursive clone is clean.
- [ ] Final Root Safety is green for the exact final SHA.
- [ ] Online dry-run acceptance is either authorized/evidenced or explicitly unexecuted; Draft cannot become Ready while required acceptance is missing.
- [ ] Final independent review has no Critical/Important findings.
- [ ] User-owned work remains untouched.
