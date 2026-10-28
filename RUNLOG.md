# RUNLOG

Chronological log of every search, download attempt, decision and error.
Format: `- timestamp | actor | message`.

## Session 2026-10-27

- 2026-10-27 22:22 | agent | Created project folder ./ramadan_surge_project and venv (.venv, Python 3.13.5). Installed pandas, numpy, scipy, statsmodels, matplotlib, seaborn, requests, openpyxl, nbformat, nbconvert, jupyter, ipykernel, convertdate.
- 2026-10-27 22:23 | agent | Source 1 attempt: HDX CKAN `package_search?q=bangladesh food prices`. ERROR: JSONDecodeError "Unterminated string" because the full (1 MB+) response was cut off by a 30 s curl timeout. FIX: saved the response to a file with a 120 s timeout and requested only the `name,title` fields (`fl=name,title`). Retry succeeded: 1566 hits, first hit `wfp-food-prices-for-bangladesh` (Bangladesh - Food Prices).
- 2026-10-27 22:24 | agent | HDX `package_show?id=wfp-food-prices-for-bangladesh`: license CC BY-IGO, 2 CSV resources (wfp_food_prices_bgd.csv, wfp_markets_bgd.csv), last modified 2026-10-25.
- 2026-10-27 22:25 | agent | Downloaded wfp_food_prices_bgd.csv (34,491 data rows) and wfp_markets_bgd.csv (171 rows).
- 2026-10-27 22:27 | agent | Quality gate exploration (retail BDT prices). Long-run staples: Rice (coarse) KG, Lentils (masur) KG, Oil (palm) L, Wheat flour KG, 2004/2006 onward. Sugar, soybean oil and onion only from 2024 (under 3 years), so they fail the 8-year rule and are excluded.
- 2026-10-27 22:28 | agent | Market structure finding: from 2004 to mid-2020 WFP reports DIVISION-level markets (e.g. "Dhaka Division"); from mid-2020 it reports DISTRICT-level markets (e.g. "Dhaka Sadar"). "Dhaka Division" has all 4 staples monthly from 2006 to 2020-07; "Dhaka Sadar" is patchy after 2020 (lentils only from 2023-08).
- 2026-10-27 22:29 | agent | DECISION: main series = "Dhaka Division" (single consistent market, 2006-07 to 2020-06, 14 years, 15 Ramadans). Robustness series = all-market national average, built from the 6 division markets up to 2020-06 and chain-linked to the district-market average from 2020-07 (ratio at the overlap months), giving 2006-07 to 2026-07. Because the Dhaka series stops in 2020, the forward forecast of the next Ramadan (1448 AH, February 2027) uses the national series, which is the only one reaching 2026.
- 2026-10-27 22:29 | agent | Quality gate result for source 1: PASS (Dhaka: 14 years monthly, 4 staples, retail, one unit per commodity, 15 Ramadans). Sources 2 to 4 were therefore not attempted, as instructed ("stop at the first source that satisfies the quality gate").
- 2026-10-27 22:31 | agent | Installed hijri-converter; it prints a DeprecationWarning pointing to its successor `hijridate`. FIX: replaced with hijridate==2.3.0 (same Umm al-Qura tables). convertdate (arithmetic Islamic calendar) kept as an independent cross-check. Installed pytest for unit tests. Froze requirements.txt.
- 2026-10-27 22:33 | agent | Wrote scripts/download_data.py (CKAN lookup + download + SOURCES.md). Re-running it as the reproducible provenance step.
- 2026-10-27 22:30:40 | download_data.py | HDX package_search q='bangladesh food prices': 1569 hits; top: ['wfp-food-prices-for-bangladesh', 'bgd-faostat-food-prices', 'bangladesh-real-time-prices']
- 2026-10-27 22:30:41 | download_data.py | HDX package_show wfp-food-prices-for-bangladesh: license='Creative Commons Attribution for Intergovernmental Organisations (CC BY-IGO)', last_modified=2026-10-25T18:09:51.180093, resources=2
- 2026-10-27 22:34:28 | download_data.py | Downloaded wfp_food_prices_bgd.csv: 34491 rows, 1900-08-15 to 2026-09-15, sha256=b003cd22f0884c47...
- 2026-10-27 22:34:36 | download_data.py | Downloaded wfp_markets_bgd.csv: 171 rows, n/a (reference table), sha256=dface2af12e1f192...
- 2026-10-27 22:34:36 | download_data.py | SOURCES.md written to data/raw/SOURCES.md
- 2026-10-28 | agent | Notebook execution ERROR: ModuleNotFoundError 'convertdate' because nbconvert used the user-level `python3` kernel (system Python). FIX: registered a venv-local kernel (`ipykernel install --sys-prefix --name ramadan-surge`) and set it in the notebook metadata and run script.
- 2026-10-28 | agent | Execution ERROR: NoSuchKernel 'ramadan-surge'. Cause: `python -m jupyter nbconvert` dispatched to ~/.local/bin/jupyter-nbconvert (system Python, outside the venv). FIX: run script now calls `.venv/bin/python -m nbconvert` directly.
- 2026-10-28 | agent | Execution ERROR: KeyError in section 2.5. Cause: palm oil chained index started 2006-04 and could not relink after >3 unmatched months, so NAT_END collapsed to 2006-04. FIX: chained_index(max_bridge=None) links to the last linked month at any distance; gap months stay NaN under the gap rules. Test added. Notebook rebuilt, not re-executed (user asked to pause).
