# Donchian Logistic Meta-Label Train-Only Preregistration

Status: frozen before implementation and before any model fit or performance evaluation on
2026-08-13. This is exploratory training for prospective data strictly after 2026-08-13. It
cannot prove current profitability and authorizes no retrospective or current performance
claim, portfolio simulation, strategy-return calculation, Paper, or Live use.

## Authority and prohibited observations

Only the frozen pre-2024 F3 physical snapshot and its byte identities may be read. The fixed
event universe is every original prior-20 first Donchian breakout event; F3-pass filtering
and portfolio busy suppression do not alter that universe. Training eligibility is
`decision_time >= 2022-03-01T00:00:00Z` and
`decision_time + 48h < 2023-01-01T00:00:00Z`.

No 2023-or-later label, feature, prediction, model evaluation, portfolio result, strategy
return, accuracy, profit, or other performance statistic may be materialized or inspected.
There is no cross-validation, search, calibration, holdout evaluation, refit, or prediction
stage. The only permitted execution output is a fitted 2022 train-only model artifact plus
training row count, class counts, and convergence state.

## Events, decisions, and labels

On official closed 15m candles, define
`U_t = max(high[t-19:t]).shift(1)` and `L_t = min(low[t-19:t]).shift(1)`. A long event is the
first close above `U_t` after a non-long-breakout close; a short event is symmetric below
`L_t`. Long precedes short if both occur at the same timestamp. The signal candle is `t`,
`decision_time = date_t + 15m`, and direction `d` is `+1` long or `-1` short. Entry is the
official 5m open exactly at `decision_time`.

The exogenous binary label is independent of portfolio state. Long target/stop are entry
times `1.04`/`0.985`; short target/stop are entry times `0.96`/`1.015`. Exactly 577 official
5m rows from decision through decision plus 48 hours inclusive must exist. Before the
deadline, each row is evaluated in this fixed order: gap stop at actual open, gap target,
intrabar stop, intrabar target. Stop wins a same-bar tie. At the deadline row, the label is
zero at its open without inspecting its range. The label is one only when target gap or
intrabar target occurs first; all other outcomes are zero.

## Fixed causal features

All prices and volume are official 15m values known at decision time. `B_t` is `U_t` for a
long and `L_t` for a short. Funding `f_tau` is the last actual funding event timestamped at
or before decision time with age in `[0, 10h]`; the physical value is the funding file's
`open` column. Feature order is fixed:

1. `funding_tailwind = -d * f_tau`.
2. `rv24 = sqrt(sum(r_i^2, i=t-95..t))`, where `r_i = ln(C_i / C_i-1)`.
3. `breakout_atr = d * (C_t - B_t) / ATR14_t`.
4. `clv_side = d * clip((2*C_t - H_t - L_t) / (H_t - L_t), -1, 1)`.
5. `body_atr_side = d * (C_t - O_t) / ATR14_t`.
6. `log_relative_volume = ln(V_t / mean(V_t-96..V_t-1))`; current volume is excluded
   from the baseline.
7. `return_1_side = d * ln(C_t / C_t-1)`.
8. `momentum_16_side = d * ln(C_t / C_t-16)`.
9. `donchian_width = (U_t - L_t) / C_t`.
10. `ema96_distance_side = d * ln(C_t / EMA96_t)`.

True range is `H_0-L_0` initially and then
`max(H-L, abs(H-prevC), abs(L-prevC))`. Wilder ATR14 starts at the 14th true range as the
arithmetic mean of the first 14 values, then recurs as `(13*prior_ATR + TR)/14`. EMA96 is
SMA-seeded: the 96th value is the mean of the first 96 closes, then
`EMA = (2/97)*C + (95/97)*prior_EMA`. Both include the current signal candle.

OHLCV dates/schema/nonfinite values and nonpositive prices invalidate the stage. An event
with missing lookback, stale/missing funding, `H=L`, `ATR<=0`, `V_t<=0`, nonpositive prior
96-volume mean, `EMA<=0`, or any nonfinite derived feature is excluded complete-case with a
reason count. No zero, epsilon, forward fill, or backfill substitution is allowed.

## Fixed training procedure

Before inspecting any sample count, the minimum eligible training size is fixed at 100,
with at least 20 examples in each class. This is a modest identifiability floor of ten
observations per one of the ten prespecified features, supplemented by a per-class floor so
balanced weighting is not driven by a handful of outcomes. Falling below either floor or
having one class invalidates the stage.

Each feature is independently winsorized to the training empirical linear-interpolation
quantiles `q01` and `q99`, learned only from eligible 2022 training rows. The clipped
training values are standardized with training population mean and standard deviation
(`ddof=0`); a zero scale is stored as `1`. Fit exactly scikit-learn
`LogisticRegression(C=1, penalty="l2", class_weight="balanced", solver="lbfgs",
fit_intercept=True, tol=1e-4, max_iter=1000)` with threshold `0.5`. No random seed is
needed by this deterministic solver configuration.

## Fail-closed artifact

Before reading data, execution must verify the frozen F3 authority, admitted source paths,
source/data SHA-256 values, manifest schema and pre-2024 physical bounds, this
preregistration hash, and runner identity. Schema/time violations, any label crossing the
training cutoff, nonfinite system data, insufficient samples/classes, failed convergence,
or an existing destination invalidates the stage.

The sole output is strict canonical UTF-8 JSON with sorted keys, compact separators, a
trailing newline, and no NaN or Infinity. It stores feature order and formulas, winsor
bounds, scaler state, coefficient/intercept/classes/iteration count, fixed model settings,
software versions, source and data hashes, eligibility/exclusion counts, and a semantic
SHA-256 over the canonical artifact with its semantic-hash field omitted. Pickle or another
executable serialization is forbidden. Loading verifies the schema and semantic hash
before exposing pure-numpy probability calculation.
