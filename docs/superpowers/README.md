# Superpowers Documentation Index

**Current status date:** 2026-07-30

Read this file before selecting an implementation plan. Dated plans and specifications
are retained as design and acceptance history; unchecked boxes in a completed plan are
not an active backlog.

## Current development state

- Runtime Registry v2 Phases 2A, 2B, and 2C are merged into local Root `main`.
- Phase 2C is accepted at its offline, fail-closed boundary. Production Supervisor
  assembly, online runtime acceptance, exchange writes, and live trading remain disabled.
- Phase 2D Tasks 1-4 are complete only on the local, unpublished
  `phase2d-runtime-access-rebaseline` branch. Root is at `2128646`; backend is at
  `b9345c4a6`; frontend is unchanged at `09b235d8`.
- Phase 2D Task 5, one authenticated base-only chart on 8090, is the next implementation
  task.
- Phase 2E remains planned and must not start before the rebaselined Phase 2D Task 8 gate.

## Active implementation entrypoints

| Role | Document | Status |
|---|---|---|
| Coordination | `plans/2026-07-12-runtime-registry-v2-master.md` | Governing Phase 2 sequence and constraints |
| Runtime Access decision | `specs/2026-07-30-runtime-access-rebaseline-design.md` | Approved amendment; read before remaining Phase 2D work |
| Next implementation | `plans/2026-07-12-runtime-registry-v2-phase2d-market-data-ui.md` | Active; Tasks 1-4 complete locally, Task 5 next |
| Later implementation | `plans/2026-07-12-runtime-registry-v2-phase2e-cutover.md` | Planned; blocked on Phase 2D Task 8 |

## Governing specifications

- `specs/2026-07-12-multi-market-research-trading-platform-design.md`
- `specs/2026-07-12-runtime-registry-v2-design.md`
- `specs/2026-07-30-runtime-access-rebaseline-design.md`
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
- Runtime Registry v2 design sections 13.4, 21.4, and 21.5: use
  `specs/2026-07-30-runtime-access-rebaseline-design.md` for Runtime Access route breadth,
  first-operation/audit contract, internal authentication, and dependency ordering. All
  other safety constraints in the 2026-07-12 design remain governing.
- Phase 2D Tasks 5-10: the active Phase 2D plan now replaces the old 49-route/token-first
  sequence with Tasks 5-8: base-only 8090 chart, Supervisor production-readiness and real
  target closure, one Bot overlay operation, and acceptance.
- Phase 2E: use the active rebaselined plan. Research, Spot, and Futures each use an
  independent service cycle: disposable read candidate, final authoritative sync, write
  migration, then listener removal. Operations are added only with their producers and
  consumers.
- For the current multi-market target architecture, use the approved 2026-07-12 design;
  the 2026-07-11 architecture document is retained as earlier design history.

## Acceptance evidence

Files under `reports/` are frozen historical evidence. Status text such as "merge
pending" describes the moment when a report was written; do not rewrite it after later
publication. Use the current Root `main` history and remote refs to determine final merge
state.

Operational runbooks under `../operations/` are current runtime documentation and are not
historical implementation plans. Some are enforced directly by automated tests.
