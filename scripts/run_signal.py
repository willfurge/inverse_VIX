"""Compute today's (or a given date's) regime and signal panel row.

Usage:
    python scripts/run_signal.py [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import pandas as pd

from vixharvest.curve.features import build_signal_panel



def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build and display a signal-panel row.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=REPO_ROOT / "data",
        help="Directory containing interim inputs and receiving processed output.",
    )
    parser.add_argument(
        "--date",
        help="Exact EOD date to display (YYYY-MM-DD). Defaults to the latest available date.",
    )
    args = parser.parse_args(argv)

    panel = build_signal_panel(data_dir=args.data_dir)
    if args.date is None:
        row = panel.iloc[-1]
    else:
        requested_date = pd.Timestamp(args.date).normalize()
        matching_rows = panel.loc[panel["date"] == requested_date]
        if matching_rows.empty:
            raise ValueError(
                f"No signal-panel row exists for {requested_date.date()}; "
                "choose an available trading date."
            )
        row = matching_rows.iloc[0]
    print(row.to_string())


if __name__ == "__main__":
    main()
