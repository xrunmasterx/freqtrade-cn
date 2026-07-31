# Backtest Pair Interpretation Boundary

**Status:** Accepted and implemented

**Date:** 2026-07-31

## Context

Gate A.2 through Gate A.4 let the existing FreqUI comparison page report exact
DataSnapshot, primary-strategy, and bounded execution-context equality independently.
The page still leaves the user to infer what a particular combination means, and its
metric table does not show the effective scored windows.

Two different research questions are easy to confuse:

1. what changed when captured strategy evidence changed on the same data and in the same
   bounded context; and
2. how the same captured strategy evidence behaved on a different historical window.

The current evidence can constrain those retrospective readings. It cannot prove
revision lineage, prior non-use of a window, statistical generalization, or future
performance.

## Decision

Add one frontend-only, fail-closed interpretation for exactly two loaded Backtest
results. Reuse the accepted strict identity helpers and the effective scored timestamps
already present on each in-memory strategy result.

| Interpretation | DataSnapshot | Strategy evidence | Execution context | Effective scored windows |
|---|---|---|---|---|
| Same-window strategy-change review | same | different | same | exactly equal |
| Cross-window review | different | same | same | strictly disjoint |

Every other fully known combination is `not_comparable`. A missing or malformed required
identity, or an invalid effective scored window, is `unknown`. A shared endpoint counts
as overlap, not disjointness.

The first state is deliberately not called a strategy revision comparison. Different
valid strategy evidence can represent unrelated strategy names, and the current evidence
does not prove a shared `StrategyExperiment` or revision lineage.

Cardinality other than two produces no pair interpretation. The existing independent
identity cards and full metric table remain unchanged.

## Claim boundary

The interpretation may say only that a pair matches one of the two evidence shapes
above. It does not:

- assign baseline/candidate or calibration/holdout roles;
- prove that a historical window was untouched;
- score, rank, recommend, promote, or automatically accept a strategy;
- establish causality, absence of lookahead/recursive bias, broader validity, Paper
  eligibility, contract safety, or future performance;
- add a persisted split, trial ledger, database, API, optimizer, scheduler, or second
  engine.

## Alternatives rejected

### Documentation-only manual interpretation

This has zero implementation cost, but leaves a recurring and error-prone three-axis
truth table to every user and omits the effective scored windows from the comparison
surface.

### Four-result calibration/second-window matrix

This is a useful manual research protocol, but it requires roles and a larger interaction
model. It is not necessary to make one loaded pair interpretable.

### Persisted holdout or validation-split contract

This would be required to govern precommitment or reveal history. The current product
does not yet require or justify that durable semantic surface.
