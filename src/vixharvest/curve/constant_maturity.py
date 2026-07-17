"""Constant-maturity VX30 interpolation (plan.md Sprint 2.2).

For each date, identify M1/M2 (nearest and next expiries with expiry > date),
compute calendar-day weights, and produce vx30. Handles roll dates and
holiday-shifted expiries.
"""


def compute_vx30() -> None:
    """Interpolate the 30-day constant-maturity VIX future series. Sprint 2."""
    raise NotImplementedError("Sprint 2: implement VX30 interpolation.")
