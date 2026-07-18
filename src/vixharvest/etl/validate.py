"""Shared ingest-time validation pass (thesis.md §9, plan.md Sprint 1.2 step 4).

Every loader calls this; failures raise, they never warn-and-continue.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
from pandas.tseries.holiday import GoodFriday, USFederalHolidayCalendar


class DataValidationError(ValueError):
    """Raised when a downloaded data set is incomplete or structurally invalid."""


# Dates when US equity markets were closed but which are not covered by the
# federal holiday calendar. This lets continuity checks fail on genuine missing
# observations without treating known exchange closures as data gaps.
AD_HOC_EXCHANGE_CLOSURES = pd.DatetimeIndex(
    [
        "1994-04-27",
        "2001-09-11",
        "2001-09-12",
        "2001-09-13",
        "2001-09-14",
        "2004-06-11",
        "2007-01-02",
        "2012-10-29",
        "2012-10-30",
        "2018-12-05",
        "2025-01-09",
    ]
)

# CBOE's legacy index-history CSV omits these otherwise-open historical dates.
# They are source-specific observations, not general exchange closures.
CBOE_INDEX_SOURCE_OMISSIONS = pd.DatetimeIndex(
    ["1991-03-01", "1997-01-31", "1997-11-26"]
)


def validate_panel(
    df: pd.DataFrame,
    checks: Iterable[str] | None = None,
    *,
    date_column: str = "date",
) -> None:
    """Run standard date validation against a freshly-loaded daily panel.

    Raises rather than warning when dates are malformed, duplicated, unordered,
    or missing on an expected US trading day.
    """
    enabled_checks = set(checks or ("dates", "continuity"))
    if date_column not in df.columns:
        raise DataValidationError(f"Missing required date column: {date_column}")
    if df.empty:
        raise DataValidationError("Panel is empty.")

    dates = pd.to_datetime(df[date_column], errors="coerce").dt.normalize()
    if dates.isna().any():
        raise DataValidationError(f"{date_column} contains invalid dates.")
    if "dates" in enabled_checks:
        if dates.duplicated().any():
            duplicates = dates[dates.duplicated()].dt.strftime("%Y-%m-%d").tolist()
            raise DataValidationError(f"Duplicate dates: {duplicates[:5]}")
        if not dates.is_monotonic_increasing:
            raise DataValidationError(f"{date_column} must be sorted ascending.")
    if "continuity" in enabled_checks:
        validate_trading_date_continuity(dates)


def validate_trading_date_continuity(dates: pd.Series) -> None:
    """Reject missing expected market days between the first and last observation."""
    start, end = dates.iloc[0], dates.iloc[-1]
    business_days = pd.bdate_range(start=start, end=end)
    federal_holidays = USFederalHolidayCalendar().holidays(start=start, end=end)
    exchange_holidays = federal_holidays.union(
        GoodFriday.dates(start_date=start, end_date=end)
    )
    expected_dates = business_days.difference(exchange_holidays).difference(
        AD_HOC_EXCHANGE_CLOSURES
    ).difference(CBOE_INDEX_SOURCE_OMISSIONS)
    missing_dates = expected_dates.difference(pd.DatetimeIndex(dates))
    if not missing_dates.empty:
        formatted = missing_dates.strftime("%Y-%m-%d").tolist()
        raise DataValidationError(
            "Unexpected trading-date gaps: " + ", ".join(formatted[:10])
        )


def validate_positive_columns(df: pd.DataFrame, columns: Iterable[str]) -> None:
    """Ensure specified market-price columns are numeric and strictly positive."""
    for column in columns:
        if column not in df.columns:
            raise DataValidationError(f"Missing required column: {column}")
        values = pd.to_numeric(df[column], errors="coerce")
        if values.isna().any() or (values <= 0).any():
            raise DataValidationError(f"{column} must contain only positive numeric values.")


def validate_vx_contracts(contracts: pd.DataFrame) -> None:
    """Validate the normalized VX-contract table required by Sprint 1."""
    required_columns = {
        "date",
        "contract",
        "expiry",
        "open",
        "high",
        "low",
        "close",
        "settle",
        "volume",
        "oi",
    }
    missing_columns = required_columns.difference(contracts.columns)
    if missing_columns:
        raise DataValidationError(f"VX contracts missing columns: {sorted(missing_columns)}")
    if contracts.empty:
        raise DataValidationError("VX contracts panel is empty.")

    normalized = contracts.copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce").dt.normalize()
    normalized["expiry"] = pd.to_datetime(normalized["expiry"], errors="coerce").dt.normalize()
    if normalized[["date", "expiry"]].isna().any().any():
        raise DataValidationError("VX contracts contain invalid dates or expiries.")
    if normalized.duplicated(["date", "contract"]).any():
        raise DataValidationError("VX contracts contain duplicate date/contract rows.")
    validate_positive_columns(normalized, ["settle"])

    non_wednesday = normalized.loc[normalized["expiry"].dt.dayofweek != 2, "expiry"].drop_duplicates()
    invalid_expiries = [
        expiry
        for expiry in non_wednesday
        if not _is_holiday_shifted_wednesday(expiry)
    ]
    if invalid_expiries:
        values = [expiry.strftime("%Y-%m-%d") for expiry in invalid_expiries]
        raise DataValidationError(f"Unexpected non-Wednesday VX expiries: {values}")

    available_from = max(normalized["date"].min(), pd.Timestamp("2007-01-01"))
    live_contracts = normalized.loc[
        (normalized["date"] >= available_from) & (normalized["expiry"] > normalized["date"])
    ]
    counts = live_contracts.groupby("date")["contract"].nunique()
    if (counts < 2).any():
        failures = counts[counts < 2].index.strftime("%Y-%m-%d").tolist()
        raise DataValidationError(f"Fewer than two live VX contracts: {failures[:10]}")


def validate_etp_prices(prices: pd.DataFrame, *, ticker: str) -> None:
    """Reject unadjusted VXX/UVXY series using the project split-sanity limit."""
    required_columns = {"date", "ticker", "close"}
    missing_columns = required_columns.difference(prices.columns)
    if missing_columns:
        raise DataValidationError(f"{ticker} prices missing columns: {sorted(missing_columns)}")
    validate_panel(prices, date_column="date")
    validate_positive_columns(prices, ["close"])

    returns = prices["close"].pct_change(fill_method=None)
    dates = pd.to_datetime(prices["date"])
    stress_mask = pd.Series(False, index=prices.index)
    for start, end in (
        ("2018-02-01", "2018-02-14"),
        ("2020-02-19", "2020-03-31"),
        ("2024-08-01", "2024-08-09"),
        ("2025-04-01", "2025-04-15"),
    ):
        stress_mask |= dates.between(start, end)
    suspicious = returns.abs().gt(0.60) & ~stress_mask
    if suspicious.any():
        failures = dates.loc[suspicious].dt.strftime("%Y-%m-%d").tolist()
        raise DataValidationError(
            f"{ticker} has >60% adjusted-close returns outside stress windows: {failures[:10]}"
        )


def _is_holiday_shifted_wednesday(expiry: pd.Timestamp) -> bool:
    """Allow documented VIX-futures holiday adjustments around normal expiry."""
    nearby_wednesdays = [
        expiry + pd.Timedelta(days=offset)
        for offset in (-1, 1)
        if (expiry + pd.Timedelta(days=offset)).dayofweek == 2
    ]
    holidays = USFederalHolidayCalendar().holidays(
        start=expiry - pd.Timedelta(days=2), end=expiry + pd.Timedelta(days=32)
    ).union(
        GoodFriday.dates(
            start_date=expiry - pd.Timedelta(days=2),
            end_date=expiry + pd.Timedelta(days=32),
        )
    ).union(AD_HOC_EXCHANGE_CLOSURES)
    if any(wednesday in holidays for wednesday in nearby_wednesdays):
        return True
    # If the following month's standard SPX expiration Friday is a market
    # holiday (for example Good Friday or Juneteenth), VIX expiry shifts from
    # Wednesday to Tuesday, 31 days before that otherwise-standard Friday.
    following_standard_friday = expiry + pd.Timedelta(days=31)
    return expiry.dayofweek == 1 and following_standard_friday in holidays
