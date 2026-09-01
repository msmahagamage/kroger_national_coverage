"""Collect Kroger-owned U.S. supermarket banners from the official Locations API."""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
TOKEN_URL = "https://api.kroger.com/v1/connect/oauth2/token"
API_ROOT = "https://api.kroger.com/v1"
OUTPUT = ROOT / "data" / "processed" / "kroger_family_official_locations.csv"
SUPERMARKET_CHAINS = (
    "BAKERS", "CITYMARKET", "DILLONS", "FOOD4LESS", "FOODSCO", "FRED",
    "FRYS", "GERBES", "HART", "JAYC", "KINGSOOPERS", "KROGER",
    "MARIANOS", "METRO MARKET", "PAYLESS", "PICK N SAVE", "QFC",
    "RALPHS", "RULER", "SMITHS",
)
NON_STORE_PATTERN = re.compile(
    r"\b(fuel|logistics|distribution|warehouse|clinic|jewelry|laboratory|lab location|office|plant)\b",
    re.IGNORECASE,
)


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
        raise SystemExit("Missing credentials. Copy .env.example to .env and configure both Kroger credential values.")
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
    value = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 3958.8 * 2 * math.asin(math.sqrt(value))


def choose_centers(points: list[tuple[float, float]], spacing_miles: float) -> list[tuple[float, float]]:
    centers: list[tuple[float, float]] = []
    for point in sorted(set(points)):
        if not any(miles(point, center) <= spacing_miles for center in centers):
            centers.append(point)
    return centers


def coordinates(items: list[dict]) -> list[tuple[float, float]]:
    result = []
    for item in items:
        geo = item.get("geolocation") or {}
        if geo.get("latitude") is not None and geo.get("longitude") is not None:
            result.append((float(geo["latitude"]), float(geo["longitude"])))
    return result


def is_supermarket(item: dict) -> bool:
    name = str(item.get("name") or "")
    return bool(name) and not NON_STORE_PATTERN.search(name)


def flatten(item: dict, collected_at: str) -> dict:
    address = item.get("address") or {}
    geo = item.get("geolocation") or {}
    chain = str(item.get("chain") or "")
    return {
        "location_id": str(item.get("locationId") or ""), "name": str(item.get("name") or chain),
        "brand": chain, "address": str(address.get("addressLine1") or ""),
        "city": str(address.get("city") or ""), "state": str(address.get("state") or "").upper(),
        "zip_code": str(address.get("zipCode") or "")[:5], "phone": str(item.get("phone") or ""),
        "latitude": geo.get("latitude"), "longitude": geo.get("longitude"), "website": "",
        "is_kroger_banner": chain == "KROGER", "status": "active",
        "status_basis": f"Returned by Kroger official Locations API on {collected_at[:10]}",
        "source": "Kroger official Locations API", "api_collected_at_utc": collected_at,
        "department_count": len(item.get("departments") or []),
    }


class KrogerClient:
    def __init__(self, delay: float):
        self.session = requests.Session()
        self.delay = delay
        self.token = get_token(self.session)
        self.calls = 0

    def get(self, endpoint: str, params: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        response = self.session.get(f"{API_ROOT}/{endpoint}", headers=headers, params=params, timeout=30)
        if response.status_code == 401:
            self.token = get_token(self.session)
            headers["Authorization"] = f"Bearer {self.token}"
            response = self.session.get(f"{API_ROOT}/{endpoint}", headers=headers, params=params, timeout=30)
        response.raise_for_status()
        self.calls += 1
        time.sleep(self.delay)
        return response.json()


def bootstrap_points(chain: str) -> list[tuple[float, float]]:
    for path in (OUTPUT,):
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        if "brand" in frame:
            frame = frame[frame["brand"].astype(str).eq(chain)]
        if len(frame):
            return list(zip(frame["latitude"].astype(float), frame["longitude"].astype(float)))
    return []


def collect_chain(client: KrogerClient, chain: str, radius: int, spacing: float) -> tuple[dict[str, dict], list[dict]]:
    raw_batches: list[dict] = []
    first = client.get("locations", {"filter.chain": chain, "filter.limit": 200})
    raw_batches.append({"chain": chain, "method": "national", "response": first})
    stores = {str(x["locationId"]): x for x in first.get("data", []) if x.get("locationId")}
    seed_points = bootstrap_points(chain) if chain == "KROGER" else []
    if len(stores) >= 190:
        seed_points.extend(coordinates(list(stores.values())))
    centers = choose_centers(seed_points, spacing)
    for number, (lat, lon) in enumerate(centers, 1):
        payload = client.get("locations", {
            "filter.chain": chain, "filter.latLong.near": f"{lat:.6f},{lon:.6f}",
            "filter.radiusInMiles": radius, "filter.limit": 200,
        })
        raw_batches.append({"chain": chain, "method": "proximity", "center": [lat, lon], "response": payload})
        for item in payload.get("data", []):
            if item.get("locationId"):
                stores[str(item["locationId"])] = item
        if number % 50 == 0:
            print(f"      {chain}: {number}/{len(centers)} searches; {len(stores):,} unique records")
    return stores, raw_batches


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", help="Collect one official chain instead of all supermarket banners")
    parser.add_argument("--radius", type=int, default=25)
    parser.add_argument("--spacing", type=float, default=18)
    parser.add_argument("--delay", type=float, default=0.10)
    args = parser.parse_args()
    load_dotenv()
    client = KrogerClient(args.delay)
    print("[1/5] Retrieving Kroger's official chain catalog...")
    official_chains = {x.get("name") for x in client.get("chains").get("data", [])}
    chains = (args.chain.upper(),) if args.chain else SUPERMARKET_CHAINS
    missing = sorted(set(chains) - official_chains)
    if missing:
        raise SystemExit(f"Chains not returned by Kroger's official catalog: {missing}")
    print(f"[2/5] Collecting {len(chains)} supermarket banner(s)...")
    all_stores: dict[str, dict] = {}
    all_batches: list[dict] = []
    for index, chain in enumerate(chains, 1):
        stores, batches = collect_chain(client, chain, args.radius, args.spacing)
        retail = {key: value for key, value in stores.items() if is_supermarket(value)}
        excluded = len(stores) - len(retail)
        all_stores.update(retail)
        all_batches.extend(batches)
        print(f"    [{index}/{len(chains)}] {chain}: {len(retail):,} supermarkets; {excluded} non-store facilities excluded")
        if client.calls > 1500:
            raise RuntimeError("Stopped before Kroger's 1,600-call daily limit.")
    collected_at = datetime.now(timezone.utc).isoformat()
    print(f"[3/5] Deduplicating {len(all_stores):,} official supermarket records...")
    frame = pd.DataFrame(flatten(item, collected_at) for item in all_stores.values())
    frame = frame.dropna(subset=["latitude", "longitude"])
    frame = frame[frame["state"].str.fullmatch(r"[A-Z]{2}", na=False)]
    frame = frame.sort_values(["brand", "state", "city", "name"]).reset_index(drop=True)
    print("[4/5] Writing official CSV and local audit response...")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUTPUT, index=False)
    raw_path = ROOT / "data" / "raw" / "kroger_family_official_api_response.json"
    raw_path.write_text(json.dumps({"collected_at_utc": collected_at, "chains": list(chains), "batches": all_batches}, indent=2), encoding="utf-8")
    print(f"[5/5] Complete: {len(frame):,} supermarkets across {frame['brand'].nunique()} banners and {frame['state'].nunique()} states using {client.calls} API calls.")
    print(f"      Output: {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
