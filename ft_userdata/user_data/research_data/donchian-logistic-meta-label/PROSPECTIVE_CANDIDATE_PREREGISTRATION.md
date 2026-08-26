# Donchian Logistic Prospective Freqtrade Candidate Preregistration

Status: candidate rules frozen before the prospective boundary and before any candidate
backtest, paper trade, live trade, performance read, or release decision. This is a research
candidate, not an accepted, paper, or live strategy. A future run is valid only after the finished
V8 recorder, projection builder, strategy, config, and non-self-referential freeze manifest are
all byte-frozen and pass their structural checks.

## Frozen identity and execution settings

- Prospective boundary: `2026-08-14T00:00:00Z`, exclusive.
- Exchange and instrument: OKX `BTC/USDT:USDT` USDT perpetual only.
- Strategy timeframe: `5m`. No `timeframe_detail` is enabled. Freqtrade forbids a detail
  timeframe equal to the strategy timeframe, and no prospective `1m` authority is frozen.
- Authorized strategy run mode: `BACKTEST` only. `LIVE`, `DRY_RUN`, `HYPEROPT`, `WEBSERVER`,
  plotting, and every other mode fail at `bot_start`. The example config's `dry_run=true` is a
  normal Freqtrade backtest configuration field; it does not authorize a dry-run bot.
- Direction: long and short.
- Margin: isolated, exactly `14x`; no silent lower-leverage execution is valid.
- Starting wallet: `1000 USDT`.
- Stake: `unlimited`, `tradable_balance_ratio=1.0`, no `available_capital`, one open trade,
  no position stacking, no position adjustment, and continuous full-wallet compounding.
- Baseline cost proxy: `0.0006` per side, composed of a `0.0005` OKX taker-fee proxy plus a
  `0.0001` cash-slippage proxy. Freqtrade applies the combined value through its fee input, so it
  is a conservative accounting proxy rather than a claim that the exchange fee alone is six basis
  points. Cost stress is `0.0010` per side and severe stress is `0.0015` per side.
- Funding fallback is forbidden. Missing exact funding or mark evidence is not zero funding.
- Auditable config:
  `ft_userdata/user_data/config.donchian-logistic-prospective.example.json`, SHA-256
  `5715884d243809f8ce897b3bbe47b329f0ca84fb2d3591ce509afd0562a15ccd`.
- Execution strategy:
  `ft_userdata/user_data/strategies/DonchianLogisticProspectiveStrategy.py`, current
  preregistration-draft SHA-256
  `d64664b18af02b5fc7e7149ba66c25963059ccc17c1a7ee3473e80081e9a10cc`.

The final freeze manifest must bind the finished strategy, example config, this document, builder,
V7 preregistration and recorder, V8 preregistration and recorder, prospective leverage-tier
snapshot, evaluation preregistration, evaluator source, main backtest/continuous-ledger
materializer, materialization-receipt schema, and the pinned Freqtrade engine, container, and
source-file hashes. It must not contain its own byte hash. Every build and evaluation invocation
instead receives the externally frozen expected manifest SHA-256 and fails closed unless the
manifest bytes match it. An actual run must explicitly load this example config or a byte-identical
controlled copy. Only run mode, immutable data root, timerange, output path, and the frozen fee
scenario may be added by the evaluator; no unrelated local config may be merged.

## Entry publication projection

The builder must invoke the complete frozen V7 journal replay validator before it considers an
event. That validator necessarily reads and recomputes existing `label_matured` records only to
prove that the raw V7 journal is complete and undamaged. After full replay, it must return a
separate, label-free collection of validated `event_prediction` records. The selection function
accepts only that event collection and V8 publication evidence; its API accepts no labels. It may
select only `predicted_positive=true` and must never use any label value to suppress, rank, or
change an entry.

V8 publication is a two-durable-write protocol. A replay-valid phase-1 `event_projection` is not
eligible by itself. Entry eligibility requires its unique, replay-valid phase-2
`publication_receipt`, exact projection linkage, and
`projection_durable_at < execution_time`. Missing or late receipts are permanently ineligible:
the builder emits no signal and never catches up or backfills an order.

The builder emits at most one row for each V7 decision `D`. Two different events for the same
decision and direction are damage and fail closed. If eligible long and short events share the same
decision, long wins deterministically. The sidecar row date is exactly `D`, while its independently
validated execution time is `E=D+5m`. The strategy performs no extra shift: Freqtrade shifts the
backtest signal to the next row and enters at the `E` row open. Only publication evidence durably
available before `E` can reach the sidecar.

The finished sidecar schema is exact, UTC, finite where applicable, strictly ordered by unique
decision, and binds the V7 event semantic hash, V8 projection semantic hash, and V8 publication
receipt semantic hash. Missing, duplicate, reordered, late, non-UTC, mismatched, or additional
fields fail closed.

A schema-shaped sidecar is not authority. The final builder must atomically emit a canonical
materialization receipt binding at least the sidecar byte SHA-256, final freeze-manifest SHA-256,
builder SHA-256, exact V7 journal prefix byte length and SHA-256, exact V8 publication/accounting
journal prefix byte lengths and SHA-256 values, prospective tier-snapshot SHA-256, and every
materialized Freqtrade input path and byte SHA-256. The strategy config must require absolute paths
to that receipt and the final manifest plus independently supplied expected SHA-256 values for
both. At `bot_start`, the finished adapter must verify the bytes, hashes, linkages, and sidecar
identity before reading a signal. A hand-written or copied sidecar without the exact receipt chain
must fail. This receipt schema and validation path are not yet frozen, so the builder remains
`NOT_READY` and the current draft adapter cannot produce acceptance evidence.

## Position and exit semantics

- The market entry is requested at `E` with exactly `14x`. `leverage()` returns `14`; because
  Freqtrade may clip that value, `custom_stake_amount()` rejects the order with zero stake unless
  the leverage delivered to it is still exactly `14` and the full proposed stake was not capped.
  Returning zero is only an order-safety stop; it is not evidence of a valid no-trade. The final
  materializer/evaluator must replay every eligible event at `E`: an already-open position may
  legitimately suppress a new entry, but when flat there must be a full-wallet trade at exactly
  `14x`, bound back to the complete event hash in its entry tag and engine receipt. A flat eligible
  event with no trade, a tier clip, a stake cap, or a tag mismatch makes the run `INVALID`.
- Target: underlying price `+4%` for long or `-4%` for short. `use_custom_roi=True`,
  `minimal_roi={}`, and custom ROI returns
  `trade.calc_profit_ratio(open_rate*1.04)` for long or
  `trade.calc_profit_ratio(open_rate*0.96)` for short. This leaves standard Freqtrade fees,
  funding, leverage, and PnL accounting in force while targeting the frozen underlying price.
- Stop: `stoploss=-0.21`; only at exactly `14x` does this represent a `1.5%` adverse underlying
  move. Trailing stop, custom stop, and stoploss-on-exchange are disabled.
- Normal exit columns are always zero. `use_exit_signal=True` exists only so Freqtrade calls
  `custom_exit`; it does not enable candle exit signals.
- Deadline: at `open_date_utc + 48h`, `custom_exit` returns on the deadline row and standard
  Freqtrade backtesting exits at that row open before evaluating its range. Before the deadline,
  standard Freqtrade evaluates stop before ROI, so stop wins a same-5m-candle stop/target tie.

V7 labels and Freqtrade are not perfectly equivalent. V7 uses inclusive target comparison while
Freqtrade ROI uses strict `>`; exchange price precision and tick size can change equality. Their
gap-stop handling can differ when a candle opens beyond the stop and later crosses back through it.
Five-minute OHLC cannot prove intrabar tick order. Market entries/exits can have latency, slippage,
and gaps, and real liquidation cannot be overridden by Python callback ordering. V7 labels are
research evidence; the standard pinned Freqtrade engine is authoritative for candidate entries,
exits, fills, fees, funding, liquidation, and PnL.

## Prospective data authority

A future materializer must reproduce these sources exactly; it may not substitute a current
download, a later historical download, an exchange-restated archive, interpolation, nearest-time
join, synthetic cadence, index/trade-price proxy, or funding fallback to sign a prospective pass.

- Trade OHLCV: only the complete replay-validated V7 `5m` candle records, preserving their exact
  event timestamps, values, order, and observation evidence. The materializer independently proves
  the raw canonical V7 path is unique and continuously spaced, that every selected `D` and
  `E=D+5m` is physically present, and binds the emitted futures Feather byte hash in its receipt.
  Freqtrade gap-filled or otherwise synthetic main candles are forbidden even if their output dates
  appear continuous; the strategy's own UTC/continuity/D/E checks are only a second validation
  layer.
- Entry sidecar: only eligible V8 publication receipts under the two-write rule above.
- Funding and mark open: only the complete replay-validated V8 accounting journal, preserving the
  exact raw settlement timestamp, minute-floored accounting timestamp, exact timestamp join,
  joined mark open, and semantic hashes.
  Before materialization, the builder must also cross-check every replay-valid V7
  `funding_observation` against the V8 raw `funding_settlement` set from effective `R` through the
  sealed common prefix. Market timestamp and rate must match exactly in both directions; V7/V8
  observation-time metadata may differ. Missing or saturated V8 evidence is `NOT_READY`; any V7
  extra, V7 omission, or value mismatch is `INVALID`. This protects model features from a silent
  omission in V7's unified-CCXT funding history.
- Leverage tiers: a separately captured prospective OKX tier snapshot is mandatory. The final
  materializer manifest binds its source, exact bytes and SHA-256, retrieval/first-seen time, and
  the complete BTC 99-tier structure, and revalidates those bytes before and after execution. A
  current historical cache may not be substituted, and Freqtrade may not refresh tiers over the
  network during execution.
- Accounting: the pinned standard Freqtrade engine consumes the exact materialized sources and is
  the sole exit/fee/funding/PnL authority.

If any required source, prefix, receipt, settlement, joined mark, materialization identity, or hash
is unavailable, the run is `NOT_READY`; a mismatch, revision, forbidden substitution, eligible
signal blocked by a leverage tier, actual trade with leverage other than `14`, or partial accounting
is `INVALID`. Neither state may be presented as zero exposure, zero funding, a failed strategy, or
a prospective pass.

Until that prospective tier snapshot is sealed, materialization and execution are `NOT_READY`.
Once sealed, a missing/revised snapshot, an execution-time tier refresh, or a full-wallet stake
whose applicable tier permits less than `14x` is `INVALID`; Freqtrade's silent leverage clipping is
never an accepted substitute.

## Frozen continuous evaluation and gates

Each cost scenario is one continuous Freqtrade wallet beginning at the exclusive prospective
boundary with `1000 USDT`. It is never restarted, segmented, or independently compounded for a
reporting window. The required elapsed checkpoints are `7d`, `30d`, `90d`, `180d`, `365d`, and
release-to-date; after the first complete calendar month, every complete UTC calendar month and
every daily rolling `30d` checkpoint at `00:00 UTC` is also reported from the same account ledger.
After `D365`, release gates recur every `30d` at `00:00 UTC`, starting exactly 30 days after D365;
there is no favorable-date selection. These are observations, not independent backtests.

No checkpoint force-closes a position. Checkpoint equity is cash plus the open position marked at
the close of the last complete, replay-valid V7 5m candle whose close boundary is no later than the
checkpoint. The mark uses the pinned standard Freqtrade trade calculation, including the frozen
cost scenario's hypothetical closing cost and all exact V8 funding settlements accrued by that
time. The open position, entry basis, funding state, and wallet then continue unchanged. If this
exact mark or any intervening source is unavailable, the checkpoint is `NOT_READY`, never zero.
An ordinary standalone Freqtrade backtest terminal `force_exit` may be reported separately but
cannot be inserted into, or used to restart, this continuous ledger. Until a bound materializer can
carry the natural open position and wallet across all checkpoints without that terminal exit, the
continuous evaluation remains `NOT_READY`.

Metrics use standard Freqtrade accounting for every closed trade plus the frozen checkpoint-equity
policy:

- net return: `checkpoint_equity / 1000 - 1`;
- win rate: closed trades with `profit_abs > 0` divided by all closed trades; draws remain in the
  denominator and are not wins;
- strict payoff: mean positive closed-trade `profit_ratio` divided by the absolute mean negative
  closed-trade `profit_ratio`;
- profit factor: gross positive closed-trade `profit_abs` divided by absolute gross negative
  closed-trade `profit_abs`;
- account maximum drawdown: maximum peak-to-subsequent-trough decline of the continuous marked
  equity path, including open positions at each authoritative 5m mark;
- long/short trade count, win rate, payoff, profit factor, and net contribution; and
- best-trade concentration: largest positive closed-trade `profit_abs` divided by gross positive
  closed-trade `profit_abs`.

No closed trades makes win rate, payoff, and profit factor `N/A`. No win or no loss makes strict
payoff `N/A`; no gross loss with positive gross profit makes profit factor `+infinity`; no positive
gross profit makes best-trade concentration `N/A`. Any `N/A` metric required by a gate makes the
checkpoint `INSUFFICIENT`, not `PASS` or `FAIL`. An incomplete time checkpoint or unsealed but
otherwise valid authoritative evidence is `NOT_READY`. `INVALID` remains reserved for violated
lineage, schema, timing, leverage, materialization, accounting, or receipt contracts.

The complete `30d` checkpoint `2026-09-13T00:00:00Z` is a stage gate, not a final prospective
pass. A `30D_STAGE_PASS` requires every structural, lineage, publication, leverage,
materialization, funding, and engine-receipt gate and all of the following:

- baseline `0.0006` per side: net return `>=100%`, win rate `>=40%`, strict payoff `>2.0`, profit
  factor `>1.2`, maximum drawdown `<25%`, zero liquidations, at least `30` strategy-closed trades,
  at least `5` closed longs, at least `5` closed shorts, at least one win and one loss, and
  best-trade gross-profit concentration `<25%`;
- stress `0.0010` per side: net return `>0`, profit factor `>1.0`, and maximum drawdown `<30%`.
  Liquidations must also equal zero.

The severe `0.0015` scenario is a mandatory diagnostic and has no performance pass threshold. It
cannot repair a baseline or stress failure. The `7d` checkpoint is diagnostic and may be
`INSUFFICIENT`. At each of the complete `90d`, `180d`, and `365d` checkpoints, and at every sealed
release-to-date evaluation thereafter, the candidate must independently satisfy:

- baseline `0.0006`: net return `>0`, win rate `>=40%`, strict payoff `>2.0`, profit factor `>1.2`,
  maximum drawdown `<25%`, best-trade gross-profit concentration `<25%`, and zero liquidations;
- stress `0.0010`: net return `>0`, profit factor `>1.0`, maximum drawdown `<30%`, and zero
  liquidations.

An `N/A` required metric is `INSUFFICIENT`; a numeric gate miss is `FAIL`. A failure or
insufficiency at any matured `30d`, `90d`, `180d`, `365d`, or release-to-date gate means the final
prospective objective has not passed. Complete calendar-month and rolling-30d reports remain
mandatory robustness evidence. No metric or gate may be evaluated before its complete checkpoint
and required accounting evidence are sealed.

Before `30D_STAGE_PASS`, no one-off historical replay, contemporary download, parameter search,
retrospective label read, or backfilled performance check may be used to validate, revise, replace,
or pre-approve this candidate. Only after that stage passes may one immutable historical review run
exactly once, with the already frozen parameters and source/evaluator contract. It must report two
separate panels: (a) a fixed-model replay beginning `2023-01-01`, after the model's `2022` training
period, which is retrospective out-of-sample evidence because the frozen model is only being run
later; and (b) a BTC issuance-to-boundary diagnostic beginning `2019-12`, whose `2019-12` through
`2021-12` pre-training segment is explicitly non-causal and must never be described as a strategy
that was deployable at that time. Neither panel is a prospective result, may rescue a prospective
gate failure, or may authorize any parameter change. A future final prospective pass is research
evidence only; it does not authorize paper trading, live trading, capital allocation, or
StrategyRelease.

Before a release decision, the evaluator must also save successful lookahead-analysis and
recursive-analysis receipts. Each receipt binds exact argv, exit code, UTC start/end, Freqtrade and
container identity, strategy/config/sidecar/data/manifest hashes, and stdout/stderr hashes. A
warning, missing receipt, mutable input, or unbound override makes the candidate `INVALID`.

No prospective candidate backtest, analysis command, network access, paper trade, live trade, or
performance inspection was authorized or performed by this preregistration.
