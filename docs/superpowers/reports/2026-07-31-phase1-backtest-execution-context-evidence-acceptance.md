# Phase 1 Backtest Execution Context Evidence Acceptance Report

**Acceptance date:** 2026-07-31

**Status:** accepted at exact implementation SHAs with one documented Futures
full-Backtest performance-evidence gap; local commits only; no subsequent implementation
slice activated by this report

**Branch:** `xrunmasterx/phase1-complete-development`

**Worktree:**
`C:\Users\dezhengu\orca\workspaces\freqtrade-cn\phase1-complete-development`

**Plan:**
[Phase 1 Backtest Execution Context Evidence](../plans/2026-07-31-phase1-backtest-execution-context-evidence.md)

**Decision:**
[Bounded Backtest execution-context evidence](../decisions/2026-07-31-backtest-execution-context-evidence-boundary.md)

**Preceding evidence gate:**
[Phase 1 Retained DataSnapshot Replay](2026-07-31-phase1-retained-data-snapshot-replay-acceptance.md)

## 1. Exact implementation identity

| Repository | Exact accepted implementation SHA |
|---|---|
| Root | `290fecbe892304bbdb295ee949210268b1ad4e7e` |
| `freqtrade/` backend | `3209d437450fd1cc72903d9cc5ae8225bd7f8fb6` |
| `frequi/` frontend | `17e88f2d6d63c0491b5648cb5597046a1e59fbbd` |
| `freqtrade-strategies/` | `dbd5b0b21cfbf5ee80588d37458ace2467b7f8a4` (unchanged) |

The Root implementation commit records the exact backend and frontend submodule
pointers. This acceptance document is a later documentation-only commit and does not
change the accepted implementation identity.

## 2. Accepted user outcome

The existing authoritative 8083 Freqtrade Backtest journey now records a bounded
execution-context manifest for supported API-2.55 runs. A user comparing a retained-data
baseline with a candidate can separately see whether these three declared components
matched:

- core runtime versions;
- effective simulation configuration; and
- admitted-pair exchange simulation facts.

The result, history, selector, search, and comparison views report the context as same,
different, or unknown independently of DataSnapshot and strategy evidence. The accepted
decision rule is:

> A metric delta remains eligible for later strategy attribution only when the captured
> data, strategy evidence, and execution-context scope are all comparable.

`DIFFERENT` or `UNKNOWN` context means the comparison is confounded. `SAME CAPTURED
SCOPE` means only that the listed component identities matched. It does not prove equal
results, causality, robustness, artifact authenticity, complete reproducibility, Paper
eligibility, contract-trading safety, stable profitability, or future profit.

## 3. Accepted evidence and ownership boundary

### Execution-context manifest

The optional `execution_context_evidence` receipt field is a strict schema-1 manifest. It
contains exact scope literals plus four domain-separated SHA-256 identities:

- `core_runtime_id`;
- `effective_config_id`;
- `exchange_simulation_id`; and
- an aggregate `evidence_id` that binds the three component identities and scopes.

Only these scopes and identities are persisted. Positive allowlists construct component
payloads in memory; the payloads are discarded after hashing. Unknown fields, malformed
types, non-finite numbers, bool-as-number values, excessive pairs or leverage tiers, and
oversized canonical payloads fail closed.

This evidence is self-reported correlation metadata. It is not a signature, attestation,
SBOM, dependency closure, complete Environment Identity, or restoration artifact. The
outer revision ID is bound by the writer, but existing readers do not recompute that outer
identity; this report therefore makes no read-side tamper-resistance claim.

### Strategy Evidence v2

Every newly captured context-bound result uses normative Strategy Evidence v2. V2 owns
the exact allowlisted Freqtrade-resolved execution settings, named hyperopt values,
custom-ROI enablement, and the protection list actually supplied to the engine. The
snapshot is taken after `ft_bot_start`; an enabled `protections` property is evaluated
exactly once and the validated value is reused by `ProtectionManager`.

V1 strategy evidence remains loadable for historical results, but a context-bound receipt
cannot bind V1. Parameter and protection values are depth-, node-, string-, count-, and
byte-bounded. Unknown setting keys, protection methods, and protection keys fail before
artifact publication.

### Engine-owned capture

The CLI and active API background path use the same single-assignment
`seal_execution_context(data)` operation immediately after standard data loading and
before prior-result reuse, strategy callbacks, or indicators. The seal owns the exact
evaluated-pair order, already-loaded exchange facts, the once-resolved proxy currency,
and the proxy-wallet free balance that participates in the real stake clamp.

The implementation adds no exchange request, market reload, optional package scan,
second Exchange, or environment service. Spot records `margin_mode: null`. Futures binds
the narrow liquidation taker rate only for the base and Bitget formulas that consume it;
Binance, Bybit, and Hyperliquid record `null`.

## 4. Admission, compatibility, and publication

API 2.55 advertises `capture_execution_context_evidence`. Updated FreqUI sends the field
automatically only for non-FreqAI revision-bound runs. API 2.54 and older request shapes
omit the property exactly.

V1 admits only static-PairList Spot and Futures Backtests:

- dynamic PairList execution fails with a stable, visible admission error;
- FreqAI and Margin remain outside the v1 evidence claim;
- Futures Cross Margin accepts a scalar wallet or an object containing only the effective
  proxy currency; and
- any wallet that would require mutable ticker conversion fails before `Wallets`
  construction, without calling conversion-rate or ticker APIs.

Requested capture forces a fresh Backtesting instance and prior-cache bypass. Retention
and replay force current context capture and Strategy Evidence v2. Context-bound ordinary
capture, replay without re-retention, and retained replay use ZIP-first publication:
create and verify a temporary archive, replace the final ZIP, then atomically publish
metadata and the latest-result pointer. Fault injection verifies rollback and prior-latest
preservation across archive, replacement, sidecar, pointer, and cleanup failures.

Legacy results and schema-1/schema-2 receipts without valid context evidence remain
loadable and report context `UNKNOWN`. No environment picker, capture checkbox, context
dashboard, restore action, or "reproducible" badge was added.

## 5. Frontend behavior

FreqUI strictly validates schema literals, exact key sets, identity prefixes, digest
lengths, aggregate binding, and the V1/V2/context relationship before treating evidence
as valid. It shows:

- full aggregate and component identities in result detail;
- compact context state in history and result selectors;
- evidence-ID search;
- independent data, strategy, and execution-context cards in comparison;
- runtime/config/exchange component drift;
- replay wording that distinguishes retained rows from current execution context; and
- the static-PairList admission failure without clearing the completed Backtest form.

Same-context wording is deliberately neutral. It says that declared inputs matched, not
that the result is reproducible, causal, robust, safe, promotable, or profitable.

## 6. Resource and performance evidence

The accepted implementation enforces:

- at most 1,000 evaluated pairs;
- at most 50,000 parsed leverage-tier rows;
- at most 16 MiB of combined canonical execution-context component bytes;
- at most 4,096 named strategy parameters and 64 protections;
- recursive strategy-value depth 8 and 16,384 nodes;
- at most 16 KiB per UTF-8 string; and
- at most 1 MiB of canonical strategy-parameter bytes.

After one warm-up, the local five-run synthetic measurements were:

| Builder | Median | Peak Python allocation | Gate |
|---|---:|---:|---:|
| Spot, 1,000 pairs | 33.128 ms | 4,628,206 bytes | <=250 ms and <=64 MiB |
| Futures, 1,000 pairs / 50,000 tiers | 386.186 ms | 24,190,715 bytes | <=750 ms and <=64 MiB |
| Maximum-shape Strategy Evidence v2 | 12.685 ms | 1,877,492 bytes | <=100 ms and <=16 MiB |

The maximum-shape strategy payload accounted for exactly 104,140 canonical bytes in both
the independent accounting path and the produced payload. Adversarial canonicalization
also matched exact JSON byte counts for 2,002 generated payloads.

### Representative full-Backtest overhead

A repository-external stdin harness used the real `Backtesting` constructor, context seal,
strategy indicator calculation, and `Backtesting.backtest()` at the accepted backend SHA.
The representative Spot fixture contained two pairs, 230 five-minute candles per pair,
and five completed trades per run. After one disabled and one enabled warm-up, the harness
alternated five disabled and five enabled runs:

| Spot mode | Five timed samples | Median |
|---|---|---:|
| Capture disabled | 42.7534, 49.7109, 49.0626, 46.6688, 42.2299 ms | 46.6688 ms |
| Capture enabled | 54.1634, 58.0415, 56.7292, 58.5174, 48.3629 ms | 56.7292 ms |

The accepted threshold was `disabled median * 1.10 + 50 ms`, or 101.3357 ms. The enabled
Spot median passed with approximately 10.0604 ms added wall time.

A real Futures setup also loaded funding, mark, and leverage-tier fixtures and produced a
valid execution-context identity. Its single disabled/enabled smoke readings were
63.7525/64.0455 ms, but both runs produced zero trades. No credible trade-producing
Futures fixture combined complete market metadata, matching tiers/funding/mark data, and
the strict context projection without synthesizing exchange facts. This report therefore
does not claim that the planned warm-up plus five-run full-Futures median gate was
completed. The worst-case 1,000-pair/50,000-tier builder measurement above remains valid,
but it is not relabeled as a trade-producing full-Backtest measurement.

## 7. Verification evidence

### Backend

All final checks used backend
`3209d437450fd1cc72903d9cc5ae8225bd7f8fb6`.

| Check | Result |
|---|---:|
| Focused execution-context, Strategy v2, replay-storage, and RPC-schema suite | 122 passed in 7.22 s |
| Targeted resource/security/adversarial selection | 33 passed, 61 deselected in 6.03 s |
| Broad accepted backend selection | 396 passed, 1 deselected, 1 warning in 65.71 s |
| Wider implementation regression selection | 441 passed, 1 deselected, 1 warning in 64.58 s |
| Replay-storage and Strategy-v2 focused selection | 60 passed |
| Ruff over touched optimize/RPC source and tests | passed |
| Parent-to-head and cumulative `git diff --check` | passed |

The deselected path is the optional FreqAI test excluded by the governing command. The
remaining warning is upstream/pre-existing test noise, not a failing context-evidence
assertion.

The final Windows probes exercised real same-file reparse replacement rejection, bounded
latest-pointer reads, cross-process named-mutex contention, release/close failures,
compare-and-swap rollback, strict historical V1/V2 tags, byte-stable Strategy v2 output,
and stable fail-closed error domains. A contended Windows child process returned
`backtest_latest_pointer_lock_failed` after approximately 5.015 seconds and the holder
exited normally.

### Frontend

All final checks used frontend
`17e88f2d6d63c0491b5648cb5597046a1e59fbbd`.

| Check | Result |
|---|---:|
| Focused Vitest revision/localization suite | 28 passed |
| `pnpm typecheck` | passed |
| `pnpm build` | passed |
| Changed-file ESLint | zero errors |
| Mocked Chromium Backtest journeys | 8 passed |
| Mocked installed Microsoft Edge Backtest journeys | 8 passed |

Build retained the known dependency pure-annotation and chunk-size warnings. The narrow
mocked background-job fixture also emits the existing
`TypeError: data is not iterable` console message at `src/stores/ftbot.ts:736`; all
journeys pass and this feature does not modify that store path.

## 8. Orchestrated Gate review

Orca orchestration tracked independent implementation, frontend, backend-contract, and
security/minimality reviews. Review workers changed no files during the final Gates.

| Task | Result |
|---|---|
| `task_3c47b0ac86b6` | Independent frontend Gate PASS; no finding |
| `task_738dd586c0f8` | Implemented and verified the final Windows reparse, bounded-lock, cleanup, and Unicode hardening at backend `3209d437...` |
| `task_abfaab3f246a` | Exact-SHA backend contract Gate PASS; no Blocker, High, or Medium finding; one Low legacy-sidecar cleanup finding |
| `task_cabf2869290e` | Exact-SHA security/robustness/minimality Gate PASS; no Blocker, High, or Medium finding; one Low snapshot-close exception-preservation finding |

The final accepted state has no unresolved Blocker, High, or Medium finding inside this
contract. The review loop closed earlier findings for strict schema tags, exact resource
accounting, secret-bearing unknown fields, property single-read semantics, all-step
rollback, cross-process publication ownership, Windows reparse races, finite lock waits,
cleanup error masking, and lone-surrogate error normalization.

## 9. Residual findings and platform caveats

Two Low findings remain explicit rather than being hidden:

1. The legacy API-2.54-compatible publication branch writes its metadata sidecar before
   acquiring the new bounded latest-pointer lock. An injected lock-acquisition failure can
   therefore leave one orphan `.meta.json`. It preserves the prior latest pointer and
   creates no ZIP. The API-2.55 context-bound transactional path is not affected.
2. If closing the already-open latest-pointer snapshot descriptor itself fails, that
   cleanup error can replace the initiating internal validation exception. Publication
   still fails closed and preserves the stable external snapshot-invalid error domain.

The pre-existing unbound legacy publication path also retains its historical
metadata/latest-before-ZIP behavior. An unrelated legacy archive-body failure can leave a
dangling latest pointer. That compatibility path predates this feature and is not used by
the new context-bound ZIP-first contract.

Native POSIX execution was unavailable on this Windows worker. POSIX nonblocking flock
and timeout behavior was source-audited and covered by deterministic fault injection, but
this report does not claim a native Linux process run. Lexically different Windows path
aliases may also use different named-mutex keys; collision-resistant artifact names and
latest-pointer compare-and-swap remain the authority across those aliases.

The full-Backtest overhead requirement has a credible Spot pass but no trade-producing
Futures five-run median. Closing that evidence gap requires a reusable Futures fixture
whose market precision, limits, contract size, leverage tiers, funding/mark data, and
stable trade-producing strategy all describe the same simulated market. This is an
explicit verification limitation, not evidence that the gate passed or failed.

## 10. Docker and operational boundary

Docker was not available on the coordinator PowerShell `PATH` or the checked common
Docker Desktop CLI location. No current-SHA image build, container start, 8083 browser
journey, service mutation, database mutation, exchange request, Paper runtime, Live
runtime, or order path was executed for this acceptance.

The earlier baseline Docker receipt remains valid only for its own accepted SHAs. This
report does not reuse that receipt as proof that Root `290fecbe...`, backend
`3209d437...`, and frontend `17e88f2d...` were built or run in Docker.

## 11. Historical artifact exposure remains open

The preceding security acceptance found 191 parseable local Backtest ZIPs, including 184
with non-placeholder API-session secrets. This work did not display, copy, rewrite,
delete, quarantine, rotate, or revoke any of them. They remain an operational exposure
until service-specific retention and credential-rotation actions are separately
authorized and completed.

## 12. Acceptance decision and next boundary

Phase 1 Backtest Execution Context Evidence is accepted at the exact implementation SHAs
above with no unresolved Blocker, High, or Medium finding inside its declared boundary.
All accepted implementation commits are local; no remote push or merge is implied by this
report.

No next implementation plan becomes active automatically. The next first-principles
decision is to reassess whether a small revision-bound robustness/holdout evidence slice
solves the next real user problem without introducing an optimizer, ranker, AI daemon, or
promotion engine. Dynamic RuntimeInstance, formal Paper Observation, Experiment UI,
platform cutover, and Live trading remain paused until separately selected and governed.
