from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "research_data"
    / "donchian-logistic-meta-label"
)
MODEL_PATH = RESEARCH_ROOT / "MODEL.json"
SHADOW_PREREGISTRATION = RESEARCH_ROOT / "SHADOW_PREREGISTRATION_V7.md"
DATA_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "data"
    / "okx-btc-usdt-swap-full-20260813"
    / "market-data"
    / "futures"
)
SEED_PATHS = {
    "15m": DATA_ROOT / "BTC_USDT_USDT-15m-futures.feather",
    "5m": DATA_ROOT / "BTC_USDT_USDT-5m-futures.feather",
}
SEED_RELATIVE_PATHS = {
    timeframe: path.relative_to(REPO_ROOT).as_posix()
    for timeframe, path in SEED_PATHS.items()
}
F3_DATA_ROOT = RESEARCH_ROOT.parent / "donchian-funding-rv" / "development-data"
F3_PATHS = {
    "15m": F3_DATA_ROOT / "BTC_USDT_USDT-15m-futures.feather",
    "5m": F3_DATA_ROOT / "BTC_USDT_USDT-5m-futures.feather",
}
JOURNAL_PATH = (
    REPO_ROOT / "ft_userdata" / "user_data" / "logs" / "donchian-logistic-shadow.jsonl"
)

MODEL_SHA256 = "160d63c4622620258ac9c76d9bf14ad5c46e579ed971c4caa61d7093aacaad24"
SHADOW_PREREGISTRATION_SHA256 = (
    "7ac3404a0e1b80a8a9896bb0411c23e88c564a6e8ceed5d0aa86fc4f38c962db"
)
SEED_SHA256 = {
    "15m": "078f646d904a2964f66b5f0eb40f8e055396a5a43ed994cb25c8d52710626407",
    "5m": "77b4e092736cf2f4484555e6c3c76db30dbe78508aeb1c03d2aceafdaa948851",
}
MODEL_DATA_SHA256 = {
    "15m": "20b4819b9cb8ad36f8f0c1b439de145d260a9b6f5f82fd4dc2e141efe0c0fc55",
    "5m": "ecf38bd22ea271d665c01ae9f80ea1aee4065e234d5af2183750d8c613bd6ee6",
}
FUNDING_TRAIN_SHA256 = "e068d437bca761d65a5a549d799941a40d1044aa9a19d76954376e5483711cc7"
MODEL_SOURCE_HASHES = {
    "f3_freeze": "2dc650975aabb81f1e8e44c3cdc12502b4f13a1664698546b51c5e36e1d6dfb7",
    "f3_manifest": "5d8b2186d238247b37b637df4caaae009693081bb92f4100b95ce83378ca41f8",
    "f3_runner": "a3723dba47cc95a821b715ae566b57e1a31cb5c0b94b0121a31da17eb6b54e6e",
    "freezer": "b842ad7f9836ec7bc7adf39aad5b9f3cd9fe429be17114c7deeeca2bf68ea912",
    "preregistration": "e405d7c01ae53e2ad1b39bfd94058c88cf7351f2579a467cf9f9eafcab06881d",
}
TRAINING_DATA_SHA256 = "d42255a66766567449e6fd8b2ab72fc2093b80de0d7178ad6d5f51870cb2a34b"

SYMBOL = "BTC/USDT:USDT"
EXCHANGE_ID = "okx"
BOUNDARY = "2026-08-14T00:00:00.000Z"
SEED_ORIGIN = "2022-02-01T00:00:00.000Z"
BOUNDARY_MS = 1_786_665_600_000
SEED_ORIGIN_MS = 1_643_673_600_000
INTERVAL_MS = {"15m": 15 * 60 * 1000, "5m": 5 * 60 * 1000}
SNAPSHOT_CUTOFF_MS = 1_786_579_200_000
FUNDING_MAX_AGE_MS = 10 * 60 * 60 * 1000
HOLD_MS = 48 * 60 * 60 * 1000
LABEL_ROWS = 577
FETCH_LIMIT = 100

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
    "body_atr_side": "d*(C_t-O_t)/ATR14_t",
    "breakout_atr": "d*(C_t-B_t)/ATR14_t",
    "clv_side": "d*clip((2*C_t-H_t-L_t)/(H_t-L_t),-1,1)",
    "donchian_width": "(U_t-L_t)/C_t",
    "ema96_distance_side": "d*ln(C_t/EMA96_t)",
    "funding_tailwind": "-d*f_tau",
    "log_relative_volume": "ln(V_t/mean(V_t-96..V_t-1))",
    "momentum_16_side": "d*ln(C_t/C_t-16)",
    "return_1_side": "d*ln(C_t/C_t-1)",
    "rv24": "sqrt(sum(ln(C_i/C_i-1)^2,i=t-95..t))",
}
EXPECTED_COLUMNS = ("date", "open", "high", "low", "close", "volume")
WINDOWS_GENERIC_READ = 0x80000000
WINDOWS_GENERIC_WRITE = 0x40000000
WINDOWS_CREATE_NEW = 1
WINDOWS_FILE_FLAG_WRITE_THROUGH = 0x80000000


class ShadowError(RuntimeError):
    pass


class NetworkDeferred(RuntimeError):
    pass


@dataclass(frozen=True)
class _ReplayContext:
    candles_15m: pd.DataFrame
    indicators_15m: pd.DataFrame
    dates_15m_ms: np.ndarray
    journal_15m_timestamps: tuple[int, ...]
    journal_15m_max_positions: np.ndarray
    journal_15m_max_observed: np.ndarray
    seed_15m_last_ms: int
    candles_5m: pd.DataFrame
    dates_5m_ms: np.ndarray
    observations_5m: Mapping[int, tuple[int, int]]


def canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ShadowError("value is not finite canonical JSON") from error


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ShadowError(f"required file is unreadable: {path}") from error
    return digest.hexdigest()


def semantic_sha256(artifact: Mapping[str, object]) -> str:
    value = dict(artifact)
    value.pop("semantic_sha256", None)
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _keys(value: object, expected: set[str], name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ShadowError(f"MODEL.json {name} schema mismatch")
    return value


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ShadowError(f"MODEL.json {name} must be an integer >= {minimum}")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ShadowError(f"MODEL.json {name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ShadowError(f"MODEL.json {name} must be finite")
    return result


def _vector(value: object, name: str, width: int = len(FEATURE_ORDER)) -> list[float]:
    if not isinstance(value, list) or len(value) != width:
        raise ShadowError(f"MODEL.json {name} width mismatch")
    return [_number(item, f"{name}[{index}]") for index, item in enumerate(value)]


def _hash(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ShadowError(f"MODEL.json {name} is not a lowercase SHA-256")
    return value


def validate_model(artifact: object) -> dict[str, object]:
    root = _keys(
        artifact,
        {
            "data_hashes",
            "feature_formulas",
            "feature_order",
            "label",
            "model",
            "preregistration_scope",
            "schema_version",
            "semantic_sha256",
            "software_versions",
            "source_hashes",
            "status",
            "training_data_sha256",
            "training_summary",
            "training_window",
        },
        "root",
    )
    if _integer(root["schema_version"], "schema_version", minimum=1) != 1:
        raise ShadowError("MODEL.json schema_version is not 1")
    if root["status"] != "FROZEN_TRAIN_ONLY":
        raise ShadowError("MODEL.json status is not frozen")
    if root["feature_order"] != list(FEATURE_ORDER):
        raise ShadowError("MODEL.json feature order mismatch")
    if root["feature_formulas"] != FEATURE_FORMULAS:
        raise ShadowError("MODEL.json feature formulas mismatch")

    data_hashes = _keys(root["data_hashes"], {"15m", "5m", "funding"}, "data_hashes")
    if {key: _hash(value, f"data_hashes.{key}") for key, value in data_hashes.items()} != {
        **MODEL_DATA_SHA256,
        "funding": FUNDING_TRAIN_SHA256,
    }:
        raise ShadowError("MODEL.json frozen data hashes mismatch")

    label = _keys(
        root["label"],
        {"deadline", "entry", "ordering", "positive", "stop_fraction", "target_fraction"},
        "label",
    )
    expected_label = {
        "deadline": "decision_time+48h open before range",
        "entry": "next official 5m open",
        "ordering": ["gap_stop", "gap_target", "intrabar_stop", "intrabar_target"],
        "positive": "target_gap_or_target_first",
    }
    if any(label[key] != value for key, value in expected_label.items()):
        raise ShadowError("MODEL.json label constants mismatch")
    if _number(label["stop_fraction"], "label.stop_fraction") != 0.015:
        raise ShadowError("MODEL.json stop fraction mismatch")
    if _number(label["target_fraction"], "label.target_fraction") != 0.04:
        raise ShadowError("MODEL.json target fraction mismatch")

    model = _keys(
        root["model"],
        {
            "classes",
            "coef",
            "converged",
            "intercept",
            "library",
            "n_iter",
            "preprocessing",
            "settings",
        },
        "model",
    )
    if model["classes"] != [0, 1] or any(type(item) is not int for item in model["classes"]):
        raise ShadowError("MODEL.json classes mismatch")
    if not isinstance(model["coef"], list) or len(model["coef"]) != 1:
        raise ShadowError("MODEL.json coefficient shape mismatch")
    _vector(model["coef"][0], "model.coef[0]")
    _vector(model["intercept"], "model.intercept", 1)
    if model["converged"] is not True:
        raise ShadowError("MODEL.json model is not converged")
    if model["library"] != "sklearn.linear_model.LogisticRegression":
        raise ShadowError("MODEL.json library mismatch")
    n_iter = _vector_of_integers(model["n_iter"], "model.n_iter", width=1, minimum=1)

    settings = _keys(
        model["settings"],
        {"C", "class_weight", "fit_intercept", "max_iter", "penalty", "solver", "threshold", "tol"},
        "model.settings",
    )
    if (
        _number(settings["C"], "model.settings.C") != 1.0
        or settings["class_weight"] != "balanced"
        or settings["fit_intercept"] is not True
        or _integer(settings["max_iter"], "model.settings.max_iter", minimum=1) != 1000
        or settings["penalty"] != "l2"
        or settings["solver"] != "lbfgs"
        or _number(settings["threshold"], "model.settings.threshold") != 0.5
        or _number(settings["tol"], "model.settings.tol") != 0.0001
        or n_iter[0] >= 1000
    ):
        raise ShadowError("MODEL.json logistic settings mismatch")

    preprocessing = _keys(
        model["preprocessing"],
        {
            "scale_ddof",
            "scaler_mean",
            "scaler_scale",
            "winsor_q01",
            "winsor_q99",
            "winsor_quantile_method",
            "zero_scale_replacement",
        },
        "model.preprocessing",
    )
    if _integer(preprocessing["scale_ddof"], "model.preprocessing.scale_ddof") != 0:
        raise ShadowError("MODEL.json scaler ddof mismatch")
    if preprocessing["winsor_quantile_method"] != "linear":
        raise ShadowError("MODEL.json winsor method mismatch")
    if _number(preprocessing["zero_scale_replacement"], "zero_scale_replacement") != 1.0:
        raise ShadowError("MODEL.json zero-scale replacement mismatch")
    lower = _vector(preprocessing["winsor_q01"], "model.preprocessing.winsor_q01")
    upper = _vector(preprocessing["winsor_q99"], "model.preprocessing.winsor_q99")
    _vector(preprocessing["scaler_mean"], "model.preprocessing.scaler_mean")
    scale = _vector(preprocessing["scaler_scale"], "model.preprocessing.scaler_scale")
    if any(left > right for left, right in zip(lower, upper, strict=True)) or any(
        value <= 0.0 for value in scale
    ):
        raise ShadowError("MODEL.json preprocessing bounds or scales are invalid")

    scope = _keys(
        root["preregistration_scope"],
        {"cannot_prove_current_profitability", "exploratory_training_only", "prospective_data_strictly_after"},
        "preregistration_scope",
    )
    if scope != {
        "cannot_prove_current_profitability": True,
        "exploratory_training_only": True,
        "prospective_data_strictly_after": "2026-08-13",
    } or any(
        type(scope[key]) is not bool
        for key in ("cannot_prove_current_profitability", "exploratory_training_only")
    ):
        raise ShadowError("MODEL.json preregistration scope mismatch")

    versions = _keys(root["software_versions"], {"numpy", "pandas", "python", "scikit_learn"}, "software_versions")
    if any(not isinstance(value, str) or not value for value in versions.values()):
        raise ShadowError("MODEL.json software versions are malformed")
    source_hashes = _keys(
        root["source_hashes"],
        {"f3_freeze", "f3_manifest", "f3_runner", "freezer", "preregistration"},
        "source_hashes",
    )
    validated_source_hashes = {
        key: _hash(value, f"source_hashes.{key}") for key, value in source_hashes.items()
    }
    if validated_source_hashes != MODEL_SOURCE_HASHES:
        raise ShadowError("MODEL.json frozen source hashes mismatch")
    if _hash(root["training_data_sha256"], "training_data_sha256") != TRAINING_DATA_SHA256:
        raise ShadowError("MODEL.json frozen training data hash mismatch")

    summary = _keys(
        root["training_summary"],
        {
            "before_start_event_count",
            "class_counts",
            "complete_case_excluded_event_count",
            "converged",
            "eligible_time_event_count",
            "exclusion_reason_counts",
            "minimum_class_samples",
            "minimum_train_samples",
            "purged_at_cutoff_event_count",
            "sample_count",
        },
        "training_summary",
    )
    counts = _keys(summary["class_counts"], {"0", "1"}, "training_summary.class_counts")
    count_values = [_integer(counts[key], f"class_counts.{key}") for key in ("0", "1")]
    sample_count = _integer(summary["sample_count"], "training_summary.sample_count", minimum=1)
    if sum(count_values) != sample_count or summary["converged"] is not True:
        raise ShadowError("MODEL.json training counts are incoherent")
    for key in (
        "before_start_event_count",
        "complete_case_excluded_event_count",
        "eligible_time_event_count",
        "purged_at_cutoff_event_count",
    ):
        _integer(summary[key], f"training_summary.{key}")
    if (
        _integer(summary["minimum_class_samples"], "minimum_class_samples", minimum=1) != 20
        or _integer(summary["minimum_train_samples"], "minimum_train_samples", minimum=1) != 100
    ):
        raise ShadowError("MODEL.json training floors mismatch")
    exclusions = summary["exclusion_reason_counts"]
    if not isinstance(exclusions, Mapping) or any(
        not isinstance(key, str) or not key or _integer(value, f"exclusion.{key}") < 0
        for key, value in exclusions.items()
    ):
        raise ShadowError("MODEL.json exclusion counts are malformed")

    window = _keys(
        root["training_window"],
        {"decision_time_start_inclusive", "label_end_cutoff_exclusive", "purge_rule"},
        "training_window",
    )
    if window != {
        "decision_time_start_inclusive": "2022-03-01T00:00:00+00:00",
        "label_end_cutoff_exclusive": "2023-01-01T00:00:00+00:00",
        "purge_rule": "decision_time+48h < label_end_cutoff_exclusive",
    }:
        raise ShadowError("MODEL.json training window mismatch")
    provided_semantic = _hash(root["semantic_sha256"], "semantic_sha256")
    if provided_semantic != semantic_sha256(root):
        raise ShadowError("MODEL.json semantic SHA-256 mismatch")
    return dict(root)


def _vector_of_integers(
    value: object, name: str, *, width: int, minimum: int
) -> list[int]:
    if not isinstance(value, list) or len(value) != width:
        raise ShadowError(f"MODEL.json {name} width mismatch")
    return [_integer(item, f"{name}[{index}]", minimum=minimum) for index, item in enumerate(value)]


def load_model(path: Path = MODEL_PATH, expected_sha256: str = MODEL_SHA256) -> dict[str, object]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ShadowError("MODEL.json is unreadable") from error
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ShadowError("MODEL.json byte SHA-256 mismatch")
    try:
        artifact = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ShadowError(f"MODEL.json contains forbidden constant {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ShadowError("MODEL.json is not strict UTF-8 JSON") from error
    if raw != canonical_json_bytes(artifact) + b"\n":
        raise ShadowError("MODEL.json is not canonical JSON")
    return validate_model(artifact)


def _iso(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _execution_time_ms(computed_at_ms: int) -> int:
    return (computed_at_ms // INTERVAL_MS["5m"] + 1) * INTERVAL_MS["5m"]


def _clock_ms(clock: Callable[[], datetime]) -> int:
    value = clock()
    if value.tzinfo is None:
        raise ShadowError("clock must return a timezone-aware datetime")
    return int(value.astimezone(UTC).timestamp() * 1000)


def _parse_iso(value: object, name: str) -> int:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ShadowError(f"{name} is not an exact UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ShadowError(f"{name} is not an exact UTC timestamp") from error
    timestamp_ms = int(parsed.timestamp() * 1000)
    if _iso(timestamp_ms) != value:
        raise ShadowError(f"{name} is not canonical millisecond UTC")
    return timestamp_ms


def _validate_frame(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if tuple(frame.columns) != EXPECTED_COLUMNS or frame.empty:
        raise ShadowError(f"{timeframe} seed schema is invalid")
    if not isinstance(frame["date"].dtype, pd.DatetimeTZDtype) or str(frame["date"].dt.tz) != "UTC":
        raise ShadowError(f"{timeframe} seed timestamps are not UTC")
    result = frame.loc[frame["date"] >= pd.Timestamp(SEED_ORIGIN)].copy().reset_index(drop=True)
    if result.empty:
        raise ShadowError(f"{timeframe} seed has no rows at the fixed origin")
    if any(not pd.api.types.is_numeric_dtype(result[column]) for column in EXPECTED_COLUMNS[1:]):
        raise ShadowError(f"{timeframe} seed OHLCV is not numeric")
    values = result.loc[:, EXPECTED_COLUMNS[1:]].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ShadowError(f"{timeframe} seed contains nonfinite values")
    if (result.loc[:, ("open", "high", "low", "close")] <= 0.0).any().any():
        raise ShadowError(f"{timeframe} seed contains nonpositive prices")
    if (
        (result["volume"] < 0.0).any()
        or (result["open"] < result["low"]).any()
        or (result["open"] > result["high"]).any()
        or (result["close"] < result["low"]).any()
        or (result["close"] > result["high"]).any()
    ):
        raise ShadowError(f"{timeframe} seed OHLCV is invalid")
    interval = pd.Timedelta(milliseconds=INTERVAL_MS[timeframe])
    if (
        int(result.iloc[0]["date"].timestamp() * 1000) != SEED_ORIGIN_MS
        or int(result.iloc[-1]["date"].timestamp() * 1000) + INTERVAL_MS[timeframe]
        > SNAPSHOT_CUTOFF_MS
        or not result["date"].diff().iloc[1:].eq(interval).all()
    ):
        raise ShadowError(f"{timeframe} seed boundary or sequence mismatch")
    return result


def load_seed_frames(
    paths: Mapping[str, Path] = SEED_PATHS,
    expected_hashes: Mapping[str, str] = SEED_SHA256,
    overlap_paths: Mapping[str, Path] = F3_PATHS,
) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for timeframe in ("15m", "5m"):
        path = paths[timeframe]
        if sha256_file(path) != expected_hashes[timeframe]:
            raise ShadowError(f"{timeframe} seed byte SHA-256 mismatch")
        try:
            frame = pd.read_feather(path)
        except Exception as error:
            raise ShadowError(f"{timeframe} seed is unreadable") from error
        result[timeframe] = _validate_frame(frame, timeframe)
        overlap_path = overlap_paths[timeframe]
        if sha256_file(overlap_path) != MODEL_DATA_SHA256[timeframe]:
            raise ShadowError(f"{timeframe} F3 overlap byte SHA-256 mismatch")
        try:
            overlap = pd.read_feather(overlap_path)
        except Exception as error:
            raise ShadowError(f"{timeframe} F3 overlap is unreadable") from error
        common = result[timeframe].loc[
            result[timeframe]["date"] <= overlap["date"].iloc[-1]
        ].reset_index(drop=True)
        if not common.equals(overlap.reset_index(drop=True)):
            raise ShadowError(f"{timeframe} full snapshot differs from its F3 overlap")
    return result


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


def compute_indicators(candles: pd.DataFrame) -> pd.DataFrame:
    close = candles["close"].astype(float)
    log_return = np.log(close / close.shift(1))
    result = pd.DataFrame(index=candles.index)
    result["upper"] = candles["high"].rolling(20, min_periods=20).max().shift(1)
    result["lower"] = candles["low"].rolling(20, min_periods=20).min().shift(1)
    result["long_breakout"] = close > result["upper"]
    result["short_breakout"] = close < result["lower"]
    result["first_long"] = result["long_breakout"] & ~result["long_breakout"].shift(
        1, fill_value=False
    )
    result["first_short"] = result["short_breakout"] & ~result["short_breakout"].shift(
        1, fill_value=False
    )
    result["rv24"] = log_return.pow(2).rolling(96, min_periods=96).sum().pow(0.5)
    result["atr14"] = wilder_atr14(candles)
    result["prior_volume96"] = candles["volume"].astype(float).shift(1).rolling(96).mean()
    result["return_1"] = log_return
    result["momentum_16"] = np.log(close / close.shift(16))
    result["ema96"] = sma_seeded_ema96(close)
    return result


def _parse_ohlcv_row(row: object, timeframe: str, observed_at_ms: int) -> dict[str, object]:
    if not isinstance(row, list) or len(row) != 6:
        raise ShadowError(f"malformed {timeframe} fetch_ohlcv row")
    timestamp = _integer(row[0], f"API {timeframe} timestamp")
    if timestamp % INTERVAL_MS[timeframe] != 0:
        raise ShadowError(f"unaligned exact {timeframe} timestamp")
    values = [_number(value, f"API {timeframe} OHLCV") for value in row[1:]]
    opening, high, low, close, volume = values
    if (
        min(opening, high, low, close) <= 0.0
        or not low <= opening <= high
        or not low <= close <= high
        or volume < 0.0
    ):
        raise ShadowError(f"invalid {timeframe} OHLCV response")
    return {
        "close": close,
        "high": high,
        "kind": "candle",
        "low": low,
        "observed_at": _iso(observed_at_ms),
        "open": opening,
        "timeframe": timeframe,
        "timestamp": _iso(timestamp),
        "timestamp_ms": timestamp,
        "volume": volume,
    }


def fetch_closed_ohlcv(
    exchange: object,
    timeframe: str,
    start_ms: int,
    clock: Callable[[], datetime],
    *,
    limit: int = FETCH_LIMIT,
) -> list[dict[str, object]]:
    cursor = start_ms
    records: list[dict[str, object]] = []
    for _page in range(10_000):
        now_ms = _clock_ms(clock)
        last_closed = (now_ms // INTERVAL_MS[timeframe] - 1) * INTERVAL_MS[timeframe]
        if cursor > last_closed:
            return records
        try:
            response = exchange.fetch_ohlcv(SYMBOL, timeframe, since=cursor, limit=limit)
        except Exception as error:
            raise NetworkDeferred(f"{timeframe} fetch_ohlcv failed") from error
        observed_at_ms = _clock_ms(clock)
        if not isinstance(response, list):
            raise ShadowError(f"malformed {timeframe} fetch_ohlcv response")
        parsed = [_parse_ohlcv_row(row, timeframe, observed_at_ms) for row in response]
        if not parsed:
            raise ShadowError(f"incomplete {timeframe} candle history")
        timestamps = [int(record["timestamp_ms"]) for record in parsed]
        if timestamps[0] != cursor or any(
            right - left != INTERVAL_MS[timeframe]
            for left, right in pairwise(timestamps)
        ):
            raise ShadowError(f"{timeframe} response has a gap, duplicate, or revision")
        closed = [
            record
            for record in parsed
            if int(record["timestamp_ms"]) + INTERVAL_MS[timeframe] <= observed_at_ms
        ]
        records.extend(closed)
        if closed:
            cursor = int(closed[-1]["timestamp_ms"]) + INTERVAL_MS[timeframe]
        if len(closed) != len(parsed):
            final_now = _clock_ms(clock)
            expected = (final_now // INTERVAL_MS[timeframe] - 1) * INTERVAL_MS[timeframe]
            if cursor > expected:
                return records
            raise ShadowError(f"incomplete {timeframe} closed-candle response")
    raise ShadowError(f"{timeframe} pagination limit exceeded")


def fetch_funding(
    exchange: object,
    start_ms: int,
    clock: Callable[[], datetime],
    *,
    limit: int = FETCH_LIMIT,
) -> list[dict[str, object]]:
    cursor = start_ms
    records: list[dict[str, object]] = []
    for _page in range(10_000):
        try:
            response = exchange.fetch_funding_rate_history(
                SYMBOL, since=cursor, limit=limit
            )
        except Exception as error:
            raise NetworkDeferred("funding history fetch failed") from error
        observed_at_ms = _clock_ms(clock)
        if not isinstance(response, list):
            raise ShadowError("malformed funding history response")
        if not response:
            return records
        page: list[dict[str, object]] = []
        for item in response:
            if not isinstance(item, Mapping) or "timestamp" not in item or "fundingRate" not in item:
                raise ShadowError("malformed standardized funding observation")
            timestamp = _integer(item["timestamp"], "API funding timestamp")
            rate = _number(item["fundingRate"], "API funding rate")
            if timestamp > observed_at_ms:
                raise ShadowError("funding event timestamp is later than its observation")
            available_at = (observed_at_ms // INTERVAL_MS["15m"] + 1) * INTERVAL_MS["15m"]
            page.append(
                {
                    "available_at": _iso(available_at),
                    "available_at_ms": available_at,
                    "kind": "funding_observation",
                    "observed_at": _iso(observed_at_ms),
                    "rate": rate,
                    "timestamp": _iso(timestamp),
                    "timestamp_ms": timestamp,
                }
            )
        timestamps = [int(record["timestamp_ms"]) for record in page]
        if timestamps[0] < cursor or any(
            right <= left for left, right in pairwise(timestamps)
        ):
            raise ShadowError("funding response timestamps are duplicated or out of order")
        records.extend(page)
        cursor = timestamps[-1] + 1
        if len(response) < limit:
            return records
    raise ShadowError("funding pagination limit exceeded")


def build_header() -> dict[str, object]:
    return {
        "boundary_exclusive": BOUNDARY,
        "exchange": EXCHANGE_ID,
        "kind": "header",
        "model_sha256": MODEL_SHA256,
        "schema_version": 4,
        "seed_origin": SEED_ORIGIN,
        "seed_paths": dict(SEED_RELATIVE_PATHS),
        "seed_sha256": dict(SEED_SHA256),
        "shadow_preregistration_v7_sha256": SHADOW_PREREGISTRATION_SHA256,
        "symbol": SYMBOL,
        "timeframes": ["15m", "5m"],
    }


def _record_key(record: Mapping[str, object]) -> tuple[object, ...]:
    kind = record.get("kind")
    if kind == "header":
        return (kind,)
    if kind == "candle":
        return (kind, record.get("timeframe"), record.get("timestamp_ms"))
    if kind == "funding_observation":
        return (kind, record.get("timestamp_ms"))
    if kind in {"event_prediction", "event_excluded", "label_matured"}:
        return ("event" if kind != "label_matured" else kind, record.get("decision_time_ms"), record.get("direction"))
    raise ShadowError("journal contains an unknown record kind")


def _semantic_record(record: Mapping[str, object]) -> dict[str, object]:
    value = dict(record)
    if record.get("kind") == "candle":
        value.pop("observed_at", None)
    elif record.get("kind") == "funding_observation":
        value.pop("observed_at", None)
        value.pop("available_at", None)
        value.pop("available_at_ms", None)
    return value


def _validate_record(record: object) -> dict[str, object]:
    if not isinstance(record, dict):
        raise ShadowError("journal record is not an object")
    kind = record.get("kind")
    schemas = {
        "header": set(build_header()),
        "candle": {"close", "high", "kind", "low", "observed_at", "open", "timeframe", "timestamp", "timestamp_ms", "volume"},
        "funding_observation": {"available_at", "available_at_ms", "kind", "observed_at", "rate", "timestamp", "timestamp_ms"},
        "event_prediction": {"computed_at", "computed_at_ms", "decision_time", "decision_time_ms", "direction", "execution_time", "execution_time_ms", "features", "kind", "predicted_positive", "probability", "signal_time", "threshold"},
        "event_excluded": {"computed_at", "computed_at_ms", "decision_time", "decision_time_ms", "direction", "kind", "reason", "signal_time"},
        "label_matured": {"decision_time", "decision_time_ms", "direction", "entry", "execution_time", "execution_time_ms", "exit_reason", "exit_time", "exit_time_ms", "kind", "label", "matured_at"},
    }
    if kind not in schemas or set(record) != schemas[kind]:
        raise ShadowError("journal record schema mismatch")
    if kind == "header":
        if record != build_header():
            raise ShadowError("journal header conflicts with frozen boundary or inputs")
        return record
    decision_kind = kind in {"event_prediction", "event_excluded", "label_matured"}
    if kind == "candle":
        timeframe = record["timeframe"]
        if not isinstance(timeframe, str) or timeframe not in INTERVAL_MS:
            raise ShadowError("journal candle timeframe is invalid")
        timestamp_ms = _integer(record["timestamp_ms"], "journal timestamp")
        if record["timestamp"] != _iso(timestamp_ms) or timestamp_ms % INTERVAL_MS[str(timeframe)]:
            raise ShadowError("journal candle timestamp is not exact")
        observed_ms = _parse_iso(record["observed_at"], "journal candle observed_at")
        if observed_ms < timestamp_ms + INTERVAL_MS[timeframe]:
            raise ShadowError("journal candle was recorded before it closed")
        values = [_number(record[key], f"journal candle {key}") for key in ("open", "high", "low", "close", "volume")]
        opening, high, low, close, volume = values
        if (
            min(opening, high, low, close) <= 0.0
            or not low <= opening <= high
            or not low <= close <= high
            or volume < 0.0
        ):
            raise ShadowError("journal candle OHLCV is invalid")
    elif kind == "funding_observation":
        timestamp_ms = _integer(record["timestamp_ms"], "journal funding timestamp")
        available_ms = _integer(record["available_at_ms"], "journal funding availability")
        if record["timestamp"] != _iso(timestamp_ms) or record["available_at"] != _iso(available_ms):
            raise ShadowError("journal funding timestamps are inconsistent")
        observed_ms = _parse_iso(record["observed_at"], "journal funding observed_at")
        expected_available = (
            observed_ms // INTERVAL_MS["15m"] + 1
        ) * INTERVAL_MS["15m"]
        if timestamp_ms > observed_ms or available_ms != expected_available:
            raise ShadowError("journal funding availability evidence is invalid")
        _number(record["rate"], "journal funding rate")
    elif decision_kind:
        decision_ms = _integer(record["decision_time_ms"], "journal decision time")
        if record["decision_time"] != _iso(decision_ms) or decision_ms <= BOUNDARY_MS:
            raise ShadowError("journal decision violates the prospective boundary")
        if not isinstance(record["direction"], str) or record["direction"] not in {"long", "short"}:
            raise ShadowError("journal event direction is invalid")
        if kind in {"event_prediction", "event_excluded"}:
            computed_ms = _integer(record["computed_at_ms"], "journal computed_at")
            if record["computed_at"] != _iso(computed_ms):
                raise ShadowError("journal computed_at is inconsistent")
            if computed_ms < decision_ms:
                raise ShadowError("journal event was computed before its decision")
        if kind == "event_prediction":
            if computed_ms >= decision_ms + INTERVAL_MS["5m"]:
                raise ShadowError("journal prediction was computed too late")
            if _parse_iso(record["signal_time"], "journal signal_time") != decision_ms - INTERVAL_MS["15m"]:
                raise ShadowError("journal signal and decision times conflict")
            _vector(record["features"], "journal features")
            probability = _number(record["probability"], "journal probability")
            if not 0.0 <= probability <= 1.0 or record["predicted_positive"] is not (probability >= 0.5) or _number(record["threshold"], "journal threshold") != 0.5:
                raise ShadowError("journal prediction is invalid")
            execution_ms = _integer(record["execution_time_ms"], "journal execution time")
            if (
                record["execution_time"] != _iso(execution_ms)
                or execution_ms != _execution_time_ms(computed_ms)
                or execution_ms != decision_ms + INTERVAL_MS["5m"]
            ):
                raise ShadowError("journal prediction execution time is invalid")
        elif kind == "event_excluded":
            if (
                _parse_iso(record["signal_time"], "journal signal_time")
                != decision_ms - INTERVAL_MS["15m"]
                or not isinstance(record["reason"], str)
                or not record["reason"]
            ):
                raise ShadowError("journal exclusion reason is invalid")
            if (record["reason"] == "late_computation") is not (
                computed_ms >= decision_ms + INTERVAL_MS["5m"]
            ):
                raise ShadowError("journal late-computation exclusion is inconsistent")
        else:
            if (
                isinstance(record["label"], bool)
                or not isinstance(record["label"], int)
                or record["label"] not in {0, 1}
            ):
                raise ShadowError("journal label is invalid")
            if _number(record["entry"], "journal label entry") <= 0.0:
                raise ShadowError("journal label entry is invalid")
            execution_ms = _integer(record["execution_time_ms"], "journal execution time")
            exit_ms = _integer(record["exit_time_ms"], "journal exit time")
            if (
                record["execution_time"] != _iso(execution_ms)
                or execution_ms != decision_ms + INTERVAL_MS["5m"]
                or record["exit_time"] != _iso(exit_ms)
                or exit_ms < execution_ms
                or exit_ms > execution_ms + HOLD_MS
                or exit_ms % INTERVAL_MS["5m"]
            ):
                raise ShadowError("journal label execution or exit time is invalid")
            matured_ms = _parse_iso(record["matured_at"], "journal matured_at")
            if matured_ms < execution_ms + HOLD_MS + INTERVAL_MS["5m"]:
                raise ShadowError("journal label matured too early")
            if not isinstance(record["exit_reason"], str) or record["exit_reason"] not in {
                "deadline_open",
                "stop_gap",
                "target_gap",
                "stop",
                "target",
            }:
                raise ShadowError("journal label exit reason is invalid")
            expected_label = 1 if record["exit_reason"] in {"target", "target_gap"} else 0
            if record["label"] != expected_label:
                raise ShadowError("journal label conflicts with its exit reason")
    return record


def _parse_journal(raw: bytes) -> list[dict[str, object]]:
    if not raw:
        raise ShadowError("journal is an existing zero-byte file")
    complete_length = raw.rfind(b"\n") + 1
    if complete_length != len(raw):
        raise ShadowError("journal has a torn or unterminated tail")
    records: list[dict[str, object]] = []
    for line in raw.splitlines():
        if not line:
            raise ShadowError("journal contains a blank complete line")
        try:
            value = json.loads(
                line.decode("utf-8"),
                parse_constant=lambda constant: (_ for _ in ()).throw(
                    ShadowError(f"journal contains forbidden constant {constant}")
                ),
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ShadowError("journal contains malformed complete JSON") from error
        if line != canonical_json_bytes(value):
            raise ShadowError("journal line is not canonical JSON")
        records.append(_validate_record(value))
    _validate_journal_sequence(records)
    return records


def _read_journal_snapshot(
    handle: BinaryIO,
) -> tuple[list[dict[str, object]], bytes]:
    try:
        handle.seek(0)
        raw = handle.read()
    except OSError as error:
        raise ShadowError("journal is unreadable") from error
    return _parse_journal(raw), raw


def _read_journal_handle(handle: BinaryIO) -> list[dict[str, object]]:
    return _read_journal_snapshot(handle)[0]


def read_journal(path: Path) -> list[dict[str, object]]:
    try:
        with path.open("rb") as handle:
            return _read_journal_handle(handle)
    except FileNotFoundError:
        return []
    except OSError as error:
        raise ShadowError("journal is unreadable") from error


def _validate_journal_sequence(records: Sequence[Mapping[str, object]]) -> None:
    if records and records[0] != build_header():
        raise ShadowError("journal does not begin with the frozen header")
    seen: dict[tuple[object, ...], Mapping[str, object]] = {}
    events: dict[tuple[object, object], Mapping[str, object]] = {}
    candle_positions = {
        (record.get("timeframe"), record.get("timestamp_ms")): index
        for index, record in enumerate(records)
        if record.get("kind") == "candle"
    }
    for index, record in enumerate(records):
        if index > 0 and record.get("kind") == "header":
            raise ShadowError("journal contains more than one header")
        key = _record_key(record)
        previous = seen.get(key)
        if previous is not None and _semantic_record(previous) != _semantic_record(record):
            raise ShadowError("journal contains a conflicting duplicate identity")
        if previous is not None:
            raise ShadowError("journal contains a duplicate identity")
        seen[key] = record
        kind = record.get("kind")
        if kind in {"event_prediction", "event_excluded"}:
            signal_key = ("15m", int(record["decision_time_ms"]) - INTERVAL_MS["15m"])
            signal_position = candle_positions.get(signal_key)
            if signal_position is None or signal_position >= index:
                raise ShadowError("journal event lacks a preceding signal candle")
            events[(record["decision_time_ms"], record["direction"])] = record
        elif kind == "label_matured":
            event_key = (record["decision_time_ms"], record["direction"])
            event = events.get(event_key)
            if event is None or event.get("kind") != "event_prediction":
                raise ShadowError("journal label lacks a preceding timely prediction")
            if record["execution_time_ms"] != event["execution_time_ms"]:
                raise ShadowError("journal label execution differs from its prediction")
            execution_ms = int(record["execution_time_ms"])
            deadline_ms = execution_ms + HOLD_MS
            matured_ms = _parse_iso(record["matured_at"], "journal matured_at")
            for timestamp_ms in range(
                execution_ms, deadline_ms + INTERVAL_MS["5m"], INTERVAL_MS["5m"]
            ):
                source_position = candle_positions.get(("5m", timestamp_ms))
                if source_position is None:
                    continue
                if source_position >= index:
                    raise ShadowError("journal label precedes a required 5m source row")
                observed_ms = _parse_iso(
                    records[source_position]["observed_at"],
                    "journal candle observed_at",
                )
                if observed_ms > matured_ms:
                    raise ShadowError("journal label predates a required 5m observation")


@contextmanager
def locked_journal(path: Path) -> Iterator[None]:
    if not path.parent.is_dir():
        raise ShadowError("journal parent directory must already exist")
    lock_path = path.with_name(f"{path.name}.lock")
    try:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as error:
        raise ShadowError("journal sidecar lock cannot be opened") from error
    with os.fdopen(descriptor, "r+b") as handle:
        descriptor = handle.fileno()
        if os.name == "nt":
            import msvcrt

            lock_offset = 0x7FFFFFFE
            os.lseek(descriptor, lock_offset, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                os.lseek(descriptor, lock_offset, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)


def _sync_parent_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _verify_path_identity(path: Path, handle: BinaryIO) -> None:
    try:
        descriptor_stat = os.fstat(handle.fileno())
        path_stat = path.stat()
    except OSError as error:
        raise ShadowError("journal pathname identity is unavailable") from error
    if (descriptor_stat.st_dev, descriptor_stat.st_ino) != (
        path_stat.st_dev,
        path_stat.st_ino,
    ):
        raise ShadowError("journal pathname does not identify its open descriptor")


def _append_records(
    handle: BinaryIO,
    path: Path,
    records: Sequence[Mapping[str, object]],
    *,
    sync_parent_entry: bool = False,
) -> None:
    _verify_path_identity(path, handle)
    if not records:
        return
    payload = b"".join(canonical_json_bytes(record) + b"\n" for record in records)
    try:
        handle.seek(0, os.SEEK_END)
        written = handle.write(payload)
        if written != len(payload):
            raise ShadowError("journal append was a short write")
        handle.flush()
        _verify_path_identity(path, handle)
        os.fsync(handle.fileno())
    except OSError as error:
        raise ShadowError("journal append or fsync failed") from error
    if sync_parent_entry and os.name != "nt":
        _sync_parent_directory(path)


@contextmanager
def _open_existing_journal(path: Path) -> Iterator[BinaryIO | None]:
    try:
        descriptor = os.open(path, os.O_RDWR)
    except FileNotFoundError:
        yield None
        return
    except OSError as error:
        raise ShadowError("journal cannot be opened") from error
    with os.fdopen(descriptor, "r+b", buffering=0) as handle:
        _verify_path_identity(path, handle)
        yield handle


@contextmanager
def _create_journal(path: Path) -> Iterator[BinaryIO]:
    try:
        descriptor = (
            _create_windows_journal_descriptor(path)
            if os.name == "nt"
            else os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        )
    except OSError as error:
        raise ShadowError("journal cannot be exclusively created") from error
    with os.fdopen(descriptor, "r+b", buffering=0) as handle:
        _verify_path_identity(path, handle)
        yield handle


def _create_windows_journal_descriptor(path: Path) -> int:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    handle = create_file(
        str(path.resolve()),
        WINDOWS_GENERIC_READ | WINDOWS_GENERIC_WRITE,
        0,
        None,
        WINDOWS_CREATE_NEW,
        WINDOWS_FILE_FLAG_WRITE_THROUGH,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        error = ctypes.get_last_error()
        raise OSError(error, "CreateFileW CREATE_NEW failed", path)
    try:
        return msvcrt.open_osfhandle(
            handle,
            os.O_RDWR | getattr(os, "O_BINARY", 0),
        )
    except (OSError, ValueError) as error:
        close_handle(handle)
        raise OSError("CreateFileW handle conversion failed") from error


def reconcile_records(
    existing: Sequence[Mapping[str, object]], candidates: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    by_key = {_record_key(record): record for record in existing}
    appended: list[dict[str, object]] = []
    for candidate_value in candidates:
        candidate = _validate_record(dict(candidate_value))
        key = _record_key(candidate)
        previous = by_key.get(key)
        if previous is not None:
            if _semantic_record(previous) != _semantic_record(candidate):
                raise ShadowError("append conflicts with an existing journal identity")
            continue
        by_key[key] = candidate
        appended.append(candidate)
    return appended


def _candle_frame(
    seed: pd.DataFrame,
    records: Sequence[Mapping[str, object]],
    timeframe: str,
) -> pd.DataFrame:
    values: dict[int, Mapping[str, object]] = {}
    for record in records:
        if record.get("kind") != "candle" or record.get("timeframe") != timeframe:
            continue
        timestamp = int(record["timestamp_ms"])
        previous = values.get(timestamp)
        if previous is not None and _semantic_record(previous) != _semantic_record(record):
            raise ShadowError(f"conflicting {timeframe} candle revision")
        values[timestamp] = record
    expected = int(seed.iloc[-1]["date"].timestamp() * 1000) + INTERVAL_MS[timeframe]
    rows: list[dict[str, object]] = []
    for timestamp in sorted(values):
        if timestamp != expected:
            raise ShadowError(f"{timeframe} journal extension has a gap or revision")
        record = values[timestamp]
        rows.append(
            {
                "date": pd.Timestamp(timestamp, unit="ms", tz="UTC"),
                "open": record["open"],
                "high": record["high"],
                "low": record["low"],
                "close": record["close"],
                "volume": record["volume"],
            }
        )
        expected += INTERVAL_MS[timeframe]
    if not rows:
        return seed.copy()
    return pd.concat((seed, pd.DataFrame(rows)), ignore_index=True)


def _funding_for_decision(
    records: Sequence[Mapping[str, object]], decision_ms: int
) -> tuple[float | None, str | None]:
    record = _FundingPrefixIndex(records, activate=True).latest(decision_ms)
    if record is None:
        return None, "funding_missing_stale_or_unavailable"
    return float(record["rate"]), None


def _event_features(
    candles: pd.DataFrame,
    indicators: pd.DataFrame,
    funding: float | None,
    index: int,
    direction: int,
) -> tuple[list[float] | None, str | None]:
    if funding is None:
        return None, "funding_missing_stale_or_unavailable"
    row = candles.iloc[index]
    indicator = indicators.iloc[index]
    required = ("upper", "lower", "rv24", "atr14", "prior_volume96", "return_1", "momentum_16", "ema96")
    if any(pd.isna(indicator[name]) for name in required):
        return None, "missing_lookback"
    high, low, close = (float(row[name]) for name in ("high", "low", "close"))
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
    features = [
        -direction * funding,
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
    if not np.isfinite(np.asarray(features)).all():
        return None, "nonfinite_derived_feature"
    return features, None


def predict_probability(model_artifact: Mapping[str, object], features: Sequence[float]) -> float:
    model = model_artifact["model"]
    assert isinstance(model, Mapping)
    preprocessing = model["preprocessing"]
    assert isinstance(preprocessing, Mapping)
    raw = np.asarray(features, dtype=float)
    lower = np.asarray(preprocessing["winsor_q01"], dtype=float)
    upper = np.asarray(preprocessing["winsor_q99"], dtype=float)
    mean = np.asarray(preprocessing["scaler_mean"], dtype=float)
    scale = np.asarray(preprocessing["scaler_scale"], dtype=float)
    coefficient = np.asarray(model["coef"], dtype=float)[0]
    intercept = float(model["intercept"][0])  # type: ignore[index]
    score = float(((np.clip(raw, lower, upper) - mean) / scale) @ coefficient + intercept)
    return 1.0 / (1.0 + math.exp(-score)) if score >= 0.0 else math.exp(score) / (1.0 + math.exp(score))


def generate_events(
    candles: pd.DataFrame,
    funding_records: Sequence[Mapping[str, object]],
    model_artifact: Mapping[str, object],
    clock: Callable[[], datetime],
    *,
    existing_event_keys: set[tuple[object, object]] | None = None,
    indicators: pd.DataFrame | None = None,
) -> list[dict[str, object]]:
    replay_indicators = compute_indicators(candles) if indicators is None else indicators
    funding_index = _FundingPrefixIndex(funding_records, activate=True)
    existing_keys = set() if existing_event_keys is None else existing_event_keys
    result: list[dict[str, object]] = []
    for index, row in candles.iterrows():
        signal_ms = int(row["date"].timestamp() * 1000)
        decision_ms = signal_ms + INTERVAL_MS["15m"]
        if decision_ms <= BOUNDARY_MS:
            continue
        directions: list[int] = []
        if bool(replay_indicators.at[index, "first_long"]):
            directions.append(1)
        if bool(replay_indicators.at[index, "first_short"]):
            directions.append(-1)
        for direction in directions:
            direction_name = "long" if direction == 1 else "short"
            if (decision_ms, direction_name) in existing_keys:
                continue
            funding_record = funding_index.latest(decision_ms)
            features, reason = _event_features(
                candles,
                replay_indicators,
                None if funding_record is None else float(funding_record["rate"]),
                index,
                direction,
            )
            probability = (
                None
                if features is None
                else predict_probability(model_artifact, features)
            )
            computed_at_ms = _clock_ms(clock)
            if computed_at_ms < decision_ms:
                raise ShadowError("event computation precedes its decision time")
            base = {
                "computed_at": _iso(computed_at_ms),
                "computed_at_ms": computed_at_ms,
                "decision_time": _iso(decision_ms),
                "decision_time_ms": decision_ms,
                "direction": direction_name,
                "signal_time": _iso(signal_ms),
            }
            if computed_at_ms >= decision_ms + INTERVAL_MS["5m"]:
                result.append(
                    {**base, "kind": "event_excluded", "reason": "late_computation"}
                )
                continue
            if features is None:
                result.append({**base, "kind": "event_excluded", "reason": reason or "unknown"})
                continue
            assert probability is not None
            execution_ms = _execution_time_ms(computed_at_ms)
            result.append(
                {
                    **base,
                    "execution_time": _iso(execution_ms),
                    "execution_time_ms": execution_ms,
                    "features": features,
                    "kind": "event_prediction",
                    "predicted_positive": probability >= 0.5,
                    "probability": probability,
                    "threshold": 0.5,
                }
            )
    return result


class _FundingPrefixIndex:
    def __init__(
        self,
        records: Sequence[Mapping[str, object]],
        *,
        activate: bool = False,
    ) -> None:
        funding_records = [
            record for record in records if record.get("kind") == "funding_observation"
        ]
        self._by_timestamp = {
            int(record["timestamp_ms"]): record for record in funding_records
        }
        if len(self._by_timestamp) != len(funding_records):
            raise ShadowError("journal contains a duplicate funding identity")
        self._timestamps = sorted(self._by_timestamp)
        self._timestamp_indexes = {
            timestamp: index for index, timestamp in enumerate(self._timestamps)
        }
        size = 1
        while size < len(self._timestamps):
            size *= 2
        self._size = size
        self._minimum_available = [math.inf] * (2 * size)
        if activate:
            for record in funding_records:
                self.add(record)

    def add(self, record: Mapping[str, object]) -> None:
        timestamp = int(record["timestamp_ms"])
        tree_index = self._size + self._timestamp_indexes[timestamp]
        self._minimum_available[tree_index] = int(record["available_at_ms"])
        tree_index //= 2
        while tree_index:
            self._minimum_available[tree_index] = min(
                self._minimum_available[2 * tree_index],
                self._minimum_available[2 * tree_index + 1],
            )
            tree_index //= 2

    def latest(self, decision_ms: int) -> Mapping[str, object] | None:
        lower = bisect_left(self._timestamps, decision_ms - FUNDING_MAX_AGE_MS)
        upper = bisect_right(self._timestamps, decision_ms)
        found = self._find_rightmost(1, 0, self._size, lower, upper, decision_ms)
        return None if found is None else self._by_timestamp[self._timestamps[found]]

    def _find_rightmost(
        self,
        node: int,
        start: int,
        stop: int,
        lower: int,
        upper: int,
        decision_ms: int,
    ) -> int | None:
        if (
            stop <= lower
            or upper <= start
            or self._minimum_available[node] > decision_ms
        ):
            return None
        if stop - start == 1:
            return start if start < len(self._timestamps) else None
        middle = (start + stop) // 2
        right = self._find_rightmost(
            2 * node + 1,
            middle,
            stop,
            lower,
            upper,
            decision_ms,
        )
        if right is not None:
            return right
        return self._find_rightmost(
            2 * node,
            start,
            middle,
            lower,
            upper,
            decision_ms,
        )


def _build_replay_context(
    seeds: Mapping[str, pd.DataFrame],
    records: Sequence[Mapping[str, object]],
) -> _ReplayContext:
    candles_15m = _candle_frame(seeds["15m"], records, "15m")
    indicators_15m = compute_indicators(candles_15m)
    dates_15m_ms = np.asarray(
        [int(value.timestamp() * 1000) for value in candles_15m["date"]],
        dtype=np.int64,
    )
    journal_candles = sorted(
        (
            int(record["timestamp_ms"]),
            index,
            _parse_iso(record["observed_at"], "journal candle observed_at"),
        )
        for index, record in enumerate(records)
        if record.get("kind") == "candle" and record.get("timeframe") == "15m"
    )
    journal_15m_max_positions = np.maximum.accumulate(
        np.asarray([value[1] for value in journal_candles], dtype=np.int64)
    )
    journal_15m_max_observed = np.maximum.accumulate(
        np.asarray([value[2] for value in journal_candles], dtype=np.int64)
    )
    candles_5m = _candle_frame(seeds["5m"], records, "5m")
    return _ReplayContext(
        candles_15m=candles_15m,
        indicators_15m=indicators_15m,
        dates_15m_ms=dates_15m_ms,
        journal_15m_timestamps=tuple(value[0] for value in journal_candles),
        journal_15m_max_positions=journal_15m_max_positions,
        journal_15m_max_observed=journal_15m_max_observed,
        seed_15m_last_ms=int(seeds["15m"].iloc[-1]["date"].timestamp() * 1000),
        candles_5m=candles_5m,
        dates_5m_ms=_five_minute_timestamp_index(candles_5m),
        observations_5m=_five_minute_observation_map(records),
    )


def _validate_existing_events(
    records: Sequence[Mapping[str, object]],
    replay: Mapping[str, pd.DataFrame] | _ReplayContext,
    model_artifact: Mapping[str, object],
) -> None:
    context = (
        replay
        if isinstance(replay, _ReplayContext)
        else _build_replay_context(replay, records)
    )
    candles = context.candles_15m
    indicators = context.indicators_15m
    dates_ms = context.dates_15m_ms
    funding_index = _FundingPrefixIndex(records)

    for position, record in enumerate(records):
        kind = record.get("kind")
        if kind == "funding_observation":
            funding_index.add(record)
            continue
        if kind not in {"event_prediction", "event_excluded"}:
            continue
        computed_ms = int(record["computed_at_ms"])
        decision_ms = int(record["decision_time_ms"])
        signal_ms = decision_ms - INTERVAL_MS["15m"]
        candle_index = int(np.searchsorted(dates_ms, signal_ms))
        if candle_index >= len(dates_ms) or int(dates_ms[candle_index]) != signal_ms:
            raise ShadowError("journal event signal candle is unavailable")
        if signal_ms > context.seed_15m_last_ms:
            source_index = bisect_right(context.journal_15m_timestamps, signal_ms) - 1
            if (
                source_index < 0
                or context.journal_15m_max_positions[source_index] >= position
            ):
                raise ShadowError("journal event lacks its complete preceding 15m prefix")
            if context.journal_15m_max_observed[source_index] > computed_ms:
                raise ShadowError("journal event predates used 15m source observation")

        direction = 1 if record["direction"] == "long" else -1
        signal_column = "first_long" if direction == 1 else "first_short"
        if not bool(indicators.at[candle_index, signal_column]):
            raise ShadowError("journal event differs from exact frozen replay")
        base = {
            "computed_at": _iso(computed_ms),
            "computed_at_ms": computed_ms,
            "decision_time": _iso(decision_ms),
            "decision_time_ms": decision_ms,
            "direction": record["direction"],
            "signal_time": _iso(signal_ms),
        }
        if computed_ms >= decision_ms + INTERVAL_MS["5m"]:
            expected = {
                **base,
                "kind": "event_excluded",
                "reason": "late_computation",
            }
        else:
            funding_record = funding_index.latest(decision_ms)
            if funding_record is not None and _parse_iso(
                funding_record["observed_at"], "journal funding observed_at"
            ) > computed_ms:
                raise ShadowError("journal event predates used funding observation")
            features, reason = _event_features(
                candles,
                indicators,
                None if funding_record is None else float(funding_record["rate"]),
                candle_index,
                direction,
            )
            if features is None:
                expected = {
                    **base,
                    "kind": "event_excluded",
                    "reason": reason or "unknown",
                }
            else:
                probability = predict_probability(model_artifact, features)
                execution_ms = _execution_time_ms(computed_ms)
                expected = {
                    **base,
                    "execution_time": _iso(execution_ms),
                    "execution_time_ms": execution_ms,
                    "features": features,
                    "kind": "event_prediction",
                    "predicted_positive": probability >= 0.5,
                    "probability": probability,
                    "threshold": 0.5,
                }
        if dict(record) != expected:
            raise ShadowError("journal event differs from exact frozen replay")


def _five_minute_timestamp_index(candles_5m: pd.DataFrame) -> np.ndarray:
    return np.asarray(
        [int(value.timestamp() * 1000) for value in candles_5m["date"]],
        dtype=np.int64,
    )


def _label_event_indexed(
    candles_5m: pd.DataFrame,
    dates_ms: np.ndarray,
    execution_ms: int,
    direction: str,
) -> tuple[int, str, float, int]:
    deadline_ms = execution_ms + HOLD_MS
    start = int(np.searchsorted(dates_ms, execution_ms))
    stop_index = int(np.searchsorted(dates_ms, deadline_ms, side="right"))
    bars = candles_5m.iloc[start:stop_index]
    if (
        len(bars) != LABEL_ROWS
        or int(bars.iloc[0]["date"].timestamp() * 1000) != execution_ms
        or int(bars.iloc[-1]["date"].timestamp() * 1000) != deadline_ms
        or not bars["date"].diff().iloc[1:].eq(pd.Timedelta(minutes=5)).all()
    ):
        raise ShadowError("event lacks the exact complete 577-row 5m label path")
    entry = float(bars.iloc[0]["open"])
    long = direction == "long"
    if not long and direction != "short":
        raise ShadowError("label direction is invalid")
    stop = entry * (0.985 if long else 1.015)
    target = entry * (1.04 if long else 0.96)
    for row in bars.itertuples(index=False):
        timestamp_ms = int(row.date.timestamp() * 1000)
        if timestamp_ms == deadline_ms:
            return 0, "deadline_open", entry, timestamp_ms
        if (row.open <= stop if long else row.open >= stop):
            return 0, "stop_gap", entry, timestamp_ms
        if (row.open >= target if long else row.open <= target):
            return 1, "target_gap", entry, timestamp_ms
        if (row.low <= stop if long else row.high >= stop):
            return 0, "stop", entry, timestamp_ms
        if (row.high >= target if long else row.low <= target):
            return 1, "target", entry, timestamp_ms
    raise ShadowError("label path produced no outcome")


def label_event(
    candles_5m: pd.DataFrame, execution_ms: int, direction: str
) -> tuple[int, str, float, int]:
    return _label_event_indexed(
        candles_5m,
        _five_minute_timestamp_index(candles_5m),
        execution_ms,
        direction,
    )


def _five_minute_observation_map(
    records: Sequence[Mapping[str, object]],
) -> dict[int, tuple[int, int]]:
    return {
        int(record["timestamp_ms"]): (
            position,
            _parse_iso(record["observed_at"], "journal candle observed_at"),
        )
        for position, record in enumerate(records)
        if record.get("kind") == "candle" and record.get("timeframe") == "5m"
    }


def _validate_existing_labels(
    records: Sequence[Mapping[str, object]],
    replay: pd.DataFrame | _ReplayContext,
) -> None:
    candles_5m = replay.candles_5m if isinstance(replay, _ReplayContext) else replay
    predictions = {
        (record["decision_time_ms"], record["direction"]): (position, record)
        for position, record in enumerate(records)
        if record.get("kind") == "event_prediction"
    }
    dates_ms = (
        replay.dates_5m_ms
        if isinstance(replay, _ReplayContext)
        else _five_minute_timestamp_index(candles_5m)
    )
    observations = (
        replay.observations_5m
        if isinstance(replay, _ReplayContext)
        else _five_minute_observation_map(records)
    )
    for position, record in enumerate(records):
        if record.get("kind") != "label_matured":
            continue
        prediction_value = predictions.get(
            (record["decision_time_ms"], record["direction"])
        )
        if prediction_value is None or prediction_value[0] >= position:
            raise ShadowError("journal label lacks a preceding timely prediction")
        prediction = prediction_value[1]
        execution_ms = int(prediction["execution_time_ms"])
        expected_label, expected_reason, expected_entry, expected_exit_ms = (
            _label_event_indexed(
                candles_5m,
                dates_ms,
                execution_ms,
                str(record["direction"]),
            )
        )
        matured_ms = _parse_iso(record["matured_at"], "journal matured_at")
        required_observed = _required_5m_observed_at(
            observations,
            execution_ms,
            before_position=position,
        )
        if matured_ms < required_observed:
            raise ShadowError("journal label predates a required 5m observation")
        if (
            record["label"],
            record["exit_reason"],
            float(record["entry"]),
            record["execution_time_ms"],
            record["execution_time"],
            record["exit_time_ms"],
            record["exit_time"],
        ) != (
            expected_label,
            expected_reason,
            expected_entry,
            execution_ms,
            _iso(execution_ms),
            expected_exit_ms,
            _iso(expected_exit_ms),
        ):
            raise ShadowError("journal label differs from its exact 577-row path")


def _required_5m_observed_at(
    observations: Mapping[int, tuple[int, int]],
    execution_ms: int,
    *,
    before_position: int | None = None,
) -> int:
    deadline_ms = execution_ms + HOLD_MS
    required_observed = 0
    for timestamp_ms in range(
        execution_ms,
        deadline_ms + INTERVAL_MS["5m"],
        INTERVAL_MS["5m"],
    ):
        source = observations.get(timestamp_ms)
        if source is None:
            continue
        position, observed_ms = source
        if before_position is not None and position >= before_position:
            raise ShadowError("journal label precedes a required 5m source row")
        required_observed = max(required_observed, observed_ms)
    return required_observed


def generate_labels(
    records: Sequence[Mapping[str, object]],
    replay: pd.DataFrame | _ReplayContext,
    now_ms: int,
) -> list[dict[str, object]]:
    candles_5m = replay.candles_5m if isinstance(replay, _ReplayContext) else replay
    existing_labels = {
        (record["decision_time_ms"], record["direction"])
        for record in records
        if record.get("kind") == "label_matured"
    }
    dates_ms = (
        replay.dates_5m_ms
        if isinstance(replay, _ReplayContext)
        else _five_minute_timestamp_index(candles_5m)
    )
    observations = (
        replay.observations_5m
        if isinstance(replay, _ReplayContext)
        else _five_minute_observation_map(records)
    )
    result: list[dict[str, object]] = []
    for record in records:
        if record.get("kind") != "event_prediction":
            continue
        decision_ms = int(record["decision_time_ms"])
        execution_ms = int(record["execution_time_ms"])
        key = (decision_ms, record["direction"])
        if key in existing_labels or now_ms < execution_ms + HOLD_MS + INTERVAL_MS["5m"]:
            continue
        label, reason, entry, exit_ms = _label_event_indexed(
            candles_5m,
            dates_ms,
            execution_ms,
            str(record["direction"]),
        )
        if now_ms < _required_5m_observed_at(observations, execution_ms):
            continue
        result.append(
            {
                "decision_time": _iso(decision_ms),
                "decision_time_ms": decision_ms,
                "direction": record["direction"],
                "entry": entry,
                "execution_time": _iso(execution_ms),
                "execution_time_ms": execution_ms,
                "exit_reason": reason,
                "exit_time": _iso(exit_ms),
                "exit_time_ms": exit_ms,
                "kind": "label_matured",
                "label": label,
                "matured_at": _iso(now_ms),
            }
        )
    return result


def _last_timestamp(records: Sequence[Mapping[str, object]], kind: str, timeframe: str | None = None) -> int | None:
    values = [
        int(record["timestamp_ms"])
        for record in records
        if record.get("kind") == kind
        and (timeframe is None or record.get("timeframe") == timeframe)
    ]
    return max(values, default=None)


def make_exchange() -> object:
    try:
        import ccxt
    except ImportError as error:
        raise ShadowError("CCXT is required only for --poll-once") from error
    return ccxt.okx({"enableRateLimit": True, "options": {"defaultType": "swap"}})


def poll_once(
    *,
    exchange: object | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    journal_path: Path = JOURNAL_PATH,
) -> dict[str, object]:
    if sha256_file(SHADOW_PREREGISTRATION) != SHADOW_PREREGISTRATION_SHA256:
        raise ShadowError("shadow preregistration SHA-256 mismatch")
    model = load_model()
    seeds = load_seed_frames()
    with (
        locked_journal(journal_path),
        _open_existing_journal(journal_path) as existing_handle,
    ):
        journal_existed = existing_handle is not None
        existing_identity = (
            None
            if existing_handle is None
            else (
                os.fstat(existing_handle.fileno()).st_dev,
                os.fstat(existing_handle.fileno()).st_ino,
            )
        )
        existing, existing_raw = (
            ([], b"")
            if existing_handle is None
            else _read_journal_snapshot(existing_handle)
        )
        existing_context = _build_replay_context(seeds, existing)
        _validate_existing_events(existing, existing_context, model)
        _validate_existing_labels(existing, existing_context)

    client = exchange if exchange is not None else make_exchange()
    fetched: list[dict[str, object]] = []
    deferred_reason: str | None = None
    try:
        for timeframe in ("15m", "5m"):
            last = _last_timestamp(existing, "candle", timeframe)
            seed_last = int(seeds[timeframe].iloc[-1]["date"].timestamp() * 1000)
            start = (
                last + INTERVAL_MS[timeframe]
                if last is not None
                else seed_last + INTERVAL_MS[timeframe]
            )
            fetched.extend(fetch_closed_ohlcv(client, timeframe, start, clock))
        last_funding = _last_timestamp(existing, "funding_observation")
        funding_start = (
            last_funding + 1
            if last_funding is not None
            else BOUNDARY_MS - FUNDING_MAX_AGE_MS
        )
        fetched.extend(fetch_funding(client, funding_start, clock))
    except NetworkDeferred as error:
        deferred_reason = str(error)

    with (
        locked_journal(journal_path),
        _open_existing_journal(journal_path) as current_handle,
    ):
        if journal_existed and current_handle is None:
            raise ShadowError("preexisting journal disappeared during network access")
        if journal_existed and current_handle is not None:
            current_stat = os.fstat(current_handle.fileno())
            if (current_stat.st_dev, current_stat.st_ino) != existing_identity:
                raise ShadowError("preexisting journal identity changed during network access")
        current, current_raw = (
            ([], b"")
            if current_handle is None
            else _read_journal_snapshot(current_handle)
        )
        if journal_existed and not current_raw.startswith(existing_raw):
            raise ShadowError(
                "preexisting journal is not an exact prefix after network access"
            )
        base_candidates = (
            []
            if deferred_reason is not None
            else ([build_header()] if not current else []) + fetched
        )
        additions = reconcile_records(current, base_candidates)
        base_prospective = [*current, *additions]
        current_context = _build_replay_context(seeds, base_prospective)
        if deferred_reason is not None:
            _validate_existing_events(current, current_context, model)
            _validate_existing_labels(current, current_context)
            return {
                "appended": 0,
                "reason": deferred_reason,
                "status": "network_deferred",
            }
        labels = generate_labels(
            base_prospective,
            current_context,
            _clock_ms(clock),
        )
        label_additions = reconcile_records(base_prospective, labels)
        before_events = [*base_prospective, *label_additions]
        existing_event_keys = {
            (record["decision_time_ms"], record["direction"])
            for record in before_events
            if record.get("kind") in {"event_prediction", "event_excluded"}
        }
        events = generate_events(
            current_context.candles_15m,
            before_events,
            model,
            clock,
            existing_event_keys=existing_event_keys,
            indicators=current_context.indicators_15m,
        )
        event_additions = reconcile_records(before_events, events)
        prospective = [*before_events, *event_additions]
        _validate_journal_sequence(prospective)
        _validate_existing_events(prospective, current_context, model)
        _validate_existing_labels(prospective, current_context)
        all_additions = [*additions, *label_additions, *event_additions]
        if current_handle is None:
            with _create_journal(journal_path) as created_handle:
                _append_records(
                    created_handle,
                    journal_path,
                    all_additions,
                    sync_parent_entry=True,
                )
        else:
            _append_records(current_handle, journal_path, all_additions)
    return {
        "appended": len(all_additions),
        "event_records": len(event_additions),
        "label_records": len(label_additions),
        "status": "poll_complete",
    }


def plan() -> dict[str, object]:
    return {
        "boundary_exclusive": BOUNDARY,
        "default_network": False,
        "default_writes": False,
        "journal": JOURNAL_PATH.relative_to(REPO_ROOT).as_posix(),
        "journal_lock": JOURNAL_PATH.with_name(
            f"{JOURNAL_PATH.name}.lock"
        ).relative_to(REPO_ROOT).as_posix(),
        "mode": "plan",
        "model_sha256": MODEL_SHA256,
        "poll_flag": "--poll-once",
        "reports_performance": False,
        "seed_origin": SEED_ORIGIN,
        "seed_paths": dict(SEED_RELATIVE_PATHS),
        "seed_sha256": dict(SEED_SHA256),
        "shadow_preregistration_v7_sha256": SHADOW_PREREGISTRATION_SHA256,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One-shot prospective Donchian logistic shadow recorder."
    )
    parser.add_argument("--poll-once", action="store_true")
    args = parser.parse_args(argv)
    result = poll_once() if args.poll_once else plan()
    print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
