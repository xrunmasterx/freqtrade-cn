# P0 Draft PR Safety Closure Tasks

> Generated from `docs/superpowers/specs/2026-07-11-p0-draft-pr-safety-closure-design.md` and the detailed implementation plan beside this file.

**Status:** Approved — Task 1 in progress

**Execution:** Subagent-Driven Development; one fresh implementer and independent task review per task.

**Task count:** 10

## Task list

### Task 1: [~] Formal runtime paths

- Files: `docker-compose.yml`, `tools/bootstrap_runtime.py`, `tools/runtime_contract.py`, `tools/compose_runtime.py`, related tests, `README.docker.md`
- Outcome: `/freqtrade/state` is the only writable root; Spot/Futures use the explicit read-only strategy path; Research alias mounts are removed.
- Acceptance: exact command/mount mutations fail; focused root tests and runtime contract pass.

### Task 2: [ ] Dynamic-UID formal startup gate

- Files: `tools/formal_startup.py`, `tests/test_formal_startup.py`, `.github/workflows/root-safety.yml`, `README.docker.md`
- Outcome: production argv is verified under UID:GID `12345:12345`, ephemeral state/secrets, dry-run, and `--network none`.
- Acceptance: Spot/Futures pass only the approved local boundary; Research answers ping; arbitrary non-zero exits are rejected.

### Task 3: [ ] Compose action convergence

- Files: `tools/compose_runtime.py`, `tests/test_compose_runtime.py`, supported runbooks
- Outcome: remove `create/start/restart`; `up` accepts exactly one service and no caller Docker flags.
- Acceptance: forbidden actions fail before Docker; emergency `stop/down/ps/logs` remain available.

### Task 4: [ ] Committed-tree build context

- Files: `tools/committed_build.py`, `tests/test_committed_build.py`
- Outcome: temporary Docker context contains only root HEAD plus exact backend/frontend gitlink trees.
- Acceptance: dirty/mismatched submodules and unsafe archive members fail; ignored/runtime/private data never enters context; cleanup is unconditional.

### Task 5: [ ] Image provenance and inspected-ID launch

- Files: `tools/image_provenance.py`, `Dockerfile`, `tools/compose_runtime.py`, `tools/runtime_contract.py`, workflow and tests
- Outcome: full root/backend/frontend SHAs are labeled and inspected; Compose launches the inspected `sha256:` image ID with fixed recreate/no-build/no-deps flags.
- Acceptance: any build/inspect/label/render failure prevents launch; no mutable-tag or old-container fallback exists.

### Task 6: [ ] Formal SQLite service lanes

- Files: `tools/sqlite_state.py`, `tests/test_sqlite_state.py`, SQLite runbook
- Outcome: schema 2 separates service state and archive; source/destination come from runtime manifest; old generic restore escape hatches are removed.
- Acceptance: Spot/Futures cross-restore and archive promotion fail before any write; schema 1 is explicit legacy-only; comparison is named structural.

### Task 7: [ ] Durability policy B

- Files: `tools/sqlite_state.py`, `tests/test_sqlite_state.py`, SQLite runbook
- Outcome: POSIX uses approved file/directory sync barriers; Windows reports only atomic/process-crash safety.
- Acceptance: exact barrier order and every failure point are tested; post-publication failures quarantine and never print success.

### Task 8: [ ] Standard-library-first Root CI

- Files: `.github/workflows/root-safety.yml`, `tests/test_root_safety_workflow.py`, optionally one proven runtime-dependent root test
- Outcome: root unit tests pass with `python -S` before bootstrap and all dependency installation; PyYAML is not required.
- Acceptance: mutation-resistant workflow step/order tests and isolated interpreter gate pass.

### Task 9: [ ] Frontend disappeared-target visibility

- Files: `frequi/src/stores/ftbotwrapper.ts`, `frequi/src/components/ftbot/TradeList.vue`, focused frontend tests, root `frequi` gitlink
- Outcome: delete/cancel/reload reject when their explicit Bot target disappears and show a localized error without active-Bot fallback.
- Acceptance: confirmation-race tests prove no API call reaches any Bot; frontend tests, typecheck, and scoped lint pass.

### Task 10: [ ] Final integration and merge-readiness evidence

- Files: ignored SDD evidence; docs only if verified drift exists
- Outcome: final local gates, remote publication, no-local recursive clone, Root Safety, optional authorized online dry-run, and whole-branch review all correspond to one final SHA.
- Acceptance: every approved spec gate passes; Draft becomes Ready only after online acceptance and no Critical/Important findings; merge remains separately authorized.

## Execution rules

- Complete exactly one task, produce its report and review package, and stop for review before the next task.
- Every task begins with an observed RED failure for the intended reason.
- Every Critical/Important review finding returns to the same task for a focused fix and re-review.
- Each task uses the commit boundary specified in the detailed plan.
- Do not push an unreviewed task commit.
- Do not modify or clean unrelated user work.
