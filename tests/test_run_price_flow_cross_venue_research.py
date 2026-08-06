from __future__ import annotations

import subprocess

from tools import run_price_flow_cross_venue_research as research


def test_backtest_runs_from_freqtrade_package_root(monkeypatch, tmp_path) -> None:
    observed: dict[str, object] = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(command, 1, "", "load failure")

    monkeypatch.setattr(research, "RESULT_ROOT", tmp_path)
    monkeypatch.setattr(research.subprocess, "run", fake_run)

    metrics = research._run_backtest(
        "PriceFlowCrossVenueControl", "B0", "d1", resume=False
    )

    assert observed["cwd"] == research.REPO_ROOT / "freqtrade"
    assert metrics.status == "INVALID_IMPLEMENTATION"
