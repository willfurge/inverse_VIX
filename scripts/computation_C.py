"""Equity overlay analysis using the frozen VIX term-structure signal.

The Sprint 3 strategy shorted vol and died on directional mean-reversion (-240%).
A long-equity book that goes to CASH on the signal does not pay that cost; going
flat does not lose when volatility reverts up. This asks a separate question:

    Used as a risk-off timer on a long-equity (SPY total-return) book, does this
    signal improve risk-adjusted returns OUT OF SAMPLE (2018+), NET of the return
    given up by sitting in cash, and does it beat simple alternatives?

Honesty rails (for a trading-desk audience):
  * Thresholds are FROZEN at their 2013-2017 calibration. Nothing is tuned here.
  * The de-risking framing is POST-HOC (formed after the short strategy failed).
    Disclosed. This is an OOS evaluation of a fixed rule, not a fresh fit.
  * rf = 0 on cash. This UNDERSTATES the overlays (they hold cash in high-rate
    stress years), so it biases against the thing being tested.
  * The decisive control is `naive_inversion_only`: one condition, zero tuned
    params. If the 3-condition signal doesn't beat it, the signal is redundant.
    * 2022 (a no-inversion bear) is reported as its own row, the attribution's
    predicted blind spot. If the overlay fails there, say so.

Usage:  python computation_c.py
Writes: results/overlay_*.{csv,parquet,md}
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import numpy as np
import pandas as pd

from vixharvest.signals.regimes import load_signal_parameters

DATA_DIR = REPO_ROOT / "data"
RESULTS_DIR = REPO_ROOT / "results"
PANEL_PATH = DATA_DIR / "processed" / "signal_panel.parquet"
SPY_FALLBACK = DATA_DIR / "raw" / "etp" / "SPY.csv"   # used only if yfinance unavailable

OOS_START = pd.Timestamp("2018-01-01")
VIX_LEVEL_THRESHOLD = 20.0     # conventional round number, NOT fit to data
TRADING_DAYS = 252
RF_DAILY = 0.0                 # conservative: understates cash-holding overlays


# --- data --------------------------------------------------------------------
def load_spy(*, fallback_path: Path = SPY_FALLBACK, allow_network: bool = True) -> pd.DataFrame:
    """SPY total-return proxy (auto_adjust folds in dividends). Fallback to CSV."""
    try:
        if not allow_network:
            raise RuntimeError("Network retrieval disabled.")
        import yfinance as yf
        raw = yf.Ticker("SPY").history(period="max", auto_adjust=True)
        raw.index = pd.to_datetime(raw.index).tz_localize(None)
        spy = raw[["Close"]].rename(columns={"Close": "spy_close"}).reset_index()
        spy = spy.rename(columns={"Date": "date", "index": "date"})
    except Exception as exc:  # noqa: BLE001
        if not fallback_path.exists():
            raise RuntimeError(
                f"SPY download failed ({exc}) and no fallback exists at {fallback_path}"
            ) from exc
        spy = pd.read_csv(fallback_path)
        spy["date"] = pd.to_datetime(spy["Date"]).dt.tz_localize(None)
        spy["spy_close"] = pd.to_numeric(spy["Close"], errors="coerce")
        spy = spy[["date", "spy_close"]]
    spy["date"] = pd.to_datetime(spy["date"]).dt.tz_localize(None)
    return spy.dropna().sort_values("date").reset_index(drop=True)


def assign_regime(frame: pd.DataFrame, parameters) -> np.ndarray:
    harvest = (frame["ratio_vix_vix3m"].lt(parameters.theta_1_ratio)
               & frame["slope_m1m2"].gt(parameters.theta_2_slope)
               & frame["ratio_vix_vix3m_delta5"].le(0))
    stress = frame["ratio_vix_vix3m"].ge(1.0) | frame["vix9d_vix"].ge(1.0)
    return np.select([harvest, stress], ["HARVEST", "STRESS"], default="NEUTRAL")


# --- exposure rules (each returns a 0/1 signal on date t; applied at t+1) -----
def build_exposures(df: pd.DataFrame) -> pd.DataFrame:
    reg = df["regime"]
    exp = pd.DataFrame(index=df.index)
    # benchmarks
    exp["buy_hold"] = 1.0
    exp["naive_vix_level"] = (df["vix"] < VIX_LEVEL_THRESHOLD).astype(float)
    exp["naive_inversion_only"] = (df["vix9d_vix"] < 1.0).astype(float)   # the control
    # signal overlays
    exp["overlay_stress_off"] = (reg != "STRESS").astype(float)           # de-risk on STRESS
    exp["overlay_harvest_only"] = (reg == "HARVEST").astype(float)        # in only in deep contango
    return exp


# --- metrics -----------------------------------------------------------------
def performance(returns: pd.Series, exposure_lag: pd.Series) -> dict:
    r = returns.dropna()
    n = len(r)
    cum = float((1 + r).prod() - 1)
    cagr = float((1 + r).prod() ** (TRADING_DAYS / n) - 1) if n else np.nan
    vol = float(r.std() * np.sqrt(TRADING_DAYS))
    downside = r[r < 0]
    dd_std = float(downside.std() * np.sqrt(TRADING_DAYS)) if len(downside) else np.nan
    sharpe = float((r.mean() - RF_DAILY) / r.std() * np.sqrt(TRADING_DAYS)) if r.std() else np.nan
    sortino = float((r.mean() - RF_DAILY) / downside.std() * np.sqrt(TRADING_DAYS)) if len(downside) and downside.std() else np.nan
    curve = (1 + r).cumprod()
    max_dd = float((curve / curve.cummax() - 1).min())
    calmar = float(cagr / abs(max_dd)) if max_dd else np.nan
    return {
        "total_return": cum, "cagr": cagr, "vol": vol, "sharpe": sharpe,
        "sortino": sortino, "max_drawdown": max_dd, "calmar": calmar,
        "pct_invested": float(exposure_lag.mean()),
    }


def capture_ratios(overlay_ret: pd.Series, mkt_ret: pd.Series) -> dict:
    up = mkt_ret > 0
    dn = mkt_ret < 0
    upcap = float(overlay_ret[up].sum() / mkt_ret[up].sum()) if mkt_ret[up].sum() else np.nan
    dncap = float(overlay_ret[dn].sum() / mkt_ret[dn].sum()) if mkt_ret[dn].sum() else np.nan
    return {"upside_capture": upcap, "downside_capture": dncap}


def run_block(df: pd.DataFrame, exp: pd.DataFrame, label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    mkt = df["spy_ret"]
    rows, series = [], {"date": df["date"]}
    for name in exp.columns:
        lag = exp[name].shift(1)                       # t+1 execution
        ret = lag * mkt + (1 - lag) * RF_DAILY
        series[name] = ret
        perf = performance(ret, lag)
        perf.update(capture_ratios(ret.dropna(), mkt.loc[ret.dropna().index]))
        perf = {"strategy": name, "period": label, **perf}
        rows.append(perf)
    return pd.DataFrame(rows), pd.DataFrame(series)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Evaluate the frozen signal as an equity de-risking overlay.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DATA_DIR,
        help="Directory containing the processed signal panel and optional SPY fallback.",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=RESULTS_DIR,
        help="Directory receiving overlay artifacts and the Markdown report.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "config" / "signals.yaml",
        help="Frozen signal configuration file.",
    )
    parser.add_argument(
        "--spy-source",
        type=Path,
        help="Local CSV fallback with Date and Close columns.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Disable yfinance and require the local SPY source.",
    )
    args = parser.parse_args(argv)
    args.results_dir.mkdir(parents=True, exist_ok=True)
    panel_path = args.data_dir / "processed" / "signal_panel.parquet"
    _require_files(
        (panel_path, args.config),
        "Run refresh_data.py and run_signal.py before running the overlay.",
    )
    panel = pd.read_parquet(panel_path).sort_values("date").copy()
    panel["date"] = pd.to_datetime(panel["date"]).dt.tz_localize(None)
    parameters = load_signal_parameters(args.config)
    panel["regime"] = assign_regime(panel, parameters)

    fallback_path = args.spy_source or args.data_dir / "raw" / "etp" / "SPY.csv"
    spy = load_spy(fallback_path=fallback_path, allow_network=not args.offline)
    df = panel.merge(spy, on="date", how="inner").sort_values("date").reset_index(drop=True)
    df["spy_ret"] = df["spy_close"].pct_change()
    df = df[df["date"] >= OOS_START].reset_index(drop=True)

    exp = build_exposures(df)

    full_metrics, full_series = run_block(df, exp, "2018-present")

    # 2022 test: the attribution's predicted blind spot (no-inversion bear)
    mask22 = (df["date"] >= "2022-01-01") & (df["date"] <= "2022-12-31")
    df22, exp22 = df.loc[mask22].reset_index(drop=True), exp.loc[mask22].reset_index(drop=True)
    metrics22, _ = run_block(df22, exp22, "2022-only")

    metrics = pd.concat([full_metrics, metrics22], ignore_index=True)
    metrics.to_csv(args.results_dir / "overlay_metrics.csv", index=False)
    full_series.to_parquet(args.results_dir / "overlay_daily_returns.parquet", index=False)

    _write_markdown(metrics, df, args.results_dir)

    show = ["strategy", "total_return", "cagr", "vol", "sharpe", "sortino",
            "max_drawdown", "calmar", "pct_invested", "downside_capture", "upside_capture"]
    pct = {"total_return", "cagr", "vol", "max_drawdown", "pct_invested",
           "downside_capture", "upside_capture"}
    for period in ("2018-present", "2022-only"):
        print(f"\n=== {period} ===")
        blk = metrics[metrics["period"] == period][show]
        print(blk.to_string(index=False, formatters={
            c: (("{:+.1%}".format if c not in ("pct_invested",) else "{:.0%}".format)
                if c in pct else "{:.2f}".format) for c in show if c != "strategy"}))
    print("\nDecisive reads:")
    print(" 1. Does overlay_stress_off beat buy_hold on Sortino AND Calmar (not just maxDD)?")
    print(" 2. Does it beat naive_inversion_only? If not, the 3-condition signal is redundant.")
    print(" 3. 2022: did any signal overlay protect, or is it blind there (attribution's prediction)?")
    print(" Downside_capture is the money metric: low = real protection; but read it next to")
    print(" upside_capture: cheap downside protection that also kills upside is worthless.")


def _md(frame: pd.DataFrame) -> str:
    cols = list(frame.columns)
    pct = {"total_return", "cagr", "vol", "max_drawdown", "pct_invested",
           "downside_capture", "upside_capture"}
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for row in frame.itertuples(index=False, name=None):
        cells = []
        for c, v in zip(cols, row):
            if pd.isna(v):
                cells.append("N/A")
            elif c in pct and isinstance(v, (float, np.floating)):
                cells.append(f"{v:+.1%}" if c != "pct_invested" else f"{v:.0%}")
            elif isinstance(v, (float, np.floating)):
                cells.append(f"{v:.2f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _write_markdown(metrics: pd.DataFrame, df: pd.DataFrame, results_dir: Path) -> None:
    cols = ["strategy", "total_return", "cagr", "vol", "sharpe", "sortino",
            "max_drawdown", "calmar", "pct_invested", "downside_capture", "upside_capture"]
    md = [
        "# Equity overlay using the VIX term-structure signal",
        "",
        f"Book: SPY total return. OOS {df['date'].min():%Y-%m-%d} to {df['date'].max():%Y-%m-%d}. "
        f"Thresholds frozen at 2013-2017. rf=0 on cash (conservative against overlays).",
        "**Post-hoc disclosure:** the de-risking framing was formed after the short "
        "strategy failed its gate; this is an OOS evaluation of a fixed rule, not a new fit.",
        "",
        "## Full period (2018-present)",
        _md(metrics[metrics["period"] == "2018-present"][cols]),
        "",
        "## 2022 test (no-inversion bear and the predicted blind spot)",
        _md(metrics[metrics["period"] == "2022-only"][cols]),
        "",
        "## How to read",
        "- The bar is not maxDD reduction alone (trivial: hold less, drop less). It is "
        "risk-adjusted return (Sortino, Calmar) NET of foregone upside, vs buy-and-hold.",
        "- `naive_inversion_only` is the control. The 3-condition signal must beat it or "
        "it adds nothing over a one-line rule.",
        "- `downside_capture` low is good ONLY if `upside_capture` stays high; read together.",
        "- `pct_invested` is the cost ledger: exposure given up to get the protection.",
        "",
    ]
    (results_dir / "overlay_summary.md").write_text("\n".join(md), encoding="utf-8")


def _require_files(paths: tuple[Path, ...], instruction: str) -> None:
    missing = [path for path in paths if not path.exists()]
    if missing:
        details = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(f"Missing required input files:\n{details}\n{instruction}")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from exc