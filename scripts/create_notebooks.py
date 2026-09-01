"""Create the three documented Jupyter notebooks for this repository."""
from pathlib import Path
import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
NB = ROOT / "notebooks"
NB.mkdir(exist_ok=True)

setup = '''from pathlib import Path
import sys

def find_project_root(start=Path.cwd()):
    for candidate in [start, *start.parents]:
        if (candidate / "scripts" / "build_all.py").exists():
            return candidate
    raise FileNotFoundError("Run this notebook from inside the repository.")

ROOT = find_project_root()
sys.path.insert(0, str(ROOT / "scripts"))
ROOT'''

def notebook(title, intro, cells):
    nb = nbf.v4.new_notebook()
    nb["metadata"]["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
    nb["metadata"]["language_info"] = {"name": "python", "version": "3"}
    nb["cells"] = [nbf.v4.new_markdown_cell(f"# {title}\n\n{intro}"), nbf.v4.new_code_cell(setup), *cells]
    return nb

nb0 = notebook(
    "00 — Download from Kroger's official API",
    "Use OAuth2 client credentials to collect Kroger-banner locations from Kroger's official proximity-based Locations API. Create `.env` from `.env.example` first. Secrets are never displayed or stored in this notebook.",
    [
        nbf.v4.new_markdown_cell("## Credential setup\n\nRegister an application at https://developer.kroger.com/. Copy `.env.example` to `.env`, then enter `KROGER_CLIENT_ID` and `KROGER_CLIENT_SECRET`. The `.env` file is excluded from Git."),
        nbf.v4.new_code_cell("import subprocess, sys\n\nresult = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'download_official_api.py'), '--chain', 'KROGER'], cwd=ROOT)\nif result.returncode:\n    raise RuntimeError('Official API collection failed. Check .env credentials and the messages above.')"),
        nbf.v4.new_code_cell("import pandas as pd\nofficial = pd.read_csv(ROOT / 'data' / 'processed' / 'kroger_official_locations.csv', dtype={'zip_code': 'string'})\nprint(f'{len(official):,} unique official API locations')\nofficial.head()"),
    ],
)

nb1 = notebook(
    "01 — Prepare official Kroger API locations",
    "Download or load Kroger locations from Kroger's official Locations API, validate them, and write the portable state, ZIP, and brand summaries. This notebook does not silently fall back to OpenStreetMap data.",
    [
        nbf.v4.new_markdown_cell("## Official API download\n\nCreate `.env` from `.env.example` and add your Kroger developer credentials. Set `RUN_OFFICIAL_DOWNLOAD = True` to refresh the data. The downloader uses OAuth2, respects Kroger's daily request limit, and never writes credentials to output files."),
        nbf.v4.new_code_cell("import subprocess, sys\n\nRUN_OFFICIAL_DOWNLOAD = False  # Change to True after configuring .env\n\nif RUN_OFFICIAL_DOWNLOAD:\n    result = subprocess.run(\n        [sys.executable, str(ROOT / 'scripts' / 'download_official_api.py'), '--chain', 'KROGER'],\n        cwd=ROOT,\n    )\n    if result.returncode:\n        raise RuntimeError('Official Kroger API download failed. Check your .env credentials.')\nelse:\n    print('Download skipped. Set RUN_OFFICIAL_DOWNLOAD=True to refresh from Kroger.')"),
        nbf.v4.new_code_cell("import pandas as pd\nfrom build_all import write_summaries\n\nofficial_path = ROOT / 'data' / 'processed' / 'kroger_official_locations.csv'\nif not official_path.exists():\n    raise FileNotFoundError(\n        'Official API export not found. Configure .env, set RUN_OFFICIAL_DOWNLOAD=True, and run the previous cell.'\n    )\nlocations = pd.read_csv(official_path, dtype={'zip_code': 'string'}).fillna({'website':'', 'phone':'', 'address':'', 'city':''})\nassert locations['source'].eq('Kroger official Locations API').all(), 'Non-official records detected'\nstate_summary, zip_summary, brand_summary = write_summaries(locations)\nprint(f'Using {len(locations):,} locations returned by Kroger official API')\nlocations.head()"),
        nbf.v4.new_markdown_cell("## Quality checks\n\nMissing values are reported explicitly. A missing ZIP is retained in the location file but excluded from the ZIP summary."),
        nbf.v4.new_code_cell("locations[['location_id','brand','state','zip_code','status','status_basis','latitude','longitude']].isna().sum().to_frame('missing')"),
        nbf.v4.new_markdown_cell("## Store status\n\n`active` means the source currently maps the record as `shop=supermarket`. It is not a real-time confirmation from Kroger. Lifecycle-tagged closed/disused objects are not present in this source export."),
        nbf.v4.new_code_cell("locations.groupby(['status', 'status_basis'], dropna=False).size().to_frame('locations')"),
        nbf.v4.new_code_cell("locations.loc[locations['zip_code'].eq(''), ['name','brand','city','state','website']].head(20)"),
        nbf.v4.new_code_cell("assert locations['state'].str.fullmatch(r'[A-Z]{2}').all()\nassert locations['latitude'].between(18, 72).all()\nassert locations['longitude'].between(-180, -60).all()\nprint('Basic U.S. coordinate and state checks passed.')"),
    ],
)

nb2 = notebook(
    "02 — Coverage summary by state and ZIP code",
    "Summarize all Kroger-family records and the Kroger banner subset. The state and ZIP tables are also saved under `data/processed/`.",
    [
        nbf.v4.new_code_cell("import pandas as pd\nimport matplotlib.pyplot as plt\n\nlocations = pd.read_csv(ROOT / 'data' / 'processed' / 'kroger_family_locations.csv', dtype={'zip_code': 'string'})\nstate_summary = pd.read_csv(ROOT / 'data' / 'processed' / 'state_summary.csv')\nzip_summary = pd.read_csv(ROOT / 'data' / 'processed' / 'zip_summary.csv', dtype={'zip_code': 'string'})\nbrand_summary = pd.read_csv(ROOT / 'data' / 'processed' / 'brand_summary.csv')"),
        nbf.v4.new_markdown_cell("## National totals"),
        nbf.v4.new_code_cell("pd.Series({'all_family_locations': len(locations), 'active_locations': int(locations['status'].eq('active').sum()), 'inactive_locations': int(locations['status'].eq('inactive').sum()), 'unknown_status_locations': int(locations['status'].eq('unknown').sum()), 'kroger_banner_locations': int(locations['is_kroger_banner'].sum()), 'states': locations['state'].nunique(), 'zip_codes': locations['zip_code'].nunique(), 'brands': locations['brand'].nunique()}).to_frame('value')"),
        nbf.v4.new_markdown_cell("Status is based on OpenStreetMap lifecycle tagging, not real-time verification with Kroger."),
        nbf.v4.new_markdown_cell("## State summary"),
        nbf.v4.new_code_cell("state_summary.style.format({'locations': '{:,.0f}', 'kroger_banner_locations': '{:,.0f}', 'brands': '{:,.0f}'})"),
        nbf.v4.new_code_cell("plot_data = state_summary.sort_values('locations')\nax = plot_data.plot.barh(x='state', y=['locations','kroger_banner_locations'], figsize=(10, max(6, len(plot_data)*0.22)), color=['#0b4fa2','#e31837'])\nax.set(title='Kroger-family coverage by state', xlabel='Mapped locations', ylabel='State')\nax.grid(axis='x', alpha=.25)\nplt.tight_layout()"),
        nbf.v4.new_markdown_cell("## ZIP-code summary\n\n`state` is included with ZIP to keep grouping unambiguous and easy to filter."),
        nbf.v4.new_code_cell("zip_summary.head(30)"),
        nbf.v4.new_markdown_cell("## Banner summary"),
        nbf.v4.new_code_cell("brand_summary.head(30)"),
    ],
)

nb3 = notebook(
    "03 — Build the interactive web map",
    "Generate `docs/index.html`, which embeds the location points and can be published from GitHub Pages. No machine-specific file paths are stored in the output.",
    [
        nbf.v4.new_code_cell("import pandas as pd\nfrom build_all import build_map\n\nlocations = pd.read_csv(ROOT / 'data' / 'processed' / 'kroger_family_locations.csv', dtype={'zip_code': 'string'}).fillna('')\nstate_summary = pd.read_csv(ROOT / 'data' / 'processed' / 'state_summary.csv')\nbuild_map(locations, state_summary)\nprint('Created:', ROOT / 'docs' / 'index.html')"),
        nbf.v4.new_markdown_cell("## Preview\n\nJupyter can display the generated page in an iframe. The map needs internet access for Leaflet and basemap tiles."),
        nbf.v4.new_code_cell("from IPython.display import IFrame\nIFrame(src='../docs/index.html', width='100%', height=650)"),
    ],
)

for name, nb in [
    ("00_download_official_api.ipynb", nb0),
    ("01_prepare_locations.ipynb", nb1),
    ("02_coverage_summary.ipynb", nb2),
    ("03_build_web_map.ipynb", nb3),
]:
    nbf.write(nb, NB / name)
    print("Created", NB / name)
