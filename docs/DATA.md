# Data provenance

The research uses public daily market data. Data files are downloaded locally, validated during ingestion, and excluded from the public source snapshot because they are large, mutable, and subject to provider terms.

## Sources

| Dataset | Source | Local output | Role |
| --- | --- | --- | --- |
| VIX, VIX3M, VIX9D histories | CBOE index-history CSV endpoints listed in `config/data_sources.yaml` | `data/raw/indices/` and `data/interim/indices.parquet` | Spot and short-horizon regime features |
| VX contract histories | CFE historical contract CSV endpoint listed in `config/data_sources.yaml` | `data/raw/cfe_vx/` and `data/interim/vx_contracts.parquet` | Front two contracts, expiry calendar, and proxy construction |
| VXX and UVXY prices | yfinance with `auto_adjust=True` | `data/raw/etp/` and `data/interim/etp_prices.parquet` | Split-adjusted sanity check and proxy validation |
| SPY total-return prices | yfinance, or a local CSV fallback | local input to the overlay command | Equity overlay comparison |

The exact endpoints, source notes, and configured coverage dates are versioned in `config/data_sources.yaml`. Provider availability and freshness can change after this repository snapshot.

## Transformations

1. CBOE index CSVs are parsed into normalized dates and numeric OHLC columns. The ETL rejects schema changes, duplicate dates, non-positive values, and stale histories.
2. CFE files are parsed into contract identity, expiry, daily settlement, volume, and open interest. Expiry rows and source-specific zero placeholders are handled explicitly. The expiry calendar used by the curve code is derived from the contract data.
3. VIX futures are combined into the constant-maturity curve using calendar-day interpolation between the nearest two contracts. Features include basis, front slope, roll-yield estimate, VIX ratios, and five-day ratio changes.
4. The proxy backtest uses contract-identity returns and lagged roll weights. A signal observed at the date-t close becomes exposure on the next observed trading date.
5. VXX data is used as a split-adjusted validation series. It is not treated as a clean substitute for the contract-level proxy.
6. The overlay uses adjusted SPY closes, computes daily total returns, and applies each exposure signal with the same one-session lag.

## Coverage and research boundaries

Public CFE contract history begins in 2013. The formal frozen fit window is 2013-01-16 through 2017-12-29, followed by out-of-sample evaluation from 2018 onward. The result report records the actual dates and hashes of the inputs used for a run.

The current gate includes partial 2026 data through the latest available source date. Results are not timeless performance claims. They are a reproducible snapshot tied to the input hashes in the generated report.

## Known issues

- VXX has undergone repeated reverse splits and a VXX to VXXB to VXX ticker transition. The source export must remain split-adjusted, and the transition is documented in `data/ANOMALIES.md` when local data is present.
- CFE contract files have contained expiry-date placeholder rows and inconsistent settlement fields across vintages. The parser preserves raw files and applies only documented normalization.
- CBOE endpoints can return stale content with a successful HTTP status. The index ETL retries stale responses and fails after the retry limit.
- SPY history may be retrieved from the network or supplied through the documented local fallback. The public analysis does not commit either source file.

## Reproducibility and licensing

Run `python scripts/refresh_data.py` to acquire current inputs. Data-provider terms, availability, and redistribution rights remain the responsibility of the user. This repository distributes code and documentation, not a copy of the downloaded market-data history. Do not commit credentials, private vendor data, or unreviewed exports.
