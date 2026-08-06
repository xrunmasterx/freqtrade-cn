from LSRICoreStrategy import LSRICoreStrategy


class LSRIAdaptiveStrategy(LSRICoreStrategy):
    """
    LSRI Adaptive Trend Strategy.

    Pair-agnostic profile selected after the bounded five-round SOXL exploratory backtest.
    The inherited LSRI core continues to own indicators, entries, stake sizing, and exits.
    """

    adaptive_profile_enabled = True
    adaptive_max_stop_distance = 0.045
    adaptive_leverage = 3.0
    adaptive_pullback_tolerance = 0.006
    adaptive_entry_min_risk_pct = 0.004
    adaptive_entry_max_risk_pct = 0.045
    adaptive_entry_volume_z_min = 0.5
    adaptive_entry_volume_z_max = 4.0
    adaptive_long_adx_hard_threshold = 18.0
    adaptive_short_adx_hard_threshold = 20.0
    adaptive_di_direction_ratio = 1.05
    adaptive_long_rsi_min = 48.0
    adaptive_long_rsi_max = 75.0
    adaptive_short_rsi_min = 25.0
    adaptive_short_rsi_max = 52.0
    adaptive_dist_ema20_limit = 0.035
    adaptive_dist_vwap_limit = 0.06
    adaptive_crowded_ret24_limit = 0.20
    adaptive_dist_ema200_4h_limit = 0.50
    adaptive_trend_min_ema_spread = 0.002
    adaptive_trend_min_atrp = 0.003
    adaptive_chop_max_adx = 14.0
    adaptive_chop_max_atrp = 0.0025
    adaptive_take_profit_r = 2.0
