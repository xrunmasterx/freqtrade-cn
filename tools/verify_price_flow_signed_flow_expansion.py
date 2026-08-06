from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass

try:
    from tools import run_price_flow_timeframe_leverage_research as research
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import run_price_flow_timeframe_leverage_research as research


FINAL_SPEC = research.StrategySpec(
    code="SIGNED-FLOW-EXPANSION",
    strategy="PriceFlowSignedFlowExpansionStrategy",
    timeframe="15m",
    leverage=2,
    risk_model="fixed_account",
    confirmation="signed_fresh_oi",
)
THREE_YEAR_FOLDS = {
    "Y1": ("2023-08-01T00:00:00Z", "2024-08-01T00:00:00Z"),
    "Y2": ("2024-08-01T00:00:00Z", "2025-08-01T00:00:00Z"),
    "Y3": ("2025-08-01T00:00:00Z", "2026-08-01T00:00:00Z"),
}
MAX_HISTORY_FOLDS = {
    "2022": ("2022-01-01T00:00:00Z", "2023-01-01T00:00:00Z"),
    "2023": ("2023-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
    "2024": ("2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
    "2025": ("2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    "2026-7m": ("2026-01-01T00:00:00Z", "2026-08-01T00:00:00Z"),
}


@dataclass(frozen=True)
class VerificationCase:
    stage: str
    timerange: tuple[str, str]
    folds: dict[str, tuple[str, str]]
    fee: float = 0.0005
    detail: str | None = None


def _verification_cases() -> list[VerificationCase]:
    return [
        VerificationCase(
            "verification-named-full", research.FULL_WINDOW, research.FULL_FOLDS
        ),
        VerificationCase(
            "verification-named-rerun", research.FULL_WINDOW, research.FULL_FOLDS
        ),
        VerificationCase(
            "verification-fee-double",
            research.FULL_WINDOW,
            research.FULL_FOLDS,
            fee=0.001,
        ),
        VerificationCase(
            "verification-detail-5m",
            research.FULL_WINDOW,
            research.FULL_FOLDS,
            detail="5m",
        ),
        VerificationCase(
            "verification-three-year",
            ("20230801", "20260801"),
            THREE_YEAR_FOLDS,
        ),
        VerificationCase(
            "verification-max-history",
            ("20220101", "20260801"),
            MAX_HISTORY_FOLDS,
        ),
    ]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the frozen PriceFlowSignedFlowExpansionStrategy."
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    return parser


def _run_case(case: VerificationCase, *, resume: bool) -> research.Metrics:
    return research._run_backtest(
        FINAL_SPEC,
        case.stage,
        case.timerange,
        case.folds,
        fee=case.fee,
        resume=resume,
        timeframe_detail=case.detail,
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.workers < 1:
        raise ValueError("--workers must be positive")
    main_results_path = research.RESULT_ROOT / "results.json"
    if not main_results_path.is_file():
        raise FileNotFoundError("Run the frozen timeframe/leverage protocol first")
    main_results = json.loads(main_results_path.read_text(encoding="utf-8"))
    selected = next(
        item
        for item in main_results["metrics"]
        if item["stage"] == "full" and item["code"] == "T15m-L2-M2"
    )

    cases = _verification_cases()
    metrics: list[research.Metrics] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(_run_case, case, resume=args.resume): case for case in cases
        }
        for future in as_completed(futures):
            metrics.append(future.result())
    order = {case.stage: position for position, case in enumerate(cases)}
    metrics.sort(key=lambda item: order[item.stage])

    named_full = next(item for item in metrics if item.stage == "verification-named-full")
    named_rerun = next(
        item for item in metrics if item.stage == "verification-named-rerun"
    )
    equivalent_to_selected = (
        named_full.trade_fingerprint == selected["trade_fingerprint"]
    )
    deterministic = named_full.trade_fingerprint == named_rerun.trade_fingerprint
    final_source = (
        research.USER_DATA / "strategies" / "PriceFlowSignedFlowExpansionStrategy.py"
    )
    payload = {
        "selected_research_code": "T15m-L2-M2",
        "equivalent_to_selected": equivalent_to_selected,
        "deterministic_named_rerun": deterministic,
        "final_strategy_source": str(final_source.relative_to(research.REPO_ROOT)),
        "final_strategy_source_sha256": research._sha256(final_source),
        "cases": [asdict(case) for case in cases],
        "metrics": [asdict(item) for item in metrics],
    }
    output = research.RESULT_ROOT / "verification-results.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    valid = all(item.status == "MEASURED" for item in metrics)
    return 0 if valid and equivalent_to_selected and deterministic else 1


if __name__ == "__main__":
    raise SystemExit(main())
