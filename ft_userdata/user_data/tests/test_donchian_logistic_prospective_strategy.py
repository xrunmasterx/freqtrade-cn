# ruff: noqa: E402, S101

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from freqtrade.configuration import TimeRange
from freqtrade.enums import CandleType, ExitType, MarginMode, RunMode, TradingMode
from freqtrade.exceptions import OperationalException
from freqtrade.exchange.exchange import TICK_SIZE
from freqtrade.optimize.backtesting import (
    DATE_IDX,
    ENTER_TAG_IDX,
    LONG_IDX,
    OPEN_IDX,
    Backtesting,
)
from freqtrade.persistence import Trade
from freqtrade.strategy.strategy_wrapper import strategy_safe_wrapper


STRATEGY_DIR = Path(__file__).resolve().parents[1] / "strategies"
CONFIG_PATH = STRATEGY_DIR.parent / "config.donchian-logistic-prospective.example.json"
sys.path.insert(0, str(STRATEGY_DIR))

from DonchianLogisticProspectiveStrategy import (
    DonchianLogisticProspectiveStrategy,
)


def sidecar_frame(**overrides) -> pd.DataFrame:
    decision = pd.Timestamp("2026-08-14T00:05:00Z")
    values = {
        "date": [decision],
        "execution_time": [decision + pd.Timedelta(minutes=5)],
        "computed_at": [decision + pd.Timedelta(seconds=10)],
        "projection_durable_at": [decision + pd.Timedelta(seconds=20)],
        "direction": ["long"],
        "predicted_positive": [True],
        "event_semantic_sha256": ["1" * 64],
        "projection_semantic_sha256": ["2" * 64],
        "publication_receipt_semantic_sha256": ["3" * 64],
    }
    values.update(overrides)
    return pd.DataFrame(values, columns=DonchianLogisticProspectiveStrategy.sidecar_columns)


def frozen_config(sidecar_path: Path, **overrides) -> dict:
    config = {
        "exchange": {"name": "okx", "pair_whitelist": ["BTC/USDT:USDT"]},
        "pairlists": [{"method": "StaticPairList"}],
        "trading_mode": TradingMode.FUTURES,
        "margin_mode": MarginMode.ISOLATED,
        "timeframe": "5m",
        "max_open_trades": 1,
        "stake_currency": "USDT",
        "stake_amount": "unlimited",
        "tradable_balance_ratio": 1.0,
        "dry_run_wallet": 1000,
        "fee": 0.0006,
        "runmode": RunMode.BACKTEST,
        "donchian_logistic_signal_sidecar": str(sidecar_path.resolve()),
    }
    config.update(overrides)
    return config


def attach_execution_context(strategy, *, full_stake: float = 1000, max_leverage: float = 20):
    exchange = SimpleNamespace(get_max_leverage=lambda pair, stake: max_leverage)
    strategy.dp = SimpleNamespace(
        _exchange=exchange,
        current_whitelist=lambda: ["BTC/USDT:USDT"],
    )
    strategy.wallets = SimpleNamespace(get_total_stake_amount=lambda: full_stake)


def test_frozen_strategy_values_and_plain_exit_signals_are_disabled():
    strategy = DonchianLogisticProspectiveStrategy(config={})

    assert strategy.timeframe == "5m"
    assert strategy.can_short is True
    assert strategy.max_open_trades == 1
    assert strategy.leverage_value == 14.0
    assert strategy.stoploss == -0.21
    assert strategy.minimal_roi == {}
    assert strategy.use_custom_roi is True
    assert strategy.use_exit_signal is True
    assert strategy.trailing_stop is False
    assert strategy.position_adjustment_enable is False
    assert strategy.process_only_new_candles is True
    assert strategy.startup_candle_count == 0
    assert strategy.order_types["stoploss_on_exchange"] is False

    result = strategy.populate_exit_trend(pd.DataFrame({"date": [pd.Timestamp.now(tz="UTC")]}), {})
    assert result["exit_long"].tolist() == [0]
    assert result["exit_short"].tolist() == [0]


def test_auditable_example_config_freezes_effective_research_settings():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    assert config["strategy"] == "DonchianLogisticProspectiveStrategy"
    assert config["exchange"]["name"] == "okx"
    assert config["exchange"]["pair_whitelist"] == ["BTC/USDT:USDT"]
    assert config["pairlists"] == [{"method": "StaticPairList"}]
    assert config["trading_mode"] == "futures"
    assert config["margin_mode"] == "isolated"
    assert config["timeframe"] == "5m"
    assert "timeframe_detail" not in config
    assert config["dry_run_wallet"] == 1000
    assert config["max_open_trades"] == 1
    assert config["stake_amount"] == "unlimited"
    assert config["tradable_balance_ratio"] == 1.0
    assert config["fee"] == 0.0006
    assert "futures_funding_rate" not in config
    assert "available_capital" not in config
    assert config["use_exit_signal"] is True
    assert config["exit_profit_only"] is False
    assert config["position_stacking"] is False
    assert config["position_adjustment_enable"] is False
    assert config["order_types"]["stoploss_on_exchange"] is False


def test_sidecar_signal_stays_on_decision_row_for_engine_shift():
    strategy = DonchianLogisticProspectiveStrategy(config={})
    signals = DonchianLogisticProspectiveStrategy.validate_signal_sidecar(sidecar_frame())
    strategy._prospective_signals = signals
    decision = signals.loc[0, "date"]
    candles = pd.DataFrame(
        {
            "date": [decision, decision + pd.Timedelta(minutes=5)],
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [1.0, 1.0],
        }
    )

    populated = strategy.populate_indicators(candles, {"pair": strategy.pair})
    populated = strategy.populate_entry_trend(populated, {"pair": strategy.pair})

    assert populated["enter_long"].tolist() == [1, 0]
    assert populated["enter_short"].tolist() == [0, 0]
    assert populated.loc[0, "enter_tag"] == f"v8:long:{'1' * 64}"
    assert len(populated.loc[0, "enter_tag"]) < 255
    assert pd.isna(populated.loc[1, "enter_tag"])
    assert signals.loc[0, "execution_time"] == decision + pd.Timedelta(minutes=5)


def test_short_signal_tag_binds_the_complete_event_hash():
    strategy = DonchianLogisticProspectiveStrategy(config={})
    strategy._prospective_signals = sidecar_frame(direction=["short"])
    decision = strategy._prospective_signals.loc[0, "date"]
    candles = pd.DataFrame(
        {"date": [decision, decision + pd.Timedelta(minutes=5)]}
    )

    populated = strategy.populate_indicators(candles, {"pair": strategy.pair})
    populated = strategy.populate_entry_trend(populated, {"pair": strategy.pair})

    assert populated.loc[0, "enter_short"] == 1
    assert populated.loc[0, "enter_tag"] == f"v8:short:{'1' * 64}"


@pytest.mark.parametrize(
    ("dates", "message"),
    [
        (
            lambda decision: [
                decision.tz_localize(None),
                (decision + pd.Timedelta(minutes=5)).tz_localize(None),
            ],
            "UTC datetime",
        ),
        (
            lambda decision: [decision + pd.Timedelta(minutes=5), decision],
            "strictly ordered",
        ),
        (
            lambda decision: [
                decision,
                decision + pd.Timedelta(minutes=5),
                decision + pd.Timedelta(minutes=15),
            ],
            "continuous 5m",
        ),
        (
            lambda decision: [
                decision + pd.Timedelta(minutes=5),
                decision + pd.Timedelta(minutes=10),
            ],
            "decision D",
        ),
        (lambda decision: [decision], "execution E"),
    ],
)
def test_candle_rows_fail_closed_before_signal_projection(dates, message):
    strategy = DonchianLogisticProspectiveStrategy(config={})
    strategy._prospective_signals = sidecar_frame()
    decision = strategy._prospective_signals.loc[0, "date"]
    candles = pd.DataFrame({"date": dates(decision)})

    with pytest.raises(OperationalException, match=message):
        strategy.populate_indicators(candles, {"pair": strategy.pair})


def test_freqtrade_engine_shifts_decision_signal_to_execution_open_at_14x():
    strategy = DonchianLogisticProspectiveStrategy(config={})
    strategy._prospective_signals = sidecar_frame()
    decision = strategy._prospective_signals.loc[0, "date"]
    candles = pd.DataFrame(
        {
            "date": pd.date_range(decision, periods=3, freq="5min", tz="UTC"),
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 101.5, 102.5],
            "volume": [1.0, 1.0, 1.0],
        }
    )
    analyzed = strategy.populate_indicators(candles, {"pair": strategy.pair})

    engine = object.__new__(Backtesting)
    engine.strategy = strategy
    engine.dataprovider = SimpleNamespace(_set_cached_df=lambda *args: None)
    engine.config = {"candle_type_def": CandleType.FUTURES}
    engine.timeframe = "5m"
    engine.timerange = TimeRange()
    engine.required_startup = 0
    engine.progress = None
    engine.abort = False
    rows = engine._get_ohlcv_as_lists({strategy.pair: analyzed})[strategy.pair]

    execution_row = rows[0]
    assert execution_row[DATE_IDX] == decision + pd.Timedelta(minutes=5)
    assert execution_row[OPEN_IDX] == 101.0
    assert execution_row[LONG_IDX] == 1
    assert execution_row[ENTER_TAG_IDX] == f"v8:long:{'1' * 64}"

    engine.trading_mode = TradingMode.FUTURES
    engine.exchange = SimpleNamespace(
        get_max_leverage=lambda pair, stake: 20.0,
        get_min_pair_stake_amount=lambda *args, **kwargs: 0.0,
        get_max_pair_stake_amount=lambda *args, **kwargs: 1000.0,
    )
    engine.wallets = SimpleNamespace(
        get_trade_stake_amount=lambda *args, **kwargs: 1000.0,
        get_available_stake_amount=lambda: 1000.0,
        validate_stake_amount=lambda **kwargs: kwargs["stake_amount"],
    )
    rate, stake, leverage, _ = engine.get_valid_entry_price_and_stake(
        strategy.pair,
        execution_row,
        execution_row[OPEN_IDX],
        0.0,
        "long",
        execution_row[DATE_IDX].to_pydatetime(),
        execution_row[ENTER_TAG_IDX],
        None,
        "market",
        None,
        TICK_SIZE,
    )

    assert rate == 101.0
    assert stake == 1000.0
    assert leverage == 14.0


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"execution_time": [pd.Timestamp("2026-08-14T00:15:00Z")]}, r"date \+ 5m"),
        ({"computed_at": [pd.Timestamp("2026-08-14T00:10:00Z")]}, "outside"),
        (
            {"projection_durable_at": [pd.Timestamp("2026-08-14T00:10:00Z")]},
            "durable publication receipt",
        ),
        ({"predicted_positive": [False]}, "predicted_positive"),
        ({"event_semantic_sha256": ["not-a-hash"]}, "event_semantic_sha256"),
    ],
)
def test_sidecar_validation_fails_closed(override, message):
    with pytest.raises(OperationalException, match=message):
        DonchianLogisticProspectiveStrategy.validate_signal_sidecar(
            sidecar_frame(**override)
        )


def test_sidecar_requires_unique_ordered_decisions():
    first = sidecar_frame()
    duplicate = pd.concat([first, first], ignore_index=True)

    with pytest.raises(OperationalException, match="unique and ordered"):
        DonchianLogisticProspectiveStrategy.validate_signal_sidecar(duplicate)


def test_bot_start_accepts_only_frozen_execution_config(tmp_path):
    path = tmp_path / "signals.feather"
    sidecar_frame().to_feather(path)
    strategy = DonchianLogisticProspectiveStrategy(config=frozen_config(path))
    attach_execution_context(strategy)

    strategy.bot_start()

    assert len(strategy._prospective_signals) == 1


@pytest.mark.parametrize(
    "override",
    [
        {"timeframe": "15m"},
        {"max_open_trades": 2},
        {"stake_amount": 1000},
        {"tradable_balance_ratio": 0.99},
        {"margin_mode": MarginMode.CROSS},
        {"dry_run_wallet": 2000},
        {"fee": 0.0008},
        {"timeframe_detail": "1m"},
        {"futures_funding_rate": 0.0},
        {"available_capital": 1000},
    ],
)
def test_bot_start_rejects_configuration_drift(tmp_path, override):
    path = tmp_path / "signals.feather"
    sidecar_frame().to_feather(path)
    strategy = DonchianLogisticProspectiveStrategy(config=frozen_config(path, **override))
    attach_execution_context(strategy)

    with pytest.raises(OperationalException):
        strategy.bot_start()


def test_bot_start_rejects_insufficient_full_wallet_leverage(tmp_path):
    path = tmp_path / "signals.feather"
    sidecar_frame().to_feather(path)
    strategy = DonchianLogisticProspectiveStrategy(config=frozen_config(path))
    attach_execution_context(strategy, max_leverage=13.0)

    with pytest.raises(OperationalException, match=r"only 13\.0x"):
        strategy.bot_start()


@pytest.mark.parametrize(
    "runmode",
    [
        RunMode.LIVE,
        RunMode.DRY_RUN,
        RunMode.HYPEROPT,
        RunMode.WEBSERVER,
        RunMode.PLOT,
        RunMode.OTHER,
    ],
)
def test_bot_start_rejects_every_non_backtest_runmode(tmp_path, runmode):
    path = tmp_path / "signals.feather"
    sidecar_frame().to_feather(path)
    strategy = DonchianLogisticProspectiveStrategy(config=frozen_config(path, runmode=runmode))
    attach_execution_context(strategy)

    with pytest.raises(OperationalException, match="only for backtesting"):
        strategy.bot_start()


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("process_only_new_candles", False),
        ("startup_candle_count", 1),
        ("leverage_value", 13.0),
        ("target_underlying_ratio", 0.05),
        ("max_hold", timedelta(hours=47)),
    ],
)
def test_bot_start_rejects_resolved_strategy_drift(tmp_path, attribute, value):
    path = tmp_path / "signals.feather"
    sidecar_frame().to_feather(path)
    strategy = DonchianLogisticProspectiveStrategy(config=frozen_config(path))
    setattr(strategy, attribute, value)
    attach_execution_context(strategy)

    with pytest.raises(OperationalException, match="resolved strategy settings"):
        strategy.bot_start()


def test_order_callbacks_refuse_engine_clipped_leverage_or_stake_caps():
    strategy = DonchianLogisticProspectiveStrategy(config={})
    now = datetime(2026, 8, 14, tzinfo=UTC)

    # The engine catches callback exceptions and falls back to 1x, so this callback must
    # return 14 even when the engine will clip it; the stake callback is the rejection gate.
    assert strategy.leverage(strategy.pair, now, 100.0, 1.0, 13.0, None, "long") == 14.0
    assert strategy.leverage(strategy.pair, now, 100.0, 1.0, 20.0, None, "long") == 14.0
    assert (
        strategy.custom_stake_amount(
            strategy.pair, now, 100.0, 1000.0, None, 1000.0, 13.0, None, "long"
        )
        == 0.0
    )
    assert (
        strategy.custom_stake_amount(
            strategy.pair, now, 100.0, 1000.0, None, 999.0, 14.0, None, "long"
        )
        == 0.0
    )
    assert (
        strategy.custom_stake_amount(
            strategy.pair, now, 100.0, 1000.0, None, 1000.0, 14.0, None, "long"
        )
        == 1000.0
    )


def test_pinned_engine_clip_path_turns_insufficient_14x_tier_into_zero_stake():
    strategy = DonchianLogisticProspectiveStrategy(config={})
    now = datetime(2026, 8, 14, tzinfo=UTC)
    max_leverage = 13.0

    requested = strategy_safe_wrapper(strategy.leverage, default_retval=1.0)(
        pair=strategy.pair,
        current_time=now,
        current_rate=100.0,
        proposed_leverage=1.0,
        max_leverage=max_leverage,
        entry_tag=f"v8:long:{'1' * 64}",
        side="long",
    )
    engine_leverage = min(max(requested, 1.0), max_leverage)
    stake = strategy.custom_stake_amount(
        strategy.pair,
        now,
        100.0,
        1000.0,
        None,
        1000.0,
        engine_leverage,
        f"v8:long:{'1' * 64}",
        "long",
    )

    assert requested == 14.0
    assert engine_leverage == 13.0
    assert stake == 0.0


class FakeTrade:
    def __init__(self, *, is_short: bool, opened: datetime, open_rate: float = 100.0):
        self.is_short = is_short
        self.open_date_utc = opened
        self.open_rate = open_rate

    def calc_profit_ratio(self, rate: float) -> float:
        return (
            (self.open_rate - rate) / self.open_rate
            if self.is_short
            else rate / self.open_rate - 1
        )


def freqtrade_trade(*, is_short: bool, opened: datetime) -> Trade:
    return Trade(
        pair="BTC/USDT:USDT",
        stake_amount=1000.0,
        amount=140.0,
        open_date=opened,
        fee_open=0.0006,
        fee_close=0.0006,
        exchange="okx",
        open_rate=100.0,
        is_short=is_short,
        leverage=14.0,
        trading_mode=TradingMode.FUTURES,
        funding_fees=-1.2,
        price_precision=1e-8,
        precision_mode=TICK_SIZE,
        precision_mode_price=TICK_SIZE,
    )


@pytest.mark.parametrize(("is_short", "expected"), [(False, 0.04), (True, 0.04)])
def test_custom_roi_targets_four_percent_underlying(is_short, expected):
    strategy = DonchianLogisticProspectiveStrategy(config={})
    opened = datetime(2026, 8, 14, tzinfo=UTC)
    trade = FakeTrade(is_short=is_short, opened=opened)

    result = strategy.custom_roi(
        strategy.pair,
        trade,
        opened,
        0,
        None,
        "short" if is_short else "long",
    )

    assert result == pytest.approx(expected)


@pytest.mark.parametrize(("is_short", "target_rate"), [(False, 104.0), (True, 96.0)])
def test_freqtrade_roi_inversion_preserves_four_percent_underlying_with_costs(
    is_short, target_rate
):
    strategy = DonchianLogisticProspectiveStrategy(config={})
    opened = datetime(2026, 8, 14, tzinfo=UTC)
    trade = freqtrade_trade(is_short=is_short, opened=opened)

    roi = strategy.custom_roi(
        strategy.pair,
        trade,
        opened,
        0,
        None,
        "short" if is_short else "long",
    )

    assert trade.calc_close_rate_for_roi(roi) == pytest.approx(target_rate, abs=1e-6)


@pytest.mark.parametrize(("is_short", "expected_stop"), [(False, 98.5), (True, 101.5)])
def test_freqtrade_14x_stoploss_is_one_point_five_percent_underlying(
    is_short, expected_stop
):
    strategy = DonchianLogisticProspectiveStrategy(config={})
    trade = freqtrade_trade(is_short=is_short, opened=datetime(2026, 8, 14, tzinfo=UTC))

    trade.adjust_stop_loss(trade.open_rate, strategy.stoploss, initial=True)

    assert trade.stop_loss == pytest.approx(expected_stop, abs=trade.price_precision)


@pytest.mark.parametrize("is_short", [False, True])
def test_freqtrade_same_candle_stop_precedes_roi_and_deadline_precedes_both(is_short):
    strategy = DonchianLogisticProspectiveStrategy(config={})
    opened = datetime(2026, 8, 14, 0, 10, tzinfo=UTC)
    low, high = ((95.0, 102.0) if is_short else (98.0, 105.0))

    before_deadline = freqtrade_trade(is_short=is_short, opened=opened)
    before_deadline.adjust_stop_loss(before_deadline.open_rate, strategy.stoploss, initial=True)
    ordinary_exits = strategy.should_exit(
        before_deadline,
        100.0,
        opened + timedelta(hours=1),
        enter=False,
        exit_=False,
        low=low,
        high=high,
    )
    assert [result.exit_type for result in ordinary_exits] == [
        ExitType.STOP_LOSS,
        ExitType.ROI,
    ]

    deadline_trade = freqtrade_trade(is_short=is_short, opened=opened)
    deadline_trade.adjust_stop_loss(deadline_trade.open_rate, strategy.stoploss, initial=True)
    deadline_exits = strategy.should_exit(
        deadline_trade,
        100.0,
        opened + timedelta(hours=48),
        enter=False,
        exit_=False,
        low=low,
        high=high,
    )
    assert [result.exit_type for result in deadline_exits] == [
        ExitType.CUSTOM_EXIT,
        ExitType.STOP_LOSS,
        ExitType.ROI,
    ]

    row = (
        pd.Timestamp(opened + timedelta(hours=48)),
        99.0,
        high,
        low,
        100.0,
        0,
        0,
        0,
        0,
        None,
        None,
    )
    engine = object.__new__(Backtesting)
    assert (
        engine._get_close_rate(
            row,
            deadline_trade,
            opened + timedelta(hours=48),
            deadline_exits[0],
            48 * 60,
        )
        == 99.0
    )


def test_deadline_exit_is_enabled_only_at_or_after_48h():
    strategy = DonchianLogisticProspectiveStrategy(config={})
    opened = datetime(2026, 8, 14, tzinfo=UTC)
    trade = FakeTrade(is_short=False, opened=opened)

    assert (
        strategy.custom_exit(
            strategy.pair,
            trade,
            opened + timedelta(hours=47, minutes=55),
            1,
            0,
        )
        is None
    )
    assert (
        strategy.custom_exit(strategy.pair, trade, opened + timedelta(hours=48), 1, 0)
        == "deadline_48h_open"
    )
