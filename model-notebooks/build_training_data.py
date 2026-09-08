"""
build_training_data.py

Rebuilds cleaned_data.csv (the file train_model.py trains on) from
the Jolpica-sourced CSVs produced by fetch_jolpica_data.py.

Fixes vs. the original notebook:
  - Target is the actual race FINISHING position (results.csv 'position',
    which Jolpica fills in as a DNF-safe numeric order), not another
    qualifying-session position. The original notebook accidentally
    trained on quali-position -> quali-position due to a pandas merge
    suffix mixup (position_x/position_y).
  - 'quali_pos' feature is the real qualifying-session classification
    (qualifying.csv 'position'), not the post-penalty starting grid slot.
  - DNF detection uses Jolpica's text status field instead of old
    Ergast numeric status IDs, which no longer exist in this data.
  - Constructor identity is NOT collapsed across rebrands. Each
    constructor name from the data is kept as its own label.

Leakage fixes (found by the offline-94% vs prod-~66% accuracy gap):
  - driver_confidence / constructor_reliability were computed ONCE per
    driver over the ENTIRE dataset (2018-2026) and stamped onto every
    row - a 2018 race carried DNF information from 2026. They are now
    EXPANDING-WINDOW stats: per row, computed from strictly earlier
    races only. A driver's first career race gets FIRST_APPEARANCE_PRIOR.
  - Championship standings (fetched all along, never used) are now
    joined as features taken from the round BEFORE the target race
    (round 1 carries the previous season's FINAL standings). A race is
    never featurized with its own results.

Serving side (flask-app/app.py /predictGrid): for a FUTURE race,
"all data to date" IS the correct point-in-time value, so the roster
JSON keeps lifetime confidence/reliability and adds the most recent
championship snapshot. app.py sends those per-row at inference.

Usage:
    python build_training_data.py --datasets ./datasets --out ./datasets
"""
import argparse
import json

import pandas as pd

# Statuses that count as "classified / finished" (not a DNF)
FINISHED_STATUSES = {"Finished", "Lapped"}

# Prior for a driver/constructor's first-ever row (no history exists yet).
# Must NOT be derived from the dataset - it is a fixed neutral value.
FIRST_APPEARANCE_PRIOR = 0.90

# Prior DNF-cause RATE for a first-ever row of the cause-split features
# (mirror of FIRST_APPEARANCE_PRIOR: 1 - 0.90 reliability = 0.10 failure
# rate, roughly the sport's real DNF base rate).
FIRST_APPEARANCE_DNF_RATE = 0.10

# Standings sentinels when no prior snapshot exists (first season's round 1,
# or an entity absent from the championship table that round).
NO_STANDING_POSITION = 0.0
NO_STANDING_POINTS = 0.0

# Prior for a constructor's first-ever race in its recent-form feature:
# zero points. Fixed constant - never derived from data that could leak.
CONSTRUCTOR_FORM_PRIOR = 0.0


def _lap_time_ms(value) -> float | None:
    """Parse a Jolpica/Ergast lap-time string ("M:SS.mmm", "SS.mmm") to ms.
    Returns None for missing/unparseable times."""
    if not isinstance(value, str) or not value.strip():
        return None
    parts = value.strip().split(":")
    try:
        if len(parts) == 2:
            minutes, rest = int(parts[0]), parts[1]
        elif len(parts) == 1:
            minutes, rest = 0, parts[0]
        else:
            return None
        sec_str, ms_str = rest.split(".")
        return (minutes * 60 + int(sec_str)) * 1000 + int(ms_str.ljust(3, "0")[:3])
    except (ValueError, IndexError):
        return None

# Prior for a driver's first-ever race in the recent-form feature: a
# neutral "no gain, no loss" grid->finish delta. Fixed constant - never
# derived from data that could leak.
RECENT_FORM_PRIOR = 0.0

# How many prior races the recent-form features average.
RECENT_FORM_WINDOW = 5


def is_dnf(status: str) -> int:
    if status in FINISHED_STATUSES:
        return 0
    if isinstance(status, str) and status.startswith("+"):  # "+1 Lap", ...
        return 0
    return 1


# DNF-cause classification from Jolpica's text status field. The split
# matters because the two causes live on different entities and different
# time-scales: an engine/gearbox failure is the CAR (constructor) and is
# fairly stationary year to year, while accidents/collisions are the
# DRIVER's racecraft and can change with a seat move or experience.
MECHANICAL_DNF_STATUSES = {
    "Battery", "Brakes", "Clutch", "Cooling system", "Differential",
    "Driveshaft", "Electrical", "Electronics", "Engine", "Exhaust",
    "Fuel leak", "Fuel pressure", "Fuel pump", "Gearbox", "Hydraulics",
    "Mechanical", "Oil leak", "Out of fuel", "Overheating", "Power Unit",
    "Power loss", "Puncture", "Radiator", "Steering", "Suspension",
    "Transmission", "Turbo", "Tyre", "Undertray", "Vibrations",
    "Water leak", "Water pressure", "Water pump", "Wheel", "Wheel nut",
}
DRIVER_ERROR_DNF_STATUSES = {"Accident", "Collision", "Collision damage", "Spun off"}


def dnf_cause(status: str) -> str:
    """Classify a status: 'mech' (car failure), 'driver' (accident/collision),
    'other' (DNF with ambiguous/external cause: damage, debris, illness,
    disqualification, ...), or 'none' (not a DNF)."""
    if not is_dnf(status):
        return "none"
    if status in MECHANICAL_DNF_STATUSES:
        return "mech"
    if status in DRIVER_ERROR_DNF_STATUSES:
        return "driver"
    return "other"


def _expanding_reliability(results: pd.DataFrame, group_col: str) -> pd.Series:
    """
    Point-in-time reliability per row: 1 - (DNFs / entries) over races
    STRICTLY BEFORE the row's (year, round). Every row of a given
    (entity, race) shares one value - a race never predicts itself.
    """
    frame = results[["year", "round", group_col, "driver_dnf"]].copy()
    frame["_order"] = frame["year"] * 1000 + frame["round"]

    per_race = (
        frame.groupby([group_col, "_order"], as_index=False)["driver_dnf"]
        .agg(["sum", "count"])
        .sort_values([group_col, "_order"])
    )
    g = per_race.groupby(group_col, sort=False)
    # shift(1) within the entity drops the race itself; cumsum then gives
    # the expanding totals over all PRIOR races (NaN on the first race).
    shifted = g[["sum", "count"]].shift(1)
    per_race["prior_sum"] = shifted["sum"].groupby(per_race[group_col], sort=False).cumsum()
    per_race["prior_cnt"] = shifted["count"].groupby(per_race[group_col], sort=False).cumsum()

    per_race["rel"] = (1 - per_race["prior_sum"] / per_race["prior_cnt"]).fillna(
        FIRST_APPEARANCE_PRIOR
    )

    # Broadcast each (entity, race) value back onto its rows, preserving order.
    out = frame[[group_col, "_order"]].merge(
        per_race[[group_col, "_order", "rel"]], on=[group_col, "_order"], how="left"
    )
    return pd.Series(out["rel"].to_numpy(), index=results.index)


def _expanding_dnf_rate(results: pd.DataFrame, group_col: str, flag_col: str) -> pd.Series:
    """
    Point-in-time rate of a 0/1 DNF-cause flag per row: the entity's share
    of prior ENTRIES flagged with this cause, over races STRICTLY BEFORE
    the row's (year, round). Same expanding-window contract as
    _expanding_reliability - a race never appears in its own features.
    First-ever race gets FIRST_APPEARANCE_DNF_RATE.
    """
    frame = results[["year", "round", group_col, flag_col]].copy()
    frame["_order"] = frame["year"] * 1000 + frame["round"]

    per_race = (
        frame.groupby([group_col, "_order"], as_index=False)[flag_col]
        .agg(["sum", "count"])
        .sort_values([group_col, "_order"])
    )
    g = per_race.groupby(group_col, sort=False)
    shifted = g[["sum", "count"]].shift(1)  # drop the race itself
    per_race["prior_sum"] = shifted["sum"].groupby(per_race[group_col], sort=False).cumsum()
    per_race["prior_cnt"] = shifted["count"].groupby(per_race[group_col], sort=False).cumsum()

    per_race["rate"] = (per_race["prior_sum"] / per_race["prior_cnt"]).fillna(
        FIRST_APPEARANCE_DNF_RATE
    )

    out = frame[[group_col, "_order"]].merge(
        per_race[[group_col, "_order", "rate"]], on=[group_col, "_order"], how="left"
    )
    return pd.Series(out["rate"].to_numpy(), index=results.index)


def _attach_prior_standings(
    base: pd.DataFrame, id_col: str, standings: pd.DataFrame,
    pos_out: str, ratio_out: str,
) -> pd.DataFrame:
    """
    Attach championship position + leader-share points ratio from the round
    BEFORE the target race. Round 1 rows carry the previous season's FINAL
    standings. A race's own round never appears in its features.

    The ratio (entity points / leader points in the same snapshot) replaces
    raw points: raw championship points are not comparable across a season
    (40 pts at round 4 = dominating; 40 pts at round 20 = mid-pack) while
    the share-of-leader stays on a 0..1 scale all year.
    """
    snap = standings.copy()
    snap["_order"] = snap["year"] * 1000 + snap["round"]
    snap_i = snap.set_index([id_col, "_order"])

    base = base.copy()
    base["_order"] = base["year"] * 1000 + base["round"]

    # Pass 1: same-year previous round (round 1 gets no match here).
    prior_order = base["_order"] - 1  # round>=2; round 1 lands on year*1000 (absent)
    joined = snap_i.reindex(
        pd.MultiIndex.from_arrays([base[id_col], prior_order])
    )
    base[pos_out] = joined["pos"].to_numpy(dtype=float)
    base[ratio_out] = joined["ratio"].to_numpy(dtype=float)

    # Pass 2: round-1 rows take the previous season's FINAL standings.
    r1 = (base["round"] == 1).to_numpy()
    if r1.any():
        finals = (
            snap.sort_values("_order")
            .groupby([id_col, "year"], as_index=False)
            .tail(1)  # each entity's last snapshot within each season
            .set_index([id_col, "year"])
        )
        j = finals.reindex(
            pd.MultiIndex.from_arrays(
                [base.loc[r1, id_col], base.loc[r1, "year"] - 1]
            )
        )
        base.loc[r1, pos_out] = j["pos"].to_numpy(dtype=float)
        base.loc[r1, ratio_out] = j["ratio"].to_numpy(dtype=float)

    # Sentinels: no prior snapshot at all (first season's round 1, rookies,
    # entities missing from the table that round, unclassified "-").
    base[[pos_out, ratio_out]] = base[[pos_out, ratio_out]].fillna(
        {pos_out: NO_STANDING_POSITION, ratio_out: NO_STANDING_POINTS}
    )
    return base.drop(columns=["_order"])


def _rolling_driver_form(results: pd.DataFrame, window: int = RECENT_FORM_WINDOW) -> pd.Series:
    """
    Recent form per row: the driver's mean GRID->FINISH DELTA over their
    previous <=window races (strictly prior - the row's own race never
    counts). Delta = qualifying position - finishing position, so positive
    means the driver typically GAINS places on race day.

    Why a delta and not a raw mean finish: mean finish is highly redundant
    with quali_pos (drivers who qualify well finish well), so the raw form
    feature contributed only ~3% model importance. The delta measures
    something quali_pos CANNOT: race-day position changes independent of
    where the driver starts. First-ever race gets RECENT_FORM_PRIOR.
    """
    frame = results[["year", "round", "driverName", "quali_pos", "position"]].copy()
    frame["_delta"] = frame["quali_pos"] - frame["position"]
    frame["_order"] = frame["year"] * 1000 + frame["round"]

    per_race = (
        frame.groupby(["driverName", "_order"], as_index=False)["_delta"]
        .mean()
        .sort_values(["driverName", "_order"])
    )
    g = per_race.groupby("driverName", sort=False)
    per_race["prev"] = g["_delta"].shift(1)  # drop the race itself
    per_race["form"] = (
        per_race.groupby("driverName", sort=False)["prev"]
        .transform(lambda s: s.rolling(window, min_periods=1).mean())
        .fillna(RECENT_FORM_PRIOR)
    )

    out = frame[["driverName", "_order"]].merge(
        per_race[["driverName", "_order", "form"]],
        on=["driverName", "_order"], how="left",
    )
    return pd.Series(out["form"].to_numpy(), index=results.index)


def _rolling_constructor_form(results: pd.DataFrame, window: int = RECENT_FORM_WINDOW) -> pd.Series:
    """
    Constructor form per row: the team's mean RACE POINTS over its previous
    <=window races (strictly prior - the row's own race never counts).

    Why mean points rather than mean finish: a constructor fields two cars,
    so per-row mean finish double-counts and mixes entries; points are the
    official per-team outcome. Why not a championship ratio: the ratio is a
    season-cumulative number with heavy inertia - a mid-season upgrade
    shows up in the last-5-race points long before it moves the table.
    First-ever race gets CONSTRUCTOR_FORM_PRIOR.
    """
    frame = results[["year", "round", "constructorName", "points"]].copy()
    frame["_order"] = frame["year"] * 1000 + frame["round"]

    per_race = (
        frame.groupby(["constructorName", "_order"], as_index=False)["points"]
        .sum()  # team points = sum over its cars that race
        .sort_values(["constructorName", "_order"])
    )
    g = per_race.groupby("constructorName", sort=False)
    per_race["prev"] = g["points"].shift(1)  # drop the race itself
    per_race["form"] = (
        per_race.groupby("constructorName", sort=False)["prev"]
        .transform(lambda s: s.rolling(window, min_periods=1).mean())
        .fillna(CONSTRUCTOR_FORM_PRIOR)
    )

    out = frame[["constructorName", "_order"]].merge(
        per_race[["constructorName", "_order", "form"]],
        on=["constructorName", "_order"], how="left",
    )
    return pd.Series(out["form"].to_numpy(), index=results.index)


def _gap_to_pole(qualifying: pd.DataFrame) -> pd.Series:
    """
    Gap-to-pole per qualifying row, in SECONDS behind the session's fastest
    best time.

    A driver's best time is the fastest of their available Q1/Q2/Q3 laps (a
    driver eliminated in Q1 has only their Q1 lap). Gap = best - pole, so
    the pole sitter scores 0.0 and a backmarker's field spread is in
    seconds. Points-resolution companion to quali_pos: P3 who was 0.05s
    off pole and P3 who was 1.4s off are different situations that the
    ordinal position cannot distinguish.

    Point-in-time BY CONSTRUCTION: qualifying happens before the race, so
    same-session times are legitimately known at prediction time - no
    windowing needed. Drivers with no recorded time get that session's
    MEDIAN gap (same-session data, known pre-race; never the driver's own
    future results). A session with no times at all yields 0.0.
    """
    q = qualifying.copy()
    # tolerate missing session columns (some sources ship Q1 only)
    sessions = [c for c in ("Q1", "Q2", "Q3") if c in q.columns]
    if not sessions:
        return pd.Series(0.0, index=qualifying.index)
    best = pd.concat(
        [q[c].map(_lap_time_ms) for c in sessions], axis=1
    ).min(axis=1)  # min ignores NaN: fastest available session lap
    q["_best_ms"] = best
    pole_ms = q.groupby(["year", "round"])["_best_ms"].transform("min")
    gap = (q["_best_ms"] - pole_ms) / 1000.0
    # median of the session's known gaps, filled into no-time rows
    session_median = gap.groupby([q["year"], q["round"]]).transform("median")
    return gap.fillna(session_median).fillna(0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", default="./datasets")
    ap.add_argument("--out", default="./datasets")
    args = ap.parse_args()

    d = args.datasets
    results = pd.read_csv(f"{d}/results.csv")
    qualifying = pd.read_csv(f"{d}/qualifying.csv")
    driver_standings = pd.read_csv(f"{d}/driver_standings.csv")
    constructor_standings = pd.read_csv(f"{d}/constructor_standings.csv")

    # Jolpica writes position="-" for unclassified entries (e.g. 0-point
    # drivers before they score); treat those as "no snapshot" so the join
    # falls through to the sentinels instead of crashing or leaking text.
    for table in (driver_standings, constructor_standings):
        table["position"] = pd.to_numeric(table["position"], errors="coerce")

    # --- DNF flags from text status (+ cause split for the rate features) ---
    results["driver_dnf"] = results["status"].apply(is_dnf)
    results["dnf_is_mech"] = (results["status"].apply(dnf_cause) == "mech").astype(int)
    results["dnf_is_acc"] = (results["status"].apply(dnf_cause) == "driver").astype(int)

    # --- join qualifying position + gap-to-pole onto results ---
    # Gap-to-pole is point-in-time BY CONSTRUCTION: qualifying happens
    # before the race, so same-session times are legitimately known at
    # prediction time (no windowing needed, unlike every other feature).
    qualifying["gap_to_pole"] = _gap_to_pole(qualifying)
    quali_small = qualifying[["year", "round", "driverId", "position", "gap_to_pole"]].rename(
        columns={"position": "quali_pos"}
    )
    merged = results.merge(quali_small, on=["year", "round", "driverId"], how="inner")

    # --- point-in-time reliability (expanding window, strictly prior races) ---
    merged["driver_confidence"] = _expanding_reliability(merged, "driverName")
    merged["constructor_relaiblity"] = _expanding_reliability(merged, "constructorName")

    # --- DNF-cause split (expanding window, strictly prior races) ---
    # Mechanical failures belong to the CAR (constructor rate); accidents
    # and collisions belong to the DRIVER (racecraft rate). Each entity
    # only sees its own prior entries.
    merged["constructor_mech_dnf_rate"] = _expanding_dnf_rate(
        merged, "constructorName", "dnf_is_mech"
    )
    merged["driver_acc_dnf_rate"] = _expanding_dnf_rate(
        merged, "driverName", "dnf_is_acc"
    )

    # --- point-in-time championship standing (prior round / prev season final) ---
    # Points become share-of-leader WITHIN each snapshot (scale-invariant).
    drv_snap = driver_standings.rename(columns={"position": "pos", "points": "pts"})
    con_snap = constructor_standings.rename(columns={"position": "pos", "points": "pts"})
    for snap in (drv_snap, con_snap):
        leader = snap.groupby(["year", "round"])["pts"].transform("max")
        snap["ratio"] = (snap["pts"] / leader).fillna(0.0)
    merged = _attach_prior_standings(
        merged, "driverId", drv_snap, "driver_champ_pos", "driver_champ_points_ratio"
    )
    merged = _attach_prior_standings(
        merged, "constructorId", con_snap, "constructor_champ_pos", "constructor_champ_points_ratio"
    )

    # --- recent form: rolling last-N stats, strictly prior races ---
    # driver: mean grid->finish delta (race-day position changes, independent
    # of quali_pos); constructor: mean team points (reacts to upgrades faster
    # than the season-cumulative championship ratio).
    merged["driver_recent_form"] = _rolling_driver_form(merged)
    merged["constructor_recent_form"] = _rolling_constructor_form(merged)

    # --- current/active roster = whoever raced in the single most recent round ---
    latest_year = merged["year"].max()
    latest_round = merged[merged["year"] == latest_year]["round"].max()
    latest_race = merged[(merged["year"] == latest_year) & (merged["round"] == latest_round)]
    active_drivers = sorted(latest_race["driverName"].unique().tolist())
    active_constructors = sorted(latest_race["constructorName"].unique().tolist())

    merged["active_driver"] = merged["driverName"].isin(active_drivers).astype(int)
    merged["active_constructor"] = merged["constructorName"].isin(active_constructors).astype(int)

    # --- lifetime stats for the ROSTER (serving side only) ---
    # For a FUTURE race, "all data to date" is the correct point-in-time
    # value, so the roster keeps the lifetime formula.
    drv_dnf = results.groupby("driverName")["driver_dnf"].sum()
    drv_entered = results.groupby("driverName")["driver_dnf"].count()
    driver_confidence_lifetime = (1 - drv_dnf / drv_entered).to_dict()
    con_dnf = results.groupby("constructorName")["driver_dnf"].sum()
    con_entered = results.groupby("constructorName")["driver_dnf"].count()
    constructor_reliability_lifetime = (1 - con_dnf / con_entered).to_dict()

    # Lifetime DNF-cause rates for the ROSTER (serving side only): for a
    # FUTURE race, lifetime-to-date is the correct point-in-time value.
    # Rates are per ENTRY (driver-row), matching the training-side window.
    constructor_mech_rate_lifetime = results.groupby("constructorName")["dnf_is_mech"].mean().to_dict()
    driver_acc_rate_lifetime = results.groupby("driverName")["dnf_is_acc"].mean().to_dict()

    # Most recent championship snapshot (the standings entering the next,
    # not-yet-run race) - exactly what /predictGrid should send per row.
    # Points are exported as share-of-leader (scale-invariant), matching the
    # training features.
    drv_latest = (
        drv_snap[drv_snap["year"] == latest_year]
        .sort_values("round").groupby("driverId", as_index=False).tail(1)
    )
    con_latest = (
        con_snap[con_snap["year"] == latest_year]
        .sort_values("round").groupby("constructorId", as_index=False).tail(1)
    )
    latest_driver_meta = dict(zip(results[results["year"] == latest_year]["driverId"],
                                  results[results["year"] == latest_year]["driverName"]))
    latest_con_meta = dict(zip(results[results["year"] == latest_year]["constructorId"],
                               results[results["year"] == latest_year]["constructorName"]))

    # Gap-to-pole references for serving a FUTURE race: the per-GP median
    # gap of the latest season's sessions (track character - Monaco's field
    # spread differs from Monza's) and each driver's most recent actual gap.
    # app.py prefers a real session gap when the frontend sends one and
    # falls back to the per-GP median.
    recent_q = qualifying[qualifying["year"] == latest_year]
    round_to_gp = (results[results["year"] == latest_year]
                   .drop_duplicates("round").set_index("round")["raceName"])
    gp_median_gap = {round_to_gp[r]: float(v)
                     for r, v in recent_q.groupby("round")["gap_to_pole"].median().items()
                     if r in round_to_gp.index}
    latest_q = recent_q[recent_q["round"] == latest_round]
    driver_last_gap = {latest_driver_meta.get(d): float(g)
                       for d, g in zip(latest_q["driverId"], latest_q["gap_to_pole"])
                       if latest_driver_meta.get(d) in active_drivers}

    # Recent form as of the latest data - the point-in-time values for a
    # future race: driver = mean grid->finish delta over the last <=window
    # races; constructor = mean team points over its last <=window races.
    driver_delta = (merged["quali_pos"] - merged["position"]).rename("_delta")
    form_latest = (
        pd.concat([merged[["driverName", "year", "round"]], driver_delta], axis=1)
        .sort_values(["driverName", "year", "round"])
        .groupby("driverName")["_delta"].apply(lambda s: s.tail(RECENT_FORM_WINDOW).mean())
    )
    con_form_latest = (
        # race-level team points first: merged has one row PER DRIVER, and a
        # row-level tail(5) would average driver rows (half the team total)
        # across a mixed race window instead of the team's last N races.
        merged.groupby(["constructorName", "year", "round"], as_index=False)["points"]
        .sum()
        .sort_values(["constructorName", "year", "round"])
        .groupby("constructorName")["points"].apply(
            lambda s: s.tail(RECENT_FORM_WINDOW).mean()  # min_periods=1, like training
        )
    )

    cleaned = merged.rename(columns={
        "raceName": "GP_name",
        "constructorName": "constructor",
        "driverName": "driver",
    })[[
        "year", "round", "GP_name", "quali_pos", "gap_to_pole", "constructor", "driver", "position",
        "driver_confidence", "constructor_relaiblity",
        "driver_champ_pos", "driver_champ_points_ratio",
        "constructor_champ_pos", "constructor_champ_points_ratio",
        "driver_recent_form", "constructor_recent_form",
        "constructor_mech_dnf_rate", "driver_acc_dnf_rate",
        "active_driver", "active_constructor",
    ]]
    # newline/line-terminator pinned: platform defaults (Windows CRLF vs
    # Linux LF) made artifacts differ across machines and broke byte-level
    # drift checks in CI. Same lesson as the encoding pin below.
    cleaned.to_csv(f"{args.out}/cleaned_data.csv", index=False, lineterminator="\n")

    driver_team = dict(zip(latest_race["driverName"], latest_race["constructorName"]))

    roster = {
        "latest_year": int(latest_year),
        "latest_round": int(latest_round),
        "active_drivers": active_drivers,
        "active_constructors": active_constructors,
        "driver_team": driver_team,
        "driver_confidence": {k: v for k, v in driver_confidence_lifetime.items() if k in active_drivers},
        "constructor_reliability": {k: v for k, v in constructor_reliability_lifetime.items() if k in active_constructors},
        # championship snapshot entering the next race (point-in-time for serving);
        # points exported as share-of-leader to match the training features
        "driver_champ_pos": {latest_driver_meta[r.driverId]: float(r.pos)
                             for r in drv_latest.itertuples() if latest_driver_meta.get(r.driverId) in active_drivers},
        "driver_champ_points_ratio": {latest_driver_meta[r.driverId]: float(r.ratio)
                                      for r in drv_latest.itertuples() if latest_driver_meta.get(r.driverId) in active_drivers},
        "constructor_champ_pos": {latest_con_meta[r.constructorId]: float(r.pos)
                                  for r in con_latest.itertuples() if latest_con_meta.get(r.constructorId) in active_constructors},
        "constructor_champ_points_ratio": {latest_con_meta[r.constructorId]: float(r.ratio)
                                           for r in con_latest.itertuples() if latest_con_meta.get(r.constructorId) in active_constructors},
        # recent form entering the next race (point-in-time for serving):
        # driver grid->finish delta; constructor mean last-N team points
        "driver_recent_form": {k: float(v) for k, v in form_latest.items() if k in active_drivers},
        "constructor_recent_form": {k: float(v) for k, v in con_form_latest.items() if k in active_constructors},
        "constructor_mech_dnf_rate": {k: float(v) for k, v in constructor_mech_rate_lifetime.items() if k in active_constructors},
        "driver_acc_dnf_rate": {k: float(v) for k, v in driver_acc_rate_lifetime.items() if k in active_drivers},
        "gp_median_gap_to_pole": gp_median_gap,
        "driver_last_gap_to_pole": driver_last_gap,
    }
    # encoding pinned: locale defaults differ (Windows cp1252 vs Linux
    # utf-8) and produced artifacts CI could not decode. Never rely on it.
    with open(f"{args.out}/current_roster.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(roster, f, indent=2, ensure_ascii=False)

    print(f"cleaned_data.csv: {len(cleaned)} rows")
    print(f"Most recent race in data: {latest_year} round {latest_round}")
    print(f"Active drivers ({len(active_drivers)}), constructors ({len(active_constructors)})")
    print("Features are point-in-time: expanding reliability + prior-round standings")
    print("+ rolling driver delta / constructor points form + DNF-cause rates.")


if __name__ == "__main__":
    main()
