import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from tools.prepare_price_flow_derivatives import _engineer_features


def _daily_inputs(rows: int) -> pd.DataFrame:
    index = np.arange(rows, dtype=float)
    return pd.DataFrame(
        {
            "source_date": pd.date_range("2025-01-01", periods=rows, freq="D", tz="UTC"),
            "oi_ccy": 1000 + index * 3,
            "taker_buy_ccy": 500 + index,
            "taker_sell_ccy": 480 + index * 0.5,
            "top_account_ratio": 1.0 + index / 1000,
            "top_position_ratio": 1.1 + index / 1200,
            "contract_account_ratio": 1.2 + index / 900,
            "funding_daily_sum": (index - 20) / 100_000,
            "option_contract_volume": 10_000 + index * 100,
            "option_put_call_ratio": 0.9 + index / 1000,
            "option_flow_size": (index - 20) / 100,
            "option_flow_premium": (index - 15) / 100,
            "option_otm_flow": (index - 10) / 100,
            "option_directional_price_change": (index - 25) / 1000,
        }
    )


def test_engineered_daily_features_are_delayed_one_full_day():
    inputs = _daily_inputs(40)

    result = _engineer_features(inputs)

    assert ((result["date"] - result["source_date"]) == pd.Timedelta(days=1)).all()


def test_future_source_rows_cannot_change_an_existing_feature_prefix():
    inputs = _daily_inputs(45)
    prefix = _engineer_features(inputs.iloc[:40].copy())
    full = _engineer_features(inputs.copy()).iloc[:40]

    compared = [
        "date",
        "source_date",
        "oi_change_1d_z",
        "taker_imbalance_z",
        "top_position_change_z",
        "option_flow_premium_z",
    ]
    assert_frame_equal(prefix[compared], full[compared])
