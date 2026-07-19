"""Precommitted Sprint 3 walk-forward metrics and GO/NO-GO evaluation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from vixharvest.signals.regimes import SignalParameters


STRATEGIES = {
    "filtered_short": "filtered_return",
    "unconditional_short": "unconditional_return",
    "flat": "flat_return",
}


@dataclass(frozen=True)
class StressWindow:
    """Named out-of-sample window used for the precommitted loss-avoidance test."""

    name: str
    start: str
    end: str


DEFAULT_STRESS_WINDOWS = (
    StressWindow("Feb 2018 (Volmageddon)", "2018-01-01", "2018-03-09"),
    StressWindow("Mar 2020 (COVID)", "2020-01-01", "2020-04-15"),
    StressWindow("Aug 2024 (yen carry)", "2024-06-01", "2024-10-06"),
    StressWindow("Apr 2025 (tariffs)", "2025-02-01", "2025-06-16"),
)


@dataclass(frozen=True)
class GateEvaluation:
    """Complete machine-readable result for the Sprint 3 precommitted gate."""

    periods: pd.DataFrame
    metrics: pd.DataFrame
    stress_windows: pd.DataFrame
    backwardation_exposure: pd.DataFrame
    criteria: pd.DataFrame
    verdict: str


def build_walk_forward_periods(
    daily: pd.DataFrame,
    parameters: SignalParameters,
    *,
    fit_start: str | pd.Timestamp,
    oos_start: str | pd.Timestamp = "2018-01-01",
) -> pd.DataFrame:
    """Create annual OOS intervals with their frozen expanding-fit provenance."""
    _validate_daily_frame(daily)
    oos = daily.loc[pd.to_datetime(daily["date"]) >= pd.Timestamp(oos_start)].copy()
    if oos.empty:
        raise ValueError("No observations are available in the requested OOS period.")

    rows = []
    last_date = pd.Timestamp(oos["date"].max()).normalize()
    for year, period in oos.groupby(pd.to_datetime(oos["date"]).dt.year, sort=True):
        test_start = pd.Timestamp(period["date"].min()).normalize()
        test_end = pd.Timestamp(period["date"].max()).normalize()
        rows.append(
            {
                "period": str(year) if year != last_date.year else f"{year} YTD",
                "fit_start": pd.Timestamp(fit_start).normalize(),
                "fit_end": pd.Timestamp(f"{year - 1}-12-31"),
                "test_start": test_start,
                "test_end": test_end,
                "is_partial": year == last_date.year and test_end < pd.Timestamp(f"{year}-12-31"),
                "test_rows": len(period),
                "theta_1_ratio": parameters.theta_1_ratio,
                "theta_2_slope": parameters.theta_2_slope,
                "momentum_lookback_days": parameters.momentum_lookback_days,
            }
        )
    return pd.DataFrame(rows)


def evaluate_sprint3_gate(
    daily: pd.DataFrame,
    parameters: SignalParameters,
    *,
    fit_start: str | pd.Timestamp,
    oos_start: str | pd.Timestamp = "2018-01-01",
    stress_windows: tuple[StressWindow, ...] = DEFAULT_STRESS_WINDOWS,
) -> GateEvaluation:
    """Calculate all precommitted Sprint 3 OOS metrics and final verdict."""
    _validate_daily_frame(daily)
    daily = daily.copy().sort_values("date", ignore_index=True)
    oos = daily.loc[pd.to_datetime(daily["date"]) >= pd.Timestamp(oos_start)].copy()
    if oos.empty:
        raise ValueError("No observations are available in the requested OOS period.")

    periods = build_walk_forward_periods(oos, parameters, fit_start=fit_start, oos_start=oos_start)
    metric_frames = [
        _period_metrics(
            oos.loc[(oos["date"] >= row.test_start) & (oos["date"] <= row.test_end)],
            period=row.period,
        )
        for row in periods.itertuples(index=False)
    ]
    metric_frames.append(_period_metrics(oos, period="2018-present"))
    metrics = pd.concat(metric_frames, ignore_index=True)

    stress = _stress_window_metrics(oos, stress_windows)
    backwardation_exposure = _backwardation_exposure(oos)
    criteria = _evaluate_criteria(metrics, stress)
    verdict = "GO" if criteria["passed"].all() else "NO-GO"
    return GateEvaluation(
        periods=periods,
        metrics=metrics,
        stress_windows=stress,
        backwardation_exposure=backwardation_exposure,
        criteria=criteria,
        verdict=verdict,
    )


def _period_metrics(frame: pd.DataFrame, *, period: str) -> pd.DataFrame:
    rows = []
    for strategy, return_column in STRATEGIES.items():
        returns = frame[return_column].astype(float)
        equity = (1.0 + returns).cumprod()
        total_return = float(equity.iloc[-1] - 1.0)
        annualized_return = float((1.0 + total_return) ** (252 / len(returns)) - 1.0)
        drawdown = equity.div(equity.cummax()).sub(1.0)
        max_drawdown = float(drawdown.min())
        return_to_drawdown = (
            annualized_return / abs(max_drawdown) if max_drawdown < 0 else np.nan
        )
        active_days = (
            int(frame["filtered_position"].sum())
            if strategy == "filtered_short"
            else (len(frame) if strategy == "unconditional_short" else 0)
        )
        position_starts = (
            int(
                (frame["filtered_position"]
                 & ~frame["filtered_position"].shift(1, fill_value=False)).sum()
            )
            if strategy == "filtered_short"
            else 0
        )
        rows.append(
            {
                "period": period,
                "strategy": strategy,
                "start": frame["date"].min(),
                "end": frame["date"].max(),
                "trading_days": len(frame),
                "active_days": active_days,
                "position_starts": position_starts,
                "total_return": total_return,
                "annualized_return": annualized_return,
                "max_drawdown": max_drawdown,
                "return_to_drawdown": return_to_drawdown,
            }
        )
    return pd.DataFrame(rows)


def _stress_window_metrics(
    daily: pd.DataFrame, windows: tuple[StressWindow, ...]
) -> pd.DataFrame:
    rows = []
    for window in windows:
        frame = daily.loc[daily["date"].between(window.start, window.end)]
        if frame.empty:
            continue
        filtered_return = _compounded_return(frame["filtered_return"])
        unconditional_return = _compounded_return(frame["unconditional_return"])
        filtered_loss = max(0.0, -filtered_return)
        unconditional_loss = max(0.0, -unconditional_return)
        applicable = unconditional_loss > 0.0
        avoided_loss = 1.0 - filtered_loss / unconditional_loss if applicable else np.nan
        rows.append(
            {
                "window": window.name,
                "start": frame["date"].min(),
                "end": frame["date"].max(),
                "trading_days": len(frame),
                "filtered_return": filtered_return,
                "unconditional_return": unconditional_return,
                "filtered_loss": filtered_loss,
                "unconditional_loss": unconditional_loss,
                "avoided_loss": avoided_loss,
                "applicable": applicable,
                "is_aggregate": False,
            }
        )

    result = pd.DataFrame(rows)
    applicable = result.loc[result["applicable"]] if not result.empty else result
    aggregate_unconditional_loss = float(applicable["unconditional_loss"].sum()) if not applicable.empty else 0.0
    aggregate_filtered_loss = float(applicable["filtered_loss"].sum()) if not applicable.empty else 0.0
    aggregate_applicable = aggregate_unconditional_loss > 0.0
    aggregate_avoidance = (
        1.0 - aggregate_filtered_loss / aggregate_unconditional_loss
        if aggregate_applicable
        else np.nan
    )
    aggregate = pd.DataFrame(
        [
            {
                "window": "Aggregate applicable stress windows",
                "start": pd.NaT,
                "end": pd.NaT,
                "trading_days": int(applicable["trading_days"].sum()) if not applicable.empty else 0,
                "filtered_return": np.nan,
                "unconditional_return": np.nan,
                "filtered_loss": aggregate_filtered_loss,
                "unconditional_loss": aggregate_unconditional_loss,
                "avoided_loss": aggregate_avoidance,
                "applicable": aggregate_applicable,
                "is_aggregate": True,
            }
        ]
    )
    return pd.concat([result, aggregate], ignore_index=True)


def _backwardation_exposure(daily: pd.DataFrame) -> pd.DataFrame:
    deployed = daily.loc[daily["filtered_position"] & daily["is_backwardation"]]
    raw_signal = daily.loc[daily["harvest_signal"] & daily["is_backwardation"]]
    return pd.DataFrame(
        [
            {
                "measure": "lagged_filtered_position_in_backwardation",
                "days": len(deployed),
                "underlying_return": _compounded_return(deployed["underlying_return"]),
                "filtered_short_return": _compounded_return(deployed["filtered_return"]),
            },
            {
                "measure": "same_day_harvest_signal_in_backwardation",
                "days": len(raw_signal),
                "underlying_return": _compounded_return(raw_signal["underlying_return"]),
                "filtered_short_return": _compounded_return(raw_signal["filtered_return"]),
            },
        ]
    )


def _evaluate_criteria(metrics: pd.DataFrame, stress: pd.DataFrame) -> pd.DataFrame:
    aggregate = metrics.loc[metrics["period"].eq("2018-present")].set_index("strategy")
    filtered = aggregate.loc["filtered_short"]
    unconditional = aggregate.loc["unconditional_short"]
    applicable_windows = stress.loc[stress["applicable"] & ~stress["is_aggregate"]]
    aggregate_stress = stress.loc[stress["is_aggregate"]].iloc[0]
    score_passed = bool(
        filtered["return_to_drawdown"] > 0.0
        and np.isfinite(unconditional["return_to_drawdown"])
        and filtered["return_to_drawdown"] >= 1.5 * unconditional["return_to_drawdown"]
    )
    window_passed = bool(
        not applicable_windows.empty and applicable_windows["avoided_loss"].ge(0.60).all()
    )
    aggregate_passed = bool(
        aggregate_stress["applicable"] and aggregate_stress["avoided_loss"] >= 0.60
    )
    return pd.DataFrame(
        [
            {
                "criterion": "Positive filtered OOS total return",
                "value": filtered["total_return"],
                "threshold": "> 0",
                "passed": bool(filtered["total_return"] > 0.0),
            },
            {
                "criterion": "Filtered return/maxDD is at least 1.5x unconditional",
                "value": filtered["return_to_drawdown"],
                "threshold": f"> 0 and >= {1.5 * unconditional['return_to_drawdown']:.6f}",
                "passed": score_passed,
            },
            {
                "criterion": "At least 60% loss avoided in each applicable stress window",
                "value": applicable_windows["avoided_loss"].min() if not applicable_windows.empty else np.nan,
                "threshold": ">= 0.60",
                "passed": window_passed,
            },
            {
                "criterion": "At least 60% loss avoided across applicable stress windows",
                "value": aggregate_stress["avoided_loss"],
                "threshold": ">= 0.60",
                "passed": aggregate_passed,
            },
        ]
    )


def _compounded_return(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    return float((1.0 + returns.astype(float)).prod() - 1.0)


def _validate_daily_frame(daily: pd.DataFrame) -> None:
    required_columns = {
        "date",
        "underlying_return",
        "filtered_return",
        "unconditional_return",
        "flat_return",
        "harvest_signal",
        "filtered_position",
        "is_backwardation",
    }
    missing_columns = required_columns.difference(daily.columns)
    if missing_columns:
        raise ValueError(f"Daily proxy frame missing columns: {sorted(missing_columns)}")
    if daily.empty:
        raise ValueError("Daily proxy frame is empty.")
    dates = pd.to_datetime(daily["date"], errors="coerce").dt.normalize()
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError("Daily proxy dates must be valid, unique, and sorted ascending.")
    for column in ("underlying_return", "filtered_return", "unconditional_return", "flat_return"):
        values = pd.to_numeric(daily[column], errors="coerce")
        if values.isna().any() or not np.isfinite(values).all() or (values <= -1.0).any():
            raise ValueError(f"{column} must contain finite returns greater than -100%.")