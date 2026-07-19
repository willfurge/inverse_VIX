"""P&L attribution for the Sprint 3 filtered-short proxy (OOS 2018-present).

Answers, mechanically: how does a filter with a p=1.0000 carry edge (step 4b)
still lose ~47% out of sample? Decomposes realized daily short P&L into:

    1. CARRY vs. DIRECTIONAL   (arithmetic, exact per day: idx_ret = carry + directional)
    2. TRANSITION BUCKET       (harvest-continues / exit-to-neutral / exit-to-stress)
                                                         -> isolates the t+1 lag-day spike cost
  3. per YEAR, and the worst-N days (tail concentration)

Standalone by design: rebuilds the validated rolled index and regime exactly as
the gate did, so the result does not depend on an interactive session.

Usage:  python attribution.py
Writes: results/attribution_*.{csv,parquet,md}

NOTE: this is forensics on a NO-GO result. It quantifies why the strategy failed;
it does not reopen the gate. No parameter is chosen here.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import numpy as np
import pandas as pd
import yaml

from vixharvest.signals.regimes import SignalParameters, load_signal_parameters

OOS_START = pd.Timestamp("2018-01-01")
WORST_N = 15


# --- rolled short-term-futures excess-return index (validated construction) --
def build_stf_index(contracts: pd.DataFrame) -> pd.DataFrame:
    c = contracts.loc[contracts["expiry"] > contracts["date"]].copy()
    c["rk"] = c.groupby("date")["expiry"].rank("first").astype(int)
    c = c.sort_values(["contract", "date"])
    c["own_ret"] = c.groupby("contract")["settle"].pct_change()

    near = c.loc[c["rk"] == 1].set_index("date")
    nxt = c.loc[c["rk"] == 2].set_index("date")
    d = pd.DataFrame(index=near.index.sort_values())
    d["expiry"], d["near_ret"], d["next_ret"] = near["expiry"], near["own_ret"], nxt["own_ret"]

    settles = np.sort(d["expiry"].unique())
    prev = {settles[i]: settles[i - 1] for i in range(1, len(settles))}
    d["p_end"] = d["expiry"]
    d["p_start"] = d["p_end"].map(prev)
    d = d.dropna(subset=["p_start"])
    bd = lambda a, b: np.busday_count(a.values.astype("datetime64[D]"), b.values.astype("datetime64[D]"))
    d["w_near"] = (bd(d.index.to_series(), d["p_end"]) / bd(d["p_start"], d["p_end"])).clip(0, 1)
    d["idx_ret"] = d["w_near"].shift(1) * d["near_ret"] + (1 - d["w_near"].shift(1)) * d["next_ret"]
    d["stf_index"] = (1 + d["idx_ret"].fillna(0)).cumprod()
    return d[["stf_index", "idx_ret"]].reset_index().rename(columns={"index": "date"})


def assign_regime(frame: pd.DataFrame, parameters: SignalParameters) -> np.ndarray:
    harvest = (frame["ratio_vix_vix3m"].lt(parameters.theta_1_ratio)
               & frame["slope_m1m2"].gt(parameters.theta_2_slope)
               & frame["ratio_vix_vix3m_delta5"].le(0))
    stress = frame["ratio_vix_vix3m"].ge(1.0) | frame["vix9d_vix"].ge(1.0)
    return np.select([harvest, stress], ["HARVEST", "STRESS"], default="NEUTRAL")


def build_daily(
    panel: pd.DataFrame,
    contracts: pd.DataFrame,
    parameters: SignalParameters,
) -> pd.DataFrame:
    panel = panel.sort_values("date").copy()
    panel["date"] = pd.to_datetime(panel["date"]).dt.tz_localize(None)
    stf = build_stf_index(contracts)
    stf["date"] = pd.to_datetime(stf["date"]).dt.tz_localize(None)

    df = panel.merge(stf, on="date", how="inner").sort_values("date").reset_index(drop=True)
    df["regime"] = assign_regime(df, parameters)

    # execution: signal from date t-1 close activates on date t (t+1 relative to signal)
    df["position_regime"] = df["regime"].shift(1)          # regime that set today's position
    df["active"] = df["position_regime"].eq("HARVEST")     # short 1 unit of the index when active

    # returns
    df["idx_ret_daily"] = df["stf_index"].pct_change()
    df["vx30_ret_daily"] = df["vx30"].pct_change()

    # mechanical (beta=1) carry / directional split of the INDEX daily return:
    #   the rolled index books roll P&L; vx30 (constant maturity) does not.
    #   carry := idx_ret - vx30_ret ;  directional := vx30_ret ;  (exact, additive)
    df["directional_daily"] = df["vx30_ret_daily"]
    df["carry_daily"] = df["idx_ret_daily"] - df["vx30_ret_daily"]

    # short P&L contributions (1 unit short => negate). Zero on flat days.
    df["short_pnl"] = np.where(df["active"], -df["idx_ret_daily"], 0.0)
    df["short_carry"] = np.where(df["active"], -df["carry_daily"], 0.0)
    df["short_directional"] = np.where(df["active"], -df["directional_daily"], 0.0)

    # transition bucket for each ACTIVE day: where is today's regime heading?
    #   we are short today because yesterday was HARVEST; today's regime tells the story
    bucket = np.where(df["regime"].eq("HARVEST"), "harvest_continues",
             np.where(df["regime"].eq("NEUTRAL"), "exit_to_neutral", "exit_to_stress"))
    df["bucket"] = np.where(df["active"], bucket, "flat")

    df["year"] = df["date"].dt.year
    return df


# --- decompositions ----------------------------------------------------------
def reconcile(df_active: pd.DataFrame) -> dict:
    """Arithmetic sum vs geometric total; the gap is the compounding interaction."""
    arith = df_active["short_pnl"].sum()
    arith_carry = df_active["short_carry"].sum()
    arith_dir = df_active["short_directional"].sum()
    geo = float(np.prod(1.0 + df_active["short_pnl"].to_numpy()) - 1.0)
    return {
        "geometric_total_return": geo,
        "arithmetic_total": arith,
        "arithmetic_carry": arith_carry,
        "arithmetic_directional": arith_dir,
        "carry_plus_dir_check": arith_carry + arith_dir,   # == arith by construction
        "compounding_interaction": geo - arith,
    }


def regression_robustness(
    df: pd.DataFrame,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
) -> dict:
    """Refit the directional beta on TRAIN daily returns (not =1), reattribute OOS.
    Confirms the carry/directional split isn't an artifact of assuming beta=1."""
    tr = df[(df["date"] >= train_start) & (df["date"] <= train_end)]
    tr = tr.dropna(subset=["idx_ret_daily", "vx30_ret_daily"])
    X = np.c_[np.ones(len(tr)), tr["vx30_ret_daily"].to_numpy()]
    beta, *_ = np.linalg.lstsq(X, tr["idx_ret_daily"].to_numpy(), rcond=None)
    b = beta[1]

    oos = df[(df["date"] >= OOS_START) & df["active"]].copy()
    dir_reg = b * oos["vx30_ret_daily"]
    carry_reg = oos["idx_ret_daily"] - dir_reg
    return {
        "train_daily_beta": float(b),
        "oos_short_carry_beta_fit": float((-carry_reg).sum()),
        "oos_short_directional_beta_fit": float((-dir_reg).sum()),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Attribute the frozen Sprint 3 filtered-short result.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=REPO_ROOT / "data",
        help="Directory containing the processed panel and VX contracts.",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=REPO_ROOT / "results",
        help="Directory receiving attribution artifacts and the Markdown report.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "config" / "signals.yaml",
        help="Frozen signal configuration file.",
    )
    args = parser.parse_args(argv)
    args.results_dir.mkdir(parents=True, exist_ok=True)
    panel_path = args.data_dir / "processed" / "signal_panel.parquet"
    contracts_path = args.data_dir / "interim" / "vx_contracts.parquet"
    _require_files(
        (panel_path, contracts_path, args.config),
        "Run refresh_data.py and run_signal.py before running attribution.",
    )
    panel = pd.read_parquet(panel_path)
    contracts = pd.read_parquet(contracts_path)
    parameters = load_signal_parameters(args.config)
    with args.config.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    train_start = pd.Timestamp(config["fit_window"]["start"])
    train_end = pd.Timestamp(config["fit_window"]["end"])

    df = build_daily(panel, contracts, parameters)
    oos = df[df["date"] >= OOS_START].copy()
    oos_active = oos[oos["active"]].dropna(subset=["short_pnl"]).copy()

    # 1) headline reconciliation ---------------------------------------------
    rec = reconcile(oos_active)
    reg = regression_robustness(df, train_start, train_end)

    # 2) bucket attribution ---------------------------------------------------
    by_bucket = (oos_active.groupby("bucket")
                 .agg(days=("short_pnl", "size"),
                      total_short_pnl=("short_pnl", "sum"),
                      total_carry=("short_carry", "sum"),
                      total_directional=("short_directional", "sum"),
                      mean_short_pnl=("short_pnl", "mean"),
                      worst_day=("short_pnl", "min"))
                 .reindex(["harvest_continues", "exit_to_neutral", "exit_to_stress"])
                 .reset_index())

    # 3) per-year attribution -------------------------------------------------
    by_year = (oos_active.groupby("year")
               .agg(active_days=("short_pnl", "size"),
                    short_pnl_arith=("short_pnl", "sum"),
                    carry=("short_carry", "sum"),
                    directional=("short_directional", "sum"),
                    stress_exit_days=("bucket", lambda s: int((s == "exit_to_stress").sum())),
                    stress_exit_pnl=("short_pnl", lambda s: float(s[oos_active.loc[s.index, "bucket"]
                                                                    == "exit_to_stress"].sum())))
               .reset_index())

    # 4) worst days (tail concentration) -------------------------------------
    worst = (oos_active.nsmallest(WORST_N, "short_pnl")
             [["date", "regime", "position_regime", "bucket",
               "idx_ret_daily", "carry_daily", "directional_daily", "short_pnl"]]
             .reset_index(drop=True))
    total_loss = oos_active.loc[oos_active["short_pnl"] < 0, "short_pnl"].sum()
    worst_share = worst["short_pnl"].sum() / total_loss if total_loss else np.nan

    # 5) cumulative component paths (for the paper's key chart) ---------------
    paths = oos.copy()
    paths["cum_short_pnl"] = (1 + paths["short_pnl"]).cumprod() - 1
    paths["cum_carry_arith"] = paths["short_carry"].cumsum()
    paths["cum_directional_arith"] = paths["short_directional"].cumsum()
    paths = paths[["date", "active", "bucket", "short_pnl", "short_carry",
                   "short_directional", "cum_short_pnl", "cum_carry_arith",
                   "cum_directional_arith"]]

    # --- write artifacts -----------------------------------------------------
    oos_active.to_parquet(args.results_dir / "attribution_daily.parquet", index=False)
    paths.to_parquet(args.results_dir / "attribution_paths.parquet", index=False)
    by_bucket.to_csv(args.results_dir / "attribution_by_bucket.csv", index=False)
    by_year.to_csv(args.results_dir / "attribution_by_year.csv", index=False)
    worst.to_csv(args.results_dir / "attribution_worst_days.csv", index=False)

    _write_markdown(rec, reg, by_bucket, by_year, worst, worst_share, args.results_dir)

    # --- console summary -----------------------------------------------------
    p = lambda x: f"{x:+.2%}"
    print("=== HEADLINE RECONCILIATION (OOS filtered short) ===")
    print(f"geometric total          {p(rec['geometric_total_return'])}")
    print(f"  = carry (arith)        {p(rec['arithmetic_carry'])}")
    print(f"  + directional (arith)  {p(rec['arithmetic_directional'])}")
    print(f"  + compounding interaction {p(rec['compounding_interaction'])}")
    print(f"train daily beta (idx~vx30): {reg['train_daily_beta']:.3f}  "
          f"(carry/dir split robust if ~1)")
    print("\n=== BUCKET ATTRIBUTION ===")
    print(by_bucket.to_string(index=False,
          formatters={c: "{:+.4f}".format for c in
          ["total_short_pnl", "total_carry", "total_directional", "mean_short_pnl", "worst_day"]}))
    print(f"\nWorst {WORST_N} days account for {worst_share:.0%} of all losing-day P&L.")
    print("Read: if carry is strongly POSITIVE and directional strongly NEGATIVE,")
    print("the edge is real but not linearly harvestable; the short cannot take")
    print("delivery of carry without eating the directional spike.")


def _require_files(paths: tuple[Path, ...], instruction: str) -> None:
    missing = [path for path in paths if not path.exists()]
    if missing:
        details = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(f"Missing required input files:\n{details}\n{instruction}")


def _md_table(frame: pd.DataFrame, pct=(), dec=()) -> str:
    cols = list(frame.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for row in frame.itertuples(index=False, name=None):
        cells = []
        for col, v in zip(cols, row):
            if pd.isna(v):
                cells.append("N/A")
            elif isinstance(v, pd.Timestamp):
                cells.append(v.strftime("%Y-%m-%d"))
            elif col in pct and isinstance(v, (float, np.floating)):
                cells.append(f"{v:+.2%}")
            elif col in dec and isinstance(v, (float, np.floating)):
                cells.append(f"{v:.4f}")
            elif isinstance(v, (float, np.floating)):
                cells.append(f"{v:+.4f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _write_markdown(rec, reg, by_bucket, by_year, worst, worst_share, results_dir: Path) -> None:
    pctcols = {"total_short_pnl", "total_carry", "total_directional", "mean_short_pnl",
               "worst_day", "short_pnl_arith", "carry", "directional", "stress_exit_pnl",
               "idx_ret_daily", "carry_daily", "directional_daily", "short_pnl"}
    md = [
        "# Attribution - Sprint 3 filtered short (OOS 2018-present)",
        "",
        "Forensics on a NO-GO result. Decomposes realized daily short P&L into carry vs",
        "directional (mechanical beta=1: `carry = idx_ret - vx30_ret`) and by transition",
        "bucket. No parameter is chosen here.",
        "",
        "## Headline reconciliation",
        f"- Geometric total return: **{rec['geometric_total_return']:+.2%}**",
        f"- Arithmetic carry contribution (short): **{rec['arithmetic_carry']:+.2%}**",
        f"- Arithmetic directional contribution (short): **{rec['arithmetic_directional']:+.2%}**",
        f"- Compounding interaction (geo - arith): {rec['compounding_interaction']:+.2%}",
        f"- Robustness: train daily beta(idx~vx30) = {reg['train_daily_beta']:.3f}; "
        f"beta-fit carry {reg['oos_short_carry_beta_fit']:+.2%}, "
        f"directional {reg['oos_short_directional_beta_fit']:+.2%}",
        "",
        "The carry contribution is the p=1.0000 edge, realized. The directional",
        "contribution is the mean-reversion/spike cost the linear short cannot avoid.",
        "",
        "## By transition bucket",
        _md_table(by_bucket, pct=pctcols),
        "",
        "`exit_to_stress` is the t+1 lag-day cost: short into the flag, out next session.",
        "",
        "## By year",
        _md_table(by_year, pct=pctcols),
        "",
        f"## Worst {len(worst)} days ({worst_share:.0%} of all losing-day P&L)",
        _md_table(worst, pct=pctcols),
        "",
    ]
    (results_dir / "attribution_summary.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from exc