"""End-of-day signal run and notification (plan.md Sprint 6).

Failure-loud by design: if data refresh fails, the alert must say so; a silent
no-alert must be distinguishable from "no signal."
"""


def run_daily_alert() -> None:
    """Refresh data, compute the panel row, evaluate regime, and notify if actionable. Sprint 6."""
    raise NotImplementedError("Sprint 6: implement daily alert pipeline.")
