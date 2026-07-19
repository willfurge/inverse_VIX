"""Full daily feature panel (thesis.md section 4.1, plan.md Sprint 2.3).

Writes data/processed/signal_panel.parquet with columns: date, vix, vix3m,
vix9d, m1, m2, expiries, vx30, basis_m1, basis_m1_pct, slope_m1m2,
roll_yield_daily, ratio_vix_vix3m, vix9d_vix, plus 5-day deltas of the ratios.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from pandas.tseries.holiday import GoodFriday, USFederalHolidayCalendar

from vixharvest.curve.calendar import build_expiry_calendar
from vixharvest.curve.constant_maturity import compute_vx30
from vixharvest.etl.validate import (
    AD_HOC_EXCHANGE_CLOSURES,
    DataValidationError,
    validate_panel,
    validate_positive_columns,
)


class FeatureConstructionError(DataValidationError):
    """Raised when the daily signal panel cannot be assembled safely."""


INDEX_CLOSE_COLUMNS = ("date", "vix_close", "vix3m_close", "vix9d_close")
PANEL_COLUMNS = (
    "date",
    "vix",
    "vix3m",
    "vix9d",
    "m1_contract",
    "m1_expiry",
    "m1",
    "m2_contract",
    "m2_expiry",
    "m2",
    "vx30",
    "basis_m1",
    "basis_m1_pct",
    "slope_m1m2",
    "roll_yield_daily",
    "ratio_vix_vix3m",
    "vix9d_vix",
    "ratio_vix_vix3m_delta5",
    "vix9d_vix_delta5",
)


def build_signal_panel(*, data_dir: Path | None = None) -> pd.DataFrame:
    """Build and persist the no-lookahead curve and regime feature panel.

    Each row contains only EOD observations from its own date. Execution
    timing is deliberately left to the Sprint 3 backtest engine.
    """
    interim_dir = _data_dir(data_dir) / "interim"
    indices_path = interim_dir / "indices.parquet"
    contracts_path = interim_dir / "vx_contracts.parquet"
    _require_input_files(indices_path, contracts_path)
    indices = pd.read_parquet(indices_path)
    contracts = pd.read_parquet(contracts_path)
    _validate_indices(indices)

    expiry_calendar = build_expiry_calendar(contracts, data_dir=data_dir)
    curve = compute_vx30(contracts, expiry_calendar)
    index_closes = indices.loc[:, INDEX_CLOSE_COLUMNS].rename(
        columns={
            "vix_close": "vix",
            "vix3m_close": "vix3m",
            "vix9d_close": "vix9d",
        }
    )
    index_closes["date"] = pd.to_datetime(index_closes["date"], errors="coerce").dt.normalize()
    index_closes = index_closes.dropna(subset=("date", "vix", "vix3m", "vix9d"))
    curve_dates_missing_from_indices = pd.DatetimeIndex(curve["date"]).difference(
        pd.DatetimeIndex(index_closes["date"])
    )
    unexpected_missing_dates = curve_dates_missing_from_indices
    if not curve_dates_missing_from_indices.empty:
        unexpected_missing_dates = curve_dates_missing_from_indices.difference(
            _exchange_holidays(
                curve_dates_missing_from_indices.min(), curve_dates_missing_from_indices.max()
            )
        )
    if not unexpected_missing_dates.empty:
        values = unexpected_missing_dates.strftime("%Y-%m-%d").tolist()
        raise FeatureConstructionError(
            f"VX curve dates missing CBOE index closes: {values[:10]}"
        )

    panel = index_closes.merge(curve, on="date", how="inner", validate="one_to_one")
    panel = panel.sort_values("date", ignore_index=True)
    validate_panel(panel, date_column="date")
    validate_positive_columns(panel, ("vix", "vix3m", "vix9d", "m1", "m2", "vx30"))

    panel["basis_m1"] = panel["m1"] - panel["vix"]
    panel["basis_m1_pct"] = panel["basis_m1"] / panel["vix"]
    panel["slope_m1m2"] = (panel["m2"] - panel["m1"]) / panel["m1"]
    panel["ratio_vix_vix3m"] = panel["vix"] / panel["vix3m"]
    panel["vix9d_vix"] = panel["vix9d"] / panel["vix"]
    panel["roll_yield_daily"] = _roll_yield_daily(panel, expiry_calendar)
    panel["ratio_vix_vix3m_delta5"] = panel["ratio_vix_vix3m"].diff(5)
    panel["vix9d_vix_delta5"] = panel["vix9d_vix"].diff(5)

    processed_dir = _data_dir(data_dir) / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    result = panel.loc[:, PANEL_COLUMNS]
    result.to_parquet(processed_dir / "signal_panel.parquet", index=False)
    return result


def _roll_yield_daily(panel: pd.DataFrame, expiry_calendar: pd.DataFrame) -> pd.Series:
    """Estimate daily M1-to-M2 roll bleed using each observed roll cycle."""
    expiries = expiry_calendar["expiry"].sort_values(ignore_index=True)
    prior_expiries = expiries.shift(1)
    cycle_days = {
        expiry: _trading_days_between(previous_expiry, expiry)
        for previous_expiry, expiry in zip(prior_expiries.iloc[1:], expiries.iloc[1:], strict=True)
    }
    trading_days = panel["m1_expiry"].map(cycle_days)
    return (panel["m1"] - panel["m2"]) / panel["m2"] / trading_days


def _trading_days_between(previous_expiry: pd.Timestamp, expiry: pd.Timestamp) -> int:
    start = previous_expiry + pd.Timedelta(days=1)
    business_days = pd.bdate_range(start=start, end=expiry)
    count = len(business_days.difference(_exchange_holidays(start, expiry)))
    if count <= 0:
        raise FeatureConstructionError(
            f"VX expiry cycle has no trading days: {previous_expiry.date()} to {expiry.date()}"
        )
    return count


def _exchange_holidays(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    federal_holidays = USFederalHolidayCalendar().holidays(start=start, end=end)
    return federal_holidays.union(
        GoodFriday.dates(start_date=start, end_date=end)
    ).union(AD_HOC_EXCHANGE_CLOSURES)


def _require_input_files(indices_path: Path, contracts_path: Path) -> None:
    missing = [str(path) for path in (indices_path, contracts_path) if not path.exists()]
    if missing:
        raise FeatureConstructionError(
            "Missing required interim data files: " + ", ".join(missing)
        )


def _validate_indices(indices: pd.DataFrame) -> None:
    missing = set(INDEX_CLOSE_COLUMNS).difference(indices.columns)
    if missing:
        raise FeatureConstructionError(
            f"Index panel missing columns: {sorted(missing)}"
        )
    if indices.empty:
        raise FeatureConstructionError("Index panel is empty.")


def _data_dir(data_dir: Path | None) -> Path:
    return data_dir or _repo_root() / "data"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]
