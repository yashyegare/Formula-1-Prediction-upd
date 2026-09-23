"""
race_intelligence.py — build the race-intel artifact the API serves.

Phase 1–3 outputs, joined into one JSON document per season:

  per-race   — for every completed race: each driver's outcome
               distribution (P(podium)/P(points)/P(out), expected
               position, simulated DNF rate) from the walk-forward
               scenario simulator, plus the derived grid-swing insight
               (mean/observed grid->finish shift) — the "why it happened"
               view a dashboard can render without touching pandas.
  season     — the error-attribution summary (miss taxonomy + evidence
               shares) for the quali-bucket baseline record.

Everything is computed OFFLINE by this script and written to
race_intel.json; the API just serves the file. That keeps the Flask
service free of numpy/sklearn imports and makes the artifact itself
reviewable in a diff before it ships.

Usage:
    python race_intelligence.py --db datasets/f1_canonical.db \
        --datasets ./datasets --out datasets/race_intel.json \
        --season 2026 --sims 2000
"""
import argparse
import json

import numpy as np
import pandas as pd

import race_simulator as rs
from error_decomposition import build_decompositions, summarize


def build_race_intel(db_path: str, datasets_dir: str, season: int,
                     n_sims: int, seed: int) -> dict:
    entries = rs.load_entries(db_path)
    train = entries[entries["year"] <= season - 1]
    test = entries[entries["year"] == season]
    if test.empty:
        raise SystemExit(f"no race entries for season {season}")
    params = rs.fit_swing_params(train)

    races = []
    for (yr, rnd), race in test.groupby(["year", "round"]):
        rng = np.random.default_rng(seed + yr * 100 + rnd)
        grid = list(zip(race["driverId"],
                        race["grid"].fillna(0).astype(int)))
        sim = rs.simulate_race(grid, n_sims, params["mean"], params["sd"],
                               params["dnf_rate"], rng)
        summ = rs.summarize_simulation(sim).merge(
            race[["driverId", "position", "grid"]], on="driverId")

        # derived insight: the driver's realized grid->finish shift vs
        # their simulated expected shift (the "why" a race landed where
        # it did, in one number per driver)
        n = len(race)
        summ["observed_swing"] = summ["grid"].clip(lower=1) - summ["position"]
        summ["sim_swing_mean"] = summ["expected_position"] \
            - summ["grid"].clip(lower=1)
        drivers = [{
            "driverId": r.driverId,
            "grid": int(r.grid),
            "p_podium": round(float(r.p_podium), 4),
            "p_points": round(float(r.p_points), 4),
            "p_out": round(float(r.p_out), 4),
            "expected_position": round(float(r.expected_position), 2),
            "sim_dnf_rate": round(float(r.dnf_rate_sim), 4),
            "observed_swing": None if pd.isna(r.position)
            else int(r.observed_swing),
            "sim_swing_mean": round(float(r.sim_swing_mean), 2),
        } for r in summ.itertuples()]

        races.append({
            "year": int(yr), "round": int(rnd), "n_drivers": n,
            "params": {"swing_mean": round(params["mean"], 3),
                       "swing_sd": round(params["sd"], 3),
                       "dnf_rate": round(params["dnf_rate"], 4)},
            "drivers": drivers,
        })

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
        "schema_version": 1,
        "season": season,
        "n_sims": n_sims,
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
    print(f"race_intel.json: {len(doc['races'])} races, season {args.season} "
          f"({doc['n_sims']} sims) -> {args.out}")


if __name__ == "__main__":
    main()
