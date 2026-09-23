"""
error_decomposition.py — Prediction Error Decomposition.

Phase 1 of the Race Intelligence plan: for every driver-race prediction in
the backtest record, explain WHY the prediction diverged from the actual
result, using only data already committed in this repo (results, qualifying,
Jolpica lap times, pit stops).

The production model predicts a 3-class bucket, so the decomposition works
in bucket space: it asks how the race unfolded relative to the P1-3 /
P4-10 / P11+ boundaries and attributes the delta to evidence-backed causes:

  dnf_mech / dnf_driver / dnf_other — did not finish; the status field says
                  why (same taxonomy as build_training_data.py).
  over_predict     — finished worse than predicted (the dominant miss class
                  for a quali-anchored model).
  under_predict    — finished better than predicted.
  correct          — bucket matched.

For finished races the module computes the ACTUAL race quantities that
distinguish a noise miss from a structural one:

  pace_delta_s   — the driver's mean lap delta to the field-median lap
                   (same construction as the rejected PRE-race feature;
                   here it is post-race evidence, so seeing the race is
                   the whole point)
  lap1/last_gain — running-order position vs grid slot on lap 1 and at
                   the flag (on-track overtaking, from lap position data)
  pit_total_s    — time spent in pit lanes + number of stops
  sc_laps        — laps whose field-median time collapsed vs the race's
                   median pace (slow laps ⇒ SC / VSC / red flag), with the
                   first such lap (strategy-shuffle timing)

Deliberately a BATCH, post-race analyzer. It does not touch the live API:
backtest_prod.py already records the predictions and its serving caveats
are stated in MODEL_NOTES.md. This module consumes recorded artifacts —
it is the "why did it happen" layer, not a new prediction path.

Usage:
    python error_decomposition.py --datasets ./datasets --year 2026
    python error_decomposition.py --pred-csv backtest_2026.csv --out attribution_2026.csv
"""
import argparse

import numpy as np
import pandas as pd

from build_training_data import (  # reuse the committed DNF taxonomy
    DRIVER_ERROR_DNF_STATUSES,
    FINISHED_STATUSES,
    MECHANICAL_DNF_STATUSES,
)

# Bucket boundaries (mirror of train_model.position_index)
PODIUM_MAX = 3
POINTS_MAX = 10

# A lap whose FIELD-MEDIAN time exceeds this multiple of the race's median
# lap indicates safety-car / VSC / red-flag exposure. The field median under
# neutral SC typically sits 35-50% above green-flag pace, so 1.20x is a
# conservative, format-agnostic detector that needs no race-control feed.
SLOW_LAP_FACTOR = 1.20

# Pace-evidence thresholds (seconds/lap vs the field median): beyond these a
# finished race's pace is treated as a real explanatory signal, not noise.
PACE_FAST_S = -0.3
PACE_SLOW_S = 0.3

# A grid->finish swing of this many places is treated as a start/strategy
# event big enough to explain a bucket miss on its own.
BIG_SWING_PLACES = 3

# Races with at least this many slow laps count as "SC-affected".
SC_LAPS_MIN = 3


def position_index(pos: float) -> int:
    if pos < PODIUM_MAX + 1:
        return 1
    if pos > POINTS_MAX:
        return 3
    return 2


def dnf_cause(status: str) -> str:
    """'mech' | 'driver' | 'other' | 'none' — same taxonomy as training."""
    if not isinstance(status, str) or status in FINISHED_STATUSES or status.startswith("+"):
        return "none"
    if status in MECHANICAL_DNF_STATUSES:
        return "mech"
    if status in DRIVER_ERROR_DNF_STATUSES:
        return "driver"
    return "other"


def _duration_to_s(value) -> float | None:
    """Parse pit-stop duration ("22.213" or "1:02.5") to seconds."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parts = value.strip().split(":")
        secs = float(parts[-1])
        mins = int(parts[-2]) if len(parts) > 1 else 0
        return mins * 60 + secs
    except (ValueError, IndexError):
        return None


# ─────────────────────────── race-level evidence ───────────────────────────

def race_lap_evidence(laps: pd.DataFrame) -> pd.DataFrame:
    """
    Per (year, round, lap): the field-median lap time (ms), the race's own
    median lap (the green-flag pace reference), and the slow-lap mask.

    The race median (not the fastest lap) is the reference because SC laps
    are a minority of laps in the typical race — the median tracks
    green-flag pace. Comparing each lap's FIELD MEDIAN against that
    reference cancels per-driver pace differences: only a race-wide
    slowdown (SC / VSC / red flag) moves the field median.
    """
    l = laps.dropna(subset=["milliseconds"])
    if l.empty:
        return pd.DataFrame(columns=["year", "round", "lap",
                                     "field_median_ms", "race_median_ms",
                                     "is_slow_lap"])
    per_lap = (l.groupby(["year", "round", "lap"], as_index=False)["milliseconds"]
               .median()
               .rename(columns={"milliseconds": "field_median_ms"}))
    per_lap["race_median_ms"] = (per_lap.groupby(["year", "round"])["field_median_ms"]
                                 .transform("median"))
    per_lap["is_slow_lap"] = (per_lap["field_median_ms"]
                              > SLOW_LAP_FACTOR * per_lap["race_median_ms"])
    return per_lap


def safety_car_exposure(lap_evidence: pd.DataFrame, year: int, rnd: int) -> dict:
    """SC exposure for one race: slow-lap count, first slow lap, share."""
    le = lap_evidence[(lap_evidence["year"] == year) & (lap_evidence["round"] == rnd)]
    if le.empty:
        return {"sc_laps": 0, "sc_first_lap": 0, "sc_share": 0.0}
    slow = le[le["is_slow_lap"]]
    total = len(le)
    return {
        "sc_laps": int(len(slow)),
        "sc_first_lap": int(slow["lap"].min()) if len(slow) else 0,
        "sc_share": float(len(slow) / total) if total else 0.0,
    }


def driver_race_pace(laps: pd.DataFrame, lap_evidence: pd.DataFrame,
                     year: int, rnd: int, driver_id: str) -> dict:
    """
    The driver's ACTUAL race pace: mean delta (s) of their laps to the
    field-median lap, plus their median lap and lap count. DNF laps after
    retirement simply don't exist in the data — no exclusion logic needed
    for a post-race analysis.
    """
    empty = {"pace_delta_s": np.nan, "pace_laps": 0, "median_lap_s": np.nan}
    l = laps[(laps["year"] == year) & (laps["round"] == rnd)
             & (laps["driverId"] == driver_id)].dropna(subset=["milliseconds"])
    if l.empty:
        return empty
    ev = lap_evidence[(lap_evidence["year"] == year)
                      & (lap_evidence["round"] == rnd)][["lap", "field_median_ms"]]
    m = l.merge(ev, on="lap", how="inner")
    if m.empty:
        return empty
    return {
        "pace_delta_s": float((m["milliseconds"] - m["field_median_ms"]).mean() / 1000.0),
        "pace_laps": int(len(m)),
        "median_lap_s": float(m["milliseconds"].median() / 1000.0),
    }


def running_position_gains(laps: pd.DataFrame, year: int, rnd: int,
                           driver_id: str, quali_pos: int) -> dict:
    """
    Running-order gains vs the grid slot: the driver's lap-1 position and
    last-recorded-lap position, expressed as quali_pos - running position
    (positive = ahead of where they qualified). Uses the lap 'position'
    column — the cleanest measure of on-track place changes in this
    dataset without full telemetry.
    """
    l = laps[(laps["year"] == year) & (laps["round"] == rnd)
             & (laps["driverId"] == driver_id)].dropna(subset=["position"])
    if l.empty:
        return {"lap1_gain": np.nan, "last_gain": np.nan, "laps_led": 0}
    l = l.sort_values("lap")
    lap1 = float(l.iloc[0]["position"])
    last = float(l.iloc[-1]["position"])
    return {
        "lap1_gain": quali_pos - lap1,          # + = gained places at the start
        "last_gain": quali_pos - last,          # + = ahead of grid slot at the flag
        "laps_led": int((l["position"] == 1).sum()),
    }


def pit_evidence(pitstops: pd.DataFrame, year: int, rnd: int, driver_id: str) -> dict:
    """Total pit time (s, sum of stop durations) and number of stops."""
    p = pitstops[(pitstops["year"] == year) & (pitstops["round"] == rnd)
                 & (pitstops["driverId"] == driver_id)]
    if p.empty:
        return {"pit_total_s": 0.0, "pit_stops": 0}
    dur = p["duration"].map(_duration_to_s).dropna()
    return {"pit_total_s": float(dur.sum()), "pit_stops": int(len(p))}


# ─────────────────────────── decomposition ────────────────────────────────

def decompose_one(pred: int, actual: int, status: str,
                  pace: dict, pits: dict, sc: dict, gains: dict) -> dict:
    """
    Attribution for one driver-race. Returns the cause label plus the
    numbers that justify it, so every row of the report carries its own
    evidence instead of a bare category.
    """
    cause = dnf_cause(status)
    correct = (pred == actual)  # bucket-space correctness, decided FIRST
    row = {
        "cause": None,
        "verdict": None,
        "pace_delta_s": pace.get("pace_delta_s"),
        "pit_total_s": pits.get("pit_total_s"),
        "pit_stops": pits.get("pit_stops"),
        "sc_laps": sc.get("sc_laps"),
        "sc_first_lap": sc.get("sc_first_lap"),
        "lap1_gain": gains.get("lap1_gain"),
        "last_gain": gains.get("last_gain"),
    }

    # 1. DNF: the strongest evidence a finished-race prediction can be
    #    wrong. A DNF whose predicted bucket was 3 (out of points) is a
    #    CORRECT prediction — recorded as such, not as a miss.
    if cause != "none" and not correct:
        row["cause"] = f"dnf_{cause}"
        row["verdict"] = "DNF destroyed the predicted outcome"
        return row
    if cause != "none" and correct:
        row["cause"] = "correct_dnf"
        row["verdict"] = "Correct — predicted out-of-points; the DNF delivered it"
        return row

    # 2. Finished: bucket-space delta (actual bucket - predicted bucket).
    bdelta = actual - pred
    if bdelta == 0:
        row["cause"] = "correct"
        row["verdict"] = "Correct"
        return row

    if bdelta < 0:
        row["cause"] = "under_predict"
        row["verdict"] = "Finished better than predicted"
    else:
        row["cause"] = "over_predict"
        row["verdict"] = "Finished worse than predicted"

    # 3. Secondary evidence for finished-race misses — appended, never the
    #    sole label, so the attribution stays falsifiable from the row.
    pace_s = pace.get("pace_delta_s")
    last_gain = gains.get("last_gain")
    if row["cause"] == "over_predict":
        if pace_s is not None and not np.isnan(pace_s) and pace_s > PACE_SLOW_S:
            row["verdict"] += f" — slow race pace (+{pace_s:.2f}s/lap vs field median)"
        if last_gain is not None and not np.isnan(last_gain) and last_gain <= -BIG_SWING_PLACES:
            row["verdict"] += f" — lost {abs(last_gain):.0f} places from grid"
        if sc.get("sc_laps", 0) >= SC_LAPS_MIN and sc.get("sc_first_lap", 0) > 1:
            # first-lap SCs are start chaos, not strategy shuffles
            row["verdict"] += f" — SC/VSC at lap {sc['sc_first_lap']} shuffled strategy"
    else:  # under_predict
        if pace_s is not None and not np.isnan(pace_s) and pace_s < PACE_FAST_S:
            row["verdict"] += f" — fast race pace ({pace_s:.2f}s/lap vs field median)"
        if last_gain is not None and not np.isnan(last_gain) and last_gain >= BIG_SWING_PLACES:
            row["verdict"] += f" — gained {last_gain:.0f} places from grid"
    return row


def active_universe(results: pd.DataFrame) -> tuple[set, set]:
    """
    The driver/constructor universe the training harness evaluates: whoever
    raced in the single most recent round of results.csv (same contract as
    build_training_data.py's active_driver / active_constructor flags).
    Restricting the decomposition to this universe keeps its headline
    numbers comparable with train_model's walk-forward reports. The full
    results.csv universe pools slightly HIGHER (68.9% vs 66.4% baseline) —
    the active grid skews toward recent, more volatile seasons — so the
    two numbers are composition effects, not accuracy claims about
    retired drivers. Row-for-row, the two universes agree exactly where
    they overlap (verified against the canonical DB, Phase 2).
    """
    latest_year = results["year"].max()
    latest_round = results[results["year"] == latest_year]["round"].max()
    latest = results[(results["year"] == latest_year)
                     & (results["round"] == latest_round)]
    return (set(latest["driverId"]), set(latest["constructorId"]))


def build_decompositions(datasets_dir: str, predictions: pd.DataFrame,
                         active_only: bool = True) -> pd.DataFrame:
    """
    Attach actual-race evidence to every recorded prediction and attribute
    the outcome. `predictions` needs: year, round, driver, qpos, pred,
    actual (bucket ints); optional race, driverId.

    active_only=True (default) restricts to the current grid — the same
    universe train_model evaluates — so accuracy here is comparable with
    the walk-forward reports. Pass False to decompose every recorded race
    including retired entities (kept for exploratory use; its pooled
    accuracy is NOT comparable with the harness numbers).
    """
    d = datasets_dir
    results = pd.read_csv(f"{d}/results.csv")
    laps = pd.read_csv(f"{d}/lap_times_jolpica.csv")
    pitstops = pd.read_csv(f"{d}/pit_stops_jolpica.csv")

    # driverId is the join key in the lap/pit data; predictions may carry
    # driverName — map through results (it has both) BEFORE any filtering.
    name_to_id = dict(results[["driverName", "driverId"]].drop_duplicates().to_numpy())
    preds = predictions.copy()
    if "driverId" not in preds.columns:
        preds["driverId"] = preds["driver"].map(name_to_id)
    else:
        preds["driverId"] = preds["driverId"].fillna(preds["driver"].map(name_to_id))

    if active_only:
        active_drivers, active_ctors = active_universe(results)
        results = results[(results["driverId"].isin(active_drivers))
                          & (results["constructorId"].isin(active_ctors))]
        preds = preds[preds["driverId"].isin(active_drivers)]

    lap_ev = race_lap_evidence(laps)

    out = []
    for _, p in preds.iterrows():
        year, rnd = int(p["year"]), int(p["round"])
        driver = p["driver"]
        driver_id = p["driverId"]
        rr = results[(results["year"] == year) & (results["round"] == rnd)
                     & (results["driverId"] == driver_id)]
        if rr.empty:
            continue
        rr = rr.iloc[0]

        pace = driver_race_pace(laps, lap_ev, year, rnd, driver_id)
        pits = pit_evidence(pitstops, year, rnd, driver_id)
        sc = safety_car_exposure(lap_ev, year, rnd)
        gains = running_position_gains(laps, year, rnd, driver_id, int(p["qpos"]))

        dec = decompose_one(int(p["pred"]), int(p["actual"]), rr["status"],
                            pace, pits, sc, gains)
        dec.update({
            "year": year, "round": rnd, "race": p.get("race", rr["raceName"]),
            "driver": driver, "qpos": int(p["qpos"]),
            "pred": int(p["pred"]), "actual": int(p["actual"]),
            "finish_pos": float(rr["position"]), "status": rr["status"],
            "constructor": rr["constructorName"],
        })
        out.append(dec)

    cols = ["year", "round", "race", "driver", "constructor", "qpos", "pred",
            "actual", "finish_pos", "status", "cause", "verdict",
            "pace_delta_s", "pit_total_s", "pit_stops",
            "sc_laps", "sc_first_lap", "lap1_gain", "last_gain"]
    return pd.DataFrame(out, columns=cols)


def summarize(dec: pd.DataFrame) -> dict:
    """
    Aggregate the attribution table into the headline numbers.

    Universe note: `dec` should cover the same driver-races the training
    harness evaluates (rows whose driver AND constructor are both on the
    current grid — the active_driver/active_constructor contract). The
    full results.csv universe pools differently (68.9% vs 66.4% baseline)
    purely from season composition; numbers are only comparable within
    one universe.
    """
    n = len(dec)
    misses = dec[~dec["cause"].isin(["correct", "correct_dnf"])]
    over = dec[dec["cause"] == "over_predict"]
    under = dec[dec["cause"] == "under_predict"]
    dnf_rows = misses[misses["cause"].str.startswith("dnf_", na=False)]
    finished_misses = misses[~misses["cause"].str.startswith("dnf_", na=False)]

    def share(sub: pd.DataFrame) -> float:
        return len(sub) / len(misses) if len(misses) else 0.0

    def pace_share(sub: pd.DataFrame, cond) -> float:
        if not len(sub):
            return 0.0
        vals = sub["pace_delta_s"].dropna()
        return float(cond(vals).mean()) if len(vals) else 0.0

    return {
        "n_predictions": n,
        "accuracy": dec["cause"].isin(["correct", "correct_dnf"]).mean() if n else 0.0,
        "n_misses": len(misses),
        "cause_counts": misses["cause"].value_counts().to_dict(),
        "cause_share": {
            "dnf_mechanical": share(dnf_rows[dnf_rows["cause"] == "dnf_mech"]),
            "dnf_driver_error": share(dnf_rows[dnf_rows["cause"] == "dnf_driver"]),
            "dnf_other": share(dnf_rows[dnf_rows["cause"] == "dnf_other"]),
            "over_predict": share(over),
            "under_predict": share(under),
        },
        "over_pace_slow_share": pace_share(over, lambda v: v > PACE_SLOW_S),
        "under_pace_fast_share": pace_share(under, lambda v: v < PACE_FAST_S),
        "sc_involved_share": share(misses[misses["sc_laps"] >= SC_LAPS_MIN]),
        "big_grid_swing_share": share(misses[misses["last_gain"].abs() >= BIG_SWING_PLACES]),
    }


def print_summary(s: dict) -> None:
    print("\n=== Prediction Error Decomposition ===")
    print(f"{s['n_predictions']} predictions | accuracy {s['accuracy']:.1%} "
          f"({s['n_misses']} misses)\n")
    print("Cause breakdown (share of all misses):")
    for k, v in s["cause_share"].items():
        print(f"  {k:24s} {v:6.1%}")
    print("\nFinished-race miss evidence:")
    print(f"  over-predict misses with slow race pace (>+0.3s/lap): {s['over_pace_slow_share']:.0%}")
    print(f"  under-predict misses with fast race pace (<-0.3s/lap): {s['under_pace_fast_share']:.0%}")
    print(f"  misses in races with >=3 slow (SC) laps:               {s['sc_involved_share']:.0%}")
    print(f"  misses with >=3-place grid->finish swing:              {s['big_grid_swing_share']:.0%}")


# ─────────────────────────── CLI ───────────────────────────────────────────

def _baseline_predictions(datasets_dir: str, year: int | None) -> pd.DataFrame:
    """
    Full prediction record without the API: the quali-bucket baseline over
    every (round, driver) with both quali + results present. Feeding THIS
    record through the decomposition shows what the model must beat and
    where the sport's irreducible noise lives.
    """
    d = datasets_dir
    results = pd.read_csv(f"{d}/results.csv")
    quali = pd.read_csv(f"{d}/qualifying.csv")
    r = results if year is None else results[results["year"] == year]
    q = quali if year is None else quali[quali["year"] == year]
    # Keyed on (year, round, driverId): in full-record mode a (round, driver)
    # key alone collides across seasons and silently serves one season's
    # quali positions to every other year — a bug that poisoned the pooled
    # accuracy while leaving single-year runs correct.
    q_lookup = {(int(a), int(b), c): int(e)
                for a, b, c, e in zip(q["year"], q["round"], q["driverId"], q["position"])}
    rows = []
    for _, rr in r.iterrows():
        key = (int(rr["year"]), int(rr["round"]), rr["driverId"])
        if key not in q_lookup:
            continue
        qpos = q_lookup[key]
        rows.append({
            "year": int(rr["year"]), "round": int(rr["round"]),
            "race": rr["raceName"], "driver": rr["driverName"],
            "driverId": rr["driverId"],
            "qpos": qpos, "pred": position_index(qpos),
            "actual": position_index(rr["position"]),
        })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description="Prediction Error Decomposition")
    ap.add_argument("--datasets", default="./datasets")
    ap.add_argument("--pred-csv", default=None,
                    help="CSV of recorded backtest predictions (year, round, race, "
                         "driver, qpos, pred, actual). If omitted, the trivial "
                         "quali-bucket baseline is decomposed instead.")
    ap.add_argument("--year", type=int, default=None, help="filter to one season")
    ap.add_argument("--out", default=None, help="write the attribution table to CSV")
    args = ap.parse_args()

    if args.pred_csv:
        preds = pd.read_csv(args.pred_csv)
        if "year" not in preds.columns:
            if args.year is None:
                raise SystemExit("--pred-csv has no 'year' column: pass --year")
            preds["year"] = args.year
    else:
        preds = _baseline_predictions(args.datasets, args.year)
        print(f"No --pred-csv given: decomposing the quali-bucket BASELINE record "
              f"({len(preds)} driver-races) — the record any model must beat.")

    if args.year:
        preds = preds[preds["year"] == args.year]

    dec = build_decompositions(args.datasets, preds)
    s = summarize(dec)
    print_summary(s)

    if args.out:
        dec.to_csv(args.out, index=False, lineterminator="\n")
        print(f"\nAttribution table written to {args.out}")


if __name__ == "__main__":
    main()
