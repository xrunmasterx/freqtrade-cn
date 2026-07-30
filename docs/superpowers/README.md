# Superpowers Documentation Index

**Current status date:** 2026-07-30

Read this file before selecting an implementation plan. Dated plans and specifications
are retained as design and acceptance history; unchecked boxes in a completed plan are
not an active backlog.

## Current development state

- Runtime Registry v2 Phases 2A, 2B, and 2C are merged into Root `main`.
- Phase 2C is accepted at its offline, fail-closed boundary. Production Supervisor
  assembly, online runtime acceptance, exchange writes, and live trading remain disabled.
- Phase 2D is the next implementation phase.
- Phase 2E remains planned and must not start before Phase 2D acceptance.

## Active implementation entrypoints

| Role | Document | Status |
|---|---|---|
| Coordination | `plans/2026-07-12-runtime-registry-v2-master.md` | Governing Phase 2 sequence and constraints |
| Next implementation | `plans/2026-07-12-runtime-registry-v2-phase2d-market-data-ui.md` | Active next phase |
| Later implementation | `plans/2026-07-12-runtime-registry-v2-phase2e-cutover.md` | Planned; blocked on Phase 2D acceptance |

## Governing specifications

- `specs/2026-07-12-multi-market-research-trading-platform-design.md`
- `specs/2026-07-12-runtime-registry-v2-design.md`
- `specs/2026-07-15-phase2c-runtime-driver-contract-design.md`
- `specs/2026-07-17-phase2c-task7b-persisted-launch-authority-design.md`
- `../chart-data-source-rules.md` for chart indicators, overlays, decision evidence,
  crosshair, and tooltip work

Later amendments override only the sections they explicitly supersede. They do not
silently replace global safety constraints or previously reviewed domain contracts.

## Completed historical plans

Treat the following as implementation history, not executable work queues:

- P0 current-system and Draft PR safety closure plans
- Market Catalog and Runtime Registry v2 Phase 2A plans
- Runtime Registry v2 Phase 2B and its Task 7 completion plan
- Runtime Registry v2 Phase 2C and its Task 1, Task 3, Task 4, and Task 7 repair or
  continuation plans
- the dated FreqUI, chart, LSRI, QQE MOD, Research, and A-share feature plans from
  2026-07-03 through 2026-07-08

These documents preserve implementation rationale, exact test commands, compatibility
constraints, and review history. Their checkbox state was not consistently updated after
publication and must not be used to infer current progress.

## Supersession map

- Phase 2B Task 7: use
  `plans/2026-07-14-runtime-registry-v2-phase2b-task7-contract-completion.md` for the
  completed contract repair.
- Phase 2C Task 1 interface and sequencing: use
  `specs/2026-07-15-phase2c-runtime-driver-contract-design.md` and its matching plan.
- Phase 2C Task 3 and Task 4: use the dated 2026-07-16 repair/clarification plans and
  acceptance reports.
- Phase 2C Task 7: use the 2026-07-17 Task 7A/7B plans, design, and acceptance reports.
- For the current multi-market target architecture, use the approved 2026-07-12 design;
  the 2026-07-11 architecture document is retained as earlier design history.

## Acceptance evidence

Files under `reports/` are frozen historical evidence. Status text such as "merge
pending" describes the moment when a report was written; do not rewrite it after later
publication. Use the current Root `main` history and remote refs to determine final merge
state.

Operational runbooks under `../operations/` are current runtime documentation and are not
historical implementation plans. Some are enforced directly by automated tests.
