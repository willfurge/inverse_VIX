# inverse VIX research

This repository tests whether a frozen VIX term-structure regime filter can identify periods in which short-volatility exposure is worth researching. The original trade expression was a defined-risk put debit spread on VXX or UVXY. The public research result is negative: the frozen Sprint 3 proxy gate is `NO-GO`, so this project is research-only and does not authorize live trading.

The current gate report is [results/sprint3_gate.md](results/sprint3_gate.md). The follow-up analyses explain why the proxy failed and test the same fixed rule as an equity de-risking overlay: [results/attribution_summary.md](results/attribution_summary.md) and [results/overlay_summary.md](results/overlay_summary.md).

## Quick start

The project supports Python 3.11 or newer. A fresh environment can be created with:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The full reproduction sequence is documented in [docs/REPRODUCING.md](docs/REPRODUCING.md). Downloaded market data is intentionally not committed. Run the refresh step before the research steps when starting from an empty `data/` directory.

## Public commands

These five scripts are the supported research interface. The package under `src/` contains the implementation used by them; notebooks are exploratory and are not required.

1. Refresh the raw and interim inputs: allow incomplete coverage is required, and is a known bug due to an assertion for longer history than is supported by CBOE.

	```powershell
	python scripts/refresh_data.py --allow-incomplete-coverage
	```

2. Build the processed panel and display its latest row:

	```powershell
	python scripts/run_signal.py
	```

3. Run the frozen out-of-sample proxy gate:

	```powershell
	python scripts/run_sprint3_gate.py
	```

4. Attribute the filtered-short result:

	```powershell
	python scripts/attribution.py
	```

5. Evaluate the fixed rule as an SPY de-risking overlay:

	```powershell
	python scripts/computation_C.py
	```

Each command accepts `--help`. All commands also accept explicit data, results, or configuration paths where those inputs are relevant. The overlay accepts `--offline --spy-source PATH` when a local SPY CSV is available.

## Research status

The signal was frozen using the available 2013-2017 CFE history. It was then evaluated out of sample from 2018 onward with a signal-at-close, execution-on-next-session rule. The filter avoided most losses in the named stress windows, but the filtered proxy still had negative total return and failed the drawdown-adjusted return requirement. The precommitted result is `NO-GO`; no additional threshold search is part of this public result.

The attribution report shows that mechanical carry was positive while directional mean reversion and spike exposure dominated the realized result. The overlay report is a separate, post-hoc question. It evaluates the same frozen rule against buy-and-hold and a one-condition inversion control, including a separate 2022 analysis. It does not revise the gate or turn the research into a trading recommendation.

## Repository map

- [thesis.md](thesis.md): strategy mechanism, assumptions, risk limits, and research rules.
- [plan.md](plan.md): historical build plan and project status.
- [docs/REPRODUCING.md](docs/REPRODUCING.md): clean-environment runbook and troubleshooting.
- [docs/DATA.md](docs/DATA.md): source provenance, transformations, coverage, and known data issues.
- [config](config): versioned source and frozen signal settings.
- [src/vixharvest](src/vixharvest): load-bearing ETL, curve, signal, and backtest code.
- [tests](tests): focused regression tests for the implementation.
- [results](results): selected human-readable report snapshots. CSV and parquet intermediates are generated locally and ignored.

This is personal research infrastructure, not investment advice. The code does not place trades, send alerts, or provide a live execution system.
