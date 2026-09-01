"""Build portable CSV summaries, notebooks, and the interactive web map."""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import folium
import pandas as pd
from folium.plugins import Fullscreen, MarkerCluster

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
DOCS = ROOT / "docs"


def write_summaries(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    if not df["source"].eq("Kroger official Locations API").all():
        raise ValueError("Only Kroger official Locations API records are supported.")
    df = df.assign(_active=df["status"].eq("active"), _inactive=df["status"].eq("inactive"), _unknown=df["status"].eq("unknown"))
    state = (df.groupby("state", as_index=False).agg(locations=("location_id", "size"), active_locations=("_active", "sum"), inactive_locations=("_inactive", "sum"), unknown_status_locations=("_unknown", "sum"), kroger_banner_locations=("is_kroger_banner", "sum"), brands=("brand", "nunique")).sort_values("locations", ascending=False))
    zipcode = (df[df["zip_code"].ne("")].groupby(["state", "zip_code"], as_index=False).agg(locations=("location_id", "size"), active_locations=("_active", "sum"), inactive_locations=("_inactive", "sum"), unknown_status_locations=("_unknown", "sum"), kroger_banner_locations=("is_kroger_banner", "sum"), brands=("brand", "nunique")).sort_values(["locations", "state", "zip_code"], ascending=[False, True, True]))
    brand = (df.groupby("brand", as_index=False).agg(locations=("location_id", "size"), active_locations=("_active", "sum"), inactive_locations=("_inactive", "sum"), unknown_status_locations=("_unknown", "sum"), states=("state", "nunique")).sort_values("locations", ascending=False))
    state.to_csv(PROCESSED / "state_summary.csv", index=False)
    zipcode.to_csv(PROCESSED / "zip_summary.csv", index=False)
    brand.to_csv(PROCESSED / "brand_summary.csv", index=False)
    return state, zipcode, brand


def build_map(df: pd.DataFrame, state: pd.DataFrame) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    m = folium.Map(location=[39.5, -98.35], zoom_start=4, tiles="CartoDB positron", control_scale=True, prefer_canvas=True)
    Fullscreen(position="topright").add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
    palette = ["#005da6", "#e31837", "#238636", "#8250df", "#bf8700", "#0969da", "#cf222e", "#1a7f37"]
    for brand_index, (brand, brand_frame) in enumerate(df.groupby("brand", sort=True)):
        layer = folium.FeatureGroup(name=f"{brand} ({len(brand_frame):,})", show=True)
        cluster = MarkerCluster(options={"disableClusteringAtZoom": 11}).add_to(layer)
        brand_color = palette[brand_index % len(palette)]
        for row in brand_frame.itertuples(index=False):
            website = str(row.website) if pd.notna(row.website) else ""
            safe_url = website if website.startswith("https://") else ""
            link = f'<br><a href="{safe_url}" target="_blank" rel="noopener">Store page</a>' if safe_url else ""
            popup = folium.Popup(f"<b>{row.name}</b><br><b>Banner:</b> {row.brand}<br>{row.address}<br>{row.city}, {row.state} {row.zip_code}<br><b>Status:</b> {row.status}<br><small>{row.status_basis}</small>{link}", max_width=340)
            folium.CircleMarker([row.latitude, row.longitude], radius=4, color="#333", weight=1, fill=True, fill_color=brand_color, fill_opacity=.8, tooltip=f"{row.brand} — {row.city}, {row.state} — {row.status}", popup=popup).add_to(cluster)
        layer.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    record_label = "official Kroger-family supermarket locations"
    data_source = "Kroger official Locations API"
    title = f'''<div style="position:fixed;top:10px;left:50px;z-index:9999;background:white;padding:10px 14px;border:1px solid #bbb;border-radius:6px;font:14px Arial;box-shadow:0 1px 5px #999"><b>Kroger National Coverage</b><br>{len(df):,} {record_label} · {df['state'].nunique()} states<br><small>Data source: {data_source} · built {date.today().isoformat()}</small></div>'''
    m.get_root().html.add_child(folium.Element(title))
    m.save(DOCS / "index.html")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--locations", type=Path, default=Path("data/processed/kroger_family_official_locations.csv"), help="Official Kroger-family API location CSV")
    args = parser.parse_args()
    print("[1/4] Loading location data...")
    location_path = args.locations if args.locations.is_absolute() else ROOT / args.locations
    df = pd.read_csv(location_path, dtype={"zip_code": "string"}).fillna({"website": "", "phone": "", "address": "", "city": ""})
    print(f"[2/4] Loaded {len(df):,} locations. Writing summary files...")
    state, zipcode, brand = write_summaries(df)
    print("[3/4] Building interactive web map...")
    build_map(df, state)
    print(f"[4/4] Complete: built {len(df):,} locations, {len(state)} states, {len(zipcode):,} state/ZIP groups, and docs/index.html")


if __name__ == "__main__":
    main()
