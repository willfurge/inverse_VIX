"""Event-driven backtest engine: signal on date t settles, position changes at t+1.

Execution lag is enforced here, not by convention (plan.md Sprint 3.1).
"""


def run_backtest(*args, **kwargs) -> None:
    """Run the event-driven backtest loop over a signal panel. Sprint 3."""
    raise NotImplementedError("Sprint 3: implement backtest engine.")
