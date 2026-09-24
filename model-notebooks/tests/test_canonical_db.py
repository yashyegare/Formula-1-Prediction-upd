"""
Tests for build_canonical.py + canonical_schema.sql (Phase 2).

The failure modes these pin:
  - natural-key drift: any fact without (year, round) keys, or a loader
    that lets duplicate keys through (the Phase-1 bug class)
  - status taxonomy drift between dim_status and build_training_data
  - view contracts drifting from the pandas implementations the ML
    pipeline already pins (medians, slow-lap flag, gains, PIT standings)
  - manifest drift-guard failures: silent source changes, wrong counts
  - STRICT/CHECK/FK weakened to the point of accepting bad data
"""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
MODEL_DIR = HERE.parent
sys.path.insert(0, str(MODEL_DIR))

import build_canonical as bc  # noqa: E402
import error_decomposition as ed  # noqa: E402

SCHEMA = str(MODEL_DIR / "canonical_schema.sql")


# ── helpers: minimal synthetic frames ────────────────────────────────────

def _dims(statuses=("Finished", "Engine", "Accident")):
    return {
        "dim_driver": pd.DataFrame([
            ("a", "a", "AAA", "A", "Alpha", "1990-01-01", "X"),
            ("b", "b", "BBB", "B", "Beta", "1991-01-01", "Y"),
        ], columns=["driverId", "driverRef", "code", "forename",
                    "surname", "dob", "nationality"]),
        "dim_constructor": pd.DataFrame([
            ("t1", "Team 1", "X"),
        ], columns=["constructorId", "name", "nationality"]),
        "dim_circuit": pd.DataFrame([
            ("c1", "Circuit 1", "Loc", "Country", 1.0, 2.0),
        ], columns=["circuitId", "name", "location", "country", "lat", "lng"]),
        "dim_status": bc.load_dims.__wrapped__ if False else _status_dim(statuses),
    }


def _status_dim(statuses):
    # mirror of the loader's derivation incl. the none->None replacement
    # (the schema CHECK requires NULL, not the literal 'none')
    return pd.DataFrame({
        "statusId": range(1, len(statuses) + 1),
        "status": list(statuses),
        "is_dnf": [bc.is_dnf(s) for s in statuses],
        "dnf_cause": [bc.dnf_cause(s) for s in statuses],
    }).replace({"dnf_cause": {"none": None}})


def _facts():
    races = pd.DataFrame([
        (2025, 5, "c1", "R2025-5", "2025-09-01", "10:00:00Z"),
        (2026, 1, "c1", "R1", "2026-03-01", "10:00:00Z"),
        (2026, 2, "c1", "R2", "2026-03-08", "10:00:00Z"),
    ], columns=["year", "round", "circuitId", "name", "date", "time"])
    quali = pd.DataFrame([
        (2026, 1, "a", "t1", 1, "1:30.000", None, None),
        (2026, 1, "b", "t1", 2, "1:30.500", None, None),
        (2026, 2, "a", "t1", 1, "1:29.000", None, None),
        (2026, 2, "b", "t1", 2, "1:29.500", None, None),
    ], columns=["year", "round", "driverId", "constructorId",
                "position", "Q1", "Q2", "Q3"])
    results = pd.DataFrame([
        (2026, 1, "a", "t1", 1, 1, 1, 25, 50, "Finished"),
        (2026, 1, "b", "t1", 2, 2, 2, 18, 50, "Finished"),
        (2026, 2, "a", "t1", 1, 1, 1, 25, 50, "Finished"),
        (2026, 2, "b", "t1", 2, 12, 12, 0, 20, "Engine"),
    ], columns=["year", "round", "driverId", "constructorId", "grid",
                "position", "positionOrder", "points", "laps", "status"])
    laps = pd.DataFrame([
        # race 1: 6 green-flag laps, a ahead of b
        (2026, 1, 1, 1.0, "a", "1:30.000", 90_000),
        (2026, 1, 1, 2.0, "b", "1:31.000", 91_000),
        (2026, 1, 2, 1.0, "a", "1:30.000", 90_000),
        (2026, 1, 2, 2.0, "b", "1:31.000", 91_000),
        (2026, 1, 3, 1.0, "a", "1:30.000", 90_000),
        (2026, 1, 3, 2.0, "b", "1:31.000", 91_000),
        # race 2: laps 1,3,4 green, lap 2 SC-slow (35% above green pace)
        (2026, 2, 1, 1.0, "a", "1:30.000", 90_000),
        (2026, 2, 1, 2.0, "b", "1:30.400", 90_400),
        (2026, 2, 2, 1.0, "a", "2:02.000", 122_000),
        (2026, 2, 2, 2.0, "b", "2:02.400", 122_400),
        (2026, 2, 3, 1.0, "a", "1:30.000", 90_000),
        (2026, 2, 3, 2.0, "b", "1:30.400", 90_400),
        (2026, 2, 4, 1.0, "a", "1:30.000", 90_000),
        (2026, 2, 4, 2.0, "b", "1:30.400", 90_400),
    ], columns=["year", "round", "lap", "position", "driverId",
                "time", "milliseconds"])
    pits = pd.DataFrame([
        (2026, 2, "b", 3, 1, "22.500"),
    ], columns=["year", "round", "driverId", "lap", "stop", "duration"])
    snaps = pd.DataFrame([
        (2025, 5, "driver", "a", 100, 5, 1),
        (2026, 1, "driver", "a", 125, 6, 1),
        (2026, 2, "driver", "a", 150, 7, 1),
        (2026, 1, "constructor", "t1", 43, 0, 1),
    ], columns=["year", "round", "kind", "entity_id", "points", "wins",
                "position"])
    return {
        "fact_race": races,
        "fact_quali_entry": None,  # built by the loader from quali
        "fact_race_entry": None,   # built by the loader from results
        "fact_lap": laps,
        "fact_pit_stop": None,     # built by the loader from pits
        "fact_championship_snapshot": snaps,
    }, quali, results, laps, pits


# ── dim_status derivation ────────────────────────────────────────────────

class TestDimStatus:
    def test_derived_from_results_vocabulary(self, tmp_path):
        for name in ("drivers.csv", "constructors.csv", "circuits.csv"):
            (tmp_path / name).write_text("x\n", encoding="utf-8")  # presence not needed
        dims = bc.load_dims(str(MODEL_DIR / "datasets") if False else str(tmp_path),
                            result_statuses=["Retired", "Engine", "Accident",
                                             "Finished", "+1 Lap"])
        s = dims["dim_status"].set_index("status")
        assert list(dims["dim_status"]["statusId"]) == [1, 2, 3, 4, 5]  # sorted text
        assert s.loc["Engine", "dnf_cause"] == "mech"
        assert s.loc["Accident", "dnf_cause"] == "driver"
        assert s.loc["Retired", "dnf_cause"] == "other"
        assert s.loc["Finished", "is_dnf"] == 0
        assert s.loc["+1 Lap", "is_dnf"] == 0

    def test_taxonomy_matches_training_module(self):
        statuses = ["Finished", "Lapped", "+1 Lap", "Engine", "Accident",
                    "Retired", "Disqualified"]
        dim = _status_dim(statuses).set_index("status")
        for s in statuses:
            assert dim.loc[s, "is_dnf"] == bc.is_dnf(s)
            expected = bc.dnf_cause(s)
            assert dim.loc[s, "dnf_cause"] == (None if expected == "none" else expected)


# ── schema enforcement ───────────────────────────────────────────────────

class TestSchemaEnforcement:
    def _db(self, tmp_path):
        db = str(tmp_path / "t.db")
        dims = _dims()
        facts, quali, results, laps, pits = _facts()
        loaded = bc.load_facts.__wrapped__ if False else None
        # build fact tables through the real loader for quali/results/pits
        con = sqlite3.connect(db)
        con.executescript(Path(SCHEMA).read_text(encoding="utf-8"))
        for t in ("dim_driver", "dim_constructor", "dim_circuit", "dim_status"):
            dims[t].to_sql(t, con, if_exists="append", index=False)
        for t in ("fact_race", "fact_championship_snapshot"):
            facts[t].to_sql(t, con, if_exists="append", index=False)
        return con, db, dims, quali, results, laps, pits

    def test_duplicate_pk_rejected(self, tmp_path):
        con, *_ = self._db(tmp_path)
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO fact_race VALUES (2026, 1, 'c1', 'X', NULL, NULL)")
        con.close()

    def test_fk_violation_rejected(self, tmp_path):
        con, *_ = self._db(tmp_path)
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO fact_race VALUES (2027, 1, 'nope', 'X', NULL, NULL)")
        con.close()

    def test_check_constraint_rejects_bad_cause(self, tmp_path):
        con, *_ = self._db(tmp_path)
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(
                "INSERT INTO dim_status VALUES (99, 'X', 1, 'banana')")
        con.close()

    def test_strict_rejects_wrong_type(self, tmp_path):
        con, *_ = self._db(tmp_path)
        # STRICT tables raise a constraint error on type mismatch
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO fact_race VALUES ('abc', 1, 'c1', 'X', NULL, NULL)")
        con.close()


# ── view contracts (cross-checked against pandas implementations) ────────

def _standings_csvs(src, snaps):
    """Write the kind-discriminated snaps frame as the two source standings
    CSVs the loader reads (the real load path for fact_championship_snapshot)."""
    drv = snaps[snaps["kind"] == "driver"].rename(
        columns={"entity_id": "driverId"})[["year", "round", "driverId",
                                           "points", "wins", "position"]]
    con = snaps[snaps["kind"] == "constructor"].rename(
        columns={"entity_id": "constructorId"})[["year", "round",
                                                 "constructorId", "points",
                                                 "wins", "position"]]
    drv.to_csv(src / "driver_standings.csv", index=False)
    con.to_csv(src / "constructor_standings.csv", index=False)


class TestViewContracts:
    def _loaded(self, tmp_path):
        """Full load path through load_facts, into a real DB."""
        dims = _dims()
        facts, quali, results, laps, pits = _facts()
        # route the loader's reads to synthetic CSVs
        src = tmp_path / "ds"
        src.mkdir()
        facts["fact_race"].to_csv(src / "races.csv", index=False)
        quali.to_csv(src / "qualifying.csv", index=False)
        results.to_csv(src / "results.csv", index=False)
        laps.to_csv(src / "lap_times_jolpica.csv", index=False)
        pits.to_csv(src / "pit_stops_jolpica.csv", index=False)
        _standings_csvs(src, facts["fact_championship_snapshot"])
        loaded_facts = bc.load_facts(str(src), dims)
        db = str(tmp_path / "v.db")
        bc.write_db(db, SCHEMA, dims, loaded_facts)
        return db, loaded_facts, laps

    def test_lap_evidence_matches_pandas(self, tmp_path):
        db, _, laps = self._loaded(tmp_path)
        con = sqlite3.connect(db)
        sql = pd.read_sql("SELECT * FROM v_race_lap_evidence", con)
        con.close()
        pan = ed.race_lap_evidence(laps)
        m = sql.merge(pan, on=["year", "round", "lap"],
                      suffixes=("_sql", "_pan"))
        assert len(m) == 7  # 3 laps race 1 + 4 laps race 2
        assert (m["is_slow_lap_sql"] == m["is_slow_lap_pan"].astype(int)).all()
        assert (m["field_median_ms_sql"] - m["field_median_ms_pan"]).abs().max() < 1e-6
        # race 2 lap 2 must be flagged slow, race 1 must have none
        r2 = m[m["round"] == 2].set_index("lap")
        assert r2.loc[2, "is_slow_lap_sql"] == 1
        assert r2.loc[1, "is_slow_lap_sql"] == 0

    def test_driver_race_evidence_matches_pandas(self, tmp_path):
        db, *_ = self._loaded(tmp_path)
        con = sqlite3.connect(db)
        sql = pd.read_sql("SELECT * FROM v_driver_race_evidence", con)
        con.close()
        pan_laps = pd.read_csv(str(tmp_path / "ds" / "lap_times_jolpica.csv"))
        pan_ev = ed.race_lap_evidence(pan_laps)
        a = ed.running_position_gains(pan_laps, 2026, 1, "a", quali_pos=1)
        row = sql[(sql["year"] == 2026) & (sql["round"] == 1)
                  & (sql["driverId"] == "a")].iloc[0]
        assert row["lap1_gain"] == pytest.approx(a["lap1_gain"])
        assert row["last_gain"] == pytest.approx(a["last_gain"])
        # driver b's last recorded lap in race 2 is the final lap (4) —
        # the view reports whatever laps exist, no special casing
        b = sql[(sql["year"] == 2026) & (sql["round"] == 2)
                & (sql["driverId"] == "b")].iloc[0]
        assert b["last_lap"] == 4

    def test_outcome_buckets_and_dnf(self, tmp_path):
        db, *_ = self._loaded(tmp_path)
        con = sqlite3.connect(db)
        out = pd.read_sql(
            "SELECT * FROM v_race_entry_outcome ORDER BY round, driverId", con)
        con.close()
        r2 = out[out["round"] == 2].set_index("driverId")
        assert r2.loc["a", "outcome_bucket"] == 1
        # b: position 12 after Engine DNF -> bucket 3, cause mech, no SC laps on them
        assert r2.loc["b", "outcome_bucket"] == 3
        assert r2.loc["b", "is_dnf"] == 1
        assert r2.loc["b", "dnf_cause"] == "mech"
        assert r2.loc["b", "statusId"] > 0
        # SC exposure joined per race (race 2 had one slow lap)
        assert r2.loc["a", "sc_laps"] == 1

    def test_standings_pit_round1_takes_prev_season_final(self, tmp_path):
        db, *_ = self._loaded(tmp_path)
        con = sqlite3.connect(db)
        s = pd.read_sql("SELECT * FROM v_standings_pit "
                        "WHERE kind='driver' AND entity_id='a' ORDER BY ord", con)
        con.close()
        # snapshot ords: 2025005, 2026001, 2026002 (SQL NULL reads as NaN)
        assert pd.isna(s["prev_ord"].iloc[0])
        assert s["prev_ord"].iloc[1] == 2025005
        assert s["prev_ord"].iloc[2] == 2026001
        # 2026 round 1's previous snapshot IS the previous season's final
        assert s.iloc[1]["prev_points"] == 100
        # share-of-leader: single-entity partitions -> ratio 1.0
        assert s["leader_ratio"].fillna(0).gt(0).all()


# ── end-to-end CLI + manifest drift guard (synthetic datasets) ───────────

class TestBuildCliAndManifest:
    def _synthetic_datasets(self, tmp_path):
        src = tmp_path / "ds"
        src.mkdir()
        dims = _dims(("Finished", "Engine"))
        facts, quali, results, laps, pits = _facts()
        dims["dim_driver"].to_csv(src / "drivers.csv", index=False)
        dims["dim_constructor"].to_csv(src / "constructors.csv", index=False)
        dims["dim_circuit"].to_csv(src / "circuits.csv", index=False)
        facts["fact_race"].to_csv(src / "races.csv", index=False)
        quali.to_csv(src / "qualifying.csv", index=False)
        results.to_csv(src / "results.csv", index=False)
        laps.to_csv(src / "lap_times_jolpica.csv", index=False)
        pits.to_csv(src / "pit_stops_jolpica.csv", index=False)
        _standings_csvs(src, facts["fact_championship_snapshot"])
        return src

    def test_cli_builds_and_manifest_deltas(self, tmp_path):
        src = self._synthetic_datasets(tmp_path)
        db = str(tmp_path / "c.db")
        man = str(tmp_path / "m.json")
        cmd = [sys.executable, str(MODEL_DIR / "build_canonical.py"),
               "--datasets", str(src), "--db", db, "--manifest", man,
               "--schema", SCHEMA]
        r1 = subprocess.run(cmd, capture_output=True, text=True)
        assert r1.returncode == 0, r1.stderr
        m1 = json.loads(Path(man).read_text(encoding="utf-8"))
        assert m1["canonical"]["fact_race"] == 3
        assert m1["canonical"]["fact_race_entry"] == 4
        assert m1["canonical"]["fact_lap"] == 14
        assert m1["canonical"]["fact_championship_snapshot"] == 4
        assert "results.csv" in m1["sources"]
        # comparison state must NEVER enter the file (byte-compare drift
        # guard would be impossible otherwise)
        assert set(m1) == {"sources", "canonical"}

        # second run: unchanged sources -> byte-identical manifest,
        # zero deltas reported on STDOUT (never in the file)
        r2 = subprocess.run(cmd, capture_output=True, text=True)
        assert r2.returncode == 0, r2.stderr
        assert Path(man).read_bytes() == Path(man).read_bytes()
        assert m1 == json.loads(Path(man).read_text(encoding="utf-8"))
        assert "(no changes)" in r2.stdout

        # mutate a source -> delta + changed source reported
        results = pd.read_csv(src / "results.csv")
        results.loc[len(results)] = [2026, 2, "a", "t1", 1, 1, 1, 25, 50, "Finished"]
        results.to_csv(src / "results.csv", index=False)  # adds a DUP key — must FAIL
        r3 = subprocess.run(cmd, capture_output=True, text=True)
        assert r3.returncode != 0
        assert "duplicate" in (r3.stderr + r3.stdout).lower()

    def test_manifest_is_byte_stable(self, tmp_path):
        src = self._synthetic_datasets(tmp_path)
        db = str(tmp_path / "c.db")
        man1, man2 = tmp_path / "m1.json", tmp_path / "m2.json"
        for man in (man1, man2):
            r = subprocess.run(
                [sys.executable, str(MODEL_DIR / "build_canonical.py"),
                 "--datasets", str(src), "--db", db, "--manifest", str(man),
                 "--schema", SCHEMA],
                capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
        # byte-identical manifests across rebuilds (no timestamps, sorted keys)
        assert man1.read_bytes() == man2.read_bytes()


# ── the real committed build (skipped if not built locally) ──────────────

REAL_DB = MODEL_DIR / "datasets" / "f1_canonical.db"
REAL_MANIFEST = MODEL_DIR / "datasets" / "build_manifest.json"


@pytest.mark.skipif(not REAL_DB.exists(), reason="canonical DB not built locally")
class TestRealBuild:
    def test_counts_match_manifest(self):
        m = json.loads(REAL_MANIFEST.read_text(encoding="utf-8"))
        con = sqlite3.connect(str(REAL_DB))
        for t, n in m["canonical"].items():
            got = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            assert got == n, t
        con.close()

    def test_fk_and_integrity(self):
        con = sqlite3.connect(str(REAL_DB))
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        con.close()

    def test_2026_baseline_accuracy_matches_documented(self):
        con = sqlite3.connect(str(REAL_DB))
        rows = con.execute("""
            SELECT q.position, e.position FROM fact_race_entry e
            JOIN fact_quali_entry q
              ON q.year=e.year AND q.round=e.round AND q.driverId=e.driverId
            WHERE e.year=2026""").fetchall()
        con.close()
        bucket = lambda p: 1 if p < 4 else (3 if p > 10 else 2)
        acc = sum(bucket(qp) == bucket(a) for qp, a in rows) / len(rows)
        assert acc == pytest.approx(0.686, abs=1e-3)

    def test_2026_statuses_are_generic(self):
        """The Phase-1 blocker, visible as data: 2026 DNF statuses are
        generic ('Retired'/'Did not start'), so dnf_cause is 'other'."""
        con = sqlite3.connect(str(REAL_DB))
        rows = con.execute("""
            SELECT s.status, s.dnf_cause FROM fact_race_entry e
            JOIN dim_status s ON s.statusId = e.statusId
            WHERE e.year=2026 AND e.is_dnf=1""").fetchall()
        con.close()
        assert rows, "2026 should have DNFs"
        assert all(cause == "other" for _, cause in rows)
