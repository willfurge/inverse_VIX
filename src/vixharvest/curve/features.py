"""Full daily feature panel (thesis.md §4.1, plan.md Sprint 2.3).

Writes data/processed/signal_panel.parquet with columns: date, vix, vix3m,
vix9d, m1, m2, expiries, vx30, basis_m1, basis_m1_pct, slope_m1m2,
roll_yield_daily, ratio_vix_vix3m, vix9d_vix, plus 5-day deltas of the ratios.
"""


def build_signal_panel() -> None:
    """Assemble the analysis-ready signal panel. Sprint 2."""
    raise NotImplementedError("Sprint 2: implement feature panel construction.")
