from __future__ import annotations

from tools import verify_price_flow_signed_flow_expansion as verify


def test_verification_cases_are_frozen_and_include_execution_stress() -> None:
    cases = verify._verification_cases()

    assert [case.stage for case in cases] == [
        "verification-named-full",
        "verification-named-rerun",
        "verification-fee-double",
        "verification-detail-5m",
        "verification-three-year",
        "verification-max-history",
    ]
    assert next(case for case in cases if case.stage == "verification-fee-double").fee == 0.001
    assert next(case for case in cases if case.stage == "verification-detail-5m").detail == "5m"


def test_named_strategy_spec_is_the_frozen_15m_2x_m2() -> None:
    spec = verify.FINAL_SPEC

    assert spec.strategy == "PriceFlowSignedFlowExpansionStrategy"
    assert spec.timeframe == "15m"
    assert spec.leverage == 2
    assert spec.confirmation == "signed_fresh_oi"
    assert spec.risk_model == "fixed_account"
