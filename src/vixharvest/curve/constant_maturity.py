"""Constant-maturity VX30 interpolation (plan.md Sprint 2.2).

For each date, identify M1/M2 (nearest and next expiries with expiry > date),
compute calendar-day weights, and produce vx30. Handles roll dates and
holiday-shifted expiries.
"""

from __future__ import annotations

import pandas as pd

from vixharvest.etl.validate import DataValidationError


class CurveConstructionError(DataValidationError):
    """Raised when a daily VX30 curve cannot be constructed without a gap."""


TARGET_MATURITY_DAYS = 30
CURVE_COLUMNS = (
    "date",
    "m1_contract",
    "m1_expiry",
    "m1",
    "m2_contract",
    "m2_expiry",
    "m2",
    "vx30",
)


def compute_vx30(contracts: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    """Construct the calendar-day-weighted, 30-day constant-maturity VX price.

    Expiry-day settlements are eligible as M1. The following contract becomes
    M1 on the next trading day, so roll behavior follows the observed CFE
    calendar rather than a hardcoded weekday convention.
    """
    _validate_inputs(contracts, calendar)
    observations = contracts[["date", "contract", "expiry", "settle"]].copy()
    observations["date"] = pd.to_datetime(observations["date"], errors="coerce").dt.normalize()
    observations["expiry"] = pd.to_datetime(observations["expiry"], errors="coerce").dt.normalize()
    observations["settle"] = pd.to_numeric(observations["settle"], errors="coerce")
    if observations[["date", "expiry", "settle"]].isna().any().any():
        raise CurveConstructionError("VX contracts contain invalid dates, expiries, or settlements.")
    if (observations["settle"] <= 0).any():
        raise CurveConstructionError("VX contracts contain non-positive settlements.")

    calendar_contracts = calendar[["contract", "expiry"]].copy()
    calendar_contracts["expiry"] = pd.to_datetime(
        calendar_contracts["expiry"], errors="coerce"
    ).dt.normalize()
    validated = observations.merge(
        calendar_contracts,
        on=["contract", "expiry"],
        how="inner",
        validate="many_to_one",
    )
    if len(validated) != len(observations):
        missing_contracts = observations.loc[
            ~observations["contract"].isin(calendar_contracts["contract"]), "contract"
        ].unique()
        raise CurveConstructionError(
            "VX contract observations are absent from the expiry calendar: "
            + ", ".join(missing_contracts[:5])
        )

    live = validated.loc[validated["expiry"] >= validated["date"]].copy()
    live = live.sort_values(["date", "expiry", "contract"], ignore_index=True)
    ranks = live.groupby("date").cumcount()
    front_two = live.loc[ranks < 2].copy()
    daily_counts = front_two.groupby("date").size()
    all_dates = pd.DatetimeIndex(validated["date"].drop_duplicates().sort_values())
    missing_m2_dates = all_dates.difference(pd.DatetimeIndex(daily_counts[daily_counts == 2].index))
    if not missing_m2_dates.empty:
        values = missing_m2_dates.strftime("%Y-%m-%d").tolist()
        raise CurveConstructionError(f"Fewer than two live VX contracts: {values[:10]}")

    m1 = front_two.loc[ranks == 0].set_index("date")
    m2 = front_two.loc[ranks == 1].set_index("date")
    curve = pd.DataFrame(
        {
            "m1_contract": m1["contract"],
            "m1_expiry": m1["expiry"],
            "m1": m1["settle"],
            "m2_contract": m2["contract"],
            "m2_expiry": m2["expiry"],
            "m2": m2["settle"],
        }
    ).reset_index(names="date")
    days_to_m1 = (curve["m1_expiry"] - curve["date"]).dt.days
    days_to_m2 = (curve["m2_expiry"] - curve["date"]).dt.days
    invalid_expiries = days_to_m1 >= days_to_m2
    if invalid_expiries.any():
        values = curve.loc[invalid_expiries, "date"].dt.strftime("%Y-%m-%d").tolist()
        raise CurveConstructionError(f"Invalid M1/M2 expiry ordering: {values[:10]}")

    span = days_to_m2 - days_to_m1
    weight_m1 = (days_to_m2 - TARGET_MATURITY_DAYS) / span
    weight_m2 = (TARGET_MATURITY_DAYS - days_to_m1) / span
    curve["vx30"] = weight_m1 * curve["m1"] + weight_m2 * curve["m2"]
    return curve.loc[:, CURVE_COLUMNS].sort_values("date", ignore_index=True)


def _validate_inputs(contracts: pd.DataFrame, calendar: pd.DataFrame) -> None:
    contract_columns = {"date", "contract", "expiry", "settle"}
    calendar_columns = {"contract", "expiry"}
    missing_contract_columns = contract_columns.difference(contracts.columns)
    missing_calendar_columns = calendar_columns.difference(calendar.columns)
    if missing_contract_columns:
        raise CurveConstructionError(
            f"VX contracts missing columns: {sorted(missing_contract_columns)}"
        )
    if missing_calendar_columns:
        raise CurveConstructionError(
            f"Expiry calendar missing columns: {sorted(missing_calendar_columns)}"
        )
    if contracts.empty or calendar.empty:
        raise CurveConstructionError("VX contracts and expiry calendar must both be non-empty.")
    if calendar.duplicated(["contract", "expiry"]).any():
        raise CurveConstructionError("Expiry calendar contains duplicate contract/expiry rows.")
