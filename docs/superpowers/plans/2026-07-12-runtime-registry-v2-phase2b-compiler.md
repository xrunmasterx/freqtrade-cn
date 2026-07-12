
# Phase 2B Trusted Template and RuntimeSpec Compiler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish committed closed AdapterTemplate revisions and compile typed owner/catalog/artifact references into deterministic immutable RuntimeSpecs with managed state and secret identities, without Docker mutation.

**Architecture:** Keep template/spec validation pure in the backend platform module and keep Git/filesystem materialization in root trusted tools. Database rows reference committed closed policy IDs; they can never introduce arbitrary images, commands, mounts, paths, ports, networks, privileges, secrets, or Compose fragments.

**Tech Stack:** Python, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, Git plumbing, pathlib, pytest, Ruff, standard-library unittest.

## Global Constraints

- Follow `docs/superpowers/plans/2026-07-12-runtime-registry-v2-master.md`.
- This phase runs no Docker lifecycle command.
- Template publication reads committed blobs from a clean tracked checkout.
- `paper_probe` is fixed to Digital Assets + Spot + Bitget + paper + `SampleStrategy` + exact boolean `dry_run=true`.
- State paths are platform-derived under `ft_userdata/runtime/instances/<instance_id>`; callers never provide a path.
- Phase 2 secret provider is exactly `local-file-v1`; PostgreSQL stores identity/version metadata only.
- Compilation output is canonical JSON with a stable SHA-256 digest.

---

## File Structure

### Backend submodule

- Create `freqtrade/platform/template_domain.py`: closed template and policy references.
- Create `freqtrade/platform/runtime_spec.py`: immutable RuntimeSpec contracts/canonicalization.
- Create `freqtrade/platform/template_models.py`: template/spec/state/secret tables.
- Create `freqtrade/platform/template_repository.py`: immutable publication and lookup.
- Create `freqtrade/platform/runtime_compiler.py`: pure validation and compilation.
- Create Alembic revision `platform_migrations/versions/20260712_0002_templates_specs.py`.
- Create tests under `tests/platform/`.

### Root repository

- Create committed JSON files under `ops/adapter-templates/`.
- Create committed JSON policy registries under `ops/runtime-policies/`.
- Create `tools/runtime_templates.py`: committed-blob publication inputs.
- Create `tools/runtime_secrets.py`: `local-file-v1` exact material handles.
- Create `tools/runtime_state.py`: managed allocation provisioning.
- Create `tools/runtime_registry_cli.py`: typed publish/register/compile commands.
- Create root standard-library tests for every filesystem/Git boundary.

---

### Task 1: Template, spec, allocation, and secret schema

**Files:**
- Create: `freqtrade/freqtrade/platform/template_domain.py`
- Create: `freqtrade/freqtrade/platform/runtime_spec.py`
- Create: `freqtrade/freqtrade/platform/template_models.py`
- Create: `freqtrade/platform_migrations/versions/20260712_0002_templates_specs.py`
- Modify: `freqtrade/freqtrade/platform/__init__.py`
- Test: `freqtrade/tests/platform/test_template_domain.py`
- Test: `freqtrade/tests/platform/test_template_migrations.py`

**Interfaces:**
- Produces `AdapterTemplate`, `TemplateStatus`, `StateAllocationStatus`, `SecretReference`, `RuntimeSpecRevision`.
- Adds tables `adapter_template_revisions`, `runtime_spec_revisions`, `state_allocations`, `secret_references`, `secret_version_metadata`.
- Immutable revision IDs reject conflicting payload digests.

- [ ] **Step 1: Write RED domain and migration tests**

```python
def test_adapter_template_rejects_raw_container_power() -> None:
    with pytest.raises(ValidationError):
        AdapterTemplate(
            template_id="bad",
            semantic_version="1.0.0",
            allowed_instance_kinds=("bot",),
            allowed_owner_kinds=("paper_probe",),
            allowed_environments=("paper",),
            image_policy_id="freqtrade-reviewed-image-v1",
            command_policy_id="freqtrade-paper-v1",
            mount_policy_ids=("config-ro-v1",),
            network_policy_id="isolated-market-data-v1",
            health_profile_id="freqtrade-ping-v1",
            resource_profile_id="small-v1",
            secret_classes=("api_auth",),
            state_layout_id="freqtrade-state-v1",
            image="malicious:latest",
        )


def test_runtime_spec_canonical_digest_is_order_independent() -> None:
    left = RuntimeSpecRevision.from_payload({"b": 2, "a": 1})
    right = RuntimeSpecRevision.from_payload({"a": 1, "b": 2})
    assert left.payload_digest == right.payload_digest
    assert left.canonical_payload == '{"a":1,"b":2}'
```

Migration test upgrades `0001 -> head` and asserts all five new tables plus restrict foreign keys and unique digest/version constraints.

- [ ] **Step 2: Run RED**

```powershell
cd freqtrade
python -m pytest tests/platform/test_template_domain.py tests/platform/test_template_migrations.py -q -p no:cacheprovider
```

Expected: missing modules/migration.

- [ ] **Step 3: Implement closed models**

`AdapterTemplate` contains only:

```python
class AdapterTemplate(FrozenPlatformModel):
    template_id: Identifier
    semantic_version: str
    allowed_instance_kinds: tuple[str, ...]
    allowed_owner_kinds: tuple[RuntimeOwnerKind, ...]
    allowed_environments: tuple[Literal["paper", "live"], ...]
    image_policy_id: Identifier
    command_policy_id: Identifier
    mount_policy_ids: tuple[Identifier, ...]
    network_policy_id: Identifier
    health_profile_id: Identifier
    resource_profile_id: Identifier
    secret_classes: tuple[Identifier, ...]
    state_layout_id: Identifier
```

Use `extra="forbid"` on every external model. `RuntimeSpecRevision.from_payload()` canonicalizes with `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` and hashes UTF-8 bytes with SHA-256.

`SecretReference` contains reference/provider/class/logical-name/owner-scope/status only; no value/path/hash field. `StateAllocation` contains platform-derived relative identity only; no caller path field.

- [ ] **Step 4: Implement explicit migration and run GREEN**

```powershell
python -m pytest tests/platform/test_template_domain.py tests/platform/test_template_migrations.py -q -p no:cacheprovider
alembic -c alembic-platform.ini check
ruff check freqtrade/platform/template_domain.py freqtrade/platform/runtime_spec.py freqtrade/platform/template_models.py platform_migrations/versions/20260712_0002_templates_specs.py tests/platform/test_template_domain.py tests/platform/test_template_migrations.py
```

Expected: tests and Alembic/Ruff checks pass.

- [ ] **Step 5: Commit backend task**

```powershell
git add freqtrade/platform/template_domain.py freqtrade/platform/runtime_spec.py freqtrade/platform/template_models.py freqtrade/platform/__init__.py platform_migrations/versions/20260712_0002_templates_specs.py tests/platform/test_template_domain.py tests/platform/test_template_migrations.py
git commit -m "feat(platform): add trusted runtime specification schema"
```

---

### Task 2: Committed closed policy and AdapterTemplate artifacts

**Files:**
- Create: `ops/adapter-templates/freqtrade-spot-migration-v1.json`
- Create: `ops/adapter-templates/freqtrade-futures-migration-v1.json`
- Create: `ops/adapter-templates/research-worker-migration-v1.json`
- Create: `ops/adapter-templates/freqtrade-paper-probe-v1.json`
- Create: `ops/runtime-policies/image-policies.json`
- Create: `ops/runtime-policies/command-policies.json`
- Create: `ops/runtime-policies/mount-policies.json`
- Create: `ops/runtime-policies/network-policies.json`
- Create: `ops/runtime-policies/health-profiles.json`
- Create: `ops/runtime-policies/resource-profiles.json`
- Create: `ops/runtime-policies/state-layouts.json`
- Create: `tools/runtime_templates.py`
- Test: `tests/test_runtime_templates.py`

**Interfaces:**
- Produces `read_committed_template(root, template_id, commit) -> CommittedTemplate`.
- Produces `load_closed_policy_registry(root, commit) -> ClosedPolicyRegistry`.
- No worktree-file trust after commit identity is captured.

- [ ] **Step 1: Write RED Git provenance tests**

```python
class RuntimeTemplateTests(unittest.TestCase):
    def test_untracked_or_dirty_template_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "template checkout must be clean"):
            publish_fixture_with_dirty_template()

    def test_committed_blob_wins_over_replaced_worktree_file(self) -> None:
        committed = read_committed_template(self.root, "freqtrade-paper-probe-v1", self.commit)
        replace_worktree_template_with_arbitrary_image(self.root)
        self.assertEqual(committed.payload["image_policy_id"], "freqtrade-reviewed-image-v1")
        self.assertNotIn("image", committed.payload)

    def test_unknown_policy_reference_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown command policy"):
            validate_template({**valid_template(), "command_policy_id": "unknown"})
```

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_runtime_templates -v
```

Expected: missing tool/artifacts.

- [ ] **Step 3: Add exact JSON artifacts**

Every JSON file has `schema_version: 1` and no unknown keys. The paper template contains:

```json
{
  "schema_version": 1,
  "template_id": "freqtrade-paper-probe-v1",
  "semantic_version": "1.0.0",
  "allowed_instance_kinds": ["freqtrade"],
  "allowed_owner_kinds": ["paper_probe"],
  "allowed_environments": ["paper"],
  "image_policy_id": "freqtrade-reviewed-image-v1",
  "command_policy_id": "freqtrade-spot-paper-v1",
  "mount_policy_ids": ["runtime-config-ro-v1", "strategy-ro-v1", "managed-state-rw-v1", "api-secrets-ro-v1"],
  "network_policy_id": "isolated-public-market-data-v1",
  "health_profile_id": "freqtrade-ping-v1",
  "resource_profile_id": "freqtrade-small-v1",
  "secret_classes": ["api_password", "jwt_secret", "ws_token"],
  "state_layout_id": "freqtrade-state-v1"
}
```

Closed policies expand only reviewed constants. No JSON accepts an image reference, shell command, host path, port, network name, device, capability, privilege, or Compose fragment.

- [ ] **Step 4: Implement committed-blob reader**

Use only non-interactive Git commands with argument arrays:

```python
def git_blob(root: Path, commit: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return completed.stdout
```

Before reading, require exact tracked path, clean relevant index/worktree, commit ancestry policy, canonical JSON, SHA-256 digest, closed schema, and every referenced policy ID present in the same committed revision.

- [ ] **Step 5: Run GREEN and commit root artifacts**

```powershell
python -S -m unittest tests.test_runtime_templates -v
python -m json.tool ops/adapter-templates/freqtrade-paper-probe-v1.json > $null
git add ops/adapter-templates ops/runtime-policies tools/runtime_templates.py tests/test_runtime_templates.py
git commit -m "feat(runtime): add committed adapter policy registry"
```

Expected: provenance/mutation tests pass and root commit contains only root artifacts/tool/tests.

---

### Task 3: Immutable template publication repository

**Files:**
- Create: `freqtrade/freqtrade/platform/template_repository.py`
- Test: `freqtrade/tests/platform/test_template_repository.py`
- Test: `freqtrade/tests/platform/test_template_repository_postgres.py`

**Interfaces:**
- Produces `publish_template(committed_template, actor, published_at) -> AdapterTemplateRevisionView`.
- Identical template/version/digest is idempotent; same template/version with another digest is rejected.
- Status transitions are `active -> deprecated` or `active/deprecated -> revoked`; revisions are never overwritten.

- [ ] **Step 1: Write RED repository tests**

```python
def test_publish_is_idempotent_but_digest_conflict_fails(repository) -> None:
    first = repository.publish(committed_template(digest="a" * 64))
    second = repository.publish(committed_template(digest="a" * 64))
    assert second.revision_id == first.revision_id

    with pytest.raises(TemplateConflict, match="template_version_digest_conflict"):
        repository.publish(committed_template(digest="b" * 64))
```

- [ ] **Step 2: Run RED**

```powershell
cd freqtrade
python -m pytest tests/platform/test_template_repository.py tests/platform/test_template_repository_postgres.py -q -p no:cacheprovider
```

Expected: missing repository.

- [ ] **Step 3: Implement transaction and status rules**

Repository publication validates canonical payload/digest again, inserts immutable revision and audit in one transaction, translates only the expected uniqueness race into `TemplateConflict`, and rethrows unrelated `IntegrityError`. Revocation blocks future specs/attempts but never kills a running attempt.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest tests/platform/test_template_repository.py tests/platform/test_template_repository_postgres.py -q -p no:cacheprovider
ruff check freqtrade/platform/template_repository.py tests/platform/test_template_repository.py tests/platform/test_template_repository_postgres.py
git add freqtrade/platform/template_repository.py tests/platform/test_template_repository.py tests/platform/test_template_repository_postgres.py
git commit -m "feat(platform): publish immutable adapter templates"
```

---

### Task 4: local-file-v1 SecretProvider

**Files:**
- Create: `tools/runtime_secrets.py`
- Test: `tests/test_runtime_secrets.py`
- Modify: `docs/operations/runtime-secrets.md`

**Interfaces:**
- Produces `LocalFileSecretProvider.resolve(reference_id, version_id) -> SecretMaterialHandle`.
- `SecretMaterialHandle` exposes an already-open descriptor or fixed mount source without exposing content through repr/log/JSON.
- Derives all paths from validated identifiers and a fixed root.

- [ ] **Step 1: Write RED path/ACL/content tests**

```python
class RuntimeSecretProviderTests(unittest.TestCase):
    def test_rejects_symlink_escape_and_user_path(self) -> None:
        with self.assertRaisesRegex(SecretMaterialError, "secret identity is invalid"):
            self.provider.resolve("../outside", "v1")
        with self.assertRaisesRegex(SecretMaterialError, "secret path is not a regular file"):
            self.provider.resolve("api-password", "symlink-version")

    def test_handle_repr_and_error_never_include_value(self) -> None:
        handle = self.provider.resolve("api-password", "v1")
        self.assertNotIn(self.secret_value, repr(handle))
```

Add Windows reparse-point and POSIX owner/mode cases using existing bootstrap permission helpers.

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_runtime_secrets -v
```

Expected: missing provider.

- [ ] **Step 3: Implement provider**

Identifiers match `^[a-z0-9][a-z0-9_-]{0,127}$`. The fixed layout is:

```text
<secret-root>/<reference-id>/<version-id>/value
```

Validate containment, no symlink/reparse point, regular file, approved owner/mode/ACL, one line, non-empty, NUL-free, class length, and distinct required values. Exceptions contain stable codes only. Never implement secret enumeration.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -S -m unittest tests.test_runtime_secrets -v
git add tools/runtime_secrets.py tests/test_runtime_secrets.py docs/operations/runtime-secrets.md
git commit -m "feat(runtime): resolve versioned local secrets"
```

---

### Task 5: Managed StateAllocation provisioning

**Files:**
- Create: `tools/runtime_state.py`
- Test: `tests/test_runtime_state.py`
- Modify: `tools/bootstrap_runtime.py`

**Interfaces:**
- Produces `ManagedStateProvider.provision(instance_id, allocation_id, layout_id) -> ProvisionedState`.
- Fixed root is `ft_userdata/runtime/instances`.
- No caller path, reuse, delete, or overwrite operation exists.

- [ ] **Step 1: Write RED ownership and fault-injection tests**

```python
class RuntimeStateTests(unittest.TestCase):
    def test_allocation_path_is_platform_derived(self) -> None:
        state = self.provider.provision("runtime-1", "allocation-1", "freqtrade-state-v1")
        self.assertEqual(
            state.relative_path,
            "ft_userdata/runtime/instances/runtime-1",
        )

    def test_partial_failure_quarantines_only_created_allocation(self) -> None:
        with self.assertRaisesRegex(StateProvisionError, "state_provision_failed"):
            self.provider.provision_with_fault("runtime-2", "allocation-2", fault="after-layout")
        self.assertTrue(self.quarantine_for("allocation-2").is_dir())
        self.assertTrue(self.unrelated_path.is_dir())
```

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_runtime_state -v
```

Expected: missing provider.

- [ ] **Step 3: Implement fixed layouts and durability**

`freqtrade-state-v1` creates `home`, `logs`, `data`, and an empty allocation identity file using atomic write, owner/ACL hardening, file and directory sync barriers, and final containment revalidation. Provisioning requires a DB reservation object and returns proof; it never mutates DB itself.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -S -m unittest tests.test_runtime_state tests.test_bootstrap_runtime -v
git add tools/runtime_state.py tools/bootstrap_runtime.py tests/test_runtime_state.py tests/test_bootstrap_runtime.py
git commit -m "feat(runtime): provision managed instance state"
```

---

### Task 6: Deterministic RuntimeSpec compiler

**Files:**
- Create: `freqtrade/freqtrade/platform/runtime_compiler.py`
- Modify: `freqtrade/freqtrade/platform/runtime_spec.py`
- Test: `freqtrade/tests/platform/test_runtime_compiler.py`

**Interfaces:**
- Produces `RuntimeSpecCompiler.compile(CompileRuntimeRequest) -> RuntimeSpecRevision`.
- Consumes typed owner, catalog revision, active template revision, environment, reserved allocation, secret reference IDs, committed config/strategy artifacts, and component commits.
- Performs no filesystem, secret, or Docker action.

- [ ] **Step 1: Write RED compiler/mutation tests**

```python
def test_paper_probe_compiles_only_bitget_spot_paper(compiler) -> None:
    spec = compiler.compile(valid_paper_probe_request())
    assert spec.canonical_payload["market_scope"] == {
        "market_id": "digital_asset",
        "product_ids": ["spot"],
        "venue_ids": ["bitget"],
        "instrument_keys": [],
    }
    assert spec.canonical_payload["environment"] == "paper"

@pytest.mark.parametrize(
    "mutation",
    [
        {"environment": "live"},
        {"market_scope.product_ids": ["spot", "perpetual"]},
        {"raw_image": "latest"},
        {"host_port": 9000},
        {"host_path": "/tmp"},
    ],
)
def test_untrusted_compile_input_fails_before_side_effect(compiler, mutation, side_effect_spy) -> None:
    with pytest.raises(RuntimeCompileError):
        compiler.compile(mutated_request(mutation))
    side_effect_spy.assert_not_called()
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/platform/test_runtime_compiler.py -q -p no:cacheprovider
```

Expected: missing compiler.

- [ ] **Step 3: Implement ordered validation**

Validation order is owner -> catalog/capability -> environment -> template status/compatibility -> state reservation -> secret classes -> committed config/strategy identities -> closed policies -> component provenance -> canonicalization. Reject unknown/extra fields at request parsing.

`CompileRuntimeRequest` has no image, command, mount, path, port, network, privilege, device, project, Compose, environment passthrough, or raw argument field.

- [ ] **Step 4: Run GREEN, golden digest test, and commit**

```powershell
python -m pytest tests/platform/test_runtime_compiler.py -q -p no:cacheprovider
ruff check freqtrade/platform/runtime_compiler.py freqtrade/platform/runtime_spec.py tests/platform/test_runtime_compiler.py
git add freqtrade/platform/runtime_compiler.py freqtrade/platform/runtime_spec.py tests/platform/test_runtime_compiler.py
git commit -m "feat(platform): compile immutable runtime specifications"
```

Expected: golden canonical payload/digest is stable and all mutation inputs fail before side effects.

---

### Task 7: Trusted Operator CLI publication/registration/compile slice

**Files:**
- Create: `tools/runtime_registry_cli.py`
- Test: `tests/test_runtime_registry_cli.py`
- Modify: `.github/workflows/root-safety.yml`
- Modify: `tests/test_root_safety_workflow.py`
- Update: root `freqtrade` gitlink after backend review.

**Interfaces:**
- Commands: `runtime-template validate`, `runtime-template publish`, `runtime-registry register-paper-probe`, `runtime-registry compile`, `runtime-registry status`.
- No start/stop/retry/retire execution is enabled until Phase 2C.
- Rejects unknown flags and raw Docker/Compose inputs.

- [ ] **Step 1: Write RED CLI tests**

```python
class RuntimeRegistryCliTests(unittest.TestCase):
    def test_compile_rejects_raw_container_flags(self) -> None:
        for flag in ("--image", "--command", "--mount", "--port", "--network", "--compose"):
            with self.subTest(flag=flag):
                result = run_cli("runtime-registry", "compile", flag, "value")
                self.assertEqual(result.returncode, 2)

    def test_paper_probe_compile_is_deterministic(self) -> None:
        first = run_cli("runtime-registry", "compile", "--instance-id", "phase2-paper-probe")
        second = run_cli("runtime-registry", "compile", "--instance-id", "phase2-paper-probe")
        self.assertEqual(first.stdout, second.stdout)
```

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_runtime_registry_cli -v
```

Expected: missing CLI.

- [ ] **Step 3: Implement typed CLI**

Use argparse subparsers with explicit flags only. The root CLI imports backend application services after dependency installation, reads committed templates through `runtime_templates.py`, and prints identifiers/status/digests only. Secret values/paths and host state paths never enter stdout/stderr.

- [ ] **Step 4: Add Root Safety selectors and verify**

```powershell
python -S -m unittest tests.test_runtime_registry_cli tests.test_runtime_templates tests.test_runtime_secrets tests.test_runtime_state tests.test_root_safety_workflow -v
Push-Location freqtrade
python -m pytest tests/platform/test_template_domain.py tests/platform/test_template_migrations.py tests/platform/test_template_repository.py tests/platform/test_runtime_compiler.py -q -p no:cacheprovider
ruff check freqtrade/platform tests/platform
Pop-Location
```

Expected: all Phase 2B offline tests pass and no Docker command executes.

- [ ] **Step 5: Commit root integration**

```powershell
git add tools/runtime_registry_cli.py tests/test_runtime_registry_cli.py .github/workflows/root-safety.yml tests/test_root_safety_workflow.py freqtrade
git commit -m "ci: gate phase2b runtime compiler"
```

Expected: reviewed backend gitlink plus root CLI/CI only; clean worktree.

