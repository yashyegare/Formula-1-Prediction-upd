"""
race_intelligence.py — build the race-intel artifact the API serves.

Phase 1–3 outputs, joined into one JSON document per season:

  per-race   — for every COMPLETED race: each driver's outcome
               distribution (P(podium)/P(points)/P(out), expected
               position, simulated DNF rate) from the walk-forward
               scenario simulator, plus the derived grid-swing insight
               (mean/observed grid->finish shift) — the "why it happened"
               view a dashboard can render without touching pandas.
  per-race   — for every FUTURE round of the season: the same simulated
               distributions from the best point-in-time grid available
               (real quali positions if the round has qualified; else
               the current championship order of the drivers'
               constructors — the same ordering train_model showed
               quali position carries). Distributions and expected
               positions are served; the grid-swing insight is omitted
               (nothing has happened yet). These are PREdictions.
  season     — the error-attribution summary (miss taxonomy + evidence
               shares) for the quali-bucket baseline record.

Every race carries `status`: "raced", "upcoming_post_quali", or
"scheduled"; the top-level `next_round` names the first non-raced round.

Schema v3 adds the ACTUAL outcome of raced rounds to each driver —
`actual_position`, `status`, `is_dnf`, `dnf_cause` (from fact_race_entry
joined to dim_status) — so the serving layer can explain user-prediction
misses (the postmortem) from this artifact alone: the Flask DB's results
table only stores classified positions, and the canonical DB is not
committed to the deploy.

Schema v4 adds a `circuit` object to every race (circuitId, name,
location, country, lat/lng from dim_circuit, the Jolpica circuitId as
the join key) — the shared circuit registry the Track Explorer
deep-links and any future per-circuit insight need, without the serving
layer ever touching the canonical DB.

Everything is computed OFFLINE by this script and written to
race_intel.json; the API just serves the file. That keeps the Flask
service free of numpy/sklearn imports and makes the artifact itself
reviewable in a diff before it ships. Two builds with the same seed are
byte-identical (per-race seed 42 + year*100 + round, so adding rounds
never reshuffles existing ones).

Usage:
    python race_intelligence.py --db datasets/f1_canonical.db \
        --datasets ./datasets --out datasets/race_intel.json \
        --season 2026 --sims 2000
"""
import argparse
import json
import sqlite3

import numpy as np
import pandas as pd

import race_simulator as rs
from error_decomposition import build_decompositions, summarize


def _load_race_meta(db_path: str) -> pd.DataFrame:
    con = sqlite3.connect(db_path)
    try:
        return pd.read_sql(
            "SELECT year, round, name, date, circuitId FROM fact_race", con)
    finally:
        con.close()


def _load_circuits(db_path: str) -> dict[str, dict]:
    """circuitId -> registry entry, straight from dim_circuit."""
    con = sqlite3.connect(db_path)
    try:
        df = pd.read_sql(
            "SELECT circuitId, name, location, country, lat, lng "
            "FROM dim_circuit", con)
    finally:
        con.close()
    return {r.circuitId: {
        "circuitId": r.circuitId,
        "name": "" if pd.isna(r.name) else str(r.name),
        "location": "" if pd.isna(r.location) else str(r.location),
        "country": "" if pd.isna(r.country) else str(r.country),
        "lat": None if pd.isna(r.lat) else round(float(r.lat), 4),
        "lng": None if pd.isna(r.lng) else round(float(r.lng), 4),
    } for r in df.itertuples()}


def _driver_standings(entries: pd.DataFrame, through_round: int,
                      db_path: str) -> pd.DataFrame:
    """Championship points per driver through `through_round`, ranked.

    Ties break by driverId — deterministic, and only ever used for
    ordering (the front-row distinction between two zero-point rookies
    is far below the simulator's noise floor, but it must never be
    random). `entries` comes from rs.load_entries (no points column),
    so points are re-read from the DB facts; the year is taken from the
    entries frame (the caller passes one season only).
    """
    raced = entries[entries["round"] <= through_round]
    season_year = int(raced["year"].iloc[0]) if len(raced) \
        else int(entries["year"].iloc[0])
    con = sqlite3.connect(db_path)
    try:
        pts = pd.read_sql(
            "SELECT driverId, SUM(points) AS points FROM fact_race_entry "
            "WHERE year = ? AND round <= ? GROUP BY driverId",
            con, params=(season_year, int(through_round)))
    finally:
        con.close()
    pts = (pts.sort_values(["points", "driverId"],
                           ascending=[False, True])
           .reset_index(drop=True))
    pts["rank"] = range(1, len(pts) + 1)
    return pts


def _grid_order_for_future(season_entries: pd.DataFrame,
                           quali: pd.DataFrame, rnd: int,
                           db_path: str) -> list[tuple[str, int]]:
    """Point-in-time grid for a future round: real quali positions when
    the round has qualified, else current championship order."""
    q = quali[(quali["year"] == season_entries["year"].iloc[0])
              & (quali["round"] == rnd)]
    if len(q):
        q = q[q["position"].notna()].copy()
        # driver standings rank for ties (quali has legitimate ties)
        standings = _driver_standings(
            season_entries, season_entries["round"].max(), db_path)
        q = q.merge(standings[["driverId", "rank"]], on="driverId", how="left")
        q["rank"] = q["rank"].fillna(999)
        q = q.sort_values(["position", "rank", "driverId"])
        return list(zip(q["driverId"], range(1, len(q) + 1)))
    # championship order of the drivers' current constructors
    standings = _driver_standings(
        season_entries, season_entries["round"].max(), db_path)
    season_year = int(season_entries["year"].iloc[0])
    last_rnd = int(season_entries["round"].max())
    ctor_of = (season_entries.sort_values("round")
               .groupby("driverId")["constructorId"].last())
    con = sqlite3.connect(db_path)
    try:
        ctor_pts = pd.read_sql(
            "SELECT constructorId, SUM(points) AS points FROM fact_race_entry "
            "WHERE year = ? AND round <= ? GROUP BY constructorId",
            con, params=(season_year, last_rnd))
    finally:
        con.close()
    ctor_rank = {c: i + 1 for i, c in enumerate(
        ctor_pts.sort_values("points", ascending=False)["constructorId"])}
    drv = standings.copy()
    drv["ctor"] = drv["driverId"].map(ctor_of)
    drv["ctor_rank"] = drv["ctor"].map(ctor_rank).fillna(99)
    drv = drv.sort_values(["ctor_rank", "rank"], kind="mergesort")
    return list(zip(drv["driverId"], range(1, len(drv) + 1)))


def _race_doc(yr: int, rnd: int, name: str, date: str, status: str,
              grid: list[tuple[str, int]], n_drivers: int, params: dict,
              n_sims: int, seed: int, actual: pd.DataFrame | None,
              driver_meta: pd.DataFrame,
              circuit: dict) -> dict:
    """Simulate one race and render its artifact entry. `actual` carries
    the real positions for raced rounds (None for future rounds)."""
    rng = np.random.default_rng(seed + yr * 100 + rnd)
    sim = rs.simulate_race(grid, n_sims, params["mean"], params["sd"],
                           params["dnf_rate"], rng)
    summ = rs.summarize_simulation(sim)

    meta = driver_meta.set_index("driverId")
    grid_map = dict(grid)
    if actual is not None:
        summ = summ.merge(
            actual[["driverId", "position", "grid",
                    "status", "is_dnf", "dnf_cause"]],
            on="driverId", how="left")
        # derived insight: the driver's realized grid->finish shift vs
        # their simulated expected shift (the "why" a race landed where
        # it did, in one number per driver)
        summ["grid_eff"] = summ["grid"].clip(lower=1)
        summ["observed_swing"] = summ["grid_eff"] - summ["position"]
        summ["sim_swing_mean"] = summ["expected_position"] - summ["grid_eff"]

    drivers = []
    for r in summ.sort_values("expected_position").itertuples():
        d = {
            "driverId": r.driverId,
            "driverCode": meta["code"].get(r.driverId, ""),
            "surname": meta["surname"].get(r.driverId, ""),
            "constructorId": meta["constructorId"].get(r.driverId, ""),
            "grid": int(grid_map[r.driverId]),
            "p_podium": round(float(r.p_podium), 4),
            "p_points": round(float(r.p_points), 4),
            "p_out": round(float(r.p_out), 4),
            "expected_position": round(float(r.expected_position), 2),
            "sim_dnf_rate": round(float(r.dnf_rate_sim), 4),
        }
        if actual is not None:
            d["observed_swing"] = (None if pd.isna(r.position)
                                   else int(r.observed_swing))
            d["sim_swing_mean"] = round(float(r.sim_swing_mean), 2)
            # schema v3: the actual outcome, for the postmortem join
            d["actual_position"] = (None if pd.isna(r.position)
                                    else int(r.position))
            d["status"] = "" if pd.isna(r.status) else str(r.status)
            d["is_dnf"] = bool(r.is_dnf == 1)
            d["dnf_cause"] = (None if pd.isna(r.dnf_cause)
                              else str(r.dnf_cause))
        drivers.append(d)

    doc = {
        "year": int(yr), "round": int(rnd), "name": name, "date": date,
        "status": status, "n_drivers": n_drivers,
        "circuit": circuit,
        "params": {"swing_mean": round(params["mean"], 3),
                   "swing_sd": round(params["sd"], 3),
                   "dnf_rate": round(params["dnf_rate"], 4)},
        "drivers": drivers,
    }
    return doc


def build_race_intel(db_path: str, datasets_dir: str, season: int,
                     n_sims: int, seed: int) -> dict:
    entries = rs.load_entries(db_path)
    train = entries[entries["year"] <= season - 1]
    test = entries[entries["year"] == season]
    if test.empty:
        raise SystemExit(f"no race entries for season {season}")
    params = rs.fit_swing_params(train)

    # driver display metadata + current constructors (from the DB facts)
    con = sqlite3.connect(db_path)
    try:
        driver_meta = pd.read_sql(
            "SELECT d.driverId, d.code, d.surname, "
            "      (SELECT e.constructorId FROM fact_race_entry e "
            "        WHERE e.driverId = d.driverId AND e.year = ? "
            "        ORDER BY e.round DESC LIMIT 1) AS constructorId "
            "FROM dim_driver d", con, params=(season,))
        # v3 actual-outcome fields, per driver per round of this season
        entry_status = pd.read_sql(
            "SELECT e.year, e.round, e.driverId, s.status, "
            "       e.is_dnf, e.dnf_cause "
            "FROM fact_race_entry e JOIN dim_status s ON s.statusId = e.statusId "
            "WHERE e.year = ?", con, params=(season,))
    finally:
        con.close()

    races_df = pd.read_csv(f"{datasets_dir}/races.csv")
    season_races = races_df[races_df["year"] == season].sort_values("round")
    quali = pd.read_csv(f"{datasets_dir}/qualifying.csv")

    last_raced = int(test["round"].max())
    meta_db = _load_race_meta(db_path)
    circuits = _load_circuits(db_path)

    races = []
    for _, rr in season_races.iterrows():
        rnd = int(rr["round"])
        name = str(rr["name"])
        date = str(rr["date"])
        cid = str(rr["circuitId"])
        # year-scoped: matching on round alone pulled names/circuits from
        # the oldest season in fact_race (v3 artifact shipped round 5 as
        # "Spanish GP" when 2026 round 5 is Canada)
        db_meta = meta_db[(meta_db["round"] == rnd)
                          & (meta_db["year"] == season)]
        if not db_meta.empty and str(db_meta["name"].iloc[0]) not in ("nan", ""):
            name = str(db_meta["name"].iloc[0])
            if str(db_meta["circuitId"].iloc[0]) not in ("nan", ""):
                cid = str(db_meta["circuitId"].iloc[0])
        # registry entry: dim_circuit when known, else the bare id so the
        # join key still ships even if the dimension lagged a new venue
        circuit = circuits.get(cid, {"circuitId": cid, "name": "",
                                     "location": "", "country": "",
                                     "lat": None, "lng": None})

        if rnd <= last_raced:
            race = test[test["round"] == rnd]
            actual = race[["driverId", "position", "grid"]].merge(
                entry_status[entry_status["round"] == rnd]
                [["driverId", "status", "is_dnf", "dnf_cause"]],
                on="driverId", how="left")
            grid = list(zip(race["driverId"],
                            race["grid"].fillna(0).astype(int)))
            doc = _race_doc(season, rnd, name, date, "raced", grid,
                            len(race), params, n_sims, seed, actual,
                            driver_meta, circuit)
        elif len(quali[(quali["year"] == season)
                       & (quali["round"] == rnd)]):
            grid = _grid_order_for_future(test, quali, rnd, db_path)
            doc = _race_doc(season, rnd, name, date, "upcoming_post_quali",
                            grid, len(grid), params, n_sims, seed, None,
                            driver_meta, circuit)
        else:
            grid = _grid_order_for_future(test, quali, rnd, db_path)
            doc = _race_doc(season, rnd, name, date, "scheduled", grid,
                            len(grid), params, n_sims, seed, None,
                            driver_meta, circuit)
        races.append(doc)

    future = [r for r in races if r["status"] != "raced"]
    next_round = min((r["round"] for r in future), default=None)

    # season-level attribution from the quali-bucket baseline record
    preds = _baseline_predictions_frame(datasets_dir, season)
    dec = build_decompositions(datasets_dir, preds)
    s = summarize(dec)
    season_summary = {
        "n_predictions": s["n_predictions"],
        "accuracy": round(s["accuracy"], 4),
        "n_misses": s["n_misses"],
        "cause_share": {k: round(v, 4) for k, v in s["cause_share"].items()},
        "evidence": {
            "over_pace_slow_share": round(s["over_pace_slow_share"], 4),
            "under_pace_fast_share": round(s["under_pace_fast_share"], 4),
            "sc_involved_share": round(s["sc_involved_share"], 4),
            "big_grid_swing_share": round(s["big_grid_swing_share"], 4),
        },
    }

    return {
        "schema_version": 4,
        "season": season,
        "n_sims": n_sims,
        "next_round": next_round,
        "mechanism": {"swing_mean": round(params["mean"], 3),
                      "swing_sd": round(params["sd"], 3),
                      "dnf_rate": round(params["dnf_rate"], 4)},
        "races": sorted(races, key=lambda r: r["round"]),
        "season_attribution": season_summary,
    }


def _baseline_predictions_frame(datasets_dir: str, season: int) -> pd.DataFrame:
    from error_decomposition import _baseline_predictions
    return _baseline_predictions(datasets_dir, season)


def main():
    ap = argparse.ArgumentParser(description="Build the race-intel artifact")
    ap.add_argument("--db", default="datasets/f1_canonical.db")
    ap.add_argument("--datasets", default="./datasets")
    ap.add_argument("--out", default="datasets/race_intel.json")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--sims", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    doc = build_race_intel(args.db, args.datasets, args.season, args.sims,
                           args.seed)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    n_raced = sum(1 for r in doc["races"] if r["status"] == "raced")
    print(f"race_intel.json: {len(doc['races'])} races "
          f"({n_raced} raced, {len(doc['races']) - n_raced} future), "
          f"season {args.season} ({doc['n_sims']} sims) "
          f"-> {args.out}")


if __name__ == "__main__":
    main()
