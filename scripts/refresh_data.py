"""One command to re-pull all raw data incrementally (plan.md Sprint 1.2 step 5).

Usage:
    python scripts/refresh_data.py
"""

from __future__ import annotations

import argparse
import logging

from vixharvest.etl.cboe_indices import build_indices_panel
from vixharvest.etl.cfe_futures import build_vx_contracts_panel
from vixharvest.etl.etp_prices import build_etp_prices_panel


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh all Sprint 1 market-data sets.")
    parser.add_argument(
        "--allow-incomplete-coverage",
        action="store_true",
        help="Write available public data even when CFE/VXX cannot meet the research coverage window.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    logging.info("Refreshing CBOE index histories")
    build_indices_panel()
    logging.info("Refreshing CFE VX contract histories")
    build_vx_contracts_panel(enforce_coverage=not args.allow_incomplete_coverage)
    logging.info("Refreshing split-adjusted VXX/UVXY histories")
    build_etp_prices_panel(enforce_coverage=not args.allow_incomplete_coverage)
    logging.info("All Sprint 1 data sets refreshed successfully")


if __name__ == "__main__":
    main()
