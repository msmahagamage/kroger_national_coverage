# Kroger National Coverage

A portable, GitHub-ready analysis of official U.S. Kroger-banner locations.
Every project file reference is relative to the repository root; the project can
be moved, copied to another computer, or published on GitHub without editing
local paths.

## Included

- `data/raw/kroger_official_api_response.json` — local official API audit response (ignored by Git)
- `data/processed/kroger_official_locations.csv` — official API location export
- `data/processed/kroger_family_locations.csv` — cleaned location-level data
- `data/processed/state_summary.csv` — counts by state
- `data/processed/zip_summary.csv` — counts by state and ZIP code
- `data/processed/brand_summary.csv` — counts by store banner
- `notebooks/00_download_official_api.ipynb` — credential-safe official API collector
- `notebooks/01_prepare_locations.ipynb` — cleaning and QA workflow
- `notebooks/02_coverage_summary.ipynb` — state, ZIP, and banner summary
- `notebooks/03_build_web_map.ipynb` — interactive-map workflow
- `docs/index.html` — ready-to-publish web map
- `scripts/build_all.py` — one-command rebuild

## Scope

The current dataset was collected from Kroger's official Locations API using
the `KROGER` chain filter. It contains Kroger and Kroger Marketplace locations,
not other Kroger-owned banners such as Ralphs, Smith's, King Soopers, QFC,
Mariano's, or Pick 'n Save.

## Quick start

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/build_all.py
jupyter lab
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
python scripts/build_all.py
jupyter lab
```

Open `docs/index.html` directly, or publish `/docs` with GitHub Pages. The
location data is embedded in the HTML; an internet connection is still needed
for map tiles and the Leaflet assets loaded over HTTPS.

## Use Kroger's official Locations API

1. Create an account and register an application at
   https://developer.kroger.com/ to obtain OAuth2 client credentials.
2. Copy `.env.example` to `.env` and enter the client ID and secret. `.env` is
   ignored by Git and must never be committed.
3. Run the official collector, then rebuild from its output:

```powershell
Copy-Item .env.example .env
python scripts/download_official_api.py --chain KROGER
python scripts/build_all.py --locations data/processed/kroger_official_locations.csv
```

The official endpoint is proximity-based and limited to 1,600 calls per day.
The collector uses geographically distributed seed points, deduplicates by
Kroger `locationId`, and exports only records actually returned by Kroger. Its
`active` status means the store was returned by the official API on the date in
`api_collected_at_utc`; the public API does not provide historical closed-store
records. The ignored raw response file preserves an audit trail locally.

## Attribution and licensing

Location records are returned by Kroger's official
Locations API and remain subject to Kroger's API terms.

## Store status

Every location has `status` and `status_basis` columns. A record is classified
`active` when Kroger's official Locations API returned it on the collection
date stored in `api_collected_at_utc`. The public API does not provide a
historical list of closed stores.
