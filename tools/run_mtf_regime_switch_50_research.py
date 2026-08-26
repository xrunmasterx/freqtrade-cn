"""Run the frozen regime-switch matrix using the audited research runner."""

from __future__ import annotations

import sys
from pathlib import Path

import run_mtf_capital_regime_50_research as audited_runner


REPO_ROOT = Path(__file__).resolve().parents[1]
USER_DATA = REPO_ROOT / "ft_userdata" / "user_data"
STRATEGY_DIR = USER_DATA / "strategies"
DATA_ROOT = REPO_ROOT / "ft_userdata" / "runtime" / "freqtrade-futures" / "data-mtf-capital-regime-research"
RESEARCH_ROOT = USER_DATA / "research_data" / "mtf-regime-switch-50"


def _load_variants() -> list[dict[str, object]]:
    sys.path.insert(0, str(REPO_ROOT / "freqtrade"))
    sys.path.insert(0, str(STRATEGY_DIR))
    from MultiTimeframeRegimeSwitchResearchStrategy import VARIANT_SPECS

    variants = [dict(item) for item in VARIANT_SPECS]
    if len(variants) != 50 or len({item["code"] for item in variants}) != 50:
        raise RuntimeError("the regime-switch matrix must contain exactly 50 unique variants")
    return variants


def main() -> int:
    audited_runner.REPO_ROOT = REPO_ROOT
    audited_runner.USER_DATA = USER_DATA
    audited_runner.STRATEGY_DIR = STRATEGY_DIR
    audited_runner.STRATEGY_SOURCE = STRATEGY_DIR / "MultiTimeframeRegimeSwitchResearchStrategy.py"
    audited_runner.EXAMPLE_CONFIG = USER_DATA / "config.mtf-regime-switch-research.example.json"
    audited_runner.DATA_ROOT = DATA_ROOT
    audited_runner.DATA_DIR = DATA_ROOT / "okx"
    audited_runner.RESEARCH_ROOT = RESEARCH_ROOT
    audited_runner.RESULT_ROOT = RESEARCH_ROOT / "results"
    audited_runner.CONFIG_PATH = RESEARCH_ROOT / "backtest-config.json"
    audited_runner.PREREGISTRATION_PATH = RESEARCH_ROOT / "PREREGISTRATION.md"
    audited_runner.AMENDMENT_PATH = RESEARCH_ROOT / "AMENDMENT-2026-08-14.md"
    audited_runner.DIAGNOSTIC_PATH = (
        REPO_ROOT / "ft_userdata" / "user_data" / "research_data" / "mtf-capital-regime-50" / "diagnostics" / "diagnostics.json"
    )
    audited_runner.MANIFEST_PATH = DATA_ROOT / "manifest.json"
    audited_runner.MARK_PATH = DATA_ROOT / "okx" / "futures" / "BTC_USDT_USDT-1h-mark.feather"
    audited_runner._load_variants = _load_variants
    return audited_runner.main()


if __name__ == "__main__":
    raise SystemExit(main())
