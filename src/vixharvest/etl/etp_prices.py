"""Download VXX/UVXY split-adjusted daily prices and run the split-sanity check.

Sprint 1.2 step 3 (plan.md). Day-over-day returns must never exceed ~60% outside
documented stress windows; anomalies (VXX->VXXB->VXX 2019, 2022 creation halt) are
logged in data/ANOMALIES.md, not silently patched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yaml

from vixharvest.etl.validate import DataValidationError, validate_etp_prices


class CoverageError(DataValidationError):
    """Raised when a provider cannot supply the configured research window."""


def fetch_etp_prices(
    ticker: str,
    *,
    config_path: Path | None = None,
    data_dir: Path | None = None,
    ticker_factory: Callable[[str], Any] | None = None,
    enforce_coverage: bool = True,
) -> pd.DataFrame:
    """Download split-adjusted VXX or UVXY data from yfinance.

    ``auto_adjust=True`` is intentional: yfinance then returns the
    split/dividend-adjusted series in ``Close`` and does not expose ``Adj Close``.
    The raw vendor export retains the related actions columns for auditability.
    """
    config = _load_config(config_path)["etp_prices"]
    key = ticker.lower()
    if key not in ("vxx", "uvxy"):
        raise ValueError("ETP ticker must be VXX or UVXY.")
    ticker_config = config[key]
    vendor_ticker = ticker_config["ticker"]
    if not config["auto_adjust"]:
        raise DataValidationError("ETP source config must set auto_adjust: true.")

    if ticker_factory is None:
        import yfinance as yf

        ticker_factory = yf.Ticker
    raw_history = ticker_factory(vendor_ticker).history(
        period="max", auto_adjust=True, actions=True, raise_errors=True
    )
    if raw_history.empty:
        raise DataValidationError(f"yfinance returned no history for {vendor_ticker}.")
    raw_dir = _raw_etp_dir(data_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_history.to_csv(raw_dir / f"{vendor_ticker}_yfinance_auto_adjusted.csv")

    prices = raw_history.reset_index().rename(columns={"Date": "date", "Close": "close"})
    prices["date"] = pd.to_datetime(prices["date"], utc=True).dt.tz_localize(None).dt.normalize()
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices["ticker"] = vendor_ticker
    result = prices[["date", "ticker", "close"]].sort_values("date", ignore_index=True)
    validate_etp_prices(result, ticker=vendor_ticker)

    required_start = pd.Timestamp(ticker_config["required_coverage_start"])
    actual_start = result["date"].min()
    if enforce_coverage and actual_start > required_start:
        raise CoverageError(
            f"{vendor_ticker} history starts {actual_start.date()}, but Sprint 1 requires "
            f"{required_start.date()}. Use a separate historical source; do not silently stitch it."
        )
    return result


def build_etp_prices_panel(
    *,
    config_path: Path | None = None,
    data_dir: Path | None = None,
    enforce_coverage: bool = True,
) -> pd.DataFrame:
    """Download, validate, and persist the VXX/UVXY adjusted-close panel."""
    frames = [
        fetch_etp_prices(
            ticker,
            config_path=config_path,
            data_dir=data_dir,
            enforce_coverage=enforce_coverage,
        )
        for ticker in ("VXX", "UVXY")
    ]
    panel = pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"], ignore_index=True)
    interim_dir = _interim_dir(data_dir)
    interim_dir.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(interim_dir / "etp_prices.parquet", index=False)
    return panel


def check_split_sanity(prices: pd.DataFrame, *, ticker: str) -> None:
    """Validate the adjusted series with the configured >60% return tripwire."""
    validate_etp_prices(prices, ticker=ticker)


def _load_config(config_path: Path | None) -> dict[str, Any]:
    path = Path(config_path) if config_path else _repo_root() / "config" / "data_sources.yaml"
    with path.open(encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _data_dir(data_dir: Path | None) -> Path:
    return data_dir or _repo_root() / "data"


def _raw_etp_dir(data_dir: Path | None) -> Path:
    return _data_dir(data_dir) / "raw" / "etp"


def _interim_dir(data_dir: Path | None) -> Path:
    return _data_dir(data_dir) / "interim"
