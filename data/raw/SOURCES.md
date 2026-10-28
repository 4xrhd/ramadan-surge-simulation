# SOURCES

**Dataset:** Bangladesh - Food Prices (HDX id `wfp-food-prices-for-bangladesh`)
**Publisher:** WFP - World Food Programme
**Original sources (per HDX):** Bangladesh Milk producer's Co-Operative Union Ltd, Bangladesh via FAO: GIEWS, DAM, Department of Agricultural Marketing, Department of Agriculture Marketing (DAM), FPMA, WFP Market Data Collection, Website of Department of Agricultural Marketing
**Landing page:** https://data.humdata.org/dataset/wfp-food-prices-for-bangladesh
**License:** Creative Commons Attribution for Intergovernmental Organisations (CC BY-IGO)
**HDX last modified:** 2026-10-25T18:09:51.180093
**Access date:** 2026-10-27
**Discovery method:** CKAN API `package_search` then `package_show` (raw API responses saved in `data/raw/api/`).

**Citation:** World Food Programme (WFP). *Bangladesh - Food Prices*. Humanitarian Data Exchange (HDX), accessed 2026-10-27. https://data.humdata.org/dataset/wfp-food-prices-for-bangladesh. Licensed Creative Commons Attribution for Intergovernmental Organisations (CC BY-IGO).

## wfp_food_prices_bgd.csv

- Resource: Bangladesh - Food Prices
- URL: https://data.humdata.org/dataset/c76eabb7-fdb5-43b7-a5c4-09091bb8acde/resource/966ab7ac-56d6-4dac-8eba-dfe815d59a52/download/wfp_food_prices_bgd.csv
- Rows (excluding header): 34491
- Date range: 1900-08-15 to 2026-09-15
- SHA-256: `b003cd22f0884c47d7b8c4527041ede4920b59da4dc0d1e4b31b10be4dd03765`
- Columns: date, admin1, admin2, market, market_id, latitude, longitude, category, commodity, commodity_id, unit, priceflag, pricetype, currency, price, usdprice

## wfp_markets_bgd.csv

- Resource: Bangladesh - Markets
- URL: https://data.humdata.org/dataset/c76eabb7-fdb5-43b7-a5c4-09091bb8acde/resource/60852e15-3e4c-43eb-abf0-650e83c8eb91/download/wfp_markets_bgd.csv
- Rows (excluding header): 171
- Date range: n/a (reference table)
- SHA-256: `dface2af12e1f1924cf4b34a129feef09ce384488ca59a72c63f7ff72961c39a`
- Columns: market_id, market, countryiso3, admin1, admin2, latitude, longitude

## Sources not used

Sources 2 to 4 of the brief (World Bank Real Time Food Prices, AgriPriceBD on Mendeley Data, other web sources) were not downloaded because source 1 passed the quality gate (see RUNLOG.md and notebook section 1).
