from PriceFlowCapitalIntentResearchStrategy import PriceFlowCapitalIntentResearchBase


class PriceFlowPositionAccountContinuationStrategy(PriceFlowCapitalIntentResearchBase):
    """Frozen C04 continuation candidate selected by the 20-round study.

    CUSUM continuation entries require rising open interest and a same-direction
    increase in top-trader position ratio relative to top-trader account ratio.
    The aggregate public ratios do not identify traders or opening intent.
    """

    research_id = 4
