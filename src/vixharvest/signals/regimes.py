"""HARVEST / NEUTRAL / STRESS / POST-SPIKE regime state machine (plan.md Sprint 3).

Thresholds (theta_1, theta_2, momentum lookback) come from config/signals.yaml
and must be fit in-sample only (plan.md Sprint 3.2).
"""


def classify_regime(panel_row) -> str:
    """Return one of HARVEST/NEUTRAL/STRESS/POST_SPIKE for a given panel row. Sprint 3."""
    raise NotImplementedError("Sprint 3: implement regime state machine.")
