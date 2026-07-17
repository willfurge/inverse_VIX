# PLAN.md — Build Plan: Empty Directory → Live Trading

> Companion to `thesis.md`. Execute in order. Each sprint ends with an explicit **exit criterion**; do not start the next sprint until it's met. Sprint 3 is a hard **GO/NO-GO gate** — the paid options data and everything after it are conditional on passing it.
>
> Time estimates assume evenings/weekends alongside a full-time job. Adjust freely; the *order* is what matters.

---

## Sprint 0 — Repo, Environment, Skeleton (1 evening)

### 0.1 Create the repo

```bash
mkdir vix-harvest && cd vix-harvest
git init
```

### 0.2 Filetree (create now, fill later)

```
vix-harvest/
├── thesis.md                  # from this session — agent context, source of truth
├── plan.md                    # this file
├── README.md                  # one-paragraph pointer to thesis.md
├── pyproject.toml
├── .gitignore                 # data/, .venv/, __pycache__, *.parquet outside data contract
├── config/
│   ├── data_sources.yaml      # every URL/endpoint, versioned; nothing hardcoded in code
│   ├── signals.yaml           # thresholds θ1..θn with fit-window metadata
│   └── risk.yaml              # position sizing, limits from thesis.md §8
├── data/                      # gitignored; regenerable from ETL
│   ├── raw/                   # exactly as downloaded, never modified
│   │   ├── cfe_vx/            # one CSV per futures contract
│   │   ├── indices/           # VIX, VIX3M, VIX9D history CSVs
│   │   └── etp/               # VXX/UVXY price downloads
│   ├── interim/               # parsed, typed, validated parquet
│   └── processed/             # analysis-ready tables (curve panel, signal panel)
├── src/vixharvest/
│   ├── __init__.py
│   ├── etl/
│   │   ├── cfe_futures.py     # download + parse per-contract VX CSVs
│   │   ├── cboe_indices.py    # VIX/VIX3M/VIX9D
│   │   ├── etp_prices.py      # VXX/UVXY adjusted prices
│   │   └── validate.py        # ingest-time checks (thesis.md §9)
│   ├── curve/
│   │   ├── calendar.py        # expiry calendar built from data
│   │   ├── constant_maturity.py  # VX30 interpolation
│   │   └── features.py        # basis, slope, roll yield, ratios
│   ├── signals/
│   │   └── regimes.py         # HARVEST/NEUTRAL/STRESS/POST-SPIKE state machine
│   ├── backtest/
│   │   ├── engine.py          # event-driven, date-t signal → t+1 execution
│   │   ├── proxy.py           # Sprint 3: underlying-proxy backtest
│   │   └── options.py         # Sprint 4-5: spread modeling
│   ├── reporting/
│   │   └── report.py          # expectancy, drawdown, stress windows
│   └── alerts/
│       └── daily.py           # Sprint 6: EOD signal run + notification
├── notebooks/                 # exploration only; nothing load-bearing lives here
├── tests/
└── scripts/
    ├── refresh_data.py
    └── run_signal.py
```

### 0.3 Environment

```bash
python -m venv .venv && source .venv/bin/activate
```

`pyproject.toml` dependencies (lean; add only when needed):

- `pandas` (or `polars` if preferred — pick one, don't mix), `numpy`
- `requests`, `pyyaml`
- `pyarrow` (parquet)
- `duckdb` (optional but excellent for the processed layer / ad-hoc queries)
- `matplotlib` (reporting)
- `pytest`
- Later (Sprint 4+): `scipy` (BS pricing), and the options-data vendor client if any
- Later (Sprint 6): whatever notification channel you choose (e.g., `smtplib` stdlib for email, or a Telegram bot lib)

**Exit criterion:** repo exists, `pytest` runs (zero tests, passing), `thesis.md` committed at root.

---

## Sprint 1 — Data Acquisition & ETL (2–4 evenings)

### 1.1 Data inventory

| Dataset | Source | Cost | Coverage needed |
|---|---|---|---|
| VIX futures, per-contract daily OHLC + settle | CBOE CFE historical data page, symbol `VX+VXT`, one CSV per contract month | Free | 2005 → present (2004 exists but thin) |
| Daily VX settlements (cross-check) | CBOE VIX Settlement Series archive | Free | Recent years, for validation |
| VIX index history | `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv` | Free | 1990 → present |
| VIX3M history | same CDN pattern, `VIX3M_History.csv` | Free | 2002ish → present |
| VIX9D history | same CDN pattern, `VIX9D_History.csv` | Free | 2011ish → present |
| VXX/UVXY split-adjusted daily prices | yfinance (interim) → validate against a second source | Free | VXX 2009 → present |
| VXX EOD option chains | ORATS / Cboe DataShop / firstratedata | **Paid — DO NOT BUY until Sprint 3 passes** | ≥ 2016 → present ideally |
| (Optional) SPX daily closes | FRED or yfinance | Free | Sanity/correlation checks |

Put every URL in `config/data_sources.yaml` with a `last_verified` date. CBOE reorganizes its site; when a fetch 404s, the fix is a config edit plus a verification note, not a code change.

### 1.2 ETL tasks, in order

1. **`cboe_indices.py`** — download the three index CSVs, parse to typed frames (DATE, OPEN, HIGH, LOW, CLOSE), write `data/interim/indices.parquet`. Validation: monotonic dates, no duplicate dates, gaps only on known market holidays, VIX pre-2004-06 OHLC-equal quirk tolerated.
2. **`cfe_futures.py`** — enumerate and download per-contract VX CSVs. Parse each: contract symbol → expiry mapping, handle the expired-contract final row (zero OHLC, settle-only). Concatenate to a long table: `(date, contract, expiry, open, high, low, close, settle, volume, oi)`. Write `data/interim/vx_contracts.parquet`. Validation: every trading date should have ≥ 2 live contracts from 2007 onward; settle > 0; expiry dates all Wednesdays or documented holiday shifts.
3. **`etp_prices.py`** — pull VXX (and UVXY) adjusted closes. **Immediately run the split-sanity check:** day-over-day returns should never exceed ±60% outside the known stress windows; a +300% "return" means an unadjusted split leaked through. Cross-check 5 random dates against a second source manually. Document VXX→VXXB→VXX 2019 transition and the 2022 creation-halt window in a `data/ANOMALIES.md`.
4. **`validate.py`** — every loader calls a shared validation pass; failures raise, never warn-and-continue.
5. **`scripts/refresh_data.py`** — one command re-pulls everything incrementally.

**Exit criterion:** `refresh_data.py` runs clean from an empty `data/` directory; all validations pass; anomalies documented.

---

## Sprint 2 — Curve Construction & Feature Panel (2–3 evenings)

1. **`calendar.py`** — build the expiry calendar *from the contract data itself* (last settle-only row per contract), cross-checked against CBOE's published calendar for recent years. Store as a table.
2. **`constant_maturity.py`** — for each date: identify M1, M2 (nearest and next expiries with expiry > date), compute calendar-day weights, produce `vx30`. Handle roll dates (day M1 expires: M2 becomes M1). Unit-test the interpolation against hand-computed examples including a roll week and a holiday-shifted expiry.
3. **`features.py`** — compute the full feature set from thesis.md §4.1 into one daily panel: `data/processed/signal_panel.parquet`. Columns: date, vix, vix3m, vix9d, m1, m2, expiries, vx30, basis_m1, basis_m1_pct, slope_m1m2, roll_yield_daily, ratio_vix_vix3m, vix9d_vix, plus 5-day deltas of the ratios.
4. **Visual QA notebook** — plot vx30 vs. VIX 2007–present; shade backwardation periods; confirm the four stress windows light up. Plot slope_m1m2 histogram — should show the ~80/20 contango/backwardation split. If it doesn't, there's a bug; do not rationalize.

**Exit criterion:** signal panel builds end-to-end from raw data; stress windows visually confirmed; contango frequency ≈ 80% ± a few points.

---

## Sprint 3 — Signal Research: THE GO/NO-GO GATE (1–2 weeks)

**Question this sprint answers:** *does the regime filter time the ETP decay well enough to matter, before any options complexity?*

### 3.1 The proxy backtest

You cannot cheaply get 15 years of option chains, and you shouldn't pay for them until the signal earns it. So test the signal on the **underlying proxy**: a hypothetical daily-marked short position in the constant-maturity VX30 (equivalently, short VXX total-return without borrow costs). This isn't the trade you'll put on — it's the *cleanest measurement of the signal itself*.

- Position: short 1 unit of vx30 when regime = HARVEST (later: test POST-SPIKE separately), flat otherwise.
- Returns: daily change in vx30, sign-flipped, plus the roll accrual (this falls out naturally if you compute vx30 returns correctly from the interpolated series — verify against VXX's actual returns as a sanity check; correlation should exceed ~0.95).
- Execution lag: signal from date-t settles → position change at t+1. Enforced by the engine, not by convention.

### 3.2 Protocol (fixed before running anything)

1. **Split:** in-sample 2007–2017, out-of-sample 2018–present. (Deliberately puts all four stress windows and the post-Dew-Becker-decay era out of sample. Harsh on purpose.)
2. **Fit:** grid over θ₁ (ratio threshold), θ₂ (slope threshold), momentum lookback — in-sample only. Keep the grid coarse (3–5 values per parameter). Record everything.
3. **Walk-forward:** refit on expanding window, test on each subsequent year, 2018–2025.
4. **Evaluate out-of-sample:** filtered short vs. (a) flat, (b) unconditional short. Metrics: annualized return, max drawdown, worst stress-window P&L, and — the key one — **return during backwardation days while the filter said HARVEST** (this measures filter failure directly).

### 3.3 GO/NO-GO criteria (pre-committed, written here so they can't be moved after seeing results)

**GO** if all of:
- Out-of-sample filtered strategy beats unconditional short on drawdown-adjusted return (e.g., return/maxDD at least 1.5× the unconditional version's).
- Filter avoids ≥ 60% of the losses the unconditional short takes in the four stress windows.
- Positive out-of-sample total return in the 2018–present window.

**NO-GO** if any fails → strategy moves to research-only. Write the post-mortem, do not "just try a few more thresholds." The grid was the grid.

**Exit criterion:** a written `results/sprint3_gate.md` with the verdict and full metrics. Only a GO unlocks Sprint 4 spending.

---

## Sprint 4 — Options Layer (1–2 weeks, conditional on GO)

1. **Buy options data.** Cheapest adequate: firstratedata VXX options EOD, or ORATS if you want their fitted surfaces. Minimum: EOD chains with bid/ask (not just last) 2016 → present.
2. **ETL the chains** (`data/raw/options/` → interim parquet): contract-level, OCC-symbol-aware around VXX splits. Validation: put-call parity spot checks, bid ≤ ask, monotonic strikes.
3. **`backtest/options.py`** — spread constructor: given a date + panel row, select the debit spread per thesis.md §5.1 (delta-targeted long leg, decay-targeted short leg, 30–60 DTE). Price entries at mid minus a slippage haircut (start: 25% of the bid-ask spread per leg; sensitivity-test at 50%).
4. **Cross-validation of pricing:** for dates where you have chains, compare the market-implied forward decay to your vx30-based decay estimate. This quantifies "how much of the edge is priced in" — expect most of it to be, per thesis.md §2.4. The residual is your actual edge estimate.

**Exit criterion:** spread constructor produces sane, liquidity-aware trades on any HARVEST date in the data; pricing validation notebook complete.

---

## Sprint 5 — Full Backtest & Expectancy (1–2 weeks)

1. Run the complete system: regime filter → spread entry → exit rules (profit target, regime exit, time exit) over the options-data window.
2. Report per thesis.md §11.5: expectancy in R, win rate, avg win/loss in R, trade count, max drawdown on a simulated sleeve with the §8 sizing rules, and each stress window's P&L.
3. Slippage sensitivity: rerun at 25% / 50% / 75% of half-spread. The strategy must survive 50%.
4. **Gate:** net expectancy ≥ +0.05R at 50% slippage, sleeve maxDD < 15% including stress windows. Below either → back to research or NO-GO.

**Exit criterion:** `results/sprint5_backtest.md` with the verdict.

---

## Sprint 6 — Alert System & Paper Phase (1 week build + 8+ weeks paper)

1. **`alerts/daily.py`** — after each close: refresh data, compute the panel row, evaluate regime, and if actionable (new entry eligible, regime exit triggered, profit target likely per marks) send a notification (email/Telegram). Include the exact proposed trade: underlying, strikes, DTE, max debit, and which rule fired. Runs on a scheduler (cron on an always-on box, or a cheap cloud scheduler).
2. **Failure-loud design:** if data refresh fails, the alert says so. A silent no-alert must be distinguishable from "no signal."
3. **Paper phase (minimum 8 weeks or 3 completed trade cycles, whichever is longer):** trade the alerts in a paper account or a written journal with real quotes captured at decision time. Log: alert time, quotes seen, hypothetical fill, and what the backtest engine *would* have assumed. The purpose is measuring **implementation shortfall** — the gap between modeled and achievable fills — not re-proving the edge.

**Exit criterion:** paper-phase implementation shortfall small enough that Sprint 5 expectancy survives it (recompute expectancy with realized paper slippage; must stay ≥ +0.05R).

---

## Sprint 7 — Go-Live (ongoing)

### Pre-flight checklist
- [ ] Broker L3 approval confirmed on the account; VXX spreads placeable.
- [ ] `config/risk.yaml` matches thesis.md §8 and the broker position is sized from it, not from feel.
- [ ] Kill criteria (thesis.md §7) printed and pinned. Literally.
- [ ] Journal template ready: every trade records regime state, panel row snapshot, quotes, fill, exit rule fired, R outcome.

### Live rules
- Start at **half size** (0.5–1% risk per trade) for the first 10 trades.
- Review after every 10 trades: realized vs. modeled expectancy, slippage, rule adherence (count of discretionary deviations — target: zero).
- Scale to full §8 sizing only after 20 trades with realized expectancy > 0 and zero rule deviations.
- Monthly: rerun walk-forward with the newest data; if the most recent test year flips negative, pause entries and review.

### Standing discipline
- The system is flat by default. No trades on "feel" during NEUTRAL/STRESS. The hardest part of this strategy is doing nothing for weeks at a time; that is the strategy working, not the strategy failing.

---

## Order of Work for Day 1 (today)

1. Sprint 0 entirely (repo, venv, filetree, commit thesis.md + plan.md).
2. Sprint 1.2 step 1: `cboe_indices.py` — the three index CSVs are the fastest win and immediately unlock the VIX/VIX3M ratio, which is the backbone regime flag.
3. Start Sprint 1.2 step 2 (futures contracts) — the download enumeration is the fiddly part; get the fetcher and parser stubbed with one contract end-to-end.

Everything else follows the sprint order. Do not touch options data, and do not write a line of spread-pricing code, until the Sprint 3 gate document exists and says GO.
