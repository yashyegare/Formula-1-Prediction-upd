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

# Street circuits in the 2018-2026 calendar, keyed by circuitId. Wall
# proximity compresses the quali/pace relationship, punishes mistakes and
# raises attrition - a coarse track-character signal that the label-encoded
# GP_name (37 categories, ~1% importance) fails to give the model. Miami is
# deliberately 0: a permanent-section hybrid, not unambiguously a street
# race. Keyed by circuitId (not race name) so renames cannot break it.
STREET_CIRCUITS = {"monaco", "baku", "singapore", "jeddah", "las_vegas"}


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


# Priors for the pace/pit features when no history exists yet (first-ever
# race, or the laps/pitstops data is absent). Fixed neutral constants -
# never derived from data that could leak. 0.0 = "no pace/pit signal": for
# the pace delta it is genuinely neutral; for pit TIME it understates
# (0s is fast) but only applies to a first-ever row with no data at all.
LAP_PACE_PRIOR = 0.0
PIT_TIME_PRIOR = 0.0


def _duration_to_s(value) -> float | None:
    """Parse a pit-stop duration to seconds. Accepts numeric values
    (pandas parses "22.213" columns as float64) and "M:SS.m" / "SS.m"
    strings (slow stops with a minute component). None if unusable."""
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


def _rolling_lap_pace(results: pd.DataFrame, laps: pd.DataFrame | None,
                      window: int = RECENT_FORM_WINDOW) -> pd.Series:
    """
    Lap-pace signal per results row: the driver's mean DELTA to the field's
    median lap time over their previous <=window races (strictly prior -
    the row's own race never counts).

    Design notes:
      - Delta is per-lap (driver lap ms - race median lap ms), MEDIANed per
        race first. Per-race median is robust to pit laps, traffic, and
        fuel-load trends inside a single race.
      - Mean over the last <=window races then smooths single-race noise.
      - Deltas, not raw lap times: raw lap times are track- and year-
        specific (Monza vs Monaco, 2018 vs 2026 cars); delta-to-field is
        comparable across every circuit and season.
      - DNF'd entries are EXCLUDED from their own lap sample (a truncated
        race under-represents pace); the race median still uses all laps.
    First-ever race (or missing laps data) gets LAP_PACE_PRIOR. Returns
    SECONDS relative to the field median (positive = slower than field).
    """
    if laps is None or laps.empty:
        return pd.Series(LAP_PACE_PRIOR, index=results.index)
    laps = laps.dropna(subset=["milliseconds"]).copy()
    if laps.empty:
        return pd.Series(LAP_PACE_PRIOR, index=results.index)

    # field median over ALL laps (before any DNF drops)
    med = laps.groupby(["year", "round"])["milliseconds"].median().rename("_race_med")
    laps = laps.merge(med, left_on=["year", "round"], right_index=True, how="left")
    laps["_lap_delta"] = laps["milliseconds"] - laps["_race_med"]

    # A driver's laps in a race they DNF'd are excluded from their OWN
    # sample (per-race, not globally), but the race keeps a NaN row in the
    # per-race sequence: rolling().mean() skips NaNs, so the window counts
    # only races with usable laps AND the next race still inherits prior
    # values through the shift.
    dnf_keys = results.loc[results["driver_dnf"] == 1, ["driverId", "year", "round"]].copy()
    dnf_keys["_is_dnf"] = 1
    laps = laps.merge(dnf_keys, on=["driverId", "year", "round"], how="left")
    finished_laps = laps[laps["_is_dnf"] != 1]
    per_race = (
        finished_laps.groupby(["driverId", "year", "round"], as_index=False)["_lap_delta"]
        .median()
    )
    # re-add every (driver, race) the driver entered but has no usable laps
    # for (DNF'd or absent from the laps data) as NaN rows
    entered = results[["driverId", "year", "round"]].drop_duplicates()
    per_race = entered.merge(per_race, on=["driverId", "year", "round"], how="left")
    per_race = per_race.sort_values(["driverId", "year", "round"])
    g = per_race.groupby("driverId", sort=False)
    per_race["prev"] = g["_lap_delta"].shift(1)  # drop the race itself
    per_race["pace"] = (
        per_race.groupby("driverId", sort=False)["prev"]
        .transform(lambda s: s.rolling(window, min_periods=1).mean())
    ) / 1000.0  # ms -> seconds

    out = results[["driverId"]].copy()
    out["_order"] = results["year"] * 1000 + results["round"]
    per_race["_order"] = per_race["year"] * 1000 + per_race["round"]
    out = out.merge(per_race[["driverId", "_order", "pace"]],
                    on=["driverId", "_order"], how="left")
    return pd.Series(out["pace"].fillna(LAP_PACE_PRIOR).to_numpy(), index=results.index)


def _rolling_pit_time(results: pd.DataFrame, pitstops: pd.DataFrame | None,
                      window: int = RECENT_FORM_WINDOW) -> pd.Series:
    """
    Pit-crew execution signal per results row: the CONSTRUCTOR's mean
    median pit-stop duration over its previous <=window races (strictly
    prior - the row's own race never counts).

    Per-race MEDIAN stop time is robust to outlier stops (slow repairs,
    penalties); the mean over the last <=window races smooths noise. Crew
    performance is a team attribute (the pit crew, not the driver), so the
    feature is attached to the constructor. Deltas are unnecessary: stop
    durations are roughly comparable across circuits/seasons (same task),
    unlike lap times. First-ever race (or missing pitstop data) gets
    PIT_TIME_PRIOR. Returns SECONDS.
    """
    if pitstops is None or pitstops.empty:
        return pd.Series(PIT_TIME_PRIOR, index=results.index)
    stops = pitstops.copy()
    stops["_dur"] = stops["duration"].map(_duration_to_s)
    stops = stops.dropna(subset=["_dur"])
    if stops.empty:
        return pd.Series(PIT_TIME_PRIOR, index=results.index)

    # Jolpica pitstops carry driverId only - map each stop to the
    # constructor via that race's results (drivers change teams across years)
    stops = stops.merge(
        results[["year", "round", "driverId", "constructorId"]].drop_duplicates(),
        on=["year", "round", "driverId"], how="left",
    )

    per_race = (
        stops.groupby(["constructorId", "year", "round"], as_index=False)["_dur"]
        .median()
        .sort_values(["constructorId", "year", "round"])
    )
    g = per_race.groupby("constructorId", sort=False)
    per_race["prev"] = g["_dur"].shift(1)  # drop the race itself
    per_race["pit"] = (
        per_race.groupby("constructorId", sort=False)["prev"]
        .transform(lambda s: s.rolling(window, min_periods=1).mean())
    )

    out = results[["constructorId"]].copy()
    out["_order"] = results["year"] * 1000 + results["round"]
    per_race["_order"] = per_race["year"] * 1000 + per_race["round"]
    out = out.merge(per_race[["constructorId", "_order", "pit"]],
                    on=["constructorId", "_order"], how="left")
    return pd.Series(out["pit"].fillna(PIT_TIME_PRIOR).to_numpy(), index=results.index)


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
    races = pd.read_csv(f"{d}/races.csv")

    # Laps / pit stops from fetch_lap_pace.py. Tolerant load: the feature
    # is skipped (neutral prior) if the fetch has not run yet, so the
    # pipeline never hard-depends on the multi-hour fetch being complete.
    try:
        laps = pd.read_csv(f"{d}/lap_times_jolpica.csv")
    except (OSError, pd.errors.EmptyDataError):
        laps = None
    try:
        pitstops = pd.read_csv(f"{d}/pit_stops_jolpica.csv")
    except (OSError, pd.errors.EmptyDataError):
        pitstops = None

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

    # --- pace & execution: rolling lap-pace delta (driver) and pit-stop
    # time (constructor), strictly prior races. Both tolerate absent data
    # (neutral prior) until the fetch_lap_pace run completes.
    merged["lap_pace_delta_s"] = _rolling_lap_pace(merged, laps)
    merged["constructor_pit_time_s"] = _rolling_pit_time(merged, pitstops)

    # --- track character: street-circuit flag (known pre-race) ---
    circuit_is_street = dict.fromkeys(races["circuitId"].unique(), 0)
    for cid in STREET_CIRCUITS:
        if cid in circuit_is_street:
            circuit_is_street[cid] = 1
    race_circuit = races.set_index(["year", "round"])["circuitId"]
    merged["is_street_circuit"] = [
        circuit_is_street[race_circuit.loc[(y, r)]]
        for y, r in zip(merged["year"], merged["round"])
    ]

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

    # Pace & pit references for serving a FUTURE race: each driver's /
    # constructor's mean over their last <=window races (all data to date
    # is the correct point-in-time value for a future race; the driver's
    # DNF'd races are excluded from their lap sample, matching training).
    # Empty dicts when the lap/pit data is absent - app.py then falls back
    # to the fixed priors, keeping the serving contract total.
    driver_id_to_name = dict(results[["driverId", "driverName"]].drop_duplicates().to_numpy())
    constructor_id_to_name = dict(results[["constructorId", "constructorName"]].drop_duplicates().to_numpy())
    pace_latest = {}
    if laps is not None and not laps.empty:
        l = laps.dropna(subset=["milliseconds"]).copy()
        med = l.groupby(["year", "round"])["milliseconds"].median()
        l = l.merge(med.rename("_race_med"), left_on=["year", "round"],
                    right_index=True, how="left")
        l["_lap_delta"] = (l["milliseconds"] - l["_race_med"]) / 1000.0
        # per-race DNF exclusion (same contract as training: a driver's laps
        # are dropped only in races they DNF'd, never globally)
        dnf_keys = results.loc[results["driver_dnf"] == 1, ["driverId", "year", "round"]].copy()
        dnf_keys["_is_dnf"] = 1
        l = l.merge(dnf_keys, on=["driverId", "year", "round"], how="left")
        l = l[l["_is_dnf"] != 1]
        pace_latest = {
            driver_id_to_name[k]: float(v)
            for k, v in (l.groupby(["driverId", "year", "round"], as_index=False)["_lap_delta"]
                         .median()
                         .sort_values(["driverId", "year", "round"])
                         .groupby("driverId")["_lap_delta"]
                         .apply(lambda s: s.tail(RECENT_FORM_WINDOW).mean())
                         .to_dict()).items()
            if k in driver_id_to_name
        }
    pit_latest = {}
    if pitstops is not None and not pitstops.empty:
        s = pitstops.copy()
        s["_dur"] = s["duration"].map(_duration_to_s)
        s = s.dropna(subset=["_dur"])
        # driver->constructor mapping per race (pitstops carry driverId only)
        s = s.merge(
            results[["year", "round", "driverId", "constructorId"]].drop_duplicates(),
            on=["year", "round", "driverId"], how="left",
        )
        pit_latest = {
            constructor_id_to_name[k]: float(v)
            for k, v in (s.groupby(["constructorId", "year", "round"], as_index=False)["_dur"]
                         .median()
                         .sort_values(["constructorId", "year", "round"])
                         .groupby("constructorId")["_dur"]
                         .apply(lambda s: s.tail(RECENT_FORM_WINDOW).mean())
                         .to_dict()).items()
            if k in constructor_id_to_name
        }

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
        "lap_pace_delta_s", "constructor_pit_time_s",
        "constructor_mech_dnf_rate", "driver_acc_dnf_rate",
        "is_street_circuit",
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
        # pace & execution entering the next race (point-in-time for serving)
        "driver_lap_pace_delta_s": {k: v for k, v in pace_latest.items() if k in active_drivers},
        "constructor_pit_time_s": {k: v for k, v in pit_latest.items() if k in active_constructors},
        "constructor_mech_dnf_rate": {k: float(v) for k, v in constructor_mech_rate_lifetime.items() if k in active_constructors},
        "driver_acc_dnf_rate": {k: float(v) for k, v in driver_acc_rate_lifetime.items() if k in active_drivers},
        # street-circuit flag keyed by RACE NAME for serving (app.py looks
        # rows up by the GP name the frontend sends)
        "gp_is_street": {
            round_to_gp[r]: int(circuit_is_street.get(cid, 0))
            for r, cid in races[races["year"] == latest_year]
            .set_index("round")["circuitId"].items()
            if r in round_to_gp.index
        },
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
    print("+ rolling driver delta / constructor points form + DNF-cause rates")
    print("+ street-circuit flag + lap-pace delta / pit-stop time.")


if __name__ == "__main__":
    main()
