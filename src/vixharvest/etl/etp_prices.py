"""Download VXX/UVXY split-adjusted daily prices and run the split-sanity check.

Sprint 1.2 step 3 (plan.md). Day-over-day returns must never exceed ~60% outside
documented stress windows; anomalies (VXX->VXXB->VXX 2019, 2022 creation halt) are
logged in data/ANOMALIES.md, not silently patched.
"""


def fetch_etp_prices(ticker: str) -> None:
    """Download adjusted daily prices for one ETP ticker (VXX, UVXY). Sprint 1."""
    raise NotImplementedError("Sprint 1: implement ETP price download.")


def check_split_sanity(ticker: str) -> None:
    """Flag day-over-day returns outside tolerance for manual review. Sprint 1."""
    raise NotImplementedError("Sprint 1: implement split-sanity validation.")
