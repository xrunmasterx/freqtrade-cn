from PriceFlowTimeframeLeverageResearchStrategy import (
    PriceFlowE10Tf15mLev2SignedFreshOiStrategy,
)


class PriceFlowSignedFlowExpansionStrategy(
    PriceFlowE10Tf15mLev2SignedFreshOiStrategy
):
    """Frozen 15m/2x E10-M2 survivor from the timeframe/leverage study.

    Public taker imbalance and open-interest changes are behavioral proxies;
    they do not identify an actor or distinguish opening from closing flow.
    """
