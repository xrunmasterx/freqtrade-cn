import csv
import json
import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT_DIR / "tools"))

from lsri_validation_workflow import (  # noqa: E402
    WorkflowConfig,
    build_workflow_commands,
    encode_for_console,
    export_key_trade_candidates,
    split_monthly_timeranges,
)


def test_split_monthly_timeranges_keeps_partial_edges():
    assert split_monthly_timeranges("20260115-20260402") == [
        "20260115-20260201",
        "20260201-20260301",
        "20260301-20260401",
        "20260401-20260402",
    ]


def test_detail_command_uses_one_minute_timeframe_detail():
    config = WorkflowConfig(
        config="/freqtrade/user_data/config.lsri.futures.100u.json",
        timerange="20260101-20260201",
        pairs=["BTC/USDT:USDT"],
    )

    commands = build_workflow_commands(config, ["detail"])

    assert len(commands) == 1
    assert commands[0].name == "detail_1m"
    assert "--timeframe-detail" in commands[0].argv
    assert "1m" in commands[0].argv
    assert "--export" in commands[0].argv
    assert "signals" in commands[0].argv


def test_stress_commands_encode_each_fee_scenario():
    config = WorkflowConfig(
        config="/freqtrade/user_data/config.lsri.futures.100u.json",
        timerange="20260101-20260201",
        pairs=["BTC/USDT:USDT"],
        stress_fees=[0.001, 0.0015],
    )

    commands = build_workflow_commands(config, ["stress"])

    assert [command.name for command in commands] == [
        "stress_fee_0_0010",
        "stress_fee_0_0015",
    ]
    assert all("--timeframe-detail" in command.argv for command in commands)
    assert all("--fee" in command.argv for command in commands)


def test_export_key_trade_candidates_reads_freqtrade_zip():
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        zip_path = temp_path / "backtest.zip"
        result = {
            "strategy": {
                "LSRICoreStrategy": {
                    "trades": [
                        {
                            "pair": "BTC/USDT:USDT",
                            "open_date": "2026-01-01 00:00:00+00:00",
                            "close_date": "2026-01-01 01:00:00+00:00",
                            "profit_abs": -4.2,
                            "profit_ratio": -0.042,
                            "exit_reason": "stop_loss",
                        },
                        {
                            "pair": "ETH/USDT:USDT",
                            "open_date": "2026-01-02 00:00:00+00:00",
                            "close_date": "2026-01-02 01:00:00+00:00",
                            "profit_abs": 3.5,
                            "profit_ratio": 0.035,
                            "exit_reason": "long_tp_2_2r",
                        },
                    ]
                }
            }
        }
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("backtest-result.json", json.dumps(result))

        csv_path = temp_path / "key_trades.csv"
        count = export_key_trade_candidates(temp_path, csv_path, top_n=10)

        assert count == 2
        with csv_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert rows[0]["pair"] == "BTC/USDT:USDT"
        assert rows[0]["reason"] == "large_loss"
        assert rows[1]["reason"] == "large_win"


def test_export_key_trade_candidates_filters_strategy_name():
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        zip_path = temp_path / "backtest.zip"
        result = {
            "strategy": {
                "VolatilitySystem": {
                    "trades": [
                        {
                            "pair": "BTC/USDT:USDT",
                            "open_date": "2026-01-01 00:00:00+00:00",
                            "close_date": "2026-01-01 01:00:00+00:00",
                            "profit_abs": 100.0,
                            "profit_ratio": 1.0,
                            "exit_reason": "exit_signal",
                        }
                    ]
                },
                "LSRICoreStrategy": {
                    "trades": [
                        {
                            "pair": "BTC/USDT:USDT",
                            "open_date": "2026-01-02 00:00:00+00:00",
                            "close_date": "2026-01-02 01:00:00+00:00",
                            "profit_abs": -2.0,
                            "profit_ratio": -0.02,
                            "exit_reason": "early_time_stop_no_impulse",
                        }
                    ]
                },
            }
        }
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("backtest-result.json", json.dumps(result))

        csv_path = temp_path / "key_trades.csv"
        count = export_key_trade_candidates(
            temp_path,
            csv_path,
            strategy_filter="LSRICoreStrategy",
        )

        assert count == 1
        with csv_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert rows[0]["strategy"] == "LSRICoreStrategy"
        assert rows[0]["profit_abs"] == "-2.0"


def test_encode_for_console_replaces_unsupported_windows_console_chars():
    assert encode_for_console("Downloaded • 1m\n", "gbk") == b"Downloaded ? 1m\n"


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
            print(f"PASS {name}")
