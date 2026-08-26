from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import warnings
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression

REPO_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "research_data"
    / "donchian-logistic-meta-label"
)
PREREGISTRATION = RESEARCH_ROOT / "PREREGISTRATION.md"
ARTIFACT = RESEARCH_ROOT / "MODEL.json"
F3_ROOT = RESEARCH_ROOT.parent / "donchian-funding-rv"
F3_FREEZE = F3_ROOT / "FREEZE.json"
F3_MANIFEST = F3_ROOT / "development-data" / "manifest.json"
F3_RUNNER = REPO_ROOT / "tools" / "run_donchian_funding_rv_research.py"
DATA_PATHS = {
    "15m": F3_ROOT / "development-data" / "BTC_USDT_USDT-15m-futures.feather",
    "5m": F3_ROOT / "development-data" / "BTC_USDT_USDT-5m-futures.feather",
    "funding": F3_ROOT / "development-data" / "BTC_USDT_USDT-1h-funding_rate.feather",
}

EXPECTED_PREREGISTRATION_SHA256 = (
    "e405d7c01ae53e2ad1b39bfd94058c88cf7351f2579a467cf9f9eafcab06881d"
)
EXPECTED_F3_FREEZE_SHA256 = (
    "2dc650975aabb81f1e8e44c3cdc12502b4f13a1664698546b51c5e36e1d6dfb7"
)
PHYSICAL_CUTOFF = pd.Timestamp("2024-01-01T00:00:00Z")
TRAIN_START = pd.Timestamp("2022-03-01T00:00:00Z")
TRAIN_CUTOFF = pd.Timestamp("2023-01-01T00:00:00Z")
HOLD = pd.Timedelta(hours=48)
FUNDING_MAX_AGE = pd.Timedelta(hours=10)
MIN_TRAIN_SAMPLES = 100
MIN_CLASS_SAMPLES = 20

FEATURE_ORDER = (
    "funding_tailwind",
    "rv24",
    "breakout_atr",
    "clv_side",
    "body_atr_side",
    "log_relative_volume",
    "return_1_side",
    "momentum_16_side",
    "donchian_width",
    "ema96_distance_side",
)
FEATURE_FORMULAS = {
    "funding_tailwind": "-d*f_tau",
    "rv24": "sqrt(sum(ln(C_i/C_i-1)^2,i=t-95..t))",
    "breakout_atr": "d*(C_t-B_t)/ATR14_t",
    "clv_side": "d*clip((2*C_t-H_t-L_t)/(H_t-L_t),-1,1)",
    "body_atr_side": "d*(C_t-O_t)/ATR14_t",
    "log_relative_volume": "ln(V_t/mean(V_t-96..V_t-1))",
    "return_1_side": "d*ln(C_t/C_t-1)",
    "momentum_16_side": "d*ln(C_t/C_t-16)",
    "donchian_width": "(U_t-L_t)/C_t",
    "ema96_distance_side": "d*ln(C_t/EMA96_t)",
}
MODEL_SETTINGS = {
    "C": 1.0,
    "class_weight": "balanced",
    "fit_intercept": True,
    "max_iter": 1000,
    "penalty": "l2",
    "solver": "lbfgs",
    "threshold": 0.5,
    "tol": 1e-4,
}
EXPECTED_COLUMNS = ("date", "open", "high", "low", "close", "volume")


class InvalidStage(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise InvalidStage("artifact contains a non-JSON or nonfinite value") from error
    return encoded.encode("utf-8")


def _semantic_sha256(artifact: Mapping[str, object]) -> str:
    semantic = dict(artifact)
    semantic.pop("semantic_sha256", None)
    return hashlib.sha256(canonical_json_bytes(semantic)).hexdigest()


def finalize_artifact(payload: Mapping[str, object]) -> dict[str, object]:
    artifact = deepcopy(dict(payload))
    if "semantic_sha256" in artifact:
        raise InvalidStage("semantic_sha256 must be generated, not supplied")
    artifact["semantic_sha256"] = _semantic_sha256(artifact)
    canonical_json_bytes(artifact)
    return artifact


def verify_artifact(artifact: Mapping[str, object]) -> dict[str, object]:
    result = deepcopy(dict(artifact))
    provided = result.get("semantic_sha256")
    if not isinstance(provided, str) or provided != _semantic_sha256(result):
        raise InvalidStage("artifact semantic SHA-256 mismatch")
    if result.get("schema_version") != 1 or result.get("status") != "FROZEN_TRAIN_ONLY":
        raise InvalidStage("artifact schema or status is not frozen")
    if result.get("feature_order") != list(FEATURE_ORDER):
        raise InvalidStage("artifact feature order differs from the frozen order")
    return result


def load_artifact(path: Path) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        artifact = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                InvalidStage(f"artifact contains forbidden constant {value}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidStage("artifact is unreadable strict JSON") from error
    if not isinstance(artifact, dict):
        raise InvalidStage("artifact root is not an object")
    if raw != canonical_json_bytes(artifact) + b"\n":
        raise InvalidStage("artifact is not canonical JSON")
    return verify_artifact(artifact)


def write_artifact(path: Path, artifact: Mapping[str, object]) -> None:
    verified = verify_artifact(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write((canonical_json_bytes(verified) + b"\n").decode("utf-8"))
    except FileExistsError as error:
        raise InvalidStage(f"refusing to overwrite existing artifact: {path}") from error


def _read_json_object(path: Path, name: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InvalidStage(f"{name} is unreadable") from error
    if not isinstance(value, dict):
        raise InvalidStage(f"{name} root is not an object")
    return value


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def verify_sources() -> dict[str, dict[str, str]]:
    if sha256_file(PREREGISTRATION) != EXPECTED_PREREGISTRATION_SHA256:
        raise InvalidStage("preregistration SHA-256 mismatch")
    if sha256_file(F3_FREEZE) != EXPECTED_F3_FREEZE_SHA256:
        raise InvalidStage("frozen F3 authority SHA-256 mismatch")

    freeze = _read_json_object(F3_FREEZE, "F3 FREEZE.json")
    if freeze.get("schema_version") != 1 or freeze.get("status") != "FROZEN":
        raise InvalidStage("F3 freeze schema or status differs from the frozen authority")
    bindings = freeze.get("bindings")
    execution_inputs = freeze.get("execution_inputs")
    if not isinstance(bindings, dict) or not isinstance(execution_inputs, dict):
        raise InvalidStage("F3 freeze bindings or execution inputs are malformed")

    required_bindings = {
        "development_manifest": F3_MANIFEST,
        "runner": F3_RUNNER,
        "preregistration": F3_ROOT / "PREREGISTRATION.md",
        "preparer": REPO_ROOT / "tools" / "prepare_donchian_funding_rv_development_data.py",
        "tests": REPO_ROOT / "tests" / "test_donchian_funding_rv_research.py",
    }
    if set(bindings) != set(required_bindings):
        raise InvalidStage("F3 freeze binding roles differ from the frozen set")
    for role, path in required_bindings.items():
        item = bindings[role]
        if not isinstance(item, dict):
            raise InvalidStage(f"F3 freeze binding {role} is malformed")
        if item.get("path") != _relative(path) or item.get("sha256") != sha256_file(path):
            raise InvalidStage(f"F3 freeze binding {role} identity mismatch")

    if set(execution_inputs) != set(DATA_PATHS):
        raise InvalidStage("F3 execution input roles differ from the frozen set")
    data_hashes: dict[str, str] = {}
    for role, path in DATA_PATHS.items():
        item = execution_inputs[role]
        if not isinstance(item, dict):
            raise InvalidStage(f"F3 execution input {role} is malformed")
        actual = sha256_file(path)
        if item.get("path") != _relative(path) or item.get("sha256") != actual:
            raise InvalidStage(f"F3 execution input {role} identity mismatch")
        data_hashes[role] = actual

    manifest = _read_json_object(F3_MANIFEST, "F3 development manifest")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("purpose") != "physical-development-snapshot-only"
        or manifest.get("cutoff_exclusive") != PHYSICAL_CUTOFF.isoformat()
    ):
        raise InvalidStage("F3 development manifest contract mismatch")
    derived = manifest.get("derived_snapshot")
    if not isinstance(derived, dict) or set(derived) != set(DATA_PATHS):
        raise InvalidStage("F3 development manifest roles differ from the frozen set")
    for role, path in DATA_PATHS.items():
        item = derived[role]
        if not isinstance(item, dict):
            raise InvalidStage(f"F3 manifest derived identity {role} is malformed")
        try:
            first = pd.Timestamp(item["first"])
            last = pd.Timestamp(item["last"])
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidStage(f"F3 manifest timestamps for {role} are invalid") from error
        if (
            item.get("path") != _relative(path)
            or item.get("sha256") != data_hashes[role]
            or not isinstance(item.get("rows"), int)
            or item["rows"] <= 0
            or first.tzinfo is None
            or last.tzinfo is None
            or first > last
            or last >= PHYSICAL_CUTOFF
        ):
            raise InvalidStage(f"F3 manifest derived identity {role} mismatch")

    source_hashes = {
        "f3_freeze": sha256_file(F3_FREEZE),
        "f3_manifest": sha256_file(F3_MANIFEST),
        "f3_runner": sha256_file(F3_RUNNER),
        "freezer": sha256_file(Path(__file__)),
        "preregistration": sha256_file(PREREGISTRATION),
    }
    return {"data_hashes": data_hashes, "source_hashes": source_hashes}


def validate_physical_frame(
    frame: pd.DataFrame,
    role: str,
    *,
    frequency: pd.Timedelta | None,
) -> pd.DataFrame:
    if tuple(frame.columns) != EXPECTED_COLUMNS:
        raise InvalidStage(f"{role} schema differs from the frozen OHLCV schema")
    if not isinstance(frame["date"].dtype, pd.DatetimeTZDtype):
        raise InvalidStage(f"{role} dates are not timezone-aware")
    if str(frame["date"].dt.tz) != "UTC":
        raise InvalidStage(f"{role} dates are not UTC")
    if any(not pd.api.types.is_numeric_dtype(frame[column]) for column in EXPECTED_COLUMNS[1:]):
        raise InvalidStage(f"{role} OHLCV columns are not numeric")
    if frame.empty:
        raise InvalidStage(f"{role} input is empty")
    result = frame.copy().reset_index(drop=True)
    if result["date"].duplicated().any() or not result["date"].is_monotonic_increasing:
        raise InvalidStage(f"{role} timestamps are duplicated or out of order")
    if result["date"].max() >= PHYSICAL_CUTOFF:
        raise InvalidStage(f"{role} physical input is not strictly pre-2024")
    values = result.loc[:, EXPECTED_COLUMNS[1:]].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise InvalidStage(f"{role} contains nonfinite system data")
    if role != "funding":
        prices = result.loc[:, ("open", "high", "low", "close")]
        if (prices <= 0.0).any().any():
            raise InvalidStage(f"{role} contains a nonpositive price")
        if (result["high"] < result["low"]).any():
            raise InvalidStage(f"{role} contains high below low")
    if frequency is not None and not result["date"].diff().iloc[1:].eq(frequency).all():
        raise InvalidStage(f"{role} timestamps are not a complete {frequency} sequence")
    return result


def read_training_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    fifteen = validate_physical_frame(
        pd.read_feather(DATA_PATHS["15m"]),
        "15m",
        frequency=pd.Timedelta(minutes=15),
    )
    five = validate_physical_frame(
        pd.read_feather(DATA_PATHS["5m"]),
        "5m",
        frequency=pd.Timedelta(minutes=5),
    )
    funding = validate_physical_frame(
        pd.read_feather(DATA_PATHS["funding"]),
        "funding",
        frequency=None,
    )
    return (
        fifteen.loc[fifteen["date"] < TRAIN_CUTOFF].reset_index(drop=True),
        five.loc[five["date"] < TRAIN_CUTOFF].reset_index(drop=True),
        funding.loc[funding["date"] < TRAIN_CUTOFF, ["date", "open"]].reset_index(
            drop=True
        ),
    )


def wilder_atr14(frame: pd.DataFrame) -> np.ndarray:
    high = frame["high"].to_numpy(dtype=float)
    low = frame["low"].to_numpy(dtype=float)
    close = frame["close"].to_numpy(dtype=float)
    true_range = high - low
    if len(frame) > 1:
        true_range[1:] = np.maximum.reduce(
            (true_range[1:], np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1]))
        )
    result = np.full(len(frame), np.nan)
    if len(frame) >= 14:
        result[13] = float(true_range[:14].mean())
        for index in range(14, len(frame)):
            result[index] = (13.0 * result[index - 1] + true_range[index]) / 14.0
    return result


def sma_seeded_ema96(close: pd.Series) -> np.ndarray:
    values = close.to_numpy(dtype=float)
    result = np.full(len(values), np.nan)
    if len(values) >= 96:
        result[95] = float(values[:96].mean())
        alpha = 2.0 / 97.0
        for index in range(96, len(values)):
            result[index] = alpha * values[index] + (1.0 - alpha) * result[index - 1]
    return result


def compute_indicators(candles_15m: pd.DataFrame) -> pd.DataFrame:
    close = candles_15m["close"].astype(float)
    log_return = np.log(close / close.shift(1))
    result = pd.DataFrame(index=candles_15m.index)
    result["upper"] = candles_15m["high"].rolling(20, min_periods=20).max().shift(1)
    result["lower"] = candles_15m["low"].rolling(20, min_periods=20).min().shift(1)
    result["long_breakout"] = close > result["upper"]
    result["short_breakout"] = close < result["lower"]
    result["first_long"] = result["long_breakout"] & ~result["long_breakout"].shift(
        1, fill_value=False
    )
    result["first_short"] = result["short_breakout"] & ~result["short_breakout"].shift(
        1, fill_value=False
    )
    result["rv24"] = log_return.pow(2).rolling(96, min_periods=96).sum().pow(0.5)
    result["atr14"] = wilder_atr14(candles_15m)
    result["prior_volume96"] = (
        candles_15m["volume"].astype(float).shift(1).rolling(96, min_periods=96).mean()
    )
    result["return_1"] = log_return
    result["momentum_16"] = np.log(close / close.shift(16))
    result["ema96"] = sma_seeded_ema96(close)
    return result


def is_training_decision(decision_time: pd.Timestamp) -> bool:
    return TRAIN_START <= decision_time and decision_time + HOLD < TRAIN_CUTOFF


def _funding_asof(
    funding: pd.DataFrame, decision_time: pd.Timestamp
) -> tuple[float | None, str | None]:
    index = funding["date"].searchsorted(decision_time, side="right") - 1
    if index < 0:
        return None, "funding_missing_or_stale"
    timestamp = funding.at[index, "date"]
    age = decision_time - timestamp
    if age < pd.Timedelta(0) or age > FUNDING_MAX_AGE:
        return None, "funding_missing_or_stale"
    rate = float(funding.at[index, "open"])
    if not math.isfinite(rate):
        raise InvalidStage("funding contains a nonfinite system value")
    return rate, None


def event_features(
    candles: pd.DataFrame,
    indicators: pd.DataFrame,
    funding: pd.DataFrame,
    index: int,
    direction: int,
    decision_time: pd.Timestamp,
) -> tuple[list[float] | None, str | None]:
    row = candles.iloc[index]
    indicator = indicators.iloc[index]
    funding_rate, reason = _funding_asof(funding, decision_time)
    if reason is not None:
        return None, reason
    required = (
        "upper",
        "lower",
        "rv24",
        "atr14",
        "prior_volume96",
        "return_1",
        "momentum_16",
        "ema96",
    )
    if any(pd.isna(indicator[name]) for name in required):
        return None, "missing_lookback"
    high = float(row["high"])
    low = float(row["low"])
    close = float(row["close"])
    volume = float(row["volume"])
    atr = float(indicator["atr14"])
    prior_volume = float(indicator["prior_volume96"])
    ema = float(indicator["ema96"])
    if high == low:
        return None, "zero_candle_range"
    if atr <= 0.0:
        return None, "nonpositive_atr"
    if volume <= 0.0:
        return None, "nonpositive_current_volume"
    if prior_volume <= 0.0:
        return None, "nonpositive_prior_volume"
    if ema <= 0.0:
        return None, "nonpositive_ema"
    boundary = float(indicator["upper"] if direction == 1 else indicator["lower"])
    values = [
        -direction * float(funding_rate),
        float(indicator["rv24"]),
        direction * (close - boundary) / atr,
        direction * float(np.clip((2.0 * close - high - low) / (high - low), -1.0, 1.0)),
        direction * (close - float(row["open"])) / atr,
        math.log(volume / prior_volume),
        direction * float(indicator["return_1"]),
        direction * float(indicator["momentum_16"]),
        (float(indicator["upper"]) - float(indicator["lower"])) / close,
        direction * math.log(close / ema),
    ]
    if not np.isfinite(np.asarray(values, dtype=float)).all():
        return None, "nonfinite_derived_feature"
    return values, None


def label_event(
    candles_5m: pd.DataFrame,
    decision_time: pd.Timestamp,
    direction: int,
) -> tuple[int, str]:
    if direction not in (-1, 1):
        raise InvalidStage("event direction must be +1 or -1")
    deadline = decision_time + HOLD
    if deadline >= TRAIN_CUTOFF:
        raise InvalidStage("label reaches or crosses the training cutoff")
    bars = candles_5m.loc[
        (candles_5m["date"] >= decision_time) & (candles_5m["date"] <= deadline)
    ]
    dates = bars["date"].reset_index(drop=True)
    if (
        len(bars) != 577
        or dates.iloc[0] != decision_time
        or dates.iloc[-1] != deadline
        or not dates.diff().iloc[1:].eq(pd.Timedelta(minutes=5)).all()
    ):
        raise InvalidStage("event lacks the exact complete 577-row 5m label path")
    entry = float(bars.iloc[0]["open"])
    stop = entry * (0.985 if direction == 1 else 1.015)
    target = entry * (1.04 if direction == 1 else 0.96)
    for row in bars.itertuples(index=False):
        if row.date == deadline:
            return 0, "deadline_open"
        stop_gap = row.open <= stop if direction == 1 else row.open >= stop
        if stop_gap:
            return 0, "stop_gap"
        target_gap = row.open >= target if direction == 1 else row.open <= target
        if target_gap:
            return 1, "target_gap"
        stop_hit = row.low <= stop if direction == 1 else row.high >= stop
        if stop_hit:
            return 0, "stop"
        target_hit = row.high >= target if direction == 1 else row.low <= target
        if target_hit:
            return 1, "target"
    raise InvalidStage("label path did not produce a deterministic outcome")


def build_training_matrix(
    candles_15m: pd.DataFrame,
    candles_5m: pd.DataFrame,
    funding: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, dict[str, object], str]:
    indicators = compute_indicators(candles_15m)
    rows: list[list[float]] = []
    labels: list[int] = []
    hash_rows: list[dict[str, object]] = []
    exclusions: Counter[str] = Counter()
    eligible_events = 0
    purged_at_cutoff = 0
    before_start = 0
    for index in range(len(candles_15m)):
        signal_time = candles_15m.at[index, "date"]
        decision_time = signal_time + pd.Timedelta(minutes=15)
        directions: list[int] = []
        if bool(indicators.at[index, "first_long"]):
            directions.append(1)
        if bool(indicators.at[index, "first_short"]):
            directions.append(-1)
        for direction in directions:
            if decision_time < TRAIN_START:
                before_start += 1
                continue
            if decision_time + HOLD >= TRAIN_CUTOFF:
                purged_at_cutoff += 1
                continue
            eligible_events += 1
            values, reason = event_features(
                candles_15m,
                indicators,
                funding,
                index,
                direction,
                decision_time,
            )
            if reason is not None or values is None:
                exclusions[reason or "unknown_complete_case_failure"] += 1
                continue
            label, _exit_reason = label_event(candles_5m, decision_time, direction)
            rows.append(values)
            labels.append(label)
            hash_rows.append(
                {
                    "decision_time": decision_time.isoformat(),
                    "direction": direction,
                    "features": values,
                    "label": label,
                }
            )
    matrix = np.asarray(rows, dtype=float)
    target = np.asarray(labels, dtype=np.int64)
    if matrix.ndim != 2 or matrix.shape[1:] != (len(FEATURE_ORDER),):
        raise InvalidStage("training matrix has no eligible complete-case rows")
    if not np.isfinite(matrix).all():
        raise InvalidStage("training matrix contains nonfinite data")
    summary = {
        "before_start_event_count": before_start,
        "complete_case_excluded_event_count": int(sum(exclusions.values())),
        "eligible_time_event_count": eligible_events,
        "exclusion_reason_counts": dict(sorted(exclusions.items())),
        "purged_at_cutoff_event_count": purged_at_cutoff,
    }
    training_hash = hashlib.sha256(canonical_json_bytes(hash_rows)).hexdigest()
    return matrix, target, summary, training_hash


def fit_training_state(
    matrix: np.ndarray,
    target: np.ndarray,
) -> tuple[dict[str, object], LogisticRegression]:
    matrix = np.asarray(matrix, dtype=float)
    target = np.asarray(target, dtype=np.int64)
    if matrix.ndim != 2 or matrix.shape[1] != len(FEATURE_ORDER):
        raise InvalidStage("training matrix does not have the frozen feature width")
    if len(matrix) < MIN_TRAIN_SAMPLES:
        raise InvalidStage(f"fewer than {MIN_TRAIN_SAMPLES} eligible training samples")
    if not np.isfinite(matrix).all():
        raise InvalidStage("training matrix contains nonfinite data")
    classes, counts = np.unique(target, return_counts=True)
    if classes.tolist() != [0, 1]:
        raise InvalidStage("training labels do not contain exactly classes 0 and 1")
    if (counts < MIN_CLASS_SAMPLES).any():
        raise InvalidStage(f"a class has fewer than {MIN_CLASS_SAMPLES} training samples")

    lower = np.quantile(matrix, 0.01, axis=0, method="linear")
    upper = np.quantile(matrix, 0.99, axis=0, method="linear")
    clipped = np.clip(matrix, lower, upper)
    mean = clipped.mean(axis=0)
    scale = clipped.std(axis=0, ddof=0)
    scale = np.where(scale == 0.0, 1.0, scale)
    standardized = (clipped - mean) / scale
    if not np.isfinite(standardized).all():
        raise InvalidStage("training-only preprocessing produced nonfinite data")

    model = LogisticRegression(
        C=1.0,
        penalty="l2",
        class_weight="balanced",
        solver="lbfgs",
        fit_intercept=True,
        tol=1e-4,
        max_iter=1000,
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        model.fit(standardized, target)
    convergence_warning = any(
        issubclass(item.category, ConvergenceWarning) for item in caught
    )
    n_iter = int(model.n_iter_[0])
    if convergence_warning or n_iter >= MODEL_SETTINGS["max_iter"]:
        raise InvalidStage("logistic regression did not converge within 1000 iterations")
    state = {
        "classes": [int(value) for value in model.classes_],
        "coef": model.coef_.astype(float).tolist(),
        "converged": True,
        "intercept": model.intercept_.astype(float).tolist(),
        "n_iter": [int(value) for value in model.n_iter_],
        "preprocessing": {
            "scale_ddof": 0,
            "scaler_mean": mean.astype(float).tolist(),
            "scaler_scale": scale.astype(float).tolist(),
            "winsor_q01": lower.astype(float).tolist(),
            "winsor_q99": upper.astype(float).tolist(),
            "winsor_quantile_method": "linear",
            "zero_scale_replacement": 1.0,
        },
    }
    return state, model


def _preprocess_from_state(state: Mapping[str, Any], matrix: np.ndarray) -> np.ndarray:
    preprocessing = state["preprocessing"]
    if not isinstance(preprocessing, Mapping):
        raise InvalidStage("artifact preprocessing state is malformed")
    lower = np.asarray(preprocessing["winsor_q01"], dtype=float)
    upper = np.asarray(preprocessing["winsor_q99"], dtype=float)
    mean = np.asarray(preprocessing["scaler_mean"], dtype=float)
    scale = np.asarray(preprocessing["scaler_scale"], dtype=float)
    if any(array.shape != (len(FEATURE_ORDER),) for array in (lower, upper, mean, scale)):
        raise InvalidStage("artifact preprocessing vectors have the wrong width")
    if not all(np.isfinite(array).all() for array in (lower, upper, mean, scale)):
        raise InvalidStage("artifact preprocessing state contains nonfinite values")
    if (scale <= 0.0).any():
        raise InvalidStage("artifact preprocessing scale is not positive")
    return (np.clip(matrix, lower, upper) - mean) / scale


def predict_probability_numpy(
    artifact: Mapping[str, object], matrix: np.ndarray
) -> np.ndarray:
    verified = verify_artifact(artifact)
    raw = np.asarray(matrix, dtype=float)
    if raw.ndim == 1:
        raw = raw.reshape(1, -1)
    if raw.ndim != 2 or raw.shape[1] != len(FEATURE_ORDER) or not np.isfinite(raw).all():
        raise InvalidStage("prediction input is not a finite frozen-width matrix")
    model = verified.get("model")
    if not isinstance(model, Mapping):
        raise InvalidStage("artifact model state is malformed")
    standardized = _preprocess_from_state(model, raw)
    coefficient = np.asarray(model["coef"], dtype=float)
    intercept = np.asarray(model["intercept"], dtype=float)
    if coefficient.shape != (1, len(FEATURE_ORDER)) or intercept.shape != (1,):
        raise InvalidStage("artifact logistic state has the wrong shape")
    score = standardized @ coefficient[0] + intercept[0]
    probability = np.empty_like(score)
    positive = score >= 0.0
    probability[positive] = 1.0 / (1.0 + np.exp(-score[positive]))
    exp_score = np.exp(score[~positive])
    probability[~positive] = exp_score / (1.0 + exp_score)
    return probability


def build_artifact(
    matrix: np.ndarray,
    target: np.ndarray,
    event_summary: Mapping[str, object],
    training_data_sha256: str,
    identities: Mapping[str, Mapping[str, str]],
) -> tuple[dict[str, object], LogisticRegression]:
    state, model = fit_training_state(matrix, target)
    class_counts = {str(label): int((target == label).sum()) for label in (0, 1)}
    payload = {
        "data_hashes": dict(identities["data_hashes"]),
        "feature_formulas": FEATURE_FORMULAS,
        "feature_order": list(FEATURE_ORDER),
        "label": {
            "deadline": "decision_time+48h open before range",
            "entry": "next official 5m open",
            "ordering": ["gap_stop", "gap_target", "intrabar_stop", "intrabar_target"],
            "positive": "target_gap_or_target_first",
            "stop_fraction": 0.015,
            "target_fraction": 0.04,
        },
        "model": {
            **state,
            "library": "sklearn.linear_model.LogisticRegression",
            "settings": MODEL_SETTINGS,
        },
        "preregistration_scope": {
            "cannot_prove_current_profitability": True,
            "exploratory_training_only": True,
            "prospective_data_strictly_after": "2026-08-13",
        },
        "schema_version": 1,
        "software_versions": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "python": platform.python_version(),
            "scikit_learn": sklearn.__version__,
        },
        "source_hashes": dict(identities["source_hashes"]),
        "status": "FROZEN_TRAIN_ONLY",
        "training_data_sha256": training_data_sha256,
        "training_summary": {
            **dict(event_summary),
            "class_counts": class_counts,
            "converged": True,
            "minimum_class_samples": MIN_CLASS_SAMPLES,
            "minimum_train_samples": MIN_TRAIN_SAMPLES,
            "sample_count": len(target),
        },
        "training_window": {
            "decision_time_start_inclusive": TRAIN_START.isoformat(),
            "label_end_cutoff_exclusive": TRAIN_CUTOFF.isoformat(),
            "purge_rule": "decision_time+48h < label_end_cutoff_exclusive",
        },
    }
    return finalize_artifact(payload), model


def run_train_and_freeze(destination: Path = ARTIFACT) -> dict[str, object]:
    if destination.exists():
        raise InvalidStage(f"refusing to overwrite existing artifact: {destination}")
    identities = verify_sources()
    candles_15m, candles_5m, funding = read_training_inputs()
    matrix, target, event_summary, training_hash = build_training_matrix(
        candles_15m, candles_5m, funding
    )
    artifact, _model = build_artifact(
        matrix,
        target,
        event_summary,
        training_hash,
        identities,
    )
    write_artifact(destination, artifact)
    summary = artifact["training_summary"]
    if not isinstance(summary, Mapping):
        raise InvalidStage("internal training summary is malformed")
    return {
        "artifact": _relative(destination) if destination.is_relative_to(REPO_ROOT) else str(destination),
        "artifact_semantic_sha256": artifact["semantic_sha256"],
        "class_counts": summary["class_counts"],
        "converged": summary["converged"],
        "n_iter": artifact["model"]["n_iter"],  # type: ignore[index]
        "sample_count": summary["sample_count"],
        "stage": "train-and-freeze",
    }


def frozen_plan() -> dict[str, object]:
    return {
        "default_fits_model": False,
        "destination": _relative(ARTIFACT),
        "permitted_stage": "train-and-freeze",
        "preregistration_sha256": EXPECTED_PREREGISTRATION_SHA256,
        "prospective_data_strictly_after": "2026-08-13",
        "reports_performance": False,
        "train_cutoff": TRAIN_CUTOFF.isoformat(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Freeze the preregistered 2022-only Donchian logistic meta-label model."
    )
    parser.add_argument("--stage", choices=("train-and-freeze",))
    args = parser.parse_args(argv)
    result = frozen_plan() if args.stage is None else run_train_and_freeze()
    print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
