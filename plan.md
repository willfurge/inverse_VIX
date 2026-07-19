# Project status and historical build plan

This document records how the repository was built and what the completed research says. It is a status record, not a live-trading roadmap.

## Current status

- Data acquisition, curve construction, signal classification, and the Sprint 3 proxy gate are implemented.
- The frozen fit window is 2013-01-16 through 2017-12-29 because public CFE contract history begins in 2013.
- The formal out-of-sample period begins in 2018 and includes partial 2026 data through the latest input date.
- The frozen proxy gate is `NO-GO`. It avoided most losses in the named stress windows but failed positive out-of-sample return and drawdown-adjusted performance requirements.
- Attribution and equity-overlay analyses were added after the gate to explain the failure and test a separate risk-management interpretation. Neither analysis reopens the gate.
- Options acquisition, spread pricing, live alerts, and live trading are not unlocked by this result.

The current conclusion is documented in [results/sprint3_gate.md](results/sprint3_gate.md). The supporting analyses are [results/attribution_summary.md](results/attribution_summary.md) and [results/overlay_summary.md](results/overlay_summary.md).

## Research question

The original question was whether the VIX futures term structure could identify periods in which the structural decay of VIX exchange-traded products was large enough, and sufficiently predictable, to justify defined-risk options research.

The staged research design was:

1. Acquire and validate public daily VIX index, VIX futures, and ETP data.
2. Build a constant-maturity VX30 curve and derived regime features.
3. Evaluate a frozen regime filter on a rolled short-term-futures proxy with next-session execution.
4. Attribute the result after the gate was complete.
5. Test the same fixed rule as an equity de-risking overlay without presenting that as the original trading thesis.

## Historical stages

### Data and ETL

The ETL downloads CBOE index histories, CFE VX contract histories, and split-adjusted VXX and UVXY prices. It validates schemas, dates, positive price fields, source freshness, contract settlements, coverage, and known ETP split issues. Raw downloads remain local and are not committed.

### Curve and signal panel

The curve layer derives the expiry calendar from contract data, selects the nearest two contracts, and interpolates a calendar-day constant-maturity value. The panel includes basis, front slope, roll-yield estimate, VIX ratios, and five-day changes used by the regime classifier.

### Sprint 3 gate

The gate was fixed before out-of-sample evaluation:

- Fit window: 2013-01-16 through 2017-12-29
- Ratio threshold: `theta_1_ratio = 0.85`
- Slope threshold: `theta_2_slope = 0.05`
- Momentum lookback: 5 sessions
- Stress classification takes precedence over harvest classification
- Signal date is the close on `t`; exposure begins on the next observed trading session

The proxy validation requires the rolled STF index to exceed 0.95 log-level correlation with split-adjusted VXX. The gate then compares filtered short exposure with unconditional short exposure and a flat benchmark across aggregate, annual, and named stress-window results.

The precommitted requirements were positive filtered out-of-sample return, a drawdown-adjusted result at least 1.5 times the unconditional short, and at least 60 percent loss avoidance in each applicable stress window. The first two failed. The verdict is `NO-GO`.

### Follow-up analyses

The attribution report decomposes the filtered result into mechanical carry and directional movement, then isolates transition buckets and tail days. The overlay report asks whether the same fixed signal is more useful for reducing SPY exposure than for shorting the proxy. It includes a one-condition inversion control and a separate 2022 test because a bear market without a VIX inversion is a known blind spot.

These analyses are descriptive. They do not constitute a new fit, a revised gate, or a live strategy.

## Supported reproduction path

The supported public workflow is documented in [docs/REPRODUCING.md](docs/REPRODUCING.md):

```text
scripts/refresh_data.py
scripts/run_signal.py
scripts/run_sprint3_gate.py
scripts/attribution.py
scripts/computation_C.py
```

The package under `src/vixharvest` contains the implementation used by those commands. Configuration under `config/` records source endpoints and frozen signal settings. Tests cover validation, curve construction, signal classification, proxy mechanics, and gate calculations.

## Future work boundary

Because the gate is `NO-GO`, the following work is outside the completed public result:

- buying or integrating paid VXX option-chain data
- fitting new thresholds to rescue the failed gate
- presenting the overlay analysis as proof of a trading edge
- building automated execution or live capital alerts

A future research revision would need a new precommitted hypothesis, a new fit and validation protocol, and a clearly separated result. It should not silently overwrite this gate.

## Changelog

- 2026-07-18: publicized the completed research workflow, documented the NO-GO result, and separated generated artifacts from the source surface.
- 2026-07-11: recorded the completed Sprint 3 gate and its frozen-parameter protocol.
