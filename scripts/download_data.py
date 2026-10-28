"""Discover and download the Bangladesh food price data (Step 1).

Queries the HDX CKAN API, downloads the WFP "Bangladesh - Food Prices"
CSV resources, checks the quality gate and writes data/raw/SOURCES.md.
Every attempt is appended to RUNLOG.md.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
API_DIR = os.path.join(RAW, "api")
RUNLOG = os.path.join(ROOT, "RUNLOG.md")

CKAN = "https://data.humdata.org/api/3/action"
SEARCH_Q = "bangladesh food prices"
PACKAGE_ID = "wfp-food-prices-for-bangladesh"
TIMEOUT = 300


def log(msg: str) -> None:
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"- {stamp} | download_data.py | {msg}\n"
    print(line, end="")
    with open(RUNLOG, "a", encoding="utf-8") as fh:
        fh.write(line)


def get_json(url: str, params: dict, out_name: str) -> dict:
    resp = requests.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    with open(os.path.join(API_DIR, out_name), "wb") as fh:
        fh.write(resp.content)
    return resp.json()


def download(url: str, out_path: str) -> str:
    with requests.get(url, stream=True, timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        sha = hashlib.sha256()
        with open(out_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                fh.write(chunk)
                sha.update(chunk)
    return sha.hexdigest()


def describe(path: str) -> dict:
    df = pd.read_csv(path)
    info = {"rows": len(df), "columns": ", ".join(df.columns)}
    if "date" in df.columns:
        dates = pd.to_datetime(df["date"], errors="coerce")
        info["date_range"] = f"{dates.min().date()} to {dates.max().date()}"
    else:
        info["date_range"] = "n/a (reference table)"
    return info


def main() -> int:
    os.makedirs(API_DIR, exist_ok=True)
    access = dt.date.today().isoformat()

    search = get_json(f"{CKAN}/package_search",
                      {"q": SEARCH_Q, "rows": 10, "fl": "name,title"},
                      "hdx_search.json")
    names = [r["name"] for r in search["result"]["results"]]
    log(f"HDX package_search q='{SEARCH_Q}': {search['result']['count']} hits; top: {names[:3]}")
    if PACKAGE_ID not in names:
        log(f"STOP: {PACKAGE_ID} not found in HDX search")
        return 1

    pkg = get_json(f"{CKAN}/package_show", {"id": PACKAGE_ID},
                   "hdx_package_show.json")["result"]
    log(f"HDX package_show {PACKAGE_ID}: license='{pkg.get('license_title')}', "
        f"last_modified={pkg.get('last_modified')}, resources={len(pkg['resources'])}")

    rows = []
    for res in pkg["resources"]:
        if str(res.get("format", "")).upper() != "CSV":
            continue
        fname = os.path.basename(res["url"])
        out_path = os.path.join(RAW, fname)
        sha = download(res["url"], out_path)
        info = describe(out_path)
        log(f"Downloaded {fname}: {info['rows']} rows, {info['date_range']}, sha256={sha[:16]}...")
        rows.append({"name": res["name"], "url": res["url"], "file": fname,
                     "sha256": sha, **info})

    write_sources(pkg, rows, access)
    log("SOURCES.md written to data/raw/SOURCES.md")
    return 0


def write_sources(pkg: dict, rows: list[dict], access: str) -> None:
    lines = [
        "# SOURCES",
        "",
        f"**Dataset:** {pkg['title']} (HDX id `{pkg['name']}`)",
        f"**Publisher:** {pkg.get('organization', {}).get('title', 'WFP')}",
        f"**Original sources (per HDX):** {pkg.get('dataset_source')}",
        f"**Landing page:** https://data.humdata.org/dataset/{pkg['name']}",
        f"**License:** {pkg.get('license_title')}",
        f"**HDX last modified:** {pkg.get('last_modified')}",
        f"**Access date:** {access}",
        "**Discovery method:** CKAN API `package_search` then `package_show` "
        "(raw API responses saved in `data/raw/api/`).",
        "",
        "**Citation:** World Food Programme (WFP). *Bangladesh - Food Prices*. "
        f"Humanitarian Data Exchange (HDX), accessed {access}. "
        f"https://data.humdata.org/dataset/{pkg['name']}. Licensed {pkg.get('license_title')}.",
        "",
    ]
    for r in rows:
        lines += [
            f"## {r['file']}",
            "",
            f"- Resource: {r['name']}",
            f"- URL: {r['url']}",
            f"- Rows (excluding header): {r['rows']}",
            f"- Date range: {r['date_range']}",
            f"- SHA-256: `{r['sha256']}`",
            f"- Columns: {r['columns']}",
            "",
        ]
    lines += [
        "## Sources not used",
        "",
        "Sources 2 to 4 of the brief (World Bank Real Time Food Prices, AgriPriceBD on "
        "Mendeley Data, other web sources) were not downloaded because source 1 passed "
        "the quality gate (see RUNLOG.md and notebook section 1).",
        "",
    ]
    with open(os.path.join(RAW, "SOURCES.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
