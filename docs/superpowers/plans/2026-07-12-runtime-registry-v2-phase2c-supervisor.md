
# Phase 2C Supervisor and Safe Runtime Driver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute Registry lifecycle jobs through one host-local Supervisor, reuse the verified P0 Compose launch kernel, create append-only attempts, reconcile ambiguous outcomes, manage per-instance access networks, and launch the isolated Bitget Spot paper probe.

**Architecture:** Keep orchestration/state transitions independent of Docker behind a `RuntimeDriver` protocol. Adapt the existing `tools.compose_runtime` validated-snapshot path instead of introducing Docker SDK control. The Supervisor supplies typed RuntimeSpec/state/secret references to the Task 4 compiler; only that compiler resolves launch material and emits the internal snapshot before the Supervisor calls the driver. Failures latch and never auto-restart.

**Tech Stack:** Python standard library, SQLAlchemy/PostgreSQL repository adapter, Docker Compose CLI, Pydantic DTOs, unittest, pytest, Ruff.

## Global Constraints

- Follow the master plan and completed Phase 2A/2B reviewed interfaces.
- The Supervisor is the only dynamic Docker actor.
- Dynamic runtime Compose uses exact inspected image ID, `restart: "no"`, no host port, no Docker socket, dropped capabilities, no-new-privileges, read-only inputs, one managed writable state, and isolated networks.
- Every actual launch creates exactly one append-only RuntimeAttempt.
- Ambiguous outcomes reconcile deterministic identity before retry.
- The Supervisor never deletes unknown containers/networks/paths.
- Emergency stop/inspect remains usable without PostgreSQL.
- Online exchange connectivity remains separately authorized.

---

## File Structure

- Create `tools/runtime_driver.py`: pure `RuntimeDriver` protocol and immutable identity/snapshot DTOs; the safe Compose adapter is deferred until Task 4 trust-boundary gates pass.
- Create `tools/runtime_supervisor/domain.py`: driver-neutral reconciliation decisions.
- Create `tools/runtime_supervisor/reconciler.py`: job/attempt reconciliation.
- Create `tools/runtime_supervisor/daemon.py`: bounded lease loop and one-shot command.
- Create `tools/runtime_supervisor/offline_identity.py`: atomic non-secret emergency snapshot.
- Create `tools/runtime_supervisor/__main__.py`.
- Modify `tools/compose_runtime.py`: extract/reuse verified launch primitives, no behavior change for current services.
- Modify `tools/runtime_registry_cli.py`: enable typed lifecycle job creation.
- Modify backend `freqtrade/platform/runtime_repository.py`: Supervisor attempt/job transaction methods.
- Add root and backend tests plus Root Safety selectors.

---

### Task 1: RuntimeDriver protocol and P0 launch-kernel extraction

**Files:**
- Create: `tools/runtime_driver.py`
- Modify: `tools/compose_runtime.py`
- Test: `tests/test_runtime_driver.py`
- Test: `tests/test_compose_runtime.py`

**Interfaces:**
- Produces `RuntimeDriver.inspect(identity)`, `launch(snapshot)`, `stop(identity)`, `probe(identity, profile_id)`.
- Produces immutable `DriverIdentity`, `DriverInspection`, `LaunchSnapshot`.
- Preserves every existing `tools.compose_runtime` CLI behavior.

- [ ] **Step 1: Write RED protocol/compatibility tests**

```python
class RuntimeDriverTests(unittest.TestCase):
    def test_launch_snapshot_validation_accepts_only_existing_snapshot(self) -> None:
        payload = valid_snapshot_payload()
        snapshot = LaunchSnapshot(**payload)
        assert LaunchSnapshot.model_validate(snapshot) is snapshot
        for external in (payload, {**payload, "compose": {"services": {}}}):
            with self.assertRaisesRegex(DriverValidationError, "driver_validation_error"):
                LaunchSnapshot.model_validate(external)

    def test_existing_compose_cli_still_calls_verified_path(self) -> None:
        completed = launch_reviewed_service("freqtrade", self.root)
        self.assertEqual(completed.returncode, 0)
        self.assertTrue(self.verified_snapshot_was_used)
```

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_runtime_driver tests.test_compose_runtime -v
```

Expected: missing `runtime_driver`.

- [ ] **Step 3: Implement protocol and adapter**

```python
class RuntimeDriver(Protocol):
    def inspect(self, identity: DriverIdentity) -> DriverInspection: ...
    def launch(self, snapshot: LaunchSnapshot) -> DriverInspection: ...
    def stop(self, identity: DriverIdentity) -> DriverInspection: ...
    def probe(
        self,
        identity: DriverIdentity,
        profile_id: str,
    ) -> HealthObservation: ...
```

Task 1 does not create `SafeComposeRuntimeDriver`. The concrete adapter is deferred until
Task 4 has implemented and mutation-tested the approved compiler and final pre-mutation
validator. It will then call the extracted `_validate_launch`, exact image inspection,
committed build identity, validated temporary snapshot, `--no-build --no-deps`, and cleanup
functions using subprocess argument lists only, with no shell interpolation or Docker SDK.
The future adapter validates `profile_id`, resolves an exact driver-owned committed health
catalog entry authorized for the complete identity, enforces bounded timing/retries,
compares the complete profile immediately before execution, and executes only that argv.
Shell/arbitrary executables, credential argv, ID/profile mismatch, and excessive bounds are
rejected with zero probe execution.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -S -m unittest tests.test_runtime_driver tests.test_compose_runtime tests.test_committed_build tests.test_image_provenance -v
git add tools/runtime_driver.py tools/compose_runtime.py tests/test_runtime_driver.py tests/test_compose_runtime.py
git commit -m "refactor(runtime): expose verified compose driver"
```

Expected: existing P0 tests and new driver tests pass with no behavior change to current services.

---

### Task 2: Supervisor repository attempt/job transactions

**Files:**
- Modify: `freqtrade/freqtrade/platform/runtime_repository.py`
- Modify: `freqtrade/freqtrade/platform/runtime_service.py`
- Test: `freqtrade/tests/platform/test_supervisor_repository.py`

**Interfaces:**
- Adds `begin_attempt(job_id, resolved_material)`, `record_healthy()`, `record_failed()`, `record_stopped()`, `renew_lease()`, `latch_failure()`.
- One transaction owns every job/attempt/instance/audit state transition.

- [ ] **Step 1: Write RED transition tests**

```python
def test_begin_attempt_creates_monotonic_append_only_attempt(repository, running_job) -> None:
    first = repository.begin_attempt(running_job.job_id, resolved_material("image-a"))
    repository.record_stopped(first.attempt_id, exit_code=0)
    second = repository.begin_attempt(next_job().job_id, resolved_material("image-a"))
    assert second.attempt_number == first.attempt_number + 1

def test_failed_attempt_latches_without_queuing_retry(repository, running_job) -> None:
    attempt = repository.begin_attempt(running_job.job_id, resolved_material("image-a"))
    repository.record_failed(attempt.attempt_id, "health_timeout")
    instance = repository.get_instance(attempt.instance_id)
    assert instance.failure_latched is True
    assert repository.pending_jobs(attempt.instance_id) == ()
```

- [ ] **Step 2: Run RED**

```powershell
cd freqtrade
python -m pytest tests/platform/test_supervisor_repository.py -q -p no:cacheprovider
```

Expected: missing methods.

- [ ] **Step 3: Implement locked transitions**

Every method locks job, instance, and active attempt in deterministic order. Attempt material includes exact RuntimeSpec/template/image/secret-version/state/component commit identities. `record_failed()` completes the job and latches the instance atomically. `retry` is rejected unless latched and creates a new job only after explicit operator command.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest tests/platform/test_supervisor_repository.py tests/platform/test_runtime_repository.py tests/platform/test_runtime_service.py -q -p no:cacheprovider
ruff check freqtrade/platform/runtime_repository.py freqtrade/platform/runtime_service.py tests/platform/test_supervisor_repository.py
git add freqtrade/platform/runtime_repository.py freqtrade/platform/runtime_service.py tests/platform/test_supervisor_repository.py
git commit -m "feat(platform): persist supervisor attempt transitions"
```

---

### Task 3: Driver-neutral reconciliation state machine

**Files:**
- Create: `tools/runtime_supervisor/__init__.py`
- Create: `tools/runtime_supervisor/domain.py`
- Create: `tools/runtime_supervisor/reconciler.py`
- Test: `tests/test_runtime_supervisor_reconciler.py`

**Interfaces:**
- Consumes repository protocol, `RuntimeDriver`, `ManagedStateProvider`, `LocalFileSecretProvider`.
- Produces stable decisions `adopt`, `launch`, `continue_observing`, `stop_exact`, `fail_latched`, `identity_mismatch`.
- No module import performs I/O.

- [ ] **Step 1: Write RED table-driven reconciliation tests**

```python
CASES = (
    ("absent", "launch"),
    ("starting_exact", "continue_observing"),
    ("healthy_exact", "adopt"),
    ("stopped_exact", "fail_latched"),
    ("healthy_wrong_spec", "identity_mismatch"),
    ("healthy_wrong_state", "identity_mismatch"),
    ("unknown_present", "fail_latched"),
)

def test_reconciliation_matrix() -> None:
    for observed, expected in CASES:
        with subTest(observed=observed):
            assert decide_reconciliation(expected_identity(), inspection(observed)).value == expected
```

Add tests proving `identity_mismatch` and `DriverState.UNKNOWN` never invoke driver
launch/stop/restart/delete. `UNKNOWN` represents paused, restarting, removing, dead, and any
future present state that cannot be safely normalized; it retains observed identity,
requires `container_id`, forbids `exit_code`, and always latches/no-ops.

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_runtime_supervisor_reconciler -v
```

Expected: missing package.

- [ ] **Step 3: Implement pure decisions and orchestrator**

`decide_reconciliation()` compares project/container labels, exact image ID, RuntimeSpec digest, allocation ID, instance/attempt ID, and network identity. The orchestrator resolves state and secret material only after spec/template/catalog revalidation. It writes an attempt before launch and records every result through repository calls.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -S -m unittest tests.test_runtime_supervisor_reconciler -v
git add tools/runtime_supervisor/domain.py tools/runtime_supervisor/reconciler.py tools/runtime_supervisor/__init__.py tests/test_runtime_supervisor_reconciler.py
git commit -m "feat(runtime): reconcile supervised attempts"
```

---

### Task 4: Safe Compose snapshot compilation and material mounts

**Files:**
- Modify: `tools/runtime_driver.py`
- Create: `tools/runtime_snapshot.py`
- Test: `tests/test_runtime_snapshot.py`
- Test: `tests/test_runtime_driver.py`

**Interfaces:**
- Produces `compile_launch_snapshot(spec, template, policies, state, secrets, identity) -> LaunchSnapshot`.
- Output uses one-time temporary Compose input and contains no long-lived generated file.
- Secrets mount as Compose secrets/fixed read-only files, never ordinary environment values.

**User-approved Architecture Resolution A:** `LaunchSnapshot` is an internal
post-compilation value, never accepted or deserialized from a public API, PostgreSQL,
RuntimeSpec JSON, or generic external mapping. Task 2 validates only structural/canonical
form and is not provenance or secret-classification authority. The Task 4 compiler accepts
only committed closed `AdapterTemplate`/policy plus typed RuntimeSpec, state-allocation, and
secret references. Only it emits argv, environment entries, and resolved mount sources.
Internal compilation uses the explicit dataclass constructor. `LaunchSnapshot.model_validate`
returns an already-constructed snapshot unchanged and rejects every mapping/raw value with
fixed `DriverValidationError`; no external boundary may use it as a deserializer.

Task 4 trust-boundary gates are mandatory:

- read-only sources originate only from compiler-owned or allowlisted material roots and
  cannot expose host directories, Docker sockets, devices, named pipes, or untyped secrets;
- every source is resolved, and parent/root escape plus symlink, junction, or reparse-point
  escape is rejected;
- argv is expanded only from a committed executable/argument template, never shell
  interpolation or caller strings, and never contains raw credentials or other secrets;
- environment names use a per-template closed allowlist, with values only from typed
  non-secret fields or committed constants;
- provider-resolved `SecretMount` values are the only secret transport;
- the final snapshot validator rechecks every gate, and the future concrete driver invokes
  it immediately before mutation.
- the future driver invokes a trusted absolute Docker executable with a driver-owned minimal
  environment and an explicitly approved local engine endpoint/context. It rejects poisoned
  `PATH`, `DOCKER_HOST`, `DOCKER_CONTEXT`, `DOCKER_CONFIG`, and Docker TLS/certificate
  variables before mutation with zero action. The extracted P0 compatibility CLI keeps its
  existing ambient Docker executable/environment behavior unchanged.

No `SafeComposeRuntimeDriver` exists until all gates and mutation tests pass. This is the
approved resolution of the review finding, not a claim that Task 2 dataclasses prove
provenance.

- [ ] **Step 1: Write RED security mutation tests**

```python
MUTATIONS = (
    ("restart", "unless-stopped"),
    ("privileged", True),
    ("network_mode", "host"),
    ("pid", "host"),
    ("volumes", ["/:/host"]),
    ("ports", ["9000:8080"]),
    ("parent_directory_docker_socket", "../docker.sock"),
    ("read_only_mount_secret_role_bypass", "secret-as-config"),
    ("source_root_or_link_escape", "material-root/link-out"),
    ("shell_argv", ("sh", "-c", "caller command")),
    ("raw_credential_argv", ("freqtrade", "--password", "private")),
    ("non_allowlisted_environment", ("CALLER_VALUE", "raw-secret")),
    ("poisoned_path", {"PATH": "attacker-bin"}),
    ("remote_docker_host", {"DOCKER_HOST": "tcp://attacker:2375"}),
    ("unapproved_docker_context", {"DOCKER_CONTEXT": "attacker"}),
    ("poisoned_docker_config", {"DOCKER_CONFIG": "attacker-config"}),
    ("poisoned_docker_tls", {"DOCKER_TLS_VERIFY": "1", "DOCKER_CERT_PATH": "attacker"}),
)

def test_snapshot_validator_rejects_escape_mutations() -> None:
    for key, value in MUTATIONS:
        with pytest.raises(SnapshotPolicyError):
            validate_rendered_snapshot(mutated_render(key, value))
```

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_runtime_snapshot tests.test_runtime_driver -v
```

Expected: missing compiler/validator.

- [ ] **Step 3: Implement exact snapshot**

Snapshot service has:
- exact image ID;
- fixed expanded command tokens;
- read-only committed config/strategy/policy mounts;
- one allocation RW mount;
- exact secret mounts;
- non-root UID/HOME;
- `cap_drop: [ALL]`;
- `security_opt: [no-new-privileges:true]`;
- `restart: "no"`;
- private network and, only for application runtimes, per-instance access network;
- identity/provenance labels;
- no host port.

Validate the compiled snapshot and rendered JSON before and immediately before action. The
acceptance tests independently cover parent-directory Docker socket exposure,
`ReadOnlyMount` secret-role bypass, source-root and symlink/junction/reparse escape, shell
argv, raw credential argv, non-allowlisted/raw-secret environment, and poisoned Docker
executable/environment/endpoint inputs with pre-mutation rejection and zero action.
Boundary-specific tests reject mapping input at the public API DTO,
repository/PostgreSQL loader, RuntimeSpec/compiler input, Supervisor assembly, and concrete-
driver launch, and assert none calls mapping deserialization. Temporary files are opened
with exclusive permissions and removed in `finally`. Create `SafeComposeRuntimeDriver` only
after all of these tests pass; it must call the final validator immediately before mutation.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -S -m unittest tests.test_runtime_snapshot tests.test_runtime_driver tests.test_runtime_contract -v
git add tools/runtime_snapshot.py tools/runtime_driver.py tests/test_runtime_snapshot.py tests/test_runtime_driver.py
git commit -m "feat(runtime): compile safe launch snapshots"
```

---

### Task 5: Per-instance Runtime Access network attachment

**Files:**
- Modify: `tools/runtime_driver.py`
- Modify: `tools/runtime_supervisor/reconciler.py`
- Test: `tests/test_runtime_access_network.py`

**Interfaces:**
- Produces `ensure_access_network(identity, platform_control_identity)` and `remove_access_network_if_empty(identity)`.
- Network contains exactly verified platform-control and exact active runtime.
- Network name/alias is deterministic from non-secret instance/attempt identity and never caller-provided.

- [ ] **Step 1: Write RED network tests**

```python
class RuntimeAccessNetworkTests(unittest.TestCase):
    def test_two_runtimes_never_share_access_network(self) -> None:
        first = access_network_identity("runtime-a")
        second = access_network_identity("runtime-b")
        self.assertNotEqual(first.network_name, second.network_name)

    def test_unknown_member_fails_closed_without_disconnect(self) -> None:
        observed = network_members("platform-control", "runtime-a", "unknown")
        with self.assertRaisesRegex(NetworkIdentityError, "access_network_member_mismatch"):
            reconcile_access_network(expected_access_identity("runtime-a"), observed)
        self.assertFalse(self.driver.disconnect_called)
```

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_runtime_access_network -v
```

Expected: missing interfaces.

- [ ] **Step 3: Implement verified closed network operations**

Use exact `docker network inspect/create/connect/disconnect/rm` argument arrays inside the driver only. Verify platform-control container ID and immutable labels before connect. Create with `--internal` when upstream access is not required. Never disconnect/delete a network containing an unknown member. Reconcile attachments after daemon restart.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -S -m unittest tests.test_runtime_access_network tests.test_runtime_driver tests.test_runtime_supervisor_reconciler -v
git add tools/runtime_driver.py tools/runtime_supervisor/reconciler.py tests/test_runtime_access_network.py
git commit -m "feat(runtime): isolate per-instance access networks"
```

---

### Task 6: Health, ambiguous launch, failure latch, and offline identity

**Files:**
- Create: `tools/runtime_supervisor/offline_identity.py`
- Modify: `tools/runtime_supervisor/reconciler.py`
- Modify: `tools/compose_runtime.py`
- Test: `tests/test_runtime_offline_identity.py`
- Test: `tests/test_runtime_supervisor_failures.py`

**Interfaces:**
- Publishes root-owned/read-only non-secret snapshot after exact identity exists.
- Emergency supports only status, inspect, logs, and exact stop.
- No emergency start/rebuild/spec/mount/restore/delete.

- [ ] **Step 1: Write RED failure and emergency tests**

```python
def test_timeout_adopts_exact_healthy_container(reconciler) -> None:
    reconciler.driver.launch.side_effect = TimeoutError()
    reconciler.driver.inspect.return_value = healthy_exact_inspection()
    result = reconciler.run(start_job())
    assert result.code == "adopted_after_ambiguous_launch"

def test_emergency_rejects_label_mismatch_without_stop(emergency) -> None:
    with pytest.raises(EmergencyIdentityError, match="offline_identity_mismatch"):
        emergency.stop("runtime-1", observed=wrong_labels())
    emergency.driver.stop.assert_not_called()
```

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_runtime_offline_identity tests.test_runtime_supervisor_failures -v
```

Expected: missing offline/failure behavior.

- [ ] **Step 3: Implement bounded health and snapshot**

Health requests pass only `profile_id`. The driver validates the ID, resolves exactly one
driver-owned committed catalog entry authorized for the complete expected identity,
enforces bounded start-period/interval/timeout/retries, compares the complete profile again
immediately before execution, and runs only its exact argv. Future mutation tests reject
shell/arbitrary executables, credential argv, ID/profile mismatch, and excessive bounds with
zero execution. Exhaustion stops only exact identity, records failed attempt, latches
instance, and queues nothing. Offline snapshot is canonical JSON with
instance/attempt/project/container/image/spec/allocation/network identities, component
commits, written atomically with durability and fixed ACL; it contains no
secret/path/credential/DSN.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -S -m unittest tests.test_runtime_offline_identity tests.test_runtime_supervisor_failures tests.test_compose_runtime -v
git add tools/runtime_supervisor/offline_identity.py tools/runtime_supervisor/reconciler.py tools/compose_runtime.py tests/test_runtime_offline_identity.py tests/test_runtime_supervisor_failures.py
git commit -m "feat(runtime): latch failures and publish emergency identity"
```

---

### Task 7: Supervisor daemon, CLI, and paper-probe offline acceptance

**Files:**
- Create: `tools/runtime_supervisor/daemon.py`
- Create: `tools/runtime_supervisor/__main__.py`
- Modify: `tools/runtime_registry_cli.py`
- Test: `tests/test_runtime_supervisor_daemon.py`
- Test: `tests/test_runtime_registry_cli.py`
- Modify: `.github/workflows/root-safety.yml`
- Modify: `tests/test_root_safety_workflow.py`
- Create: `docs/operations/runtime-supervisor.md`
- Update: root `freqtrade` gitlink.

**Interfaces:**
- Commands: `python -m tools.runtime_supervisor run`, `reconcile-once`.
- CLI lifecycle commands create DB jobs only; web API remains read-only.
- Paper probe offline acceptance uses Bitget Spot, SampleStrategy, committed config, enforced paper/dry-run, no exchange-write credential, no host port.

- [ ] **Step 1: Write RED daemon/CLI tests**

```python
def test_daemon_renews_lease_and_processes_one_job_at_a_time() -> None:
    daemon = RuntimeSupervisorDaemon(fake_repository(two_jobs()), fake_reconciler())
    daemon.run_once()
    assert daemon.repository.claim_count == 1
    assert daemon.repository.completed_count == 1

def test_cli_start_creates_job_without_calling_driver() -> None:
    result = run_cli(
        "runtime-registry", "start",
        "--instance-id", "phase2-paper-probe",
        "--expected-version", "0",
        "--idempotency-key", "acceptance-start-1",
    )
    assert result.returncode == 0
    assert fake_driver.calls == []
```

- [ ] **Step 2: Run RED**

```powershell
python -S -m unittest tests.test_runtime_supervisor_daemon tests.test_runtime_registry_cli -v
```

Expected: missing daemon/lifecycle command behavior.

- [ ] **Step 3: Implement daemon and typed CLI**

Daemon uses bounded poll/lease intervals, graceful signal shutdown, no concurrent job for one instance, and shared `run_once()` implementation. CLI commands are `start`, `stop`, `retry`, `retire`, `status`; every mutation requires explicit expected version and idempotency key.

- [ ] **Step 4: Add offline formal acceptance and Root Safety**

CI compiles the paper probe, provisions isolated temporary state/secrets, renders and validates snapshot, performs an offline formal startup that cannot reach an exchange, proves `dry_run` exact boolean and no write credential, checks no host port, then stops exact identity and retains attempt evidence.

- [ ] **Step 5: Verify Phase 2C**

```powershell
python -S -m unittest tests.test_runtime_driver tests.test_runtime_snapshot tests.test_runtime_access_network tests.test_runtime_supervisor_reconciler tests.test_runtime_supervisor_failures tests.test_runtime_offline_identity tests.test_runtime_supervisor_daemon tests.test_runtime_registry_cli -v
Push-Location freqtrade
python -m pytest tests/platform/test_supervisor_repository.py tests/platform/test_runtime_repository.py tests/platform/test_runtime_service.py -q -p no:cacheprovider
ruff check freqtrade/platform tests/platform
Pop-Location
```

Expected: all tests pass; no authorized-online step runs.

- [ ] **Step 6: Commit root integration**

```powershell
git add tools/runtime_supervisor tools/runtime_registry_cli.py .github/workflows/root-safety.yml tests/test_root_safety_workflow.py tests/test_runtime_supervisor_daemon.py docs/operations/runtime-supervisor.md freqtrade
git commit -m "ci: gate phase2c runtime supervisor"
```

Expected: reviewed backend gitlink, root supervisor/CI/runbook only, clean worktree.
