from __future__ import annotations

import inspect
import sys
from pathlib import Path

STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
sys.path.insert(0, str(STRATEGY_DIR))

from PriceFlowSignedFlowExpansionStrategy import PriceFlowSignedFlowExpansionStrategy
from PriceFlowTimeframeLeverageResearchStrategy import (
    PriceFlowE10Tf15mLev2SignedFreshOiStrategy,
)


def test_signed_flow_expansion_is_a_literal_frozen_m2_strategy() -> None:
    source = Path(inspect.getfile(PriceFlowSignedFlowExpansionStrategy)).read_text(
        encoding="utf-8"
    )
    strategy = PriceFlowSignedFlowExpansionStrategy(config={})

    assert PriceFlowSignedFlowExpansionStrategy.__bases__ == (
        PriceFlowE10Tf15mLev2SignedFreshOiStrategy,
    )
    assert "class PriceFlowSignedFlowExpansionStrategy(" in source
    assert strategy.timeframe == "15m"
    assert strategy.target_leverage == 2.0
    assert strategy.event_id == 10
    assert strategy.confirmation_mode == "signed_fresh_oi"
    assert strategy.stoploss == -0.03
    assert strategy.minimal_roi == {"0": 0.06, "720": 0.04, "1440": 0.02}
