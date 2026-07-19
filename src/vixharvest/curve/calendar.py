"""Build the VX expiry calendar from the contract data itself (plan.md Sprint 2.1).

Cross-checked against CBOE's published calendar for recent years.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from vixharvest.etl.validate import DataValidationError


class CalendarValidationError(DataValidationError):
    """Raised when VX contract observations cannot form a reliable expiry calendar."""


CALENDAR_COLUMNS = ("contract", "expiry", "first_date", "last_date", "n_obs")
MAX_LAST_OBSERVATION_GAP_DAYS = 5
MIN_EXPIRY_GAP_DAYS = 21
MAX_EXPIRY_GAP_DAYS = 40


def build_expiry_calendar(
    contracts: pd.DataFrame,
    *,
    data_dir: Path | None = None,
    persist: bool = True,
) -> pd.DataFrame:
    """Derive and optionally persist the canonical VX expiry calendar.

    The contract data, rather than a hardcoded rule, defines each expiry. A
    small last-observation tolerance accommodates documented CFE expiry-row
    placeholders that are excluded during ETL.
    """
    _validate_contract_columns(contracts)
    normalized = contracts[["contract", "date", "expiry"]].copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce").dt.normalize()
    normalized["expiry"] = pd.to_datetime(normalized["expiry"], errors="coerce").dt.normalize()
    if normalized[["date", "expiry"]].isna().any().any():
        raise CalendarValidationError("VX contracts contain invalid dates or expiries.")

    expiry_counts = normalized.groupby("contract")["expiry"].nunique()
    inconsistent = expiry_counts[expiry_counts != 1]
    if not inconsistent.empty:
        raise CalendarValidationError(
            "VX contracts map to multiple expiries: " + ", ".join(inconsistent.index[:5])
        )

    calendar = (
        normalized.groupby(["contract", "expiry"], as_index=False)
        .agg(first_date=("date", "min"), last_date=("date", "max"), n_obs=("date", "size"))
        .sort_values("expiry", ignore_index=True)
    )
    _validate_calendar(calendar)

    if persist:
        interim_dir = _data_dir(data_dir) / "interim"
        interim_dir.mkdir(parents=True, exist_ok=True)
        calendar.to_parquet(interim_dir / "expiry_calendar.parquet", index=False)
    return calendar.loc[:, CALENDAR_COLUMNS]


def _validate_contract_columns(contracts: pd.DataFrame) -> None:
    required = {"contract", "date", "expiry"}
    missing = required.difference(contracts.columns)
    if missing:
        raise CalendarValidationError(
            f"VX contracts missing columns: {sorted(missing)}"
        )
    if contracts.empty:
        raise CalendarValidationError("VX contracts panel is empty.")


def _validate_calendar(calendar: pd.DataFrame) -> None:
    if calendar["expiry"].duplicated().any():
        duplicated = calendar.loc[calendar["expiry"].duplicated(keep=False), "expiry"]
        values = duplicated.dt.strftime("%Y-%m-%d").unique().tolist()
        raise CalendarValidationError(f"Duplicate VX expiries: {values[:5]}")

    after_expiry = calendar["last_date"] > calendar["expiry"]
    if after_expiry.any():
        values = calendar.loc[after_expiry, "contract"].tolist()
        raise CalendarValidationError(
            f"VX contract observations occur after expiry: {values[:5]}"
        )

    panel_as_of = calendar["last_date"].max()
    expiry_gaps = (calendar["expiry"] - calendar["last_date"]).dt.days
    expired_contracts = calendar["expiry"] <= panel_as_of
    too_early = expired_contracts & (expiry_gaps > MAX_LAST_OBSERVATION_GAP_DAYS)
    if too_early.any():
        values = calendar.loc[too_early, "contract"].tolist()
        raise CalendarValidationError(
            "VX contract final observation is too far before expiry: "
            + ", ".join(values[:5])
        )

    spacing = calendar["expiry"].diff().dt.days.iloc[1:]
    invalid_spacing = spacing.loc[
        (spacing < MIN_EXPIRY_GAP_DAYS) | (spacing > MAX_EXPIRY_GAP_DAYS)
    ]
    if not invalid_spacing.empty:
        values = calendar.loc[invalid_spacing.index, "expiry"].dt.strftime("%Y-%m-%d").tolist()
        raise CalendarValidationError(f"Unexpected VX expiry spacing before: {values[:5]}")


def _data_dir(data_dir: Path | None) -> Path:
    return data_dir or _repo_root() / "data"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]
