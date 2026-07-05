# QQE MOD Shared Indicators Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Mihkel00-style QQE MOD as a shared backend indicator, migrate Supertrend into the same shared indicator layer, and expose QQE MOD as a default chart watch indicator without changing existing strategy trading rules.

**Architecture:** `freqtrade.indicators` becomes the numerical source of truth for reusable technical indicators. `freqtrade.rpc.chart_indicators` adapts shared indicator output into `watch_*` chart columns and `plot_config`. FreqUI keeps rendering server-provided columns and receives only type support for `qqe_mod` request payloads.

**Tech Stack:** Python, pandas, TA-Lib abstract API, Pydantic v2 schemas, pytest, TypeScript, Vue/FreqUI chart payload types.

---

## File Structure

- Create: `freqtrade/freqtrade/indicators/__init__.py`
  - Exposes the shared indicator package.
- Create: `freqtrade/freqtrade/indicators/supertrend.py`
  - Owns the ATR-based Supertrend calculation and dataframe helper.
- Create: `freqtrade/freqtrade/indicators/qqe_mod.py`
  - Owns the Mihkel00 QQE MOD dual-QQE calculation and dataframe helper.
- Create: `freqtrade/tests/indicators/test_supertrend.py`
  - Verifies migrated Supertrend behavior independent of RPC.
- Create: `freqtrade/tests/indicators/test_qqe_mod.py`
  - Verifies QQE MOD shared indicator behavior independent of RPC.
- Modify: `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
  - Adds `QqeModIndicatorRequest` and wires it into `ChartIndicatorRequest`.
- Modify: `freqtrade/freqtrade/rpc/chart_indicators.py`
  - Removes Supertrend algorithm ownership, calls shared Supertrend, calls shared QQE MOD, and builds QQE MOD plot config.
- Modify: `freqtrade/tests/rpc/test_chart_indicators.py`
  - Updates default expectations for QQE MOD and validates chart adapter behavior.
- Modify: `freqtrade/tests/rpc/test_chart_data.py`
  - Verifies `/chart_candles` returns QQE MOD columns and plot config.
- Modify: `freqtrade/tests/rpc/test_rpc_apiserver.py`
  - Adds request schema validation for `watch_indicators.qqe_mod`.
- Modify: `frequi/src/types/candleTypes.ts`
  - Adds FreqUI request payload typing for QQE MOD.

Do not change strategy files in this plan. Strategy usage is enabled by imports only.

---

### Task 1: Add Shared Supertrend Indicator

**Files:**
- Create: `freqtrade/freqtrade/indicators/__init__.py`
- Create: `freqtrade/freqtrade/indicators/supertrend.py`
- Create: `freqtrade/tests/indicators/test_supertrend.py`

- [ ] **Step 1: Write failing shared Supertrend tests**

Create `freqtrade/tests/indicators/test_supertrend.py`:

```python
import pandas as pd
from pandas.testing import assert_frame_equal, assert_series_equal

from freqtrade.indicators.supertrend import add_supertrend
from tests.conftest import generate_test_data


def test_add_supertrend_creates_default_columns_without_mutating_input():
    dataframe = generate_test_data("15m", 160, "2024-01-01 00:00:00+00:00")
    original = dataframe.copy()

    result = add_supertrend(dataframe)

    assert_frame_equal(dataframe, original)
    assert "supertrend_up" in result.columns
    assert "supertrend_down" in result.columns
    assert "supertrend_price" in result.columns
    assert_series_equal(result["supertrend_price"], dataframe["close"], check_names=False)
    populated_sides = result[["supertrend_up", "supertrend_down"]].notna().sum(axis=1)
    assert populated_sides.max() <= 1
    assert populated_sides.sum() > 0


def test_add_supertrend_accepts_custom_prefix():
    dataframe = generate_test_data("15m", 160, "2024-01-01 00:00:00+00:00")

    result = add_supertrend(dataframe, period=7, multiplier=2.5, prefix="custom_st")

    assert "custom_st_up" in result.columns
    assert "custom_st_down" in result.columns
    assert "custom_st_price" in result.columns
    assert_series_equal(result["custom_st_price"], dataframe["close"], check_names=False)


def test_add_supertrend_matches_existing_direction_transition_fixture():
    dataframe = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=5, freq="15min", tz="UTC"),
            "open": [10.0, 10.0, 10.0, 12.0, 13.0],
            "high": [10.0, 10.0, 10.0, 12.0, 13.0],
            "low": [10.0, 10.0, 10.0, 12.0, 13.0],
            "close": [10.0, 10.0, 10.0, 12.0, 13.0],
            "volume": [100.0, 100.0, 100.0, 100.0, 100.0],
        }
    )

    result = add_supertrend(dataframe, period=2, multiplier=1.0, prefix="st")

    expected_up = pd.Series([float("nan"), float("nan"), float("nan"), 11.0, 12.0])
    expected_down = pd.Series([float("nan"), float("nan"), 10.0, float("nan"), float("nan")])
    assert_series_equal(result["st_up"], expected_up, check_names=False)
    assert_series_equal(result["st_down"], expected_down, check_names=False)


def test_add_supertrend_rejects_missing_columns():
    dataframe = pd.DataFrame({"close": [1.0, 2.0, 3.0]})

    try:
        add_supertrend(dataframe)
    except ValueError as exc:
        assert "high" in str(exc)
        assert "low" in str(exc)
    else:
        raise AssertionError("add_supertrend should reject missing high/low columns")
```

- [ ] **Step 2: Run the new Supertrend tests and verify RED**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
pytest tests/indicators/test_supertrend.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'freqtrade.indicators'`.

- [ ] **Step 3: Create the shared indicator package**

Create `freqtrade/freqtrade/indicators/__init__.py`:

```python
"""Shared technical indicators for strategies and chart adapters."""
```

- [ ] **Step 4: Implement `freqtrade.indicators.supertrend`**

Create `freqtrade/freqtrade/indicators/supertrend.py`:

```python
from __future__ import annotations

import pandas as pd
import talib.abstract as ta
from pandas import DataFrame


def add_supertrend(
    dataframe: DataFrame,
    period: int = 10,
    multiplier: float = 3.0,
    prefix: str = "supertrend",
) -> DataFrame:
    _validate_supertrend_input(dataframe)
    result = dataframe.copy()
    supertrend, direction = calculate_supertrend(result, period, multiplier)
    result[f"{prefix}_up"] = supertrend.where(direction == 1)
    result[f"{prefix}_down"] = supertrend.where(direction == -1)
    result[f"{prefix}_price"] = result["close"]
    return result


def calculate_supertrend(
    dataframe: DataFrame,
    period: int,
    multiplier: float,
) -> tuple[pd.Series, pd.Series]:
    _validate_supertrend_input(dataframe)
    atr = ta.ATR(dataframe, timeperiod=period)
    hl2 = (dataframe["high"] + dataframe["low"]) / 2
    basic_upper = hl2 + multiplier * atr
    basic_lower = hl2 - multiplier * atr
    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()
    supertrend = pd.Series(float("nan"), index=dataframe.index, dtype="float64")
    direction = pd.Series(0, index=dataframe.index, dtype="int64")

    for index in range(len(dataframe)):
        if pd.isna(atr.iloc[index]):
            continue

        if index == 0 or direction.iloc[index - 1] == 0:
            final_upper.iloc[index] = basic_upper.iloc[index]
            final_lower.iloc[index] = basic_lower.iloc[index]
            if dataframe["close"].iloc[index] <= final_upper.iloc[index]:
                direction.iloc[index] = -1
                supertrend.iloc[index] = final_upper.iloc[index]
            else:
                direction.iloc[index] = 1
                supertrend.iloc[index] = final_lower.iloc[index]
            continue

        prev_final_upper = final_upper.iloc[index - 1]
        prev_final_lower = final_lower.iloc[index - 1]
        prev_close = dataframe["close"].iloc[index - 1]

        if pd.isna(prev_final_upper) or (
            basic_upper.iloc[index] < prev_final_upper or prev_close > prev_final_upper
        ):
            final_upper.iloc[index] = basic_upper.iloc[index]
        else:
            final_upper.iloc[index] = prev_final_upper

        if pd.isna(prev_final_lower) or (
            basic_lower.iloc[index] > prev_final_lower or prev_close < prev_final_lower
        ):
            final_lower.iloc[index] = basic_lower.iloc[index]
        else:
            final_lower.iloc[index] = prev_final_lower

        close = dataframe["close"].iloc[index]
        if direction.iloc[index - 1] == -1:
            if close > final_upper.iloc[index]:
                direction.iloc[index] = 1
                supertrend.iloc[index] = final_lower.iloc[index]
            else:
                direction.iloc[index] = -1
                supertrend.iloc[index] = final_upper.iloc[index]
        else:
            if close < final_lower.iloc[index]:
                direction.iloc[index] = -1
                supertrend.iloc[index] = final_upper.iloc[index]
            else:
                direction.iloc[index] = 1
                supertrend.iloc[index] = final_lower.iloc[index]

    return supertrend, direction


def _validate_supertrend_input(dataframe: DataFrame) -> None:
    missing = {"high", "low", "close"} - set(dataframe.columns)
    if missing:
        missing_columns = ", ".join(sorted(missing))
        raise ValueError(f"Supertrend requires columns: {missing_columns}")
```

- [ ] **Step 5: Run shared Supertrend tests and verify GREEN**

Run:

```powershell
pytest tests/indicators/test_supertrend.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

Run:

```powershell
git add freqtrade/indicators/__init__.py freqtrade/indicators/supertrend.py tests/indicators/test_supertrend.py
git commit -m "feat: add shared supertrend indicator"
```

---

### Task 2: Add Shared QQE MOD Indicator

**Files:**
- Create: `freqtrade/freqtrade/indicators/qqe_mod.py`
- Create: `freqtrade/tests/indicators/test_qqe_mod.py`

- [ ] **Step 1: Write failing shared QQE MOD tests**

Create `freqtrade/tests/indicators/test_qqe_mod.py`:

```python
import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal, assert_series_equal

from freqtrade.indicators.qqe_mod import add_qqe_mod
from tests.conftest import generate_test_data


QQE_MOD_COLUMNS = [
    "qqe_mod_trend",
    "qqe_mod_hist",
    "qqe_mod_up",
    "qqe_mod_down",
    "qqe_mod_up_state",
    "qqe_mod_down_state",
    "qqe_mod_up_event",
    "qqe_mod_down_event",
]


def test_add_qqe_mod_creates_default_columns_without_mutating_input():
    dataframe = generate_test_data("15m", 220, "2024-01-01 00:00:00+00:00")
    original = dataframe.copy()

    result = add_qqe_mod(dataframe)

    assert_frame_equal(dataframe, original)
    for column in QQE_MOD_COLUMNS:
        assert column in result.columns
    assert result["qqe_mod_hist"].notna().sum() > 0
    assert result["qqe_mod_trend"].notna().sum() > 0
    assert result["qqe_mod_up_state"].dtype == bool
    assert result["qqe_mod_down_state"].dtype == bool
    assert result["qqe_mod_up_event"].dtype == bool
    assert result["qqe_mod_down_event"].dtype == bool


def test_add_qqe_mod_accepts_custom_prefix():
    dataframe = generate_test_data("15m", 220, "2024-01-01 00:00:00+00:00")

    result = add_qqe_mod(dataframe, prefix="custom_qqe")

    assert "custom_qqe_trend" in result.columns
    assert "custom_qqe_hist" in result.columns
    assert "custom_qqe_up" in result.columns
    assert "custom_qqe_down" in result.columns


def test_add_qqe_mod_keeps_warmup_empty_instead_of_zero_filled():
    dataframe = generate_test_data("15m", 220, "2024-01-01 00:00:00+00:00")

    result = add_qqe_mod(dataframe)

    warmup_hist = result["qqe_mod_hist"].iloc[:20]
    assert warmup_hist.isna().any()
    assert not (warmup_hist.fillna(np.nan) == 0).all()


def test_add_qqe_mod_signal_columns_match_states():
    dataframe = generate_test_data("15m", 260, "2024-01-01 00:00:00+00:00")

    result = add_qqe_mod(dataframe)

    assert result.loc[~result["qqe_mod_up_state"], "qqe_mod_up"].isna().all()
    assert result.loc[~result["qqe_mod_down_state"], "qqe_mod_down"].isna().all()
    assert result.loc[result["qqe_mod_up_state"], "qqe_mod_up"].equals(
        result.loc[result["qqe_mod_up_state"], "qqe_mod_hist"]
    )
    assert result.loc[result["qqe_mod_down_state"], "qqe_mod_down"].equals(
        result.loc[result["qqe_mod_down_state"], "qqe_mod_hist"]
    )


def test_add_qqe_mod_events_fire_only_on_state_transitions():
    dataframe = generate_test_data("15m", 260, "2024-01-01 00:00:00+00:00")

    result = add_qqe_mod(dataframe)

    expected_up_event = result["qqe_mod_up_state"] & ~result["qqe_mod_up_state"].shift(
        1, fill_value=False
    )
    expected_down_event = result["qqe_mod_down_state"] & ~result["qqe_mod_down_state"].shift(
        1, fill_value=False
    )
    assert_series_equal(result["qqe_mod_up_event"], expected_up_event, check_names=False)
    assert_series_equal(result["qqe_mod_down_event"], expected_down_event, check_names=False)


def test_add_qqe_mod_constant_price_has_neutral_histogram_after_warmup():
    dataframe = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=180, freq="15min", tz="UTC"),
            "open": [100.0] * 180,
            "high": [100.0] * 180,
            "low": [100.0] * 180,
            "close": [100.0] * 180,
            "volume": [1000.0] * 180,
        }
    )

    result = add_qqe_mod(dataframe)
    valid_hist = result["qqe_mod_hist"].dropna()

    assert len(valid_hist) > 0
    assert valid_hist.abs().max() == 0
    assert not result["qqe_mod_up_state"].any()
    assert not result["qqe_mod_down_state"].any()


def test_add_qqe_mod_rejects_missing_source_column():
    dataframe = pd.DataFrame({"close": [1.0, 2.0, 3.0]})

    try:
        add_qqe_mod(dataframe, source="hlc3")
    except ValueError as exc:
        assert "hlc3" in str(exc)
    else:
        raise AssertionError("add_qqe_mod should reject a missing source column")
```

- [ ] **Step 2: Run the new QQE MOD tests and verify RED**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
pytest tests/indicators/test_qqe_mod.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'freqtrade.indicators.qqe_mod'`.

- [ ] **Step 3: Implement `freqtrade.indicators.qqe_mod`**

Create `freqtrade/freqtrade/indicators/qqe_mod.py`:

```python
from __future__ import annotations

import numpy as np
import pandas as pd
from pandas import DataFrame


def add_qqe_mod(
    dataframe: DataFrame,
    rsi_length: int = 6,
    rsi_smoothing: int = 5,
    qqe_factor: float = 3.0,
    bollinger_length: int = 50,
    bollinger_multiplier: float = 0.35,
    secondary_rsi_length: int = 6,
    secondary_rsi_smoothing: int = 5,
    secondary_qqe_factor: float = 1.61,
    threshold: float = 3.0,
    source: str = "close",
    prefix: str = "qqe_mod",
) -> DataFrame:
    _validate_qqe_mod_input(
        dataframe,
        source,
        rsi_length,
        rsi_smoothing,
        qqe_factor,
        bollinger_length,
        bollinger_multiplier,
        secondary_rsi_length,
        secondary_rsi_smoothing,
        secondary_qqe_factor,
        threshold,
    )
    result = dataframe.copy()
    source_series = pd.to_numeric(result[source], errors="coerce").astype("float64")

    primary = _qqe_pass(source_series, rsi_length, rsi_smoothing, qqe_factor)
    primary_trail_offset = primary["trail"] - 50.0
    bb_basis = primary_trail_offset.rolling(bollinger_length, min_periods=bollinger_length).mean()
    bb_dev = (
        primary_trail_offset.rolling(bollinger_length, min_periods=bollinger_length).std(ddof=0)
        * bollinger_multiplier
    )
    upper = bb_basis + bb_dev
    lower = bb_basis - bb_dev

    secondary = _qqe_pass(
        source_series,
        secondary_rsi_length,
        secondary_rsi_smoothing,
        secondary_qqe_factor,
    )
    trend = secondary["trail"] - 50.0
    hist = secondary["rsi_ma"] - 50.0

    up_state = (hist > threshold) & ((primary["rsi_ma"] - 50.0) > upper)
    down_state = (hist < -threshold) & ((primary["rsi_ma"] - 50.0) < lower)
    up_state = up_state.fillna(False).astype(bool)
    down_state = down_state.fillna(False).astype(bool)
    up_event = up_state & ~up_state.shift(1, fill_value=False)
    down_event = down_state & ~down_state.shift(1, fill_value=False)

    result[f"{prefix}_trend"] = trend
    result[f"{prefix}_hist"] = hist
    result[f"{prefix}_up"] = hist.where(up_state)
    result[f"{prefix}_down"] = hist.where(down_state)
    result[f"{prefix}_up_state"] = up_state
    result[f"{prefix}_down_state"] = down_state
    result[f"{prefix}_up_event"] = up_event
    result[f"{prefix}_down_event"] = down_event
    return result


def _qqe_pass(
    source: pd.Series,
    rsi_length: int,
    rsi_smoothing: int,
    qqe_factor: float,
) -> dict[str, pd.Series]:
    wilders_period = rsi_length * 2 - 1
    rsi = _wilder_rsi(source, rsi_length)
    rsi_ma = _ema(rsi, rsi_smoothing)
    atr_rsi = (rsi_ma - rsi_ma.shift(1)).abs()
    ma_atr_rsi = _ema(atr_rsi, wilders_period)
    dar = _ema(ma_atr_rsi, wilders_period) * qqe_factor

    new_longband = rsi_ma - dar
    new_shortband = rsi_ma + dar
    longband = pd.Series(np.nan, index=source.index, dtype="float64")
    shortband = pd.Series(np.nan, index=source.index, dtype="float64")
    trend = pd.Series(1, index=source.index, dtype="int64")
    trail = pd.Series(np.nan, index=source.index, dtype="float64")

    for index in range(len(source)):
        current_rsi = rsi_ma.iloc[index]
        current_long = new_longband.iloc[index]
        current_short = new_shortband.iloc[index]
        if pd.isna(current_rsi) or pd.isna(current_long) or pd.isna(current_short):
            trend.iloc[index] = trend.iloc[index - 1] if index > 0 else 1
            continue

        if index == 0 or pd.isna(longband.iloc[index - 1]):
            longband.iloc[index] = current_long
        elif rsi_ma.iloc[index - 1] > longband.iloc[index - 1] and current_rsi > longband.iloc[index - 1]:
            longband.iloc[index] = max(longband.iloc[index - 1], current_long)
        else:
            longband.iloc[index] = current_long

        if index == 0 or pd.isna(shortband.iloc[index - 1]):
            shortband.iloc[index] = current_short
        elif rsi_ma.iloc[index - 1] < shortband.iloc[index - 1] and current_rsi < shortband.iloc[index - 1]:
            shortband.iloc[index] = min(shortband.iloc[index - 1], current_short)
        else:
            shortband.iloc[index] = current_short

        previous_trend = trend.iloc[index - 1] if index > 0 else 1
        if index >= 2 and _crossed(
            rsi_ma.iloc[index - 1],
            current_rsi,
            shortband.iloc[index - 2],
            shortband.iloc[index - 1],
        ):
            trend.iloc[index] = 1
        elif index >= 2 and _crossed(
            longband.iloc[index - 2],
            longband.iloc[index - 1],
            rsi_ma.iloc[index - 1],
            current_rsi,
        ):
            trend.iloc[index] = -1
        else:
            trend.iloc[index] = previous_trend

        trail.iloc[index] = longband.iloc[index] if trend.iloc[index] == 1 else shortband.iloc[index]

    return {"rsi_ma": rsi_ma, "trail": trail, "trend": trend}


def _wilder_rsi(source: pd.Series, length: int) -> pd.Series:
    delta = source.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    average_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    average_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    relative_strength = average_gain / average_loss
    rsi = 100.0 - (100.0 / (1.0 + relative_strength))
    rsi = rsi.mask((average_loss == 0) & (average_gain > 0), 100.0)
    rsi = rsi.mask((average_gain == 0) & (average_loss > 0), 0.0)
    rsi = rsi.mask((average_gain == 0) & (average_loss == 0), 50.0)
    return rsi


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def _crossed(
    previous_left: float,
    current_left: float,
    previous_right: float,
    current_right: float,
) -> bool:
    if any(pd.isna(value) for value in [previous_left, current_left, previous_right, current_right]):
        return False
    return (previous_left <= previous_right and current_left > current_right) or (
        previous_left >= previous_right and current_left < current_right
    )


def _validate_qqe_mod_input(
    dataframe: DataFrame,
    source: str,
    rsi_length: int,
    rsi_smoothing: int,
    qqe_factor: float,
    bollinger_length: int,
    bollinger_multiplier: float,
    secondary_rsi_length: int,
    secondary_rsi_smoothing: int,
    secondary_qqe_factor: float,
    threshold: float,
) -> None:
    if source not in dataframe.columns:
        raise ValueError(f"QQE MOD source column is missing: {source}")
    integer_params = {
        "rsi_length": rsi_length,
        "rsi_smoothing": rsi_smoothing,
        "bollinger_length": bollinger_length,
        "secondary_rsi_length": secondary_rsi_length,
        "secondary_rsi_smoothing": secondary_rsi_smoothing,
    }
    invalid_integer_params = [
        name for name, value in integer_params.items() if not isinstance(value, int) or value < 1
    ]
    if invalid_integer_params:
        names = ", ".join(invalid_integer_params)
        raise ValueError(f"QQE MOD integer parameters must be >= 1: {names}")
    positive_params = {
        "qqe_factor": qqe_factor,
        "bollinger_multiplier": bollinger_multiplier,
        "secondary_qqe_factor": secondary_qqe_factor,
        "threshold": threshold,
    }
    invalid_positive_params = [
        name for name, value in positive_params.items() if not np.isfinite(value) or value <= 0
    ]
    if invalid_positive_params:
        names = ", ".join(invalid_positive_params)
        raise ValueError(f"QQE MOD positive parameters must be finite and > 0: {names}")
```

- [ ] **Step 4: Run shared QQE MOD tests and verify GREEN**

Run:

```powershell
pytest tests/indicators/test_qqe_mod.py -q
```

Expected: PASS.

- [ ] **Step 5: Run all shared indicator tests**

Run:

```powershell
pytest tests/indicators/test_supertrend.py tests/indicators/test_qqe_mod.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

Run:

```powershell
git add freqtrade/indicators/qqe_mod.py tests/indicators/test_qqe_mod.py
git commit -m "feat: add shared QQE MOD indicator"
```

---

### Task 3: Add QQE MOD API Schema

**Files:**
- Modify: `freqtrade/freqtrade/rpc/api_server/api_schemas.py`
- Modify: `freqtrade/tests/rpc/test_chart_indicators.py`
- Modify: `freqtrade/tests/rpc/test_rpc_apiserver.py`

- [ ] **Step 1: Add schema tests for QQE MOD defaults and validation**

Append these tests to `freqtrade/tests/rpc/test_chart_indicators.py`:

```python
from freqtrade.rpc.api_server.api_schemas import QqeModIndicatorRequest


def test_chart_indicator_request_includes_default_qqe_mod():
    indicators = ChartIndicatorRequest()

    assert len(indicators.qqe_mod) == 1
    assert indicators.qqe_mod[0].rsi_length == 6
    assert indicators.qqe_mod[0].rsi_smoothing == 5
    assert indicators.qqe_mod[0].qqe_factor == pytest.approx(3.0)
    assert indicators.qqe_mod[0].bollinger_length == 50
    assert indicators.qqe_mod[0].bollinger_multiplier == pytest.approx(0.35)
    assert indicators.qqe_mod[0].secondary_qqe_factor == pytest.approx(1.61)
    assert indicators.qqe_mod[0].threshold == pytest.approx(3.0)
    assert indicators.qqe_mod[0].source == "close"


def test_chart_indicator_request_accepts_empty_qqe_mod():
    indicators = ChartIndicatorRequest(qqe_mod=[])

    assert indicators.qqe_mod == []


def test_invalid_qqe_mod_period_fails_schema():
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        QqeModIndicatorRequest(rsi_length=0)


def test_invalid_qqe_mod_factor_fails_schema():
    with pytest.raises(ValueError, match="greater than 0"):
        QqeModIndicatorRequest(qqe_factor=0)


def test_invalid_qqe_mod_threshold_fails_schema():
    with pytest.raises(ValueError, match="greater than 0"):
        QqeModIndicatorRequest(threshold=0)
```

In `test_add_watch_indicators_accepts_empty_request`, change the request construction to:

```python
indicators = ChartIndicatorRequest(ma=[], rsi=[], macd=[], supertrend=[], qqe_mod=[])
```

- [ ] **Step 2: Add API payload validation test**

In `freqtrade/tests/rpc/test_rpc_apiserver.py`, extend the existing `test_chart_candles_schema_validation` parameter list with this payload:

```python
{
    "pair": "XRP/BTC",
    "timeframe": "5m",
    "watch_indicators": {"qqe_mod": [{"rsi_length": 0}]},
}
```

Expected result for this case remains an API validation error.

- [ ] **Step 3: Run schema tests and verify RED**

Run:

```powershell
pytest tests/rpc/test_chart_indicators.py::test_chart_indicator_request_includes_default_qqe_mod tests/rpc/test_chart_indicators.py::test_invalid_qqe_mod_period_fails_schema -q
```

Expected: FAIL with import error for `QqeModIndicatorRequest` or missing `qqe_mod`.

- [ ] **Step 4: Add `QqeModIndicatorRequest` to API schemas**

In `freqtrade/freqtrade/rpc/api_server/api_schemas.py`, add this class after `SupertrendIndicatorRequest`:

```python
class QqeModIndicatorRequest(BaseModel):
    rsi_length: int = Field(default=6, ge=1, le=500)
    rsi_smoothing: int = Field(default=5, ge=1, le=500)
    qqe_factor: float = Field(default=3.0, gt=0, le=100)
    bollinger_length: int = Field(default=50, ge=1, le=1000)
    bollinger_multiplier: float = Field(default=0.35, gt=0, le=100)
    secondary_rsi_length: int = Field(default=6, ge=1, le=500)
    secondary_rsi_smoothing: int = Field(default=5, ge=1, le=500)
    secondary_qqe_factor: float = Field(default=1.61, gt=0, le=100)
    threshold: float = Field(default=3.0, gt=0, le=100)
    source: str = Field(default="close", min_length=1, max_length=64)
```

Then add this field to `ChartIndicatorRequest`:

```python
qqe_mod: list[QqeModIndicatorRequest] = Field(
    default_factory=lambda: [QqeModIndicatorRequest()]
)
```

- [ ] **Step 5: Run schema tests and verify GREEN**

Run:

```powershell
pytest tests/rpc/test_chart_indicators.py::test_chart_indicator_request_includes_default_qqe_mod tests/rpc/test_chart_indicators.py::test_chart_indicator_request_accepts_empty_qqe_mod tests/rpc/test_chart_indicators.py::test_invalid_qqe_mod_period_fails_schema tests/rpc/test_chart_indicators.py::test_invalid_qqe_mod_factor_fails_schema tests/rpc/test_chart_indicators.py::test_invalid_qqe_mod_threshold_fails_schema -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

Run:

```powershell
git add freqtrade/rpc/api_server/api_schemas.py tests/rpc/test_chart_indicators.py tests/rpc/test_rpc_apiserver.py
git commit -m "feat: add QQE MOD chart indicator schema"
```

---

### Task 4: Move Chart Supertrend Adapter to Shared Indicator

**Files:**
- Modify: `freqtrade/freqtrade/rpc/chart_indicators.py`
- Modify: `freqtrade/tests/rpc/test_chart_indicators.py`

- [ ] **Step 1: Update chart indicator tests to keep Supertrend behavior stable**

Keep the existing Supertrend tests in `freqtrade/tests/rpc/test_chart_indicators.py`. The Task 1 shared tests already cover the algorithm. No new test name is required here; the existing tests must keep passing after the adapter stops owning `_calculate_supertrend`.

- [ ] **Step 2: Run chart indicator Supertrend tests before editing**

Run:

```powershell
pytest tests/rpc/test_chart_indicators.py::test_supertrend_matches_expected_bands_after_direction_transition tests/rpc/test_chart_indicators.py::test_supertrend_populates_only_one_direction_per_candle -q
```

Expected: PASS before the refactor.

- [ ] **Step 3: Import shared Supertrend and remove local algorithm ownership**

In `freqtrade/freqtrade/rpc/chart_indicators.py`, add:

```python
from freqtrade.indicators.supertrend import add_supertrend
```

Remove the `import pandas as pd` line if it becomes unused after deleting `_calculate_supertrend`.

Replace the Supertrend loop in `add_watch_indicators` with:

```python
    for supertrend_config in indicators.supertrend:
        prefix = _supertrend_column_prefix(supertrend_config)
        result = add_supertrend(
            result,
            period=supertrend_config.period,
            multiplier=supertrend_config.multiplier,
            prefix=prefix,
        )
```

Replace `_supertrend_column_names` with:

```python
def _supertrend_column_prefix(supertrend_config: SupertrendIndicatorRequest) -> str:
    if _supertrend_period(supertrend_config) == DEFAULT_SUPERTREND_PERIOD:
        return "watch_supertrend"

    suffix = (
        f"_{supertrend_config.period}_"
        f"{_supertrend_multiplier_suffix(supertrend_config.multiplier)}"
    )
    return f"watch_supertrend{suffix}"


def _supertrend_column_names(
    supertrend_config: SupertrendIndicatorRequest,
) -> tuple[str, str, str]:
    prefix = _supertrend_column_prefix(supertrend_config)
    return f"{prefix}_up", f"{prefix}_down", f"{prefix}_price"
```

Delete the local `_calculate_supertrend` function from `chart_indicators.py`.

- [ ] **Step 4: Run chart indicator tests and verify GREEN**

Run:

```powershell
pytest tests/rpc/test_chart_indicators.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

Run:

```powershell
git add freqtrade/rpc/chart_indicators.py tests/rpc/test_chart_indicators.py
git commit -m "refactor: use shared supertrend for chart indicators"
```

---

### Task 5: Add QQE MOD to Chart Watch Indicators

**Files:**
- Modify: `freqtrade/freqtrade/rpc/chart_indicators.py`
- Modify: `freqtrade/tests/rpc/test_chart_indicators.py`

- [ ] **Step 1: Add chart adapter tests for QQE MOD columns and plot config**

Update `test_add_watch_indicators_uses_default_columns` in `freqtrade/tests/rpc/test_chart_indicators.py` to assert these default columns:

```python
    assert "watch_qqe_mod_trend" in result.columns
    assert "watch_qqe_mod_hist" in result.columns
    assert "watch_qqe_mod_up" in result.columns
    assert "watch_qqe_mod_down" in result.columns
    assert "watch_qqe_mod_up_state" in result.columns
    assert "watch_qqe_mod_down_state" in result.columns
    assert "watch_qqe_mod_up_event" in result.columns
    assert "watch_qqe_mod_down_event" in result.columns
    assert result["watch_qqe_mod_hist"].notna().sum() > 0
```

Update `test_build_watch_plot_config_matches_default_columns` to assert:

```python
    assert set(plot_config["subplots"]["QQE MOD"]) == {
        "watch_qqe_mod_hist",
        "watch_qqe_mod_up",
        "watch_qqe_mod_down",
        "watch_qqe_mod_trend",
    }
    assert plot_config["subplots"]["QQE MOD"]["watch_qqe_mod_hist"]["type"] == "bar"
    assert plot_config["subplots"]["QQE MOD"]["watch_qqe_mod_up"]["color"] == "#22c55e"
    assert plot_config["subplots"]["QQE MOD"]["watch_qqe_mod_down"]["color"] == "#ef4444"
```

Update `test_add_watch_indicators_accepts_custom_periods` to pass `qqe_mod=[]` so that custom MA/RSI/MACD/Supertrend expectations remain scoped:

```python
indicators = ChartIndicatorRequest(
    ma=[10],
    rsi=[7],
    macd=[MacdIndicatorRequest(fast=5, slow=13, signal=4)],
    supertrend=[SupertrendIndicatorRequest(period=7, multiplier=2.5)],
    qqe_mod=[],
)
```

Add this new test:

```python
def test_add_watch_indicators_accepts_custom_qqe_mod_periods():
    dataframe = generate_test_data("15m", 240, "2024-01-01 00:00:00+00:00")
    indicators = ChartIndicatorRequest(
        ma=[],
        rsi=[],
        macd=[],
        supertrend=[],
        qqe_mod=[QqeModIndicatorRequest(rsi_length=7, threshold=4.0)],
    )

    result = add_watch_indicators(dataframe, indicators)

    assert "watch_qqe_mod_hist_7_5_3_50_0_35_6_5_1_61_4_close" in result.columns
    assert "watch_qqe_mod_trend_7_5_3_50_0_35_6_5_1_61_4_close" in result.columns
    assert result["watch_qqe_mod_hist_7_5_3_50_0_35_6_5_1_61_4_close"].notna().sum() > 0
```

Add this new test:

```python
def test_build_watch_plot_config_accepts_custom_qqe_mod_periods():
    indicators = ChartIndicatorRequest(
        ma=[],
        rsi=[],
        macd=[],
        supertrend=[],
        qqe_mod=[QqeModIndicatorRequest(rsi_length=7, threshold=4.0)],
    )

    plot_config = build_watch_plot_config(indicators)

    assert set(plot_config["subplots"]["QQE MOD"]) == {
        "watch_qqe_mod_hist_7_5_3_50_0_35_6_5_1_61_4_close",
        "watch_qqe_mod_up_7_5_3_50_0_35_6_5_1_61_4_close",
        "watch_qqe_mod_down_7_5_3_50_0_35_6_5_1_61_4_close",
        "watch_qqe_mod_trend_7_5_3_50_0_35_6_5_1_61_4_close",
    }
```

- [ ] **Step 2: Run QQE chart adapter tests and verify RED**

Run:

```powershell
pytest tests/rpc/test_chart_indicators.py::test_add_watch_indicators_uses_default_columns tests/rpc/test_chart_indicators.py::test_build_watch_plot_config_matches_default_columns tests/rpc/test_chart_indicators.py::test_add_watch_indicators_accepts_custom_qqe_mod_periods -q
```

Expected: FAIL because chart adapter does not yet add QQE MOD.

- [ ] **Step 3: Import QQE MOD shared helper and schema**

In `freqtrade/freqtrade/rpc/chart_indicators.py`, update imports:

```python
from freqtrade.indicators.qqe_mod import add_qqe_mod
from freqtrade.indicators.supertrend import add_supertrend
from freqtrade.rpc.api_server.api_schemas import (
    ChartIndicatorRequest,
    MacdIndicatorRequest,
    QqeModIndicatorRequest,
    SupertrendIndicatorRequest,
)
```

- [ ] **Step 4: Add QQE MOD defaults and plot config**

Add constants near existing defaults:

```python
DEFAULT_QQE_MOD_PERIOD = (6, 5, 3.0, 50, 0.35, 6, 5, 1.61, 3.0, "close")
QQE_MOD_FIELDS = (
    "trend",
    "hist",
    "up",
    "down",
    "up_state",
    "down_state",
    "up_event",
    "down_event",
)
```

Add this subplot to `DEFAULT_WATCH_PLOT_CONFIG["subplots"]`:

```python
        "QQE MOD": {
            "watch_qqe_mod_hist": {"type": "bar", "color": "#64748b"},
            "watch_qqe_mod_up": {"type": "bar", "color": "#22c55e"},
            "watch_qqe_mod_down": {"type": "bar", "color": "#ef4444"},
            "watch_qqe_mod_trend": {"type": "line", "color": "#eab308"},
        },
```

- [ ] **Step 5: Add QQE MOD calculation to `add_watch_indicators`**

Add this loop after the Supertrend loop:

```python
    for index, qqe_config in enumerate(indicators.qqe_mod):
        columns = _qqe_mod_column_names(qqe_config)
        if _qqe_mod_period(qqe_config) == DEFAULT_QQE_MOD_PERIOD:
            result = add_qqe_mod(
                result,
                rsi_length=qqe_config.rsi_length,
                rsi_smoothing=qqe_config.rsi_smoothing,
                qqe_factor=qqe_config.qqe_factor,
                bollinger_length=qqe_config.bollinger_length,
                bollinger_multiplier=qqe_config.bollinger_multiplier,
                secondary_rsi_length=qqe_config.secondary_rsi_length,
                secondary_rsi_smoothing=qqe_config.secondary_rsi_smoothing,
                secondary_qqe_factor=qqe_config.secondary_qqe_factor,
                threshold=qqe_config.threshold,
                source=qqe_config.source,
                prefix="watch_qqe_mod",
            )
            continue

        temp_prefix = f"__watch_qqe_mod_{index}"
        result = add_qqe_mod(
            result,
            rsi_length=qqe_config.rsi_length,
            rsi_smoothing=qqe_config.rsi_smoothing,
            qqe_factor=qqe_config.qqe_factor,
            bollinger_length=qqe_config.bollinger_length,
            bollinger_multiplier=qqe_config.bollinger_multiplier,
            secondary_rsi_length=qqe_config.secondary_rsi_length,
            secondary_rsi_smoothing=qqe_config.secondary_rsi_smoothing,
            secondary_qqe_factor=qqe_config.secondary_qqe_factor,
            threshold=qqe_config.threshold,
            source=qqe_config.source,
            prefix=temp_prefix,
        )
        result = result.rename(
            columns={f"{temp_prefix}_{field}": columns[field] for field in QQE_MOD_FIELDS}
        )
```

- [ ] **Step 6: Add QQE MOD plot config for explicit non-default requests**

In `build_watch_plot_config`, add:

```python
    if indicators.qqe_mod:
        plot_config["subplots"]["QQE MOD"] = {}
        for qqe_config in indicators.qqe_mod:
            columns = _qqe_mod_column_names(qqe_config)
            plot_config["subplots"]["QQE MOD"][columns["hist"]] = {
                "type": "bar",
                "color": "#64748b",
            }
            plot_config["subplots"]["QQE MOD"][columns["up"]] = {
                "type": "bar",
                "color": "#22c55e",
            }
            plot_config["subplots"]["QQE MOD"][columns["down"]] = {
                "type": "bar",
                "color": "#ef4444",
            }
            plot_config["subplots"]["QQE MOD"][columns["trend"]] = {
                "type": "line",
                "color": "#eab308",
            }
```

- [ ] **Step 7: Add QQE MOD column naming helpers**

Add these helpers near existing column name helpers:

```python
def _qqe_mod_column_names(qqe_config: QqeModIndicatorRequest) -> dict[str, str]:
    if _qqe_mod_period(qqe_config) == DEFAULT_QQE_MOD_PERIOD:
        return {field: f"watch_qqe_mod_{field}" for field in QQE_MOD_FIELDS}

    suffix = "_".join(
        [
            str(qqe_config.rsi_length),
            str(qqe_config.rsi_smoothing),
            _number_suffix(qqe_config.qqe_factor),
            str(qqe_config.bollinger_length),
            _number_suffix(qqe_config.bollinger_multiplier),
            str(qqe_config.secondary_rsi_length),
            str(qqe_config.secondary_rsi_smoothing),
            _number_suffix(qqe_config.secondary_qqe_factor),
            _number_suffix(qqe_config.threshold),
            _source_suffix(qqe_config.source),
        ]
    )
    return {field: f"watch_qqe_mod_{field}_{suffix}" for field in QQE_MOD_FIELDS}


def _qqe_mod_period(
    qqe_config: QqeModIndicatorRequest,
) -> tuple[int, int, float, int, float, int, int, float, float, str]:
    return (
        qqe_config.rsi_length,
        qqe_config.rsi_smoothing,
        _normalized_float(qqe_config.qqe_factor),
        qqe_config.bollinger_length,
        _normalized_float(qqe_config.bollinger_multiplier),
        qqe_config.secondary_rsi_length,
        qqe_config.secondary_rsi_smoothing,
        _normalized_float(qqe_config.secondary_qqe_factor),
        _normalized_float(qqe_config.threshold),
        qqe_config.source,
    )


def _normalized_float(value: float) -> float:
    normalized = float(value)
    if math.isclose(normalized, round(normalized)):
        normalized = float(round(normalized))
    return normalized


def _number_suffix(value: float) -> str:
    return f"{_normalized_float(value):g}".replace(".", "_")


def _source_suffix(source: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in source)
```

Then update `_supertrend_multiplier_suffix` to reuse `_number_suffix`:

```python
def _supertrend_multiplier_suffix(multiplier: float) -> str:
    return _number_suffix(multiplier)
```

Update `_supertrend_period` to reuse `_normalized_float`:

```python
def _supertrend_period(supertrend_config: SupertrendIndicatorRequest) -> tuple[int, float]:
    return supertrend_config.period, _normalized_float(supertrend_config.multiplier)
```

- [ ] **Step 8: Include QQE MOD in default indicator detection**

Update `_is_default_watch_indicators`:

```python
    qqe_mod_periods = tuple(_qqe_mod_period(qqe_config) for qqe_config in indicators.qqe_mod)
    return (
        tuple(indicators.ma) == DEFAULT_MA_PERIODS
        and tuple(indicators.rsi) == DEFAULT_RSI_PERIODS
        and macd_periods == (DEFAULT_MACD_PERIOD,)
        and supertrend_periods == (DEFAULT_SUPERTREND_PERIOD,)
        and qqe_mod_periods == (DEFAULT_QQE_MOD_PERIOD,)
    )
```

- [ ] **Step 9: Run chart indicator tests and verify GREEN**

Run:

```powershell
pytest tests/rpc/test_chart_indicators.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit Task 5**

Run:

```powershell
git add freqtrade/rpc/chart_indicators.py tests/rpc/test_chart_indicators.py
git commit -m "feat: add QQE MOD chart watch indicator"
```

---

### Task 6: Add Chart Response and Frontend Type Coverage

**Files:**
- Modify: `freqtrade/tests/rpc/test_chart_data.py`
- Modify: `frequi/src/types/candleTypes.ts`

- [ ] **Step 1: Add chart response assertions for QQE MOD**

Update `test_build_chart_candles_response_includes_watch_plot_config` in `freqtrade/tests/rpc/test_chart_data.py`:

```python
    assert "QQE MOD" in response["plot_config"]["subplots"]
    assert "watch_qqe_mod_hist" in response["plot_config"]["subplots"]["QQE MOD"]
    assert "watch_qqe_mod_trend" in response["plot_config"]["subplots"]["QQE MOD"]
```

Add this new test:

```python
def test_build_chart_candles_response_includes_qqe_mod_watch_indicator(mocker):
    chart_df = generate_test_data("15m", 260, "2024-01-01 00:00:00+00:00")
    rpc = MagicMock()
    rpc._freqtrade.exchange.get_historic_ohlcv.return_value = chart_df
    rpc._freqtrade.config = {
        "strategy": "StrategyUnderTest",
        "timeframe": "1h",
        "candle_type_def": CandleType.SPOT,
    }
    request = ChartCandlesRequest(
        pair="BTC/USDT", timeframe="15m", limit=50, include_strategy_overlay=False
    )

    response = build_chart_candles_response(rpc, rpc._freqtrade.config, request)

    assert "watch_qqe_mod_hist" in response["columns"]
    assert "watch_qqe_mod_trend" in response["columns"]
    assert "watch_qqe_mod_up" in response["columns"]
    assert "watch_qqe_mod_down" in response["columns"]
    assert "QQE MOD" in response["plot_config"]["subplots"]
    assert any(value is not None for value in _response_column(response, "watch_qqe_mod_hist"))
```

Update `test_build_chart_candles_response_keeps_warmup_for_watch_indicators`:

```python
    assert "watch_qqe_mod_hist" in response["columns"]
    assert any(value is not None for value in _response_column(response, "watch_qqe_mod_hist"))
```

- [ ] **Step 2: Run chart response tests and verify RED or GREEN**

Run:

```powershell
pytest tests/rpc/test_chart_data.py::test_build_chart_candles_response_includes_watch_plot_config tests/rpc/test_chart_data.py::test_build_chart_candles_response_includes_qqe_mod_watch_indicator tests/rpc/test_chart_data.py::test_build_chart_candles_response_keeps_warmup_for_watch_indicators -q
```

Expected: PASS if Task 5 added QQE MOD correctly. If `watch_qqe_mod_hist` is all null in the trimmed response, increase `CHART_WARMUP_CANDLES` in `freqtrade/freqtrade/rpc/chart_data.py` from `120` to `180`, then update `test_load_chart_ohlcv_uses_limit_and_warmup` expected length and since candle count from `620` to `680`.

- [ ] **Step 3: Add FreqUI QQE MOD payload type**

Modify `frequi/src/types/candleTypes.ts` after `ChartSupertrendIndicatorPayload`:

```ts
export interface ChartQqeModIndicatorPayload {
  rsi_length: number;
  rsi_smoothing: number;
  qqe_factor: number;
  bollinger_length: number;
  bollinger_multiplier: number;
  secondary_rsi_length: number;
  secondary_rsi_smoothing: number;
  secondary_qqe_factor: number;
  threshold: number;
  source: string;
}
```

Add `qqe_mod` to `ChartIndicatorPayload`:

```ts
export interface ChartIndicatorPayload {
  ma?: number[];
  rsi?: number[];
  macd?: ChartMacdIndicatorPayload[];
  supertrend?: ChartSupertrendIndicatorPayload[];
  qqe_mod?: ChartQqeModIndicatorPayload[];
}
```

- [ ] **Step 4: Run backend chart response tests**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
pytest tests/rpc/test_chart_data.py tests/rpc/test_chart_indicators.py -q
```

Expected: PASS.

- [ ] **Step 5: Run frontend typecheck**

Run from `G:\AI_Trading\freqtrade-cn\frequi`:

```powershell
pnpm typecheck
```

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

Run from `G:\AI_Trading\freqtrade-cn`:

```powershell
git -C freqtrade add tests/rpc/test_chart_data.py freqtrade/rpc/chart_data.py
git -C freqtrade commit -m "test: cover QQE MOD chart response"
git -C frequi add src/types/candleTypes.ts
git -C frequi commit -m "feat: add QQE MOD chart payload type"
```

If `freqtrade/rpc/chart_data.py` was not changed, omit it from the first `git add`.

---

### Task 7: Full Verification, Docker Rebuild, and Browser Check

**Files:**
- No planned source edits.
- Uses current working tree after Tasks 1-6.

- [ ] **Step 1: Run focused backend tests**

Run from `G:\AI_Trading\freqtrade-cn\freqtrade`:

```powershell
pytest tests/indicators/test_supertrend.py tests/indicators/test_qqe_mod.py tests/rpc/test_chart_indicators.py tests/rpc/test_chart_data.py tests/rpc/test_rpc_apiserver.py -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend verification**

Run from `G:\AI_Trading\freqtrade-cn\frequi`:

```powershell
pnpm typecheck
pnpm exec eslint src/types/candleTypes.ts --quiet
```

Expected: PASS.

- [ ] **Step 3: Rebuild and restart the local container**

Run from `G:\AI_Trading\freqtrade-cn`:

```powershell
docker compose build --progress=plain freqtrade
docker compose up -d freqtrade
docker compose ps freqtrade
```

Expected: `freqtrade-cn` is `Up` and bound to `127.0.0.1:8081->8080/tcp`.

- [ ] **Step 4: Verify API includes QQE MOD**

Run:

```powershell
$body = @{
  pair = "BTC/USDT"
  timeframe = "15m"
  limit = 200
  include_strategy_overlay = $false
  candle_mode = "live"
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8081/api/v1/chart_candles -ContentType "application/json" -Body $body |
  Select-Object -ExpandProperty columns
```

Expected output includes:

```text
watch_qqe_mod_hist
watch_qqe_mod_trend
watch_qqe_mod_up
watch_qqe_mod_down
```

- [ ] **Step 5: Verify in browser**

Use the in-app browser at:

```text
http://127.0.0.1:8081/trade
```

Expected:

- Supertrend still renders on the main candle chart.
- A `QQE MOD` subplot is visible.
- The subplot includes histogram bars and a trend line.
- Switching chart timeframe between `1m`, `15m`, and `1h` reloads QQE MOD for that timeframe.
- Existing strategy overlay and trade markers still render.
- No existing strategy entry or exit behavior is changed by the indicator being available.

- [ ] **Step 6: Final status review**

Run from `G:\AI_Trading\freqtrade-cn`:

```powershell
git status --short
git -C freqtrade status --short
git -C frequi status --short
```

Expected:

- Only intended implementation files are changed or committed.
- Existing unrelated dirty files remain untouched.
- `.superpowers/` remains untracked unless the user explicitly asks to keep or remove it.

