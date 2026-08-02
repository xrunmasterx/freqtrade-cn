# VolatilitySystem Bounded True-Range Development Screen — INVALID

**Status:** Final; study closed without retry

**Decision date:** 2026-08-02

**Preregistered protocol:**
[VolatilitySystem Bounded True-Range Episode Development Screen](../plans/2026-08-01-volatility-bounded-true-range-episode-screen.md)

**Frozen pre-performance evidence:**
[VolatilitySystem Bounded True-Range Research Receipt](2026-08-01-volatility-bounded-true-range-research-receipt.md)

## Decision

Classify the bounded true-range development study as protocol `INVALID` for
completeness/evidence failure and close it without retry.

The single permitted attempt `dev-bc-56b60c7` ran against clean Root
`56b60c7a42ee9190830e6dd7843b85ee5c0a8ca9` for 3,607.2 seconds. Its only surfaced
controller output was `CONTROLLER_FAILED`. That token is the controller's literal failure
output, not the study classification. The immutable spent lease proves the development
attempt was consumed; the protocol does not permit another attempt.

This is not a finding about candidate performance. No B result was opened, C never ran,
and no comparison or metric was validated or inspected.

## Control-only evidence

The review used only named lifecycle/control files and did not enumerate or open any B
output, ZIP, metadata, pointer, log, trade, or metric.

| Fact | Observation |
|---|---|
| Executed Root | `56b60c7a42ee9190830e6dd7843b85ee5c0a8ca9` |
| Attempt | `dev-bc-56b60c7` |
| Controller binding | 64,085 bytes; SHA-256 `03fd6ef62155a977c9a3ccf493f3e05c97c07894ce24a9e0c9ce1e00d3b49012` |
| Canonical runtime receipt | 1,509 bytes; SHA-256 `7941da008c46ae1fdb3654f65e18e4769f1bb29455590ee882100438ab28d348` |
| Observed wall time | 3,607.2 seconds |
| Literal controller output | `CONTROLLER_FAILED` |
| Spent lease | Present; 74 bytes; SHA-256 `16085bd379bdcf629ff504c12765de5194307994c683e99e351de33153ee04f1` |
| Run state | Present |
| B request | Present |
| C request | Absent |
| Validator manifest | Absent |
| Validator report | Absent |
| Attempt containers/network after failure | Absent |

The spent lease was created at `2026-08-01T23:27:03.1405512Z`. The control state was
checked after the failed invocation at `2026-08-02T00:30:00.1816831Z`
(`2026-08-02T08:30:00+08:00`, Asia/Shanghai).

## Failure boundary and root-cause limit

The frozen [controller evidence](../receipts/2026-08-01-volatility-bounded-true-range/bytes/controller.py.txt)
writes the spent lease immediately before B's result POST. It seals B and binds the C
request only after that POST succeeds; the host sequence is preflight, network, B, C,
then validator. The present B request and spent lease, together with the absent C request,
therefore locate the stop inside the B POST boundary before B sealing and before C.

The container-side B POST waits up to 3,600 seconds, while its host subprocess allowance
is 3,700 seconds. The observed 3,607.2-second duration is strongly consistent with the
inner B POST deadline. The controller exposes only `CONTROLLER_FAILED` and suppresses the
inner exception, however, so this report does not claim a more specific infrastructure
root cause.

Whether the B process created transient internal result bytes is deliberately unknown.
None were listed, opened, validated, or used for a strategy conclusion.

## Why the class is INVALID

The protocol classifies outcomes in this order: `INVALID` for identity, data,
implementation, completeness, evidence, or arithmetic failure; `INSUFFICIENT` for an
unmet observation floor; `REJECTED` for a parity, mechanism, safety, performance, or risk
failure; then `DEVELOPMENT-SURVIVOR` only after every preceding Gate passes.

Required C and validator evidence does not exist. The atomic B-then-C comparison is
therefore incomplete and cannot be validated, which is a terminal completeness/evidence
failure:

- it is not `INSUFFICIENT`, because no validated comparison reached an observation-floor
  decision;
- it is not performance `REJECTED`, because no performance, risk, mechanism, parity, or
  safety result was validated or inspected;
- it is not a survivor, and the spent lease forbids retrying or repairing this attempt.

An independent read-only classification Gate returned `PASS`, `P0=0`, `P1=0`, and
`P2=0` for this decision and claim boundary.

## Closed scope and cleanup

- C never ran.
- Lookahead Analysis and Recursive Analysis never ran.
- Neither tracked `VolatilitySystem` copy changed.
- The prospective interval was not spent and is not authorized for this closed candidate.
- No BotRelease, RuntimeInstance, formal Paper Observation, compatibility-runtime
  promotion, exchange write, or Live action was opened.
- Matching attempt containers and the Docker network are absent.
- The partial run directory was moved intact from its working location to recoverable,
  external quarantine `freqtrade-cn-spent-attempt-quarantine-dev-bc-56b60c7`. Its spent
  lease retained the exact byte count and SHA-256 above. No result content was opened
  during that move.
- Root and all three submodules were clean before this documentation closeout.

The frozen receipt, candidate/baseline/data/image/validator/contract/config/controller
identities, and pre-performance report remain unchanged historical evidence. This report
makes no profit, statistical-significance, Paper-readiness, or future-return claim.
