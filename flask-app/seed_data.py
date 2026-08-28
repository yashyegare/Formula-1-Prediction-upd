#!/usr/bin/env python3
"""
Seed the F1 SQLite database from the Jolpica (Ergast) API.

Usage:
    python seed_data.py              # Seed all seasons (1981–2026)
    python seed_data.py --year 2026  # Seed only one season
    python seed_data.py --reseed     # Drop and re-create everything

First run takes ~5-8 minutes (fetches ~40 seasons × ~23 rounds each).
Subsequent runs skip already-seeded years unless --reseed is used.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Optional

from database import (
    init_db, is_seeded, insert_season, insert_race, insert_driver,
    insert_constructor, insert_result, insert_standing,
    get_connection, get_db_path,
)

# ── Constants ────────────────────────────────────────────────────────────

BASE_URLS = [
    "https://api.jolpi.ca/ergast/f1",
    "https://api.ergast.com/f1",
]
ACTIVE_BASE_URL = BASE_URLS[0]
SEED_START_YEAR = 1981
SEED_END_YEAR = 2026

# Driver IDs that Jolpica normalizes differently from what the frontend expects
DRIVER_ID_MAP = {
    "max_verstappen": "verstappen",
    "arvid_lindblad": "lindblad",
}

# Official 2026 standings (includes sprint + fastest lap points not in Jolpica)
OFFICIAL_DRIVER_STANDINGS_2026 = [
    (1, "antonelli", 242), (2, "russell", 183), (3, "hamilton", 183),
    (4, "norris", 159), (5, "leclerc", 155), (6, "verstappen", 112),
    (7, "piastri", 104), (8, "hadjar", 68), (9, "lawson", 49),
    (10, "gasly", 44), (11, "lindblad", 23), (12, "colapinto", 19),
    (13, "bearman", 18), (14, "bortoleto", 10), (15, "hulkenberg", 6),
    (16, "sainz", 6), (17, "albon", 5), (18, "ocon", 3),
    (19, "alonso", 3), (20, "tsunoda", 0), (21, "stroll", 0),
    (22, "bottas", 0), (23, "perez", 0),
]

OFFICIAL_CONSTRUCTOR_STANDINGS_2026 = [
    (1, "mercedes", 425), (2, "ferrari", 338), (3, "mclaren", 263),
    (4, "red_bull", 186), (5, "rb", 66), (6, "alpine", 63),
    (7, "haas", 21), (8, "audi", 16), (9, "williams", 11),
    (10, "aston_martin", 3), (11, "cadillac", 0),
]

# Sprint rounds by year (approximate — covers 2021+)
SPRINT_ROUNDS = {
    2021: {3, 10, 14},
    2022: {3, 10, 17, 20},
    2023: {5, 10, 16, 19},
    2024: {4, 10, 17, 20},
    2025: {3, 10, 17, 20},
    2026: {3, 10, 17, 20},
}

# Country code map for circuits
COUNTRY_CODES = {
    "australia": "au", "china": "cn", "japan": "jp", "bahrain": "bh",
    "saudi arabia": "sa", "usa": "us", "italy": "it", "monaco": "mc",
    "canada": "ca", "spain": "es", "austria": "at", "uk": "uk",
    "great britain": "uk", "hungary": "hu", "belgium": "be",
    "netherlands": "nl", "azerbaijan": "az", "singapore": "sg",
    "mexico": "mx", "brazil": "br", "qatar": "qa", "uae": "ae",
    "france": "fr", "portugal": "pt", "turkey": "tr", "malaysia": "my",
    "south africa": "za", "argentina": "ar", "sweden": "se",
    "switzerland": "ch", "germany": "de", "india": "in",
    "south korea": "kr", "russia": "ru", "spain": "es",
    "80th anniversary grand prix": "uk",
}

# Team colors for known constructors (used across all years)
TEAM_COLORS = {
    "mercedes": {"color": "#75F1D3"},
    "ferrari": {"color": "#D52E37"},
    "mclaren": {"color": "#FF8000"},
    "red_bull": {"color": "#4570C0"},
    "aston_martin": {"color": "#229971"},
    "alpine": {"color": "#0093CC", "secondaryColor": "#FF87BC"},
    "audi": {"color": "#BB0A30"},
    "rb": {"color": "#6692FF"},
    "haas": {"color": "#B6BABD"},
    "williams": {"color": "#64C4FF"},
    "cadillac": {"color": "#1E1E1E", "secondaryColor": "#E0E0E0"},
    "renault": {"color": "#FFF500"},
    "toro_rosso": {"color": "#469DFF"},
    "force_india": {"color": "#F07500"},
    "racing_point": {"color": "#F07500"},
    "alfa": {"color": "#C92D4B"},
    "alfa_romeo": {"color": "#C92D4B"},
    "sauber": {"color": "#9E1933"},
    "toyota": {"color": "#D9202A"},
    "honda": {"color": "#CC0000"},
    "jordan": {"color": "#00492B"},
    "minardi": {"color": "#2F2F2F"},
    "bar": {"color": "#3073BE"},
    "jaguar": {"color": "#1C4C7C"},
    "prost": {"color": "#0055A4"},
    "benetton": {"color": "#00604A"},
    "stewart": {"color": "#003366"},
    "tyrrell": {"color": "#1B3D73"},
    "shadow": {"color": "#333333"},
    "enso": {"color": "#003087"},
    "ats": {"color": "#808080"},
    "fittipaldi": {"color": "#1B6F44"},
    "wolf": {"color": "#FF0000"},
    "brabham": {"color": "#003DA5"},
    "lotus": {"color": "#FFD700"},
    "lotus_f1": {"color": "#FFD700"},
    " McLaren": {"color": "#FF8000"},
}


# ── API helpers ──────────────────────────────────────────────────────────

def api_get(relative: str, retries: int = 3) -> Optional[dict]:
    """Fetch JSON from Jolpica with exponential backoff retries."""
    # Try each base URL (Jolpica first, Ergast fallback)
    for base in BASE_URLS:
        full_url = f"{base}/{relative}"
        for attempt in range(retries):
            try:
                req = urllib.request.Request(full_url, headers={"User-Agent": "F1-Predictor/1.0"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = min(30, 3 * (2 ** attempt))
                    print(f"    Rate limited on {base.split('//')[1][:20]}, waiting {wait}s...")
                    time.sleep(wait)
                else:
                    break  # Try next base URL
            except Exception:
                break  # Try next base URL
    # All failed
    print(f"  [WARN] All APIs failed for: {relative}")
    return None


def normalize_driver_id(raw_id: str) -> str:
    return DRIVER_ID_MAP.get(raw_id, raw_id)


# ── Per-season seeder ────────────────────────────────────────────────────

def seed_season(year: int, force: bool = False):
    """Seed one F1 season into SQLite."""
    if is_seeded(year) and not force:
        print(f"  [OK] {year} already seeded, skipping")
        return

    print(f"  >> Fetching {year} season data...")

    # 1. Get schedule (race list)
    sched_data = api_get(f"{year}.json?limit=100")
    if not sched_data:
        print(f"  [FAIL] Failed to fetch schedule for {year}")
        return

    races = sched_data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
    if not races:
        print(f"  [FAIL] No races found for {year}")
        return

    max_rounds = len(races)

    # 2. Fetch results per-round (reliable, handles any season length)
    all_results = {}
    constructor_map = {}  # constructor_id → {name, nationality}

    for rnd in range(1, max_rounds + 1):
        rnd_data = api_get(f"{year}/{rnd}/results.json")
        if not rnd_data:
            continue
        rnd_races = rnd_data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
        if not rnd_races or not rnd_races[0].get("Results"):
            continue
        for res in rnd_races[0].get("Results", []):
            drv = res.get("Driver", {})
            con = res.get("Constructor", {})
            raw_did = drv.get("driverId", "")
            did = normalize_driver_id(raw_did)
            cid = con.get("constructorId", "")
            pos_raw = res.get("position")
            try:
                pos = int(pos_raw) if pos_raw else None
            except (ValueError, TypeError):
                pos = None
            if pos is None:
                continue
            fastest = 1 if res.get("FastestLap") else 0
            all_results.setdefault(rnd, []).append({
                "driver_id": did,
                "raw_driver_id": raw_did,
                "team_id": cid,
                "position": pos,
                "fastest_lap": fastest,
                "given_name": drv.get("givenName", ""),
                "family_name": drv.get("familyName", ""),
                "code": drv.get("code", raw_did[:3].upper()),
                "nationality": drv.get("nationality", ""),
            })
            if cid and cid not in constructor_map:
                constructor_map[cid] = {
                    "name": con.get("name", cid),
                    "nationality": con.get("nationality", ""),
                }
        time.sleep(1)  # Rate limit

    # 3. Write to database
    print(f"  >> Writing {year} to database...")

    insert_season(year, max_rounds)

    # Races
    sprint_rounds = SPRINT_ROUNDS.get(year, set())
    for race in races:
        rnd = int(race.get("round", 0))
        circ = race.get("Circuit", {})
        loc = circ.get("Location", {})
        country = loc.get("country", "")
        cc = COUNTRY_CODES.get(country.lower(), country.lower()[:2])
        race_id = f"{year}_r{rnd}"
        is_sprint = rnd in sprint_rounds
        completed = rnd in all_results

        insert_race(
            race_id, year, rnd, race.get("raceName", ""),
            circ.get("circuitId", f"r{rnd}"), country, cc,
            race.get("date", ""), is_sprint, completed,
        )

    # Drivers (collect unique drivers from all rounds)
    driver_seen = {}
    for rnd, results in all_results.items():
        for r in results:
            did = r["driver_id"]
            if did not in driver_seen:
                driver_seen[did] = r

    for did, info in driver_seen.items():
        insert_driver(
            did, year, info["code"], info["given_name"],
            info["family_name"], info["nationality"], info["team_id"],
        )

    # Constructors
    for cid, info in constructor_map.items():
        colors = TEAM_COLORS.get(cid, {"color": "#888888"})
        insert_constructor(
            cid, year, info["name"], info["nationality"],
            colors["color"], colors.get("secondaryColor"),
        )

    # Results
    for rnd, results in all_results.items():
        for r in results:
            insert_result(year, rnd, r["driver_id"], r["team_id"],
                         r["position"], bool(r["fastest_lap"]))

    # Standings
    _seed_standings(year, all_results, constructor_map)

    total_results = sum(len(v) for v in all_results.values())
    print(f"  [OK] {year}: {len(races)} races, {len(driver_seen)} drivers, "
          f"{len(constructor_map)} teams, {total_results} results")


def _seed_standings(year: int, all_results: dict, constructor_map: dict):
    """Fetch championship standings from Jolpica's standings endpoint.
    This gives accurate final standings including sprint + fastest lap points."""
    # For 2026, use hardcoded official standings
    if year == 2026:
        for pos, did, pts in OFFICIAL_DRIVER_STANDINGS_2026:
            insert_standing(year, did, "driver", pos, pts)
        for pos, tid, pts in OFFICIAL_CONSTRUCTOR_STANDINGS_2026:
            insert_standing(year, tid, "constructor", pos, pts)
        return

    # Fetch final driver standings from Jolpica
    driver_data = api_get(f"{year}/driverStandings.json?limit=100")
    if driver_data:
        standings = driver_data.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [])
        if standings:
            for s in standings[0].get("DriverStandings", []):
                did = normalize_driver_id(s.get("Driver", {}).get("driverId", ""))
                pos = int(s.get("position", 0))
                pts = int(s.get("points", 0))
                if did and pos > 0:
                    insert_standing(year, did, "driver", pos, pts)

    # Fetch final constructor standings from Jolpica
    constructor_data = api_get(f"{year}/constructorStandings.json?limit=100")
    if constructor_data:
        standings = constructor_data.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [])
        if standings:
            for s in standings[0].get("ConstructorStandings", []):
                tid = s.get("Constructor", {}).get("constructorId", "")
                pos = int(s.get("position", 0))
                pts = int(s.get("points", 0))
                if tid and pos > 0:
                    insert_standing(year, tid, "constructor", pos, pts)

    time.sleep(1)  # Rate limit after standings fetch


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Seed F1 data into SQLite")
    parser.add_argument("--year", type=int, help="Seed only this year")
    parser.add_argument("--start", type=int, default=SEED_START_YEAR,
                        help=f"Start year (default: {SEED_START_YEAR})")
    parser.add_argument("--end", type=int, default=SEED_END_YEAR,
                        help=f"End year (default: {SEED_END_YEAR})")
    parser.add_argument("--reseed", action="store_true",
                        help="Drop all data and re-seed")
    args = parser.parse_args()

    print("F1 Data Seeder")
    print(f"   Database: {get_db_path()}")

    if args.reseed:
        from database import DB_PATH
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
            print("   Deleted old database")

    init_db()
    print("   Database initialized\n")

    if args.year:
        years = [args.year]
    else:
        years = list(range(args.start, args.end + 1))

    total_start = time.time()

    for i, year in enumerate(years):
        print(f"[{i+1}/{len(years)}] Seeding {year}...")
        try:
            seed_season(year)
            # Cooldown between seasons to avoid rate limiting
            if i < len(years) - 1:
                time.sleep(3)
        except Exception as e:
            print(f"  [FAIL] Error seeding {year}: {e}")

    elapsed = time.time() - total_start
    print(f"\nDone! Seeded {len(years)} seasons in {elapsed:.1f}s")
    print(f"   Database size: {os.path.getsize(get_db_path()) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
