import inspect
import sys
from pathlib import Path

import pandas as pd
import pytest

STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
sys.path.insert(0, str(STRATEGY_DIR))

from PriceFlowCPIAbsorptionStrategy import PriceFlowCPIAbsorptionStrategy
from PriceFlowCrossVenueResearchStrategy import (
    PriceFlowCrossVenue15Strategy,
    PriceFlowCrossVenue33Strategy,
    PriceFlowCrossVenue40Strategy,
    PriceFlowCrossVenueResearchBase,
)
from PriceFlowShortDteOptionPressureStrategy import (
    PriceFlowShortDteOptionPressureStrategy,
)
from PriceFlowTakerCUSUMStrategy import PriceFlowTakerCUSUMStrategy

PROMOTIONS = (
    (
        PriceFlowTakerCUSUMStrategy,
        PriceFlowCrossVenue40Strategy,
        40,
        "A40",
    ),
    (
        PriceFlowShortDteOptionPressureStrategy,
        PriceFlowCrossVenue15Strategy,
        15,
        "D15",
    ),
    (
        PriceFlowCPIAbsorptionStrategy,
        PriceFlowCrossVenue33Strategy,
        33,
        "P33",
    ),
)


def _entry_row(**overrides):
    row = {
        "volume": 100.0,
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "ema20": 100.0,
        "rolling_vwap_24h": 100.0,
        "long_retest": True,
        "short_retest": False,
        "long_trend_1h": True,
        "short_trend_1h": False,
        "long_regime_4h": True,
        "short_regime_4h": False,
        "flow_imbalance_8": 0.11,
        "flow_imbalance_24": 0.04,
        "return_24h_1h": 0.05,
        "cross_data_valid": True,
        "bin_taker_imbalance": 0.2,
        "opt_dte_1_7_count_1h": 5,
        "opt_dte_1_7_urgency_1h": 0.2,
        "taker_cusum_long_follow": False,
        "taker_cusum_short_follow": False,
        "minutes_from_cpi": 120.0,
        "cpi_event_high": 102.0,
        "cpi_event_low": 99.0,
    }
    row.update(overrides)
    return row


def _representative_entries() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _entry_row(),
            _entry_row(
                long_retest=False,
                close=103.0,
                high=103.5,
                taker_cusum_long_follow=True,
                minutes_from_cpi=45.0,
            ),
            _entry_row(
                cross_data_valid=False,
                opt_dte_1_7_count_1h=0,
                opt_dte_1_7_urgency_1h=0.0,
            ),
        ]
    )


@pytest.mark.parametrize("promoted_class,frozen_class,candidate_id,code", PROMOTIONS)
def test_promoted_strategy_has_a_literal_selectable_class_and_frozen_origin(
    promoted_class,
    frozen_class,
    candidate_id,
    code,
):
    source = Path(inspect.getfile(promoted_class)).read_text(encoding="utf-8")
    strategy = promoted_class(config={})

    assert promoted_class.__bases__ == (PriceFlowCrossVenueResearchBase,)
    assert f"class {promoted_class.__name__}(" in source
    assert strategy.candidate_id == candidate_id
    assert strategy.candidate_code == code
    assert frozen_class.candidate_id == candidate_id


@pytest.mark.parametrize("promoted_class,frozen_class,_,__", PROMOTIONS)
def test_promoted_strategy_preserves_frozen_entry_semantics(
    promoted_class,
    frozen_class,
    _,
    __,
):
    dataframe = _representative_entries()
    metadata = {"pair": "BTC/USDT:USDT"}

    promoted = promoted_class(config={}).populate_entry_trend(dataframe.copy(), metadata)
    frozen = frozen_class(config={}).populate_entry_trend(dataframe.copy(), metadata)

    signal_columns = ["enter_long", "enter_short", "enter_tag"]
    pd.testing.assert_frame_equal(promoted[signal_columns], frozen[signal_columns])
