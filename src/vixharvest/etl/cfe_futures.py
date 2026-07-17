"""Download and parse per-contract VIX futures (VX) CSVs from the CBOE CFE
historical data page.

Sprint 1.2 step 2 (plan.md). Writes data/interim/vx_contracts.parquet.
"""


def fetch_contract(symbol: str) -> None:
    """Download the raw CSV for a single VX contract month. Sprint 1."""
    raise NotImplementedError("Sprint 1: implement per-contract VX download.")


def build_vx_contracts_panel() -> None:
    """Concatenate all downloaded contracts into data/interim/vx_contracts.parquet. Sprint 1."""
    raise NotImplementedError("Sprint 1: implement contract concatenation + validation.")
