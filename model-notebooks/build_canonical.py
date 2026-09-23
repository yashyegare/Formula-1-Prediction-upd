"""
build_canonical.py — build the canonical F1 data platform (Phase 2).

Loads the committed datasets/*.csv into the STRICT SQLite schema defined in
canonical_schema.sql, runs validation gates BEFORE committing anything, and
stamps a deterministic build_manifest.json (source hashes, row counts,
per-table deltas, git SHA) that CI byte-compares on every push — the same
drift-guard contract the ML pipeline applies to cleaned_data.csv and
current_roster.json.

Why a strict typed DB instead of more CSVs: the Phase-1 decomposition ran
on DataFrames whose join keys were correct only because a human checked
them (and one bug — a quali lookup keyed without year — survived two code
reviews). The canonical model makes the keys structural: PRIMARY KEYs on
(year, round, driverId...), FOREIGN KEYs to the race, CHECKs on buckets
and causes, and status as a first-class dimension so the 2026 generic-
status regression ("Retired" everywhere) is visible as data, not folklore.

Natural keys, no surrogates: (year, round) identifies a race and
(year, round, driverId) an entry — the same keys cleaned_data.csv,
backtest_wf.py and error_decomposition.py already join on.

Usage:
    python build_canonical.py --datasets ./datasets \
        --schema canonical_schema.sql --db ./datasets/f1_canonical.db \
        --manifest ./datasets/build_manifest.json
"""
import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd

from build_training_data import (  # single source of truth for the taxonomy
    _duration_to_s,
    _gap_to_pole,
    _lap_time_ms,
    dnf_cause,
    is_dnf,
)

# Views to count in the manifest (no timestamps anywhere — byte-stable).
COUNT_VIEWS = [
    "v_race_lap_evidence",
    "v_race_sc_exposure",
    "v_running_position_gains",
    "v_driver_race_evidence",
    "v_race_entry_outcome",
]

TABLES = [
    "dim_driver", "dim_constructor", "dim_circuit", "dim_status",
    "fact_race", "fact_quali_entry", "fact_race_entry", "fact_lap",
    "fact_pit_stop", "fact_championship_snapshot",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


class ValidationError(RuntimeError):
    """Raised when a validation gate fails — nothing gets committed."""


def _require_unique(df: pd.DataFrame, cols: list[str], label: str) -> None:
    dups = df.duplicated(subset=cols).sum()
    if dups:
        raise ValidationError(f"{label}: {dups} duplicate rows on key {cols}")


def _require_fk(child: pd.DataFrame, child_col: str,
                parent_keys: set, label: str) -> None:
    missing = ~child[child_col].isin(parent_keys)
    if missing.any():
        bad = child.loc[missing, child_col].unique()[:5]
        raise ValidationError(f"{label}: {missing.sum()} rows with {child_col} "
                              f"not in parent ({list(bad)}...)")


def _lap_ms(value) -> float | None:
    ms = _lap_time_ms(value)
    return None if ms is None else float(ms)


def load_dims(d: str, result_statuses: list[str] | None = None) -> dict[str, pd.DataFrame]:
    drivers = pd.read_csv(f"{d}/drivers.csv", keep_default_na=False)
    constructors = pd.read_csv(f"{d}/constructors.csv", keep_default_na=False)
    circuits = pd.read_csv(f"{d}/circuits.csv", keep_default_na=False)
    # dim_status derives from the status vocabulary ACTUALLY PRESENT in
    # results.csv (deterministic IDs by sorted text), not from the legacy
    # Ergast-era status.csv: Jolpica writes status text directly and its
    # vocabulary diverges from the old numeric dimension ("Cooling system",
    # "Debris", "Illness", "Did not start" have no status.csv row).
    # is_dnf / dnf_cause come from the ONE shared taxonomy
    # (build_training_data), so the dimension cannot drift from what the
    # model treats as a DNF cause. A newly appearing upstream status
    # changes the dimension and the manifest — visible in CI, not silent.
    statuses = sorted(set(result_statuses or []))
    status = pd.DataFrame({
        "statusId": range(1, len(statuses) + 1),
        "status": statuses,
        "is_dnf": [is_dnf(s) for s in statuses],
        "dnf_cause": [dnf_cause(s) for s in statuses],
    }).replace({"dnf_cause": {"none": None}})
    return {
        "dim_driver": drivers,
        "dim_constructor": constructors,
        "dim_circuit": circuits,
        "dim_status": status,
    }


def load_facts(d: str, dims: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    races = pd.read_csv(f"{d}/races.csv")
    quali = pd.read_csv(f"{d}/qualifying.csv")
    results = pd.read_csv(f"{d}/results.csv")
    laps = pd.read_csv(f"{d}/lap_times_jolpica.csv")
    pitstops = pd.read_csv(f"{d}/pit_stops_jolpica.csv")
    drv_stand = pd.read_csv(f"{d}/driver_standings.csv")
    con_stand = pd.read_csv(f"{d}/constructor_standings.csv")

    # ── pre-insert structural validation ───────────────────────────────
    race_keys = set(zip(races["year"], races["round"]))
    _require_unique(races, ["year", "round"], "races.csv")
    _require_unique(quali, ["year", "round", "driverId"], "qualifying.csv")
    _require_unique(results, ["year", "round", "driverId"], "results.csv")
    _require_unique(laps, ["year", "round", "lap", "driverId"],
                    "lap_times_jolpica.csv")
    _require_unique(pitstops, ["year", "round", "driverId", "stop"],
                    "pit_stops_jolpica.csv")
    for name, stand, id_col in (("driver_standings.csv", drv_stand, "driverId"),
                                ("constructor_standings.csv", con_stand,
                                 "constructorId")):
        _require_unique(stand, ["year", "round", id_col], name)
    _require_fk(quali.assign(k=list(zip(quali["year"], quali["round"]))),
                "k", race_keys, "qualifying.csv race ref")
    _require_fk(results.assign(k=list(zip(results["year"], results["round"]))),
                "k", race_keys, "results.csv race ref")
    _require_fk(laps.assign(k=list(zip(laps["year"], laps["round"]))),
                "k", race_keys, "lap_times_jolpica.csv race ref")
    _require_fk(pitstops.assign(k=list(zip(pitstops["year"], pitstops["round"]))),
                "k", race_keys, "pit_stops_jolpica.csv race ref")
    _require_fk(drv_stand.assign(k=list(zip(drv_stand["year"], drv_stand["round"]))),
                "k", race_keys, "driver_standings.csv race ref")
    _require_fk(con_stand.assign(k=list(zip(con_stand["year"], con_stand["round"]))),
                "k", race_keys, "constructor_standings.csv race ref")

    circuit_ids = set(dims["dim_circuit"]["circuitId"])
    _require_fk(races.assign(k=races["circuitId"]), "k", circuit_ids,
                "races.csv circuit ref")
    driver_ids = set(dims["dim_driver"]["driverId"])
    for name, df in (("qualifying.csv", quali), ("results.csv", results),
                     ("lap_times_jolpica.csv", laps),
                     ("pit_stops_jolpica.csv", pitstops)):
        _require_fk(df.assign(k=df["driverId"]), "k", driver_ids,
                    f"{name} driver ref")
    constructor_ids = set(dims["dim_constructor"]["constructorId"])
    _require_fk(quali.assign(k=quali["constructorId"]), "k", constructor_ids,
                "qualifying.csv constructor ref")
    _require_fk(results.assign(k=results["constructorId"]), "k", constructor_ids,
                "results.csv constructor ref")

    # results positions must be a strict DNF-safe order within a race
    # (Jolpica contract the training target depends on). Qualifying MAY
    # carry tied positions — penalty-tied classifications are real
    # upstream semantics (e.g. Perez/Bottas both P15, 2023 Spa; Sainz/
    # Albon both P10, 2024 Monza) — so no uniqueness gate there.
    pos = results[results["position"].notna()]
    duppos = pos.duplicated(subset=["year", "round", "position"]).sum()
    if duppos:
        raise ValidationError(f"results.csv: {duppos} duplicate positions "
                              f"within the same race")

    # ── shape the facts ────────────────────────────────────────────────
    fact_quali = quali.copy()
    for col in ("Q1", "Q2", "Q3"):
        fact_quali[col.lower() + "_ms"] = fact_quali[col].map(_lap_ms)
    fact_quali["gap_to_pole_s"] = _gap_to_pole(quali)

    status_ids = dict(zip(dims["dim_status"]["status"], dims["dim_status"]["statusId"]))
    unknown = set(results["status"]) - set(status_ids)
    if unknown:
        raise ValidationError(f"results.csv statuses missing from status.csv "
                              f"dimension: {sorted(unknown)[:5]}")
    fact_entry = pd.DataFrame({
        "year": results["year"], "round": results["round"],
        "driverId": results["driverId"],
        "constructorId": results["constructorId"],
        "grid": pd.to_numeric(results["grid"], errors="coerce"),
        "position": pd.to_numeric(results["position"], errors="coerce"),
        # Ergast-era rows carry TEXT classification markers ("R"/"D") in
        # positionOrder; Jolpica-era rows are numeric. Markers -> NULL:
        # the DNF-safe order lives in `position` (the training contract).
        "positionOrder": pd.to_numeric(results["positionOrder"], errors="coerce"),
        "points": results["points"], "laps": results["laps"],
        "statusId": results["status"].map(status_ids),
        "is_dnf": results["status"].apply(is_dnf),
        "dnf_cause": results["status"].apply(dnf_cause).replace({"none": None}),
    })

    fact_lap = pd.DataFrame({
        "year": laps["year"], "round": laps["round"], "lap": laps["lap"],
        "driverId": laps["driverId"], "position": laps["position"],
        "time_str": laps["time"], "milliseconds": laps["milliseconds"],
    })

    fact_pit = pd.DataFrame({
        "year": pitstops["year"], "round": pitstops["round"],
        "driverId": pitstops["driverId"], "lap": pitstops["lap"],
        "stop": pitstops["stop"],
        "duration_s": pitstops["duration"].map(_duration_to_s),
    })

    # Standings: kind-discriminated snapshots. Position '-' (unclassified)
    # coerces to NULL, matching build_training_data's to_numeric coercion.
    def snap(df: pd.DataFrame, kind: str, id_col: str) -> pd.DataFrame:
        pos = pd.to_numeric(df["position"], errors="coerce")
        return pd.DataFrame({
            "year": df["year"], "round": df["round"], "kind": kind,
            "entity_id": df[id_col], "points": df["points"],
            "wins": pd.to_numeric(df["wins"], errors="coerce"),
            "position": pos,
        })

    fact_snap = pd.concat([
        snap(drv_stand, "driver", "driverId"),
        snap(con_stand, "constructor", "constructorId"),
    ], ignore_index=True)

    facts = {
        "fact_race": races[["year", "round", "circuitId", "name", "date", "time"]],
        "fact_quali_entry": fact_quali[["year", "round", "driverId",
                                        "constructorId", "position",
                                        "q1_ms", "q2_ms", "q3_ms",
                                        "gap_to_pole_s"]],
        "fact_race_entry": fact_entry,
        "fact_lap": fact_lap,
        "fact_pit_stop": fact_pit,
        "fact_championship_snapshot": fact_snap,
    }
    return facts


def write_db(db_path: str, schema_path: str,
             dims: dict[str, pd.DataFrame],
             facts: dict[str, pd.DataFrame]) -> None:
    Path(db_path).unlink(missing_ok=True)  # rebuild is always from scratch
    con = sqlite3.connect(db_path)
    try:
        con.executescript(Path(schema_path).read_text(encoding="utf-8"))
        for table in TABLES:
            df = dims.get(table, facts.get(table))
            if df is None:
                raise ValidationError(f"no data produced for {table}")
            if len(df) == 0:
                raise ValidationError(f"{table}: loader produced 0 rows")
            df.to_sql(table, con, if_exists="append", index=False)
        con.commit()
        # post-insert integrity gates
        fk_bad = con.execute("PRAGMA foreign_key_check").fetchall()
        if fk_bad:
            raise ValidationError(f"foreign key violations: {fk_bad[:5]}")
        int_bad = con.execute("PRAGMA integrity_check").fetchone()[0]
        if int_bad != "ok":
            raise ValidationError(f"integrity_check: {int_bad}")
    finally:
        con.close()


def count_rows(db_path: str) -> dict[str, int]:
    con = sqlite3.connect(db_path)
    try:
        counts = {}
        for t in TABLES:
            counts[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for v in COUNT_VIEWS:
            counts[v] = con.execute(f"SELECT COUNT(*) FROM {v}").fetchone()[0]
        return counts
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser(description="Build the canonical F1 database")
    ap.add_argument("--datasets", default="./datasets")
    ap.add_argument("--schema", default="canonical_schema.sql")
    ap.add_argument("--db", default="./datasets/f1_canonical.db")
    ap.add_argument("--manifest", default="./datasets/build_manifest.json")
    args = ap.parse_args()

    d = args.datasets
    print("Loading dimensions...")
    # dim_status derives from the vocabulary present in results.csv
    res_probe = pd.read_csv(f"{d}/results.csv")
    dims = load_dims(d, res_probe["status"].dropna().astype(str).unique().tolist())
    print("Loading facts + validation gates...")
    facts = load_facts(d, dims)

    print("Writing database...")
    write_db(args.db, args.schema, dims, facts)

    counts = count_rows(args.db)
    # Manifest covers every source the loader reads that actually exists
    # (status.csv is legacy Ergast-era and no longer consumed).
    SOURCES = ["drivers.csv", "constructors.csv", "circuits.csv",
               "races.csv", "qualifying.csv", "results.csv",
               "lap_times_jolpica.csv", "pit_stops_jolpica.csv",
               "driver_standings.csv", "constructor_standings.csv"]
    src = {}
    for name in SOURCES:
        p = Path(d) / name
        if not p.exists():
            raise ValidationError(f"source file missing: {p}")
        src[name] = {"sha256": sha256(p),
                     "rows": sum(1 for _ in open(p, encoding="utf-8")) - 1}

    # The manifest FILE contains only source hashes + row counts — nothing
    # path-dependent, no timestamps, no git SHAs, and NO comparison state.
    # (delta_vs_previous/changed_sources were originally written into the
    # file; that made the byte-compare drift-guard impossible, since a
    # fresh rebuild with no previous manifest at the output path could
    # never match a committed copy that carried those keys.) The manifest
    # must be byte-identical across rebuilds from the same sources, so CI
    # can byte-compare it against the committed baseline.
    manifest = {"sources": src, "canonical": counts}
    m_path = Path(args.manifest)
    # Deltas vs the PREVIOUS manifest are a stdout report for humans, never
    # persisted into the file.
    if m_path.exists():
        prev = json.loads(m_path.read_text(encoding="utf-8"))
        deltas = {t: counts[t] - prev.get("canonical", {}).get(t, 0)
                  for t in counts}
        changed = sorted(k for k in src
                         if prev.get("sources", {}).get(k, {}).get("sha256")
                         != src[k]["sha256"])
        print("Deltas vs previous manifest:")
        for t, dv in deltas.items():
            if dv:
                print(f"  {t:32s} {dv:+d}")
        if changed:
            print(f"  changed sources: {', '.join(changed)}")
        if not any(deltas.values()) and not changed:
            print("  (no changes)")

    # byte-stable serialization: sorted keys, fixed separators, LF, UTF-8
    m_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8", newline="\n")
    total = sum(counts[t] for t in TABLES)
    print(f"\nCanonical DB: {args.db} ({total:,} fact+dim rows, "
          f"{len(TABLES)} tables, {len(COUNT_VIEWS)} views)")
    print(f"Manifest: {args.manifest}")


if __name__ == "__main__":
    main()
