"""Daily proxy engine with an enforced signal-on-t, execution-on-t+1 lag."""

from __future__ import annotations

import numpy as np
import pandas as pd


class BacktestInputError(ValueError):
    """Raised when a daily backtest frame cannot be executed safely."""


def run_backtest(
    frame: pd.DataFrame,
    *,
    signal_column: str = "harvest_signal",
    underlying_return_column: str = "underlying_return",
) -> pd.DataFrame:
    """Return daily benchmark and filtered-short returns with a one-session lag.

    The signal measured at the date-t close becomes a position only for the next
    observed trading row. The returned ``filtered_position`` is therefore an
    auditable execution record rather than a convention at individual call sites.
    """
    _validate_input(frame, signal_column=signal_column, return_column=underlying_return_column)
    result = frame[["date", signal_column, underlying_return_column]].copy()
    result = result.rename(
        columns={
            signal_column: "harvest_signal",
            underlying_return_column: "underlying_return",
        }
    )
    result["harvest_signal"] = result["harvest_signal"].astype(bool)
    result["filtered_position"] = result["harvest_signal"].shift(1, fill_value=False).astype(bool)
    result["filtered_return"] = -result["filtered_position"].astype(float) * result["underlying_return"]
    result["unconditional_return"] = -result["underlying_return"]
    result["flat_return"] = 0.0
    return result


def _validate_input(frame: pd.DataFrame, *, signal_column: str, return_column: str) -> None:
    required_columns = {"date", signal_column, return_column}
    missing_columns = required_columns.difference(frame.columns)
    if missing_columns:
        raise BacktestInputError(f"Missing required backtest columns: {sorted(missing_columns)}")
    if frame.empty:
        raise BacktestInputError("Backtest frame is empty.")

    dates = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise BacktestInputError("Backtest dates must be valid, unique, and sorted ascending.")

    signals = frame[signal_column]
    if not pd.api.types.is_bool_dtype(signals) or signals.isna().any():
        raise BacktestInputError(f"{signal_column} must contain only Boolean values.")

    returns = pd.to_numeric(frame[return_column], errors="coerce")
    if returns.isna().any() or not np.isfinite(returns).all():
        raise BacktestInputError(f"{return_column} must contain only finite numeric values.")
