# THESIS.md - VIX-ETP Contango Harvest 

> **Purpose of this file:** This is the canonical research context for the project. Anyone working in this repo must treat this document as the source of truth for why the code exists, and what the strategy is. If code contradicts this document, the code is wrong or this document must be explicitly amended with a dated changelog entry. Do not let implementation details drift from the thesis.

---

## 0. Project Identity & Hard Constraints

| Field | Value |
|---|---|
| Strategy class | Conditional short-volatility, regime-gated, swing horizon |
| Instruments | Put debit spreads on VXX / UVXY (defined-risk only) |
| Account | Sub-$25k sleeve, retail brokerage, options L3 (defined-risk spreads permitted, no naked short options) |
| Execution | Manual, off an alert system. No electronic/automated execution. No HFT. |
| PDT | Positions are swing/positional (days to weeks). |
| Holding period | Typically 2-6 weeks per position (30-60 DTE entry, exit before final week) |

**Design rules:**

1. **Max loss on any position = debit paid.** No structure with undefined or margin-expanding risk is ever modeled, alerted, or traded. No short VXX. No naked short calls. No ratio spreads with net short units.
2. **The system is flat by default.** The alert is the regime. Between alerts, the correct position is no position.
3. **All backtests must be survivable by the account.** Any parameter set producing a modeled drawdown that would breach risk limits (Section 8) is rejected regardless of return.

---

## 1. Thesis (one paragraph)

VIX exchange-traded products (VXX, UVXY) hold rolling long positions in the front two VIX futures contracts, rebalancing daily to maintain a constant ~30-day maturity. Because the VIX futures curve is upward-sloping (contango) roughly 80% of the time, that daily roll mechanically sells cheaper expiring contracts and buys richer later-dated ones, producing structural decay in the ETPs regardless of spot VIX direction. The tradeable edge is not the decay itself, the decay is substantially priced into the ETPs' options. The edge is the residual volatility risk premium (VRP): in contango regimes, realized decay tends to exceed what option prices imply, because option sellers demand compensation for the ~20% of the time the curve inverts and these products spike violently. A regime filter keeps us collecting that premium only when the curve's shape and momentum say the premium is rich, and a put debit spread caps our loss at the debit when we're wrong. We are selling insurance while simultaneously truncating our own tail.

The academic flagship version of this trade (Simon & Campasano) has measurably decayed out of sample. 
---

## 2. Mechanism, Ground Up

### 2.1 What VIX actually is

VIX is not a tradeable asset. It is a calculation: the square root of a 30-day variance swap rate on the S&P 500, computed from a strip of out-of-the-money SPX option prices across strikes, interpolated between two expirations to hit exactly 30 calendar days. You cannot buy VIX. Everything downstream (futures, ETPs, options on ETPs) exists because of this fact.

### 2.2 VIX futures and the curve

VIX futures (symbol VX, CFE-listed, launched March 2004) settle to a special opening quotation (SOQ) of VIX on their expiration morning (Wednesday, 30 days before the next monthly SPX expiration). Key structural facts:

- **VIX futures are forecasts.** There is no cash-and-carry arbitrage tying a VIX future to spot VIX, because spot VIX cannot be held. The future is the market's risk-adjusted expectation of where VIX will be at settlement, plus/minus a risk premium.
- **Contango is the normal state.** Since 2004, the 30-day constant-maturity future has traded above spot roughly 80% of the time. Two reasons: (a) VIX is mean-reverting and usually sits below its long-run mean, so expected future VIX > spot; (b) demand for long-vol hedges pushes futures above even the honest forecast - this second component is the risk premium we harvest.
- **Backwardation is the crisis state.** When spot VIX spikes above the futures, the curve inverts. In backwardation, the roll works for the long-vol ETPs and violently against short-vol positions. Feb 2018 (VIX 17 to 50 in days, several inverse-vol products terminated), Mar 2020, Aug 2024, Apr 2025 are the canonical stress windows for this repo.

### 2.3 ETP roll mechanics (the bleed)

VXX (and its 1.5x-levered sibling UVXY) track the S&P 500 VIX Short-Term Futures Index. Mechanics:

- The index holds a weighted position in the front-month (M1) and second-month (M2) VIX futures.
- Each trading day it sells a slice of M1 and buys M2 so that the weighted-average maturity remains ~30 days. Over a full roll cycle, the entire position migrates from M1 to M2.
- **In contango (M2 > M1):** each day the fund sells the cheaper contract and buys the more expensive one. It receives fewer units per dollar. Holding notional constant, NAV bleeds by approximately the daily roll yield.
- **Daily roll yield approx (M1 - M2) / M2 * (1 / days-in-roll-period).** In typical contango of 5-10% between M1 and M2 over a ~21-trading-day cycle, this is roughly -5 to -10% per month of headwind for the ETP.
- Consequence: VXX has lost the vast majority of its value since inception and reverse-splits regularly to stay listed. 
- UVXY adds 1.5x daily leverage, which adds volatility drag (a second, path-dependent decay term) on top of roll decay. It decays faster but gaps harder in spikes.

### 2.4 Why the edge isn't "just buy VXX puts"

VXX option market makers know everything in 2.3. The forward decay is embedded in the option surface: VXX puts trade at prices consistent with the futures curve's implied forward path. If the curve's implied decay were realized exactly, long puts would roughly break even net of spread and theta.

The residual edge is that realized decay in contango regimes has historically exceeded implied decay. Sellers of VXX puts (equivalently, buyers of the tail) systematically overpay for the spike scenario, because the spike scenario is catastrophic for them and they demand compensation. We are on the other side, but only when the regime filter says the premium is rich, and only in structures where the spike costs us a known, small, pre-paid amount.

---

## 3. Academic Foundation (and its decay)


1. **Simon & Campasano (2014), "The VIX Futures Basis: Evidence and Trading Strategies," Journal of Derivatives.**
2. **Johnson (2017-era work on the VIX term structure slope).**
3. **Cheng, "The Expected Return of Fear" (VIX premium work).** 
4. **Dew-Becker & Giglio, Chicago Fed WP 2025-17.**

---

## 4. Signal Specification

All signals are computed from end-of-day data. The alert fires after the close; execution is manual, next session. Every feature at date t uses only data with timestamp <= t close.

### 4.1 Core curve features

| Feature | Definition | Notes |
|---|---|---|
| `basis_m1` | M1 settle - spot VIX | Simon & Campasano's raw signal |
| `basis_m1_pct` | (M1 - VIX) / VIX | Normalized |
| `slope_m1m2` | (M2 - M1) / M1 | Front-of-curve contango; drives the ETP roll |
| `vx30` | Constant-maturity 30-day futures price: linear interpolation of M1, M2 settles weighted by calendar days to each expiry | The synthetic underlying VXX tracks |
| `roll_yield_daily` | (M1 - M2) / M2 / trading-days-in-cycle | The mechanical daily bleed estimate |
| `ratio_vix_vix3m` | VIX / VIX3M | <1.0 = contango (normal); >1.0 = stress. |
| `vix9d_vix` | VIX9D / VIX | Very-front-end stress detector; leads the monthly curve |

### 4.2 Regime states

- **HARVEST:** `ratio_vix_vix3m` < threshold theta_1 and `slope_m1m2` > theta_2 and both stable/improving over a short lookback (e.g., 5-day slope of the ratio not rising). Alert: eligible to enter.
- **NEUTRAL:** contango present but shallow, or curve flattening. No new entries; manage existing per exit rules.
- **STRESS:** `ratio_vix_vix3m` >= 1.0 or VIX9D/VIX >= 1.0 or basis collapse > theta_3 within N days. No entries. Existing positions: exit per rules (their loss is already capped, but salvage value decisions are pre-specified, not improvised).
- **POST-SPIKE:** VIX elevated and curve re-steepening after a stress episode. Per Dew-Becker & Giglio and Cheng, this is when the premium is richest. Candidate for the highest-conviction entries; validate in Sprint 3.

Thresholds theta are hypotheses. They get fit in-sample and validated walk-forward. *

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

## 9. Data & Engineering Landmines

1. **VXX reverse splits.** 
2. **VXX issuer/ticker history.** 
3. **CBOE URL drift.** CBOE reorganizes its site frequently; static download links break.
4. **Expired-contract CSV quirk:** in CFE per-contract files, the final settlement row has zero OHLC/volume with only Settle populated. Handle explicitly.
5. **Pre-2004-06 VIX OHLC:** 
6. **Futures expiry calendar:** 
7. **Constant-maturity interpolation:** 
8. **Timezones:**
9. **Options data is the only paid dataset.** 
10. **No lookahead, ever.** 

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

1. This file and plan.md are the specification. Amendments should include rationale and a dated changelog entry.
2. Every dataset gets a validation module that runs on ingest (schema, date continuity, split-date sanity checks, expiry-row handling). ETL that "works" without validation is incomplete.
3. Backtest code must structurally prevent lookahead (separate signal timestamps from execution timestamps).
4. Parameters live in config files, never inline. Every fitted parameter records its fit window.
5. Results reporting always includes: expectancy in R, win rate, max drawdown, stress-window P&L, and trade count. Never report a Sharpe ratio without also reporting skew and the worst single month.
6. Nothing in this repository constitutes advice to anyone else; it is personal research infrastructure. Any go-live decision belongs to the researcher and must follow the gates defined in `plan.md`.

---

*Changelog:*
- *2026-07-11: v2 - public research document. Supersedes strategy.md from June 2026.*
