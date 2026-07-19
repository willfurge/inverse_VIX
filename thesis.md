# THESIS.md - VIX-ETP Contango Harvest (Defined-Risk)

> **Purpose of this file:** This is the canonical research context for the project. Anyone working in this repo must treat this document as the source of truth for *why* the code exists, *what* the strategy is, and *which assumptions are load-bearing*. If code contradicts this document, the code is wrong or this document must be explicitly amended with a dated changelog entry. Do not let implementation details drift from the thesis.

---

## 0. Project Identity & Hard Constraints

| Field | Value |
|---|---|
| Strategy class | Conditional short-volatility, regime-gated, swing horizon |
| Instruments | Put debit spreads on VXX / UVXY (defined-risk only) |
| Account | Sub-$25k sleeve, retail brokerage, options L3 (defined-risk spreads permitted, no naked short options) |
| Execution | **Manual**, off an alert system. No electronic/automated execution. No HFT. |
| PDT | Account is under $25k -> Pattern Day Trader rule applies. Positions are swing/positional (days to weeks). No same-day round trips as a design assumption. |
| Holding period | Typically 2-6 weeks per position (30-60 DTE entry, exit before final week) |
| Developer | Solo, experienced Python (~10 yrs), strong fixed income / quant foundation |

**Non-negotiable design rules:**

1. **Max loss on any position = debit paid.** No structure with undefined or margin-expanding risk is ever modeled, alerted, or traded. No short VXX. No naked short calls. No ratio spreads with net short units.
2. **The system is flat by default.** The alert is the regime. Between alerts, the correct position is no position.
3. **All backtests must be survivable by the account.** Any parameter set producing a modeled drawdown that would breach risk limits (Section 8) is rejected regardless of return.

---

## 1. Thesis (one paragraph)

VIX exchange-traded products (VXX, UVXY) hold rolling long positions in the front two VIX futures contracts, rebalancing daily to maintain a constant ~30-day maturity. Because the VIX futures curve is upward-sloping (contango) roughly 80% of the time, that daily roll mechanically sells cheaper expiring contracts and buys richer later-dated ones, producing structural decay in the ETPs regardless of spot VIX direction. The tradeable edge is **not** the decay itself - the decay is substantially priced into the ETPs' options. The edge is the residual **volatility risk premium (VRP)**: in contango regimes, realized decay tends to exceed what option prices imply, because option sellers demand compensation for the ~20% of the time the curve inverts and these products spike violently. A regime filter keeps us collecting that premium only when the curve's shape and momentum say the premium is rich, and a put debit spread caps our loss at the debit when we're wrong. We are selling insurance while simultaneously truncating our own tail.

**Hard caveat, stated up front and never to be softened:** the academic flagship version of this trade (Simon & Campasano) has *measurably decayed out of sample*. Every return expectation in this repo is anchored to the post-decay reality, not headline backtest numbers.

---

## 2. Mechanism, Ground Up

### 2.1 What VIX actually is

VIX is not a tradeable asset. It is a calculation: the square root of a 30-day variance swap rate on the S&P 500, computed from a strip of out-of-the-money SPX option prices across strikes, interpolated between two expirations to hit exactly 30 calendar days. You cannot buy VIX. Everything downstream (futures, ETPs, options on ETPs) exists because of this fact.

### 2.2 VIX futures and the curve

VIX futures (symbol VX, CFE-listed, launched March 2004) settle to a special opening quotation (SOQ) of VIX on their expiration morning (Wednesday, 30 days before the next monthly SPX expiration). Key structural facts:

- **VIX futures are forecasts, not carries.** There is no cash-and-carry arbitrage tying a VIX future to spot VIX, because spot VIX cannot be held. The future is the market's risk-adjusted expectation of where VIX will be at settlement, plus/minus a risk premium.
- **Contango is the normal state.** Since 2004, the 30-day constant-maturity future has traded above spot roughly 80% of the time. Two reasons: (a) VIX is mean-reverting and usually sits below its long-run mean, so expected future VIX > spot; (b) demand for long-vol hedges pushes futures above even the honest forecast - this second component *is* the risk premium we harvest.
- **Backwardation is the crisis state.** When spot VIX spikes above the futures, the curve inverts. In backwardation, the roll works *for* the long-vol ETPs and violently against short-vol positions. Feb 2018 (VIX 17 to 50 in days, several inverse-vol products terminated), Mar 2020, Aug 2024, Apr 2025 are the canonical stress windows for this repo.

### 2.3 ETP roll mechanics (the bleed)

VXX (and its 1.5x-levered sibling UVXY) track the S&P 500 VIX Short-Term Futures Index. Mechanics:

- The index holds a weighted position in the front-month (M1) and second-month (M2) VIX futures.
- Each trading day it sells a slice of M1 and buys M2 so that the weighted-average maturity remains ~30 days. Over a full roll cycle, the entire position migrates from M1 to M2.
- **In contango (M2 > M1):** each day the fund sells the cheaper contract and buys the more expensive one. It receives fewer units per dollar. Holding notional constant, NAV bleeds by approximately the daily roll yield.
- **Daily roll yield approx (M1 - M2) / M2 * (1 / days-in-roll-period).** In typical contango of 5-10% between M1 and M2 over a ~21-trading-day cycle, this is roughly -5 to -10% per month of headwind for the ETP. This is arithmetic, not a forecast.
- Consequence: VXX has lost the vast majority of its value since inception and reverse-splits regularly to stay listed. **Reverse splits are an ETL landmine; see Section 9.**
- UVXY adds 1.5x daily leverage, which adds volatility drag (a second, path-dependent decay term) on top of roll decay. It decays faster but gaps harder in spikes.

### 2.4 Why the edge isn't "just buy VXX puts"

VXX option market makers know everything in 2.3. The forward decay is embedded in the option surface: VXX puts trade at prices consistent with the futures curve's implied forward path. If the curve's implied decay were realized *exactly*, long puts would roughly break even net of spread and theta.

The residual edge is that **realized decay in contango regimes has historically exceeded implied decay** - that is, the volatility risk premium. Sellers of VXX puts (equivalently, buyers of the tail) systematically overpay for the spike scenario, because the spike scenario is catastrophic for them and they demand compensation. We are on the other side, but *only when the regime filter says the premium is rich*, and only in structures where the spike costs us a known, small, pre-paid amount.

---

## 3. Academic Foundation (and its decay)

Read these in order. The repo's expectations are calibrated to #4, not #1.

1. **Simon & Campasano (2014), "The VIX Futures Basis: Evidence and Trading Strategies," Journal of Derivatives.** The flagship. Documents that the VIX futures basis (futures - spot) does not predict changes in spot VIX but *does* predict futures returns: rich basis (steep contango) leads to short futures profits; deep backwardation leads to long futures profits. This is the intellectual core of the regime filter: **the basis is the signal.**
2. **Johnson (2017-era work on the VIX term structure slope).** Shows the slope of the VIX futures term structure is the dominant priced factor in volatility markets; slope subsumes level. Justifies building the signal off slope measures (VIX/VIX3M, M1:M2) rather than the VIX level.
3. **Cheng, "The Expected Return of Fear" (VIX premium work).** Documents that the VIX futures risk premium is time-varying and, critically, *tends to fall before volatility spikes*; the premium compresses as smart money de-risks before the event. Implication for us: a **premium-momentum / premium-level component** in the filter (not just static contango) helps exit before spikes, and a collapsing basis is a de-risking signal, not a buy-the-dip signal.
4. **Dew-Becker & Giglio, Chicago Fed WP 2025-17.** The reality check. Documents that equity index option returns and CAPM alphas, sharply negative historically (that is, great for vol sellers), have become statistically indistinguishable from zero over the past ~15 years. Attributes it to better-capitalized, more competitive vol sellers via an intermediary asset-pricing model. **Implication: the unconditional VRP is dead. The premium is now state-dependent, meaningfully positive when implied vol is rich versus a realized-vol forecast and after vol shocks, and near zero otherwise.** This is why the strategy is a *filter*, and why doing nothing between alerts is the discipline, not a limitation.

### 3.1 What this means for expected returns

- Trade-level expectancy, not backtest headlines, drives sizing and go/no-go decisions.
- Realistic annual expectation in a normal year: **mid-single digits to mid-teens percent** on the sleeve.
- Ideal-case ceiling (persistent steep contango year, no spikes): **~20-30% gross.**
- Distribution: **negative skew, clustered losses.** Wins are frequent and modest; losses come in bunches around vol events. Double-digit drawdowns during spike episodes are expected and must be pre-modeled in the stress windows.
- Any backtest showing materially better than this is presumptively overfit or has a data bug (lookahead, split-adjustment error, survivorship in the ETP series). Investigate before celebrating.

---

## 4. Signal Specification

All signals are computed from end-of-day data. The alert fires after the close; execution is manual, next session. **No intraday signals. No lookahead: every feature at date t uses only data with timestamp <= t close.**

### 4.1 Core curve features

| Feature | Definition | Notes |
|---|---|---|
| `basis_m1` | M1 settle - spot VIX | Simon & Campasano's raw signal |
| `basis_m1_pct` | (M1 - VIX) / VIX | Normalized |
| `slope_m1m2` | (M2 - M1) / M1 | Front-of-curve contango; drives the ETP roll |
| `vx30` | Constant-maturity 30-day futures price: linear interpolation of M1, M2 settles weighted by calendar days to each expiry | The synthetic underlying VXX tracks |
| `roll_yield_daily` | (M1 - M2) / M2 / trading-days-in-cycle | The mechanical daily bleed estimate |
| `ratio_vix_vix3m` | VIX / VIX3M | <1.0 = contango (normal); >1.0 = stress. Cleanest single regime flag; both series free from CBOE |
| `vix9d_vix` | VIX9D / VIX | Very-front-end stress detector; leads the monthly curve |

### 4.2 Regime states (proposed; Sprint 3 validates and may revise)

- **HARVEST:** `ratio_vix_vix3m` < threshold theta_1 **and** `slope_m1m2` > theta_2 **and** both stable/improving over a short lookback (e.g., 5-day slope of the ratio not rising). Alert: eligible to enter.
- **NEUTRAL:** contango present but shallow, or curve flattening. No new entries; manage existing per exit rules.
- **STRESS:** `ratio_vix_vix3m` >= 1.0 or VIX9D/VIX >= 1.0 or basis collapse > theta_3 within N days. No entries. Existing positions: exit per rules (their loss is already capped, but salvage value decisions are pre-specified, not improvised).
- **POST-SPIKE:** VIX elevated and curve re-steepening after a stress episode. Per Dew-Becker & Giglio and Cheng, this is when the premium is richest. Candidate for the highest-conviction entries; validate in Sprint 3.

Thresholds theta are hypotheses. They get fit in-sample and validated walk-forward. **Never hand-tune thresholds on the full sample.**

### 4.3 What the signal is NOT

- Not a VIX-level signal ("VIX is low, sell vol"); level without slope is noise per Johnson.
- Not a mean-reversion trade on spikes ("VIX at 40, it must fall"); futures already price the reversion.
- Not a market-direction view. The strategy should be approximately agnostic to SPX drift in HARVEST regimes.

---

## 5. Trade Expression

### 5.1 Structure

**Put debit spread on VXX (default) or UVXY (only if VXX liquidity degrades):**

- Long put near-the-money (delta approx -0.45 to -0.55 on entry)
- Short put at lower strike, roughly at the level implied by expected roll decay over the holding period (e.g., strike approx spot * (1 + expected decay to exit date))
- 30-60 DTE at entry
- Net debit paid = max loss. Target reward-to-risk >= 1:1 on the spread at the planned exit horizon (not at expiry).

### 5.2 Why a debit spread and not alternatives

- **vs. long put:** the short leg sells back the far-downside tail that roll decay rarely reaches within one cycle, and offsets the elevated IV you're paying on the long leg. Reduces theta bleed and vega exposure.
- **vs. put credit spread on inverse products / call credit spread on VXX:** credit structures are short the spike; assignment and early-exercise mechanics on deep ITM short legs of American options add operational risk. Debit spread keeps worst case as "spread expires worthless, lose debit."
- **vs. short VXX / long SVIX-type inverse ETP:** undefined risk and volatility drag respectively; both excluded by design rules.

### 5.3 Entry / exit rules (initial spec; Sprint 5 finalizes)

- **Entry:** regime = HARVEST (or validated POST-SPIKE), and spread pricing offers >= target R:R using the constant-maturity decay estimate. Enter with limit orders at/near mid; walk the order, never cross a wide market.
- **Profit exit:** close at 50-70% of max spread value, or when DTE < 10, whichever first. Do not hold to expiry (pin/assignment risk on the short leg, gamma noise).
- **Regime exit:** if regime flips to STRESS, exit next session regardless of P&L. The debit cap is the disaster brake; the regime exit is the ordinary brake.
- **Time exit:** DTE < 10, close.
- **One position per underlying at a time** during initial live phase.

---

## 6. Expectancy Framework

All performance evaluation is in **R-multiples** where 1R = debit paid on the trade.

Expectancy per trade: `E = p_win * avg_win_R - (1 - p_win) * avg_loss_R`

Working hypothesis to validate (NOT assume): p_win approx 0.60-0.70 in HARVEST regimes, avg_win approx +0.6 to +0.8R (due to early profit-taking), avg_loss approx -0.7 to -1.0R (regime exits salvage some premium; full -1R losses occur on gaps). That yields E approx +0.10 to +0.25R per trade before slippage. With ~10-20 qualifying trades/year and 1-2% of sleeve risked per trade, this reconciles to the mid-single-to-mid-teens annual expectation. **If Sprint 5 backtest expectancy falls below +0.05R net of modeled slippage, the strategy does not go live.**

---

## 7. Prior Art Decay & Kill Criteria

The strategy dies (goes to research-only, no live capital) if any of the following:

1. Sprint 3 gate fails: regime-filtered underlying proxy shows no statistically meaningful edge out-of-sample (see plan.md Sprint 3 for the specific test).
2. Sprint 5 net expectancy < +0.05R.
3. Live phase: realized expectancy over first 20 trades < 0R, or a single position loses more than the debit (indicates a structural misunderstanding; this should be impossible).
4. Market-structure change that removes the mechanism (e.g., ETP restructuring away from daily front-month roll, delisting of liquid VXX options).

---

## 8. Risk Limits (live phase)

- Max risk per trade: 1-2% of sleeve (= the debit).
- Max concurrent premium at risk: 5% of sleeve.
- Max monthly loss: 6% of sleeve -> flat for the remainder of the month, mandatory review.
- Stress-window rehearsal: every parameter set must be run through Feb 2018, Mar 2020, Aug 2024, Apr 2025 windows before deployment. Report worst peak-to-trough on the sleeve; must be < 15%.
- No martingale, no size-up-after-loss, no "the regime is extra good" discretionary oversizing.

---

## 9. Data & Engineering Landmines

1. **VXX reverse splits.** VXX reverse-splits repeatedly (typically 1:4). Unadjusted price series have massive jumps; naively adjusted series from some vendors mishandle the option chains. Always use split-adjusted underlying prices for signal work, and *contract-level* option data (which is split-adjusted by OCC at the contract level with new symbols) for options work. Validate around known split dates.
2. **VXX issuer/ticker history.** The original VXX (Barclays ETN) matured Jan 2019 and was succeeded by VXXB, renamed back to VXX. In 2022 Barclays halted creations, causing premium-to-NAV distortion for weeks. Any backtest spanning these events must flag them; consider stitching or excluding distorted windows.
3. **CBOE URL drift.** CBOE reorganizes its site frequently; static download links break. The stable-ish endpoints as of July 2026: index histories at `https://cdn.cboe.com/api/global/us_indices/daily_prices/{SYMBOL}_History.csv` (VIX, VIX3M, VIX9D), futures contract CSVs via the CFE historical data page (symbol `VX+VXT`, one CSV per contract month), and daily settlements via the VIX Settlement Series archive. ETL must fail loudly (not silently return empty frames) when an endpoint 404s or schema-shifts.
4. **Expired-contract CSV quirk:** in CFE per-contract files, the final settlement row has zero OHLC/volume with only Settle populated. Handle explicitly.
5. **Pre-2004-06 VIX OHLC:** VIX daily data before mid-June 2004 has open=high=low=close (only closes were recorded). Fine for this project (we use closes) but don't compute intraday ranges pre-2004.
6. **Futures expiry calendar:** VIX futures expire Wednesdays, 30 days before the next monthly SPX expiration; holiday adjustments exist. Never hardcode "third Wednesday." Build the calendar from the contracts' own final rows or CBOE's published expiration calendar and store it as data.
7. **Constant-maturity interpolation:** use calendar days to expiry for weights (matching the index methodology), not trading days. Roll happens on the CBOE roll schedule (expiry-to-expiry), not month boundaries.
8. **Timezones:** all timestamps in America/Chicago (CFE) or normalize everything to dates only (EOD project; prefer dates).
9. **Options data is the only paid dataset.** EOD VXX option chains: ORATS, Cboe DataShop, or firstratedata. Do not buy until Sprint 3 gate passes.
10. **No lookahead, ever.** Settlement values are known after the close; a signal computed from date-t settles is tradeable at t+1's session at the earliest. The backtest engine must enforce this structurally (feature timestamps vs. execution timestamps), not by convention.

---

## 10. Glossary (canonical definitions for this repo)

- **M1, M2:** front-month and second-month VIX futures contracts by expiry.
- **Basis:** futures price minus spot VIX.
- **Contango / backwardation:** upward- / downward-sloping futures curve.
- **VX30:** synthetic constant-maturity 30-day VIX futures price (calendar-day-weighted M1/M2 interpolation).
- **Roll yield:** P&L impact of the daily M1 to M2 migration, sign-flipped for long ETPs in contango.
- **VRP (volatility risk premium):** implied volatility/variance minus subsequently realized; the compensation vol sellers earn.
- **R-multiple:** trade P&L divided by initial risk (debit).
- **HARVEST / NEUTRAL / STRESS / POST-SPIKE:** regime states per Section 4.2.
- **Stress windows:** Feb 2018, Mar 2020, Aug 2024, Apr 2025.
- **Walk-forward:** repeated fit-on-past / test-on-next-segment validation; the only accepted out-of-sample protocol in this repo.

---

## 11. Research governance

1. This file and `plan.md` are the specification. Amendments should include rationale and a dated changelog entry.
2. Every dataset gets a validation module that runs on ingest (schema, date continuity, split-date sanity checks, expiry-row handling). ETL that "works" without validation is incomplete.
3. Backtest code must structurally prevent lookahead (separate signal timestamps from execution timestamps).
4. Parameters live in config files, never inline. Every fitted parameter records its fit window.
5. Results reporting always includes: expectancy in R, win rate, max drawdown, stress-window P&L, and trade count. Never report a Sharpe ratio without also reporting skew and the worst single month.
6. Nothing in this repository constitutes advice to anyone else; it is personal research infrastructure. Any go-live decision belongs to the researcher and must follow the gates defined in `plan.md`.

---

*Changelog:*
- *2026-07-11: v2 - public research document. Supersedes strategy.md from June 2026.*
