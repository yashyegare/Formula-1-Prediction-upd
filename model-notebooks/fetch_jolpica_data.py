"""
fetch_jolpica_data.py

Rebuilds the model-notebooks/datasets/*.csv files from the Jolpica-F1 API
(the community-run, drop-in successor to the now-shutdown Ergast API:
https://github.com/jolpica/jolpica-f1).

Output CSVs match the original Ergast/Kaggle schema used by F1.ipynb and
prediction_iter1.ipynb, so you can point the notebooks at this new
`datasets/` folder with no other changes.

Usage:
    pip install requests pandas
    python fetch_jolpica_data.py --start-year 2018 --end-year 2026 --out ./datasets

Notes:
- Jolpica's unauthenticated rate limit is ~4 req/burst, 200 req/hour.
  This script sleeps between calls and caches every raw response to
  `--cache-dir` so re-runs (or a run that gets rate-limited) don't
  re-fetch anything already on disk.
- 2026 is the current season: only races that have actually happened
  will have results/qualifying data. Future rounds are skipped
  automatically (empty results = skipped, logged at the end).
"""
import argparse
import json
import os
import time
from pathlib import Path

import requests

BASE = "https://api.jolpi.ca/ergast/f1"
SLEEP = 0.35  # keep well under the 4 req/sec burst limit


def dump_debug(cache_dir, label, obj):
    """Write an unexpected API shape to disk so it can be inspected, instead of crashing the run."""
    debug_dir = Path(cache_dir) / "_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    fname = debug_dir / f"{label}_{int(time.time()*1000)}.json"
    fname.write_text(json.dumps(obj, indent=2))


def get(session, cache_dir, path, params=None):
    """GET with on-disk caching so re-runs are cheap and rate-limit-safe."""
    cache_key = path.replace("/", "_") + (("_" + "_".join(f"{k}{v}" for k, v in (params or {}).items())) if params else "")
    cache_file = Path(cache_dir) / f"{cache_key}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    url = f"{BASE}/{path}"
    for attempt in range(5):
        resp = session.get(url, params=params, timeout=15)
        if resp.status_code == 429:
            wait = 5 * (attempt + 1)
            print(f"  rate limited, waiting {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        data = resp.json()
        cache_file.write_text(json.dumps(data))
        time.sleep(SLEEP)
        return data
    raise RuntimeError(f"Failed to fetch {url} after retries")


def paginate(session, cache_dir, path, limit=100):
    """Walk MRData pagination and return the concatenated list under the given key."""
    offset = 0
    out = []
    while True:
        data = get(session, cache_dir, path, params={"limit": limit, "offset": offset})
        mr = data["MRData"]
        total = int(mr["total"])
        table_key = [k for k in mr if k.endswith("Table")][0]
        list_key = [k for k in mr[table_key] if isinstance(mr[table_key][k], list)][0]
        chunk = mr[table_key][list_key]
        out.extend(chunk)
        offset += limit
        if offset >= total or not chunk:
            break
    return out


def fetch_season_races(session, cache_dir, year):
    data = get(session, cache_dir, f"{year}.json", params={"limit": 100})
    return data["MRData"]["RaceTable"]["Races"]


def fetch_round_results(session, cache_dir, year, rnd):
    data = get(session, cache_dir, f"{year}/{rnd}/results.json", params={"limit": 100})
    races = data["MRData"]["RaceTable"]["Races"]
    return races[0]["Results"] if races else []


def fetch_round_qualifying(session, cache_dir, year, rnd):
    data = get(session, cache_dir, f"{year}/{rnd}/qualifying.json", params={"limit": 100})
    races = data["MRData"]["RaceTable"]["Races"]
    return races[0]["QualifyingResults"] if races else []


def fetch_round_driver_standings(session, cache_dir, year, rnd):
    data = get(session, cache_dir, f"{year}/{rnd}/driverStandings.json", params={"limit": 100})
    lists = data["MRData"]["StandingsTable"]["StandingsLists"]
    return lists[0]["DriverStandings"] if lists else []


def fetch_round_constructor_standings(session, cache_dir, year, rnd):
    data = get(session, cache_dir, f"{year}/{rnd}/constructorStandings.json", params={"limit": 100})
    lists = data["MRData"]["StandingsTable"]["StandingsLists"]
    return lists[0]["ConstructorStandings"] if lists else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=2018)
    ap.add_argument("--end-year", type=int, default=2026)
    ap.add_argument("--out", default="./datasets")
    ap.add_argument("--cache-dir", default="./.jolpica_cache")
    args = ap.parse_args()

    Path(args.out).mkdir(parents=True, exist_ok=True)
    Path(args.cache_dir).mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "f1-predictor-refresh/1.0"})

    races_rows, results_rows, quali_rows = [], [], []
    driver_standings_rows, constructor_standings_rows = [], []
    circuits_seen, drivers_seen, constructors_seen = {}, {}, {}
    skipped_future_rounds = []

    for year in range(args.start_year, args.end_year + 1):
        print(f"== {year} ==")
        races = fetch_season_races(session, args.cache_dir, year)
        for race in races:
            rnd = int(race["round"])
            circ = race["Circuit"]
            circuits_seen[circ["circuitId"]] = {
                "circuitId": circ["circuitId"],
                "name": circ["circuitName"],
                "location": circ["Location"]["locality"],
                "country": circ["Location"]["country"],
                "lat": circ["Location"]["lat"],
                "lng": circ["Location"]["long"],
            }
            races_rows.append({
                "year": year,
                "round": rnd,
                "circuitId": circ["circuitId"],
                "name": race["raceName"],
                "date": race["date"],
                "time": race.get("time", ""),
            })

            print(f"  round {rnd}: {race['raceName']}", end=" ")
            results = fetch_round_results(session, args.cache_dir, year, rnd)
            if not results:
                print("- no results yet (future race), skipping")
                skipped_future_rounds.append((year, rnd, race["raceName"]))
                continue
            print(f"- {len(results)} results")

            for r in results:
                if "Driver" not in r or "Constructor" not in r:
                    dump_debug(args.cache_dir, "results_bad_row", r)
                    print("    ! skipping malformed result row (see debug dump)")
                    continue
                drv, con = r["Driver"], r["Constructor"]
                drivers_seen[drv["driverId"]] = {
                    "driverId": drv["driverId"],
                    "driverRef": drv["driverId"],
                    "code": drv.get("code", ""),
                    "forename": drv["givenName"],
                    "surname": drv["familyName"],
                    "dob": drv.get("dateOfBirth", ""),
                    "nationality": drv.get("nationality", ""),
                }
                constructors_seen[con["constructorId"]] = {
                    "constructorId": con["constructorId"],
                    "name": con["name"],
                    "nationality": con.get("nationality", ""),
                }
                results_rows.append({
                    "year": year,
                    "round": rnd,
                    "raceName": race["raceName"],
                    "driverId": drv["driverId"],
                    "driverName": f"{drv['givenName']} {drv['familyName']}",
                    "constructorId": con["constructorId"],
                    "constructorName": con["name"],
                    "grid": r.get("grid"),
                    "position": r.get("position"),
                    "positionOrder": r.get("positionText"),
                    "points": r.get("points"),
                    "laps": r.get("laps"),
                    "status": r.get("status"),
                })

            quali = fetch_round_qualifying(session, args.cache_dir, year, rnd)
            for q in quali:
                if "Driver" not in q or "Constructor" not in q:
                    dump_debug(args.cache_dir, "qualifying_bad_row", q)
                    print("    ! skipping malformed qualifying row (see debug dump)")
                    continue
                drv, con = q["Driver"], q["Constructor"]
                quali_rows.append({
                    "year": year,
                    "round": rnd,
                    "driverId": drv["driverId"],
                    "constructorId": con["constructorId"],
                    "position": q.get("position"),
                    "Q1": q.get("Q1", ""),
                    "Q2": q.get("Q2", ""),
                    "Q3": q.get("Q3", ""),
                })

            for ds in fetch_round_driver_standings(session, args.cache_dir, year, rnd):
                if "Driver" not in ds:
                    dump_debug(args.cache_dir, "driver_standings_bad_row", ds)
                    print(f"    ! skipping malformed driver standings row (see debug dump)")
                    continue
                driver_standings_rows.append({
                    "year": year,
                    "round": rnd,
                    "driverId": ds["Driver"]["driverId"],
                    "points": ds.get("points"),
                    "wins": ds.get("wins"),
                    "position": ds.get("position") or ds.get("positionText"),
                })

            for cs in fetch_round_constructor_standings(session, args.cache_dir, year, rnd):
                if "Constructor" not in cs:
                    dump_debug(args.cache_dir, "constructor_standings_bad_row", cs)
                    print(f"    ! skipping malformed constructor standings row (see debug dump)")
                    continue
                constructor_standings_rows.append({
                    "year": year,
                    "round": rnd,
                    "constructorId": cs["Constructor"]["constructorId"],
                    "points": cs.get("points"),
                    "wins": cs.get("wins"),
                    "position": cs.get("position") or cs.get("positionText"),
                })

    import pandas as pd
    pd.DataFrame(races_rows).to_csv(f"{args.out}/races.csv", index=False)
    pd.DataFrame(results_rows).to_csv(f"{args.out}/results.csv", index=False)
    pd.DataFrame(quali_rows).to_csv(f"{args.out}/qualifying.csv", index=False)
    pd.DataFrame(driver_standings_rows).to_csv(f"{args.out}/driver_standings.csv", index=False)
    pd.DataFrame(constructor_standings_rows).to_csv(f"{args.out}/constructor_standings.csv", index=False)
    pd.DataFrame(list(circuits_seen.values())).to_csv(f"{args.out}/circuits.csv", index=False)
    pd.DataFrame(list(drivers_seen.values())).to_csv(f"{args.out}/drivers.csv", index=False)
    pd.DataFrame(list(constructors_seen.values())).to_csv(f"{args.out}/constructors.csv", index=False)

    print("\nDone.")
    print(f"  races: {len(races_rows)}, results: {len(results_rows)}, qualifying: {len(quali_rows)}")
    print(f"  drivers: {len(drivers_seen)}, constructors: {len(constructors_seen)}, circuits: {len(circuits_seen)}")
    if skipped_future_rounds:
        print(f"  skipped {len(skipped_future_rounds)} future/unplayed rounds:")
        for y, r, n in skipped_future_rounds:
            print(f"    {y} round {r}: {n}")


if __name__ == "__main__":
    main()