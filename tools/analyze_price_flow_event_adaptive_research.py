from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from tools.run_price_flow_event_adaptive_research import _trade_fingerprint

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULT_ROOT = (
    REPO_ROOT
    / "ft_userdata"
    / "runtime"
    / "freqtrade-futures"
    / "backtest_results"
    / "price-flow-event-adaptive-20-rounds"
)
PROMOTED_STRATEGY = "PriceFlowParticipationFreshnessStrategy"
PROMOTED_FILE = (
    REPO_ROOT
    / "ft_userdata"
    / "user_data"
    / "strategies"
    / f"{PROMOTED_STRATEGY}.py"
)


def trade_summary(values: pd.Series) -> dict[str, float | int | None]:
    profits = pd.Series(values, dtype=float).dropna()
    winners = profits[profits > 0]
    losers = profits[profits < 0]
    payoff = None
    if not winners.empty and not losers.empty:
        payoff = winners.mean() / abs(losers.mean())
    profit_factor = None
    if not losers.empty:
        profit_factor = winners.sum() / abs(losers.sum())
    elif not winners.empty:
        profit_factor = math.inf
    return {
        "trades": len(profits),
        "winrate_pct": round(float((profits > 0).mean() * 100), 10) if len(profits) else 0.0,
        "payoff": round(float(payoff), 10) if payoff is not None else None,
        "profit_factor": (
            round(float(profit_factor), 10) if profit_factor is not None else None
        ),
        "profit_sum_pct": round(float(profits.sum() * 100), 10),
    }


def trigger_labels(frame: pd.DataFrame) -> pd.Series:
    is_short = frame["is_short"].astype(bool)
    price = pd.Series(
        np.where(
            is_short,
            frame["ci_price_accept_short"].fillna(False),
            frame["ci_price_accept_long"].fillna(False),
        ),
        index=frame.index,
        dtype=bool,
    )
    fresh = pd.Series(
        np.where(
            is_short,
            frame["bin_taker_imbalance"].le(frame["bin_taker_lag2"]),
            frame["bin_taker_imbalance"].ge(frame["bin_taker_lag2"]),
        ),
        index=frame.index,
        dtype=bool,
    )
    labels = np.select(
        [price & fresh, price, fresh],
        ["both", "price_acceptance_only", "fresh_flow_only"],
        default="neither",
    )
    return pd.Series(labels, index=frame.index, dtype=str)


def continuous_wallet_monthly(
    wallet: pd.DataFrame,
    trades: pd.DataFrame,
    *,
    start: str,
    end: str,
) -> list[dict[str, float | int | str]]:
    wallet = wallet.copy()
    wallet["date"] = pd.to_datetime(wallet["date"], utc=True)
    wallet = wallet.sort_values("date")
    trades = trades.copy()
    trades["open_date"] = pd.to_datetime(trades["open_date"], utc=True)
    trades["close_date"] = pd.to_datetime(trades["close_date"], utc=True)

    start_period = pd.Timestamp(start).to_period("M")
    end_period = pd.Timestamp(end).to_period("M")
    periods = pd.period_range(start_period, end_period - 1, freq="M")
    previous_balance = float(wallet.iloc[0]["total_quote"])
    rows: list[dict[str, float | int | str]] = []
    for period in periods:
        start_time = pd.Timestamp(period.start_time, tz="UTC")
        end_time = pd.Timestamp((period + 1).start_time, tz="UTC")
        month_wallet = wallet[wallet["date"].ge(start_time) & wallet["date"].lt(end_time)]
        end_balance = (
            float(month_wallet.iloc[-1]["total_quote"])
            if not month_wallet.empty
            else previous_balance
        )
        opened = trades["open_date"].ge(start_time) & trades["open_date"].lt(end_time)
        closed = trades["close_date"].ge(start_time) & trades["close_date"].lt(end_time)
        rows.append(
            {
                "month": str(period),
                "start_balance": round(previous_balance, 10),
                "end_balance": round(end_balance, 10),
                "return_pct": round((end_balance / previous_balance - 1) * 100, 10),
                "entries_opened": int(opened.sum()),
                "trades_closed": int(closed.sum()),
            }
        )
        previous_balance = end_balance
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _result_zip(directory: Path) -> Path:
    last_result = directory / ".last_result.json"
    if last_result.is_file():
        name = json.loads(last_result.read_text(encoding="utf-8"))["latest_backtest"]
        archive = directory / name
        if archive.is_file():
            return archive
    archives = sorted(directory.glob("*.zip"), key=lambda path: path.stat().st_mtime)
    if not archives:
        raise FileNotFoundError(f"No backtest archive in {directory}")
    return archives[-1]


def _load_result(directory: Path, strategy: str) -> tuple[dict[str, Any], Path]:
    archive = _result_zip(directory)
    with zipfile.ZipFile(archive) as bundle:
        result_name = next(
            name
            for name in bundle.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        )
        payload = json.loads(bundle.read(result_name))
    return payload["strategy"][strategy], archive


def _load_wallet(archive: Path) -> pd.DataFrame:
    with zipfile.ZipFile(archive) as bundle:
        name = next(name for name in bundle.namelist() if name.endswith("_wallet.feather"))
        return pd.read_feather(io.BytesIO(bundle.read(name)))


def _load_signals(
    directory: Path, strategy: str
) -> tuple[dict[str, pd.DataFrame], dict[str, Any], Path]:
    result, archive = _load_result(directory, strategy)
    with zipfile.ZipFile(archive) as bundle:
        name = next(name for name in bundle.namelist() if name.endswith("_signals.pkl"))
        signals = joblib.load(io.BytesIO(bundle.read(name)))[strategy]
    return signals, result, archive


def _result_metrics(
    code: str,
    fee: float,
    result: dict[str, Any],
    archive: Path,
) -> dict[str, Any]:
    summary = trade_summary(pd.Series([trade["profit_ratio"] for trade in result["trades"]]))
    total = next(row for row in result["results_per_pair"] if row["key"] == "TOTAL")
    try:
        artifact = str(archive.relative_to(REPO_ROOT))
    except ValueError:
        artifact = str(archive)
    return {
        "code": code,
        "fee_per_side_pct": fee * 100,
        **summary,
        "profit_factor": float(total["profit_factor"]),
        "wallet_profit_pct": float(total["profit_total_pct"]),
        "max_drawdown_pct": float(result["max_drawdown_account"]) * 100,
        "final_balance": float(result["final_balance"]),
        "trade_fingerprint": _trade_fingerprint(result["trades"]),
        "artifact": artifact,
        "artifact_sha256": _sha256(archive),
    }


def _join_signals() -> tuple[pd.DataFrame, Path]:
    strategy = "PriceFlowEventAdaptive10Strategy"
    signals, result, archive = _load_signals(RESULT_ROOT / "analysis" / "e10-signals", strategy)
    frames: list[pd.DataFrame] = []
    for pair, dataframe in signals.items():
        pair_frame = dataframe.copy()
        pair_frame["pair"] = pair
        frames.append(pair_frame)
    signal_frame = pd.concat(frames, ignore_index=True)
    signal_frame["decision_time"] = pd.to_datetime(signal_frame["decision_time"], utc=True)
    trades = pd.DataFrame(result["trades"])
    trades["open_date"] = pd.to_datetime(trades["open_date"], utc=True)
    joined = trades.merge(
        signal_frame,
        left_on=["pair", "open_date"],
        right_on=["pair", "decision_time"],
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    missing = joined["_merge"].ne("both")
    if missing.any():
        raise RuntimeError(f"Signal join failed for {int(missing.sum())} E10 trades")
    joined = joined.drop(columns="_merge")
    joined["trigger"] = trigger_labels(joined)
    if joined["trigger"].eq("neither").any():
        raise RuntimeError("E10 emitted a trade without either frozen trigger")
    return joined, archive


def _attribution_rows(joined: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    trigger_rows: list[dict[str, Any]] = []
    trigger_order = ["both", "price_acceptance_only", "fresh_flow_only"]
    for label in trigger_order:
        subset = joined[joined["trigger"].eq(label)]
        trigger_rows.append({"group": label, **trade_summary(subset["profit_ratio"])})

    scheduled = joined["ea_minutes_from_scheduled"]
    quarterly = joined["ea_quarterly_expiry_minutes"]
    flags: dict[str, pd.Series] = {
        "FOMC pre 6h": joined["ea_minutes_from_fomc"].ge(-360)
        & joined["ea_minutes_from_fomc"].lt(0),
        "FOMC post 6h": joined["ea_minutes_from_fomc"].between(0, 360),
        "CPI pre 6h": joined["minutes_from_cpi"].ge(-360)
        & joined["minutes_from_cpi"].lt(0),
        "CPI post 6h": joined["minutes_from_cpi"].between(0, 360),
        "scheduled pre 6h": scheduled.ge(-360) & scheduled.lt(0),
        "scheduled post 6h": scheduled.between(0, 360),
        "scheduled post 6-24h": scheduled.gt(360) & scheduled.le(1440),
        "policy post 24h": joined["ea_policy_post_24h"].fillna(False).astype(bool),
        "quarterly expiry pre 6h": quarterly.ge(-360) & quarterly.lt(0),
        "quarterly expiry post 24h": quarterly.between(0, 1440),
        "endogenous shock 75m": joined["ea_shock_window_4"].fillna(False).astype(bool),
    }
    event_union = pd.concat(flags.values(), axis=1).any(axis=1)
    flags["outside all registered contexts"] = ~event_union
    event_rows = [
        {"group": "overall", **trade_summary(joined["profit_ratio"])}
    ]
    for label, mask in flags.items():
        event_rows.append({"group": label, **trade_summary(joined.loc[mask, "profit_ratio"])})
    joined["registered_event_context"] = event_union
    return trigger_rows, event_rows


def _challenge_bootstrap() -> dict[str, Any]:
    candidate, _ = _load_result(RESULT_ROOT / "challenge" / "e10", "PriceFlowEventAdaptive10Strategy")
    control, _ = _load_result(RESULT_ROOT / "challenge" / "c04", "PriceFlowEventAdaptiveControl")
    months = pd.period_range("2025-08", "2026-07", freq="M").astype(str).tolist()

    def blocks(result: dict[str, Any]) -> dict[str, list[float]]:
        values = {month: [] for month in months}
        for trade in result["trades"]:
            values[str(trade["open_date"])[:7]].append(float(trade["profit_ratio"]))
        return values

    candidate_blocks = blocks(candidate)
    control_blocks = blocks(control)
    rng = np.random.default_rng(20260805)
    samples: list[tuple[float, float, float, float, float]] = []
    for _ in range(20_000):
        selected = rng.integers(0, len(months), len(months))
        profits = pd.Series(
            [
                value
                for index in selected
                for value in candidate_blocks[months[int(index)]]
            ],
            dtype=float,
        )
        metrics = trade_summary(profits)
        candidate_sum = float(metrics["profit_sum_pct"])
        control_sum = (
            sum(sum(control_blocks[months[int(index)]]) for index in selected) * 100
        )
        samples.append(
            (
                candidate_sum,
                float(metrics["winrate_pct"]),
                float(metrics["profit_factor"] or np.nan),
                float(metrics["payoff"] or np.nan),
                candidate_sum - control_sum,
            )
        )
    sample_array = np.asarray(samples)
    names = ("profit_sum_pct", "winrate_pct", "profit_factor", "payoff", "delta_vs_c04_pp")
    intervals: dict[str, Any] = {}
    for column, name in enumerate(names):
        values = sample_array[:, column]
        intervals[name] = {
            "p2_5": float(np.nanpercentile(values, 2.5)),
            "median": float(np.nanpercentile(values, 50)),
            "p97_5": float(np.nanpercentile(values, 97.5)),
            "probability_above_zero": float(np.nanmean(values > 0)),
        }
    return {
        "method": "calendar-month block bootstrap with replacement",
        "seed": 20260805,
        "iterations": 20_000,
        "months": months,
        "intervals": intervals,
        "limitations": [
            "Does not correct family-wise error from selecting among 20 candidates.",
            "The challenge window had been viewed elsewhere in this session and is not pristine.",
            "Profit sums are trade-attribution returns, not the shared-wallet compounded return.",
        ],
    }


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    if isinstance(value, float) and math.isinf(value):
        return "∞"
    return f"{float(value):.{digits}f}"


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def _write_report(
    development: list[dict[str, Any]],
    challenge: list[dict[str, Any]],
    full: list[dict[str, Any]],
    c04_monthly: list[dict[str, Any]],
    monthly: list[dict[str, Any]],
    triggers: list[dict[str, Any]],
    events: list[dict[str, Any]],
    fees: list[dict[str, Any]],
    bootstrap: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    dev_rows = [
        [
            row["code"],
            row["trades"],
            f'{row["profit_pct"]:+.2f}%',
            f'{row["winrate"] * 100:.2f}%',
            _fmt(row["payoff"]),
            _fmt(row["profit_factor"]),
            f'{row["drawdown_pct"]:.2f}%',
            row["status"],
        ]
        for row in development
    ]
    challenge_by_code = {row["code"]: row for row in challenge}
    full_by_code = {row["code"]: row for row in full}
    comparison_rows: list[list[Any]] = []
    for code in ("C04", "E02", "E10", "E03"):
        for label, values in (
            ("挑战 1 年", challenge_by_code[code]),
            ("连续 3 年", full_by_code[code]),
        ):
            comparison_rows.append(
                [
                    label,
                    code,
                    values["trades"],
                    f'{values["profit_pct"]:+.2f}%',
                    f'{values["winrate"] * 100:.2f}%',
                    _fmt(values["payoff"]),
                    _fmt(values["profit_factor"]),
                    f'{values["drawdown_pct"]:.2f}%',
                ]
            )

    trigger_rows = [
        [
            row["group"],
            row["trades"],
            f'{row["winrate_pct"]:.2f}%',
            _fmt(row["payoff"]),
            _fmt(row["profit_factor"]),
            f'{row["profit_sum_pct"]:+.2f}%',
        ]
        for row in triggers
    ]
    event_rows = [
        [
            row["group"],
            row["trades"],
            f'{row["winrate_pct"]:.2f}%',
            _fmt(row["payoff"]),
            _fmt(row["profit_factor"]),
            f'{row["profit_sum_pct"]:+.2f}%',
        ]
        for row in events
    ]
    monthly_rows = [
        [
            e10_row["month"],
            f'{c04_row["return_pct"]:+.2f}%',
            _fmt(c04_row["end_balance"], 4),
            f'{e10_row["return_pct"]:+.2f}%',
            _fmt(e10_row["end_balance"], 4),
            f'{e10_row["return_pct"] - c04_row["return_pct"]:+.2f}pp',
        ]
        for c04_row, e10_row in zip(c04_monthly, monthly, strict=True)
    ]
    fee_rows = [
        [
            row["code"],
            f'{row["fee_per_side_pct"]:.2f}%',
            row["trades"],
            f'{row["wallet_profit_pct"]:+.2f}%',
            f'{row["winrate_pct"]:.2f}%',
            _fmt(row["payoff"]),
            _fmt(row["profit_factor"]),
            f'{row["max_drawdown_pct"]:.2f}%',
        ]
        for row in fees
    ]
    interval = bootstrap["intervals"]
    e10_full = full_by_code["E10"]
    e03_full = full_by_code["E03"]
    e10_challenge = challenge_by_code["E10"]
    e03_challenge = challenge_by_code["E03"]
    positive_months = sum(row["return_pct"] > 0 for row in monthly)
    negative_months = sum(row["return_pct"] < 0 for row in monthly)
    flat_months = len(monthly) - positive_months - negative_months
    c04_positive_months = sum(row["return_pct"] > 0 for row in c04_monthly)
    c04_negative_months = sum(row["return_pct"] < 0 for row in c04_monthly)
    c04_flat_months = len(c04_monthly) - c04_positive_months - c04_negative_months

    report = f"""# PriceFlow 事件自适应 20 轮研究与选择后审计

记录日期：2026-08-05

## 1. 结论

20 个预注册候选均已完成开发回测，没有追加第 21 个候选。最终固化策略为
`{PROMOTED_STRATEGY}`，对应预注册候选 E10。

选择 E10 而不是 E03 的原因是目标函数优先“胜率 + Payoff + PF”：挑战年 E10 为
{e10_challenge['profit_pct']:+.2f}% / 胜率 {e10_challenge['winrate'] * 100:.2f}% /
Payoff {_fmt(e10_challenge['payoff'])} / PF {_fmt(e10_challenge['profit_factor'])} /
回撤 {e10_challenge['drawdown_pct']:.2f}%，均优于 E03 的
{e03_challenge['profit_pct']:+.2f}% / {e03_challenge['winrate'] * 100:.2f}% /
{_fmt(e03_challenge['payoff'])} / {_fmt(e03_challenge['profit_factor'])} /
{e03_challenge['drawdown_pct']:.2f}%。连续三年 E03 收益只高 0.44 个百分点
（{e03_full['profit_pct']:+.2f}% 对 {e10_full['profit_pct']:+.2f}%），但 E10 的胜率、
Payoff、PF 和挑战年表现更强，因此按预定研究目标选 E10。

这仍是**历史研究候选**，不是已证明的 alpha，也没有获准进入 Paper/Live。挑战窗口只有
28 笔，ETH 仅 5 笔；20 候选选择效应、历史窗口已被查看、真实 funding/滑点/限价未成交
均未被充分解决。

## 2. 冻结规则与数据边界

- OKX BTC/USDT:USDT 与 ETH/USDT:USDT 永续，15m，共用 20 USDT 钱包，2x，最多一仓。
- `stake_amount=unlimited`，余额使用率 90%，逐边手续费 0.05%，`cache=none`。
- 开发窗 `[2023-08-01, 2025-08-01)`；挑战窗 `[2025-08-01, 2026-08-01)`；
  连续三年只用于完整复利路径和上下文，不提升验证等级。
- 20 轮定义在首次结果产生前冻结；预注册 SHA-256：
  `{receipt['preregistration_sha256']}`。
- FOMC/CPI 使用公开日历时间；无精确分钟的政策事件保守地从次日 00:00 UTC 才可用，
  不给事件预先赋多空方向。

## 3. 20 轮开发回测

{_markdown_table(['候选', '交易', '钱包收益', '胜率', 'Payoff', 'PF', '最大回撤', '冻结门槛状态'], dev_rows)}

E11–E16 试图提高频率，但交易数膨胀到 321–839 笔，胜率约 27%–33%，PF 约
0.93–1.17，最大回撤约 29%–65%。这构成了明确反证：在当前 15m 数据分辨率下，
仅放宽“吸收/接力”语义会重复交易同一噪声，价格结果加单一资金代理不足以识别资金目的。

## 4. 冻结挑战与连续共享钱包路径

{_markdown_table(['窗口', '候选', '交易', '钱包收益', '胜率', 'Payoff', 'PF', '最大回撤'], comparison_rows)}

三个正式候选 E02/E10/E03 在挑战年的四个季度逐笔收益和均为正，但样本很少。E10 连续
三年的年度逐笔收益和分别约 +33.51%、+43.23%、+71.51%；三年钱包从 20 USDT
变为 {e10_full['final_balance']:.4f} USDT。这是一次连续共用钱包复利路径，不是分段收益相加。

## 5. E10 的第一性原理机制与归因

E10 不使用事件方向下注。它先保留 C04 的价格结构与 CUSUM continuation，再要求：

1. 相对成交量至少 0.8，确认有足够市场参与；
2. 方向性价格接受，或当前 Binance 5m taker imbalance 相对第二滞后值没有同向衰减；
3. 所有 cross-venue 必需字段缺失时 fail closed。

{_markdown_table(['触发子集', '交易', '胜率', 'Payoff', '等权 PF', '逐笔收益和'], trigger_rows)}

归因表的 PF 与收益和按每笔 `profit_ratio` 等权计算，用于比较信号机制；它们不是按动态
仓位金额加权的钱包 PF，所以 overall 等权 PF 2.40 与共享钱包 PF 2.72 不矛盾。

“价格接受 + fresh flow 同时成立”最强；仅 fresh-flow 的 58 笔胜率和 PF 明显较弱。因此
不能把 E10 解释成“资金流单独预测未来”。更准确的解释是：价格先给出结果，成交参与和
同向 taker 未衰减用于排除部分低质量结果。下一阶段应把三个触发子集作为 shadow 标签
前瞻记录，不能看完历史后直接删除 fresh-only。

## 6. 大事件、政治政策与市场失真

{_markdown_table(['事件上下文（可重叠）', '交易', '胜率', 'Payoff', '等权 PF', '逐笔收益和'], event_rows)}

事件结果不支持“重大事件直接增加入场”的结论：E17（宏观前 6h 禁入、发布后严格确认）
在开发窗通过点门槛，但按冻结排序仅第 4，未进入最多 3 个候选的挑战，不能事后补测；
E18–E20 的更复杂宏观/政策/冲击组合没有通过开发门槛。E10 在 FOMC/CPI 前后 6 小时
总共只有 2 笔且都亏损；政策后 24 小时只有 2 笔且都亏损。内生冲击窗口 14 笔表现较好，
但这是选择后、小样本归因，只能生成下一轮预注册假设。现阶段事件更适合作为风险状态，
而不是额外 alpha 入场器。

事件清单来自官方一手时间源：[Federal Reserve FOMC calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)、
[BLS CPI schedule](https://www.bls.gov/schedule/news_release/cpi.htm)、
[SEC spot-Bitcoin ETP statement](https://www.sec.gov/newsroom/speeches-statements/gensler-statement-spot-bitcoin-011023)、
[SEC spot-Ether ETP order](https://www.sec.gov/files/rules/sro/nysearca/2024/34-100224.pdf)、
[White House digital-assets order](https://www.whitehouse.gov/presidential-actions/2025/01/strengthening-american-leadership-in-digital-financial-technology/)、
[Strategic Bitcoin Reserve order](https://www.whitehouse.gov/presidential-actions/2025/03/establishment-of-the-strategic-bitcoin-reserve-and-united-states-digital-asset-stockpile/)、
[2025 reciprocal-tariff action](https://www.whitehouse.gov/presidential-actions/2025/04/regulating-imports-with-a-reciprocal-tariff-to-rectify-trade-practices-that-contribute-large-and-persistent-annual-united-states-goods-trade-deficits/)
及 [BOJ 2024-07-31 decision](https://www.boj.or.jp/en/mopo/mpmdeci/state_2024/k240731a.htm)。

## 7. BTC + ETH 共用钱包逐月收益

下表同时给出 C04 与固化 E10 的连续 `wallet total_quote` 路径，按 UTC 月末权益计算月环比；
不是每月重置 20 USDT，也不是把单笔百分比相加。C04 的 36 个月为
{c04_positive_months} 个正月、{c04_negative_months} 个负月、{c04_flat_months} 个无变化月；
E10 为 {positive_months} 个正月、{negative_months} 个负月、{flat_months} 个无变化月。

{_markdown_table(['月份', 'C04 月收益', 'C04 月末权益', 'E10 月收益', 'E10 月末权益', 'E10-C04'], monthly_rows)}

月度离散很明显：例如 2024-11 +25.85%，但 2024-01 -5.42%、2024-06 -4.71%。
因此“长期总收益高”不等于每月稳定盈利。带开/平仓数的原始明细分别保存在
`c04-shared-wallet-monthly-mark-to-market.csv` 与 `e10-shared-wallet-monthly.csv`。

## 8. 成本、确定性与偏差审计

{_markdown_table(['候选', '逐边费率', '交易', '钱包收益', '胜率', 'Payoff', 'PF', '最大回撤'], fee_rows)}

- E10 在逐边费率从 0.05% 翻倍到 0.10% 后仍为 +176.31%、PF 2.29；但最大回撤升至
  11.92%，真实滑点和未成交仍可能更差。
- 原 E10、独立确定性重跑、具名固化策略三者的 111 笔 fingerprint 完全一致：
  `{receipt['trade_fingerprint']}`。
- 研究完成后只给事件距离函数增加了 `decision_time=NaT` 的 fail-closed guard，以消除
  启动期整数溢出警告；有效决策行逻辑未变，具名策略的逐笔 fingerprint 仍与原 E10 一致。
- Freqtrade Lookahead Analysis：100 个目标信号，`has_bias=False`，偏置 entry 0、exit 0。
- Recursive Analysis：startup 960/1200/1400 时 `flow_imbalance_8/24` 差异约 0%，
  `ema200_4h` 最大约 -0.001%，未发现 indicator-only lookahead。
- 早期 funding 数据从 2024-05-31 才开始；配置对缺口使用 `futures_funding_rate=0.0`。
  这不是完整的真实资金费率回放。

## 9. 不确定性与多重尝试

固定种子 20260805，按挑战年的 12 个日历月做 20,000 次有放回块 bootstrap：E10
逐笔收益和的 95% 区间约
[{interval['profit_sum_pct']['p2_5']:+.2f}%, {interval['profit_sum_pct']['p97_5']:+.2f}%]；
胜率区间约 [{interval['winrate_pct']['p2_5']:.2f}%, {interval['winrate_pct']['p97_5']:.2f}%]，
PF 区间约 [{interval['profit_factor']['p2_5']:.2f}, {interval['profit_factor']['p97_5']:.2f}]，
Payoff 区间约 [{interval['payoff']['p2_5']:.2f}, {interval['payoff']['p97_5']:.2f}]。

但 E10 相对 C04 的配对月度增量 95% 区间约
[{interval['delta_vs_c04_pp']['p2_5']:+.2f}pp, {interval['delta_vs_c04_pp']['p97_5']:+.2f}pp]，
增量大于 0 的 bootstrap 比例仅
{interval['delta_vs_c04_pp']['probability_above_zero'] * 100:.2f}%。因此“E10 在挑战年本身为正”
的证据强于“E10 确定优于 C04”。这些区间没有对 20 候选做 family-wise 修正，也不能
消除挑战窗口已被查看的问题。

## 10. 研究依据与边界

订单流不平衡与短期价格影响的联系有微观结构研究支持（[Cont, Kukanov & Stoikov](https://arxiv.org/abs/1011.6402)），
Bitcoin 期权净买压与价格/波动率的关系也有实证研究（[Alexander et al.](https://arxiv.org/abs/2109.02776)）。
这些研究支持“资金变量能解释形成机制”的研究方向，但不识别交易者身份、开平仓目的，
也不保证当前公开聚合指标可交易。当前 Deribit 期权样本稀疏，20 轮结果没有证明期权流
带来稳定增量。

## 11. 后续开发建议

1. 停止继续查看同一历史后微调 E10 阈值；在新数据上前瞻 shadow 比较 E10/C04/E03。
2. 建 point-in-time 实时 collector，记录 exchange timestamp、首次可见时间、watermark、
   缺口、重试与 schema；真实记录 funding、basis、下单/成交、未成交与滑点。
3. 预注册事件“意外程度”而不仅是日历：实际值相对共识、FOMC 文本/利率意外，事件后
   价格接受与 OI/taker 持续性；不知道发布时间的政策事件继续保守 fail closed。
4. 若追求更高频，新增真正的信息分辨率：order-book replenishment/cancellation、
   liquidation tape、跨 venue lead-lag；当前 E11–E16 已反证单纯放宽 15m 条件。
5. 期权研究使用逐笔成交时的 mark/IV、到期/执行价、可判定的净买压，并单独处理
   Deribit 与 Binance/OKX 的资金池、基差和可用时间，不把日级聚合混入现策略。
6. 至少积累 100 笔 forward 交易，且 BTC/ETH、long/short 各方向达到预注册最低样本，
   再讨论 Paper；通过真实执行压力和 kill-switch 前不得进入 Live。

## 12. 固化与运行边界

- 固化类：`{PROMOTED_STRATEGY}`
- 固化文件 SHA-256：`{receipt['source_hashes'][PROMOTED_FILE.name]}`
- E10 signals 一对一归因：{receipt['signal_joined_trades']}/111。
- 数据最后边界：2026-08-01 00:00 UTC；不是实时数据。
- 本研究没有修改机器人配置，没有启动 Paper/Live。
"""
    (RESULT_ROOT / "POST_SELECTION_AUDIT.md").write_text(report, encoding="utf-8")


def main() -> int:
    development = json.loads((RESULT_ROOT / "development-results.json").read_text(encoding="utf-8"))
    challenge = json.loads((RESULT_ROOT / "challenge-results.json").read_text(encoding="utf-8"))
    full = json.loads((RESULT_ROOT / "full-results.json").read_text(encoding="utf-8"))

    promoted_result, promoted_archive = _load_result(
        RESULT_ROOT / "promoted-validation", PROMOTED_STRATEGY
    )
    wallet = _load_wallet(promoted_archive)
    promoted_trades = pd.DataFrame(promoted_result["trades"])
    monthly = continuous_wallet_monthly(
        wallet,
        promoted_trades,
        start="2023-08-01",
        end="2026-08-01",
    )
    monthly_compounded_profit_pct = (
        math.prod(1 + float(row["return_pct"]) / 100 for row in monthly) - 1
    ) * 100
    promoted_wallet_profit_pct = (
        float(promoted_result["final_balance"]) / float(promoted_result["starting_balance"]) - 1
    ) * 100
    if not math.isclose(
        monthly_compounded_profit_pct,
        promoted_wallet_profit_pct,
        abs_tol=1e-7,
    ):
        raise RuntimeError("Monthly shared-wallet returns do not reproduce total profit")
    c04_result, c04_archive = _load_result(
        RESULT_ROOT / "full-3y" / "c04", "PriceFlowEventAdaptiveControl"
    )
    c04_monthly = continuous_wallet_monthly(
        _load_wallet(c04_archive),
        pd.DataFrame(c04_result["trades"]),
        start="2023-08-01",
        end="2026-08-01",
    )
    c04_monthly_compounded_profit_pct = (
        math.prod(1 + float(row["return_pct"]) / 100 for row in c04_monthly) - 1
    ) * 100
    c04_wallet_profit_pct = (
        float(c04_result["final_balance"]) / float(c04_result["starting_balance"]) - 1
    ) * 100
    if not math.isclose(
        c04_monthly_compounded_profit_pct,
        c04_wallet_profit_pct,
        abs_tol=1e-7,
    ):
        raise RuntimeError("C04 monthly shared-wallet returns do not reproduce total profit")

    joined, signal_archive = _join_signals()
    triggers, events = _attribution_rows(joined)
    event_columns = [
        "pair",
        "open_date",
        "close_date",
        "profit_ratio",
        "is_short",
        "trigger",
        "ea_minutes_from_fomc",
        "minutes_from_cpi",
        "ea_minutes_from_policy",
        "ea_quarterly_expiry_minutes",
        "ea_shock_window_4",
        "registered_event_context",
    ]

    full_by_code = {row["code"]: row for row in full}
    base_strategy = {
        "E02": "PriceFlowEventAdaptive02Strategy",
        "E10": "PriceFlowEventAdaptive10Strategy",
        "E03": "PriceFlowEventAdaptive03Strategy",
    }
    fee_directory = {
        "E02": RESULT_ROOT / "verification-fee" / "e02" / "fee-0p0010",
        "E10": RESULT_ROOT / "verification-fee-all" / "e10",
        "E03": RESULT_ROOT / "verification-fee-all" / "e03",
    }
    fees: list[dict[str, Any]] = []
    for code in ("E02", "E10", "E03"):
        base = full_by_code[code]
        fees.append(
            {
                "code": code,
                "fee_per_side_pct": 0.05,
                "trades": base["trades"],
                "winrate_pct": base["winrate"] * 100,
                "payoff": base["payoff"],
                "profit_factor": base["profit_factor"],
                "profit_sum_pct": sum(
                    values["profit_sum_pct"] for values in base["folds"].values()
                ),
                "wallet_profit_pct": base["profit_pct"],
                "max_drawdown_pct": base["drawdown_pct"],
                "final_balance": base["final_balance"],
                "trade_fingerprint": base["trade_fingerprint"],
                "artifact": base["artifact"],
                "artifact_sha256": base["artifact_sha256"],
            }
        )
        stressed_result, stressed_archive = _load_result(
            fee_directory[code], base_strategy[code]
        )
        fees.append(_result_metrics(code, 0.001, stressed_result, stressed_archive))

    e10_result, e10_archive = _load_result(
        RESULT_ROOT / "full-3y" / "e10", "PriceFlowEventAdaptive10Strategy"
    )
    deterministic_result, deterministic_archive = _load_result(
        RESULT_ROOT / "verification-determinism-e10", "PriceFlowEventAdaptive10Strategy"
    )
    fingerprints = {
        "e10_original": _trade_fingerprint(e10_result["trades"]),
        "e10_deterministic_rerun": _trade_fingerprint(deterministic_result["trades"]),
        "promoted": _trade_fingerprint(promoted_result["trades"]),
    }
    if len(set(fingerprints.values())) != 1:
        raise RuntimeError(f"Promotion parity failed: {fingerprints}")

    lookahead = pd.read_csv(RESULT_ROOT / "lookahead" / "lookahead.csv").iloc[0].to_dict()
    lookahead = {
        "strategy": str(lookahead["strategy"]),
        "has_bias": str(lookahead["has_bias"]).lower() == "true",
        "total_signals": int(lookahead["total_signals"]),
        "biased_entry_signals": int(lookahead["biased_entry_signals"]),
        "biased_exit_signals": int(lookahead["biased_exit_signals"]),
        "biased_indicators": (
            None if pd.isna(lookahead["biased_indicators"]) else str(lookahead["biased_indicators"])
        ),
    }
    bootstrap = _challenge_bootstrap()
    original_run_receipt = json.loads(
        (RESULT_ROOT / "run-receipt.json").read_text(encoding="utf-8")
    )
    runner_file = REPO_ROOT / "tools" / "run_price_flow_event_adaptive_research.py"
    runner_sha256 = _sha256(runner_file)
    if runner_sha256 != original_run_receipt["runner_sha256"]:
        raise RuntimeError("Frozen runner no longer matches the original run receipt")
    source_files = [
        PROMOTED_FILE,
        PROMOTED_FILE.with_name("PriceFlowEventAdaptiveResearchStrategy.py"),
        PROMOTED_FILE.with_name("PriceFlowCapitalIntentResearchStrategy.py"),
        PROMOTED_FILE.with_name("PriceFlowCrossVenueResearchStrategy.py"),
        PROMOTED_FILE.with_name("PriceFlowContinuationStrategy.py"),
    ]
    receipt = {
        "promoted_class": PROMOTED_STRATEGY,
        "promoted_file": str(PROMOTED_FILE.relative_to(REPO_ROOT)),
        "research_candidate": "E10",
        "preregistration_sha256": _sha256(RESULT_ROOT / "PREREGISTRATION.md"),
        "research_config_sha256": _sha256(RESULT_ROOT / "research-config.json"),
        "runner_sha256": runner_sha256,
        "original_research_strategy_sha256": original_run_receipt["strategy_sha256"],
        "data_manifest_sha256": original_run_receipt["data_manifest_sha256"],
        "trade_fingerprint": fingerprints["promoted"],
        "fingerprints": fingerprints,
        "deterministic": True,
        "promotion_parity": True,
        "signal_joined_trades": len(joined),
        "monthly_compounded_profit_pct": monthly_compounded_profit_pct,
        "c04_monthly_compounded_profit_pct": c04_monthly_compounded_profit_pct,
        "monthly_compounding_matches_total": True,
        "source_hashes": {path.name: _sha256(path) for path in source_files},
        "artifacts": {
            "e10_original": str(e10_archive.relative_to(REPO_ROOT)),
            "e10_deterministic_rerun": str(deterministic_archive.relative_to(REPO_ROOT)),
            "promoted_validation": str(promoted_archive.relative_to(REPO_ROOT)),
            "signals": str(signal_archive.relative_to(REPO_ROOT)),
        },
        "lookahead": lookahead,
        "recursive": {
            "pair": "BTC/USDT:USDT",
            "timerange": "20250801-20260801",
            "startup_candles": [960, 1200, 1400],
            "flow_imbalance_8_max_abs_pct": 0.0,
            "flow_imbalance_24_max_abs_pct": 0.0,
            "ema200_4h_max_abs_pct": 0.001,
            "indicator_only_lookahead": False,
        },
        "runtime_boundary": {
            "data_end_utc": "2026-08-01T00:00:00Z",
            "paper_or_live_changed": False,
        },
    }

    pd.DataFrame(monthly).to_csv(RESULT_ROOT / "e10-shared-wallet-monthly.csv", index=False)
    pd.DataFrame(c04_monthly).to_csv(
        RESULT_ROOT / "c04-shared-wallet-monthly-mark-to-market.csv", index=False
    )
    monthly_comparison = pd.DataFrame(
        {
            "month": [row["month"] for row in monthly],
            "c04_return_pct": [row["return_pct"] for row in c04_monthly],
            "c04_end_balance": [row["end_balance"] for row in c04_monthly],
            "e10_return_pct": [row["return_pct"] for row in monthly],
            "e10_end_balance": [row["end_balance"] for row in monthly],
        }
    )
    monthly_comparison["e10_minus_c04_pp"] = (
        monthly_comparison["e10_return_pct"] - monthly_comparison["c04_return_pct"]
    )
    monthly_comparison.to_csv(RESULT_ROOT / "c04-vs-e10-shared-wallet-monthly.csv", index=False)
    pd.DataFrame(triggers).to_csv(RESULT_ROOT / "e10-trigger-attribution.csv", index=False)
    pd.DataFrame(events).to_csv(RESULT_ROOT / "e10-event-attribution.csv", index=False)
    joined.loc[joined["registered_event_context"], event_columns].to_csv(
        RESULT_ROOT / "e10-event-trades.csv", index=False
    )
    pd.DataFrame(fees).to_csv(RESULT_ROOT / "shortlist-cost-verification.csv", index=False)
    (RESULT_ROOT / "post-selection-bootstrap.json").write_text(
        json.dumps(bootstrap, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (RESULT_ROOT / "promotion-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_report(
        development,
        challenge,
        full,
        c04_monthly,
        monthly,
        triggers,
        events,
        fees,
        bootstrap,
        receipt,
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
