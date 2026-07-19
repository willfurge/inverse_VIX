"""One command to re-pull all raw data incrementally (plan.md Sprint 1.2 step 5).

Usage:
    python scripts/refresh_data.py
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from vixharvest.etl.cboe_indices import build_indices_panel
from vixharvest.etl.cfe_futures import build_vx_contracts_panel
from vixharvest.etl.etp_prices import build_etp_prices_panel


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Refresh the market data required by the research pipeline.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=REPO_ROOT / "data",
        help="Directory receiving raw and interim data.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "config" / "data_sources.yaml",
        help="Data-source configuration file.",
    )
    parser.add_argument(
        "--allow-incomplete-coverage",
        action="store_true",
        help="Write available data even when the configured coverage window is not met.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    logging.info("Refreshing CBOE index histories")
    build_indices_panel(config_path=args.config, data_dir=args.data_dir)
    logging.info("Refreshing CFE VX contract histories")
    build_vx_contracts_panel(
        config_path=args.config,
        data_dir=args.data_dir,
        enforce_coverage=not args.allow_incomplete_coverage,
    )
    logging.info("Refreshing split-adjusted VXX/UVXY histories")
    build_etp_prices_panel(
        config_path=args.config,
        data_dir=args.data_dir,
        enforce_coverage=not args.allow_incomplete_coverage,
    )
    logging.info("All Sprint 1 data sets refreshed successfully")


if __name__ == "__main__":
    main()
