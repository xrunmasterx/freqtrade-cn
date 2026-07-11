# Root Safety empty-state CI fix report

## Scope and result

- Target failure: Root Safety run `29139429237`, job `86509754311`, step `Verify empty state through Freqtrade`.
- Scope: `tools/compose_runtime.py`, its focused contract test, and this report only.
- No raw Compose invocation was added or used by the workflow. The probe remains reachable only through the fixed `check-state` allowlist.
- No workflow, Compose, Dockerfile, backend, frontend, submodule content, or gitlink was changed.
- The shell contract remains strict: both command substitutions must equal exactly `[]`.

## Exact CI failure

The first command failed:

```text
python tools/compose_runtime.py check-state freqtrade
```

The safe helper expanded it to the fixed command equivalent of:

```text
docker compose ... run --rm --no-deps freqtrade \
  show-trades \
  --db-url sqlite:////freqtrade/state/trades.sqlite \
  --config /freqtrade/config/runtime.json \
  --config /freqtrade/config/trading-safety.json \
  --print-json
```

The container exited `2` before reading or printing the trades table:

```text
freqtrade - ERROR - Directory `/freqtrade/user_data` is not readable, writable,
and searchable by the container user. Fix the host directory ownership or
permissions before startup.
```

Because the Spot command substitution failed under `set -euo pipefail`, the subsequent `test "${spot_state}" = "[]"` and the Futures command were not executed. Therefore this was not an `[]` comparison failure, and no Futures output existed in the failing job.

## Root cause

`check-state` correctly selected the initialized database at `/freqtrade/state/trades.sqlite`; the fixture contains zero trades. However, Freqtrade's common configuration loading runs before `show-trades` opens the database. It resolves a user-data directory and calls `create_userdata_dir(..., create_dir=False)`, whose Docker access gate requires read, write, and search access.

Without an explicit CLI override, the configured/default path is `/freqtrade/user_data`. The image creates that path as image user `ftuser` (UID 1000). Compose deliberately replaces the container identity with the bootstrapped host identity so bind-mounted state remains accessible; on the GitHub runner that identity differs from UID 1000. Consequently the state mount is writable, while the image-owned `/freqtrade/user_data` root fails the write-access gate. The earlier mount probe passed because it used an explicit Python entrypoint and tested `/freqtrade/state` plus the read-only input mounts; it did not run Freqtrade configuration loading.

The initialized SQLite files were not the cause: both exist at the expected mounted paths with complete Freqtrade schema and zero `trades` rows.

## Minimal fix

The fixed `check-state` expansion now adds:

```text
--user-data-dir /freqtrade/state
```

`/freqtrade/state` is the already verified, service-private writable bind mount. This lets Freqtrade complete its standard configuration initialization without granting write access to `/freqtrade/user_data`, changing the Compose security model, or adding another mount. The DB URL, both config paths, service allowlist, argument rejection rules, and `--print-json` are unchanged.

The probe may create Freqtrade's standard empty user-data subdirectories below the service-private state root. It does not alter or print trade rows; the authoritative result still comes from `show-trades --print-json` against the fixed database URL.

## TDD evidence

RED was established by changing only the expected safe expansion for both Spot and Futures, then running:

```text
python -m unittest tests.test_compose_runtime.ComposeRuntimeTests.test_state_check_expands_to_fixed_freqtrade_command -v
```

Result: two subtest failures, each showing that the production expansion lacked only `--user-data-dir /freqtrade/state`.

After adding those two fixed tokens to production code, the same focused test passed. The complete `tests.test_compose_runtime` module then passed `14/14`.

## Verification

Fresh local Docker checks through the safe helper:

```text
python tools/compose_runtime.py check-state freqtrade
python tools/compose_runtime.py check-state freqtrade-futures
```

Both exited `0`; each stdout was exactly `[]`. Docker/Freqtrade lifecycle logs remained on stderr, and no trade row was emitted.

Fresh repository checks:

```text
python -m unittest discover -s tests -p "test_*.py" -v
```

Result: `Ran 170 tests`, `OK (skipped=1)`. The skip is the existing POSIX-only integration test on Windows.

```text
python tools/runtime_contract.py
```

Result: `runtime contract: OK`.

```text
git diff --check
```

Result: exit `0`; only the existing Windows LF-to-CRLF working-copy warnings were printed.

## Self-review and remaining concern

- Every production change is covered by the focused exact-list assertion for both allowed services.
- Caller-supplied extra arguments, alternate services, user overrides, entrypoints, volumes, environment, and capabilities remain rejected.
- The strict `[]` workflow assertion was not weakened or bypassed.
- The change does not capture or post-process JSON, so it cannot accidentally leak trade rows through a new error/reporting path.
- The local Docker engine reported pre-existing orphan containers for the shared project name; they did not affect the `--no-deps` one-shot probes and were not modified.
- A new GitHub-hosted Root Safety run is still required after the parent pushes the commit, both to confirm the Linux UID scenario and to allow the previously skipped Gitleaks step to execute.
