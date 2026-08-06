from PriceFlowEventAdaptiveResearchStrategy import PriceFlowEventAdaptive10Strategy


class PriceFlowParticipationFreshnessStrategy(PriceFlowEventAdaptive10Strategy):
    """Frozen E10 candidate selected by the preregistered 20-round study.

    C04 entries require at least 0.8 relative volume and either directional
    price acceptance or non-weakening same-direction five-minute taker flow.
    """
