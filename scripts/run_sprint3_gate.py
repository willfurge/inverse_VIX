"""Run the frozen-parameter Sprint 3 walk-forward proxy gate.

Usage:
    python scripts/run_sprint3_gate.py
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import numpy as np
import pandas as pd
import yaml

from vixharvest.backtest.gate import evaluate_sprint3_gate
from vixharvest.backtest.proxy import run_proxy_backtest
from vixharvest.signals.regimes import load_signal_parameters


OOS_START = pd.Timestamp("2018-01-01")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the frozen Sprint 3 out-of-sample proxy gate.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=REPO_ROOT / "data",
        help="Directory containing the processed panel, contracts, and VXX input.",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=REPO_ROOT / "results",
        help="Directory receiving artifacts and the Markdown report.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "config" / "signals.yaml",
        help="Frozen signal configuration file.",
    )
    args = parser.parse_args(argv)

    panel_path = args.data_dir / "processed" / "signal_panel.parquet"
    contracts_path = args.data_dir / "interim" / "vx_contracts.parquet"
    vxx_path = args.data_dir / "raw" / "etp" / "VXX_yfinance_auto_adjusted.csv"
    _require_files(
        (panel_path, contracts_path, vxx_path, args.config),
        "Run refresh_data.py and run_signal.py before running the gate.",
    )
    config = _load_config(args.config)
    fit_start = pd.Timestamp(config["fit_window"]["start"])
    fit_end = pd.Timestamp(config["fit_window"]["end"])
    parameters = load_signal_parameters(args.config)
    panel = pd.read_parquet(panel_path)
    contracts = pd.read_parquet(contracts_path)
    daily = run_proxy_backtest(panel, contracts, parameters=parameters)
    daily = daily.sort_values("date", ignore_index=True)
    proxy_validation = _validate_stf_against_vxx(daily, vxx_path)
    if proxy_validation["log_level_correlation"] <= 0.95:
        raise RuntimeError(
            "STF/VXX construction validation failed: log-level correlation must exceed 0.95."
        )

    evaluation = evaluate_sprint3_gate(
        daily,
        parameters,
        fit_start=fit_start,
        oos_start=OOS_START,
    )
    oos_daily = daily.loc[daily["date"] >= OOS_START].copy()
    _write_artifacts(
        oos_daily=oos_daily,
        periods=evaluation.periods,
        metrics=evaluation.metrics,
        stress_windows=evaluation.stress_windows,
        backwardation_exposure=evaluation.backwardation_exposure,
        criteria=evaluation.criteria,
        verdict=evaluation.verdict,
        parameters=parameters,
        fit_start=fit_start,
        fit_end=fit_end,
        proxy_validation=proxy_validation,
        results_dir=args.results_dir,
        input_files=(panel_path, contracts_path, vxx_path, args.config),
    )
    print(f"Sprint 3 verdict: {evaluation.verdict}")
    print(f"Report: {args.results_dir / 'sprint3_gate.md'}")


def _require_files(paths: tuple[Path, ...], instruction: str) -> None:
    missing = [path for path in paths if not path.exists()]
    if missing:
        details = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(f"Missing required input files:\n{details}\n{instruction}")


def _load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    if not isinstance(config, dict) or not config.get("fit_window", {}).get("start"):
        raise ValueError("signals.yaml must include a frozen fit_window.start.")
    return config


def _validate_stf_against_vxx(daily: pd.DataFrame, vxx_path: Path) -> dict[str, object]:
    if not vxx_path.exists():
        raise FileNotFoundError(f"Missing split-adjusted VXX source: {vxx_path}")
    vxx = pd.read_csv(vxx_path)
    required_columns = {"Date", "Close"}
    missing_columns = required_columns.difference(vxx.columns)
    if missing_columns:
        raise ValueError(f"VXX source missing columns: {sorted(missing_columns)}")
    vxx["date"] = pd.to_datetime(vxx["Date"], utc=True, errors="coerce").dt.tz_convert(None).dt.normalize()
    vxx["vxx_close"] = pd.to_numeric(vxx["Close"], errors="coerce")
    vxx = vxx.loc[:, ["date", "vxx_close"]].dropna().drop_duplicates("date")
    both = daily.loc[:, ["date", "stf_index"]].merge(
        vxx,
        on="date",
        how="inner",
        validate="one_to_one",
    )
    both = both.loc[both["date"] >= "2018-01-25"].copy()
    if len(both) < 2:
        raise ValueError("STF/VXX validation has fewer than two overlapping Series B dates.")
    both["stf_norm"] = both["stf_index"] / both["stf_index"].iloc[0]
    both["vxx_norm"] = both["vxx_close"] / both["vxx_close"].iloc[0]
    return {
        "start": both["date"].min(),
        "end": both["date"].max(),
        "rows": len(both),
        "stf_total_return": float(both["stf_norm"].iloc[-1] - 1.0),
        "vxx_total_return": float(both["vxx_norm"].iloc[-1] - 1.0),
        "log_level_correlation": float(
            np.corrcoef(np.log(both["stf_norm"]), np.log(both["vxx_norm"]))[0, 1]
        ),
    }


def _write_artifacts(
    *,
    oos_daily: pd.DataFrame,
    periods: pd.DataFrame,
    metrics: pd.DataFrame,
    stress_windows: pd.DataFrame,
    backwardation_exposure: pd.DataFrame,
    criteria: pd.DataFrame,
    verdict: str,
    parameters,
    fit_start: pd.Timestamp,
    fit_end: pd.Timestamp,
    proxy_validation: dict[str, object],
    results_dir: Path,
    input_files: tuple[Path, ...],
) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    oos_daily.to_parquet(results_dir / "sprint3_oos_daily.parquet", index=False)
    periods.to_csv(results_dir / "sprint3_walk_forward_periods.csv", index=False)
    metrics.to_csv(results_dir / "sprint3_oos_metrics.csv", index=False)
    stress_windows.to_csv(results_dir / "sprint3_stress_windows.csv", index=False)
    backwardation_exposure.to_csv(results_dir / "sprint3_backwardation_exposure.csv", index=False)
    criteria.to_csv(results_dir / "sprint3_gate_criteria.csv", index=False)

    report = _build_report(
        oos_daily=oos_daily,
        periods=periods,
        metrics=metrics,
        stress_windows=stress_windows,
        backwardation_exposure=backwardation_exposure,
        criteria=criteria,
        verdict=verdict,
        parameters=parameters,
        fit_start=fit_start,
        fit_end=fit_end,
        proxy_validation=proxy_validation,
        input_files=input_files,
    )
    (results_dir / "sprint3_gate.md").write_text(report, encoding="utf-8")


def _build_report(
    *,
    oos_daily: pd.DataFrame,
    periods: pd.DataFrame,
    metrics: pd.DataFrame,
    stress_windows: pd.DataFrame,
    backwardation_exposure: pd.DataFrame,
    criteria: pd.DataFrame,
    verdict: str,
    parameters,
    fit_start: pd.Timestamp,
    fit_end: pd.Timestamp,
    proxy_validation: dict[str, object],
    input_files: tuple[Path, ...],
) -> str:
    hashes = pd.DataFrame(
        [
            {"file": _display_path(path), "sha256": _sha256(path)}
            for path in input_files
        ]
    )
    frozen = pd.DataFrame(
        [
            {
                "fit_start": fit_start,
                "fit_end": fit_end,
                "theta_1_ratio": parameters.theta_1_ratio,
                "theta_2_slope": parameters.theta_2_slope,
                "momentum_lookback_days": parameters.momentum_lookback_days,
                "regime_precedence": "STRESS before HARVEST",
            }
        ]
    )
    scope = pd.DataFrame(
        [
            {
                "item": "available in-sample window",
                "value": f"{fit_start:%Y-%m-%d} to {fit_end:%Y-%m-%d}",
            },
            {
                "item": "out-of-sample window",
                "value": f"{oos_daily['date'].min():%Y-%m-%d} to {oos_daily['date'].max():%Y-%m-%d}",
            },
            {"item": "OOS observations", "value": len(oos_daily)},
            {"item": "execution", "value": "date-t close signal activates on next observed trading date"},
            {"item": "proxy", "value": "rolled STF index; filtered, unconditional short, and flat"},
            {"item": "2026", "value": "included as partial-year YTD in the formal aggregate"},
        ]
    )
    proxy = pd.DataFrame([proxy_validation])
    criteria_display = criteria.copy()
    criteria_display["value"] = [
        (
            f"{value:.4f}"
            if "return/maxDD" in criterion
            else (f"{value:.2%}" if pd.notna(value) else "N/A")
        )
        for criterion, value in zip(criteria_display["criterion"], criteria_display["value"], strict=True)
    ]
    failures = criteria.loc[~criteria["passed"], "criterion"].tolist()
    verdict_text = (
        "All precommitted Sprint 3 requirements passed. This unlocks Sprint 4 data acquisition only; it does not authorize live trading."
        if verdict == "GO"
        else "Precommitted requirements failed: "
        + "; ".join(failures)
        + ". The project remains research-only. No additional threshold search is permitted for this gate."
    )
    return "\n".join(
        [
            f"# Sprint 3 Gate: {verdict}",
            "",
            "This report is generated by `scripts/run_sprint3_gate.py` from persisted input and result artifacts.",
            "",
            "## Scope",
            _markdown_table(scope),
            "",
            "The original plan specified a 2007-2017 fit; public CFE contract coverage begins in 2013, so the frozen fit window is 2013-2017. No OOS data was used to select the parameters below.",
            "",
            "## Frozen Signal Contract",
            _markdown_table(frozen, percent_columns={"theta_2_slope"}),
            "",
            "HARVEST requires `ratio_vix_vix3m < theta_1`, `slope_m1m2 > theta_2`, and a non-rising five-day ratio delta. STRESS takes precedence whenever `ratio_vix_vix3m >= 1.0` or `vix9d_vix >= 1.0`.",
            "",
            "## STF Proxy Validation",
            _markdown_table(
                proxy,
                percent_columns={"stf_total_return", "vxx_total_return"},
                decimal_columns={"log_level_correlation"},
            ),
            "",
            "The rolled STF proxy must exceed 0.95 log-level correlation with split-adjusted VXX before the gate is evaluated.",
            "",
            "## Walk-Forward Periods",
            _markdown_table(periods, percent_columns={"theta_2_slope"}),
            "",
            "Parameters are frozen for every annual OOS slice. Expanding historical windows are audit provenance, not annual re-optimization.",
            "",
            "## OOS Performance",
            _markdown_table(
                metrics,
                percent_columns={"total_return", "annualized_return", "max_drawdown"},
                decimal_columns={"return_to_drawdown"},
            ),
            "",
            "## Stress-Window Loss Avoidance",
            _markdown_table(
                stress_windows,
                percent_columns={
                    "filtered_return",
                    "unconditional_return",
                    "filtered_loss",
                    "unconditional_loss",
                    "avoided_loss",
                },
            ),
            "",
            "A window is applicable only when unconditional short suffered a loss. The 60% hurdle applies to every applicable named window and to the aggregate row.",
            "",
            "## Backwardation While Active",
            _markdown_table(
                backwardation_exposure,
                percent_columns={"underlying_return", "filtered_short_return"},
            ),
            "",
            "The first row is the deployed failure measure: lagged filtered exposure while `slope_m1m2 <= 0`. The second is the same-date signal diagnostic.",
            "",
            "## Gate Checklist",
            _markdown_table(criteria_display),
            "",
            "## Verdict",
            f"**{verdict}**. {verdict_text}",
            "",
            "## Input Hashes",
            _markdown_table(hashes),
            "",
        ]
    )


def _markdown_table(
    frame: pd.DataFrame,
    *,
    percent_columns: set[str] | None = None,
    decimal_columns: set[str] | None = None,
) -> str:
    percent_columns = percent_columns or set()
    decimal_columns = decimal_columns or set()
    columns = list(frame.columns)
    rows = []
    for values in frame.itertuples(index=False, name=None):
        rows.append(
            [
                _format_value(value, column, percent_columns, decimal_columns)
                for column, value in zip(columns, values, strict=True)
            ]
        )
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def _format_value(
    value: object,
    column: str,
    percent_columns: set[str],
    decimal_columns: set[str],
) -> str:
    if pd.isna(value):
        return "N/A"
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if column in percent_columns and isinstance(value, (float, np.floating)):
        return f"{value:.2%}"
    if column in decimal_columns and isinstance(value, (float, np.floating)):
        return f"{value:.4f}"
    if isinstance(value, (float, np.floating)):
        return f"{value:.6f}"
    return str(value).replace("|", "\\|")


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from exc
