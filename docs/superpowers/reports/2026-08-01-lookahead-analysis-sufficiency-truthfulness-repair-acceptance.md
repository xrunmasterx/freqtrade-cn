# Phase 1 Lookahead Analysis Sufficiency Truthfulness Repair Acceptance Report

**Acceptance date:** 2026-08-01

**Status:** accepted at exact implementation SHAs and one immutable local image; no
market-data analysis, strategy candidate, retired-holdout use, performance result,
Runtime, Paper, Live, exchange write, remote push, merge, release, or deployment

**Branch:** `xrunmasterx/phase1-complete-development`

**Worktree:**
`C:\Users\dezhengu\orca\workspaces\freqtrade-cn\phase1-complete-development`

**Plan:**
[Phase 1 Lookahead Analysis Sufficiency Truthfulness Repair](../plans/2026-08-01-lookahead-analysis-sufficiency-truthfulness-repair.md)

**Triggering evidence:**
[Phase 1 Baseline Capability Gate Acceptance](2026-07-30-phase1-baseline-capability-gate-acceptance.md)

## 1. Exact implementation identity

| Repository | Exact accepted implementation SHA |
|---|---|
| Root | `c79df3362988909428893d90659dd8f89a7a9e89` |
| `freqtrade/` backend | `8b1ec82765cc0eb59da0287cd62dd892b62f0f11` |
| `frequi/` frontend | `a0a4502a02b4a98854eb60d554ccf7205ca89f15` |
| `freqtrade-strategies/` | `dec5adb77f03b0c33ccfbc036ff0a3e57f7d571d` (unchanged) |

The Root implementation commit has tree
`59b308400a9244b9e159af1f0af4e096a3c35672` and directly pins the three submodule
SHAs above. It updates the approved plan from design to implemented and contains no
acceptance claim. This report and the final status update are a later documentation-only
commit and do not replace the implementation identity.

The accepted frontend head contains the original result-state implementation
`3dd957951381f6a728ca03854c5786e161afb2f7` followed by the fail-closed correction
`a0a4502a02b4a98854eb60d554ccf7205ca89f15`. The accepted backend head contains the
single bounded implementation commit
`8b1ec82765cc0eb59da0287cd62dd892b62f0f11`.

## 2. Accepted user outcome

The existing Freqtrade Lookahead Analysis journey now answers two questions in their
logical order:

1. did the run analyze at least its effective minimum number of signals; and
2. only after that minimum was reached, did the run detect a lookahead-bias witness?

The accepted behavior is:

- the backend returns `analysis_state=insufficient_signals` below its initialized
  effective minimum and reports the effective minimum and target;
- it returns `analysis_state=completed` only after the minimum is reached and the
  existing engine check completes successfully;
- a completed result may be below the target because the target is a work goal/cap, not
  a second validity Gate;
- a minimum-reached result whose engine check remains failed uses the existing background
  error channel rather than a fabricated successful state;
- the public API rejects zero and negative minimum or target values, aligning the API
  with the existing positive-integer CLI invariant;
- FreqUI shows green only for an internally consistent
  `completed + has_bias=false` response;
- insufficient, legacy, and malformed responses remain neutral with an explicit
  not-evaluated verdict; and
- every state permanently says that Lookahead Analysis does not establish strategy
  quality, representative coverage, robustness, Paper/Live eligibility, or current or
  future profit.

The existing route, form, request field names and defaults, background-job lifecycle,
analysis algorithm, result table, store, page, and Freqtrade authority remain in place.

## 3. Contract and compatibility boundary

API 2.56 adds required response fields on new backend results:

- `analysis_state`, with exactly `completed` or `insufficient_signals`;
- positive integer `minimum_trade_amount`; and
- positive integer `targeted_trade_amount`.

The thresholds come from the initialized `LookaheadAnalysis` instance after the existing
configuration overrides. FreqUI does not reconstruct them from form state, defaults, or
a prior request.

The frontend intentionally keeps the additive fields optional at the TypeScript boundary
so a new UI can load an older response. Its runtime Gate then requires:

- a recognized state;
- positive integer thresholds with `target >= minimum`;
- a nonnegative integer analyzed-signal count;
- a strict boolean `has_bias`; and
- a count/state relationship consistent with the effective minimum.

Any missing or inconsistent item produces the neutral unknown state. In particular,
missing, `null`, numeric, or string bias verdicts cannot be interpreted through
JavaScript truthiness as a clean result.

Rolling compatibility is deliberately one-directional. A new FreqUI with an old backend
is safe and neutral. An old FreqUI with API 2.56 is not safe because it ignores the new
state and can retain the old false-green behavior. API 2.56 must therefore be published
frontend-first or atomically with the matching frontend. This local acceptance used one
combined immutable image; it does not authorize a backend-first rollout.

## 4. Automated verification

All final checks used the backend and frontend SHAs in Section 1 and did not execute a
real Lookahead Analysis or read market/holdout data.

| Check | Result |
|---|---:|
| Focused mocked backend Lookahead/API-version pytest | 9 passed |
| Full backend API-server test file, excluding one unavailable optional FreqAI resolver case | 133 passed, 1 deselected |
| Backend changed-file Ruff check | passed |
| Focused frontend component and locale Vitest | 2 files, 36 passed |
| Full frontend Vitest | 45 files, 292 passed |
| Frontend typecheck | passed |
| Frontend production build | passed |
| Final repair-file ESLint and Prettier check | passed |
| Mocked Chromium completed and insufficient journeys | 2 passed |
| Root/backend/frontend `git diff --check` | passed |

The unfiltered backend API-server file first reported 133 passes and one unrelated
environment failure: the local virtual environment does not provide the optional
`freqtrade.resolvers.freqaimodel_resolver` module that the pre-existing
`test_api_freqaimodels` tries to patch. The final rerun excluded only that named case;
all 133 remaining tests passed. The nine changed-contract tests passed independently,
so the environmental failure is not treated as a hidden green result.

The full Vitest command exited successfully with all 292 tests passed while still
printing the existing Happy DOM fetch-abort and fork `EPROTO` teardown noise. The mocked
Playwright journey prints the existing `recoverBgJobs` mock console noise. A concurrent
first Playwright invocation reached the page before its temporary Vite server was ready
and failed with `ERR_CONNECTION_REFUSED`; the dedicated final invocation started the
configured server and passed both affected journeys. None of these harness observations
changed product code.

The production build retained existing third-party pure-annotation and chunk-size
warnings. A Ruff format preview would also reflow older, unrelated sections of two large
backend files, so it was not used to manufacture a broad formatting diff; the required
Ruff check and all changed-contract tests passed.

## 5. Orchestrated independent Gates

Read-only reviewers separately checked backend semantics, frontend user truthfulness,
the cross-repository contract, and exact-image provenance. They made no repository
changes and did not open market or holdout data.

| Review | Result |
|---|---|
| Backend implementation Gate | PASS; P0/P1/P2 = 0 |
| Initial frontend implementation Gate | FAIL; one P1 false-green path for malformed `has_bias` and inconsistent thresholds |
| Frontend re-Gate at `a0a4502a...` | PASS; P0/P1/P2 = 0 |
| Cross-repository integration Gate | PASS; P0/P1/P2 = 0 |
| Exact-image acceptance Gate | PASS; P0/P1 = 0, one non-blocking P2 embedded-UI-provenance gap |
| Initial acceptance-documentation Gate | FAIL; one P1 sentence incorrectly denied the positive-integer request-validation change |
| Acceptance-documentation re-Gate | PASS; P0/P1/P2 = 0 |
| Independent acceptance-evidence audit | PASS; no new P0/P1/P2, known provenance P2 confirmed |

The P1 repair requires `has_bias` to be a runtime boolean, validates
`target >= minimum`, uses strict `=== false` for green and `=== true` for red, and adds
neutral cases for missing, null, and string verdicts plus an inverted threshold pair.
Focused tests increased from 32 to 36 and passed before re-Gate.

The documentation P1 was corrected by distinguishing unchanged request shape/defaults
from the one intentional request-behavior change: positive-integer API validation. The
re-Gate and an independent SHA/build/image/cleanup evidence audit then passed without a
new finding.

## 6. Exact Docker build provenance

The accepted combined image is:

```text
tag: freqtrade-cn:lookahead-c79df33
immutable OCI index/image ID:
  sha256:3c2b6e276dc486b57bba69c0e8e6d5f6e9f9d3a7a5b313551e960f0172df5c17
platform: linux/amd64
```

The tag is only a convenient local name. The immutable OCI ID is the image authority.

Docker Buildx retained this exact completed record:

```text
build ref: iugii627lmmjfl9lnxq91iq5r
VCS revision: c79df3362988909428893d90659dd8f89a7a9e89
status: completed
steps: 25/25, including 10 cached steps
OCI amd64 manifest:
  sha256:23980c048decfff5ff7ebab8816e9ecaeed4d8f39dd44832185e13d71a749746
SLSA provenance attachment:
  sha256:88662a7dcad6a0643fca8f9351aa0d39dc33f4afcc62fac1c52fabee8f188a01
```

The build record used context `.` and the committed `Dockerfile`, and binds the final OCI
index to the exact Root revision. The Root tree in turn binds the accepted backend,
frontend, and strategy SHAs. The build context was 1.40 MB. `.dockerignore` excluded
`.git`, `.env`, all `ft_userdata/`, Node dependencies, local frontend output, the backend
virtual environment and user data, caches, and Playwright reports/results. No local
secret, runtime database, log, receipt, or market-data file was included in the image.

The build regenerated the production FreqUI bundle, including
`LookaheadAnalysisView-CgU2Nvwx.js`, copied that exact `dist` tree into the runtime image,
and copied the accepted backend source from the same context. Direct image inspection
then reported API version 2.56, an installed UI index, and 137 packaged UI files.

## 7. Isolated API acceptance

The image was started by immutable ID in one temporary container:

```text
container ID:
  239f079c687e5dc3612f1e89725ab3dd34c3d9c49b66fdc9d2da07849f0fe13c
endpoint: http://127.0.0.1:18087
```

The container used UID/GID `1000:1000`, a read-only root filesystem, init, all Linux
capabilities dropped, `no-new-privileges:true`, and a loopback-only published port. Its
only mounts were one read-only operational config, one new writable temporary state
directory, and three read-only API secret files. It had no market-data, strategy, trading
database, or retained-result mount. Its command was `webserver`; no trade, Paper, Live,
backtest, or analysis command was started.

The API returned:

| Check | Exact result |
|---|---|
| unauthenticated ping | `pong` |
| `/show_config` API version | `2.56` |
| runmode / safety mode | `webserver`, `dry_run=true`, Spot |
| `minimum_trade_amount=0` | HTTP 422 at `minimum_trade_amount` |
| `targeted_trade_amount=0` | HTTP 422 at `targeted_trade_amount` |
| background jobs after both invalid requests | 0 |
| container restarts | 0 |
| actual `ERROR`, `CRITICAL`, or traceback log entries | 0 |

Authentication values were read only into process memory. They were not printed, copied
into the repository, or included in this report. Log lines from the logger named
`uvicorn.error` were INFO startup messages, not error-severity events.

## 8. Exact packaged-UI acceptance

A real headless branded-Chrome session loaded the static UI from the isolated immutable
container. All API responses were intercepted with repository fixtures, so the browser
tested the exact packaged frontend without starting an analysis or reading data.

| Runtime response | Rendered state | Verdict | Signal counts | False-green state |
|---|---|---|---|---|
| valid completed clean | `lookahead-completed-clean` | `No / 否` | analyzed 20, minimum 10, target 20 | intended bounded clean state |
| insufficient | `lookahead-insufficient-signals` | `Not evaluated / 尚未评估` | analyzed 0, minimum 10, target 20 | absent |
| legacy response missing the new contract | `lookahead-contract-unknown` | `Not evaluated / 尚未评估` | hidden because unknown | absent |
| malformed completed response missing `has_bias` | `lookahead-contract-unknown` | `Not evaluated / 尚未评估` | hidden because unknown | absent |

Every case displayed the permanent supporting-diagnostic evidence boundary. The first
read-only browser assertion expected the pure-English verdict `No`; the configured
product correctly rendered bilingual `No / 否`. The assertion was corrected to accept
the actual bilingual copy, and all four cases passed without a product change.

## 9. Non-blocking embedded UI-provenance gap

The exact-image Gate found one P2 packaging limitation that is deliberately not hidden:

- the FreqUI builder cannot run `git rev-parse` because `.git` and Git are absent, so the
  bundle compiles `__COMMIT_HASH__=unknown` and logs a build warning;
- the Dockerfile writes the historical value `local-frequi-f5a81466` to
  `ui/.uiversion`, while `/ui_version` reads `ui/installed/.uiversion`; the served version
  therefore cannot report the accepted frontend SHA.

Neither value chooses the installed bundle, participates in API negotiation, or controls
the Lookahead result state. The production bundle was rebuilt and copied into the image,
and its actual behavior was tested by immutable image ID. Exact acceptance is therefore
authorized by the external chain:

```text
clean Root SHA
  -> exact submodule tree
  -> Buildx VCS revision and SLSA attachment
  -> immutable OCI image ID
  -> actual API and packaged-browser behavior
```

The visible `/ui_version` value and bundled `unknown` marker are not acceptance evidence.
A future packaging/provenance slice may pass the full frontend SHA explicitly, write it
to `ui/installed/.uiversion`, add exact repository OCI labels, and verify both labels and
the endpoint. That work needs its own design and tests; it is not silently added to this
functional repair.

## 10. Cleanup and decision

After evidence collection:

- the temporary container was stopped and removed;
- the dedicated state root
  `C:\Users\dezhengu\AppData\Local\Temp\freqtrade-cn-lookahead-c79df33-acceptance`
  was resolved inside the Windows temporary directory and removed;
- no acceptance container remains;
- the exact `freqtrade-cn:lookahead-c79df33` tag and immutable image ID were retained for
  local reproduction; and
- Root, backend, frontend, and strategies were clean before this documentation update.

Phase 1 Lookahead Analysis Sufficiency Truthfulness Repair is accepted at the exact
implementation SHAs in Section 1. There is no unresolved P0 or P1 inside its declared
boundary. The embedded UI-provenance P2 is recorded, not reclassified as functional
proof and not allowed to weaken the external exact-image chain.

This supporting diagnostic does not prove that a strategy is profitable, unbiased on
unseen markets, representative, robust, restart-stable, Paper-ready, Live-ready, or
likely to make money. No strategy candidate is active. The former
`20250702-20260702` holdout remains retired, and no replacement holdout is assigned by
this acceptance.
