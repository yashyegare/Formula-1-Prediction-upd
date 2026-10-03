"""
sync_season_db.py — backfill the SERVED season data with the latest race
results, without a re-seed.

Why this exists: /api/init answers from the seeded database whenever the
season has rows (get_season_init_data); the live-Jolpica fallback only
runs for seasons that were never seeded. A race finished on Sunday is
therefore invisible to the Season Simulator until someone re-runs
seed_data.py — and with it every user's post-race score and the
leaderboard.

One run per season:
  1. find open rounds (races.completed = 0), ascending;
  2. fetch {year}/{round}/results.json — the first round Jolpica has no
     results for has not been raced yet, so stop there (never guess by
     calendar date);
  3. write the results, upsert any new drivers/constructors, mark the
     round completed;
  4. if anything landed, replace the season standings with Jolpica's
     current classification — roster entries Jolpica does not list stay
     at 0 points, ordered after the classified ones (deterministic by
     id, so two runs with the same payload produce the same table);
  5. re-score every prediction of the season and refresh the leaderboard
     rows (the same path /api/me/prediction POST uses), so users'
     numbers move with the new results. rescore=False opts out.

Usage:
    python sync_season_db.py --year 2026
    python sync_season_db.py --year 2026 --no-rescore

The nightly workflow (refresh.yml) runs this on the committed SQLite and
calls POST /api/admin/sync-season on the deployed service, which runs
the same code against production Postgres — the committed SQLite file
alone never reaches a running DATABASE_URL install.
"""
import argparse
import json

from database import (
    _execute, _fetchall, _is_pg, get_all_predictions, get_connection,
    is_seeded, update_leaderboard,
)
from seed_data import TEAM_COLORS, api_get, normalize_driver_id


def _ph() -> str:
    return "%s" if _is_pg() else "?"


def _open_rounds(conn, year: int) -> list[int]:
    rows = _fetchall(
        conn,
        f"SELECT round_num FROM races WHERE year = {_ph()} "
        "AND completed = 0 ORDER BY round_num",
        (year,))
    return [int(r["round_num"]) for r in rows]


def _fetch_round_results(year: int, rnd: int) -> list[dict] | None:
    """One round's classified finishers from Jolpica, or None when the
    round has not been raced (no Results block)."""
    data = api_get(f"{year}/{rnd}/results.json")
    races = ((data or {}).get("MRData", {})
             .get("RaceTable", {}).get("Races", []))
    if not races or not races[0].get("Results"):
        return None
    out = []
    for res in races[0]["Results"]:
        drv, con = res.get("Driver", {}), res.get("Constructor", {})
        did = normalize_driver_id(drv.get("driverId", ""))
        cid = con.get("constructorId", "")
        try:
            pos = int(res.get("position"))
        except (TypeError, ValueError):
            continue
        if not did or pos <= 0:
            continue
        out.append({
            "driver_id": did, "team_id": cid, "position": pos,
            "fastest_lap": bool(res.get("FastestLap")),
            "code": drv.get("code", did[:3].upper()),
            "given_name": drv.get("givenName", ""),
            "family_name": drv.get("familyName", ""),
            "nationality": drv.get("nationality", ""),
            "team_name": con.get("name", cid),
            "team_nationality": con.get("nationality", ""),
        })
    return out


def _ingest_round(conn, year: int, rnd: int, results: list[dict]) -> None:
    for r in results:
        if _is_pg():
            _execute(conn,
                     "INSERT INTO drivers (id, year, code, given_name, "
                     "family_name, nationality, team_id) "
                     "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                     "ON CONFLICT (id, year) DO UPDATE SET "
                     "code = EXCLUDED.code, team_id = EXCLUDED.team_id",
                     (r["driver_id"], year, r["code"], r["given_name"],
                      r["family_name"], r["nationality"], r["team_id"]))
            _execute(conn,
                     "INSERT INTO results (year, round_num, driver_id, "
                     "team_id, position, fastest_lap) "
                     "VALUES (%s, %s, %s, %s, %s, %s) "
                     "ON CONFLICT (year, round_num, driver_id) DO UPDATE SET "
                     "team_id = EXCLUDED.team_id, "
                     "position = EXCLUDED.position, "
                     "fastest_lap = EXCLUDED.fastest_lap",
                     (year, rnd, r["driver_id"], r["team_id"],
                      r["position"], int(r["fastest_lap"])))
            if r["team_id"]:
                colors = TEAM_COLORS.get(r["team_id"], {"color": "#888888"})
                _execute(conn,
                         "INSERT INTO constructors (id, year, name, "
                         "nationality, color, secondary_color) "
                         "VALUES (%s, %s, %s, %s, %s, %s) "
                         "ON CONFLICT (id, year) DO NOTHING",
                         (r["team_id"], year, r["team_name"],
                          r["team_nationality"], colors["color"],
                          colors.get("secondaryColor")))
        else:
            _execute(conn,
                     "INSERT OR REPLACE INTO drivers (id, year, code, "
                     "given_name, family_name, nationality, team_id) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (r["driver_id"], year, r["code"], r["given_name"],
                      r["family_name"], r["nationality"], r["team_id"]))
            _execute(conn,
                     "INSERT OR REPLACE INTO results (year, round_num, "
                     "driver_id, team_id, position, fastest_lap) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (year, rnd, r["driver_id"], r["team_id"],
                      r["position"], int(r["fastest_lap"])))
            if r["team_id"]:
                colors = TEAM_COLORS.get(r["team_id"], {"color": "#888888"})
                _execute(conn,
                         "INSERT OR REPLACE INTO constructors (id, year, "
                         "name, nationality, color, secondary_color) "
                         "VALUES (?, ?, ?, ?, ?, ?)",
                         (r["team_id"], year, r["team_name"],
                          r["team_nationality"], colors["color"],
                          colors.get("secondaryColor")))
    _execute(conn,
             f"UPDATE races SET completed = 1 WHERE year = {_ph()} "
             f"AND round_num = {_ph()}", (year, rnd))


def _standings_entries(year: int, kind: str,
                       key: str) -> list[tuple[str, int, float]]:
    """Jolpica standings for the season, as of its last raced round."""
    data = api_get(f"{year}/{kind}.json?limit=100")
    lists = ((data or {}).get("MRData", {})
             .get("StandingsTable", {}).get("StandingsLists", []))
    if not lists:
        return []
    out = []
    for s in lists[0].get(key, []):
        entity = s.get("Driver") or s.get("Constructor") or {}
        eid = entity.get("driverId") or entity.get("constructorId") or ""
        eid = normalize_driver_id(eid)
        try:
            pos = int(s.get("position"))
        except (TypeError, ValueError):
            continue
        if not eid or pos <= 0:
            continue
        try:
            pts = float(s.get("points", 0))
        except (TypeError, ValueError):
            pts = 0.0
        out.append((eid, pos, pts))
    return out


def _replace_standings(conn, year: int, entity_type: str,
                       entries: list[tuple[str, int, float]],
                       roster_table: str) -> None:
    for eid, pos, pts in entries:
        _execute(conn,
                 "INSERT INTO standings (year, entity_id, entity_type, "
                 f"position, points) VALUES ({_ph()}, {_ph()}, {_ph()}, "
                 f"{_ph()}, {_ph()})",
                 (year, eid, entity_type, pos, pts))
    # roster members Jolpica does not classify yet sit at 0 points, after
    # the last classified position — ordered by id so reruns match
    classified = {e[0] for e in entries}
    rows = _fetchall(conn,
                     f"SELECT id FROM {roster_table} WHERE year = {_ph()} "
                     "ORDER BY id", (year,))
    pos = max((e[1] for e in entries), default=0)
    for r in rows:
        if r["id"] in classified:
            continue
        pos += 1
        _execute(conn,
                 "INSERT INTO standings (year, entity_id, entity_type, "
                 f"position, points) VALUES ({_ph()}, {_ph()}, {_ph()}, "
                 f"{_ph()}, 0)",
                 (year, r["id"], entity_type, pos))


def _refresh_standings(conn, year: int) -> bool:
    drivers = _standings_entries(year, "driverStandings",
                                 "DriverStandings")
    constructors = _standings_entries(year, "constructorStandings",
                                      "ConstructorStandings")
    if not drivers and not constructors:
        return False  # fetch failed — never wipe live standings on that
    _execute(conn, f"DELETE FROM standings WHERE year = {_ph()}", (year,))
    _replace_standings(conn, year, "driver", drivers, "drivers")
    _replace_standings(conn, year, "constructor", constructors,
                       "constructors")
    return True


def _rescore_season(year: int) -> int:
    """Re-score every stored prediction of the season against results —
    identical math and write path to the /api/me/prediction POST."""
    from predictions_api import _score_prediction
    n = 0
    for pred in get_all_predictions(year):
        try:
            grids = json.loads(pred["grids_json"]) if pred["grids_json"] else {}
        except (TypeError, ValueError):
            continue
        scoring = _score_prediction(grids, year)
        update_leaderboard(
            pred["user_id"], year,
            scoring["accuracyScore"], scoring["racesScored"],
            scoring["exactMatches"], scoring["totalPositions"])
        n += 1
    return n


def sync_year(year: int, rescore: bool = True) -> dict:
    if not is_seeded(year):
        raise ValueError(
            f"season {year} is not seeded — run seed_data.py --year {year}")
    new_rounds: list[int] = []
    with get_connection() as conn:
        for rnd in _open_rounds(conn, year):
            results = _fetch_round_results(year, rnd)
            if results is None:
                break
            _ingest_round(conn, year, rnd, results)
            new_rounds.append(rnd)
        refreshed = _refresh_standings(conn, year) if new_rounds else False
    scored = _rescore_season(year) if (new_rounds and rescore) else 0
    return {
        "year": year,
        "new_rounds": new_rounds,
        "standings_refreshed": refreshed,
        "rescored_predictions": scored,
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ingest finished rounds into the served season data")
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--no-rescore", action="store_true",
                    help="skip leaderboard re-scoring of user predictions")
    args = ap.parse_args()
    summary = sync_year(args.year, rescore=not args.no_rescore)
    print(f"sync {args.year}: new rounds {summary['new_rounds'] or '—'}, "
          f"standings refreshed: {summary['standings_refreshed']}, "
          f"predictions rescored: {summary['rescored_predictions']}")


if __name__ == "__main__":
    main()
