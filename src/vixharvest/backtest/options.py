"""Options spread modeling: debit spread construction and pricing (thesis.md section 5.1).

Sprint 4-5 (plan.md), conditional on the Sprint 3 GO/NO-GO gate passing. Do not
implement spread-pricing logic before results/sprint3_gate.md says GO.
"""


def construct_spread(*args, **kwargs) -> None:
    """Select the debit spread (delta-targeted long leg, decay-targeted short leg,
    30-60 DTE) for a given date + panel row. Sprint 4, conditional on Sprint 3 GO.
    """
    raise NotImplementedError("Sprint 4: implement spread constructor (gated on Sprint 3 GO).")
