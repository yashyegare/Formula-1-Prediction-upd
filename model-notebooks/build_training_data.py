"""
build_training_data.py

Rebuilds cleaned_data.csv (the file prediction_iter1.ipynb trains on) from
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
  - Constructor identity is NOT collapsed across rebrands (the original
    code mapped both 'Racing Point' AND the *current* 'Aston Martin' to
    'Racing Point', silently erasing today's team name). Each
    constructor name from the data is kept as its own label.

Usage:
    python build_training_data.py --datasets ./datasets --out ./datasets
"""
import argparse
import pandas as pd

# Statuses that count as "classified / finished" (not a DNF)
FINISHED_STATUSES = {"Finished", "Lapped"}


def is_dnf(status: str) -> int:
    if status in FINISHED_STATUSES:
        return 0
    if isinstance(status, str) and status.startswith("+"):  # "+1 Lap", "+2 Laps", ...
        return 0
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", default="./datasets")
    ap.add_argument("--out", default="./datasets")
    args = ap.parse_args()

    d = args.datasets
    results = pd.read_csv(f"{d}/results.csv")
    qualifying = pd.read_csv(f"{d}/qualifying.csv")

    # --- DNF flags from text status ---
    results["driver_dnf"] = results["status"].apply(is_dnf)

    # --- driver_confidence: 1 - (DNFs / races entered), per driver ---
    drv_dnf = results.groupby("driverName")["driver_dnf"].sum()
    drv_entered = results.groupby("driverName")["driver_dnf"].count()
    driver_confidence = (1 - drv_dnf / drv_entered).to_dict()

    # --- constructor_reliability: same formula, per constructor ---
    con_dnf = results.groupby("constructorName")["driver_dnf"].sum()
    con_entered = results.groupby("constructorName")["driver_dnf"].count()
    constructor_reliability = (1 - con_dnf / con_entered).to_dict()

    # --- join qualifying position onto results (year, round, driverId) ---
    quali_small = qualifying[["year", "round", "driverId", "position"]].rename(
        columns={"position": "quali_pos"}
    )
    merged = results.merge(quali_small, on=["year", "round", "driverId"], how="inner")

    merged["driver_confidence"] = merged["driverName"].map(driver_confidence)
    merged["constructor_relaiblity"] = merged["constructorName"].map(constructor_reliability)

    # --- current/active roster = whoever raced in the single most recent round ---
    latest_year = merged["year"].max()
    latest_round = merged[merged["year"] == latest_year]["round"].max()
    latest_race = merged[(merged["year"] == latest_year) & (merged["round"] == latest_round)]
    active_drivers = sorted(latest_race["driverName"].unique().tolist())
    active_constructors = sorted(latest_race["constructorName"].unique().tolist())

    merged["active_driver"] = merged["driverName"].isin(active_drivers).astype(int)
    merged["active_constructor"] = merged["constructorName"].isin(active_constructors).astype(int)

    cleaned = merged.rename(columns={
        "raceName": "GP_name",
        "constructorName": "constructor",
        "driverName": "driver",
    })[[
        "GP_name", "quali_pos", "constructor", "driver", "position",
        "driver_confidence", "constructor_relaiblity",
        "active_driver", "active_constructor",
    ]]

    cleaned.to_csv(f"{args.out}/cleaned_data.csv", index=False)

    # driver -> current team, straight from the most recent race actually run
    driver_team = dict(zip(latest_race["driverName"], latest_race["constructorName"]))

    # also dump the current-season roster + stats for the app/frontend rebuild
    roster = {
        "latest_year": int(latest_year),
        "latest_round": int(latest_round),
        "active_drivers": active_drivers,
        "active_constructors": active_constructors,
        "driver_team": driver_team,
        "driver_confidence": {k: v for k, v in driver_confidence.items() if k in active_drivers},
        "constructor_reliability": {k: v for k, v in constructor_reliability.items() if k in active_constructors},
    }
    import json
    with open(f"{args.out}/current_roster.json", "w") as f:
        json.dump(roster, f, indent=2)

    print(f"cleaned_data.csv: {len(cleaned)} rows")
    print(f"Most recent race in data: {latest_year} round {latest_round}")
    print(f"Active drivers ({len(active_drivers)}): {active_drivers}")
    print(f"Active constructors ({len(active_constructors)}): {active_constructors}")
    print("\nDriver confidence (active only):")
    for k, v in roster["driver_confidence"].items():
        print(f"  {k}: {v:.3f}")
    print("\nConstructor reliability (active only):")
    for k, v in roster["constructor_reliability"].items():
        print(f"  {k}: {v:.3f}")


if __name__ == "__main__":
    main()