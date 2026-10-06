"""Fetch SDG 7 (Affordable and Clean Energy) indicator data from the UN Statistics Division SDG API (v5).

Writes one cached JSON file per series to data/raw/. Responses are cached because a
full pull is slow; re-running is a no-op unless --refresh is passed.

Usage:
    python scripts/01_fetch_un_sdg.py
    python scripts/01_fetch_un_sdg.py --refresh
    python scripts/01_fetch_un_sdg.py --series EG_EGY_CLEAN
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests

BASE_URL = "https://unstats.un.org/sdgs/UNSDGAPIV5/v1/sdg"
RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

YEARS = list(range(2015, 2025))  # 2015-2024, per the ISS brief
PAGE_SIZE = 2000
TIMEOUT = 180
MAX_RETRIES = 3

# The SDG 7 series this project uses. Descriptions are the UN's own wording.
SERIES = {
    "EG_ACS_ELEC": "7.1.1 Proportion of population with access to electricity, by urban/rural (%)",
    "EG_EGY_CLEAN": "7.1.2 Proportion of population with primary reliance on clean fuels and technology (%)",
    "EG_FEC_RNEW": "7.2.1 Renewable energy share in the total final energy consumption (%)",
    "EG_EGY_PRIM": "7.3.1 Energy intensity level of primary energy (MJ per constant 2021 PPP GDP)",
}


def get(path, params=None):
    """GET with retries. The UN API is reliable but slow and occasionally times out."""
    url = f"{BASE_URL}{path}"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, params=params, timeout=TIMEOUT)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            if attempt == MAX_RETRIES:
                raise
            wait = 5 * attempt
            print(f"    attempt {attempt} failed ({exc}); retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)


def fetch_series(code):
    """Page through /Series/Data for one series, restricted to YEARS."""
    params = [("seriesCode", code), ("pageSize", PAGE_SIZE)]
    params += [("timePeriod", year) for year in YEARS]

    rows = []
    page = 1
    meta = {}
    while True:
        payload = get("/Series/Data", params=params + [("page", page)])
        rows.extend(payload["data"])
        total_pages = payload.get("totalPages", 1)
        if page == 1:
            # Dimension and attribute code lists only need capturing once.
            meta = {k: v for k, v in payload.items() if k != "data"}
            print(f"    {payload.get('totalElements')} records across {total_pages} page(s)")
        if page >= total_pages:
            break
        page += 1

    return rows, meta


def write_cache(path, body):
    path.write_text(json.dumps(body, indent=1))
    size_kb = path.stat().st_size / 1024
    print(f"    wrote {path.name} ({size_kb:,.0f} KB)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="re-download even if cached")
    parser.add_argument("--series", nargs="*", help="limit to specific series codes")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    codes = args.series or list(SERIES)

    for code in codes:
        if code not in SERIES:
            print(f"!! unknown series {code}; skipping", file=sys.stderr)
            continue

        out_path = RAW_DIR / f"{code}.json"
        if out_path.exists() and not args.refresh:
            cached = json.loads(out_path.read_text())
            print(f"[cached] {code}: {len(cached['data'])} records — use --refresh to re-pull")
            continue

        print(f"[fetch]  {code} — {SERIES[code]}")
        started = time.time()
        rows, meta = fetch_series(code)
        write_cache(
            out_path,
            {
                "series_code": code,
                "description": SERIES[code],
                "source_api": BASE_URL,
                "years_requested": YEARS,
                "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "record_count": len(rows),
                "api_metadata": meta,
                "data": rows,
            },
        )
        print(f"    done in {time.time() - started:.0f}s")

    # Region lookup, needed to tell countries apart from aggregates.
    tree_path = RAW_DIR / "geoarea_tree.json"
    if not tree_path.exists() or args.refresh:
        print("[fetch]  GeoArea/Tree — country/region hierarchy")
        write_cache(tree_path, get("/GeoArea/Tree"))
    else:
        print("[cached] geoarea_tree.json")


if __name__ == "__main__":
    main()
