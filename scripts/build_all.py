"""Build portable CSV summaries, notebooks, and the interactive web map."""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

import folium
import pandas as pd
from folium.plugins import FastMarkerCluster, Fullscreen, MarkerCluster

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "kroger_us.geojson"
PROCESSED = ROOT / "data" / "processed"
DOCS = ROOT / "docs"


def clean_zip(value: object) -> str:
    match = re.search(r"\b(\d{5})\b", str(value or ""))
    return match.group(1) if match else ""


def load_locations(raw_path: Path = RAW) -> pd.DataFrame:
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    rows = []
    for feature in payload.get("features", []):
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") or [None, None]
        if geometry.get("type") != "Point" or len(coords) < 2:
            continue
        url = str(props.get("website") or "")
        banner = str(props.get("brand") or props.get("name") or "Unknown").strip()
        rows.append({
            "location_id": str(props.get("ref") or ""),
            "name": str(props.get("name") or banner).strip(),
            "brand": banner,
            "address": " ".join(filter(None, [str(props.get("addr:housenumber") or "").strip(), str(props.get("addr:street") or "").strip()])),
            "city": str(props.get("addr:city") or "").strip(),
            "state": str(props.get("addr:state") or "").strip().upper(),
            "zip_code": clean_zip(props.get("addr:postcode")),
            "phone": str(props.get("phone") or "").strip(),
            "latitude": float(coords[1]),
            "longitude": float(coords[0]),
            "website": url,
            "is_kroger_banner": banner.casefold() == "kroger" or str(props.get("name") or "").casefold().startswith("kroger"),
            # This source exports current OSM objects tagged shop=supermarket.
            # Lifecycle-prefixed objects (closed:/disused:/abandoned:) are not
            # present, so "active" is an OSM classification, not a real-time
            # confirmation from Kroger.
            "status": "active" if props.get("shop") == "supermarket" else "unknown",
            "status_basis": "Mapped as shop=supermarket in source; not real-time verified" if props.get("shop") == "supermarket" else "No current shop tag in source",
            "source": "OpenStreetMap via whubsch/atp-import",
        })
    df = pd.DataFrame(rows)
    df = df[df["state"].str.fullmatch(r"[A-Z]{2}", na=False)].copy()
    df = df.drop_duplicates(subset=["location_id", "latitude", "longitude"]).sort_values(["state", "city", "brand", "name"])
    return df.reset_index(drop=True)


def write_summaries(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    df.to_csv(PROCESSED / "kroger_family_locations.csv", index=False)
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
    kroger_only_input = bool(len(df)) and df["is_kroger_banner"].astype(bool).all()
    primary_label = "Official Kroger-banner locations" if kroger_only_input else "All Kroger-family locations"
    family = folium.FeatureGroup(name=f"{primary_label} ({len(df):,})", show=True)
    cluster = MarkerCluster(name="Locations", options={"disableClusteringAtZoom": 11}).add_to(family)
    for row in df.itertuples(index=False):
        website = str(row.website) if pd.notna(row.website) else ""
        safe_url = website if website.startswith("https://") else ""
        link = f'<br><a href="{safe_url}" target="_blank" rel="noopener">Store page</a>' if safe_url else ""
        popup = folium.Popup(f"<b>{row.name}</b><br>{row.brand}<br>{row.address}<br>{row.city}, {row.state} {row.zip_code}<br><b>Status:</b> {row.status}<br><small>{row.status_basis}</small>{link}", max_width=340)
        marker_color = "#238636" if row.status == "active" else ("#cf222e" if row.status == "inactive" else "#6e7781")
        folium.CircleMarker([row.latitude, row.longitude], radius=4, color="#0b4fa2", weight=1, fill=True, fill_color=marker_color, fill_opacity=.8, tooltip=f"{row.brand} — {row.city}, {row.state} — {row.status}", popup=popup).add_to(cluster)
    family.add_to(m)
    kroger = df[df["is_kroger_banner"]]
    # Add a separate Kroger-only layer only when the input also contains other
    # Kroger-family banners. For a KROGER-only official API export it would be
    # an exact duplicate of the main layer.
    if 0 < len(kroger) < len(df):
        FastMarkerCluster(kroger[["latitude", "longitude"]].values.tolist(), name=f"Kroger banner only ({len(kroger):,})", show=False).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    title = f'''<div style="position:fixed;top:10px;left:50px;z-index:9999;background:white;padding:10px 14px;border:1px solid #bbb;border-radius:6px;font:14px Arial;box-shadow:0 1px 5px #999"><b>Kroger National Coverage</b><br>{len(df):,} Kroger-family supermarket records · {df['state'].nunique()} states<br><small>Source: OpenStreetMap contributors · built {date.today().isoformat()}</small></div>'''
    m.get_root().html.add_child(folium.Element(title))
    m.save(DOCS / "index.html")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=RAW)
    parser.add_argument("--locations", type=Path, help="Use an already-cleaned location CSV, such as the official API export")
    args = parser.parse_args()
    if args.locations:
        location_path = args.locations if args.locations.is_absolute() else ROOT / args.locations
        df = pd.read_csv(location_path, dtype={"zip_code": "string"}).fillna({"website": "", "phone": "", "address": "", "city": ""})
    else:
        df = load_locations(args.raw)
    state, zipcode, brand = write_summaries(df)
    build_map(df, state)
    print(f"Built {len(df):,} locations, {len(state)} states, {len(zipcode):,} state/ZIP groups, and docs/index.html")


if __name__ == "__main__":
    main()
