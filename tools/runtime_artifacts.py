from __future__ import annotations

import ast
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from tools.committed_git import CommittedGitStore


_EXCHANGE_SENSITIVE_ALIASES = frozenset(
    {
        "key",
        "api_key",
        "apiKey",
        "secret",
        "password",
        "uid",
        "account_id",
        "accountId",
        "wallet_address",
        "walletAddress",
        "private_key",
        "privateKey",
    }
)
_CCXT_CONFIG_BAGS = ("ccxt_config", "ccxt_sync_config", "ccxt_async_config")
_CCXT_PRODUCT_KEYS = frozenset({"defaultType", "default_type"})


@dataclass(frozen=True, slots=True)
class CommittedPaperProbeArtifacts:
    root_commit: str
    backend_commit: str
    frontend_commit: str
    strategies_commit: str
    config_sha256: str
    strategy_sha256: str
    safety_sha256: str
    strategy_class_name: str


class _DuplicateJsonKey(ValueError):
    pass


class _NonFiniteJsonNumber(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def _reject_nonfinite_number(_value: str) -> None:
    raise _NonFiniteJsonNumber


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise _NonFiniteJsonNumber
    return parsed


def _strict_json(document: bytes, identity: str) -> object:
    try:
        text = document.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"{identity} JSON must be UTF-8") from None
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_number,
            parse_float=_parse_finite_float,
        )
    except _DuplicateJsonKey:
        raise ValueError(f"{identity} JSON contains a duplicate key") from None
    except _NonFiniteJsonNumber:
        raise ValueError(f"{identity} JSON contains a non-finite number") from None
    except json.JSONDecodeError:
        raise ValueError(f"{identity} JSON is invalid") from None


def _validate_config(document: bytes) -> None:
    payload = _strict_json(document, "config")
    if not isinstance(payload, dict):
        raise ValueError("config root must be a JSON object")
    if payload.get("dry_run") is not True:
        raise ValueError("config dry_run must be exact boolean true")
    if payload.get("trading_mode") != "spot":
        raise ValueError("config trading_mode must be spot")
    exchange = payload.get("exchange")
    if not isinstance(exchange, dict) or exchange.get("name") != "bitget":
        raise ValueError("config exchange must be bitget")
    if any(
        exchange[field] not in (None, "")
        for field in _EXCHANGE_SENSITIVE_ALIASES
        if field in exchange
    ):
        raise ValueError("exchange write credential must be empty")
    for field in _CCXT_CONFIG_BAGS:
        if field not in exchange:
            continue
        bag = exchange[field]
        if not isinstance(bag, dict):
            raise ValueError("CCXT configuration bag must be a JSON object")
        _validate_ccxt_node(bag)


def _validate_ccxt_node(value: object) -> None:
    if isinstance(value, list):
        for item in value:
            _validate_ccxt_node(item)
        return
    if not isinstance(value, dict):
        return
    for field, nested in value.items():
        if field in _EXCHANGE_SENSITIVE_ALIASES and nested not in (None, ""):
            raise ValueError("exchange write credential must be empty")
        if field in _CCXT_PRODUCT_KEYS and nested != "spot":
            raise ValueError("CCXT product override must remain spot")
        if field == "fetchMarkets":
            if not isinstance(nested, dict):
                raise ValueError("CCXT product override must remain spot")
            if "types" in nested and nested["types"] != ["spot"]:
                raise ValueError("CCXT product override must remain spot")
        _validate_ccxt_node(nested)


def _validate_safety(document: bytes) -> None:
    payload = _strict_json(document, "safety")
    if not isinstance(payload, dict):
        raise ValueError("safety root must be a JSON object")
    if payload.get("dry_run") is not True:
        raise ValueError("safety dry_run must be exact boolean true")


def _strategy_class_name(document: bytes) -> str:
    try:
        source = document.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("strategy source must be UTF-8") from None
    try:
        module = ast.parse(source, filename="<committed-strategy>")
    except (SyntaxError, ValueError):
        raise ValueError("strategy syntax is invalid") from None
    classes = [node for node in ast.walk(module) if isinstance(node, ast.ClassDef)]
    if len(classes) != 1:
        raise ValueError("strategy must declare exactly one SampleStrategy class")
    if classes[0].name != "SampleStrategy" or classes[0] not in module.body:
        raise ValueError("strategy class must be the top-level SampleStrategy")
    return "SampleStrategy"


def read_committed_paper_probe_artifacts(
    root: Path,
    commit: str,
) -> CommittedPaperProbeArtifacts:
    store = CommittedGitStore(root, commit)
    store.assert_runtime_checkout_clean()
    config = store.read_runtime_config_blob()
    strategy = store.read_runtime_strategy_blob()
    safety = store.read_runtime_safety_blob()

    _validate_config(config)
    strategy_class_name = _strategy_class_name(strategy)
    _validate_safety(safety)

    return CommittedPaperProbeArtifacts(
        root_commit=store.root_commit,
        backend_commit=store.backend_commit,
        frontend_commit=store.frontend_commit,
        strategies_commit=store.strategies_commit,
        config_sha256=hashlib.sha256(config).hexdigest(),
        strategy_sha256=hashlib.sha256(strategy).hexdigest(),
        safety_sha256=hashlib.sha256(safety).hexdigest(),
        strategy_class_name=strategy_class_name,
    )
