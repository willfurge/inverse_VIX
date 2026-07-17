"""Download and parse VIX / VIX3M / VIX9D index history CSVs from the CBOE CDN.

Sprint 1.2 step 1 (plan.md) — the fastest win; unlocks the VIX/VIX3M ratio regime
flag. Writes data/interim/indices.parquet.
"""


def fetch_index_history(index_name: str) -> None:
    """Download one index's history CSV (VIX, VIX3M, or VIX9D). Sprint 1."""
    raise NotImplementedError("Sprint 1: implement index CSV download + parsing.")


def build_indices_panel() -> None:
    """Combine VIX/VIX3M/VIX9D into data/interim/indices.parquet. Sprint 1."""
    raise NotImplementedError("Sprint 1: implement indices panel build + validation.")
