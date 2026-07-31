# Phase 1 Recursive Analysis Truthfulness Repair Acceptance Report

**Acceptance date:** 2026-08-01

**Status:** accepted at exact implementation SHAs after a development-only rerun; local
commits only; an earlier acceptance request contaminated and retired the former sealed
holdout with final-row indicator inspection; no signals, trades, performance, Paper,
Live, exchange-write, or remote state was changed

**Branch:** `xrunmasterx/phase1-complete-development`

**Worktree:**
`C:\Users\dezhengu\orca\workspaces\freqtrade-cn\phase1-complete-development`

**Plan:**
[Phase 1 Recursive Analysis Truthfulness Repair](../plans/2026-08-01-recursive-analysis-truthfulness-repair.md)

**Triggering evidence:**
[VolatilitySystem Breakout-Episode Risk Calibration Rejection](2026-08-01-volatility-breakout-episode-risk-calibration-rejection.md)

## 1. Exact implementation identity

| Repository | Exact accepted implementation SHA |
|---|---|
| Root | `bc51d415bdb70e2903ef5367994c3f08ba8fac42` |
| `freqtrade/` backend | `53fb46d0322a33b41f5ce5ca2d0749c40f379831` |
| `frequi/` frontend | `8a26426fb5520b9673c66c079bbe1fff1af23d01` |
| `freqtrade-strategies/` | `dec5adb77f03b0c33ccfbc036ff0a3e57f7d571d` (unchanged) |

The Root implementation commit pins the exact backend and frontend submodule revisions
and updates the plan/status documents from design to implemented. This acceptance report
is a later documentation-only commit and does not replace the accepted implementation
identity.

The accepted backend history contains the functional commit
`d6b60e0908d75d5d4764eb19d0f97daf0977d533` followed by the evidence-scope correction
in the accepted backend head. The accepted frontend history contains the functional
commit `6883e43ae4a86037bfcbebbedacd27a210dc6090` followed by the permanent-boundary copy
correction in the accepted frontend head.

## 2. Accepted user outcome

The existing Freqtrade Recursive Analysis route now presents only the evidence that the
run actually computes:

- every materialized startup-candle profile is compared independently at the run's
  final analyzed candle; an earlier exact match no longer stops later profiles;
- both empty and non-empty results permanently identify all tested profiles;
- `strategy_scc` is labeled as the strategy-declared startup-candle count, not as a
  recommendation produced by the analysis;
- an empty sparse result is neutral information, not a green strategy-level success;
- non-empty results are described as final-candle indicator differences;
- `-` means that a profile was evaluated and that indicator had no reported difference
  at the final row; it does not mean skipped or unknown; and
- the result always says that it does not evaluate historical signals, orders, trades,
  Paper or Live behavior, or profitability.

The existing route, form, background job, request, response, table, and Freqtrade
analysis authority remain in place. The user gets more complete and less misleading
evidence without learning a new workflow.

## 3. Claim and implementation boundary

The backend change is one control-flow correction in
`RecursiveAnalysis.analyze_indicators()`: a profile with no final-row variance logs its
bounded result and continues instead of breaking out of the profile loop. A focused
regression fixes the decisive case where profile A matches and later profile B differs.
Backend documentation now states that the command compares indicators at one final row
for every tested profile and cannot establish historical signal stability.

The frontend change is confined to the existing result component, English and Chinese
copy, and focused component, locale, and existing-journey tests. It adds no API field,
schema, route, page, store, persistence, receipt, feature flag, or user option.

This acceptance does not establish any of the following:

- historical entry/exit signal equality over the timerange;
- restart stability, warm-state equivalence, state restoration, or full-window parity;
- correctness of orders, trades, Backtest metrics, Paper behavior, or Live behavior;
- DataSnapshot, Strategy Evidence, Execution Context, or complete environment identity;
- strategy quality, robustness, promotion eligibility, or current/future profitability;
- a BotRelease, dynamic RuntimeInstance, Experiment-to-Paper workflow, scheduler, AI
  daemon, or self-optimization loop.

No number of final-candle Recursive Analysis runs may be accumulated into a formal
full-window signal-stability PASS. A future strategy intended for a restartable Runtime,
Paper, or Live path still needs the separately governed real-strategy full-window Gate
or an accepted state-restoration contract.

## 4. Automated verification

All final checks used the exact backend and frontend SHAs in Section 1.

| Check | Result |
|---|---:|
| Backend `tests/optimize/test_recursive_analysis.py` | 9 passed |
| Backend Ruff check | passed |
| Backend Ruff format check | passed |
| Focused frontend component and locale Vitest | 2 files, 22 passed |
| Full frontend Vitest | 44 files, 276 passed |
| Frontend typecheck | passed |
| Frontend production build | passed |
| Changed-file ESLint | zero errors; four pre-existing locale formatting warnings |
| Targeted changed-file Prettier check | passed |
| Existing mocked Chromium analysis journey | 3 passed |
| Root/backend/frontend `git diff --check` | passed |

The full Vitest command exited successfully after reporting all 276 tests passed, while
still printing the existing Happy DOM fetch-abort/fork `EPROTO` teardown noise. The
mocked Playwright analysis journey still prints the existing `recoverBgJobs` mock console
noise. Neither warning changed the successful command result, and neither was expanded
into unrelated toolchain work.

## 5. Orchestrated independent Gate

Orca orchestration used three read-only reviewers for backend correctness, frontend user
truthfulness, and integrated product/evidence boundaries. Review workers did not open
holdout data and made no repository changes.

| Review task | Dispatch | Result |
|---|---|---|
| `task_19a5c78228ac` | `ctx_c40321dcbedc` | backend PASS; P0/P1/P2 0 |
| `task_2d29d8ba78f3` | `ctx_698a97a97832` | found one P1: the evidence boundary was not permanently visible |
| `task_11be4db78133` | `ctx_e8f08ea30819` | confirmed the P1 and one P2 documentation/log-scope wording issue |
| `task_ceb4c61d3338` | `ctx_378db7f795b3` | frontend re-Gate PASS; P0/P1/P2 0 |
| `task_37fea427604d` | `ctx_83e005cc91d1` | integrated re-Gate PASS; P0/P1/P2 0 |

The repair loop made the one-final-row limitation permanently visible in both result
states, explicitly excluded signals/orders/trades/Paper/Live/profit, and aligned backend
documentation and logging with the same scope before the final PASS.

The first final documentation Gate then found a separate P0 governance error in the
acceptance procedure itself: its timerange crossed the frozen holdout boundary while the
draft report still called that holdout unopened. The Gate stopped the documentation
commit. Sections 6-9 record the irreversible impact, corrected development-only rerun,
and cleanup.

## 6. Holdout governance incident

The earliest known breach was preparatory API job
`08ce0661-ffc0-44ee-ae85-cc566c189db1` on the first implementation image, before the
final evidence-boundary correction and final image build. It used timerange
`20250101-20250801` and returned the same two final-row indicator entries shown below.
That preparatory image was not retained as formal acceptance identity, but the observed
result was sufficient to open the protected domain.

The later exact-container API and UI acceptance repeated timerange
`20250101-20250801`. The frozen strategy-research authority defined
`20250702-20260702` as sealed against strategy indicator, signal, trade, performance, or
result inspection until an authorized spend. The acceptance request therefore selected
approximately 2025-07-02 through 2025-07-31 from that reserved domain and displayed
final-row indicator results.

Exact-image API job `f3345a9b-8d6a-45ac-8118-8ebc04b78023` repeated those two final-row
indicator entries for profiles 299, 499, and 999:

| Indicator | 299 ratio | 499 ratio | 999 ratio |
|---|---:|---:|---:|
| `atr` | `-0.000252796524` | `-1.724418E-06` | `2E-12` |
| `resample_180_atr` | `-0.000252796524` | `-1.724418E-06` | `2E-12` |

A real browser also observed the same bounded result. This was not a signal scan,
Backtest, trade, performance metric, Paper run, Live run, or authorized candidate
holdout spend. It nevertheless met the frozen definition of opening indicator/result
evidence, so deletion or a later rerun cannot restore the window's unseen state.

The governance decision is therefore:

- retire the entire former `20250702-20260702` window from any future claim of fresh
  candidate holdout validation;
- preserve the Breakout rejection report's historical statement as true for that study
  at its decision time, while current status authorities record the later contamination;
- use none of the overlapping result as candidate research, ranking, promotion, Paper,
  Live, or profitability evidence;
- assign no replacement holdout now; any future candidate must preregister a window not
  previously used for strategy indicator, signal, trade, or metric inspection; and
- rerun product acceptance on the already viewed development domain.

The incident was found before this documentation-only acceptance commit. No strategy
candidate was active, and no source or parameter decision was made from the exposed
indicator values.

An independent incident Gate then found that the first incident draft began with the
later `f3345a9b-...` exact-image run and omitted the earlier `08ce0661-...` preparatory
run. The chronology above was corrected. The final documentation Gate and the independent
holdout-incident Gate both passed with P0/P1/P2 equal to zero.

## 7. Corrected exact Docker and API acceptance

The final production backend/frontend commits were built into and accepted from image:

```text
tag: freqtrade-cn:truthfulness-bc51d41
image ID: sha256:b6e3d7ddc1e30fd6f7786c40a37dd208306e443bed75eb4a8b8c17ae53941ebc
platform: linux/amd64
```

The image was built after the final backend and frontend commits. The Root commit was
then created only to pin those exact submodule pointers and update Markdown status; it
did not change any Docker runtime input. The exact Root tag was applied before formal
acceptance. The immutable image ID, not the movable tag, is the image authority.

The corrected isolated acceptance container used:

- container ID
  `6611b4733800050a29048ab9c6ee5f977a456f0db36ee55bd25e6ec046839d36`;
- host endpoint `http://127.0.0.1:18086` mapped to container port 8080;
- runtime user `1000:1000`, init enabled, all Linux capabilities dropped, and
  `no-new-privileges:true`;
- a new writable temporary state root;
- read-only local market data, strategy, operational config, and three API secret
  mounts; and
- no trading command, trading database, Paper process, Live process, or order action.

The service returned `{"status":"pong"}` with zero restarts. Authentication values were
read only into process memory and were not printed, copied into the repository, or
included in the acceptance report.

The corrected formal API request ended at the frozen development boundary, one calendar
day before the former holdout began:

```json
{
  "strategy": "VolatilitySystem",
  "timeframe": "1h",
  "timerange": "20250101-20250701",
  "startup_candle": [299, 499, 999]
}
```

Background job `d9160171-a7b2-410b-8eb9-55c5000c1c52` ended successfully. The exact
development-only bounded result was:

| Indicator | 299 ratio | 499 ratio | 999 ratio |
|---|---:|---:|---:|
| `atr` | `-0.000209106379` | `6.3196E-07` | `8E-12` |
| `resample_180_atr` | `-0.000209106379` | `6.3196E-07` | `8E-12` |

The response also reported `strategy_scc=499` and exactly the tested profile list
`[299, 499, 999]`. Runtime logs recorded calculations for 299, 499, and 999 in sequence;
the later profile was not skipped.

The ratios above are sparse reported differences at one final row, not performance
returns. FreqUI formats them as approximately `-0.021%`, `0.000%`, and `0.000%` at
three decimal places. A displayed rounded zero in an existing result cell is still a
reported sparse difference; only `-` carries the documented no-reported-difference
meaning.

## 8. Corrected exact real-browser acceptance

A headless branded-Chrome Playwright session authenticated against the corrected exact
isolated container and used the visible FreqUI controls. Its start response recorded UI
job `642bbccf-6bbb-4eb5-a7b2-f36db6033d76`, and the captured POST body exactly matched
the development-only JSON in Section 7. The browser then observed:

- the `/recursive_analysis` result page;
- `VolatilitySystem`, timeframe `1h`, and timerange `20250101-20250701`;
- strategy-declared startup count `499`;
- tested profiles `299, 499, 999` in both the result summary and table columns;
- a warning that exactly two indicators had reported differences at the final analyzed
  candle;
- table rows for `atr` and `resample_180_atr`;
- the permanent bilingual one-final-candle indicator-only scope and explicit exclusions;
- the `-` meaning; and
- no `Recommended startup candle` or general `No recursive issues` claim.

During the earlier overlapping run, the first browser assertion reached the completed
result but expected a pure-English boundary string. The product correctly rendered its
configured bilingual English/Chinese text, so only the read-only assertion was corrected.
The corrected development-only journey used the proper bilingual assertion from the
start and passed without a product change.

An earlier preparatory attempt to use Orca's embedded browser bridge timed out while the
Orca runtime connection briefly closed; the service itself stayed healthy. Exact final
acceptance therefore used the repository's installed Playwright/Chrome path directly.
The passing screenshot was visually inspected for layout and content, then deleted with
the other temporary acceptance artifacts instead of being committed as a binary.

## 9. Cleanup and acceptance decision

After evidence collection:

- the preparatory `08ce0661-...` run's transient container and temporary state had
  already been removed before exact-image acceptance; its container ID was not retained
  as formal evidence;
- both the overlapping container
  `c632c18b14b201273d6a6ce1e8569172d32f1ca198f7a53d1e120f82313cb7af` and corrected
  container `6611b4733800050a29048ab9c6ee5f977a456f0db36ee55bd25e6ec046839d36`
  were stopped and removed;
- the later overlapping and corrected dedicated state, log, and screenshot directories
  were resolved under the Windows temporary directory and removed, and no dedicated
  preparatory acceptance directory remains;
- the intermediate `truthfulness-candidate` image tag was removed; and
- the exact `freqtrade-cn:truthfulness-bc51d41` tag and immutable image ID were retained
  as the only acceptance image reference.

Phase 1 Recursive Analysis Truthfulness Repair is accepted at the exact implementation
SHAs above with no unresolved P0, P1, or P2 finding inside its declared boundary. The
acceptance is local-only; no remote push, merge, release, or deployment is implied.

No strategy candidate is active. The former `20250702-20260702` holdout is retired, no
replacement window is assigned, and no performance, Paper, or Live stage is authorized
by this repair. The next implementation must be selected as a separate bounded user-value
decision; this supporting diagnostic does not automatically activate a generic
full-window engine, optimizer, AI daemon, dynamic Runtime, or any paused platform
roadmap.
