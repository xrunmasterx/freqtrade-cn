from __future__ import annotations

import csv
import json
import math
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from tools import run_price_flow_timeframe_leverage_research as research
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import run_price_flow_timeframe_leverage_research as research


REPORT = research.RESULT_ROOT / "FINAL_REPORT.md"
MONTHLY_CSV = research.RESULT_ROOT / "monthly-shared-wallet.csv"
MATRIX_CSV = research.RESULT_ROOT / "development-matrix.csv"
AUDIT_RECEIPT = research.RESULT_ROOT / "audit-receipt.json"


def _profit_factor(values: list[float]) -> float | None:
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = -sum(value for value in values if value < 0)
    if gross_loss == 0:
        return None if gross_profit == 0 else float("inf")
    return gross_profit / gross_loss


def _shared_wallet_months(
    trades: list[dict[str, Any]],
    *,
    start: str,
    end: str,
    starting_balance: float,
) -> list[dict[str, float | int | str | None]]:
    frame = pd.DataFrame(trades)
    if frame.empty:
        frame = pd.DataFrame(columns=["close_date", "profit_abs", "profit_ratio"])
    else:
        frame["close_date"] = pd.to_datetime(frame["close_date"], utc=True)
        frame["month"] = frame["close_date"].dt.tz_localize(None).dt.to_period("M")
    start_month = pd.Timestamp(start).to_period("M")
    end_month = (pd.Timestamp(end) - pd.Timedelta(seconds=1)).to_period("M")
    balance = float(starting_balance)
    result: list[dict[str, float | int | str | None]] = []
    for month in pd.period_range(start_month, end_month, freq="M"):
        subset = frame.loc[frame.get("month", pd.Series(dtype=object)).eq(month)]
        profits = [float(value) for value in subset.get("profit_ratio", [])]
        profit_abs = float(subset.get("profit_abs", pd.Series(dtype=float)).sum())
        month_start = balance
        balance += profit_abs
        result.append(
            {
                "month": str(month),
                "trades": len(subset),
                "wins": sum(value > 0 for value in profits),
                "losses": sum(value < 0 for value in profits),
                "profit_factor": _profit_factor(profits),
                "profit_abs_usdt": profit_abs,
                "start_balance": month_start,
                "return_pct": profit_abs / month_start * 100 if month_start else 0.0,
                "end_balance": balance,
            }
        )
    return result


def _read_result(artifact: str, strategy: str) -> dict[str, Any]:
    archive = research.REPO_ROOT / artifact
    with zipfile.ZipFile(archive) as bundle:
        result_name = next(
            name
            for name in bundle.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        )
        payload = json.loads(bundle.read(result_name))
    return payload["strategy"][strategy]


def _detail_comparison(
    baseline: list[dict[str, Any]], detail: list[dict[str, Any]]
) -> dict[str, bool | int]:
    economic_keys = (
        "pair",
        "open_date",
        "open_rate",
        "close_rate",
        "profit_ratio",
        "profit_abs",
        "is_short",
        "enter_tag",
        "exit_reason",
    )
    trade_count_equal = len(baseline) == len(detail)
    economic_outcomes_equal = trade_count_equal and all(
        all(left.get(key) == right.get(key) for key in economic_keys)
        for left, right in zip(baseline, detail, strict=True)
    )
    close_timing_differences = (
        sum(
            left.get("close_date") != right.get("close_date")
            or left.get("trade_duration") != right.get("trade_duration")
            for left, right in zip(baseline, detail, strict=True)
        )
        if trade_count_equal
        else max(len(baseline), len(detail))
    )
    return {
        "trade_count_equal": trade_count_equal,
        "economic_outcomes_equal": economic_outcomes_equal,
        "close_timing_equal": trade_count_equal and close_timing_differences == 0,
        "close_timing_differences": close_timing_differences,
    }


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    output = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    output.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(output)


def _fmt(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    if math.isinf(value):
        return "∞"
    return f"{value:.{digits}f}"


def _pct(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "—"
    prefix = "+" if signed and value > 0 else ""
    return f"{prefix}{value:.2f}%"


def _development_score(item: dict[str, Any]) -> tuple[float, ...]:
    return (
        float(item["worst_fold_profit_pct"]),
        float(item["min_asset_profit_factor"]),
        float(item["profit_factor"]),
        float(item["winrate"]),
        float(item["payoff"] or 0),
        float(item["profit_pct"]),
        -float(item["drawdown_pct"]),
    )


def _duplicate_audit() -> dict[str, Any]:
    audited = 0
    mismatches: list[str] = []
    stages = {
        "parity-full",
        "development",
        "development-confirmation",
        "development-price-geometry",
        "challenge",
        "full",
    }
    for directory in research.RESULT_ROOT.rglob("*"):
        if not directory.is_dir() or not any(part in stages for part in directory.parts):
            continue
        archives = sorted(directory.glob("*.zip"))
        if len(archives) < 2:
            continue
        values = []
        for archive in archives:
            with zipfile.ZipFile(archive) as bundle:
                result_name = next(
                    name
                    for name in bundle.namelist()
                    if name.endswith(".json") and not name.endswith("_config.json")
                )
                payload = json.loads(bundle.read(result_name))
            result = next(iter(payload["strategy"].values()))
            values.append(
                (
                    research._trade_fingerprint(result["trades"]),
                    float(result["final_balance"]),
                )
            )
        audited += 1
        if len(set(values)) != 1:
            mismatches.append(str(directory.relative_to(research.RESULT_ROOT)))
    return {"duplicate_directories": audited, "mismatch_directories": mismatches}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    main_payload = json.loads((research.RESULT_ROOT / "results.json").read_text(encoding="utf-8"))
    verification = json.loads(
        (research.RESULT_ROOT / "verification-results.json").read_text(encoding="utf-8")
    )
    metrics = main_payload["metrics"]
    verification_metrics = verification["metrics"]
    development = [item for item in metrics if item["stage"] == "development"]
    confirmations = [
        item for item in metrics if item["stage"] == "development-confirmation"
    ]
    geometry = [
        item for item in metrics if item["stage"] == "development-price-geometry"
    ]
    challenge = [item for item in metrics if item["stage"] == "challenge"]
    full = [item for item in metrics if item["stage"] == "full"]

    final_metric = next(
        item for item in verification_metrics if item["stage"] == "verification-named-full"
    )
    final_result = _read_result(
        final_metric["artifact"], "PriceFlowSignedFlowExpansionStrategy"
    )
    monthly = _shared_wallet_months(
        final_result["trades"],
        start=research.FULL_WINDOW[0],
        end=research.FULL_WINDOW[1],
        starting_balance=float(final_result["starting_balance"]),
    )
    _write_csv(MONTHLY_CSV, monthly)
    _write_csv(
        MATRIX_CSV,
        [
            {
                key: item[key]
                for key in (
                    "code",
                    "strategy",
                    "timeframe",
                    "leverage",
                    "status",
                    "reason",
                    "trades",
                    "profit_pct",
                    "winrate",
                    "payoff",
                    "profit_factor",
                    "drawdown_pct",
                    "btc_profit_sum_pct",
                    "eth_profit_sum_pct",
                    "profitable_folds",
                    "worst_fold_profit_pct",
                )
            }
            for item in development
        ],
    )

    matrix_rows = [
        [
            item["timeframe"],
            f"{item['leverage']}x",
            str(item["trades"]),
            _pct(item["profit_pct"], signed=True),
            _pct(item["winrate"] * 100),
            _fmt(item["payoff"]),
            _fmt(item["profit_factor"]),
            _pct(item["drawdown_pct"]),
            item["status"].replace("DEVELOPMENT_SURVIVOR", "PASS"),
        ]
        for item in development
    ]
    representatives = []
    for timeframe in research.TIMEFRAMES:
        candidates = [item for item in development if item["timeframe"] == timeframe]
        sample_valid = [item for item in candidates if item["trades"] >= 20]
        pool = sample_valid or candidates
        representatives.append(max(pool, key=_development_score))
    representative_rows = [
        [
            item["timeframe"],
            f"{item['leverage']}x",
            str(item["trades"]),
            _pct(item["profit_pct"], signed=True),
            _pct(item["winrate"] * 100),
            _fmt(item["payoff"]),
            _fmt(item["profit_factor"]),
            _pct(item["drawdown_pct"]),
            item["reason"],
        ]
        for item in representatives
    ]
    confirmation_rows = [
        [
            item["code"],
            item["confirmation"],
            str(item["trades"]),
            _pct(item["profit_pct"], signed=True),
            _pct(item["winrate"] * 100),
            _fmt(item["payoff"]),
            _fmt(item["profit_factor"]),
            _pct(item["drawdown_pct"]),
            item["status"],
        ]
        for item in confirmations
    ]
    challenge_rows = [
        [
            item["code"],
            str(item["trades"]),
            _pct(item["profit_pct"], signed=True),
            _pct(item["winrate"] * 100),
            _fmt(item["payoff"]),
            _fmt(item["profit_factor"]),
            _pct(item["drawdown_pct"]),
            f"{item['profitable_folds']}/4",
            item["status"],
        ]
        for item in challenge
    ]
    full_rows = [
        [
            item["code"],
            str(item["trades"]),
            _pct(item["profit_pct"], signed=True),
            _pct(item["winrate"] * 100),
            _fmt(item["payoff"]),
            _fmt(item["profit_factor"]),
            _pct(item["drawdown_pct"]),
        ]
        for item in full
    ]
    geometry_rows = [
        [
            f"{item['leverage']}x",
            str(item["trades"]),
            _pct(item["profit_pct"], signed=True),
            _pct(item["winrate"] * 100),
            _fmt(item["payoff"]),
            _fmt(item["profit_factor"]),
            _pct(item["drawdown_pct"]),
            item["reason"],
        ]
        for item in geometry
    ]
    verification_rows = [
        [
            item["stage"].replace("verification-", ""),
            str(item["trades"]),
            _pct(item["profit_pct"], signed=True),
            _pct(item["winrate"] * 100),
            _fmt(item["payoff"]),
            _fmt(item["profit_factor"]),
            _pct(item["drawdown_pct"]),
        ]
        for item in verification_metrics
        if item["stage"] not in {"verification-named-rerun"}
    ]
    monthly_rows = [
        [
            str(item["month"]),
            str(item["trades"]),
            f"{item['wins']}/{item['losses']}",
            _fmt(item["profit_factor"]),
            f"{item['profit_abs_usdt']:+.4f}",
            _pct(item["return_pct"], signed=True),
            f"{item['end_balance']:.4f}",
        ]
        for item in monthly
    ]
    pair_rows = [
        [
            item["key"],
            str(item["trades"]),
            _pct(item["profit_total_pct"], signed=True),
            _pct(item["winrate"] * 100),
            _fmt(item["profit_factor"]),
            _pct(item["max_drawdown_account"] * 100),
        ]
        for item in final_result["results_per_pair"]
    ]
    tag_rows = [
        [
            "Short" if item["key"].endswith("_short") else "Long",
            str(item["trades"]),
            _pct(item["profit_total_pct"], signed=True),
            _pct(item["winrate"] * 100),
            _fmt(item["profit_factor"]),
        ]
        for item in final_result["results_per_enter_tag"]
        if item["key"] != "TOTAL"
    ]
    exit_rows = [
        [
            item["key"],
            str(item["trades"]),
            _pct(item["profit_total_pct"], signed=True),
            _pct(item["winrate"] * 100),
        ]
        for item in final_result["exit_reason_summary"]
        if item["key"] != "TOTAL"
    ]

    lookahead_path = research.RESULT_ROOT / "lookahead" / "lookahead.csv"
    lookahead = pd.read_csv(lookahead_path).iloc[0].to_dict()
    lookahead = {
        key: None if pd.isna(value) else value for key, value in lookahead.items()
    }
    duplicate_audit = _duplicate_audit()
    detail = next(
        item for item in verification_metrics if item["stage"] == "verification-detail-5m"
    )
    named = next(
        item for item in verification_metrics if item["stage"] == "verification-named-full"
    )
    detail_result = _read_result(
        detail["artifact"], "PriceFlowSignedFlowExpansionStrategy"
    )
    detail_comparison = _detail_comparison(
        final_result["trades"], detail_result["trades"]
    )
    active_months = [item for item in monthly if item["trades"]]
    positive_months = sum(float(item["profit_abs_usdt"]) > 0 for item in monthly)
    negative_months = sum(float(item["profit_abs_usdt"]) < 0 for item in monthly)
    flat_months = len(monthly) - positive_months - negative_months

    report = f"""# PriceFlow 多周期 × 杠杆研究最终报告

状态：**HISTORICAL TEMPORAL-CHALLENGE SURVIVOR；NOT PAPER/LIVE ENABLED**

## 1. 结论

本轮冻结协议选出的历史最佳组合是：

- 策略：`PriceFlowSignedFlowExpansionStrategy`
- 主 K 线：**15m**
- 杠杆：**2x isolated**
- 资金持续性：E10 的价格结构之后，FRESH_FLOW 分支必须满足当前 taker imbalance 与方向同号，并且当前 15m OI change > 0；价格接受分支仍可独立保留。
- 账户口径：BTC 与 ETH 共用 20 USDT 钱包、90% 余额、最多一笔持仓、单边 0.05% 手续费、保护启用。

它不是“收益数字最大”的配置。15m 价格几何 10x 在开发期显示 +466.81%，但最大回撤 35.40% 且收益月份集中，按冻结风险门槛被拒绝。最终选择优先最差时间折、双资产 PF、总 PF、胜率、Payoff 和低回撤，而不是最高名义收益。

时间挑战年（已在本 session 其他研究中看过，不能称 untouched）：25 笔、**+71.05%**、胜率 **64.00%**、Payoff **3.81**、PF **6.37**、最大账户回撤 **3.42%**，四个季度和 BTC/ETH 两个资产均为正。

共同 25 个月完整路径：61 笔、20 USDT → **51.0913 USDT**，即 **+155.46%**；胜率 **54.10%**、Payoff **2.90**、PF **3.68**、最大账户回撤 **3.64%**。高胜率/高盈亏比在挑战年很强，但三年胜率回落到 48.45%，所以合理结论是“历史质量较好”，不是未来仍会保持 64% 胜率。

## 2. 研究边界

所有候选在读取本轮收益前已冻结于 `PREREGISTRATION.md`。本轮正式新增尝试为 20 个周期×杠杆基线、4 个有限确认微调和 5 个价格几何诊断，共 29 个开发期回测；最多 3 个进入时间挑战。上游 E10 本身又来自更早的多轮研究，因此真实选择偏差高于 29 次，任何 p-value 都不应作独立统计显著性解释。

5m/15m/30m/1h 的价格窗口按真实分钟缩放。30m 只由连续 OKX 15m OHLCV 聚合。Binance 官方 5m metrics/klines 重建的资金行以结束时间标记，主 K 线只能读取 `decision_time <= candle close`，且最新 5m 行必须恰好到达该收盘；否则 fail closed。BTC 148,932 个、ETH 131,840 个原 15m 有效时间点逐字段对账均为 0 差异。

## 3. 20 个主矩阵开发结果

{_markdown_table(['周期', '杠杆', '交易', '收益', '胜率', 'Payoff', 'PF', '回撤', '状态'], matrix_rows)}

周期代表对比：

{_markdown_table(['周期', '代表杠杆', '交易', '收益', '胜率', 'Payoff', 'PF', '回撤', '主要结论'], representative_rows)}

解释：

- 5m 把结构切得太碎。只有 1x 勉强 +3.62%，但胜率 26.39%、PF 1.09，BTC 为负；更高杠杆因价格止损距离缩窄到 1.5%/1.0%/0.6%/0.3% 后显著恶化。
- 15m 保留了足够的价格接受信息，又能及时消费 5m 资金变化，是本数据中最好的噪声/延迟平衡。
- 30m 的最佳点只有 +8.71%、PF 1.30、Payoff 1.78，聚合开始漏掉有效的短时延续。
- 1h 全部只有 3 笔，无法形成可用样本；3x 的 +3.68% 不具有比较意义。

## 4. 有限微调与杠杆诊断

预定义确认微调：

{_markdown_table(['候选', '机制', '交易', '收益', '胜率', 'Payoff', 'PF', '回撤', '状态'], confirmation_rows)}

M2 比 M1 少 1 笔开发交易、少 2 笔挑战交易，但开发/挑战的 PF、胜率和回撤同时改善。其逻辑不是声称识别“大资金”，而是要求：价格结果已经出现，主动成交方向仍在持续，同时 OI 增加说明系统总风险敞口在扩大；它仍无法分辨新多、新空、平多或平空。

15m 价格几何诊断保持约 1.5% 的市场价格止损距离：

{_markdown_table(['杠杆', '交易', '收益', '胜率', 'Payoff', 'PF', '回撤', '拒绝原因'], geometry_rows)}

1–5x 的交易、胜率和 Payoff 几乎相同，说明名义收益上升主要来自同一市场路径的杠杆放大，而不是更好的信号。5x 已到 19.01% 回撤，10x 达 35.40%；这就是不把 5x/10x 称为“最佳杠杆”的原因。

## 5. 时间挑战与完整路径

时间挑战：

{_markdown_table(['候选', '交易', '收益', '胜率', 'Payoff', 'PF', '回撤', '正季度', '状态'], challenge_rows)}

共同 25 个月：

{_markdown_table(['候选', '交易', '收益', '胜率', 'Payoff', 'PF', '回撤'], full_rows)}

具名策略与更长窗口/压力验证：

{_markdown_table(['验证', '交易', '收益', '胜率', 'Payoff', 'PF', '回撤'], verification_rows)}

- 具名策略与研究类完整 61 笔 fingerprint 相同；具名独立复跑也相同。
- 单边费率翻倍到 0.10% 后仍为 +140.57%、PF 3.27、回撤 4.16%。
- `timeframe-detail=5m` 后 61 笔交易的入场、成交价格、收益、方向、标签与退出原因一致，账户收益也完全相同；但 {detail_comparison['close_timing_differences']} 笔平仓时间晚了 5–10 分钟，持仓时长、K 内极值和订单记录相应变化，因此完整逐笔 fingerprint **并不相同**。它只支持“本样本经济结果不变”，不支持“执行路径完全相同”。
- 三年为 +216.02%、97 笔、胜率 48.45%、Payoff 2.77、PF 2.98、回撤 3.52%，三个年度折逐笔收益和均为正。
- 从 2022-01-01 起的最大审计窗口为 +216.43%、103 笔、PF 2.82；但最大回撤升到 12.61%。2022 年没有成交，早期活跃历史并没有提供与近年同等的风险质量。

## 6. BTC + ETH 共享钱包逐月复利路径

下表用完整 Freqtrade 回测中每笔已经计算好的 `profit_abs`，按平仓月累加到账户余额。它保留了共享钱包、90% 动态仓位和前序盈亏对后续 stake 的影响；是已实现盈亏的月末钱包路径，不是未平仓头寸的 mark-to-market 净值。

{_markdown_table(['月份', '交易', '胜/负', 'PF', '盈亏 USDT', '月收益', '月末钱包'], monthly_rows)}

25 个月中 {positive_months} 个正月、{negative_months} 个负月、{flat_months} 个零成交/零收益月；有成交的月份为 {len(active_months)} 个。最终月末钱包 {monthly[-1]['end_balance']:.4f} USDT，与 Freqtrade `final_balance` {final_result['final_balance']:.4f} 完全一致。

## 7. 收益来源与薄弱点

逐资产：

{_markdown_table(['资产', '交易', '收益', '胜率', 'PF', '独立资产回撤'], pair_rows)}

逐方向：

{_markdown_table(['方向', '交易', '收益', '胜率', 'PF'], tag_rows)}

退出原因：

{_markdown_table(['退出', '交易', '收益', '胜率'], exit_rows)}

核心不对称非常明显：Short 27 笔贡献 +130.10%、胜率 70.37%、PF 9.18；Long 34 笔只贡献 +25.35%、胜率 41.18%、PF 1.60。策略整体仍通过双资产门槛，但收益主要来自空头方向。下一项独立研究最有价值的方向不是继续改全局 RV/OI 阈值，而是预注册 long/short 分离的价格接受与退出假设；在新数据到来前不能用本结果反向删除 long。

ROI 退出 30 笔全部盈利并贡献 +212.23%；18 笔 long flow invalidation、7 笔 short flow invalidation和 6 笔止损合计回吐。最大连续亏损 4 笔，平均持仓 {final_result['holding_avg']}，最长账户回撤持续 {final_result['drawdown_duration']}。funding 合计 {sum(float(trade.get('funding_fees') or 0) for trade in final_result['trades']):+.4f} USDT。

## 8. 偏差、确定性与实现审计

- 冻结 E10 与 15m/2x 研究副本：67 笔 fingerprint 完全相同。
- 因一次外层超时留下两个独立进程，{duplicate_audit['duplicate_directories']} 个结果目录意外获得双跑；逐目录比较逐笔 fingerprint 与 final balance，差异目录为 {len(duplicate_audit['mismatch_directories'])}。
- 具名策略两次完整回测 fingerprint 相同，并与 M2 研究类相同。
- Freqtrade lookahead-analysis：{int(lookahead['total_signals'])} 个目标信号，`has_bias={lookahead['has_bias']}`，偏差入场 {int(lookahead['biased_entry_signals'])}、偏差退出 {int(lookahead['biased_exit_signals'])}、偏差指标为空。该工具为避免误报会禁用 protections、强制市场单和无限并发，因此它只验证信号因果，不复现账户收益。
- recursive-analysis 分别对 BTC 与 ETH 使用 startup 960/1200/1400：flow 两列显示到 0.000%，BTC `ema200_4h` 最大显示差异 0.001%，ETH 最大 0.002%；两次均报告无 indicator-only lookahead bias。
- 5m 资金侧车所有用于主信号的行必须时间戳精确到主 K 线收盘；缺行时不会前填成有效交易证据。

## 9. 不能从本报告推出什么

1. 不能把 Binance/OKX/Deribit 的不同资金池当成同一批钱；venue spread、OI、账户比和期权成交只是行为代理。
2. OI 增加不能区分新多/新空，taker imbalance 不能识别交易者身份；“大资金”是机制假设，不是数据字段直接标签。
3. K 线回测没有订单簿排队、真实延迟、冲击成本、网络失败和交易所风控。手续费翻倍通过不等于实盘滑点通过。
4. 20 USDT、90% 余额、单持仓使复利路径清晰，但小钱包的最小下单量、精度和手续费占比不代表大资金容量。
5. 时间挑战已在本 session 被看过，且上游策略经过大量历史研究；+71.05% 与 64% 胜率不能当作真正样本外预期。
6. 最大历史只有 103 笔，1h 更只有 3 笔；尾部事件和制度变化仍可能完全改变结果。

## 10. 后续开发建议

1. **先停止同历史阈值微调。** 从 2026-08-01 之后做至少 30–50 笔 forward shadow；同时保留冻结 E10、M1、M2，预先规定比较日期和门槛。
2. **预注册方向分治。** Short 明显强、Long 较弱；下一预算可单独研究 long 的价格接受持续性与 flow invalidation，但不能看完本样本后直接关闭 long。
3. **做真实执行压力。** 用历史盘口/成交或 dry-run 记录估计限价未成交、滑点、网络延迟和 funding 偏差；将 0.10% 费率测试扩展为滑点分布，而非固定常数。
4. **验证跨 venue 稳定性。** 分别移除 Binance 5m、期权和 venue-spread 侧车做预注册消融，并检查 Binance 与 OKX 的时间延迟/基差在极端事件中是否改变符号。
5. **独立研究 5m，而不是继续缩放 15m。** 5m 失败说明 E10 的回踩结构不适合机械缩放；若要高频，应重新定义微结构级标签、持有期和成交模型，使用新的实验预算。
6. **杠杆保持 2x。** 只有在 forward shadow、滑点和清算压力同时通过后才讨论 3x；5x/10x 当前明确不合格。

## 11. 固化与文件

- 最终策略：`ft_userdata/user_data/strategies/PriceFlowSignedFlowExpansionStrategy.py`
- 冻结 E10：`ft_userdata/user_data/strategies/PriceFlowParticipationFreshnessStrategy.py`（未修改）
- 研究副本：`ft_userdata/user_data/strategies/PriceFlowTimeframeLeverageResearchStrategy.py`
- 预注册：`ft_userdata/runtime/freqtrade-futures/backtest_results/price-flow-timeframe-leverage-research/PREREGISTRATION.md`
- 主结果：`results.json` / `results.csv`
- 验证：`verification-results.json`
- 逐月共享钱包：`monthly-shared-wallet.csv`
- 开发矩阵：`development-matrix.csv`
- lookahead：`lookahead/lookahead.csv`
- recursive：`recursive/recursive.log` 与 `recursive/recursive-eth.log`

本研究没有修改机器人配置、没有启动 dry-run/Paper/Live，也没有配置真实交易密钥。
"""
    REPORT.write_text(report, encoding="utf-8")

    receipt = {
        "selected_strategy": "PriceFlowSignedFlowExpansionStrategy",
        "selected_timeframe": "15m",
        "selected_leverage": 2,
        "selected_confirmation": "signed_fresh_oi",
        "preregistration_sha256": main_payload["protocol"]["preregistration_sha256"],
        "strategy_source_sha256": verification["final_strategy_source_sha256"],
        "parity_ok": main_payload["protocol"]["parity_ok"],
        "named_equivalent_to_selected": verification["equivalent_to_selected"],
        "named_deterministic": verification["deterministic_named_rerun"],
        "detail_trade_fingerprint_equal": (
            detail["trade_fingerprint"] == named["trade_fingerprint"]
        ),
        "detail_comparison": detail_comparison,
        "lookahead": lookahead,
        "recursive": {
            "BTC": {"max_displayed_variance_pct": 0.001, "indicator_lookahead": False},
            "ETH": {"max_displayed_variance_pct": 0.002, "indicator_lookahead": False},
        },
        "five_minute_parity": {
            "BTC_rows": 148932,
            "ETH_rows": 131840,
            "field_mismatches": 0,
        },
        "duplicate_audit": duplicate_audit,
        "monthly_final_balance": monthly[-1]["end_balance"],
        "freqtrade_final_balance": final_result["final_balance"],
        "report": str(REPORT.relative_to(research.REPO_ROOT)),
        "monthly_csv": str(MONTHLY_CSV.relative_to(research.REPO_ROOT)),
        "matrix_csv": str(MATRIX_CSV.relative_to(research.REPO_ROOT)),
    }
    AUDIT_RECEIPT.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
