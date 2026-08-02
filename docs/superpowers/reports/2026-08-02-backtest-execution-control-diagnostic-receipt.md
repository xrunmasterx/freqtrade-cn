# Phase 1 Backtest Execution Control Diagnostic Receipt

**Status:** Terminal `DIAGNOSTIC_INVALID`; closed without retry and not accepted
for another strategy-candidate spend

**Attempt:** `backtest-control-diagnostic-20260802-b`

**Committed Root:** `50ada14fd0261021c91f6e5ad2173a103b6e6d93`

**Scope:** Control-path evidence only. No result-bearing endpoint, Backtest result,
trade, performance metric, strategy comparison, Runtime, Paper, Live, or deployment
evidence is included.

## Outcome

The one authorized real diagnostic started at
`2026-08-02T07:07:02.402264+00:00` and finalized at
`2026-08-02T07:07:06.593283+00:00`. It created the exact labelled network and
container, then rejected the created-but-not-started container at the frozen container
inspection boundary:

| Field | Value |
|---|---|
| Host verdict | `DIAGNOSTIC_INVALID` |
| Primary code | `container_inspect_failed` |
| Primary error type | `EvidenceError` |
| Container started | No |
| Backtest POST count | 0 |
| Bound job | None |
| Child control receipt | None |
| Abort | Not reached |
| Result access | None |

Because validation failed before `start_container`, the Freqtrade API server never
started and the request was never submitted. The receipt intentionally retains only the
bounded stage code and error type; it does not retain the field-specific validator
message. The exact mismatched container fact therefore cannot be inferred from this
receipt, and this report does not guess whether it was a Docker Desktop representation
difference or an actual configuration mismatch.

This is the sole real attempt. The governing plan does not authorize a retry.

## Frozen evidence

| Artifact or identity | Bytes | SHA-256 / value |
|---|---:|---|
| Preregistration v2 | 5,012 | `582a62ad870cbc6e0fc0cd50bfdcef2092cee9932c3a8004145bbe91807550ed` |
| Temporary `probe.py` | 133,310 | `b107130d888265bdafcfd731e75158e117115765a59b512d0a6db07f0adb1579` |
| Temporary `test_probe.py` | 92,826 | `9adc741f45f0de0d057b2acc3fa8b1be7f0696b4fd323f08687d2e7ef4941f8a` |
| Frozen request | 382 | `5de919af1057b22135d073b4e6f835087554ca61671ec9fdd173070e043d9f8a` |
| Baseline strategy | 6,618 | `fed33eceed8bec65f5c47d1727aa4a18b70f15d064b20000eb653622bb16fe85` |
| Effective configuration | 1,794 | `0685d9f364b9fd208c437b1c5511c20b4ee9d28780a220f24059225cb5a5b37e` |
| Futures 1h data | 595,146 | `fda58d314cbcacd8605d5b4996030b9fb73eb2544ed35b9ef64ffeca6a252369` |
| Mark 1h data | 484,234 | `6e4a742f05a36df2a0894583463ae7904c56596d824ac5a7c444be7dbce9c86f` |
| Funding-rate data | 32,026 | `2a49b31fc35be0e3a26f4199fd773998a811ae19dd9e82a181c2fbfdf1c8fe94` |
| Leverage tiers | 13,231,201 | `fbfb3a0b96cd713a4050a8393c912a114634f953c69cc56440623f457ba2016e` |
| Immutable image | — | `sha256:fb7bc20017bae79af1f7533c8b2018098bb627306d9c2286fb9b1501551fe03c` |
| Docker executable | 43,095,472 | `c11b843b727ea76e6c63b393bccb73d957b6fcc12ba871c8265699e3a12e933c` |
| Final host control receipt | 4,436 | `563dfe95534c662ab2e129b6828d09fee87251f300351a6a759a7356478a2da6` |

The final receipt is external at
`C:\Users\dezhengu\AppData\Local\Temp\freqtrade-cn-backtest-control-final-3f0eb24.json`.
It binds the full preregistration, registered identities, Docker identities, host phase
offsets, cleanup, quarantine, secret disposal, child-control absence, and explicit
evidence exclusions.

## Gate and deterministic verification

The independent source/design re-Gate returned `PASS` with `P0 = 0`,
`P1 = 0`, and one acknowledged non-blocking `P2`: ordinary Docker lifecycle
stdout/stderr temporary files are capped after a command returns, rather than while the
bounded command is running. Long child output is discarded.

The originally dispatched Orca provider workers became unavailable before completing the
review. A separate continuation session therefore performed the complete read-only
review and manually reconciled Orca task `task_99f2564296ed` as an explicit recovery;
it did not fabricate a provider `worker_done`. The verified checks were:

- all 11 focused P1 tests passed;
- all 37 tests passed;
- all 26 legacy-only tests passed;
- isolated `py_compile` passed;
- all frozen hashes stayed unchanged;
- Root and all three submodules stayed clean; and
- planned run and quarantine paths were absent before the real attempt.

The canonical preregistration then passed the probe's real Docker-backed `preflight`
with exit code 0 before the one `host` invocation.

The independently dispatched final-documentation Gate did not run: its Claude provider
exhausted 10 of 10 service retries and returned idle before file access, without
`worker_done`. Orca task `task_0ba16d0aa73c` is recorded as failed with that
provenance. A manual closeout fact audit rechecked the complete four-file diff, final
control receipt, hashes, links, status language, and prohibited inferences and found
`P0 = 0` and `P1 = 0`; it is not represented as an independent Gate.

## Owned-resource finalization

| Boundary | Final evidence |
|---|---|
| Container | ID `3ae61a6b04e693c7ee0a4a81d28a0ed7ae5c5f2597c9fa30c6c23c3590710626`; removed; exact name absent |
| Network | ID `b0f0919ae1fb522ec764885016a56b36ba4aabefba240537fcc6eec86122b30d`; removed; exact name absent |
| Cleanup | `succeeded = true`; no cleanup errors |
| Quarantine | `succeeded = true` |
| Secret disposal | `succeeded = true`; exact secret directory absent |
| Original run root | Absent after atomic quarantine move |

The untouched attempt tree is quarantined at
`C:\Users\dezhengu\AppData\Local\Temp\freqtrade-cn-backtest-control-quarantine-3f0eb24`.
Only its existence was checked. Its contents were not enumerated, opened, changed, or
deleted. The older spent-attempt quarantine was likewise not touched.

## Acceptance result

| Criterion | Result |
|---|---|
| Plan and exact implementation identities committed before the real attempt | Satisfied |
| Deterministic tests green | Satisfied |
| One fresh diagnostic and exactly one POST | **Not satisfied:** the sole attempt stopped before start/POST |
| Durable receipt with a bounded, non-catch-all failure | Satisfied |
| No result/performance access; historical quarantine untouched | Satisfied |
| Owned cleanup, quarantine, and secret disposal confirmed | Satisfied |
| Root and submodules clean after the diagnostic | Satisfied before closeout documentation |
| Final documentation Gate | **Not satisfied:** provider unavailable before file access; manual fact audit found `P0 = 0`, `P1 = 0` but was not independent |

The diagnostic is therefore closed but not accepted: the exact-one-POST criterion and
the independent final-documentation Gate were not satisfied. It is not proof that the
existing Backtest/background-job control contract works, and it also does not prove that
the API contract is insufficient, because execution never reached the API.

## Follow-up boundary

No probe promotion, product change, new strategy candidate, or automatic retry follows
from this receipt. If work is explicitly resumed later, a new plan must first decide how
to reproduce the created-container inspection facts without spending another Backtest,
and how to retain a sanitized field-specific validation code. It must not inspect either
quarantine or infer a profitability conclusion from this control-path failure.
