"""Collect Kroger-banner locations from Kroger's official public Locations API.

The API only supports proximity searches. This script uses the existing public
location snapshot solely to choose geographically distributed search centers;
every exported store record comes from Kroger's official API response.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
TOKEN_URL = "https://api.kroger.com/v1/connect/oauth2/token"
LOCATIONS_URL = "https://api.kroger.com/v1/locations"


def load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def get_token(session: requests.Session) -> str:
    client_id = os.getenv("KROGER_CLIENT_ID", "").strip()
    client_secret = os.getenv("KROGER_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise SystemExit("Missing credentials. Copy .env.example to .env and add KROGER_CLIENT_ID and KROGER_CLIENT_SECRET.")
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    response = session.post(
        TOKEN_URL,
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials", "scope": "product.compact"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    x = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 3958.8 * 2 * math.asin(math.sqrt(x))


def choose_centers(points: list[tuple[float, float]], spacing_miles: float) -> list[tuple[float, float]]:
    centers: list[tuple[float, float]] = []
    for point in sorted(set(points)):
        if not any(miles(point, center) <= spacing_miles for center in centers):
            centers.append(point)
    return centers


def flatten(location: dict, collected_at: str) -> dict:
    address = location.get("address") or {}
    coordinates = location.get("geolocation") or {}
    chain = str(location.get("chain") or "")
    return {
        "location_id": str(location.get("locationId") or ""),
        "name": str(location.get("name") or chain),
        "brand": chain,
        "address": str(address.get("addressLine1") or ""),
        "city": str(address.get("city") or ""),
        "state": str(address.get("state") or "").upper(),
        "zip_code": str(address.get("zipCode") or "")[:5],
        "phone": str(location.get("phone") or ""),
        "latitude": coordinates.get("latitude"),
        "longitude": coordinates.get("longitude"),
        "website": "",
        "is_kroger_banner": chain.casefold() == "kroger",
        "status": "active",
        "status_basis": f"Returned by Kroger official Locations API on {collected_at[:10]}",
        "source": "Kroger official Locations API",
        "api_collected_at_utc": collected_at,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", default="KROGER", help="Official chain name; default: KROGER")
    parser.add_argument("--radius", type=int, default=25, help="Search radius in miles")
    parser.add_argument("--spacing", type=float, default=18, help="Maximum spacing between search centers")
    parser.add_argument("--delay", type=float, default=0.12, help="Delay between API calls")
    args = parser.parse_args()
    load_dotenv()
    seed_path = ROOT / "data" / "processed" / "kroger_official_locations.csv"
    if not seed_path.exists():
        raise SystemExit("Bootstrap file data/processed/kroger_official_locations.csv is missing.")
    seeds = pd.read_csv(seed_path)
    if args.chain.casefold() == "kroger":
        seeds = seeds[seeds["is_kroger_banner"].astype(str).str.casefold().eq("true")]
    points = list(zip(seeds["latitude"].astype(float), seeds["longitude"].astype(float)))
    centers = choose_centers(points, args.spacing)
    if len(centers) > 1550:
        raise SystemExit(f"Planned {len(centers)} calls, too close to the 1,600/day limit. Increase --spacing.")

    session = requests.Session()
    token = get_token(session)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    stores: dict[str, dict] = {}
    collected_at = datetime.now(timezone.utc).isoformat()
    raw_batches = []
    for number, (lat, lon) in enumerate(centers, 1):
        params = {
            "filter.latLong.near": f"{lat:.6f},{lon:.6f}",
            "filter.radiusInMiles": args.radius,
            "filter.limit": 50,
            "filter.chain": args.chain,
        }
        response = session.get(LOCATIONS_URL, headers=headers, params=params, timeout=30)
        if response.status_code == 401:
            token = get_token(session)
            headers["Authorization"] = f"Bearer {token}"
            response = session.get(LOCATIONS_URL, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        raw_batches.append({"center": [lat, lon], "response": payload})
        for item in payload.get("data", []):
            if item.get("locationId"):
                stores[str(item["locationId"])] = item
        if number % 50 == 0:
            print(f"{number}/{len(centers)} searches; {len(stores)} unique stores")
        time.sleep(args.delay)

    raw_path = ROOT / "data" / "raw" / "kroger_official_api_response.json"
    raw_path.write_text(json.dumps({"collected_at_utc": collected_at, "chain": args.chain, "batches": raw_batches}, indent=2), encoding="utf-8")
    frame = pd.DataFrame(flatten(item, collected_at) for item in stores.values())
    frame = frame.sort_values(["state", "city", "name"]).reset_index(drop=True)
    output = ROOT / "data" / "processed" / "kroger_official_locations.csv"
    frame.to_csv(output, index=False)
    print(f"Saved {len(frame):,} official API locations to {output.relative_to(ROOT)} using {len(centers)} API calls")
    print("Run: python scripts/build_all.py --locations data/processed/kroger_official_locations.csv")


if __name__ == "__main__":
    main()
