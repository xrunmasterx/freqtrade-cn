
# Phase 2E Compatibility Writes, Controlled Cutover, and Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve approved existing Bot/Research application actions through governed Gateway routes, import and cut over Spot/Futures/Research into managed RuntimeInstances with copied state, remove active 8081/8082/8083 listeners, and prove rollback/emergency/backup safety.

**Architecture:** Treat the current exact-three manifest and Compose definitions as immutable migration input, not permanent services. Cut over one instance at a time through backup -> exact stop -> absence proof -> new allocation -> verified copy -> managed launch -> 8090 acceptance; retain original state read-only for rollback. Compatibility writes use a closed route policy, instance-bound internal tokens, capability checks, durable request/audit identity, and no ambiguous retry.

**Tech Stack:** Python, PostgreSQL/Alembic, Docker Compose CLI, SQLite online backup, FastAPI/httpx, Vue/Pinia/Axios, unittest, pytest, Vitest, Root Safety.

## Global Constraints

- Follow the master plan and completed Phase 2A-2D interfaces.
- No destructive recovery, move, delete, overwrite, or simultaneous old/new state writer.
- Import itself performs no Docker/filesystem mutation.
- Cutover requires explicit operator steps and expected identities.
- Old source state/config/definition remains inactive rollback evidence; it is not an active service.
- Runtime lifecycle remains CLI/Supervisor-only.
- Gateway application writes are a compatibility bridge and never a Docker lifecycle path.
- Current authorized acceptance is paper/dry-run only; no real order or exchange write.
- Final accepted state has no active listener on 8081, 8082, or 8083.

---

## File Structure

### Backend submodule

- Create `freqtrade/platform/runtime_migration.py` and ORM migration record.
- Create Alembic revision `20260712_0003_migration_access_writes.py`.
- Create committed `runtime-access-write-v1.json`.
- Extend Runtime Access policy/gateway/request repository for application writes.
- Add API and policy tests.
- Modify Freqtrade internal auth/route metadata for approved write groups.

### Frontend submodule

- Create a runtime-compatible Axios client using platform auth and instance ID.
- Change Bot substore/API creation to route through 8090 after cutover.
- Preserve current UI actions and error behavior; remove fixed endpoint assumptions.
- Add action-routing and cross-instance tests.

### Root repository

- Move current exact-three manifest/Compose definition to `ops/migration/` as immutable import/rollback evidence.
- Create `tools/runtime_migration.py` and generalized instance backup/restore adapters.
- Replace fixed service emergency/start tooling with Registry/offline-identity tooling.
- Remove active old services/ports from final Compose.
- Add cutover receipts, runbook, Root Safety, fresh recursive checkout, and authorized online acceptance.

---

### Task 1: Existing-process migration records and stopped import

**Files:**
- Create: `freqtrade/freqtrade/platform/runtime_migration.py`
- Modify: `freqtrade/freqtrade/platform/runtime_models.py`
- Create: `freqtrade/platform_migrations/versions/20260712_0003_migration_access_writes.py`
- Create: `tools/runtime_migration.py`
- Test: `freqtrade/tests/platform/test_runtime_migration.py`
- Test: `tests/test_runtime_migration.py`

**Interfaces:**
- `import-existing` maps Spot/Futures to `migration_bot` and Research to `workspace_worker`.
- Produces stopped managed instances/spec references and immutable `runtime_migration_records`.
- Records old port as evidence only; new endpoint policy has no host port.
- Import is idempotent for exact identity and rejects conflicts.

- [ ] **Step 1: Write RED import tests**

```python
def test_import_classifies_existing_processes_without_mutation(importer, mutation_spy) -> None:
    result = importer.import_manifest(existing_manifest(), verified_compose())
    assert result["freqtrade"].owner_kind == "migration_bot"
    assert result["freqtrade-futures"].owner_kind == "migration_bot"
    assert result["freqtrade-research"].owner_kind == "workspace_worker"
    assert all(item.desired_state == "stopped" for item in result.values())
    mutation_spy.assert_not_called()

def test_import_records_old_port_only_as_evidence(importer) -> None:
    record = importer.import_manifest(existing_manifest(), verified_compose())["freqtrade"]
    assert record.source_port == 8081
    assert record.runtime_endpoint.exposure_policy == "internal_only"
```

Root tests mutate role/config/strategy/state/image/port and expect exact stable rejection before Docker/filesystem calls.

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_runtime_migration -v
Push-Location freqtrade
python -m pytest tests/platform/test_runtime_migration.py -q -p no:cacheprovider
Pop-Location
```

Expected: missing import modules/migration.

- [ ] **Step 3: Implement migration record and importer**

Migration record fields: migration ID, source manifest digest, source service/role/port/config/strategy/state/image/component commits, owner ref, target instance/spec/allocation IDs, status, receipt digest, timestamps. Closed statuses: `discovered`, `imported_stopped`, `state_copied`, `managed`, `accepted`, `rollback_retained`, `failed`.

Root importer reads committed migration manifest + verified Compose render + exact image/component identities, builds typed requests, and calls backend service. It exposes no auto-cutover flag.

- [ ] **Step 4: Run GREEN and commit backend/root tasks separately**

```powershell
Push-Location freqtrade
python -m pytest tests/platform/test_runtime_migration.py tests/platform/test_template_migrations.py -q -p no:cacheprovider
ruff check freqtrade/platform/runtime_migration.py freqtrade/platform/runtime_models.py tests/platform/test_runtime_migration.py
git add freqtrade/platform/runtime_migration.py freqtrade/platform/runtime_models.py platform_migrations/versions/20260712_0003_migration_access_writes.py tests/platform/test_runtime_migration.py
git commit -m "feat(platform): record existing runtime migrations"
Pop-Location

python -S -m unittest tests.test_runtime_migration -v
git add tools/runtime_migration.py tests/test_runtime_migration.py
git commit -m "feat(runtime): import existing services as stopped instances"
```

---

### Task 2: Governed compatibility application-write policy

**Files:**
- Create: `freqtrade/freqtrade/platform_control/policies/runtime-access-write-v1.json`
- Modify: `freqtrade/freqtrade/platform/runtime_access_policy.py`
- Modify: `freqtrade/freqtrade/platform/runtime_access_gateway.py`
- Modify: `freqtrade/freqtrade/platform/runtime_repository.py`
- Modify: `freqtrade/freqtrade/platform_control/api_runtime_access.py`
- Test: `freqtrade/tests/platform/test_runtime_access_writes.py`
- Test: `freqtrade/tests/platform_control/test_api_runtime_access_writes.py`

**Interfaces:**
- Approved write route groups include current Bot state/config/manual-trade actions explicitly; Research has no trading write group.
- POST/DELETE is never automatically retried.
- Every request has durable request ID; idempotency key is required where supported.
- Paper cannot call Live-only route; live remains unavailable until a separately accepted lane exists.

- [ ] **Step 1: Write RED authorization/ambiguity tests**

```python
@pytest.mark.asyncio
async def test_research_cannot_call_force_entry(gateway) -> None:
    result = await gateway.write(
        instance_id="research-runtime",
        route_id="force_entry",
        payload=valid_force_entry(),
        idempotency_key="force-entry-1",
    )
    assert result.code == "runtime_route_owner_denied"
    gateway.http.send.assert_not_called()

@pytest.mark.asyncio
async def test_ambiguous_post_is_recorded_and_not_retried(gateway) -> None:
    gateway.http.send.side_effect = ReadTimeout()
    result = await gateway.write(
        instance_id="paper-runtime",
        route_id="stop_entry",
        payload={},
        idempotency_key="stop-entry-1",
    )
    assert result.code == "runtime_write_result_ambiguous"
    assert gateway.http.send.call_count == 1
```

Add cross-instance token, route/method mismatch, body-size, unsupported content type, redirect, stale endpoint, and duplicate idempotency tests.

- [ ] **Step 2: Run RED**

```powershell
cd freqtrade
python -m pytest tests/platform/test_runtime_access_writes.py tests/platform_control/test_api_runtime_access_writes.py -q -p no:cacheprovider
```

Expected: write routes/policy absent.

- [ ] **Step 3: Add explicit policy**

Every entry contains exact external route ID, upstream method/path, owner kinds, environments, capability, request schema ID, response size, timeout, retry mode `never`, and audit class. The compatibility inventory is explicit:

```text
DELETE /locks/{lock_id}
POST   /pairlists
DELETE /background/clear
POST   /download_data
POST   /recursive_analysis
POST   /lookahead_analysis
POST   /start
POST   /stop
POST   /stopbuy
POST   /reload_config
DELETE /trades/{trade_id}
DELETE /trades/{trade_id}/open-order
POST   /trades/{trade_id}/reload
POST   /start_trade
POST   /forcesell
POST   /forcebuy
POST   /blacklist
DELETE /blacklist
POST   /backtest
DELETE /backtest
GET    /backtest/abort
DELETE /backtest/history/{filename}
PATCH  /backtest/history/{filename}
POST   /research/backtest
```

Each route is enabled only for the owner/environment/capability that already supports it. The policy contains no withdrawal, transfer, account administration, arbitrary URL/path, or Runtime lifecycle route. A contract test compares this inventory with the explicit route IDs used by `frequi/src/stores/ftbot.ts` and `frequi/src/stores/research.ts`; any newly introduced mutation fails CI until reviewed and classified.

- [ ] **Step 4: Implement durable write flow**

Within one DB transaction insert `runtime_access_requests` pending record and audit. Forward once with instance-bound token and request ID. On definitive response update terminal code/status; on timeout/disconnect after send, mark `ambiguous` and return stable error without retry. Duplicate idempotency returns stored definitive result metadata or the same ambiguous state; it never replays the upstream write.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest tests/platform/test_runtime_access_writes.py tests/platform_control/test_api_runtime_access_writes.py -q -p no:cacheprovider
ruff check freqtrade/platform/runtime_access_policy.py freqtrade/platform/runtime_access_gateway.py freqtrade/platform/runtime_repository.py freqtrade/platform_control/api_runtime_access.py tests/platform/test_runtime_access_writes.py tests/platform_control/test_api_runtime_access_writes.py
git add freqtrade/platform_control/policies/runtime-access-write-v1.json freqtrade/platform/runtime_access_policy.py freqtrade/platform/runtime_access_gateway.py freqtrade/platform/runtime_repository.py freqtrade/platform_control/api_runtime_access.py tests/platform/test_runtime_access_writes.py tests/platform_control/test_api_runtime_access_writes.py
git commit -m "feat(platform): govern compatibility runtime writes"
```

---

### Task 3: FreqUI Bot application client through Runtime Access

**Files:**
- Create: `frequi/src/composables/runtimeApi.ts`
- Modify: `frequi/src/stores/ftbot.ts`
- Modify: `frequi/src/stores/ftbotwrapper.ts`
- Modify: `frequi/src/composables/api.ts`
- Modify: `frequi/src/types/types.ts`
- Test: `frequi/tests/unit/runtimeApi.spec.ts`
- Test: `frequi/tests/unit/ftbotwrapperTradeRouting.spec.ts`
- Test: relevant Bot action component tests.

**Interfaces:**
- Existing relative v1 Bot calls map through one platform-authenticated runtime client bound to immutable instance ID.
- Client exposes no base URL editing after Registry selection.
- Non-idempotent writes carry generated request ID/idempotency key and disable Axios retry.

- [ ] **Step 1: Write RED routing tests**

```ts
it('routes a bot action through the selected runtime instance', async () => {
  await bot.forceExit({ tradeid: 7, ordertype: 'market', amount: null });
  expect(platformApi.post).toHaveBeenCalledWith(
    '/runtime-access/v1/instances/runtime-a/routes/force_exit',
    expect.any(Object),
    expect.objectContaining({ headers: expect.objectContaining({ 'Idempotency-Key': expect.any(String) }) }),
  );
});

it('cannot retarget an existing runtime client', () => {
  const client = createRuntimeApi(platformApi, 'runtime-a');
  expect(() => client.withInstance('runtime-b')).toThrow('runtime client target is immutable');
});
```

- [ ] **Step 2: Run RED**

```powershell
cd frequi
pnpm exec vitest run tests/unit/runtimeApi.spec.ts tests/unit/ftbotwrapperTradeRouting.spec.ts tests/component/ForceTradeForms.spec.ts tests/component/BotControls.spec.ts
```

Expected: missing runtime client/current direct Bot API calls.

- [ ] **Step 3: Implement typed route mapping**

Create a constant map from existing store operation names to Gateway route IDs. Preserve store method signatures and UI confirmations. Do not build a generic `{path}` proxy client. Platform session handles authentication/refresh; runtime clients are created only from Registry descriptors.

- [ ] **Step 4: Run GREEN, typecheck, lint, and commit**

```powershell
pnpm exec vitest run tests/unit/runtimeApi.spec.ts tests/unit/ftbotwrapperTradeRouting.spec.ts tests/component/ForceTradeForms.spec.ts tests/component/BotControls.spec.ts tests/component/TradeListTradeActions.spec.ts
pnpm typecheck
pnpm lint-ci
git add src/composables/runtimeApi.ts src/composables/api.ts src/stores/ftbot.ts src/stores/ftbotwrapper.ts src/types/types.ts tests/unit/runtimeApi.spec.ts tests/unit/ftbotwrapperTradeRouting.spec.ts tests/component/ForceTradeForms.spec.ts tests/component/BotControls.spec.ts tests/component/TradeListTradeActions.spec.ts
git commit -m "feat(ui): route bot actions through runtime access"
```

---

### Task 4: Generalized instance backup and non-destructive restore

**Files:**
- Modify: `tools/sqlite_state.py`
- Create: `tools/runtime_backup.py`
- Test: `tests/test_runtime_backup.py`
- Test: `tests/test_sqlite_state.py`
- Modify: `docs/operations/sqlite-backup-and-restore.md`

**Interfaces:**
- Resolves instance lane from Registry or verified offline identity; no arbitrary source/output root.
- Bundle identity includes instance/allocation/layout/spec/schema/source filename/provenance.
- Restore always targets a new empty allocation and never overwrites.

- [ ] **Step 1: Write RED identity/overwrite tests**

```python
class RuntimeBackupTests(unittest.TestCase):
    def test_backup_rejects_arbitrary_source(self) -> None:
        result = run_backup("--instance-id", "runtime-a", "--source", "C:\\other\\db.sqlite")
        self.assertEqual(result.returncode, 2)

    def test_restore_requires_new_empty_allocation(self) -> None:
        with self.assertRaisesRegex(StateBundleError, "restore_target_not_empty"):
            restore_instance_bundle(self.bundle, existing_allocation())
```

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_runtime_backup tests.test_sqlite_state -v
```

Expected: missing generalized adapter/unsupported identity.

- [ ] **Step 3: Implement adapter around proven primitives**

Reuse `online_backup`, manifest verification, locks, durability, receipt, quarantine, and structure compare. Replace fixed service lookup with an injected exact instance lane. Emergency mode may verify/create backup only; normal restore requires Registry/Supervisor stopped proof and a new allocation reservation.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -S -m unittest tests.test_runtime_backup tests.test_sqlite_state -v
git add tools/runtime_backup.py tools/sqlite_state.py tests/test_runtime_backup.py tests/test_sqlite_state.py docs/operations/sqlite-backup-and-restore.md
git commit -m "feat(runtime): back up identity-bound instances"
```

---

### Task 5: Verified state copy and one-writer cutover workflow

**Files:**
- Modify: `tools/runtime_migration.py`
- Modify: `tools/runtime_registry_cli.py`
- Test: `tests/test_runtime_cutover.py`
- Create: `docs/operations/runtime-cutover.md`

**Interfaces:**
- Explicit commands: `prepare`, `prove-stopped`, `copy-state`, `launch-managed`, `accept`, `rollback`.
- Each command consumes previous receipt digest and exact expected identities.
- No command both stops old and launches new without an intervening durable receipt.

- [ ] **Step 1: Write RED one-writer/fault tests**

```python
class RuntimeCutoverTests(unittest.TestCase):
    def test_copy_requires_exact_old_container_absence(self) -> None:
        with self.assertRaisesRegex(CutoverError, "source_writer_still_active"):
            self.cutover.copy_state(prepared_receipt(), observed_old_container())

    def test_failed_copy_quarantines_new_allocation_and_preserves_source(self) -> None:
        source_digest = tree_digest(self.source)
        with self.assertRaisesRegex(CutoverError, "state_copy_failed"):
            self.cutover.copy_state_with_fault(prepared_receipt(), fault="mid-copy")
        self.assertEqual(tree_digest(self.source), source_digest)
        self.assertTrue(self.quarantine.exists())
```

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_runtime_cutover -v
```

Expected: cutover commands absent.

- [ ] **Step 3: Implement receipt-driven workflow**

`prepare` creates verified P0 backup and source identity receipt. `prove-stopped` stops only exact old container through existing trusted command and records absence. `copy-state` reserves new allocation, copies approved files without following links, syncs, validates SQLite/research structure/digests, and never mutates source. `launch-managed` submits a start job. `accept` records evidence. `rollback` first stops/proves managed absence, then may restart the exact inactive old definition against untouched source.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -S -m unittest tests.test_runtime_cutover tests.test_runtime_migration tests.test_runtime_backup tests.test_sqlite_state -v
git add tools/runtime_migration.py tools/runtime_registry_cli.py tests/test_runtime_cutover.py docs/operations/runtime-cutover.md
git commit -m "feat(runtime): add receipt-driven compatibility cutover"
```

---

### Task 6: Convert old service definitions into inactive migration evidence

**Files:**
- Create: `ops/migration/current-runtime-import-v1.json`
- Create: `ops/migration/current-runtime-compose-v1.yml`
- Modify: `docker-compose.yml`
- Modify: `ops/runtime-services.json` or remove it after every consumer is migrated in the same commit.
- Modify: `tools/runtime_manifest.py`
- Modify: `tools/compose_runtime.py`
- Modify: `tools/runtime_contract.py`
- Modify: `tools/formal_startup.py`
- Test: current root runtime tests and new `tests/test_final_runtime_topology.py`.

**Interfaces:**
- Final active Compose has platform services only; Bots/Research come from Supervisor snapshots.
- Migration evidence remains committed/read-only but is not addressable by normal start commands.
- 8081/8082/8083 do not appear in final active Compose ports.

- [ ] **Step 1: Write RED final-topology tests**

```python
class FinalRuntimeTopologyTests(unittest.TestCase):
    def test_active_compose_has_no_fixed_bot_or_research_services(self) -> None:
        services = render_compose(root=REPO_ROOT)["services"]
        self.assertNotIn("freqtrade", services)
        self.assertNotIn("freqtrade-futures", services)
        self.assertNotIn("freqtrade-research", services)

    def test_active_compose_has_no_old_ports(self) -> None:
        rendered = json.dumps(render_compose(root=REPO_ROOT), sort_keys=True)
        for port in ("8081", "8082", "8083"):
            self.assertNotIn(port, rendered)
```

Add a test proving migration evidence cannot be passed to the normal start CLI.

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_final_runtime_topology -v
```

Expected: current fixed services/ports still active.

- [ ] **Step 3: Archive evidence and replace fixed consumers**

Copy exact reviewed old manifest/Compose semantics into `ops/migration/` with digest/provenance metadata. Update import/cutover/rollback tools to read it only under explicit migration commands. Replace fixed service backup/emergency/formal-startup selectors with Registry/offline-identity selectors. Then remove old active services/secrets/ports and exact-three normal lifecycle support.

- [ ] **Step 4: Run full root GREEN and commit**

```powershell
python -S -m unittest discover -s tests -p "test_*.py" -v
python tools/compose_runtime.py --profile platform config --format json > $env:TEMP\final-compose.json
python tools/runtime_contract.py --compose-json $env:TEMP\final-compose.json
git add docker-compose.yml ops/migration ops/runtime-services.json tools/runtime_manifest.py tools/compose_runtime.py tools/runtime_contract.py tools/formal_startup.py tests/test_final_runtime_topology.py tests
git commit -m "refactor(runtime): retire fixed bot service topology"
```

Expected: all updated root tests pass and active Compose contains only platform infrastructure/application services.

---

### Task 7: Offline and authorized online cutover acceptance

**Files:**
- Create: `tools/runtime_acceptance.py`
- Test: `tests/test_runtime_acceptance.py`
- Modify: `.github/workflows/root-safety.yml`
- Modify: `tests/test_root_safety_workflow.py`
- Create: `docs/operations/phase2-acceptance.md`
- Update backend/frontend gitlinks.

**Interfaces:**
- Offline acceptance always runs.
- Online acceptance requires explicit `--authorized-paper-online`, exact approved instances, and no exchange-write credentials.
- Produces non-secret signed receipt with component commits, instance/attempt/spec/image/state/network/policy identities and test results.

- [ ] **Step 1: Write RED authorization tests**

```python
class RuntimeAcceptanceTests(unittest.TestCase):
    def test_online_mode_requires_exact_authorization_flag(self) -> None:
        result = run_acceptance("--online")
        self.assertEqual(result.returncode, 2)
        self.assertIn("authorized paper online acceptance is required", result.stderr)

    def test_live_or_write_credentials_are_rejected_before_network(self) -> None:
        with self.assertRaisesRegex(AcceptanceError, "online_acceptance_not_paper_safe"):
            validate_online_acceptance(live_spec_or_write_secret())
        self.assertFalse(self.network.called)
```

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_runtime_acceptance tests.test_root_safety_workflow -v
```

Expected: acceptance/gates absent.

- [ ] **Step 3: Implement offline acceptance**

Prove:
- platform-control 8090 health/auth;
- PostgreSQL internal/no host port;
- managed Spot/Futures/Research identities;
- no listeners 8081/8082/8083;
- base chart works with related Bot stopped;
- all refresh intervals/policy aliases;
- Strategy overlay/Research read through exact Gateway;
- cross-instance/owner/environment/route/method denial;
- write timeout no retry;
- emergency exact stop without DB;
- backup/restore identity and non-destructive rules;
- no Docker/secret-root/state access in platform-control.

- [ ] **Step 4: Implement separately authorized paper-online acceptance**

When explicitly authorized, run Bitget Spot paper probe and approved migrated paper runtimes only. Prove public market reads, no real order, no exchange write, exact boolean dry-run, independent state, bounded health, clean stop, and receipt. Never infer authorization from design approval.

- [ ] **Step 5: Run Phase 2E offline gates and commit**

```powershell
python -S -m unittest discover -s tests -p "test_*.py" -v
Push-Location freqtrade
python -m pytest tests/platform tests/platform_control tests/rpc/test_runtime_access_auth.py -q -p no:cacheprovider
ruff check freqtrade/platform freqtrade/platform_control tests/platform tests/platform_control tests/rpc/test_runtime_access_auth.py
Pop-Location
Push-Location frequi
pnpm exec vitest run tests/unit/runtimeApi.spec.ts tests/unit/ftbotwrapperTradeRouting.spec.ts tests/unit/marketDataStore.spec.ts tests/component/ForceTradeForms.spec.ts tests/component/BotControls.spec.ts tests/component/TradingViewLiveChart.spec.ts tests/component/ResearchView.spec.ts
pnpm typecheck
pnpm lint-ci
pnpm build
Pop-Location
python tools/runtime_acceptance.py --offline
git add tools/runtime_acceptance.py tests/test_runtime_acceptance.py .github/workflows/root-safety.yml tests/test_root_safety_workflow.py docs/operations/phase2-acceptance.md freqtrade frequi
git commit -m "ci: gate phase2e managed runtime cutover"
```

Expected: offline acceptance passes; no online/network/live/order action occurs.

---

### Task 8: Fresh recursive checkout and final review gate

**Files:**
- No production file changes unless verification identifies a defect.
- Record evidence in the PR/check system only when separately authorized.

**Interfaces:**
- Exact root SHA recursively resolves reviewed backend/frontend/strategy SHAs.
- Root Safety and all component gates run from a zero-cache fresh checkout.
- No merge/push/PR-ready action is implied.

- [ ] **Step 1: Verify clean exact component state**

```powershell
git status --short
git submodule status --recursive
git log -1 --oneline
git -C freqtrade log -1 --oneline
git -C frequi log -1 --oneline
git -C freqtrade-strategies log -1 --oneline
```

Expected: clean status and expected reviewed SHAs.

- [ ] **Step 2: Run zero-cache recursive checkout verification**

Use a new empty directory, clone/fetch the exact root SHA, run `git submodule update --init --recursive --depth 1` only if the exact commits are reachable, install from lock/pinned inputs, and run the master final gate. Do not copy build artifacts, virtual environments, node_modules, secrets, state, or Docker images from the development checkout.

- [ ] **Step 3: Run independent reviews**

Request architecture, code-quality/security, compatibility, execution-safety, and Root Safety reviews. Resolve every actionable P0/P1 and rerun affected/full gates.

- [ ] **Step 4: Stop before external publication**

Report exact commits, test counts, skips/warnings, offline/online acceptance status, remaining risks, and whether 8081/8082/8083 are absent. Await explicit push/PR/merge/live instructions.
