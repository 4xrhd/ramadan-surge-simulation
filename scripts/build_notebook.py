"""Build outputs/ramadan_surge_simulation.ipynb (unexecuted) from cell definitions.

Run:  .venv/bin/python scripts/build_notebook.py
Then execute and export with scripts/run_notebook.sh.
"""

from __future__ import annotations

import os
from textwrap import dedent

import nbformat as nbf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NB_PATH = os.path.join(ROOT, "outputs", "ramadan_surge_simulation.ipynb")

cells: list = []


def md(text: str) -> None:
    cells.append(nbf.v4.new_markdown_cell(dedent(text).strip()))


def code(text: str) -> None:
    cells.append(nbf.v4.new_code_cell(dedent(text).strip()))


# =============================================================================
md(r"""
# Forecasting and Risk Assessment of Ramadan-Driven Price Surges in Bangladesh's Staple Food Markets Using Seasonal Decomposition and Monte Carlo Simulation

**Aim.** Measure how much retail prices of Bangladesh staples rise in the month of Ramadan, separate that effect from ordinary calendar seasonality, and simulate the price risk of the next Ramadan after the end of the data.

**Data.** WFP *Bangladesh - Food Prices* (Humanitarian Data Exchange, CC BY-IGO): monthly retail prices of coarse rice, masur lentils, palm oil and wheat flour.

**Structure.** 0 Setup and seed | 1 Data sources | 2 Cleaning | 3 Ramadan calendar | 4 Decomposition | 5 Surge table | 6 Distribution fit | 7 Monte Carlo | 8 Tests | 9 Scenarios and sensitivity | 10 Backtest | 11 Dashboard | 12 Limitations and conclusion.

**Reading guide.** Markdown cells explain *why* each step is done. Every number quoted in the conclusions, in `REPORT.md` and in `results.xlsx` is computed by a code cell of this notebook; interpretations that depend on results are printed by code so they cannot drift from the numbers.
""")

# =============================================================================
md("""
## 0 Setup and seed

Why: the analysis must be reproducible. We fix the global seed to **42**, and every stochastic step (bootstrap, goodness-of-fit simulation, Monte Carlo) draws from its own generator derived from that seed and a stage label. The results therefore do not depend on the order in which cells are run. Helper functions that are reused (calendar, cleaning, decomposition, distribution fitting) live in `src/ramadan_surge.py` and are covered by unit tests in `tests/`.
""")
code("""
import hashlib
import json
import re
import shutil
import sys
import zlib
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy
import statsmodels
import statsmodels.api as sm
import statsmodels.formula.api as smf
from cycler import cycler
from IPython.display import Markdown, display
from matplotlib.patches import Patch
from matplotlib.ticker import PercentFormatter
from scipy import stats
from statsmodels.stats.multitest import multipletests
from statsmodels.tsa.seasonal import seasonal_decompose


def find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "RUNLOG.md").exists() and (p / "src" / "ramadan_surge.py").exists():
            return p
    raise FileNotFoundError("project root with RUNLOG.md and src/ramadan_surge.py not found")


ROOT = find_root(Path.cwd().resolve())
sys.path.insert(0, str(ROOT / "src"))
import ramadan_surge as rs  # noqa: E402
import workbook  # noqa: E402

RAW, CLEAN, OUT = ROOT / "data" / "raw", ROOT / "data" / "clean", ROOT / "outputs"
FIG = OUT / "figures"
for folder in (CLEAN, FIG):
    folder.mkdir(parents=True, exist_ok=True)

SEED = 42
np.random.seed(SEED)  # legacy global seed for any library that still uses it


def rng_for(stage: str) -> np.random.Generator:
    # Independent, reproducible random stream per analysis stage (seed 42 + stage label).
    return np.random.default_rng([SEED, zlib.crc32(stage.encode())])


N_SIM = 10_000
print(f"Global random seed: {SEED}")
print(f"Monte Carlo draws per simulation: {N_SIM:,}")
print(f"Python {sys.version.split()[0]} | pandas {pd.__version__} | numpy {np.__version__} | "
      f"scipy {scipy.__version__} | statsmodels {statsmodels.__version__} | matplotlib {matplotlib.__version__}")
""")

md("""
Why: all charts follow one publication style (black and white only; series are told apart by line style, marker and hatching), every chart carries a title, axis labels and units, and every chart is saved as PNG to `outputs/figures/`. Commodity names, units and styles are defined once here.
""")
code("""
plt.rcParams.update({
    "figure.dpi": 100, "savefig.dpi": 200, "font.family": "DejaVu Sans", "font.size": 9,
    "axes.prop_cycle": cycler(color=["black"]), "axes.edgecolor": "black", "axes.labelcolor": "black",
    "axes.titleweight": "bold", "axes.titlesize": 9.5, "xtick.color": "black", "ytick.color": "black",
    "legend.edgecolor": "black", "legend.fontsize": 7.5, "figure.facecolor": "white",
    "axes.facecolor": "white", "savefig.facecolor": "white", "lines.linewidth": 1.2,
    "hatch.color": "black", "hatch.linewidth": 0.6, "axes.grid": False,
})

COMMODITIES = ["rice", "lentils", "palm_oil", "wheat_flour"]
LABEL = {"rice": "Rice (coarse)", "lentils": "Lentils (masur)", "palm_oil": "Palm oil", "wheat_flour": "Wheat flour"}
UNIT = {"rice": "BDT/kg", "lentils": "BDT/kg", "palm_oil": "BDT/litre", "wheat_flour": "BDT/kg"}
LS = {"rice": "-", "lentils": "--", "palm_oil": ":", "wheat_flour": "-."}
MK = {"rice": "o", "lentils": "s", "palm_oil": "^", "wheat_flour": "D"}
HATCH = {"rice": "", "lentils": "///", "palm_oil": "...", "wheat_flour": "xxx"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
FIGURES: list[str] = []


def savefig(fig, name: str) -> Path:
    path = FIG / f"{name}.png"
    fig.savefig(path, bbox_inches="tight")
    FIGURES.append(path.name)
    return path


def pct(x: float, digits: int = 1) -> str:
    return f"{100 * x:.{digits}f}%"


pd.set_option("display.width", 170)
pd.set_option("display.max_columns", 30)
pd.set_option("display.precision", 4)
print("Commodities:", ", ".join(f"{LABEL[c]} ({UNIT[c]})" for c in COMMODITIES))
""")

# =============================================================================
md("""
## 1 Data sources

Why: the brief requires real, citable data. Sources were tried in the prescribed order and the search stopped at the first one that passed the quality gate:

1. **HDX "Bangladesh - Food Prices" (WFP price database)**, found with the CKAN API (`package_search`, then `package_show`), CSV downloaded by `scripts/download_data.py`. **Passed the gate**, so sources 2 to 4 (World Bank Real Time Food Prices, AgriPriceBD on Mendeley Data, other web sources) were not needed.

Every search, download and decision is logged in `RUNLOG.md`; URL, access date, licence, row count, date range, columns and the SHA-256 checksum are in `data/raw/SOURCES.md`. The cell below prints that record and verifies that the local file is byte-identical to the one recorded.
""")
code("""
sources_md = (RAW / "SOURCES.md").read_text(encoding="utf-8")
print(sources_md)
match = re.search(r"## wfp_food_prices_bgd\\.csv.*?SHA-256: `([0-9a-f]{64})`", sources_md, re.S)
actual_sha = hashlib.sha256((RAW / "wfp_food_prices_bgd.csv").read_bytes()).hexdigest()
assert match and actual_sha == match.group(1), "raw file differs from the one recorded in SOURCES.md"
raw = pd.read_csv(RAW / "wfp_food_prices_bgd.csv")
print(f"SHA-256 verified ({actual_sha[:16]}...). Raw rows: {len(raw):,}; columns: {list(raw.columns)}")
display(raw.head())
""")

md("""
Why: before choosing commodities we look at what the file actually contains. Only retail prices in BDT are relevant. Sugar, onion and soybean oil (preferred in the brief) only start in 2024, so they cannot meet the 8-year rule; the four long-running staples are coarse rice, masur lentils, palm oil and wheat flour. (One fuel row dated 1900-08-15 is an obvious date error; it is non-food and is dropped by the commodity filter.)
""")
code("""
retail_all = raw[(raw["pricetype"] == "Retail") & (raw["currency"] == "BDT")].assign(date=lambda d: pd.to_datetime(d["date"]))
overview = (retail_all.groupby(["commodity", "unit"])
            .agg(observations=("price", "size"), markets=("market", "nunique"), first=("date", "min"), last=("date", "max"))
            .assign(years=lambda d: ((d["last"] - d["first"]).dt.days / 365.25).round(1))
            .sort_values("observations", ascending=False))
display(overview.head(12))
for name in ["Sugar", "Onions (imported, China)", "Oil (soybean, fortified)"]:
    row = overview.xs(name, level="commodity").iloc[0]
    print(f"{name}: {row['first'].date()} to {row['last'].date()} ({row['years']} years) -> fails the 8-year rule")
""")

md("""
Why: the quality gate is checked in code, not asserted by hand. The gate is applied to the main series (Dhaka Division market): at least 8 years of monthly data, at least 4 staples, retail price type, one unit per commodity and at least 6 Ramadan periods with both baseline and flag month inside the data.
""")
code("""
STAPLES = {"Rice (coarse)": "rice", "Lentils (masur)": "lentils", "Oil (palm)": "palm_oil", "Wheat flour": "wheat_flour"}
MAIN_MARKET = "Dhaka Division"
main_raw = retail_all[(retail_all["market"] == MAIN_MARKET) & retail_all["commodity"].isin(STAPLES)]
per_c = main_raw.groupby("commodity").agg(first=("date", "min"), last=("date", "max"),
                                          months=("date", "nunique"), units=("unit", "nunique"))
gate_first = per_c["first"].max().to_period("M").to_timestamp()
gate_last = per_c["last"].min().to_period("M").to_timestamp()
gate_years = (gate_last - gate_first).days / 365.25
gate_cal = rs.ramadan_calendar(gate_first.year, gate_last.year)
gate_ramadans = int(((gate_cal["baseline_m1"] >= gate_first) & (gate_cal["flag_month"] <= gate_last)).sum())
gate = pd.DataFrame([
    ("Years of monthly data (common span)", ">= 8", round(gate_years, 1), gate_years >= 8),
    ("Staple commodities", ">= 4", len(per_c), len(per_c) >= 4),
    ("Price type", "Retail", ", ".join(main_raw["pricetype"].unique()), set(main_raw["pricetype"]) == {"Retail"}),
    ("Units per commodity", "1", int(per_c["units"].max()), per_c["units"].max() == 1),
    ("Ramadan periods covered", ">= 6", gate_ramadans, gate_ramadans >= 6),
], columns=["criterion", "requirement", "observed", "pass"])
display(per_c)
display(gate)
assert gate["pass"].all(), "quality gate failed: see STOP CONDITIONS"
print(f"Quality gate PASSED for {MAIN_MARKET}: {gate_first:%Y-%m} to {gate_last:%Y-%m}.")
""")

# =============================================================================
md("""
## 2 Cleaning

Why: every cleaning rule is explicit, applied in code and logged, so that nothing is silently changed. The rules are:

1. Standardise column names (lower case, underscores), parse dates, and map each WFP date (stamped mid-month) to the first day of its month.
2. Keep retail prices in BDT for the four staples.
3. Remove exact duplicate rows and check that no month, market and commodity has two different prices; remove non-positive prices.
4. Check that each commodity has a single unit (kg or litre).
5. **Suspected recording errors.** A run of 1 to 3 months in one market that moves more than 25% (log) away from the previous month and then returns to within 10% of it is a *candidate*. It is confirmed only if the other markets did not move the same way in those months (their median move is less than half of the candidate's). Confirmed values are set to missing, never replaced. Nationwide moves such as a real Ramadan surge cannot be removed by this rule.
6. **Gaps.** A single missing month is filled with the mean of its two neighbours. A run of two missing months is filled by linear interpolation between the neighbours (each filled value is a distance-weighted average of the two neighbours). Runs longer than two months are **never** filled. Every filled cell is logged.
7. **Main series:** Dhaka Division market. **Robustness series:** an all-market national average built as a matched-market chained index (explained in 2.5).
8. Save the cleaned monthly data to `data/clean/prices_monthly.csv`.
""")
code("""
steps = [("Raw rows (all commodities, markets, price types)", len(raw))]
df = raw.copy()
df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
df["date"] = pd.to_datetime(df["date"], errors="raise")
df["month"] = df["date"].dt.to_period("M").dt.to_timestamp()
df = df[df["pricetype"].eq("Retail")]
steps.append(("Retail price type only", len(df)))
df = df[df["currency"].eq("BDT")]
steps.append(("Currency BDT", len(df)))
df = df[df["commodity"].isin(STAPLES)].assign(commodity_key=lambda d: d["commodity"].map(STAPLES))
steps.append(("Four staple commodities", len(df)))
key = ["month", "market_id", "commodity_key"]
exact_dups = int(df.duplicated(key + ["price"]).sum())
df = df.drop_duplicates(key + ["price"])
steps.append(("Exact duplicates removed", len(df)))
conflicts = int(df.duplicated(key, keep=False).sum())
assert conflicts == 0, f"{conflicts} conflicting prices for the same month, market and commodity"
nonpos = int((df["price"] <= 0).sum())
df = df[df["price"] > 0]
steps.append(("Non-positive prices removed", len(df)))
assert df.groupby("market")["market_id"].nunique().max() == 1, "market names are not unique"
display(pd.DataFrame(steps, columns=["step", "rows remaining"]))
print(f"Exact duplicates removed: {exact_dups}; conflicting duplicates: {conflicts}; non-positive prices removed: {nonpos}")
""")

md("""
Why: a commodity reported in two units (for example kg and 50 kg bag) cannot be averaged. We also show the WFP price flags: `actual` values were collected as reported, `aggregate` values were aggregated by WFP from higher-frequency data. Both are kept, but this is noted as a limitation (some values may be estimated).
""")
code("""
units = df.groupby("commodity_key")["unit"].unique()
assert all(len(u) == 1 for u in units), "a commodity has more than one unit"
assert {units[c][0] for c in COMMODITIES} == {"KG", "L"}
display(units.apply(lambda u: u[0]).rename("unit").to_frame().T)
display(df.groupby(["commodity_key", "priceflag"]).size().unstack(fill_value=0))
""")

md("""
Why: plotting the division markets revealed an implausible pattern for coarse rice in 2017: three divisions drop by about 40% for exactly three months and return, while the other divisions stay flat. Rule 5 detects such spike-and-revert runs systematically across *all* markets and commodities; the table lists every excluded observation and the figure shows the 2017 case.
""")
code("""
df_before_errors = df.copy()
error_rows = []
for c in COMMODITIES:
    panel = df[df["commodity_key"].eq(c)].pivot_table(index="month", columns="market", values="price")
    panel = panel.reindex(pd.date_range(panel.index.min(), panel.index.max(), freq="MS"))
    flags = rs.flag_panel_errors(panel)
    for month, market in zip(*np.nonzero(flags.to_numpy())):
        t, m = flags.index[month], flags.columns[market]
        error_rows.append({"commodity": c, "market": m, "month": t, "price": panel.at[t, m]})
errors = pd.DataFrame(error_rows, columns=["commodity", "market", "month", "price"])
error_keys = set(zip(errors["commodity"], errors["market"], errors["month"]))
is_error = np.array([k in error_keys for k in zip(df["commodity_key"], df["market"], df["month"])], dtype=bool)
df = df[~is_error]
print(f"Suspected recording errors excluded: {len(errors)} of {len(df_before_errors):,} observations "
      f"({100 * len(errors) / len(df_before_errors):.2f}%)")
display(errors.assign(month=errors["month"].dt.strftime("%Y-%m")).sort_values(["commodity", "market", "month"]))

div_rice = (df_before_errors[df_before_errors["commodity_key"].eq("rice") & df_before_errors["market"].str.endswith("Division")]
            .pivot_table(index="month", columns="market", values="price").loc["2016-07":"2018-12"])
fig, ax = plt.subplots(figsize=(8, 3.6))
for m, s, mk in zip(div_rice.columns, ["-", "--", ":", "-.", (0, (5, 1)), (0, (1, 1))], ["o", "s", "^", "D", "v", "P"]):
    ax.plot(div_rice.index, div_rice[m], linestyle=s, marker=mk, markersize=3, label=m.replace(" Division", ""))
e = errors[errors["commodity"].eq("rice") & errors["market"].str.endswith("Division")
           & errors["month"].between(div_rice.index.min(), div_rice.index.max())]
ax.scatter(e["month"], e["price"], s=90, facecolors="none", edgecolors="black", linewidths=1.3,
           zorder=5, label="Excluded (suspected error)")
ax.set(title="Coarse rice, division markets: suspected recording errors, 2017",
       xlabel="Month", ylabel="Retail price (BDT/kg)")
ax.legend(ncol=4, loc="lower left")
savefig(fig, "fig02_suspected_errors_rice_2017")
plt.show()
""")

md("""
Why: the main series is one consistent market. WFP reports *division-level* markets until mid-2020 and *district-level* markets afterwards, so "Dhaka Division" is the longest single Dhaka series. The window starts at the first month from which no commodity has a raw gap longer than two months and ends at the last month in which all four are observed. Gaps are then filled under rule 6 and every filled cell is logged; gaps that may not be filled are listed separately.
""")
code("""
def market_panel(frame: pd.DataFrame, market: str) -> pd.DataFrame:
    sub = frame[frame["market"].eq(market)]
    return sub.pivot_table(index="month", columns="commodity_key", values="price").reindex(columns=COMMODITIES)


dh_before = market_panel(df_before_errors, MAIN_MARKET)
DH_END = min(dh_before[c].last_valid_index() for c in COMMODITIES)
DH_START = max(rs.first_month_after_long_gaps(dh_before[c], DH_END) for c in COMMODITIES)
dh_obs = market_panel(df, MAIN_MARKET).reindex(pd.date_range(DH_START, DH_END, freq="MS"))
dh_parts, fill_logs = {}, []
for c in COMMODITIES:
    filled, log = rs.fill_short_gaps(dh_obs[c])
    dh_parts[c] = filled
    fill_logs.append(log.assign(series="Dhaka", commodity=c))
dh = pd.DataFrame(dh_parts)
print(f"Dhaka window: {DH_START:%Y-%m} to {DH_END:%Y-%m} ({len(dh)} months)")
dh_fill_log = pd.concat(fill_logs, ignore_index=True)
print(f"Filled cells (Dhaka): {len(dh_fill_log)}")
display(dh_fill_log.assign(date=dh_fill_log["date"].dt.strftime("%Y-%m")).round(2))
dh_missing = [(c, t) for c in COMMODITIES for t in dh.index[dh[c].isna()]]
print("Months left missing in the Dhaka series (runs longer than 2 months, never filled):")
display(pd.DataFrame([(LABEL[c], f"{t:%Y-%m}") for c, t in dh_missing], columns=["commodity", "month"]))
""")

md("""
Why (robustness series): a plain average across markets is distorted when the set of reporting markets changes. The number of reporting markets rises from 6 divisions to about 60 districts in 2020, and in some months only one division reports. We therefore build an **all-market matched-sample chained index** (the method used for consumer price indices). Each month's change is the average log price change over markets observed in *both* that month and the previous month; where a month has fewer than 2 matched markets, the change is bridged from the most recent linked month (at any distance; the months in between stay missing and fall under the gap rules). The index is converted to BDT by scaling it so that its mean over the last 12 months equals the simple all-market mean of those months. Unlinked months are then gap-filled under rule 6. This national series is the only one that reaches 2026, so it is used for the forecast of the next Ramadan.
""")
code("""
NAT_START = DH_START
data_end = df["month"].max()
chains, simple_means = {}, {}
for c in COMMODITIES:
    panel = df[df["commodity_key"].eq(c)].pivot_table(index="month", columns="market", values="price")
    panel = panel.reindex(pd.date_range(NAT_START, data_end, freq="MS"))
    chains[c] = rs.chained_index(panel, max_bridge=None)
    simple_means[c] = panel.mean(axis=1)
NAT_END = min(chains[c]["index"].last_valid_index() for c in COMMODITIES)
ANCHOR = pd.date_range(NAT_END - pd.DateOffset(months=11), NAT_END, freq="MS")
nat_parts, nat_logs, diag = {}, [], []
for c in COMMODITIES:
    ci = chains[c].loc[NAT_START:NAT_END]
    k = float((simple_means[c].loc[ANCHOR] / ci["index"].loc[ANCHOR]).mean())
    filled, log = rs.fill_short_gaps(ci["index"] * k)
    nat_parts[c] = filled
    nat_logs.append(log.assign(series="National", commodity=c))
    both = pd.concat([np.log(ci["index"]).diff(), np.log(simple_means[c].loc[NAT_START:NAT_END]).diff()], axis=1).dropna()
    diag.append({"commodity": LABEL[c], "min matched markets": int(ci["n_matched"][ci["n_matched"] > 0].min()),
                 "median matched markets": float(ci["n_matched"][ci["n_matched"] > 0].median()),
                 "months bridged": int((ci["lag"] > 1).sum()), "months unlinked": int(ci["index"].isna().sum()),
                 "months filled": len(log), "BDT anchor factor": round(k, 3),
                 "corr. of monthly changes with simple mean": round(both.corr().iloc[0, 1], 3)})
nat = pd.DataFrame(nat_parts)
nat_fill_log = pd.concat(nat_logs, ignore_index=True)
print(f"National window: {NAT_START:%Y-%m} to {NAT_END:%Y-%m} ({len(nat)} months)")
display(pd.DataFrame(diag))
display(nat_fill_log.assign(date=nat_fill_log["date"].dt.strftime("%Y-%m")).round(2))
assert not nat.isna().any().any(), "national series still has gaps longer than 2 months"
""")

md("""
Why: a visual check that the two series agree where they overlap (2006 to 2020) and that no artificial jumps remain at the 2020 change from division to district markets.
""")
code("""
fig, axes = plt.subplots(2, 2, figsize=(11, 6.4), sharex=True)
for ax, c in zip(axes.flat, COMMODITIES):
    ax.plot(nat.index, nat[c], ls="--", lw=1.0, label="National (chained index, BDT)")
    ax.plot(dh.index, dh[c], ls="-", lw=1.2, label="Dhaka Division")
    ax.axvline(pd.Timestamp("2020-07-01"), color="black", lw=0.6, ls=":")
    ax.set(title=LABEL[c], ylabel=f"Retail price ({UNIT[c]})")
for ax in axes[1]:
    ax.set_xlabel("Month")
axes[0, 0].legend(loc="upper left")
axes[0, 0].annotate("division to district\\nmarkets (2020-07)", xy=(pd.Timestamp("2020-07-01"), axes[0, 0].get_ylim()[0]),
                    xytext=(5, 5), textcoords="offset points", fontsize=7)
fig.suptitle("Monthly retail prices: Dhaka Division (main) and national chained index (robustness)", fontweight="bold")
fig.tight_layout()
savefig(fig, "fig01_price_series")
plt.show()
""")

md("""
Why: the cleaned data is saved in one tidy file (one row per month, series and commodity) together with the logs of filled cells and excluded observations, so later work does not need to repeat the cleaning.
""")
code("""
def to_long(frame: pd.DataFrame, series: str, log: pd.DataFrame) -> pd.DataFrame:
    filled = set(zip(log["commodity"], log["date"]))
    long = frame.rename_axis("date").reset_index().melt(id_vars="date", var_name="commodity", value_name="price_bdt")
    return long.assign(series=series, unit=long["commodity"].map(UNIT),
                       imputed=[(c, d) in filled for c, d in zip(long["commodity"], long["date"])])


prices_long = pd.concat([to_long(dh, "Dhaka", dh_fill_log), to_long(nat, "National", nat_fill_log)], ignore_index=True)
prices_long = prices_long[["date", "series", "commodity", "unit", "price_bdt", "imputed"]]
prices_long.to_csv(CLEAN / "prices_monthly.csv", index=False, date_format="%Y-%m-%d")
pd.concat([dh_fill_log, nat_fill_log]).to_csv(CLEAN / "filled_cells_log.csv", index=False, date_format="%Y-%m")
errors.to_csv(CLEAN / "excluded_suspected_errors.csv", index=False, date_format="%Y-%m")
print(f"Saved {len(prices_long):,} rows to data/clean/prices_monthly.csv "
      f"({int(prices_long['imputed'].sum())} imputed, {int(prices_long['price_bdt'].isna().sum())} missing)")
""")

# =============================================================================
md("""
## 3 Ramadan calendar

Why: Ramadan follows the lunar Hijri calendar and moves about 11 days earlier each Gregorian year, so its dates must be computed, not hard-coded. We use `hijridate` (Umm al-Qura tables, the Saudi official calendar) and cross-check against the arithmetic Islamic calendar in `convertdate`. Because Bangladesh often starts Ramadan one day after Saudi Arabia, every date is also computed with a +1 day shift.

Definitions (assumptions):
* **Flag month** = the Gregorian month containing most Ramadan days.
* **Baseline** = mean price of the two calendar months before the month in which Ramadan starts (so the baseline never contains Ramadan days).
* **Marginal year** = less than 60% of Ramadan days fall in the flag month (an almost even split). Marginal years are kept but marked, and summaries are also shown without them.
""")
code("""
CAL_FIRST, CAL_LAST = NAT_START.year, (NAT_END + pd.DateOffset(years=1)).year
cal0 = rs.ramadan_calendar(CAL_FIRST, CAL_LAST, offset_days=0)
cal1 = rs.ramadan_calendar(CAL_FIRST, CAL_LAST, offset_days=1)
assert list(cal0["hijri_year"]) == list(cal1["hijri_year"])
arith_start = [pd.Timestamp(rs.ramadan_dates(h, "arithmetic")[0]) for h in cal0["hijri_year"]]
cal_view = pd.DataFrame({
    "Hijri year": cal0["hijri_year"], "Start (Umm al-Qura)": cal0["start"].dt.date, "End": cal0["end"].dt.date,
    "Days": cal0["n_days"], "Flag month": cal0["flag_month"].dt.strftime("%Y-%m"),
    "Share in flag month": cal0["flag_share"].round(2), "Marginal": cal0["marginal"],
    "Flag month (+1 day)": cal1["flag_month"].dt.strftime("%Y-%m"),
    "Flag changes (+1)": cal0["flag_month"].ne(cal1["flag_month"]),
    "Baseline changes (+1)": cal0["start_month"].ne(cal1["start_month"]),
    "Arithmetic start minus Umm al-Qura (days)": [(a - s).days for a, s in zip(arith_start, cal0["start"])],
})
display(cal_view)
""")

md("""
Why: we report whether the +1 day Bangladesh shift changes any flag month or baseline window. If it does, the surge table is recomputed under both calendars in section 5. We also fix the analysis windows and the forecast target: the first Ramadan whose flag month lies after the end of the national data.
""")
code("""
changed = cal_view[cal_view["Flag changes (+1)"] | cal_view["Baseline changes (+1)"]]
print(f"Ramadan periods computed: {len(cal0)} (Hijri {cal0['hijri_year'].min()} to {cal0['hijri_year'].max()})")
if changed.empty:
    print("+1 day sensitivity: no flag month and no baseline window changes.")
else:
    print(f"+1 day sensitivity: {len(changed)} Ramadan(s) change flag month or baseline window:")
    display(changed)
print("Marginal years (flag share < 0.6):",
      ", ".join(f"{r.gregorian_year} ({r.flag_share:.2f})" for r in cal0.itertuples() if r.marginal) or "none")
print("Largest difference between the two calendar libraries:",
      max(abs(d) for d in cal_view["Arithmetic start minus Umm al-Qura (days)"]), "day(s)")


def in_window(cal: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return cal[(cal["baseline_m1"] >= start) & (cal["flag_month"] <= end)].reset_index(drop=True)


CAL = cal0.copy()
cal_dh, cal_nat = in_window(CAL, DH_START, DH_END), in_window(CAL, NAT_START, NAT_END)
TARGET = CAL[CAL["flag_month"] > NAT_END].iloc[0]
print(f"Ramadans inside the Dhaka window: {len(cal_dh)} ({cal_dh['gregorian_year'].min()} to {cal_dh['gregorian_year'].max()})")
print(f"Ramadans inside the national window: {len(cal_nat)} ({cal_nat['gregorian_year'].min()} to {cal_nat['gregorian_year'].max()})")
print(f"Forecast target: Ramadan {TARGET['hijri_year']} AH, {TARGET['start']:%d %b %Y} to {TARGET['end']:%d %b %Y}; "
      f"flag month {TARGET['flag_month']:%b %Y}; baseline months {TARGET['baseline_m1']:%b %Y} and {TARGET['baseline_m2']:%b %Y}")
""")

md("""
Why: the drift of Ramadan through the Gregorian year is what makes it possible to separate a Ramadan effect from ordinary calendar-month seasonality. Over the 2006 to 2026 window Ramadan moves from autumn to late winter.
""")
code("""
fig, ax = plt.subplots(figsize=(8, 3.4))
doy = CAL["start"].dt.dayofyear
ax.plot(CAL["gregorian_year"], doy, marker="o", lw=1.0, label="Start, Umm al-Qura")
ax.scatter(CAL.loc[CAL["marginal"], "gregorian_year"], doy[CAL["marginal"]], s=90, facecolors="none",
           edgecolors="black", label="Marginal year (flag share < 0.6)")
month_starts = pd.date_range("2001-01-01", periods=12, freq="MS").dayofyear
ax.set_yticks(month_starts, MONTHS)
ax.set(title="Ramadan start date drifts about 11 days earlier each year", xlabel="Gregorian year of Ramadan start",
       ylabel="Calendar month of start")
ax.legend(loc="upper right")
savefig(fig, "fig03_ramadan_drift")
plt.show()
""")

# =============================================================================
md("""
## 4 Decomposition

Why: a multiplicative decomposition (price = trend x seasonal x residual, period 12) shows how much of the monthly pattern is ordinary calendar seasonality. We compute it twice: with `statsmodels.seasonal_decompose` and with a manual ratio-to-centred-moving-average (2 x 12 MA) implementation, and show that the two agree. The manual version tolerates missing months, so it also runs on the Dhaka rice series, which keeps an unfillable 3-month gap after the 2017 error exclusion; `statsmodels` requires a complete series and is not run there.
""")
code("""
SERIES = {"Dhaka": dh, "National": nat}
dec_manual, dec_sm, agree_rows = {}, {}, []
for s_name, frame in SERIES.items():
    for c in COMMODITIES:
        x = frame[c]
        man = rs.ratio_to_cma(x)
        dec_manual[(s_name, c)] = man
        row = {"series": s_name, "commodity": LABEL[c]}
        if x.isna().any():
            agree_rows.append({**row, "statsmodels": "not run (unfilled gap)"})
            continue
        res = seasonal_decompose(x, model="multiplicative", period=12)
        dec_sm[(s_name, c)] = res
        both = man["trend"].notna() & res.trend.notna()
        agree_rows.append({**row, "statsmodels": "run",
                           "max abs diff, seasonal index": float((man["seasonal"] - res.seasonal).abs().max()),
                           "max abs rel. diff, trend": float((man["trend"][both] / res.trend[both] - 1).abs().max()),
                           "max abs diff, residual": float((man["resid"] - res.resid).abs().max())})
agree = pd.DataFrame(agree_rows)
display(agree)
print(f"Largest disagreement between statsmodels and the manual method: "
      f"{agree.select_dtypes('number').max().max():.2e} (numerical rounding only)")
""")

md("""
Why: the seasonal index of each calendar month (in % above or below the trend) summarises ordinary seasonality. Note that an index for, say, March also contains any Ramadan months that happened to fall in March, which is why section 4.4 adds a moving Ramadan dummy.
""")
code("""
def month_index(dec: pd.DataFrame) -> pd.Series:
    s = dec["seasonal"]
    return s.groupby(s.index.month).first()


seasonal_table = pd.DataFrame({(s, LABEL[c]): (month_index(dec_manual[(s, c)]) - 1) * 100
                               for s in SERIES for c in COMMODITIES})
seasonal_table.index = MONTHS
seasonal_table.loc["Range (max - min)"] = seasonal_table.max() - seasonal_table.min()
print("Seasonal index, % deviation from trend (manual ratio-to-CMA):")
display(seasonal_table.round(2))
""")

md("""
Why: the plots show, for each commodity, the observed series with the two trend estimates, the seasonal index from both methods (the two lines lie on top of each other) and the residual.
""")
code("""
def plot_decomposition(s_name: str, fig_name: str) -> None:
    fig, axes = plt.subplots(4, 3, figsize=(12, 10.5), gridspec_kw={"width_ratios": [2.2, 1.1, 2.2]})
    legend_row = next(i for i, c in enumerate(COMMODITIES) if (s_name, c) in dec_sm)
    for i, c in enumerate(COMMODITIES):
        man, res = dec_manual[(s_name, c)], dec_sm.get((s_name, c))
        ax = axes[i, 0]
        ax.plot(man.index, man["observed"], lw=0.7, label="Observed")
        if res is not None:
            ax.plot(res.trend.index, res.trend, lw=2.0, label="Trend, statsmodels")
        ax.plot(man.index, man["trend"], lw=1.0, ls=(0, (2, 2)), label="Trend, manual 2x12 CMA")
        ax.set(title=f"{LABEL[c]}: observed and trend", ylabel=f"Price ({UNIT[c]})")
        ax = axes[i, 1]
        if res is not None:
            ax.plot(range(1, 13), res.seasonal.groupby(res.seasonal.index.month).first(), marker="o", ms=4,
                    label="statsmodels")
        ax.plot(range(1, 13), month_index(man), marker="x", ms=6, ls="--", label="manual ratio-to-CMA")
        ax.axhline(1, lw=0.5)
        ax.set_xticks(range(1, 13), [m[0] for m in MONTHS])
        ax.set(title=f"{LABEL[c]}: seasonal index", ylabel="Index (1 = trend)")
        ax = axes[i, 2]
        ax.plot(man.index, man["resid"], lw=0.7)
        ax.axhline(1, lw=0.5, ls=":")
        ax.set(title=f"{LABEL[c]}: residual (manual)", ylabel="Ratio to trend x season")
    axes[legend_row, 0].legend(loc="upper left")
    axes[legend_row, 1].legend(loc="best")
    axes[3, 0].set_xlabel("Month")
    axes[3, 1].set_xlabel("Calendar month")
    axes[3, 2].set_xlabel("Month")
    fig.suptitle(f"Multiplicative decomposition, period 12: {s_name} series (statsmodels vs manual)", fontweight="bold")
    fig.tight_layout()
    savefig(fig, fig_name)
    plt.show()


plot_decomposition("Dhaka", "fig04_decomposition_dhaka")
plot_decomposition("National", "fig05_decomposition_national")
""")

md("""
Why: a calendar-month seasonal index cannot tell a March effect from a Ramadan-in-March effect. We therefore estimate three regressions per series and commodity (HAC Newey-West standard errors with 12 lags, because monthly prices are strongly autocorrelated):

* **A:** log(price) ~ linear trend + month effects (calendar seasonality only)
* **B:** log(price) ~ linear trend + month effects + Ramadan dummy (the model in the brief)
* **C:** log(price / centred moving-average trend) ~ month effects + Ramadan dummy (robustness: replaces the single linear trend, which fits 14 to 20 years of prices poorly, by the flexible decomposition trend)

The Ramadan dummy is 1 in the flag month. Its coefficient b is reported as a percentage effect, exp(b) - 1, with a 95% confidence interval.
""")
code("""
def ramadan_regressions(series: pd.Series, trend: pd.Series, flag_months) -> dict:
    d = pd.DataFrame({"price": series, "trend": trend})
    d["logp"] = np.log(d["price"])
    d["t"] = (d.index.year - d.index[0].year) * 12 + d.index.month - d.index[0].month
    d["month"] = d.index.month
    d["ramadan"] = d.index.isin(pd.DatetimeIndex(flag_months)).astype(int)
    d["dev"] = np.log(d["price"] / d["trend"])
    hac = {"cov_type": "HAC", "cov_kwds": {"maxlags": 12}}
    obs = d.dropna(subset=["logp"])
    return {"A": smf.ols("logp ~ t + C(month)", obs).fit(**hac),
            "B": smf.ols("logp ~ t + C(month) + ramadan", obs).fit(**hac),
            "C": smf.ols("dev ~ C(month) + ramadan", d.dropna(subset=["dev"])).fit(**hac)}


REG, reg_rows = {}, []
for s_name, frame in SERIES.items():
    flags = (cal_dh if s_name == "Dhaka" else cal_nat)["flag_month"]
    for c in COMMODITIES:
        fits = ramadan_regressions(frame[c], dec_manual[(s_name, c)]["trend"], flags)
        REG[(s_name, c)] = fits
        for m in ("B", "C"):
            f = fits[m]
            lo, hi = f.conf_int().loc["ramadan"]
            reg_rows.append({"series": s_name, "commodity": LABEL[c], "model": m, "n months": int(f.nobs),
                             "Ramadan months": int(f.model.exog[:, f.model.exog_names.index("ramadan")].sum()),
                             "Ramadan effect %": 100 * np.expm1(f.params["ramadan"]),
                             "95% CI low %": 100 * np.expm1(lo), "95% CI high %": 100 * np.expm1(hi),
                             "p-value": f.pvalues["ramadan"], "R2": f.rsquared})
reg_table = pd.DataFrame(reg_rows)
display(reg_table.round(3))
""")

md("""
Why: comparing the month effects of model A (no dummy) and model B (with dummy) shows how much of the "calendar" seasonality was really Ramadan. The figure overlays, for the national series, the decomposition seasonal index and the normalised month effects of models A and B.
""")
code("""
def month_effects(fit) -> pd.Series:
    coefs = np.array([0.0] + [fit.params.get(f"C(month)[T.{m}]", np.nan) for m in range(2, 13)])
    idx = np.exp(coefs)
    return pd.Series(idx / idx.mean(), index=range(1, 13))


shift_rows = []
for (s_name, c), fits in REG.items():
    a, b = month_effects(fits["A"]), month_effects(fits["B"])
    diff = (b - a) * 100
    shift_rows.append({"series": s_name, "commodity": LABEL[c],
                       "max abs change in a month effect (pp)": float(diff.abs().max()),
                       "month most affected": MONTHS[int(diff.abs().idxmax()) - 1]})
display(pd.DataFrame(shift_rows).round(2))

fig, axes = plt.subplots(1, 4, figsize=(13, 3.2), sharey=True)
for ax, c in zip(axes, COMMODITIES):
    ax.plot(range(1, 13), month_index(dec_manual[("National", c)]), marker="o", ms=4, label="Decomposition index")
    ax.plot(range(1, 13), month_effects(REG[("National", c)]["A"]), marker="s", ms=3, ls="--", label="Regression A (no dummy)")
    ax.plot(range(1, 13), month_effects(REG[("National", c)]["B"]), marker="^", ms=3, ls=":", label="Regression B (+ Ramadan)")
    ax.axhline(1, lw=0.5)
    ax.set_xticks(range(1, 13), [m[0] for m in MONTHS])
    ax.set(title=LABEL[c], xlabel="Calendar month")
axes[0].set_ylabel("Month effect (1 = average month)")
axes[0].legend(loc="lower left")
fig.suptitle("National series: calendar-month effects with and without the moving Ramadan dummy", fontweight="bold")
fig.tight_layout()
savefig(fig, "fig06_month_effects_vs_ramadan_dummy")
plt.show()
""")

# =============================================================================
md("""
## 5 Surge table

Why: the direct, model-free measure of the Ramadan effect is the surge, **Surge% = price in flag month / baseline - 1**, computed for every commodity and Ramadan year. Surges are computed for both series; the national series (longer, reaching the present) is the basis for the simulation and the Dhaka series (ending in 2020) is the comparison. The number of Ramadans in each window is printed in section 3.
""")
code("""
surge_dh = rs.surge_table(dh, cal_dh).assign(series="Dhaka")
surge_nat = rs.surge_table(nat, cal_nat).assign(series="National")
SURGES = {"Dhaka": surge_dh, "National": surge_nat}
for name, s in SURGES.items():
    print(f"{name}: {s['hijri_year'].nunique()} Ramadans, {len(s)} commodity-year surges (% shown)")
    display((s.pivot_table(index=["year", "marginal"], columns="commodity", values="surge")[COMMODITIES] * 100).round(1))
""")

md("""
Why: the summary statistics requested (mean, SD, min, max, coefficient of variation) are shown for all years and for non-marginal years only, plus a pooled row across commodities. A CV above 1 means year-to-year variation is larger than the average surge itself, an early sign that the surge is not a reliable, fixed markup.
""")
code("""
def summary_table(s: pd.DataFrame) -> pd.DataFrame:
    per = rs.summarize_surges(s).reindex(COMMODITIES)
    pooled = rs.summarize_surges(s.assign(commodity="pooled"))
    out = pd.concat([per, pooled])
    out[["mean", "sd", "min", "max"]] *= 100
    return out.rename(columns={"mean": "mean %", "sd": "SD %", "min": "min %", "max": "max %", "cv": "CV"})


surge_summary = pd.concat({(name, sample): summary_table(s if sample == "all years" else s[~s["marginal"]])
                           for name, s in SURGES.items() for sample in ("all years", "non-marginal")})
surge_summary.index.names = ["series", "sample", "commodity"]
display(surge_summary.round(2))
""")

md("""
Why: the +1 day sensitivity from section 3 is carried through to the surge numbers themselves.
""")
code("""
sens_rows = []
for name, frame in SERIES.items():
    start, end = (DH_START, DH_END) if name == "Dhaka" else (NAT_START, NAT_END)
    s1 = rs.surge_table(frame, in_window(cal1, start, end))
    m = SURGES[name].merge(s1, on=["hijri_year", "commodity"], suffixes=("", "_plus1"), how="outer")
    d = (m["surge_plus1"] - m["surge"]).abs() * 100
    sens_rows.append({"series": name, "surges compared": int(d.notna().sum()), "surges that change": int((d > 1e-9).sum()),
                      "max abs change (pp)": float(d.max()), "mean surge, +0 (%)": 100 * m["surge"].mean(),
                      "mean surge, +1 (%)": 100 * m["surge_plus1"].mean()})
display(pd.DataFrame(sens_rows).round(3))
""")

md("""
Why: the bar charts show each year's surge per commodity; marginal years are hatched and the dashed line is the mean.
""")
code("""
def plot_surges(name: str, fig_name: str) -> None:
    s = SURGES[name]
    fig, axes = plt.subplots(2, 2, figsize=(11, 6.2), sharex=True)
    for ax, c in zip(axes.flat, COMMODITIES):
        sub = s[s["commodity"].eq(c)].sort_values("year")
        ax.bar(sub["year"], sub["surge"] * 100, color="white", edgecolor="black", linewidth=0.8,
               hatch=["////" if m else "" for m in sub["marginal"]])
        ax.axhline(0, lw=0.6)
        ax.axhline(sub["surge"].mean() * 100, ls="--", lw=1.0)
        ax.set(title=f"{LABEL[c]} ({UNIT[c]})", ylabel="Surge vs 2-month baseline (%)")
    for ax in axes[1]:
        ax.set_xlabel("Ramadan year (Gregorian)")
    axes[0, 0].legend(handles=[Patch(facecolor="white", edgecolor="black", label="Ramadan year"),
                               Patch(facecolor="white", edgecolor="black", hatch="////", label="Marginal year"),
                               plt.Line2D([], [], ls="--", color="black", label="Mean surge")], loc="upper left")
    fig.suptitle(f"Ramadan surge by commodity and year: {name} series", fontweight="bold")
    fig.tight_layout()
    savefig(fig, fig_name)
    plt.show()


plot_surges("Dhaka", "fig07_surge_bars_dhaka")
plot_surges("National", "fig08_surge_bars_national")
""")

# =============================================================================
md("""
## 6 Distribution fit

Why: the parametric Monte Carlo needs a distribution for the surge. We fit a **Normal** distribution to the surge and a **Lognormal** distribution to the gross ratio 1 + surge (surges can be negative, so the lognormal cannot be fitted to the surge directly), plus the **empirical** distribution (used by the bootstrap in section 7). Fits are by maximum likelihood.

Tests:
* **Kolmogorov-Smirnov.** Because the parameters are estimated from the same data, the textbook KS p-value is too lenient; we also report a Lilliefors-type p-value from 2,000 parametric-bootstrap refits.
* **Chi-square.** Equal-probability bins with an expected count of at least 5 per bin; degrees of freedom = bins - 1 - 2 estimated parameters.

With one surge per Ramadan year (a few dozen at most even when pooled) both tests have **low power**: failing to reject a distribution is weak evidence that it is right. The table states this explicitly per sample.
""")
code("""
FAMILIES = ["normal", "lognormal"]
N_KS_BOOT = 2000


def reliability_note(n: int, chi: dict) -> str:
    notes = []
    if n < 30:
        notes.append(f"n={n} < 30: low power, non-rejection is weak evidence")
    if chi["dof"] < 1:
        notes.append("chi-square not computable (dof < 1)")
    elif chi["dof"] < 3:
        notes.append(f"chi-square has only {chi['bins']} bins (dof={chi['dof']}), unreliable")
    return "; ".join(notes) or "sample adequate for both tests"


gof_rows = []
for s_name, s in SURGES.items():
    for sample in COMMODITIES + ["pooled"]:
        x = (s["surge"] if sample == "pooled" else s.loc[s["commodity"].eq(sample), "surge"]).to_numpy()
        for fam in FAMILIES:
            fit = rs.fit_surge_distribution(x, fam)
            ks = rs.ks_lilliefors(x, fam, N_KS_BOOT, rng_for(f"ks-{s_name}-{sample}-{fam}"))
            chi = rs.chi_square_gof(x, fam)
            ll = rs.surge_loglik(x, fit)
            gof_rows.append({"series": s_name, "sample": sample, "n": len(x), "family": fam,
                             "mean %": 100 * fit["mean"], "SD %": 100 * fit["sd"], "AIC": 4 - 2 * ll,
                             "KS D": ks["ks_d"], "KS p naive": ks["p_naive"], "KS p Lilliefors": ks["p_lilliefors"],
                             "chi2 bins": chi["bins"], "chi2": chi["chi2"], "chi2 dof": chi["dof"], "chi2 p": chi["p"],
                             "reliability": reliability_note(len(x), chi)})
gof = pd.DataFrame(gof_rows)
display(gof.round(3))
""")

md("""
Why: the model choice follows a rule fixed *before* looking at the results: for each commodity (national series), among the families **not rejected** at 5% by the Lilliefors KS test or the chi-square test, choose the one with the **lower AIC**; if both are rejected, keep the lower-AIC family for Version A but treat the bootstrap (Version B) as the primary result. The justification is printed by the code.
""")
code("""
CHOSEN, choice_rows = {}, []
for c in COMMODITIES:
    sub = gof[gof["series"].eq("National") & gof["sample"].eq(c)].set_index("family")
    ok = [f for f in FAMILIES if sub.at[f, "KS p Lilliefors"] >= 0.05 and not sub.at[f, "chi2 p"] < 0.05]
    best = min(ok or FAMILIES, key=lambda f: sub.at[f, "AIC"])
    other = next(f for f in FAMILIES if f != best)
    gap = sub.at[other, "AIC"] - sub.at[best, "AIC"]
    CHOSEN[c] = best
    why = (f"{best} chosen: lower AIC ({sub.at[best, 'AIC']:.1f} vs {sub.at[other, 'AIC']:.1f}, difference {gap:.1f}"
           f"{', practically indistinguishable' if gap < 2 else ''}); "
           + (f"not rejected (Lilliefors KS p = {sub.at[best, 'KS p Lilliefors']:.2f}). " if ok else
              "BOTH families rejected, so the bootstrap (Version B) is the primary result for this commodity. ")
           + f"n = {int(sub.at[best, 'n'])}, so the tests have low power.")
    choice_rows.append({"commodity": LABEL[c], "chosen family": best,
                        "families not rejected": ", ".join(ok) or "none", "justification": why})
choice = pd.DataFrame(choice_rows)
with pd.option_context("display.max_colwidth", 400):
    display(choice)
""")

md("""
Why: the histograms with both fitted densities, and the pooled empirical CDF against both fitted CDFs, let the reader judge the fit by eye.
""")
code("""
fig, axes = plt.subplots(2, 2, figsize=(10, 6.2))
for ax, c in zip(axes.flat, COMMODITIES):
    x = surge_nat.loc[surge_nat["commodity"].eq(c), "surge"].to_numpy()
    grid = np.linspace(x.min() - 0.08, x.max() + 0.08, 300)
    ax.hist(x, bins=8, density=True, color="white", edgecolor="black", label="Observed surges")
    fn, fl = rs.fit_surge_distribution(x, "normal"), rs.fit_surge_distribution(x, "lognormal")
    ax.plot(grid, stats.norm.pdf(grid, fn["mu"], fn["sigma"]), lw=1.3, label="Normal fit")
    ax.plot(grid, stats.lognorm.pdf(1 + grid, s=fl["sigma"], scale=np.exp(fl["mu"])), ls="--", lw=1.3, label="Lognormal fit (1 + surge)")
    ax.xaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set(title=f"{LABEL[c]} (chosen: {CHOSEN[c]})", xlabel="Ramadan surge (%)", ylabel="Density")
axes[0, 0].legend(loc="upper right")
fig.suptitle("Distribution of Ramadan surges, national series, 2006 to 2026", fontweight="bold")
fig.tight_layout()
savefig(fig, "fig09_surge_distribution_fit")
plt.show()

xp = np.sort(surge_nat["surge"].to_numpy())
fig, ax = plt.subplots(figsize=(6.5, 3.6))
ax.step(xp, np.arange(1, len(xp) + 1) / len(xp), where="post", lw=1.2, label="Empirical CDF")
for fam, ls in zip(FAMILIES, [":", "--"]):
    ax.plot(xp, rs.surge_cdf(xp, rs.fit_surge_distribution(xp, fam)), ls=ls, lw=1.3, label=f"{fam.capitalize()} fit")
ax.xaxis.set_major_formatter(PercentFormatter(1.0))
ax.set(title="Pooled surges (all commodities), national series", xlabel="Ramadan surge (%)", ylabel="Cumulative probability")
ax.legend(loc="lower right")
savefig(fig, "fig10_pooled_ecdf")
plt.show()
""")

# =============================================================================
md("""
## 7 Monte Carlo simulation of the next Ramadan

Why: the goal is a probability distribution, not a single number, for staple prices in the flag month of the next Ramadan. The simulation has two parts:

**Baseline (pre-Ramadan) price.** For each commodity: seasonal indices from the ratio-to-CMA decomposition; a log-linear trend fitted to the last 36 months of the seasonally adjusted series and extrapolated to the two baseline months; baseline = mean over the two months of trend x seasonal index. Uncertainty comes from the residuals of the trend regression (prediction standard error of a new observation, including parameter uncertainty); the simulated baseline is lognormal with that standard error, and baseline shocks are correlated across commodities using the residual correlation.

**Surge.** *Version A (parametric):* draws from the family chosen in section 6, with per-commodity mean and SD, linked across commodities by a Gaussian copula (rank correlation of past surges). *Version B (bootstrap):* resamples whole past Ramadan years (all four commodities of the same year together, which keeps their co-movement).

**Price** = baseline x (1 + surge). N = 10,000 draws.

The same `run_forecast` function is reused unchanged by the backtest in section 10, with data cut at each forecast origin. The forecast origin is the last month of national data; the number of months between the origin and the month in which the target Ramadan starts (printed below) is reused as the lead time in the backtest.
""")
code("""
TREND_WINDOW = 36
BASKET = {"rice": 40.0, "lentils": 2.0, "palm_oil": 3.0, "wheat_flour": 5.0}
ORIGIN_LAG = (TARGET["start_month"].year - NAT_END.year) * 12 + TARGET["start_month"].month - NAT_END.month


def months_between(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


def forecast_baselines(frame: pd.DataFrame, origin: pd.Timestamp, target: pd.Series,
                       window: int = TREND_WINDOW) -> tuple[pd.DataFrame, pd.DataFrame]:
    hist = frame.loc[:origin]
    months = [target["baseline_m1"], target["baseline_m2"]]
    rows, resid = {}, {}
    for c in COMMODITIES:
        y = hist[c]
        season = rs.ratio_to_cma(y)["seasonal"]
        idx_by_month = season.groupby(season.index.month).first()
        sa = np.log(y / season).dropna().iloc[-window:]
        t = np.array([months_between(sa.index[0], m) for m in sa.index], dtype=float)
        fit = sm.OLS(sa.to_numpy(), sm.add_constant(t)).fit()
        tf = np.array([months_between(sa.index[0], m) for m in months], dtype=float)
        pred = fit.get_prediction(sm.add_constant(tf, has_constant="add"))
        se_obs = np.sqrt(pred.se_mean ** 2 + fit.scale)
        seas = idx_by_month.loc[[m.month for m in months]].to_numpy()
        rows[c] = {"last obs month": y.dropna().index[-1], "last obs price": float(y.dropna().iloc[-1]),
                   "trend slope %/month": 100 * float(fit.params[1]), "seasonal idx m1": seas[0],
                   "seasonal idx m2": seas[1], "baseline_hat": float(np.mean(np.exp(pred.predicted_mean) * seas)),
                   "sigma_log": float(se_obs.mean())}
        resid[c] = pd.Series(fit.resid, index=sa.index)
    return pd.DataFrame.from_dict(rows, orient="index"), pd.DataFrame(resid)


print(f"Forecast origin lag: {ORIGIN_LAG} months before the Ramadan start month; trend window {TREND_WINDOW} months")
print("Assumed monthly household basket (illustrative, not sourced): "
      + ", ".join(f"{LABEL[c]} {q:g} {UNIT[c].split('/')[1]}" for c, q in BASKET.items()))
""")

md("""
Why: the surge model is fitted only to Ramadans that were fully observed before the forecast origin; Version A takes its families either from section 6 (main forecast) or by the AIC rule (backtest refits).
""")
code("""
def fit_surge_models(surges: pd.DataFrame, origin: pd.Timestamp, families: dict | None = None):
    past = surges[surges["flag_month"] <= origin]
    matrix = past.pivot_table(index="hijri_year", columns="commodity", values="surge").reindex(columns=COMMODITIES)
    params = {}
    for c in COMMODITIES:
        x = matrix[c].dropna().to_numpy()
        fits = {f: rs.fit_surge_distribution(x, f) for f in FAMILIES}
        aic = {f: 4 - 2 * rs.surge_loglik(x, fits[f]) for f in FAMILIES}
        fam = (families or {}).get(c) or min(aic, key=aic.get)
        params[c] = {**fits[fam], "n": len(x), "AIC normal": aic["normal"], "AIC lognormal": aic["lognormal"]}
    return params, rs.normal_scores_corr(matrix), matrix


def correlated_normals(corr: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    w, v = np.linalg.eigh(corr)
    root = v @ np.diag(np.sqrt(np.clip(w, 1e-10, None)))
    return rng.standard_normal((n, corr.shape[0])) @ root.T


def draw_shocks(r_base: np.ndarray, r_surge: np.ndarray, n_boot_rows: int, n: int, rng: np.random.Generator) -> dict:
    return {"z_base": correlated_normals(r_base, n, rng), "z_surge": correlated_normals(r_surge, n, rng),
            "boot_idx": rng.integers(0, n_boot_rows, n)}


def prices_from_shocks(shocks: dict, base: pd.DataFrame, params: dict, boot: pd.DataFrame, version: str = "A",
                       surge_mult: float = 1.0, base_mult: float = 1.0, mean_mult: float = 1.0,
                       sd_mult: float = 1.0) -> pd.DataFrame:
    out = {}
    for k, c in enumerate(COMMODITIES):
        b = base.at[c, "baseline_hat"] * base_mult * np.exp(base.at[c, "sigma_log"] * shocks["z_base"][:, k])
        if version == "A":
            p = params[c]
            s = rs.surge_from_z(shocks["z_surge"][:, k], p["family"], p["mean"] * mean_mult, p["sd"] * sd_mult)
        else:
            s = boot[c].to_numpy()[shocks["boot_idx"]]
        s = s * surge_mult
        out[(c, "baseline")], out[(c, "surge")], out[(c, "price")] = b, s, b * (1 + s)
    return pd.DataFrame(out)


def run_forecast(frame, surges, target, origin, families=None, n=N_SIM, tag="main") -> dict:
    base, resid = forecast_baselines(frame, origin, target)
    params, r_surge, matrix = fit_surge_models(surges, origin, families)
    r_base = np.corrcoef(resid.dropna().to_numpy(), rowvar=False)
    boot = matrix.dropna()
    shocks = draw_shocks(r_base, r_surge, len(boot), n, rng_for(f"mc-{tag}"))
    sims = {v: prices_from_shocks(shocks, base, params, boot, version=v) for v in ("A", "B")}
    return {"base": base, "params": params, "r_surge": r_surge, "r_base": r_base, "matrix": matrix,
            "boot": boot, "shocks": shocks, "sims": sims, "origin": origin, "target": target}


def risk_summary(sim: pd.DataFrame, qty: dict = BASKET) -> pd.DataFrame:
    rows = {}
    for c in COMMODITIES:
        p, s = sim[(c, "price")], sim[(c, "surge")]
        rows[c] = {"expected": p.mean(), "p5": p.quantile(0.05), "median": p.median(), "p95": p.quantile(0.95),
                   "mean surge": s.mean(), "P(surge>10%)": (s > 0.10).mean(), "P(surge>20%)": (s > 0.20).mean()}
    cost = sum(qty[c] * sim[(c, "price")] for c in COMMODITIES)
    base_cost = sum(qty[c] * sim[(c, "baseline")] for c in COMMODITIES)
    bs = cost / base_cost - 1
    rows["basket"] = {"expected": cost.mean(), "p5": cost.quantile(0.05), "median": cost.median(),
                      "p95": cost.quantile(0.95), "mean surge": bs.mean(), "P(surge>10%)": (bs > 0.10).mean(),
                      "P(surge>20%)": (bs > 0.20).mean()}
    out = pd.DataFrame.from_dict(rows, orient="index")
    out["price at risk (P95 - expected)"] = out["p95"] - out["expected"]
    return out
""")

md("""
Why: run the main forecast for the next Ramadan from the national series, with the families chosen in section 6, and show its inputs: baseline forecast, surge parameters and the two correlation matrices.
""")
code("""
FC = run_forecast(nat, surge_nat, TARGET, NAT_END, families=CHOSEN, tag=f"ramadan-{TARGET['gregorian_year']}")
print(f"Target: Ramadan {TARGET['hijri_year']} AH, flag month {TARGET['flag_month']:%b %Y}; origin {NAT_END:%b %Y}")
display(FC["base"].assign(**{"last obs month": FC["base"]["last obs month"].dt.strftime("%Y-%m")}).round(4))
display(pd.DataFrame(FC["params"]).T[["family", "n", "mean", "sd", "mu", "sigma", "AIC normal", "AIC lognormal"]])
print("Rank correlation of past surges (Gaussian copula, Version A):")
display(pd.DataFrame(FC["r_surge"], index=COMMODITIES, columns=COMMODITIES).round(2))
print("Correlation of baseline-trend residuals (baseline shocks):")
display(pd.DataFrame(FC["r_base"], index=COMMODITIES, columns=COMMODITIES).round(2))
print(f"Bootstrap pool (Version B): {len(FC['boot'])} complete Ramadan years")
""")

md("""
Why: these are the requested risk measures per commodity and for the basket: expected price, 5th and 95th percentiles, P(surge > 10%), P(surge > 20%) and price-at-risk (P95 minus expected cost). Versions A and B are compared side by side.
""")
code("""
RISK_A, RISK_B = (risk_summary(FC["sims"][v]) for v in ("A", "B"))
print("Version A (parametric):")
display(RISK_A.round(3))
print("Version B (bootstrap of past Ramadan years):")
display(RISK_B.round(3))
compare = pd.DataFrame({"expected A": RISK_A["expected"], "expected B": RISK_B["expected"],
                        "P95 A": RISK_A["p95"], "P95 B": RISK_B["p95"],
                        "P(surge>10%) A": RISK_A["P(surge>10%)"], "P(surge>10%) B": RISK_B["P(surge>10%)"]})
compare["P95 diff (B - A) %"] = 100 * (compare["P95 B"] / compare["P95 A"] - 1)
display(compare.round(3))
base_basket = sum(BASKET[c] * FC["base"].at[c, "baseline_hat"] for c in COMMODITIES)
print(f"Baseline basket cost without Ramadan surge: {base_basket:,.0f} BDT/month; expected in the Ramadan month "
      f"(A): {RISK_A.at['basket', 'expected']:,.0f} BDT; P95 (A): {RISK_A.at['basket', 'p95']:,.0f} BDT")
""")

md("""
Why: the convergence plot checks that N = 10,000 is enough: the running mean and the running 95th percentile of the basket cost must settle well before N.
""")
code("""
fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
checkpoints = np.unique(np.logspace(2, np.log10(N_SIM), 60).astype(int))
for v, ls in (("A", "-"), ("B", "--")):
    cost = sum(BASKET[c] * FC["sims"][v][(c, "price")] for c in COMMODITIES).to_numpy()
    axes[0].plot(checkpoints, [cost[:n].mean() for n in checkpoints], ls=ls, label=f"Version {v}")
    axes[1].plot(checkpoints, [np.quantile(cost[:n], 0.95) for n in checkpoints], ls=ls, label=f"Version {v}")
    mcse = cost.std(ddof=1) / np.sqrt(len(cost))
    print(f"Version {v}: Monte Carlo standard error of the mean basket cost at N={N_SIM:,}: {mcse:.2f} BDT "
          f"({100 * mcse / cost.mean():.3f}% of the mean)")
for ax, what in zip(axes, ["Running mean", "Running 95th percentile"]):
    ax.set_xscale("log")
    ax.set(title=f"{what} of basket cost", xlabel="Number of simulations (log scale)", ylabel="Basket cost (BDT/month)")
    ax.legend()
fig.suptitle("Monte Carlo convergence", fontweight="bold")
fig.tight_layout()
savefig(fig, "fig11_mc_convergence")
plt.show()
""")

md("""
Why: the simulated price distributions per commodity show the spread of outcomes, with the baseline forecast and the 5th to 95th percentile band.
""")
code("""
fig, axes = plt.subplots(2, 2, figsize=(11, 6.2))
for ax, c in zip(axes.flat, COMMODITIES):
    for v, ls in (("A", "-"), ("B", "--")):
        ax.hist(FC["sims"][v][(c, "price")], bins=60, density=True, histtype="step", ls=ls, lw=1.1, label=f"Version {v}")
    for q in ("p5", "p95"):
        ax.axvline(RISK_A.at[c, q], ls=":", lw=1.0)
    ax.axvline(FC["base"].at[c, "baseline_hat"], ls="-.", lw=1.0)
    ax.set(title=f"{LABEL[c]}: {TARGET['flag_month']:%b %Y}", xlabel=f"Simulated price ({UNIT[c]})", ylabel="Density")
axes[0, 0].legend(handles=[plt.Line2D([], [], ls="-", color="black", label="Version A"),
                           plt.Line2D([], [], ls="--", color="black", label="Version B"),
                           plt.Line2D([], [], ls=":", color="black", label="P5 and P95 (A)"),
                           plt.Line2D([], [], ls="-.", color="black", label="Baseline forecast")], loc="upper right")
fig.suptitle(f"Simulated Ramadan-month prices, national series, N = {N_SIM:,}", fontweight="bold")
fig.tight_layout()
savefig(fig, "fig12_mc_price_distributions")
plt.show()
""")

# =============================================================================
md("""
## 8 Statistical tests

Why: two complementary questions. (1) Are month-on-month price changes in Ramadan flag months different from changes in other months? **Welch t-test** of monthly log returns (unequal variances), with the mean difference, its 95% CI and **Hedges' g** as effect size. Holm correction is applied across the four commodities within each series. The pooled row stacks all commodities; it is shown for completeness but its observations are not independent. (2) Is the average surge different from zero? **Bootstrap 95% CI** (BCa, 10,000 resamples) of the mean surge, with Cohen's d (mean / SD).

Note that the monthly return in the flag month captures only a one-month move, while the surge compares the flag month with a baseline 2 to 3 months earlier, so the two can disagree.
""")
code("""
def effect_label(g: float) -> str:
    a = abs(g)
    return "negligible" if a < 0.2 else "small" if a < 0.5 else "medium" if a < 0.8 else "large"


test_rows = []
for s_name, frame in SERIES.items():
    flags = (cal_dh if s_name == "Dhaka" else cal_nat)["flag_month"]
    rets = np.log(frame).diff()
    is_flag = rets.index.isin(pd.DatetimeIndex(flags))
    for c in COMMODITIES + ["pooled"]:
        cols = COMMODITIES if c == "pooled" else [c]
        a = rets.loc[is_flag, cols].to_numpy().ravel()
        b = rets.loc[~is_flag, cols].to_numpy().ravel()
        a, b = a[~np.isnan(a)], b[~np.isnan(b)]
        t, p = stats.ttest_ind(a, b, equal_var=False)
        lo, hi = rs.welch_ci(a, b)
        g = rs.hedges_g(a, b)
        test_rows.append({"series": s_name, "commodity": c, "n flag": len(a), "n other": len(b),
                          "mean flag %": 100 * a.mean(), "mean other %": 100 * b.mean(),
                          "diff pp": 100 * (a.mean() - b.mean()), "95% CI low pp": 100 * lo, "95% CI high pp": 100 * hi,
                          "t": t, "p": p, "Hedges g": g, "effect": effect_label(g)})
tests = pd.DataFrame(test_rows)
for s_name in SERIES:
    m = tests["series"].eq(s_name) & tests["commodity"].ne("pooled")
    tests.loc[m, "p Holm"] = multipletests(tests.loc[m, "p"], method="holm")[1]
display(tests.round(3))
""")

md("""
Why: the bootstrap CI does not assume normality, which matters with only one surge per Ramadan year per commodity.
""")
code("""
boot_rows = []
for s_name, s in SURGES.items():
    for c in COMMODITIES + ["pooled"]:
        x = (s["surge"] if c == "pooled" else s.loc[s["commodity"].eq(c), "surge"]).to_numpy()
        res = stats.bootstrap((x,), np.mean, n_resamples=10_000, confidence_level=0.95, method="BCa",
                              rng=rng_for(f"boot-{s_name}-{c}"))
        lo, hi = res.confidence_interval
        boot_rows.append({"series": s_name, "commodity": c, "n": len(x), "mean surge %": 100 * x.mean(),
                          "95% CI low %": 100 * lo, "95% CI high %": 100 * hi, "CI excludes 0": bool(lo > 0 or hi < 0),
                          "Cohen d": x.mean() / x.std(ddof=1), "effect": effect_label(x.mean() / x.std(ddof=1)),
                          "one-sample t p": stats.ttest_1samp(x, 0).pvalue})
boot_ci = pd.DataFrame(boot_rows)
display(boot_ci.round(3))
""")

# =============================================================================
md("""
## 9 Scenarios and sensitivity

Why: decision makers need "what if" answers. All scenarios reuse the **same random draws** as the Version A base case (common random numbers), so differences between scenarios are due to the scenario, not to simulation noise.

* **Base:** the section 7 forecast.
* **High hoarding:** every simulated surge multiplied by 1.5 (as specified; note this also makes negative surges more negative).
* **Supply shock:** baseline price +5% and +10% (for example an import disruption before Ramadan), surge unchanged.
""")
code("""
SCENARIOS = {"Base": {}, "High hoarding (surge x 1.5)": {"surge_mult": 1.5},
             "Supply shock (baseline +5%)": {"base_mult": 1.05}, "Supply shock (baseline +10%)": {"base_mult": 1.10}}
scen_rows = []
for name, kw in SCENARIOS.items():
    r = risk_summary(prices_from_shocks(FC["shocks"], FC["base"], FC["params"], FC["boot"], version="A", **kw))
    for item in COMMODITIES + ["basket"]:
        scen_rows.append({"scenario": name, "item": item, "expected": r.at[item, "expected"], "p95": r.at[item, "p95"],
                          "P(surge>10%)": r.at[item, "P(surge>10%)"], "P(surge>20%)": r.at[item, "P(surge>20%)"],
                          "price at risk": r.at[item, "price at risk (P95 - expected)"]})
scen = pd.DataFrame(scen_rows)
display(scen.pivot(index="scenario", columns="item", values="expected").reindex(list(SCENARIOS))[COMMODITIES + ["basket"]].round(2))
display(scen.pivot(index="scenario", columns="item", values="p95").reindex(list(SCENARIOS))[COMMODITIES + ["basket"]].round(2))
display(scen[scen["item"].eq("basket")].set_index("scenario").round(3))

sb = scen[scen["item"].eq("basket")].set_index("scenario").reindex(list(SCENARIOS))
fig, ax = plt.subplots(figsize=(9, 3.8))
xpos = np.arange(len(sb))
bars1 = ax.bar(xpos - 0.2, sb["expected"], 0.4, color="white", edgecolor="black", label="Expected cost")
bars2 = ax.bar(xpos + 0.2, sb["p95"], 0.4, color="white", edgecolor="black", hatch="///", label="95th percentile")
for bars in (bars1, bars2):
    ax.bar_label(bars, fmt="{:,.0f}", fontsize=7, padding=2)
ax.set_xticks(xpos, [s.replace(" (", "\\n(") for s in sb.index])
ax.set_ylim(0, sb["p95"].max() * 1.15)
ax.set(title=f"Household basket cost in {TARGET['flag_month']:%b %Y} by scenario (Version A)",
       ylabel="Basket cost (BDT/month)", xlabel="Scenario")
ax.legend(loc="upper left")
savefig(fig, "fig13_scenarios")
plt.show()
""")

md("""
Why: one-at-a-time sensitivity shows which input drives the tail risk most. Each input is moved by -25% and +25% while all others stay at their base values (same random draws), and we record the change in the 95th percentile of the basket cost. The tornado chart ranks the inputs.
""")
code("""
OAT = {"Mean surge": "mean_mult", "Surge SD": "sd_mult", "Baseline price": "base_mult", "Basket quantities": "qty_mult"}
P95_BASE = RISK_A.at["basket", "p95"]
oat_rows = []
for label, arg in OAT.items():
    row = {"input": label}
    for mult, col in ((0.75, "-25%"), (1.25, "+25%")):
        kw = {} if arg == "qty_mult" else {arg: mult}
        qty = {c: q * mult for c, q in BASKET.items()} if arg == "qty_mult" else BASKET
        sim = prices_from_shocks(FC["shocks"], FC["base"], FC["params"], FC["boot"], version="A", **kw)
        row[col] = risk_summary(sim, qty).at["basket", "p95"] - P95_BASE
    oat_rows.append(row)
oat = pd.DataFrame(oat_rows).assign(range=lambda d: (d["+25%"] - d["-25%"]).abs()).sort_values("range")
print(f"Base P95 basket cost: {P95_BASE:,.0f} BDT/month")
display(oat.round(1))


def plot_tornado(ax) -> None:
    y = np.arange(len(oat))
    ax.barh(y, oat["-25%"], color="white", edgecolor="black", hatch="///", label="Input -25%")
    ax.barh(y, oat["+25%"], color="black", edgecolor="black", label="Input +25%")
    ax.axvline(0, lw=0.8)
    ax.set_yticks(y, oat["input"])
    ax.set(xlabel="Change in P95 basket cost (BDT/month)", title="Sensitivity of P95 basket cost (+/-25%)")
    ax.legend(loc="lower right")


fig, ax = plt.subplots(figsize=(8, 3.4))
plot_tornado(ax)
savefig(fig, "fig14_tornado")
plt.show()
""")

# =============================================================================
md("""
## 10 Validation: rolling-origin backtest

Why: a model is only credible if it would have worked in the past. For each of the **last three Ramadans** in each series we rebuild everything using **only data available at the forecast origin** (the same lead time before the Ramadan start month as the real forecast): seasonal indices, trend, surge distribution (only earlier Ramadans; family by AIC) and correlations. We then forecast the flag-month price and compare it with what actually happened.

Metrics: absolute percentage error (APE) of the median forecast and its mean (MAPE), compared with a naive forecast (last observed price at the origin); whether the actual price lies inside the simulated 5th to 95th percentile band; and whether the actual surge lies inside the simulated surge band.
""")
code("""
bt_rows = []
for s_name, frame in SERIES.items():
    cal_s = cal_dh if s_name == "Dhaka" else cal_nat
    for _, target in cal_s.tail(3).iterrows():
        origin = target["start_month"] - pd.DateOffset(months=ORIGIN_LAG)
        fc = run_forecast(frame, SURGES[s_name], target, origin, tag=f"bt-{s_name}-{target['hijri_year']}")
        for c in COMMODITIES:
            simA, simB = fc["sims"]["A"], fc["sims"]["B"]
            actual = frame.at[target["flag_month"], c]
            actual_base = frame.loc[[target["baseline_m1"], target["baseline_m2"]], c].mean()
            bt_rows.append({
                "series": s_name, "year": int(target["gregorian_year"]), "commodity": c, "origin": origin.strftime("%Y-%m"),
                "past Ramadans used": fc["params"][c]["n"], "family": fc["params"][c]["family"],
                "forecast_median": simA[(c, "price")].median(), "forecast_p5": simA[(c, "price")].quantile(0.05),
                "forecast_p95": simA[(c, "price")].quantile(0.95), "actual_price": actual,
                "naive_last_price": fc["base"].at[c, "last obs price"], "actual_surge": actual / actual_base - 1,
                "surge_p5": simA[(c, "surge")].quantile(0.05), "surge_p95": simA[(c, "surge")].quantile(0.95),
                "forecast_median_B": simB[(c, "price")].median(), "forecast_p5_B": simB[(c, "price")].quantile(0.05),
                "forecast_p95_B": simB[(c, "price")].quantile(0.95)})
bt = pd.DataFrame(bt_rows)
bt["APE"] = (bt["forecast_median"] - bt["actual_price"]).abs() / bt["actual_price"]
bt["APE naive"] = (bt["naive_last_price"] - bt["actual_price"]).abs() / bt["actual_price"]
bt["APE B"] = (bt["forecast_median_B"] - bt["actual_price"]).abs() / bt["actual_price"]
bt["price in band A"] = bt["actual_price"].between(bt["forecast_p5"], bt["forecast_p95"])
bt["price in band B"] = bt["actual_price"].between(bt["forecast_p5_B"], bt["forecast_p95_B"])
bt["surge in band"] = bt["actual_surge"].between(bt["surge_p5"], bt["surge_p95"])
display(bt.drop(columns=["forecast_median_B", "forecast_p5_B", "forecast_p95_B"]).round(3))
""")

md("""
Why: summary of forecast accuracy per series and per commodity, followed by a chart of every forecast band against the actual price.
""")
code("""
def bt_summary(g: pd.DataFrame) -> pd.Series:
    return pd.Series({"forecasts": len(g), "MAPE model A %": 100 * g["APE"].mean(), "MAPE model B %": 100 * g["APE B"].mean(),
                      "MAPE naive %": 100 * g["APE naive"].mean(), "price coverage A": g["price in band A"].mean(),
                      "price coverage B": g["price in band B"].mean(), "surge coverage": g["surge in band"].mean()})


bt_by_series = bt.groupby("series").apply(bt_summary)
bt_by_commodity = bt.groupby(["series", "commodity"]).apply(bt_summary)
display(bt_by_series.round(3))
display(bt_by_commodity.round(3))

fig, axes = plt.subplots(2, 4, figsize=(13, 5.6))
for i, s_name in enumerate(SERIES):
    for j, c in enumerate(COMMODITIES):
        ax = axes[i, j]
        sub = bt[bt["series"].eq(s_name) & bt["commodity"].eq(c)]
        yerr = [sub["forecast_median"] - sub["forecast_p5"], sub["forecast_p95"] - sub["forecast_median"]]
        ax.errorbar(sub["year"], sub["forecast_median"], yerr=yerr, fmt="o", mfc="white", capsize=4, lw=1.0,
                    label="Forecast median, P5 to P95")
        ax.scatter(sub["year"], sub["actual_price"], marker="x", s=50, zorder=5, label="Actual")
        ax.scatter(sub["year"], sub["naive_last_price"], marker="_", s=120, zorder=4, label="Naive (last price)")
        ax.set_xticks(sub["year"])
        ax.set(title=f"{s_name}: {LABEL[c]}", ylabel=f"Flag-month price ({UNIT[c]})")
        if i == 1:
            ax.set_xlabel("Ramadan year")
axes[0, 0].legend(loc="upper left", fontsize=6.5)
fig.suptitle("Rolling-origin backtest: forecast bands vs actual Ramadan-month prices", fontweight="bold")
fig.tight_layout()
savefig(fig, "fig15_backtest")
plt.show()
""")

# =============================================================================
md("""
## 11 Dashboard

Why: one place with the headline numbers (KPI table) and the four key charts: price history with Ramadan months, the distribution of past surges, the simulated basket cost for the next Ramadan and the sensitivity tornado.
""")
code("""
reg_c = reg_table[reg_table["series"].eq("National") & reg_table["model"].eq("C")].set_index("commodity")
bci = boot_ci[boot_ci["series"].eq("National")].set_index("commodity")
mape_c = bt_by_commodity.loc["National", "MAPE model A %"]
kpi = pd.DataFrame({
    "unit": [UNIT[c] for c in COMMODITIES],
    f"last price ({NAT_END:%b %Y})": [FC["base"].at[c, "last obs price"] for c in COMMODITIES],
    "baseline forecast": [FC["base"].at[c, "baseline_hat"] for c in COMMODITIES],
    "expected Ramadan price": [RISK_A.at[c, "expected"] for c in COMMODITIES],
    "P5": [RISK_A.at[c, "p5"] for c in COMMODITIES], "P95": [RISK_A.at[c, "p95"] for c in COMMODITIES],
    "P(surge>10%)": [RISK_A.at[c, "P(surge>10%)"] for c in COMMODITIES],
    "P(surge>20%)": [RISK_A.at[c, "P(surge>20%)"] for c in COMMODITIES],
    "mean past surge %": [bci.at[c, "mean surge %"] for c in COMMODITIES],
    "surge 95% CI": [f"{bci.at[c, '95% CI low %']:.1f} to {bci.at[c, '95% CI high %']:.1f}" for c in COMMODITIES],
    "Ramadan effect (model C) %": [reg_c.at[LABEL[c], "Ramadan effect %"] for c in COMMODITIES],
    "backtest MAPE %": [mape_c[c] for c in COMMODITIES],
}, index=[LABEL[c] for c in COMMODITIES])
display(kpi.round(2))
print(f"Basket ({', '.join(f'{q:g} {UNIT[c].split(chr(47))[1]} {c}' for c, q in BASKET.items())}): "
      f"expected {RISK_A.at['basket', 'expected']:,.0f} BDT, P5 {RISK_A.at['basket', 'p5']:,.0f}, "
      f"P95 {RISK_A.at['basket', 'p95']:,.0f}, price-at-risk {RISK_A.at['basket', 'price at risk (P95 - expected)']:,.0f} BDT/month")
""")

md("""
Why: the 2 x 2 dashboard figure is the one-page visual summary used in the report.
""")
code("""
fig, axes = plt.subplots(2, 2, figsize=(13, 8.4))
ax = axes[0, 0]
for c in COMMODITIES:
    ax.plot(nat.index, nat[c], ls=LS[c], lw=1.0, label=f"{LABEL[c]} ({UNIT[c]})")
for m in cal_nat["flag_month"]:
    ax.axvline(m, lw=0.4, ls=":")
ax.set(title="(a) National retail prices; dotted lines = Ramadan flag months", xlabel="Month", ylabel="Price (BDT per kg or litre)")
ax.legend(loc="upper left")
ax = axes[0, 1]
ax.boxplot([surge_nat.loc[surge_nat["commodity"].eq(c), "surge"] * 100 for c in COMMODITIES],
           tick_labels=[LABEL[c] for c in COMMODITIES], medianprops={"color": "black"}, showmeans=True,
           meanprops={"marker": "D", "markerfacecolor": "white", "markeredgecolor": "black"})
ax.axhline(0, lw=0.6)
ax.set(title=f"(b) Past Ramadan surges, {cal_nat['gregorian_year'].min()} to {cal_nat['gregorian_year'].max()} (diamond = mean)",
       ylabel="Surge vs 2-month baseline (%)", xlabel="Commodity")
ax = axes[1, 0]
cost = sum(BASKET[c] * FC["sims"]["A"][(c, "price")] for c in COMMODITIES)
ax.hist(cost, bins=60, color="white", edgecolor="black", lw=0.5)
for val, ls, lab in ((RISK_A.at["basket", "p5"], ":", "P5"), (RISK_A.at["basket", "expected"], "-", "Expected"),
                     (RISK_A.at["basket", "p95"], "--", "P95")):
    ax.axvline(val, ls=ls, lw=1.3, label=f"{lab}: {val:,.0f}")
ax.set(title=f"(c) Simulated household basket cost, {TARGET['flag_month']:%b %Y} (Version A)",
       xlabel="Basket cost (BDT/month)", ylabel="Number of simulations")
ax.legend(loc="upper right")
plot_tornado(axes[1, 1])
axes[1, 1].set_title("(d) Sensitivity of P95 basket cost (+/-25%)")
fig.suptitle("Ramadan price-surge dashboard: Bangladesh staples", fontweight="bold", fontsize=12)
fig.tight_layout()
savefig(fig, "fig16_dashboard")
plt.show()
""")

# =============================================================================
md("""
## 12 Limitations and conclusion

**Limitations**

* **Ramadan drifts about 11 days earlier each year.** Over 15 to 21 years it covers only part of the calendar (autumn to late winter), so the Ramadan effect is identified from a limited set of calendar months, and the flag month is partly confounded with ordinary seasonality.
* **Nominal prices.** Prices are not inflation-adjusted; the trend absorbs general inflation, and surges are measured relative to a baseline only 2 to 3 months earlier, which limits but does not remove the effect of inflation.
* **Other drivers are not separated:** monsoon and Aman/Boro harvest cycles, floods, trade policy (import duties, export bans by India), the exchange rate and the 2020 COVID-19 shock all move prices and can coincide with Ramadan.
* **Small number of Ramadan observations** (one per year per commodity; counts in section 3): distribution tests have low power and tail estimates (P95) carry wide uncertainty.
* **Some source values may be estimated:** WFP marks part of the data as `aggregate`; suspected recording errors were excluded and short gaps filled by the stated rules (section 2).
* **Market structure break in 2020:** WFP switched from division to district markets. The main Dhaka series therefore ends in 2020, and the national series is a chained index whose level before 2020 rests on the division markets.
* **Forecast design:** the baseline trend is a 36-month log-linear extrapolation; the household basket quantities are illustrative assumptions; Ramadan dates follow the Umm al-Qura calendar (the +1 day Bangladesh shift is tested).

**Conclusion.** The key findings below are generated from the results above.
""")
code("""
nat_b = boot_ci[boot_ci["series"].eq("National")].set_index("commodity")
sig = [c for c in COMMODITIES if nat_b.at[c, "CI excludes 0"] and nat_b.at[c, "mean surge %"] > 0]
top = max(COMMODITIES, key=lambda c: nat_b.at[c, "mean surge %"])
regC = reg_table[reg_table["series"].eq("National") & reg_table["model"].eq("C")].set_index("commodity")
reg_sig = [c for c in COMMODITIES if regC.at[LABEL[c], "95% CI low %"] > 0]
riskiest = max(COMMODITIES, key=lambda c: RISK_A.at[c, "P(surge>10%)"])
nat_bt = bt_by_series.loc["National"]
dh_bt = bt_by_series.loc["Dhaka"]

top_input = oat.iloc[-1]
pooled_sig = nat_b.at["pooled", "CI excludes 0"]
beats_naive = nat_bt["MAPE model A %"] < nat_bt["MAPE naive %"]
FINDINGS = [
    (f"Across {len(cal_nat)} Ramadans (national series, {cal_nat['gregorian_year'].min()} to "
     f"{cal_nat['gregorian_year'].max()}) the flag-month price was on average {nat_b.at['pooled', 'mean surge %']:.1f}% "
     f"{'above' if nat_b.at['pooled', 'mean surge %'] >= 0 else 'below'} the pre-Ramadan baseline (pooled 95% bootstrap CI "
     f"{nat_b.at['pooled', '95% CI low %']:.1f}% to {nat_b.at['pooled', '95% CI high %']:.1f}%, "
     f"{'significantly different from zero' if pooled_sig else 'not distinguishable from zero'}). The largest mean surge is for "
     f"{LABEL[top].lower()} ({nat_b.at[top, 'mean surge %']:.1f}%); commodities whose mean surge is significantly positive: "
     f"{', '.join(LABEL[c].lower() for c in sig) or 'none'}. After controlling for calendar seasonality and trend "
     f"(model C), the Ramadan effect is significantly positive for: {', '.join(LABEL[c].lower() for c in reg_sig) or 'none'}."),
    (f"For Ramadan {TARGET['hijri_year']} AH ({TARGET['flag_month']:%B %Y}) the simulated household basket costs "
     f"{RISK_A.at['basket', 'expected']:,.0f} BDT on average (90% range {RISK_A.at['basket', 'p5']:,.0f} to "
     f"{RISK_A.at['basket', 'p95']:,.0f} BDT) against a no-surge baseline of {base_basket:,.0f} BDT; the price-at-risk "
     f"(P95 minus expected) is {RISK_A.at['basket', 'price at risk (P95 - expected)']:,.0f} BDT per month. "
     f"{LABEL[riskiest]} has the highest chance of a surge above 10% ({pct(RISK_A.at[riskiest, 'P(surge>10%)'])}). "
     f"The most influential input for the P95 basket cost is {top_input['input'].lower()} "
     f"({top_input['-25%']:+,.0f} to {top_input['+25%']:+,.0f} BDT for a -25% to +25% change)."),
    (f"Backtest (last three Ramadans, data cut at each origin): national MAPE {nat_bt['MAPE model A %']:.1f}% versus "
     f"{nat_bt['MAPE naive %']:.1f}% for the naive last-price forecast ({'better' if beats_naive else 'not better'} than naive); "
     f"the actual price fell inside the 5 to 95% band in {pct(nat_bt['price coverage A'], 0)} of national and "
     f"{pct(dh_bt['price coverage A'], 0)} of Dhaka forecasts (Dhaka MAPE {dh_bt['MAPE model A %']:.1f}% vs naive "
     f"{dh_bt['MAPE naive %']:.1f}%)."),
]
for i, f in enumerate(FINDINGS, 1):
    display(Markdown(f"**Finding {i}.** {f}"))
""")

md("""
Why: the Excel workbook lets the results be reproduced by hand for the lab: cleaned data, surge table with live `AVERAGE`, `STDEV.S`, `PERCENTILE.INC` and `COUNTIF` formulas, the 10,000 Version A draws with formula-based prices, basket cost and risk measures (next to the Python values), scenarios, the backtest with formula-based APE, MAPE and coverage, and the assumptions (the basket quantities on the Assumptions sheet drive the Risk formulas).
""")
code("""
def surge_wide(s: pd.DataFrame) -> pd.DataFrame:
    rows = {}
    for year, g in s.groupby("year"):
        row = {("all", "marginal"): bool(g["marginal"].iloc[0])}
        for r in g.itertuples():
            row[(r.commodity, "baseline_m1")] = r.baseline_m1_price
            row[(r.commodity, "baseline_m2")] = r.baseline_m2_price
            row[(r.commodity, "flag")] = r.flag_price
        rows[year] = row
    return pd.DataFrame.from_dict(rows, orient="index")


data_wide = pd.concat({f"{s} {c} ({UNIT[c]})": frame[c] for s, frame in (("National", nat), ("Dhaka", dh))
                       for c in COMMODITIES}, axis=1)
flag_series = pd.Series(1, index=pd.DatetimeIndex(cal_nat["flag_month"]))
draws = pd.concat([FC["sims"]["A"][[(c, "baseline"), (c, "surge")]] for c in COMMODITIES], axis=1)
py_risk = pd.DataFrame({
    "Expected price": RISK_A["expected"], "P5 price": RISK_A["p5"], "P95 price": RISK_A["p95"],
    "P(surge > 10%)": RISK_A["P(surge>10%)"], "P(surge > 20%)": RISK_A["P(surge>20%)"],
    "Price-at-risk": RISK_A["price at risk (P95 - expected)"]}).T[COMMODITIES + ["basket"]]
py_risk.loc[["P(surge > 10%)", "P(surge > 20%)"], "basket"] = np.nan
assumptions = pd.DataFrame([
    ("Random seed", SEED, "global; each stage uses np.random.default_rng([42, crc32(stage)])"),
    ("Monte Carlo draws", N_SIM, "per simulation"),
    ("Data source", "WFP Bangladesh - Food Prices (HDX)", "CC BY-IGO; see SOURCES.md"),
    ("Main series", f"{MAIN_MARKET}, {DH_START:%Y-%m} to {DH_END:%Y-%m}", "single market, retail BDT"),
    ("Robustness / forecast series", f"National chained index, {NAT_START:%Y-%m} to {NAT_END:%Y-%m}", "matched-market Jevons index, BDT anchored on last 12 months"),
    ("Ramadan calendar", "Umm al-Qura (hijridate); +1 day sensitivity", "flag month = month with most Ramadan days"),
    ("Baseline", "mean of the two months before the Ramadan start month", ""),
    ("Marginal year", "flag share < 0.6", "kept and marked"),
    ("Gap filling", "1 month: neighbour mean; 2 months: linear; > 2: never", "all filled cells logged"),
    ("Suspected recording errors", "spike-and-revert > 25% log, confirmed against peers", f"{len(errors)} observations excluded"),
    ("Forecast target", f"Ramadan {TARGET['hijri_year']} AH, flag month {TARGET['flag_month']:%Y-%m}", f"origin {NAT_END:%Y-%m}, lead {ORIGIN_LAG} months"),
    ("Baseline trend window", f"{TREND_WINDOW} months", "log-linear on seasonally adjusted series"),
    ("Surge families (Version A)", ", ".join(f"{c}: {f}" for c, f in CHOSEN.items()), "section 6 rule"),
    ("Basket", ", ".join(f"{c} {q:g}" for c, q in BASKET.items()), "illustrative monthly household quantities (assumption)"),
], columns=["item", "value", "note"])
bt_x = bt[["series", "year", "commodity", "origin", "forecast_median", "forecast_p5", "forecast_p95", "actual_price",
           "naive_last_price", "actual_surge", "surge_p5", "surge_p95"]].round(6)
XLSX = workbook.build_workbook(
    OUT / "results.xlsx", data=data_wide, flags=flag_series,
    surge_blocks={f"National series surges ({cal_nat['gregorian_year'].min()} to {cal_nat['gregorian_year'].max()})": surge_wide(surge_nat),
                  f"Dhaka Division surges ({cal_dh['gregorian_year'].min()} to {cal_dh['gregorian_year'].max()})": surge_wide(surge_dh)},
    commodities=COMMODITIES, draws=draws,
    risk_title=f"Version A Monte Carlo draws, Ramadan {TARGET['hijri_year']} AH ({TARGET['flag_month']:%b %Y}); price = baseline x (1 + surge)",
    python_risk=py_risk, scenarios=scen.round(4), backtest=bt_x, assumptions=assumptions, basket=BASKET)
print(f"Saved {XLSX.relative_to(ROOT)} with sheets Data, Surge, Risk, Scenarios, Backtest, Assumptions")
""")

md("""
Why: `REPORT.md` is generated from the variables above, so every number in it comes from a notebook cell. The data record (`SOURCES.md`) and the run log are copied next to the other deliverables, and the headline facts are saved for the final checklist.
""")
code("""
def kpi_line(c: str) -> str:
    return (f"| {LABEL[c]} ({UNIT[c]}) | {nat_b.at[c, 'mean surge %']:.1f} ({nat_b.at[c, '95% CI low %']:.1f} to "
            f"{nat_b.at[c, '95% CI high %']:.1f}) | {regC.at[LABEL[c], 'Ramadan effect %']:.1f} "
            f"({regC.at[LABEL[c], '95% CI low %']:.1f} to {regC.at[LABEL[c], '95% CI high %']:.1f}) | "
            f"{FC['base'].at[c, 'baseline_hat']:.1f} | {RISK_A.at[c, 'expected']:.1f} | {RISK_A.at[c, 'p5']:.1f} to "
            f"{RISK_A.at[c, 'p95']:.1f} | {pct(RISK_A.at[c, 'P(surge>10%)'])} | {pct(RISK_A.at[c, 'P(surge>20%)'])} |")


report = f'''# Ramadan Price Surges in Bangladesh Staples: Summary Report

**Project:** Forecasting and Risk Assessment of Ramadan-Driven Price Surges in Bangladesh's Staple Food Markets Using Seasonal Decomposition and Monte Carlo Simulation

**Data.** WFP *Bangladesh - Food Prices* via HDX (CC BY-IGO), monthly retail prices in BDT for coarse rice, masur lentils, palm oil and wheat flour. Main series: {MAIN_MARKET}, {DH_START:%b %Y} to {DH_END:%b %Y} ({len(cal_dh)} Ramadans). Robustness and forecast series: national matched-market chained index, {NAT_START:%b %Y} to {NAT_END:%b %Y} ({len(cal_nat)} Ramadans). {len(errors)} suspected recording errors excluded; {len(dh_fill_log) + len(nat_fill_log)} short gaps filled.

**Method.** Multiplicative decomposition (statsmodels and manual ratio-to-CMA, max difference {agree.select_dtypes('number').max().max():.1e}); regression with a moving Ramadan dummy (HAC errors); surge = flag-month price / mean of the two pre-Ramadan months - 1; Normal and Lognormal fits (KS with Lilliefors bootstrap, chi-square); Monte Carlo with N = {N_SIM:,} (Version A parametric, Version B bootstrap), seed {SEED}; scenarios, one-at-a-time sensitivity and a rolling-origin backtest.

## Key numbers (national series; forecast for Ramadan {TARGET['hijri_year']} AH, flag month {TARGET['flag_month']:%B %Y})

| Commodity | Mean past surge % (95% CI) | Ramadan effect, model C % (95% CI) | Baseline forecast | Expected price | 90% range (P5 to P95) | P(surge > 10%) | P(surge > 20%) |
|---|---|---|---|---|---|---|---|
{chr(10).join(kpi_line(c) for c in COMMODITIES)}

Household basket (assumed {', '.join(f'{q:g} {UNIT[c].split(chr(47))[1]} {LABEL[c].lower()}' for c, q in BASKET.items())} per month): no-surge baseline {base_basket:,.0f} BDT; expected Ramadan-month cost {RISK_A.at['basket', 'expected']:,.0f} BDT; P95 {RISK_A.at['basket', 'p95']:,.0f} BDT; price-at-risk {RISK_A.at['basket', 'price at risk (P95 - expected)']:,.0f} BDT. Version B (bootstrap) expected cost {RISK_B.at['basket', 'expected']:,.0f} BDT, P95 {RISK_B.at['basket', 'p95']:,.0f} BDT. Scenario P95 basket cost: {'; '.join(f"{r.scenario} {r.p95:,.0f} BDT" for r in scen[scen['item'].eq('basket')].itertuples())}.

**Validation.** Rolling-origin backtest over the last three Ramadans: national MAPE {nat_bt['MAPE model A %']:.1f}% (naive {nat_bt['MAPE naive %']:.1f}%), price coverage of the 5 to 95% band {pct(nat_bt['price coverage A'], 0)}; Dhaka MAPE {dh_bt['MAPE model A %']:.1f}% (naive {dh_bt['MAPE naive %']:.1f}%), coverage {pct(dh_bt['price coverage A'], 0)}.

## Findings

{chr(10).join(f'{i}. {f}' for i, f in enumerate(FINDINGS, 1))}

## Limitations

Ramadan drifts about 11 days earlier each year, so it is observed in only part of the calendar; prices are nominal (not inflation-adjusted); monsoon, floods, trade policy and the exchange rate are not separated; the number of Ramadan observations is small ({len(cal_dh)} Dhaka, {len(cal_nat)} national); some source values are WFP aggregates or estimates; WFP changed from division to district markets in 2020; basket quantities are assumptions.

## Sources

World Food Programme (WFP). *Bangladesh - Food Prices*. Humanitarian Data Exchange, https://data.humdata.org/dataset/wfp-food-prices-for-bangladesh (accessed {re.search(r"Access date:\\*\\* (\\S+)", sources_md).group(1)}). Licence CC BY-IGO. Ramadan dates: hijridate (Umm al-Qura), cross-checked with convertdate. Full record: SOURCES.md; process log: RUNLOG.md.
'''
assert not re.search("[\\u2013\\u2014\\u2015]", report), "long dash found in report text"
(OUT / "REPORT.md").write_text(report, encoding="utf-8")
shutil.copy(RAW / "SOURCES.md", OUT / "SOURCES.md")
shutil.copy(ROOT / "RUNLOG.md", OUT / "RUNLOG.md")
facts = {"dataset": "WFP Bangladesh - Food Prices (HDX, wfp-food-prices-for-bangladesh)",
         "main_series": f"{MAIN_MARKET} {DH_START:%Y-%m} to {DH_END:%Y-%m}",
         "national_series": f"National chained index {NAT_START:%Y-%m} to {NAT_END:%Y-%m}",
         "ramadans_dhaka": len(cal_dh), "ramadans_national": len(cal_nat),
         "target": f"Ramadan {TARGET['hijri_year']} AH, flag month {TARGET['flag_month']:%Y-%m}",
         "findings": FINDINGS, "figures": sorted(set(FIGURES))}
(OUT / "findings.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")
display(Markdown(report))
print("Figures saved:", ", ".join(sorted(set(FIGURES))))
""")

nb = nbf.v4.new_notebook()
nb["cells"] = cells
nb["metadata"] = {"kernelspec": {"display_name": "Python 3 (ramadan_surge_project venv)", "language": "python", "name": "ramadan-surge"},
                  "language_info": {"name": "python"}}
nbf.validate(nb)
os.makedirs(os.path.dirname(NB_PATH), exist_ok=True)
nbf.write(nb, NB_PATH)
n_code = sum(c.cell_type == "code" for c in cells)
print(f"Wrote {NB_PATH}: {len(cells)} cells ({n_code} code)")
