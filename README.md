# Ramadan Price Surges in Bangladesh Staples

Forecasting and risk assessment of Ramadan-driven price surges in Bangladesh's staple food markets using seasonal decomposition and Monte Carlo simulation.

## Data

WFP *Bangladesh - Food Prices*, Humanitarian Data Exchange (HDX), licence CC BY-IGO.
https://data.humdata.org/dataset/wfp-food-prices-for-bangladesh

Monthly retail prices (BDT) for coarse rice, masur lentils, palm oil and wheat flour.

- **Main series:** Dhaka Division market, 2006 to 2020.
- **Robustness and forecast series:** a national matched-market chained index, 2006 to 2026.

The URL, access date, licence, row counts and SHA-256 checksums are in `data/raw/SOURCES.md`. Every search, download, decision and error is logged in `RUNLOG.md`.

## Method

1. Clean the data. Cleaning removes duplicates and non-positive prices and excludes suspected recording errors (they are not imputed). It fills gaps of 1 to 2 months by neighbour averaging and never fills longer gaps; every filled cell is logged.
2. Compute the Ramadan calendar with `hijridate` (Umm al-Qura), cross-checked with `convertdate`, plus a +1 day sensitivity run for Bangladesh.
3. Run a multiplicative decomposition (statsmodels and a manual ratio-to-CMA version), then a regression with a moving Ramadan dummy (HAC standard errors).
4. Compute the surge: price in the flag month / mean of the two pre-Ramadan months - 1.
5. Fit Normal and Lognormal distributions and test them (KS with a Lilliefors bootstrap, chi-square).
6. Run a Monte Carlo simulation (N = 10,000, seed 42): Version A is parametric, Version B bootstraps past Ramadan years.
7. Run the Welch t-test and bootstrap CIs, the scenarios, the one-at-a-time tornado sensitivity and a rolling-origin backtest.

## Layout

```
data/raw/        raw WFP CSVs, API responses, SOURCES.md
data/clean/      prices_monthly.csv, gap and exclusion logs (written by the notebook)
src/             ramadan_surge.py (analysis helpers), workbook.py (Excel output)
tests/           pytest unit tests for src/
scripts/         download_data.py, build_notebook.py, run_notebook.sh
outputs/         notebook, HTML export, figures/, results.xlsx, REPORT.md
```

## Usage

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m ipykernel install --sys-prefix --name ramadan-surge
.venv/bin/python scripts/download_data.py      # optional: re-download the raw data
.venv/bin/python -m pytest tests               # unit tests
scripts/run_notebook.sh                        # build, execute and export the notebook
```

`run_notebook.sh` calls `.venv/bin/python -m nbconvert` directly so that the notebook runs in the project venv rather than a system Jupyter.

## Running on Google Colab from VS Code

1. Install the **Google Colab** extension (`google.colab`). VS Code suggests it when you open this folder, through `.vscode/extensions.json`; it also needs the Jupyter extension.
2. Open `outputs/ramadan_surge_simulation.ipynb`, click **Select Kernel**, choose **Colab**, then **Auto Connect** (or pick a runtime), and sign in with Google.
3. Run all cells. The first cell detects the Colab runtime, clones this repository into `/content/ramadan-surge-simulation`, installs `requirements-colab.txt` and moves into the project. On a local kernel it does nothing.

Outputs (figures, `results.xlsx`, `REPORT.md`) are written on the Colab runtime under `/content/ramadan-surge-simulation/outputs/`, not to your local folder. Download them from there, or run locally with `scripts/run_notebook.sh`. Colab clones the version pushed to GitHub, so push local changes before running there.

## Status

- Data download, quality gate, helper modules and unit tests are complete; all tests pass.
- The notebook is built but **not yet fully executed**. The outputs (`REPORT.md`, `results.xlsx`, `figures/`, HTML) are produced by the first successful run of `scripts/run_notebook.sh`.

## Limitations

- Ramadan drifts about 11 days earlier each year, so it is observed in only part of the calendar.
- Prices are nominal, not inflation-adjusted.
- Monsoon, floods, trade policy and the exchange rate are not separated out.
- There are few Ramadan observations.
- Some source values are WFP aggregates.
- In 2020 WFP switched from division-level to district-level markets.
- The household basket quantities are illustrative assumptions.
