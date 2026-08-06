from PriceFlowCrossVenueResearchStrategy import PriceFlowCrossVenueResearchBase


class PriceFlowShortDteOptionPressureStrategy(PriceFlowCrossVenueResearchBase):
    """Frozen selectable promotion of research candidate D15.

    The strategy preserves the exact 1-7 DTE option-urgency confirmation semantics.
    It requires a causal, current cross-venue sidecar; the historical result failed
    sample-coverage and drawdown Gates, so this class is not Live-approved.
    """

    candidate_id = 15
