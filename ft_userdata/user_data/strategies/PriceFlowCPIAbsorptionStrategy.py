from PriceFlowCrossVenueResearchStrategy import PriceFlowCrossVenueResearchBase


class PriceFlowCPIAbsorptionStrategy(PriceFlowCrossVenueResearchBase):
    """Frozen selectable promotion of research candidate P33.

    The strategy preserves the exact post-CPI price-absorption entry semantics.  It
    requires a causal, current cross-venue sidecar; only five historical event entries
    were observed, so this class is a development strategy and is not Live-approved.
    """

    candidate_id = 33
