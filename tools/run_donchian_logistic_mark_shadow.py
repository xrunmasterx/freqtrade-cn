from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import BinaryIO


REPO_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "research_data"
    / "donchian-logistic-meta-label"
)
PREREGISTRATION_PATH = RESEARCH_ROOT / "SHADOW_PREREGISTRATION_V8.md"
FREEZE_MANIFEST_PATH = RESEARCH_ROOT / "SHADOW_FREEZE_V8.json"
V7_PREREGISTRATION_PATH = RESEARCH_ROOT / "SHADOW_PREREGISTRATION_V7.md"
V7_MODEL_PATH = RESEARCH_ROOT / "MODEL.json"
V7_RECORDER_PATH = REPO_ROOT / "tools" / "run_donchian_logistic_shadow.py"
PUBLICATION_JOURNAL_PATH = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "logs"
    / "donchian-logistic-publication-v8.jsonl"
)
ACCOUNTING_JOURNAL_PATH = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "logs"
    / "donchian-logistic-mark-funding-v8.jsonl"
)
V7_JOURNAL_PATH = (
    REPO_ROOT / "ft_userdata" / "user_data" / "logs" / "donchian-logistic-shadow.jsonl"
)

BOUNDARY = "2026-08-14T00:00:00.000Z"
BOUNDARY_MS = 1_786_665_600_000
HOUR_MS = 60 * 60 * 1000
FIVE_MINUTES_MS = 5 * 60 * 1000
MINUTE_MS = 60 * 1000
FETCH_LIMIT = 100
MAX_FETCH_PAGES = 10_000
SYMBOL = "BTC/USDT:USDT"
OKX_INSTRUMENT_ID = "BTC-USDT-SWAP"
EXCHANGE_ID = "okx"
MARK_TIMEFRAME = "1h"
MARK_SOURCE_METHOD = "ccxt.fetch_ohlcv.price_mark"
FUNDING_SOURCE_METHOD = "ccxt.okx.publicGetPublicFundingRateHistory"

V7_PREREGISTRATION_SHA256 = (
    "7ac3404a0e1b80a8a9896bb0411c23e88c564a6e8ceed5d0aa86fc4f38c962db"
)
V7_RECORDER_SHA256 = "dc8869c4803cf6a76c6a24fa441c052cec2dd4d7f58668af9b19d79a9fba6c8c"
V7_MODEL_SHA256 = "160d63c4622620258ac9c76d9bf14ad5c46e579ed971c4caa61d7093aacaad24"
FREQTRADE_GIT_SHA = "b1121f89512f6af1a99b4d3929d4405093363c99"
FREQTRADE_SOURCE_HASHES = {
    "freqtrade/freqtrade/data/converter/converter.py": (
        "b262fbfe02b2fd81c4c89f3fdf004a0008aed828e20ec0ac75b5d1f9c2c093cb"
    ),
    "freqtrade/freqtrade/exchange/exchange.py": (
        "384716d8c7df55385ffabc261f05b31d1810d5643cfadb465f19bdcf2a78bf8c"
    ),
    "freqtrade/freqtrade/exchange/exchange_utils_timeframe.py": (
        "eff0ba69f833dabe101d4fa31f78a6709ab58a3dcedddc8c7e8cdffed4281dc6"
    ),
}
CCXT_VERSION = "4.5.73"
CCXT_SOURCE_HASHES = {
    "freqtrade/.venv/Lib/site-packages/ccxt/base/exchange.py": (
        "426784bd6826ba3ca4b9fdcaa4480bba9ae647be7aeb68d1a773e459363bf453"
    ),
    "freqtrade/.venv/Lib/site-packages/ccxt/okx.py": (
        "69c2c74878abdaab102221dc91d1dcadc7a3da71543a9d45bad5fff3e1d23767"
    ),
}

WINDOWS_GENERIC_READ = 0x80000000
WINDOWS_GENERIC_WRITE = 0x40000000
WINDOWS_CREATE_NEW = 1
WINDOWS_FILE_FLAG_WRITE_THROUGH = 0x80000000


class ShadowError(RuntimeError):
    pass


class NetworkDeferred(RuntimeError):
    pass


@dataclass(frozen=True)
class Freeze:
    manifest: Mapping[str, object]
    manifest_sha256: str


@dataclass(frozen=True)
class JournalSnapshot:
    existed: bool
    identity: tuple[int, int] | None
    records: tuple[Mapping[str, object], ...]
    raw: bytes


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


def _git_head(repository: Path) -> str:
    metadata = repository / ".git"
    try:
        if metadata.is_file():
            pointer = metadata.read_text(encoding="utf-8").strip()
            if not pointer.startswith("gitdir: "):
                raise ShadowError("Freqtrade gitdir pointer is malformed")
            git_directory = (repository / pointer.removeprefix("gitdir: ")).resolve()
        else:
            git_directory = metadata
        head = (git_directory / "HEAD").read_text(encoding="ascii").strip()
        if head.startswith("ref: "):
            reference = head.removeprefix("ref: ")
            loose_reference = git_directory / reference
            if loose_reference.is_file():
                head = loose_reference.read_text(encoding="ascii").strip()
            else:
                packed = (git_directory / "packed-refs").read_text(encoding="ascii")
                matches = [
                    line.split(" ", 1)[0]
                    for line in packed.splitlines()
                    if line.endswith(f" {reference}")
                ]
                if len(matches) != 1:
                    raise ShadowError("Freqtrade git reference is not uniquely resolved")
                head = matches[0]
    except OSError as error:
        raise ShadowError("Freqtrade git identity is unreadable") from error
    if len(head) != 40 or any(character not in "0123456789abcdef" for character in head):
        raise ShadowError("Freqtrade git HEAD is not a full commit identity")
    return head


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ShadowError(f"{name} is not a valid integer")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ShadowError(f"{name} is not numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ShadowError(f"{name} is not finite")
    return result


def _iso(timestamp_ms: int) -> str:
    return (
        datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _parse_iso(value: object, name: str) -> int:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ShadowError(f"{name} is not canonical UTC")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ShadowError(f"{name} is malformed") from error
    timestamp_ms = int(parsed.timestamp() * 1000)
    if _iso(timestamp_ms) != value:
        raise ShadowError(f"{name} is not canonical millisecond UTC")
    return timestamp_ms


def _clock_ms(clock: Callable[[], datetime]) -> int:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ShadowError("clock must return a timezone-aware datetime")
    return int(value.timestamp() * 1000)


def _defer_network_error(error: Exception, operation: str) -> None:
    transient_names = {
        "DDoSProtection",
        "ExchangeNotAvailable",
        "NetworkError",
        "RateLimitExceeded",
        "RequestTimeout",
    }
    transient = isinstance(error, (ConnectionError, OSError, TimeoutError)) or any(
        parent.__name__ in transient_names for parent in type(error).__mro__
    )
    if transient:
        raise NetworkDeferred(f"{operation} was deferred") from error
    raise ShadowError(f"{operation} failed outside the recoverable network boundary") from error


def _manifest_paths() -> dict[str, str]:
    return {
        "v7_model_path": V7_MODEL_PATH.relative_to(REPO_ROOT).as_posix(),
        "v7_preregistration_path": V7_PREREGISTRATION_PATH.relative_to(REPO_ROOT).as_posix(),
        "v7_recorder_path": V7_RECORDER_PATH.relative_to(REPO_ROOT).as_posix(),
        "v8_preregistration_path": PREREGISTRATION_PATH.relative_to(REPO_ROOT).as_posix(),
        "v8_recorder_path": Path(__file__).resolve().relative_to(REPO_ROOT).as_posix(),
    }


def _validate_manifest_schema(  # noqa: C901 - strict freeze schema is intentionally flat
    manifest: object,
) -> Mapping[str, object]:
    expected_keys = {
        "boundary_exclusive",
        "ccxt_source_sha256",
        "ccxt_version",
        "freqtrade_git_sha",
        "freqtrade_source_sha256",
        "frozen_at",
        "schema_version",
        "tests_are_runtime_identity",
        "v7_model_path",
        "v7_model_sha256",
        "v7_preregistration_path",
        "v7_preregistration_sha256",
        "v7_recorder_path",
        "v7_recorder_sha256",
        "v8_preregistration_path",
        "v8_preregistration_sha256",
        "v8_recorder_path",
        "v8_recorder_sha256",
    }
    if not isinstance(manifest, Mapping) or set(manifest) != expected_keys:
        raise ShadowError("freeze manifest schema mismatch")
    if manifest["schema_version"] != 1:
        raise ShadowError("freeze manifest schema version mismatch")
    if manifest["boundary_exclusive"] != BOUNDARY:
        raise ShadowError("freeze manifest boundary mismatch")
    if manifest["tests_are_runtime_identity"] is not False:
        raise ShadowError("freeze manifest test-identity declaration mismatch")
    for key, expected in _manifest_paths().items():
        if manifest[key] != expected:
            raise ShadowError(f"freeze manifest {key} mismatch")
    fixed_hashes = {
        "v7_preregistration_sha256": V7_PREREGISTRATION_SHA256,
        "v7_recorder_sha256": V7_RECORDER_SHA256,
        "v7_model_sha256": V7_MODEL_SHA256,
    }
    for key, expected in fixed_hashes.items():
        if manifest[key] != expected:
            raise ShadowError(f"freeze manifest {key} mismatch")
    if manifest["freqtrade_git_sha"] != FREQTRADE_GIT_SHA:
        raise ShadowError("freeze manifest Freqtrade git identity mismatch")
    if manifest["freqtrade_source_sha256"] != FREQTRADE_SOURCE_HASHES:
        raise ShadowError("freeze manifest Freqtrade source identity mismatch")
    if manifest["ccxt_version"] != CCXT_VERSION:
        raise ShadowError("freeze manifest CCXT version mismatch")
    if manifest["ccxt_source_sha256"] != CCXT_SOURCE_HASHES:
        raise ShadowError("freeze manifest CCXT source identity mismatch")
    for key in ("v8_preregistration_sha256", "v8_recorder_sha256"):
        if not _is_sha256(manifest[key]):
            raise ShadowError(f"freeze manifest {key} is invalid")
    frozen_at_ms = _parse_iso(manifest["frozen_at"], "freeze manifest frozen_at")
    if frozen_at_ms >= BOUNDARY_MS:
        raise ShadowError("freeze manifest was not frozen before the boundary")
    return manifest


def load_freeze_manifest(
    path: Path = FREEZE_MANIFEST_PATH,
    expected_sha256: str | None = None,
) -> Freeze:
    if expected_sha256 is not None and not _is_sha256(expected_sha256):
        raise ShadowError("expected freeze manifest SHA-256 is invalid")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ShadowError("freeze manifest is unreadable") from error
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise ShadowError("freeze manifest SHA-256 differs from the external expectation")
    if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
        raise ShadowError("freeze manifest is not one terminated canonical JSON line")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ShadowError("freeze manifest is malformed") from error
    if raw != canonical_json_bytes(value) + b"\n":
        raise ShadowError("freeze manifest is not canonical JSON")
    manifest = _validate_manifest_schema(value)
    bound_files = {
        str(manifest["v7_model_path"]): str(manifest["v7_model_sha256"]),
        str(manifest["v7_preregistration_path"]): str(
            manifest["v7_preregistration_sha256"]
        ),
        str(manifest["v7_recorder_path"]): str(manifest["v7_recorder_sha256"]),
        str(manifest["v8_preregistration_path"]): str(
            manifest["v8_preregistration_sha256"]
        ),
        str(manifest["v8_recorder_path"]): str(manifest["v8_recorder_sha256"]),
        **{str(key): str(digest) for key, digest in FREQTRADE_SOURCE_HASHES.items()},
        **{str(key): str(digest) for key, digest in CCXT_SOURCE_HASHES.items()},
    }
    for relative, expected in bound_files.items():
        if sha256_file(REPO_ROOT / relative) != expected:
            raise ShadowError(f"freeze-bound dependency SHA-256 mismatch: {relative}")
    try:
        installed_ccxt_version = importlib.metadata.version("ccxt")
    except importlib.metadata.PackageNotFoundError as error:
        raise ShadowError("freeze-bound CCXT distribution is unavailable") from error
    if installed_ccxt_version != CCXT_VERSION:
        raise ShadowError("installed CCXT version differs from freeze manifest")
    if _git_head(REPO_ROOT / "freqtrade") != FREQTRADE_GIT_SHA:
        raise ShadowError("Freqtrade git HEAD differs from freeze manifest")
    return Freeze(manifest=dict(manifest), manifest_sha256=actual_sha256)


def _load_verified_v7(freeze: Freeze) -> ModuleType:
    expected = str(freeze.manifest["v7_recorder_sha256"])
    if sha256_file(V7_RECORDER_PATH) != expected:
        raise ShadowError("V7 recorder changed after freeze validation")
    module_name = "_donchian_logistic_shadow_v7_verified"
    spec = importlib.util.spec_from_file_location(module_name, V7_RECORDER_PATH)
    if spec is None or spec.loader is None:
        raise ShadowError("verified V7 recorder cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def build_header(journal_type: str, freeze: Freeze) -> dict[str, object]:
    if journal_type not in {"publication", "accounting"}:
        raise ShadowError("unknown V8 journal type")
    manifest_copy = json.loads(canonical_json_bytes(freeze.manifest))
    return {
        "boundary_exclusive": BOUNDARY,
        "claim": "exact pinned Freqtrade funding-accounting input"
        if journal_type == "accounting"
        else "conservative V7 event publication evidence",
        "exchange": EXCHANGE_ID,
        "freeze_manifest": manifest_copy,
        "freeze_manifest_sha256": freeze.manifest_sha256,
        "journal_type": journal_type,
        "kind": "header",
        "schema_version": 1,
        "symbol": SYMBOL,
    }


def _record_key(record: Mapping[str, object]) -> tuple[object, ...]:
    kind = record.get("kind")
    if kind == "header":
        return (kind,)
    if kind == "mark_open_observation":
        return (kind, record.get("timestamp_ms"))
    if kind in {"funding_settlement", "funding_accounting_join"}:
        return (kind, record.get("raw_settlement_timestamp_ms"))
    if kind in {"event_projection", "publication_receipt"}:
        return (kind, record.get("decision_time_ms"), record.get("direction"))
    raise ShadowError("journal contains an unknown record kind")


def _semantic_record(record: Mapping[str, object]) -> bytes:
    value = dict(record)
    if record.get("kind") in {"mark_open_observation", "funding_settlement"}:
        value.pop("observed_at", None)
        value.pop("observed_at_ms", None)
    return canonical_json_bytes(value)


def _validate_record(  # noqa: C901 - fail-closed schemas remain explicit and local
    record: object,
    journal_type: str,
    freeze: Freeze | None,
) -> dict[str, object]:
    if not isinstance(record, dict):
        raise ShadowError("journal record is not an object")
    kind = record.get("kind")
    common_schemas = {
        "mark_open_observation": {
            "kind",
            "timestamp",
            "timestamp_ms",
            "open",
            "observed_at",
            "observed_at_ms",
            "source_method",
        },
        "funding_settlement": {
            "kind",
            "raw_settlement_timestamp",
            "raw_settlement_timestamp_ms",
            "accounting_timestamp",
            "accounting_timestamp_ms",
            "rate",
            "observed_at",
            "observed_at_ms",
            "source_method",
        },
        "funding_accounting_join": {
            "kind",
            "raw_settlement_timestamp",
            "raw_settlement_timestamp_ms",
            "accounting_timestamp",
            "accounting_timestamp_ms",
            "open_mark",
            "open_fund",
            "mark_record_sha256",
            "funding_record_sha256",
        },
        "event_projection": {
            "kind",
            "symbol",
            "decision_time",
            "decision_time_ms",
            "direction",
            "execution_time",
            "execution_time_ms",
            "event_sha256",
            "v7_prefix_byte_length",
            "v7_prefix_sha256",
        },
        "publication_receipt": {
            "kind",
            "decision_time",
            "decision_time_ms",
            "direction",
            "execution_time",
            "execution_time_ms",
            "projection_sha256",
            "projection_durable_at",
            "projection_durable_at_ms",
            "eligible",
        },
    }
    if kind == "header":
        if freeze is None or record != build_header(journal_type, freeze):
            raise ShadowError("journal header conflicts with the frozen V8 identity")
        return record
    allowed = (
        {"event_projection", "publication_receipt"}
        if journal_type == "publication"
        else {"mark_open_observation", "funding_settlement", "funding_accounting_join"}
    )
    if kind not in allowed or set(record) != common_schemas.get(str(kind)):
        raise ShadowError("journal record schema mismatch")
    if kind == "mark_open_observation":
        timestamp_ms = _integer(record["timestamp_ms"], "mark timestamp")
        observed_ms = _integer(record["observed_at_ms"], "mark observed_at")
        if record["timestamp"] != _iso(timestamp_ms):
            raise ShadowError("mark timestamp fields disagree")
        if record["observed_at"] != _iso(observed_ms) or observed_ms < timestamp_ms:
            raise ShadowError("mark first observation is invalid")
        if timestamp_ms < BOUNDARY_MS or timestamp_ms % HOUR_MS:
            raise ShadowError("mark timestamp is outside the frozen one-hour grid")
        if _number(record["open"], "mark open") <= 0.0:
            raise ShadowError("mark open is not positive")
        if record["source_method"] != MARK_SOURCE_METHOD:
            raise ShadowError("mark source method mismatch")
    elif kind == "funding_settlement":
        raw_ms = _integer(record["raw_settlement_timestamp_ms"], "raw funding timestamp")
        accounting_ms = _integer(record["accounting_timestamp_ms"], "accounting timestamp")
        observed_ms = _integer(record["observed_at_ms"], "funding observed_at")
        if record["raw_settlement_timestamp"] != _iso(raw_ms):
            raise ShadowError("raw funding timestamp fields disagree")
        if record["accounting_timestamp"] != _iso(accounting_ms):
            raise ShadowError("accounting timestamp fields disagree")
        if raw_ms <= BOUNDARY_MS or accounting_ms != raw_ms // MINUTE_MS * MINUTE_MS:
            raise ShadowError("funding timestamp violates the pinned minute-floor rule")
        if record["observed_at"] != _iso(observed_ms) or observed_ms < raw_ms:
            raise ShadowError("funding first observation is invalid")
        _number(record["rate"], "funding rate")
        if record["source_method"] != FUNDING_SOURCE_METHOD:
            raise ShadowError("funding source method mismatch")
    elif kind == "funding_accounting_join":
        raw_ms = _integer(record["raw_settlement_timestamp_ms"], "join raw timestamp")
        accounting_ms = _integer(record["accounting_timestamp_ms"], "join accounting timestamp")
        if record["raw_settlement_timestamp"] != _iso(raw_ms):
            raise ShadowError("join raw timestamp fields disagree")
        if record["accounting_timestamp"] != _iso(accounting_ms):
            raise ShadowError("join accounting timestamp fields disagree")
        if accounting_ms != raw_ms // MINUTE_MS * MINUTE_MS:
            raise ShadowError("join timestamp violates the pinned minute-floor rule")
        if _number(record["open_mark"], "joined mark open") <= 0.0:
            raise ShadowError("joined mark open is not positive")
        _number(record["open_fund"], "joined funding rate")
        for field in ("mark_record_sha256", "funding_record_sha256"):
            if not _is_sha256(record[field]):
                raise ShadowError("join source SHA-256 is invalid")
    elif kind == "event_projection":
        decision_ms = _integer(record["decision_time_ms"], "projection decision")
        execution_ms = _integer(record["execution_time_ms"], "projection execution")
        prefix_length = _integer(
            record["v7_prefix_byte_length"], "V7 prefix byte length", minimum=1
        )
        if prefix_length < 1:
            raise ShadowError("V7 prefix byte length is empty")
        if record["decision_time"] != _iso(decision_ms) or decision_ms <= BOUNDARY_MS:
            raise ShadowError("projection decision violates the boundary")
        if record["execution_time"] != _iso(execution_ms):
            raise ShadowError("projection execution fields disagree")
        if execution_ms != decision_ms + FIVE_MINUTES_MS:
            raise ShadowError("projection execution identity is invalid")
        if record["symbol"] != SYMBOL or record["direction"] not in {"long", "short"}:
            raise ShadowError("projection event identity is invalid")
        for field in ("event_sha256", "v7_prefix_sha256"):
            if not _is_sha256(record[field]):
                raise ShadowError("projection SHA-256 is invalid")
    else:
        decision_ms = _integer(record["decision_time_ms"], "receipt decision")
        execution_ms = _integer(record["execution_time_ms"], "receipt execution")
        durable_ms = _integer(record["projection_durable_at_ms"], "projection durable_at")
        if record["decision_time"] != _iso(decision_ms):
            raise ShadowError("receipt decision fields disagree")
        if record["execution_time"] != _iso(execution_ms):
            raise ShadowError("receipt execution fields disagree")
        if record["projection_durable_at"] != _iso(durable_ms):
            raise ShadowError("receipt durable-at fields disagree")
        if durable_ms < decision_ms:
            raise ShadowError("receipt durable-at predates the V7 event decision")
        if record["direction"] not in {"long", "short"}:
            raise ShadowError("receipt direction is invalid")
        if not _is_sha256(record["projection_sha256"]):
            raise ShadowError("receipt projection SHA-256 is invalid")
        if record["eligible"] is not (durable_ms < execution_ms):
            raise ShadowError("receipt eligible flag violates the strict execution boundary")
    return record


def _validate_publication_sequence(
    records: Sequence[Mapping[str, object]], freeze: Freeze
) -> None:
    if records and records[0] != build_header("publication", freeze):
        raise ShadowError("publication journal does not begin with its frozen header")
    projections: dict[tuple[object, object], Mapping[str, object]] = {}
    seen: set[tuple[object, ...]] = set()
    for index, record in enumerate(records):
        key = _record_key(record)
        if key in seen:
            raise ShadowError("publication journal contains a duplicate identity")
        seen.add(key)
        kind = record.get("kind")
        if index > 0 and kind == "header":
            raise ShadowError("publication journal contains more than one header")
        event_key = (record.get("decision_time_ms"), record.get("direction"))
        if kind == "event_projection":
            projections[event_key] = record
        elif kind == "publication_receipt":
            projection = projections.get(event_key)
            if projection is None:
                raise ShadowError("publication receipt lacks a preceding projection")
            if (
                record["decision_time"] != projection["decision_time"]
                or record["execution_time"] != projection["execution_time"]
                or record["execution_time_ms"] != projection["execution_time_ms"]
                or record["projection_sha256"]
                != hashlib.sha256(canonical_json_bytes(projection)).hexdigest()
            ):
                raise ShadowError("publication receipt conflicts with its projection")


def _accounting_state(  # noqa: C901 - replay invariants are checked in one ordered pass
    records: Sequence[Mapping[str, object]],
    freeze: Freeze | None,
    *,
    require_complete: bool,
) -> tuple[
    dict[int, Mapping[str, object]],
    dict[int, Mapping[str, object]],
    dict[int, Mapping[str, object]],
]:
    if freeze is not None and records and records[0] != build_header("accounting", freeze):
        raise ShadowError("accounting journal does not begin with its frozen header")
    marks: dict[int, Mapping[str, object]] = {}
    funding: dict[int, Mapping[str, object]] = {}
    joins: dict[int, Mapping[str, object]] = {}
    seen: set[tuple[object, ...]] = set()
    last_mark: int | None = None
    last_raw: int | None = None
    accounting_minutes: set[int] = set()
    for index, record in enumerate(records):
        key = _record_key(record)
        if key in seen:
            raise ShadowError("accounting journal contains a duplicate identity")
        seen.add(key)
        kind = record.get("kind")
        if index > 0 and kind == "header":
            raise ShadowError("accounting journal contains more than one header")
        if kind == "mark_open_observation":
            timestamp_ms = int(record["timestamp_ms"])
            expected = BOUNDARY_MS if last_mark is None else last_mark + HOUR_MS
            if timestamp_ms != expected:
                raise ShadowError("mark-open sequence is not continuous from the boundary")
            marks[timestamp_ms] = record
            last_mark = timestamp_ms
        elif kind == "funding_settlement":
            raw_ms = int(record["raw_settlement_timestamp_ms"])
            accounting_ms = int(record["accounting_timestamp_ms"])
            if last_raw is not None and raw_ms <= last_raw:
                raise ShadowError("funding settlement sequence is not strictly increasing")
            if accounting_ms in accounting_minutes:
                raise ShadowError("funding settlements collide in the same accounting minute")
            funding[raw_ms] = record
            accounting_minutes.add(accounting_ms)
            last_raw = raw_ms
        elif kind == "funding_accounting_join":
            raw_ms = int(record["raw_settlement_timestamp_ms"])
            source = funding.get(raw_ms)
            mark = marks.get(int(record["accounting_timestamp_ms"]))
            if source is None or mark is None:
                raise ShadowError("accounting join lacks both preceding exact sources")
            if (
                record["raw_settlement_timestamp"] != source["raw_settlement_timestamp"]
                or record["accounting_timestamp"] != source["accounting_timestamp"]
                or record["accounting_timestamp_ms"] != source["accounting_timestamp_ms"]
                or _semantic_record({"value": record["open_mark"]})
                != _semantic_record({"value": mark["open"]})
                or _semantic_record({"value": record["open_fund"]})
                != _semantic_record({"value": source["rate"]})
                or record["mark_record_sha256"]
                != hashlib.sha256(canonical_json_bytes(mark)).hexdigest()
                or record["funding_record_sha256"]
                != hashlib.sha256(canonical_json_bytes(source)).hexdigest()
            ):
                raise ShadowError("accounting join conflicts with its exact sources")
            joins[raw_ms] = record
    if marks and min(marks) != BOUNDARY_MS:
        raise ShadowError("first mark-open observation is not the boundary mark")
    mark_tail = max(marks, default=None)
    expected_joins: set[int] = set()
    if mark_tail is not None:
        for raw_ms, source in funding.items():
            accounting_ms = int(source["accounting_timestamp_ms"])
            if accounting_ms > mark_tail:
                continue
            if accounting_ms not in marks:
                raise ShadowError("funding accounting minute has no exact mark open")
            expected_joins.add(raw_ms)
    actual_joins = set(joins)
    if not actual_joins <= expected_joins:
        raise ShadowError("accounting journal contains a premature or orphan join")
    if require_complete and actual_joins != expected_joins:
        raise ShadowError("accounting journal is missing a required exact join")
    return marks, funding, joins


def _validate_journal_sequence(
    records: Sequence[Mapping[str, object]], journal_type: str, freeze: Freeze
) -> None:
    if journal_type == "publication":
        _validate_publication_sequence(records, freeze)
    elif journal_type == "accounting":
        _accounting_state(records, freeze, require_complete=True)
    else:
        raise ShadowError("unknown V8 journal type")


def _parse_journal(raw: bytes, journal_type: str, freeze: Freeze) -> list[dict[str, object]]:
    if not raw:
        raise ShadowError("journal is an existing zero-byte file")
    if raw.rfind(b"\n") + 1 != len(raw):
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
        records.append(_validate_record(value, journal_type, freeze))
    _validate_journal_sequence(records, journal_type, freeze)
    return records


def _read_journal_snapshot(
    handle: BinaryIO, journal_type: str, freeze: Freeze
) -> tuple[list[dict[str, object]], bytes]:
    try:
        handle.seek(0)
        raw = handle.read()
    except OSError as error:
        raise ShadowError("journal is unreadable") from error
    return _parse_journal(raw, journal_type, freeze), raw


def read_journal(path: Path, journal_type: str, freeze: Freeze) -> list[dict[str, object]]:
    try:
        with path.open("rb") as handle:
            return _read_journal_snapshot(handle, journal_type, freeze)[0]
    except FileNotFoundError:
        return []
    except OSError as error:
        raise ShadowError("journal is unreadable") from error


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


def _durability_barrier(handle: BinaryIO, path: Path) -> None:
    try:
        _verify_path_identity(path, handle)
        handle.flush()
        os.fsync(handle.fileno())
        _verify_path_identity(path, handle)
    except OSError as error:
        raise ShadowError("journal durability barrier failed") from error


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
        return msvcrt.open_osfhandle(handle, os.O_RDWR | getattr(os, "O_BINARY", 0))
    except (OSError, ValueError) as error:
        close_handle(handle)
        raise OSError("CreateFileW handle conversion failed") from error


def _capture_snapshot(path: Path, journal_type: str, freeze: Freeze) -> JournalSnapshot:
    with locked_journal(path), _open_existing_journal(path) as handle:
        if handle is None:
            return JournalSnapshot(False, None, (), b"")
        stat = os.fstat(handle.fileno())
        records, raw = _read_journal_snapshot(handle, journal_type, freeze)
        return JournalSnapshot(True, (stat.st_dev, stat.st_ino), tuple(records), raw)


def _verify_snapshot(
    snapshot: JournalSnapshot,
    current_handle: BinaryIO | None,
    current_raw: bytes,
) -> None:
    if snapshot.existed and current_handle is None:
        raise ShadowError("preexisting journal disappeared during unlocked work")
    if snapshot.existed and current_handle is not None:
        stat = os.fstat(current_handle.fileno())
        if (stat.st_dev, stat.st_ino) != snapshot.identity:
            raise ShadowError("preexisting journal identity changed during unlocked work")
        if not current_raw.startswith(snapshot.raw):
            raise ShadowError("preexisting journal is not an exact byte prefix")


def reconcile_records(
    existing: Sequence[Mapping[str, object]],
    candidates: Sequence[Mapping[str, object]],
    journal_type: str,
    freeze: Freeze | None = None,
) -> list[dict[str, object]]:
    by_key = {_record_key(record): record for record in existing}
    additions: list[dict[str, object]] = []
    for candidate_value in candidates:
        candidate = _validate_record(dict(candidate_value), journal_type, freeze)
        key = _record_key(candidate)
        previous = by_key.get(key)
        if previous is not None:
            if _semantic_record(previous) != _semantic_record(candidate):
                raise ShadowError("append conflicts with an existing identity or revision")
            continue
        by_key[key] = candidate
        additions.append(candidate)
    return additions


def fetch_mark_open_observations(  # noqa: C901 - pagination validates every boundary inline
    exchange: object,
    start_ms: int,
    cutoff_ms: int,
    clock: Callable[[], datetime],
    limit: int = FETCH_LIMIT,
) -> list[dict[str, object]]:
    if getattr(exchange, "has", {}).get("fetchMarkOHLCV") is not True:
        raise ShadowError("CCXT fetchMarkOHLCV capability must be literal true")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= FETCH_LIMIT:
        raise ShadowError("mark fetch limit must be between 1 and 100")
    if start_ms < BOUNDARY_MS or start_ms % HOUR_MS or cutoff_ms % HOUR_MS:
        raise ShadowError("mark fetch range is outside the frozen one-hour grid")
    if cutoff_ms < start_ms:
        return []
    cursor = start_ms
    result: list[dict[str, object]] = []
    for _page_number in range(MAX_FETCH_PAGES):
        try:
            response = exchange.fetch_ohlcv(
                SYMBOL,
                MARK_TIMEFRAME,
                since=cursor,
                limit=limit,
                params={"paginate": False, "price": "mark"},
            )
        except Exception as error:  # noqa: BLE001 - classify CCXT network subclasses below
            _defer_network_error(error, "mark-open fetch")
        observed_ms = _clock_ms(clock)
        if not isinstance(response, Sequence) or isinstance(response, (str, bytes)):
            raise ShadowError("mark-open response is malformed")
        admitted: list[dict[str, object]] = []
        previous_timestamp: int | None = None
        for row in response:
            if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) < 2:
                raise ShadowError("mark-open row is malformed")
            timestamp_ms = _integer(row[0], "mark API timestamp")
            if previous_timestamp is not None and timestamp_ms <= previous_timestamp:
                raise ShadowError("mark response is duplicated or out of order")
            previous_timestamp = timestamp_ms
            if timestamp_ms < cursor:
                raise ShadowError("mark response precedes its requested cursor")
            if timestamp_ms > cutoff_ms:
                break
            expected = cursor + len(admitted) * HOUR_MS
            if timestamp_ms != expected:
                raise ShadowError("mark response has a gap and is not continuous")
            if timestamp_ms > observed_ms:
                raise ShadowError("mark open was observed before its timestamp")
            opening = _number(row[1], "mark API open")
            if opening <= 0.0:
                raise ShadowError("mark API open is not positive")
            admitted.append(
                {
                    "kind": "mark_open_observation",
                    "timestamp": _iso(timestamp_ms),
                    "timestamp_ms": timestamp_ms,
                    "open": opening,
                    "observed_at": _iso(observed_ms),
                    "observed_at_ms": observed_ms,
                    "source_method": MARK_SOURCE_METHOD,
                }
            )
        if not admitted:
            raise ShadowError("mark response cannot cover the required continuous range")
        result.extend(admitted)
        cursor = int(admitted[-1]["timestamp_ms"]) + HOUR_MS
        if cursor > cutoff_ms:
            return result
    raise ShadowError("mark pagination limit exceeded")


def fetch_funding_settlements(  # noqa: C901 - provenance checks stay adjacent to admission
    exchange: object,
    start_ms: int,
    cutoff_ms: int,
    clock: Callable[[], datetime],
    limit: int = FETCH_LIMIT,
) -> list[dict[str, object]]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= FETCH_LIMIT:
        raise ShadowError("funding fetch limit must be between 1 and 100")
    cursor = max(start_ms, BOUNDARY_MS + 1)
    request = {
        "instId": OKX_INSTRUMENT_ID,
        "before": cursor - 1,
        "limit": limit,
    }
    try:
        response = exchange.publicGetPublicFundingRateHistory(request)
    except Exception as error:  # noqa: BLE001 - classify CCXT network subclasses below
        _defer_network_error(error, "funding-settlement fetch")
    observed_ms = _clock_ms(clock)
    if not isinstance(response, Mapping) or set(response) != {"code", "msg", "data"}:
        raise ShadowError("funding raw response envelope is malformed")
    if response["code"] != "0" or response["msg"] != "":
        raise ShadowError("funding raw response reports an exchange error")
    data = response["data"]
    if not isinstance(data, list):
        raise ShadowError("funding raw response data is malformed")
    if len(data) >= limit:
        raise ShadowError(
            "funding raw backlog reaches the single-page limit; completeness is unprovable"
        )
    result: list[dict[str, object]] = []
    accounting_minutes: set[int] = set()
    previous_timestamp: int | None = None
    for item in data:
        if not isinstance(item, Mapping) or set(item) != {
            "instType",
            "instId",
            "fundingRate",
            "realizedRate",
            "fundingTime",
        }:
            raise ShadowError("funding raw item schema is malformed")
        if item["instType"] != "SWAP":
            raise ShadowError("funding raw instType does not match the frozen market type")
        if item["instId"] != OKX_INSTRUMENT_ID:
            raise ShadowError("funding raw instId does not match the frozen instrument")
        raw_timestamp = item["fundingTime"]
        if (
            not isinstance(raw_timestamp, str)
            or not raw_timestamp.isascii()
            or not raw_timestamp.isdecimal()
        ):
            raise ShadowError("funding raw fundingTime is malformed")
        raw_ms = int(raw_timestamp)
        if str(raw_ms) != raw_timestamp:
            raise ShadowError("funding raw fundingTime is not canonical integer text")
        if previous_timestamp is not None and raw_ms >= previous_timestamp:
            raise ShadowError("funding raw response is duplicated or not strictly descending")
        previous_timestamp = raw_ms
        if raw_ms < cursor:
            raise ShadowError("funding raw response precedes its requested cursor")
        if raw_ms > cutoff_ms:
            raise ShadowError("funding raw response exceeds the fixed fetch cutoff")
        if raw_ms > observed_ms:
            raise ShadowError("funding raw timestamp is later than its first observation")
        if not isinstance(item["fundingRate"], str):
            raise ShadowError("funding raw fundingRate is malformed")
        try:
            funding_rate = float(item["fundingRate"])
        except ValueError as error:
            raise ShadowError("funding raw fundingRate is malformed") from error
        if not math.isfinite(funding_rate):
            raise ShadowError("funding raw fundingRate is not finite")
        if not isinstance(item["realizedRate"], str):
            raise ShadowError("funding raw realizedRate is malformed")
        try:
            rate = float(item["realizedRate"])
        except ValueError as error:
            raise ShadowError("funding raw realizedRate is malformed") from error
        if not math.isfinite(rate):
            raise ShadowError("funding raw realizedRate is not finite")
        accounting_ms = raw_ms // MINUTE_MS * MINUTE_MS
        if accounting_ms in accounting_minutes:
            raise ShadowError("funding settlements collide in the same accounting minute")
        accounting_minutes.add(accounting_ms)
        result.append(
            {
                "kind": "funding_settlement",
                "raw_settlement_timestamp": _iso(raw_ms),
                "raw_settlement_timestamp_ms": raw_ms,
                "accounting_timestamp": _iso(accounting_ms),
                "accounting_timestamp_ms": accounting_ms,
                "rate": rate,
                "observed_at": _iso(observed_ms),
                "observed_at_ms": observed_ms,
                "source_method": FUNDING_SOURCE_METHOD,
            }
        )
    result.reverse()
    return result


def generate_accounting_joins(
    records: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    marks, funding, joins = _accounting_state(records, None, require_complete=False)
    mark_tail = max(marks, default=None)
    if mark_tail is None:
        return []
    result: list[dict[str, object]] = []
    for raw_ms, source in funding.items():
        if raw_ms in joins:
            continue
        accounting_ms = int(source["accounting_timestamp_ms"])
        if accounting_ms > mark_tail:
            continue
        mark = marks.get(accounting_ms)
        if mark is None:
            raise ShadowError("funding accounting minute has no exact mark open")
        result.append(
            {
                "kind": "funding_accounting_join",
                "raw_settlement_timestamp": source["raw_settlement_timestamp"],
                "raw_settlement_timestamp_ms": raw_ms,
                "accounting_timestamp": source["accounting_timestamp"],
                "accounting_timestamp_ms": accounting_ms,
                "open_mark": mark["open"],
                "open_fund": source["rate"],
                "mark_record_sha256": hashlib.sha256(
                    canonical_json_bytes(mark)
                ).hexdigest(),
                "funding_record_sha256": hashlib.sha256(
                    canonical_json_bytes(source)
                ).hexdigest(),
            }
        )
    return result


def _event_sha256(event: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(event)).hexdigest()


def _build_projection(event: Mapping[str, object], v7_raw: bytes) -> dict[str, object]:
    if event.get("kind") != "event_prediction":
        raise ShadowError("only V7 event_prediction may create a projection")
    decision_ms = _integer(event.get("decision_time_ms"), "V7 event decision")
    execution_ms = _integer(event.get("execution_time_ms"), "V7 event execution")
    if event.get("decision_time") != _iso(decision_ms):
        raise ShadowError("V7 event decision fields disagree")
    if event.get("execution_time") != _iso(execution_ms):
        raise ShadowError("V7 event execution fields disagree")
    if event.get("direction") not in {"long", "short"}:
        raise ShadowError("V7 event direction is invalid")
    event_line = canonical_json_bytes(event) + b"\n"
    if not v7_raw.endswith(b"\n") or event_line not in v7_raw:
        raise ShadowError("V7 event is not contained in the validated journal prefix")
    return {
        "kind": "event_projection",
        "symbol": SYMBOL,
        "decision_time": event["decision_time"],
        "decision_time_ms": decision_ms,
        "direction": event["direction"],
        "execution_time": event["execution_time"],
        "execution_time_ms": execution_ms,
        "event_sha256": _event_sha256(event),
        "v7_prefix_byte_length": len(v7_raw),
        "v7_prefix_sha256": hashlib.sha256(v7_raw).hexdigest(),
    }


def _build_receipt(
    projection: Mapping[str, object], durable_at_ms: int
) -> dict[str, object]:
    execution_ms = int(projection["execution_time_ms"])
    return {
        "kind": "publication_receipt",
        "decision_time": projection["decision_time"],
        "decision_time_ms": projection["decision_time_ms"],
        "direction": projection["direction"],
        "execution_time": projection["execution_time"],
        "execution_time_ms": execution_ms,
        "projection_sha256": hashlib.sha256(
            canonical_json_bytes(projection)
        ).hexdigest(),
        "projection_durable_at": _iso(durable_at_ms),
        "projection_durable_at_ms": durable_at_ms,
        "eligible": durable_at_ms < execution_ms,
    }


def _validate_projection_sources(
    records: Sequence[Mapping[str, object]],
    events: Sequence[Mapping[str, object]],
    v7_raw: bytes,
) -> None:
    events_by_hash = {_event_sha256(event): event for event in events}
    for projection in records:
        if projection.get("kind") != "event_projection":
            continue
        prefix_length = int(projection["v7_prefix_byte_length"])
        if prefix_length > len(v7_raw):
            raise ShadowError("publication projection names a future V7 prefix")
        prefix = v7_raw[:prefix_length]
        if not prefix.endswith(b"\n"):
            raise ShadowError("publication projection V7 prefix is not record-complete")
        if hashlib.sha256(prefix).hexdigest() != projection["v7_prefix_sha256"]:
            raise ShadowError("publication projection V7 prefix hash mismatch")
        event = events_by_hash.get(str(projection["event_sha256"]))
        if event is None or canonical_json_bytes(event) + b"\n" not in prefix:
            raise ShadowError("publication projection event is absent from its V7 prefix")
        if (
            projection["decision_time_ms"] != event["decision_time_ms"]
            or projection["direction"] != event["direction"]
            or projection["execution_time_ms"] != event["execution_time_ms"]
        ):
            raise ShadowError("publication projection changes the V7 event identity")


def _write_publication_handle(
    handle: BinaryIO,
    path: Path,
    current: list[dict[str, object]],
    events: Sequence[Mapping[str, object]],
    v7_raw: bytes,
    clock: Callable[[], datetime],
    freeze: Freeze,
    *,
    newly_created: bool,
) -> dict[str, object]:
    _validate_projection_sources(current, events, v7_raw)
    header_candidates = [build_header("publication", freeze)] if not current else []
    projected_keys = {
        (record["decision_time_ms"], record["direction"])
        for record in current
        if record.get("kind") == "event_projection"
    }
    projections = [
        _build_projection(event, v7_raw)
        for event in events
        if (event["decision_time_ms"], event["direction"]) not in projected_keys
    ]
    phase_one = reconcile_records(
        current,
        [*header_candidates, *projections],
        "publication",
        freeze,
    )
    phase_one_prospective = [*current, *phase_one]
    _validate_publication_sequence(phase_one_prospective, freeze)
    _validate_projection_sources(phase_one_prospective, events, v7_raw)
    _append_records(
        handle,
        path,
        phase_one,
        sync_parent_entry=newly_created,
    )
    existing_receipt_keys = {
        (record["decision_time_ms"], record["direction"])
        for record in phase_one_prospective
        if record.get("kind") == "publication_receipt"
    }
    orphans = [
        record
        for record in phase_one_prospective
        if record.get("kind") == "event_projection"
        and (record["decision_time_ms"], record["direction"]) not in existing_receipt_keys
    ]
    if orphans and not phase_one:
        _durability_barrier(handle, path)
    durable_at_ms = _clock_ms(clock) if orphans else None
    receipt_candidates = (
        []
        if durable_at_ms is None
        else [_build_receipt(projection, durable_at_ms) for projection in orphans]
    )
    receipts = reconcile_records(
        phase_one_prospective,
        receipt_candidates,
        "publication",
    )
    prospective = [*phase_one_prospective, *receipts]
    _validate_publication_sequence(prospective, freeze)
    _append_records(handle, path, receipts)
    eligible = sum(record["eligible"] is True for record in receipts)
    return {
        "status": "publication_complete",
        "projections": sum(record.get("kind") == "event_projection" for record in phase_one),
        "receipts": len(receipts),
        "eligible": eligible,
        "ineligible": len(receipts) - eligible,
        "appended": len(phase_one) + len(receipts),
    }


def record_publication(
    events: Sequence[Mapping[str, object]],
    v7_raw: bytes,
    *,
    path: Path,
    clock: Callable[[], datetime],
    freeze: Freeze,
    _initial_snapshot: JournalSnapshot | None = None,
) -> dict[str, object]:
    snapshot = (
        _capture_snapshot(path, "publication", freeze)
        if _initial_snapshot is None
        else _initial_snapshot
    )
    with locked_journal(path), _open_existing_journal(path) as current_handle:
        current, current_raw = (
            ([], b"")
            if current_handle is None
            else _read_journal_snapshot(current_handle, "publication", freeze)
        )
        _verify_snapshot(snapshot, current_handle, current_raw)
        if current_handle is None:
            with _create_journal(path) as created_handle:
                return _write_publication_handle(
                    created_handle,
                    path,
                    current,
                    events,
                    v7_raw,
                    clock,
                    freeze,
                    newly_created=True,
                )
        return _write_publication_handle(
            current_handle,
            path,
            current,
            events,
            v7_raw,
            clock,
            freeze,
            newly_created=False,
        )


def _run_v7_and_load_events(
    v7: ModuleType,
    exchange: object,
    clock: Callable[[], datetime],
    v7_journal_path: Path,
) -> tuple[dict[str, object], list[dict[str, object]], bytes]:
    result = v7.poll_once(exchange=exchange, clock=clock, journal_path=v7_journal_path)
    with v7.locked_journal(v7_journal_path), v7._open_existing_journal(
        v7_journal_path
    ) as handle:
        if handle is None:
            return result, [], b""
        records, raw = v7._read_journal_snapshot(handle)
        model = v7.load_model()
        seeds = v7.load_seed_frames()
        context = v7._build_replay_context(seeds, records)
        v7._validate_existing_events(records, context, model)
        v7._validate_existing_labels(records, context)
    events = [dict(record) for record in records if record.get("kind") == "event_prediction"]
    return result, events, raw


def _last_accounting_timestamp(
    records: Sequence[Mapping[str, object]], kind: str
) -> int | None:
    field = "timestamp_ms" if kind == "mark_open_observation" else "raw_settlement_timestamp_ms"
    values = [int(record[field]) for record in records if record.get("kind") == kind]
    return max(values, default=None)


def _write_accounting(
    snapshot: JournalSnapshot,
    marks: Sequence[Mapping[str, object]],
    funding: Sequence[Mapping[str, object]],
    *,
    path: Path,
    freeze: Freeze,
) -> dict[str, object]:
    with locked_journal(path), _open_existing_journal(path) as current_handle:
        current, current_raw = (
            ([], b"")
            if current_handle is None
            else _read_journal_snapshot(current_handle, "accounting", freeze)
        )
        _verify_snapshot(snapshot, current_handle, current_raw)
        candidates = ([build_header("accounting", freeze)] if not current else []) + [
            *marks,
            *funding,
        ]
        source_additions = reconcile_records(current, candidates, "accounting", freeze)
        sources = [*current, *source_additions]
        joins = generate_accounting_joins(sources)
        join_additions = reconcile_records(sources, joins, "accounting")
        additions = [*source_additions, *join_additions]
        prospective = [*current, *additions]
        _validate_journal_sequence(prospective, "accounting", freeze)
        if current_handle is None:
            with _create_journal(path) as created_handle:
                _append_records(
                    created_handle,
                    path,
                    additions,
                    sync_parent_entry=True,
                )
        else:
            _append_records(current_handle, path, additions)
    return {
        "status": "accounting_complete",
        "mark_open_observations": sum(
            record.get("kind") == "mark_open_observation" for record in source_additions
        ),
        "funding_settlements": sum(
            record.get("kind") == "funding_settlement" for record in source_additions
        ),
        "joins": len(join_additions),
        "appended": len(additions),
    }


def poll_accounting(
    exchange: object,
    *,
    path: Path,
    clock: Callable[[], datetime],
    freeze: Freeze,
) -> dict[str, object]:
    snapshot = _capture_snapshot(path, "accounting", freeze)
    existing = snapshot.records
    now_ms = _clock_ms(clock)
    mark_cutoff_ms = now_ms // HOUR_MS * HOUR_MS
    last_mark = _last_accounting_timestamp(existing, "mark_open_observation")
    mark_start = BOUNDARY_MS if last_mark is None else last_mark
    last_funding = _last_accounting_timestamp(existing, "funding_settlement")
    funding_start = BOUNDARY_MS + 1 if last_funding is None else last_funding + 1
    try:
        marks = (
            []
            if mark_cutoff_ms < BOUNDARY_MS
            else fetch_mark_open_observations(
                exchange,
                mark_start,
                mark_cutoff_ms,
                clock,
            )
        )
        funding = fetch_funding_settlements(
            exchange,
            funding_start,
            now_ms,
            clock,
        )
    except NetworkDeferred as error:
        with locked_journal(path), _open_existing_journal(path) as current_handle:
            current_raw = (
                b""
                if current_handle is None
                else _read_journal_snapshot(current_handle, "accounting", freeze)[1]
            )
            _verify_snapshot(snapshot, current_handle, current_raw)
        return {
            "status": "network_deferred",
            "reason": str(error),
            "appended": 0,
        }
    return _write_accounting(snapshot, marks, funding, path=path, freeze=freeze)


def make_exchange() -> object:
    try:
        import ccxt
    except ImportError as error:
        raise ShadowError("freeze-bound CCXT is required only for --poll-once") from error
    return ccxt.okx({"enableRateLimit": True, "options": {"defaultType": "swap"}})


def poll_once(
    *,
    exchange: object | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    manifest_path: Path = FREEZE_MANIFEST_PATH,
    expected_manifest_sha256: str | None,
    publication_path: Path = PUBLICATION_JOURNAL_PATH,
    accounting_path: Path = ACCOUNTING_JOURNAL_PATH,
    v7_journal_path: Path = V7_JOURNAL_PATH,
) -> dict[str, object]:
    if expected_manifest_sha256 is None:
        raise ShadowError("an external expected freeze manifest SHA-256 is required")
    freeze = load_freeze_manifest(manifest_path, expected_manifest_sha256)
    v7 = _load_verified_v7(freeze)
    publication_snapshot = _capture_snapshot(publication_path, "publication", freeze)
    client = exchange if exchange is not None else make_exchange()
    v7_result, events, v7_raw = _run_v7_and_load_events(
        v7,
        client,
        clock,
        v7_journal_path,
    )
    publication = record_publication(
        events,
        v7_raw,
        path=publication_path,
        clock=clock,
        freeze=freeze,
        _initial_snapshot=publication_snapshot,
    )
    accounting = poll_accounting(
        client,
        path=accounting_path,
        clock=clock,
        freeze=freeze,
    )
    return {
        "status": (
            "accounting_deferred"
            if accounting["status"] == "network_deferred"
            else "poll_complete"
        ),
        "v7": v7_result,
        "publication": publication,
        "accounting": accounting,
    }


def plan() -> dict[str, object]:
    return {
        "accounting_journal": ACCOUNTING_JOURNAL_PATH.relative_to(REPO_ROOT).as_posix(),
        "accounting_lock": ACCOUNTING_JOURNAL_PATH.with_name(
            f"{ACCOUNTING_JOURNAL_PATH.name}.lock"
        ).relative_to(REPO_ROOT).as_posix(),
        "boundary_exclusive": BOUNDARY,
        "default_network": False,
        "default_writes": False,
        "freeze_manifest": FREEZE_MANIFEST_PATH.relative_to(REPO_ROOT).as_posix(),
        "manifest_sha256_flag": "--freeze-manifest-sha256",
        "mode": "plan",
        "poll_flag": "--poll-once",
        "publication_journal": PUBLICATION_JOURNAL_PATH.relative_to(REPO_ROOT).as_posix(),
        "publication_lock": PUBLICATION_JOURNAL_PATH.with_name(
            f"{PUBLICATION_JOURNAL_PATH.name}.lock"
        ).relative_to(REPO_ROOT).as_posix(),
        "reports_performance": False,
        "source_methods": [
            "ccxt.fetch_ohlcv.price_mark",
            "ccxt.okx.publicGetPublicFundingRateHistory",
        ],
        "symbol": SYMBOL,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One-shot V8 publication and mark/funding evidence recorder."
    )
    parser.add_argument("--poll-once", action="store_true")
    parser.add_argument("--freeze-manifest-sha256")
    args = parser.parse_args(argv)
    result = (
        poll_once(expected_manifest_sha256=args.freeze_manifest_sha256)
        if args.poll_once
        else plan()
    )
    print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
