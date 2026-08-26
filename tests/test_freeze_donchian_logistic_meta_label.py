from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tools import freeze_donchian_logistic_meta_label as freezer


def _label_bars() -> pd.DataFrame:
    dates = pd.date_range(freezer.TRAIN_START, periods=577, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "date": dates,
            "open": np.full(577, 100.0),
            "high": np.full(577, 100.0),
            "low": np.full(577, 100.0),
            "close": np.full(577, 100.0),
            "volume": np.full(577, 1.0),
        }
    )


def _training_data() -> tuple[np.ndarray, np.ndarray]:
    generator = np.random.default_rng(20260813)
    matrix = generator.normal(size=(120, len(freezer.FEATURE_ORDER)))
    matrix[:, -1] = 3.0
    target = np.asarray([0, 1] * 60, dtype=np.int64)
    return matrix, target


def _artifact_with_state(state: dict[str, object]) -> dict[str, object]:
    return freezer.finalize_artifact(
        {
            "feature_order": list(freezer.FEATURE_ORDER),
            "model": state,
            "schema_version": 1,
            "status": "FROZEN_TRAIN_ONLY",
        }
    )


def test_training_split_is_start_inclusive_and_strictly_purged_at_cutoff() -> None:
    assert freezer.is_training_decision(freezer.TRAIN_START)
    assert not freezer.is_training_decision(freezer.TRAIN_START - pd.Timedelta(nanoseconds=1))
    assert freezer.is_training_decision(
        freezer.TRAIN_CUTOFF - freezer.HOLD - pd.Timedelta(minutes=5)
    )
    assert not freezer.is_training_decision(freezer.TRAIN_CUTOFF - freezer.HOLD)

    with pytest.raises(freezer.InvalidStage, match="reaches or crosses"):
        freezer.label_event(
            _label_bars(), freezer.TRAIN_CUTOFF - freezer.HOLD, direction=1
        )


def test_label_path_uses_same_bar_stop_first_and_deadline_open_before_range() -> None:
    same_bar = _label_bars()
    same_bar["date"] = same_bar["date"].astype("datetime64[ms, UTC]")
    same_bar.loc[1, ["high", "low"]] = [105.0, 98.0]
    assert freezer.label_event(same_bar, freezer.TRAIN_START, 1) == (0, "stop")

    target_only = _label_bars()
    target_only.loc[1, ["high", "low"]] = [105.0, 99.0]
    assert freezer.label_event(target_only, freezer.TRAIN_START, 1) == (1, "target")

    deadline = _label_bars()
    deadline.loc[576, ["high", "low"]] = [105.0, 98.0]
    assert freezer.label_event(deadline, freezer.TRAIN_START, 1) == (0, "deadline_open")


def test_causal_feature_inputs_are_prefix_invariant() -> None:
    rows = 220
    step = np.arange(rows, dtype=float)
    close = 100.0 * np.exp(0.0004 * step + 0.002 * np.sin(step / 7.0))
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2022-02-01", periods=rows, freq="15min", tz="UTC"),
            "open": close * 0.999,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": 1000.0 + step,
        }
    )
    prefix_length = 180
    prefix = freezer.compute_indicators(frame.iloc[:prefix_length].copy())
    extended = frame.copy()
    extended.loc[prefix_length:, ["open", "high", "low", "close", "volume"]] *= 50.0
    full = freezer.compute_indicators(extended).iloc[:prefix_length]

    pd.testing.assert_frame_equal(prefix, full)


def test_winsor_and_scaler_state_are_learned_from_training_rows_only() -> None:
    matrix, target = _training_data()
    state, _model = freezer.fit_training_state(matrix, target)
    preprocessing = state["preprocessing"]
    assert isinstance(preprocessing, dict)

    expected_lower = np.quantile(matrix, 0.01, axis=0, method="linear")
    expected_upper = np.quantile(matrix, 0.99, axis=0, method="linear")
    clipped = np.clip(matrix, expected_lower, expected_upper)
    expected_mean = clipped.mean(axis=0)
    expected_scale = clipped.std(axis=0, ddof=0)
    expected_scale[expected_scale == 0.0] = 1.0
    np.testing.assert_array_equal(preprocessing["winsor_q01"], expected_lower)
    np.testing.assert_array_equal(preprocessing["winsor_q99"], expected_upper)
    np.testing.assert_array_equal(preprocessing["scaler_mean"], expected_mean)
    np.testing.assert_array_equal(preprocessing["scaler_scale"], expected_scale)

    future_outlier = np.full((20, matrix.shape[1]), 1e12)
    full_upper = np.quantile(
        np.vstack((matrix, future_outlier)), 0.99, axis=0, method="linear"
    )
    assert not np.array_equal(preprocessing["winsor_q99"], full_upper)
    assert preprocessing["scaler_scale"][-1] == 1.0


def test_artifact_is_canonical_tamper_evident_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    matrix, target = _training_data()
    state, _model = freezer.fit_training_state(matrix, target)
    artifact = _artifact_with_state(state)
    path = tmp_path / "MODEL.json"
    freezer.write_artifact(path, artifact)
    assert freezer.load_artifact(path) == artifact

    with pytest.raises(freezer.InvalidStage, match="refusing to overwrite"):
        freezer.write_artifact(path, artifact)

    tampered = freezer.load_artifact(path)
    model = tampered["model"]
    assert isinstance(model, dict)
    model["coef"][0][0] += 1.0
    path.write_bytes(freezer.canonical_json_bytes(tampered) + b"\n")
    with pytest.raises(freezer.InvalidStage, match="semantic SHA-256 mismatch"):
        freezer.load_artifact(path)


def test_pure_numpy_probability_matches_sklearn() -> None:
    matrix, target = _training_data()
    state, model = freezer.fit_training_state(matrix, target)
    artifact = _artifact_with_state(state)
    standardized = freezer._preprocess_from_state(state, matrix)
    expected = model.predict_proba(standardized)[:, 1]
    actual = freezer.predict_probability_numpy(artifact, matrix)
    np.testing.assert_allclose(actual, expected, rtol=1e-13, atol=1e-15)
