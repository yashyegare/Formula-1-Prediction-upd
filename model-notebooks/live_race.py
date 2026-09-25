"""
live_race.py — the live race-day layer.

Fetches the CURRENT running order from the OpenF1 public feed (the only
free near-real-time F1 position source) and re-simulates the remaining
race with the lap_curves replay machinery: for every driver still
running, P(podium)/P(points)/P(out) and expected position CONDITIONED on
where they are right now; retired drivers are out.

This is the plan's live-intelligence layer in its honest v1 form: a
snapshot refreshed on a cadence (the live workflow / --refresh), not a
streaming service. The artifact records `fetched_at` and the session
identity; the API marks it stale when old — never silently serving
yesterday's race as if it were live.

Mapping: OpenF1 identifies drivers by racing NUMBER; the platform uses
Ergast-era driverIds. The stable join key is the 3-letter code (HAM,
RUS, ...) — dim_driver.code on our side, `name_acronym` on OpenF1's.

Truth: drivers absent from the position stream are OUT (OpenF1's stream
only tracks cars currently running; a driver who parked disappears and
never returns mid-race). Total laps for the remaining-fraction fit come
from the circuit's historical race length in the canonical DB.

Determinism: the SIMULATION is seeded and reproducible (same seed +
same snapshot => same distributions); the FETCH obviously is not —
the snapshot's `fetched_at` makes that explicit.

Usage:
    python live_race.py --db datasets/f1_canonical.db \
        --out datasets/live_state.json --sims 400
"""
import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

import lap_curves as lc
import race_simulator as rs

OPENF1 = "https://api.openf1.org/v1"
# A snapshot older than this is flagged stale (the API says so loudly).
STALE_AFTER_MIN = 45
# Race-day length varies by circuit; use the historical max laps for the
# current season's round at that circuit (the calendar rarely changes).
DEFAULT_LAPS = 60

# OpenF1 locks GLOBAL access (even past sessions) behind authentication
# while a live F1 session is running — precisely when this module runs.
# With OPENF1_USERNAME/OPENF1_PASSWORD set, a Bearer token is obtained
# from the OAuth2 token endpoint (valid 3600s) and attached to every
# call; without them the anonymous feed is used (fine off-session).
_TOKEN: dict | None = None


def _openf1_token() -> str | None:
    """Bearer token for the paid live tier; None when unconfigured."""
    global _TOKEN
    user = os.environ.get("OPENF1_USERNAME", "").strip()
    pwd = os.environ.get("OPENF1_PASSWORD", "").strip()
    if not user or not pwd:
        return None
    if _TOKEN is not None and _TOKEN["expires"] > time.time() + 60:
        return _TOKEN["token"]
    try:
        r = requests.post("https://api.openf1.org/token",
                          data={"username": user, "password": pwd},
                          timeout=30)
        r.raise_for_status()
        tok = r.json()["access_token"]
    except Exception:
        return None
    _TOKEN = {"token": tok, "expires": time.time() + 3600}
    return tok


# ── OpenF1 fetch ─────────────────────────────────────────────────────────

def _get(path: str, **params) -> list:
    headers = {}
    tok = _openf1_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    r = requests.get(f"{OPENF1}/{path}", params=params, timeout=30,
                     headers=headers)
    r.raise_for_status()
    return r.json()


def fetch_live_session() -> dict:
    """The most recent session on the feed (any type) + its drivers +
    position stream. Raises RuntimeError when the feed is unreachable or
    empty — the caller turns that into an explicit artifact error."""
    sessions = _get("sessions", session_key="latest")
    if not sessions:
        raise RuntimeError("OpenF1 returned no sessions")
    s = sessions[0]
    sk = s["session_key"]
    drivers = _get("drivers", session_key=sk)
    positions = _get("position", session_key=sk)
    return {"session": s, "drivers": drivers, "positions": positions}


def latest_running_order(positions: list) -> list[dict]:
    """Collapse the position stream to one row per driver_number: their
    most recent (date, position). Drivers currently running appear;
    retired ones are absent — that absence IS the retirement signal."""
    latest: dict[int, tuple[str, int]] = {}
    for p in positions:
        n = p["driver_number"]
        cur = latest.get(n)
        if cur is None or p["date"] > cur[0]:
            latest[n] = (p["date"], p["position"])
    return [{"driver_number": n, "date": d, "position": pos}
            for n, (d, pos) in sorted(latest.items(), key=lambda kv: kv[1])]


# ── mapping to platform identity ─────────────────────────────────────────

def _code_map(db_path: str) -> dict[str, str]:
    """{3-letter code: driverId} from dim_driver."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT code, driverId FROM dim_driver WHERE code != ''").fetchall()
    finally:
        con.close()
    return {code.upper(): did for code, did in rows}


def _historical_laps(db_path: str, year: int, location: str) -> int:
    """Race distance (laps) for this circuit from the canonical DB:
    the max laps ever completed at circuits matching the location, in
    the current season's calendar when possible."""
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("""
            SELECT MAX(f.laps) FROM fact_race_entry f
            JOIN fact_race r ON r.year = f.year AND r.round = f.round
            JOIN dim_circuit c ON c.circuitId = r.circuitId
            WHERE f.year = ?
              AND (c.name LIKE ? OR c.location LIKE ?)
        """, (year, f"%{location}%", f"%{location}%")).fetchone()
    finally:
        con.close()
    return int(row[0]) if row and row[0] else DEFAULT_LAPS


# ── snapshot builder ─────────────────────────────────────────────────────

def build_live_snapshot(db_path: str, n_sims: int, seed: int) -> dict:
    """Fetch live state and simulate the remainder of the current race.

    The mechanism is the lap-curves replay at the CURRENT remaining
    fraction: remaining-swing/fail parameters fitted from the canonical
    DB's history (strictly prior seasons of the current one), runners
    re-simulated from their live positions, retired drivers pinned at
    P(out)=1."""
    live = fetch_live_session()
    session, drivers, positions = (live["session"], live["drivers"],
                                   live["positions"])
    order = latest_running_order(positions)
    if not order:
        raise RuntimeError("OpenF1 position stream is empty")

    codes = _code_map(db_path)
    acronym = {d["driver_number"]: d.get("name_acronym", "").upper()
               for d in drivers}

    # runners with platform identity; unmapped numbers are noted, never
    # silently dropped (a new driver's code must surface as a gap, not
    # vanish from the picture)
    runners, unmapped = [], []
    for o in order:
        did = codes.get(acronym.get(o["driver_number"], ""))
        if did is None:
            unmapped.append({"driver_number": o["driver_number"],
                             "name_acronym": acronym.get(o["driver_number"])})
        else:
            runners.append({"driverId": did, "position": o["position"]})

    year = int(session.get("year", datetime.now(timezone.utc).year))
    # which season's mechanism: the CURRENT season's fits (the live race
    # belongs to the ongoing season; fits use strictly prior seasons —
    # identical to the artifact builders' walk-forward discipline)
    con = sqlite3.connect(db_path)
    try:
        latest_season = con.execute(
            "SELECT MAX(year) FROM fact_race_entry").fetchone()[0]
    finally:
        con.close()
    mech_year = max(year, int(latest_season))

    laps = lc._load_laps(db_path)
    entries = lc._load_entries_full(db_path)
    hist = laps[laps["year"] < mech_year]
    hist_e = entries[entries["year"] < mech_year]
    slow = {k for k in lc._slow_lap_set(laps) if k[0] < mech_year}
    rem = lc.fit_remaining_swing(hist, hist_e, slow_laps=slow)
    fail = lc.fit_remaining_fail_rate(hist, hist_e)

    # remaining fraction: laps done = the leader's completed laps; the
    # session's lap column is not exposed by the position stream, so the
    # leader's CURRENT lap number is approximated by stream progression —
    # OpenF1 position dates tick per lap for the leader. When the race
    # has not started (grid order, lap 0), remaining = 1.
    n_laps = _historical_laps(db_path, year, session.get("location", ""))
    frac = max(0.0, 1.0 - min(len({p["date"] for p in positions}) / n_laps, 1.0)) \
        if session.get("session_type") == "Race" else 1.0
    b = lc.remaining_bucket(frac)
    params = rem.get(b, dict(lc.GLOBAL_FALLBACK_REMAINING))
    p_fail = fail.get(b, lc.GLOBAL_FALLBACK_REMAINING["fail_rate"])

    rng = np.random.default_rng(seed)
    grid = [(r["driverId"], r["position"]) for r in runners]
    sim = rs.simulate_race(grid, n_sims, params["mean"], params["sd"],
                           p_fail, rng) if runners else pd.DataFrame(
        columns=["driverId", "sim", "position", "is_dnf"])
    summ = rs.summarize_simulation(sim) if runners else None

    out = []
    for r in runners:
        s = summ[summ["driverId"] == r["driverId"]].iloc[0]
        out.append({
            "driverId": r["driverId"],
            "position_now": r["position"],
            "p_podium": round(float(s["p_podium"]), 4),
            "p_points": round(float(s["p_points"]), 4),
            "p_out": round(float(s["p_out"]), 4),
            "expected_position": round(float(s["expected_position"]), 2),
        })
    # retired / not-yet-seen drivers of the latest season roster
    con = sqlite3.connect(db_path)
    try:
        roster = pd.read_sql(
            "SELECT DISTINCT driverId FROM fact_race_entry WHERE year = ?",
            con, params=(mech_year,))
    finally:
        con.close()
    running_ids = {r["driverId"] for r in runners}
    if session.get("session_type") == "Race":
        for did in roster["driverId"]:
            if did not in running_ids and did in set(codes.values()):
                # present earlier in the stream but gone now = retired;
                # never seen at all this session = not classified either
                out.append({"driverId": did, "position_now": None,
                            "p_podium": 0.0, "p_points": 0.0, "p_out": 1.0,
                            "expected_position": None})
    out.sort(key=lambda d: (d["position_now"] is None,
                            d["position_now"] or 99))

    fetched = datetime.now(timezone.utc)
    return {
        "schema_version": 1,
        "fetched_at": fetched.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stale_after_min": STALE_AFTER_MIN,
        "session": {k: session.get(k) for k in
                    ("session_key", "meeting_key", "session_name",
                     "session_type", "date_start", "date_end",
                     "location", "country_name", "circuit_short_name",
                     "year")},
        "mechanism_year": mech_year,
        "remaining_fraction": round(frac, 4),
        "n_laps_estimated": n_laps,
        "n_sims": n_sims,
        "rem_params_bucket": {"bucket": b, "mean": round(params["mean"], 3),
                              "sd": round(params["sd"], 3),
                              "fail_rate": round(p_fail, 4)},
        "drivers": out,
        "unmapped_numbers": unmapped,
    }


def main():
    ap = argparse.ArgumentParser(description="Live race snapshot")
    ap.add_argument("--db", default="datasets/f1_canonical.db")
    ap.add_argument("--out", default="datasets/live_state.json")
    ap.add_argument("--sims", type=int, default=400)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    try:
        doc = build_live_snapshot(args.db, args.sims, args.seed)
    except RuntimeError as e:
        raise SystemExit(f"live fetch failed: {e}") from None
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    running = sum(1 for d in doc["drivers"] if d["position_now"])
    print(f"live_state.json: {doc['session'].get('session_name')} @ "
          f"{doc['session'].get('country_name')} "
          f"({doc['session'].get('date_start')}) — {running} running, "
          f"{len(doc['drivers']) - running} retired/out, "
          f"remaining ~{doc['remaining_fraction']:.0%}")


if __name__ == "__main__":
    main()
