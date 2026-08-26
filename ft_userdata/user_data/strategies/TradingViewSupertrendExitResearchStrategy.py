from TradingViewSupertrendStrategy import TradingViewSupertrendStrategy


class TradingViewSupertrendExitResearchBase(TradingViewSupertrendStrategy):
    activation_min_profit = 0.002
    activation_atr_multiplier = 0.5
    bounce_max_candles = 4
    trail_bars = 3
    swing_lookback = 12
    partial_exit_fraction = 0.5
    invalidation_atr_multiplier = 0.25
    regime_structure_lookback = 3
    require_regime_filter = True
    require_regime_structure = True
    price_action_exit_enabled = True


class TradingViewSupertrendExitControl(TradingViewSupertrendExitResearchBase):
    require_regime_filter = False
    require_regime_structure = False
    price_action_exit_enabled = False
    partial_exit_fraction = 0.0
    stoploss = -0.99


class TradingViewSupertrendExitR01(TradingViewSupertrendExitResearchBase):
    pass


class TradingViewSupertrendExitR02(TradingViewSupertrendExitResearchBase):
    activation_min_profit = 0.0015


class TradingViewSupertrendExitR03(TradingViewSupertrendExitResearchBase):
    activation_min_profit = 0.0025


class TradingViewSupertrendExitR04(TradingViewSupertrendExitResearchBase):
    activation_min_profit = 0.003


class TradingViewSupertrendExitR05(TradingViewSupertrendExitResearchBase):
    activation_atr_multiplier = 0.35


class TradingViewSupertrendExitR06(TradingViewSupertrendExitResearchBase):
    activation_atr_multiplier = 0.65


class TradingViewSupertrendExitR07(TradingViewSupertrendExitResearchBase):
    trail_bars = 2


class TradingViewSupertrendExitR08(TradingViewSupertrendExitResearchBase):
    trail_bars = 4


class TradingViewSupertrendExitR09(TradingViewSupertrendExitResearchBase):
    trail_bars = 5


class TradingViewSupertrendExitR10(TradingViewSupertrendExitResearchBase):
    bounce_max_candles = 3


class TradingViewSupertrendExitR11(TradingViewSupertrendExitResearchBase):
    bounce_max_candles = 6


class TradingViewSupertrendExitR12(TradingViewSupertrendExitResearchBase):
    partial_exit_fraction = 0.33


class TradingViewSupertrendExitR13(TradingViewSupertrendExitResearchBase):
    partial_exit_fraction = 0.67


class TradingViewSupertrendExitR14(TradingViewSupertrendExitResearchBase):
    swing_lookback = 8


class TradingViewSupertrendExitR15(TradingViewSupertrendExitResearchBase):
    swing_lookback = 20


class TradingViewSupertrendExitR16(TradingViewSupertrendExitResearchBase):
    invalidation_atr_multiplier = 0.0


class TradingViewSupertrendExitR17(TradingViewSupertrendExitResearchBase):
    invalidation_atr_multiplier = 0.5


class TradingViewSupertrendExitR18(TradingViewSupertrendExitResearchBase):
    require_regime_structure = False


class TradingViewSupertrendExitR19(TradingViewSupertrendExitResearchBase):
    regime_structure_lookback = 2


class TradingViewSupertrendExitR20(TradingViewSupertrendExitResearchBase):
    partial_exit_fraction = 0.0
