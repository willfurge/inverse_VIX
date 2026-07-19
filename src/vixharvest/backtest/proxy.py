"""Underlying-proxy backtest using the validated rolled short-term VX index."""

from __future__ import annotations

import numpy as np
import pandas as pd

from vixharvest.backtest.engine import run_backtest
from vixharvest.signals.regimes import SignalParameters, classify_regime, load_signal_parameters


class ProxyConstructionError(ValueError):
    """Raised when the rolled short-term-futures proxy cannot be constructed safely."""


def build_stf_proxy_index(contracts: pd.DataFrame) -> pd.DataFrame:
    """Build the diagnostics-validated rolled short-term-futures index.

    The return on each leg is measured within its own contract identity. Roll
    weights are applied with a one-session lag, matching the validated notebook
    construction that tracks split-adjusted VXX cumulatively.
    """
    required_columns = {"date", "contract", "expiry", "settle"}
    missing_columns = required_columns.difference(contracts.columns)
    if missing_columns:
        raise ProxyConstructionError(f"VX contracts missing columns: {sorted(missing_columns)}")
    if contracts.empty:
        raise ProxyConstructionError("VX contracts are empty.")

    observations = contracts.loc[:, ["date", "contract", "expiry", "settle"]].copy()
    observations["date"] = pd.to_datetime(observations["date"], errors="coerce").dt.normalize()
    observations["expiry"] = pd.to_datetime(observations["expiry"], errors="coerce").dt.normalize()
    observations["settle"] = pd.to_numeric(observations["settle"], errors="coerce")
    if observations[["date", "expiry", "settle"]].isna().any().any():
        raise ProxyConstructionError("VX contracts contain invalid dates, expiries, or settlements.")
    if observations.duplicated(["date", "contract"]).any():
        raise ProxyConstructionError("VX contracts contain duplicate date/contract rows.")
    if (observations["settle"] <= 0).any():
        raise ProxyConstructionError("VX contracts contain non-positive settlements.")

    live = observations.loc[observations["expiry"] > observations["date"]].copy()
    live = live.sort_values(["date", "expiry", "contract"], ignore_index=True)
    live["rank"] = live.groupby("date").cumcount() + 1
    _validate_front_two(live)

    observations = observations.sort_values(["contract", "date"], ignore_index=True)
    observations["contract_return"] = observations.groupby("contract")["settle"].pct_change(
        fill_method=None
    )
    live = live.merge(
        observations[["date", "contract", "contract_return"]],
        on=["date", "contract"],
        how="left",
        validate="one_to_one",
    )

    near = live.loc[live["rank"] == 1].set_index("date")
    next_contract = live.loc[live["rank"] == 2].set_index("date")
    index_frame = pd.DataFrame(index=near.index.sort_values())
    index_frame["near_contract"] = near["contract"]
    index_frame["next_contract"] = next_contract["contract"]
    index_frame["expiry"] = near["expiry"]
    index_frame["near_return"] = near["contract_return"]
    index_frame["next_return"] = next_contract["contract_return"]

    expiries = np.sort(index_frame["expiry"].unique())
    previous_expiry = {expiries[i]: expiries[i - 1] for i in range(1, len(expiries))}
    index_frame["period_start"] = index_frame["expiry"].map(previous_expiry)
    index_frame = index_frame.dropna(subset=["period_start"]).copy()
    if index_frame.empty:
        raise ProxyConstructionError("No complete roll periods are available for the STF proxy.")

    period_days = _business_days(index_frame["period_start"], index_frame["expiry"])
    days_remaining = _business_days(index_frame.index.to_series(), index_frame["expiry"])
    if (period_days <= 0).any():
        raise ProxyConstructionError("STF roll period has no business days.")
    index_frame["near_weight"] = (days_remaining / period_days).clip(0.0, 1.0)
    lagged_weight = index_frame["near_weight"].shift(1)
    index_frame["underlying_return"] = (
        lagged_weight * index_frame["near_return"]
        + (1.0 - lagged_weight) * index_frame["next_return"]
    ).fillna(0.0)
    index_frame["stf_index"] = (1.0 + index_frame["underlying_return"]).cumprod()
    if not np.isfinite(index_frame[["underlying_return", "stf_index"]].to_numpy()).all() or (
        index_frame["stf_index"] <= 0
    ).any():
        raise ProxyConstructionError("STF proxy contains invalid daily returns or index levels.")

    return (
        index_frame.reset_index(names="date")
        .loc[
            :,
            [
                "date",
                "near_contract",
                "next_contract",
                "expiry",
                "period_start",
                "near_weight",
                "underlying_return",
                "stf_index",
            ],
        ]
        .sort_values("date", ignore_index=True)
    )


def run_proxy_backtest(
    panel: pd.DataFrame,
    contracts: pd.DataFrame,
    *,
    parameters: SignalParameters | None = None,
) -> pd.DataFrame:
    """Run filtered, unconditional-short, and flat daily proxy strategies.

    ``panel`` contains date-t close features. The returned filtered position and
    return columns are generated by the engine's structural one-session lag.
    """
    _validate_panel(panel)
    frozen = parameters or load_signal_parameters()
    stf = build_stf_proxy_index(contracts)
    features = panel.copy()
    features["date"] = pd.to_datetime(features["date"], errors="coerce").dt.normalize()
    merged = features.merge(stf, on="date", how="inner", validate="one_to_one")
    if merged.empty:
        raise ProxyConstructionError("Signal panel and STF proxy have no overlapping dates.")
    merged = merged.sort_values("date", ignore_index=True)
    merged["regime"] = merged.apply(
        lambda row: classify_regime(row, parameters=frozen), axis="columns"
    )
    merged["harvest_signal"] = merged["regime"].eq("HARVEST")

    strategy_returns = run_backtest(
        merged[["date", "harvest_signal", "underlying_return"]]
    )
    result = merged.merge(strategy_returns, on=["date", "harvest_signal", "underlying_return"], validate="one_to_one")
    result["prior_signal_date"] = result["date"].shift(1).where(result["filtered_position"])
    result["is_backwardation"] = result["slope_m1m2"].le(0.0)
    return result


def _business_days(start: pd.Series, end: pd.Series) -> np.ndarray:
    return np.busday_count(
        start.to_numpy(dtype="datetime64[D]"), end.to_numpy(dtype="datetime64[D]")
    )


def _validate_front_two(live: pd.DataFrame) -> None:
    counts = live.groupby("date")["contract"].size()
    insufficient = counts[counts < 2]
    if not insufficient.empty:
        dates = insufficient.index.strftime("%Y-%m-%d").tolist()
        raise ProxyConstructionError(f"Fewer than two live VX contracts: {dates[:10]}")


def _validate_panel(panel: pd.DataFrame) -> None:
    required_columns = {
        "date",
        "ratio_vix_vix3m",
        "slope_m1m2",
        "ratio_vix_vix3m_delta5",
        "vix9d_vix",
    }
    missing_columns = required_columns.difference(panel.columns)
    if missing_columns:
        raise ProxyConstructionError(f"Signal panel missing columns: {sorted(missing_columns)}")
    if panel.empty:
        raise ProxyConstructionError("Signal panel is empty.")
    dates = pd.to_datetime(panel["date"], errors="coerce").dt.normalize()
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ProxyConstructionError("Signal panel dates must be valid, unique, and sorted ascending.")
