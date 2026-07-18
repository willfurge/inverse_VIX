# Data Anomalies and Source Limits

## VXX issuer and ticker history

- The original Barclays VXX matured in January 2019.
- VXXB succeeded it and was later renamed VXX.
- Yahoo Finance's current `VXX` history starts on 2018-01-25; its `VXXB` history is not usable as a historical stitch. The ETL therefore raises a coverage error rather than pretending the required 2009 VXX history exists.
- Any provider used to fill the pre-2018 window must be documented in `config/data_sources.yaml`, retained in `data/raw/`, and compared at five manually selected overlapping dates before it is accepted.

## VXX 2022 creation halt

Barclays' halt of VXX creations caused a premium-to-NAV distortion during 2022. Flag this window in any VXX comparison or backtest; do not treat it as ordinary VX roll behavior.

## CFE VX public-file coverage

- The public CFE per-contract price-and-volume URL pattern is `VX_{expiry}.csv`.
- Direct-file checks on 2026-07-17 found public data from 2013 onward; pre-2013 requests return HTTP 403.
- The ETL records this as a coverage error against the 2005 Sprint 1 research requirement unless `refresh_data.py --allow-incomplete-coverage` is used. That option is for inspection only and does not satisfy the Sprint 1 exit criterion.

## CFE settlement field variation

Older CFE files can report `Settle=0` while a valid `Close` is present. The normalized table uses `Close` only for those missing settlements and retains the original CSV unchanged. Fully zero pre-listing rows and 2013 expiry-day placeholders (zero `Open`, `Close`, and `Settle` with stray `High`/`Low`) are discarded; partial missing-price rows still raise an error.

## CBOE index-history continuity

The CBOE VIX-history CSV omits 1991-03-01, 1997-01-31, and 1997-11-26 despite these being otherwise-open sessions. These are documented source-specific omissions in the continuity validator; any newly observed missing expected session still raises an ingest error.

## VX holiday-shifted expiries

The downloaded CFE files confirm Tuesday expiries when the following month's normal SPX expiration Friday is a market holiday, including 2014-03-18, 2019-03-19, 2022-03-15, 2025-03-18, and 2026-05-19. The expiry validator accepts only this rule or a direct adjacent-Wednesday holiday shift.

## Split-sanity control

The yfinance loader requests `auto_adjust=True`. In that mode, the `Close` column is already split/dividend-adjusted and there is no `Adj Close` column. The loader rejects daily moves over 60% outside the four configured stress windows, preventing an unadjusted reverse split from entering the interim panel.
