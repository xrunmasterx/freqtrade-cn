# Phase 1 Backtest Execution Control Diagnostic

**Status:** Active; design frozen, implementation not started

**Design Gate:** PASS; P0 = 0, P1 = 0, P2 = 0

**Scope:** Root-only research-control probe and one isolated, baseline-only local
diagnostic; no backend, frontend, strategy, Backtest-engine, API, market-data, Runtime,
Paper, Live, deployment, optimizer, or AI-worker change

## User problem

The latest bounded strategy study reached its one permitted Backtest POST, spent its
lease, and later exposed only `CONTROLLER_FAILED`. The historical receipt proves neither
the precise inner exception nor whether the backend job completed, failed, or continued
after the controller stopped. That attempt is terminal and must not be retried or opened.

Before another strategy candidate can spend a development interval, the research loop
needs a smaller and independently testable guarantee: a caller must be able to prove
that one standard Freqtrade Backtest was acknowledged, bind its existing background job,
observe only bounded control state, stop waiting at a declared deadline, request abort
once, and confirm termination or clean up only its owned isolation boundary.

## First-principles decision

Freqtrade already owns Backtest calculation and already exposes the required control
primitives:

- `POST /api/v1/backtest` starts the standard asynchronous Backtest;
- `GET /api/v1/background` and `GET /api/v1/background/{job_id}` expose bounded job
  identity, status, progress, and error state without returning the Backtest result; and
- `GET /api/v1/backtest/abort` acknowledges an abort request.

The demonstrated gap is therefore orchestration observability, not a missing Backtest
engine or job system. The first diagnostic will use those existing contracts from one
fresh dedicated container. It will not add a scheduler, generic workflow platform, new
endpoint, POST response field, persistence model, or UI. An additive `job_id` in the POST
response is considered only if a real isolated diagnostic proves that the existing
background-job discovery contract cannot bind the new job safely.

## Assumptions and fixed identities

1. The diagnostic container is fresh and dedicated to this one request. Any pre-existing
   Backtest-category background job is a preflight failure.
2. The request is the unchanged accepted `VolatilitySystem` baseline workload, except
   for a new diagnostic Experiment ID. It is not a strategy candidate and creates no
   comparison.
3. The standard Backtest request is submitted exactly once. A lost, malformed, or
   ambiguous acknowledgement does not authorize another POST.
4. Background status `pending` with `running == false` is startup state, not completion.
   The worker writes `success` or `failed` immediately before clearing its running flag,
   so terminal control evidence requires the bound job to report one of those statuses
   and `running == false` in the same sample.
5. Abort acknowledgement is not proof that cooperative Backtest execution has stopped.
   The bound background job must become terminal during the finite abort grace period;
   otherwise termination remains unconfirmed and the owned container is removed.
6. No result endpoint, Backtest ZIP, metadata, pointer, log, trade, metric, or strategy
   performance field may be opened or interpreted. The state/output directory is moved
   intact to a recoverable external quarantine after the container stops.
7. The immutable image remains
   `sha256:fb7bc20017bae79af1f7533c8b2018098bb627306d9c2286fb9b1501551fe03c`.
8. The exact baseline strategy is 6,618 bytes with SHA-256
   `fed33eceed8bec65f5c47d1727aa4a18b70f15d064b20000eb653622bb16fe85`.
9. The exact effective configuration is 1,794 bytes with SHA-256
   `0685d9f364b9fd208c437b1c5511c20b4ee9d28780a220f24059225cb5a5b37e`.
10. The four previously admitted local OKX inputs remain byte-identical: Futures 1h
    `fda58d314cbcacd8605d5b4996030b9fb73eb2544ed35b9ef64ffeca6a252369`,
    Mark 1h `6e4a742f05a36df2a0894583463ae7904c56596d824ac5a7c444be7dbce9c86f`,
    Funding Rate
    `2a49b31fc35be0e3a26f4199fd773998a811ae19dd9e82a181c2fbfdf1c8fe94`,
    and OKX leverage tiers
    `fbfb3a0b96cd713a4050a8393c912a114634f953c69cc56440623f457ba2016e`.
11. The request keeps `VolatilitySystem`, `1h`, `20240701-20250701`, one
    `BTC/USDT:USDT` pair, `backtest_cache = none`, and the accepted evidence-capture and
    retained-snapshot switches. Only `experiment_id` changes to
    `backtest-control-diagnostic-20260802-b`.

The committed historical bounded-true-range receipt is immutable and is only the source
of already admitted baseline/configuration identities. Its controller and request bytes
are not edited or executed as a retry.

## Bounded control protocol

The diagnostic probe is a temporary, external, non-product program whose exact bytes and
SHA-256 are recorded before execution. It uses only the Python standard library and an
injectable transport/clock so its state machine can be tested without Docker or market
work. The following resource bounds are fixed protocol values, not implementation
defaults:

| Boundary | Fixed value |
|---|---:|
| host identity preflight window | 120 seconds |
| readiness window before POST | 60 seconds |
| readiness poll interval | 250 milliseconds |
| request/discovery/poll HTTP timeout | at most 5 seconds and never beyond the current monotonic phase deadline |
| request or response body | 65,536 bytes; read 65,537 and reject overflow |
| new-job discovery window | 10 seconds inside the 7,200-second execution deadline |
| discovery poll interval | 250 milliseconds |
| steady-state poll interval | 5 seconds |
| transient GET failures | at most 3 total after POST; the fourth is a primary control failure |
| persisted control samples | at most 512 |
| one sanitized error value | at most 512 UTF-8 bytes after redaction |
| progress and final control receipt | at most 1,048,576 bytes each |
| abort grace | 120 seconds |
| one Docker image/network/container create, inspect, start, or remove command | at most 30 seconds |
| host watchdog around the complete probe subprocess | 7,800 seconds |

Every call computes `min(5 seconds, remaining phase time)` immediately before opening
the request; no call begins when no time remains. The POST is never retried and does not
consume the transient-GET budget. A change-only sample is retained when phase, status,
running state, progress-task description, or integer five-percentage-point progress
bucket changes. After 512 samples, the probe retains the first sample, latest terminal or
failure sample, and an explicit truncation count within the same 512-entry ceiling.
The 7,800-second host watchdog covers readiness, the 7,200-second execution budget, the
120-second abort grace, and bounded return to host cleanup. If it fires, the host still
enters the same unconditional cleanup path; it does not authorize another POST.

1. Verify the exact image, baseline, configuration, and four data-file hashes before any
   server start.
2. Create one attempt-labelled network and start one identically labelled, read-only,
   capability-dropped container with only the declared read-only inputs, separate
   read-write state and control-output directories, loopback API, and ephemeral secret
   files. Exact names and labels are frozen in the preregistration evidence before start.
3. Wait for `/ping`, then snapshot `/background`. Require zero Backtest-category jobs.
4. Start the end-to-end monotonic deadline immediately before the sole POST. Require HTTP
   200 and a JSON object whose `status` is `running`.
5. Discover exactly one new Backtest-category job and bind its `job_id`. Zero or multiple
   new matching jobs after the bounded discovery window is an ambiguous failure.
6. Poll only `/background/{job_id}` every five seconds. Persist timestamped, bounded,
   allowlisted control samples when phase, status, running state, progress value, progress
   task, or sanitized error changes. Never call `GET /backtest` after submission.
7. Treat `success` plus `running == false` as control success and `failed` plus
   `running == false` as control failure. A terminal-looking status with `running == true`
   remains non-terminal until a later sample. Neither outcome says anything about
   profitability or strategy quality.
8. Enforce a 7,200-second end-to-end execution deadline. On deadline or a terminal
   control failure that leaves execution ownership uncertain, call the existing abort
   route exactly once. Poll the bound job for at most 120 additional seconds, with each
   abort or poll call capped by the remaining grace time.
9. Enter one unconditional host `finally` cleanup on every success, failure, exception,
   or interruption path. Before acting, inspect exact names and require the frozen attempt
   label; a name/label mismatch is a cleanup failure and is never removed. Force-remove
   the exact owned container when it still exists, then remove the exact owned network
   when it still exists, and confirm both are absent. Cleanup is attempted even when
   server start, readiness, POST, discovery, polling, or abort failed.
10. Still inside cleanup, move the untouched state/output directory to its preregistered
    recoverable quarantine without enumerating or opening contents, then dispose of the
    three ephemeral secret files. Record move/disposal failures separately and do not
    hide the primary diagnostic outcome.
11. Only after container/network absence, quarantine, and secret disposal have been
    attempted, atomically finalize one capped control receipt containing identities, UTC
    and monotonic-relative timestamps, POST count, bound job ID, allowlisted samples,
    primary outcome, abort acknowledgement, termination confirmation, quarantine outcome,
    secret-disposal outcome, cleanup outcome, and explicit evidence exclusions. A crash
    before that ordering completes leaves only the bounded progress receipt and cannot be
    reported as `RELIABILITY_PASS`.

HTTP bodies are capped before JSON parsing. Unknown fields are discarded. Sanitization
replaces the exact three generated secret values, the exact Basic-auth token derived from
`research:<api_password>`, and case-insensitive `authorization`, `api_password`,
`jwt_secret_key`, and `ws_token` assignment values with `[REDACTED]`; it collapses line
breaks and then applies the 512-byte UTF-8 cap. Raw response bodies and credentials are
never persisted.

## Diagnostic verdicts

- `RELIABILITY_PASS`: one POST was acknowledged, exactly one job was bound, that job
  reached `success` inside the deadline, cleanup was confirmed, and no result content was
  read.
- `RELIABILITY_FAIL`: a control-contract, backend, deadline, abort, termination, or
  cleanup failure occurred. The receipt records the primary and cleanup outcomes without
  converting this into a strategy-performance verdict.
- `DIAGNOSTIC_INVALID`: identities, isolation, one-POST enforcement, evidence bounds, or
  receipt integrity could not be proven. No retry is authorized by this plan.

These verdicts do not reuse the strategy-study meanings `DEVELOPMENT-SURVIVOR`,
`REJECTED`, or `INVALID` and cannot promote a strategy to Paper.

## RED test requirements

Before the real workload, deterministic tests must fail against the absent probe and then
pass for the minimal implementation:

1. exact HTTP 200/running acknowledgement produces one POST; malformed, lost, or rejected
   acknowledgement never reposts;
2. a sole new Backtest job is bound; zero, multiple, or pre-existing Backtest jobs fail
   closed;
3. `pending` plus `running == false` remains non-terminal; `success` plus
   `running == true` remains non-terminal until `success` plus `running == false`, and the
   equivalent `failed`-true to `failed`-false sequence is covered;
4. terminal failure preserves a capped, redacted control error without a result body;
5. fake-clock deadline triggers one abort, treats its response as acknowledgement only,
   then distinguishes confirmed terminal stop from expired grace;
6. transient poll failures consume a bounded budget without reposting;
7. samples and final receipt contain only the allowlist, remain size-bounded, and retain
   primary and cleanup outcomes separately; and
8. the client never requests the result-bearing `GET /backtest` route; and
9. success, pre-POST failure, POST ambiguity, interrupt, deadline, abort-grace expiry,
   quarantine failure, secret-disposal failure, and name/label mismatch all enter the
   unconditional cleanup path, while final-receipt creation occurs only after cleanup,
   quarantine, and secret-disposal attempts.

## Acceptance criteria

1. The active plan is committed before any real POST, and the external probe/test hashes
   plus exact diagnostic request hash are recorded before execution.
2. All deterministic probe tests pass without Docker, market data, or strategy execution.
3. One fresh isolated baseline diagnostic produces one durable control receipt and exactly
   one POST.
4. The receipt proves either `RELIABILITY_PASS` or a specific bounded failure; literal
   catch-all output alone is not acceptable.
5. No result-bearing endpoint or output artifact is opened, no trade/performance metric is
   reported, and the old quarantined attempt remains untouched.
6. Owned container/network cleanup and external state-output quarantine are confirmed.
7. Root, backend, frontend, and strategy repositories are clean after the diagnostic.
8. Independent design, implementation/control-evidence, and final documentation Gates
   report no unresolved P0/P1 findings.

## Decision after the diagnostic

- A diagnostic verdict never promotes the temporary probe. First publish the bounded
  control evidence and close this diagnostic. A separate post-evidence design and
  implementation Gate must explicitly authorize either a maintained Root tool or a
  product-code change.
- If that later Gate is justified by a passing existing API contract, it may select a
  small candidate-agnostic Root tool with focused tests. Future study receipts would pin
  the tool's exact hash and declare their own identities, deadline, retry policy, and
  result protocol.
- If the existing API contract cannot bind the job safely in the fresh dedicated
  container, the later Gate may review the narrowest additive compatibility change,
  preferably a `job_id` in the existing POST response. It must not create a new endpoint
  or job system.
- Do not select or run another strategy candidate until this reliability slice is
  accepted.

## Explicit non-goals

- no retry or inspection of `dev-bc-56b60c7` or its quarantine;
- no candidate, B/C comparison, holdout, Lookahead, Recursive, Hyperopt, ranking, or
  optimization work;
- no result parsing, profit, drawdown, trade-count, or future-return claim;
- no backend/FreqUI change unless this diagnostic proves the existing contract
  insufficient;
- no generic scheduler, workflow engine, distributed queue, Experiment CRUD, or new
  persistence model;
- no BotRelease, RuntimeInstance, Paper Observation, Live trading, exchange write, push,
  merge, release, or deployment.

## Planned verification

```powershell
python -m unittest <external-probe-test-module> -v
git diff --check
git status --short --branch
git -C freqtrade status --short --branch
git -C frequi status --short --branch
git -C freqtrade-strategies status --short --branch
```

The exact Docker invocation, probe/test paths and hashes, diagnostic request hash, control
receipt hash, cleanup result, and quarantine path are acceptance evidence, not assumptions,
and will be recorded only after they exist.
