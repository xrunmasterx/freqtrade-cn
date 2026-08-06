from PriceFlowCrossVenueResearchStrategy import PriceFlowCrossVenueResearchBase


class PriceFlowTakerCUSUMStrategy(PriceFlowCrossVenueResearchBase):
    """Frozen selectable promotion of research candidate A40.

    The strategy preserves the exact A40 signal and risk semantics.  It requires a
    causal, current cross-venue sidecar; the historical result was research-promising
    but failed sample-coverage and drawdown Gates, so this class is not Live-approved.
    """

    candidate_id = 40
