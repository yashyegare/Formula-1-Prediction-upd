"""
Tests for error_decomposition.py — the post-race attribution layer.

The failure modes these pin:
  - bucket boundaries drifting from train_model.position_index
  - the DNF taxonomy drifting from build_training_data
  - slow-lap (SC) detection flagging normal green-flag racing
  - attribution mislabeling a finished race as a DNF (or vice versa)
  - evidence numbers (pace delta, grid swings) computed on the wrong join
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
MODEL_DIR = HERE.parent
sys.path.insert(0, str(MODEL_DIR))

import error_decomposition as ed  # noqa: E402


# ── bucket boundaries + DNF taxonomy (mirrors of the training pipeline) ──

class TestBuckets:
    def test_position_index_boundaries(self):
        assert ed.position_index(1) == 1
        assert ed.position_index(3) == 1
        assert ed.position_index(4) == 2
        assert ed.position_index(10) == 2
        assert ed.position_index(11) == 3
        assert ed.position_index(20) == 3

    def test_dnf_cause_taxonomy_matches_training(self):
        assert ed.dnf_cause("Finished") == "none"
        assert ed.dnf_cause("+1 Lap") == "none"
        assert ed.dnf_cause("Lapped") == "none"
        assert ed.dnf_cause("Engine") == "mech"
        assert ed.dnf_cause("Gearbox") == "mech"
        assert ed.dnf_cause("Accident") == "driver"
        assert ed.dnf_cause("Collision") == "driver"
        assert ed.dnf_cause("Disqualified") == "other"
        assert ed.dnf_cause("Withdrew") == "other"
        assert ed.dnf_cause(None) == "none"

    def test_pit_duration_parsing(self):
        assert ed._duration_to_s("22.213") == pytest.approx(22.213)
        assert ed._duration_to_s("1:02.5") == pytest.approx(62.5)
        assert ed._duration_to_s(25.1) == pytest.approx(25.1)
        assert ed._duration_to_s(None) is None
        assert ed._duration_to_s("") is None


# ── slow-lap (safety-car) detection ──────────────────────────────────────

class TestRaceLapEvidence:
    def _laps(self, medians):
        """Build a laps frame from {lap: field median ms} for one race."""
        rows = []
        for lap, med in medians.items():
            # two drivers straddling the field median so the median is stable
            rows.append((2026, 1, lap, 1.0, "a", "1:30.000", med - 100))
            rows.append((2026, 1, lap, 2.0, "b", "1:30.200", med + 100))
        return pd.DataFrame(rows, columns=[
            "year", "round", "lap", "position", "driverId", "time", "milliseconds"])

    def test_green_flag_race_has_no_slow_laps(self):
        laps = self._laps({i: 90_000 for i in range(1, 11)})
        ev = ed.race_lap_evidence(laps)
        assert not ev["is_slow_lap"].any()
        assert ev["race_median_ms"].iloc[0] == 90_000

    def test_safety_car_laps_detected(self):
        # laps 5-7 are SC-slow (field median 35% above green pace)
        meds = {i: 90_000 for i in range(1, 11)}
        meds.update({5: 121_000, 6: 125_000, 7: 118_000})
        ev = ed.race_lap_evidence(self._laps(meds))
        slow = ev[ev["is_slow_lap"]]
        assert sorted(slow["lap"]) == [5, 6, 7]

    def test_safety_car_exposure_summary(self):
        meds = {i: 90_000 for i in range(1, 11)}
        meds.update({5: 121_000, 6: 125_000, 7: 118_000})
        ev = ed.race_lap_evidence(self._laps(meds))
        sc = ed.safety_car_exposure(ev, 2026, 1)
        assert sc["sc_laps"] == 3
        assert sc["sc_first_lap"] == 5
        assert sc["sc_share"] == pytest.approx(0.3)

    def test_borderline_1p2x_lap_not_flagged(self):
        # exactly at the threshold = not slow (strictly-greater comparison)
        laps = self._laps({1: 90_000, 2: 108_000, 3: 90_000})
        ev = ed.race_lap_evidence(laps)
        assert not ev[ev["lap"] == 2]["is_slow_lap"].any()


# ── driver-level evidence ────────────────────────────────────────────────

class TestDriverEvidence:
    def _fixtures(self):
        laps = pd.DataFrame([
            # race 1: driver a laps 1-3, driver b laps 1-3
            (2026, 1, 1, 1.0, "a", "1:29.000", 89_000),
            (2026, 1, 1, 2.0, "b", "1:31.000", 91_000),
            (2026, 1, 2, 1.0, "a", "1:29.000", 89_000),
            (2026, 1, 2, 2.0, "b", "1:31.000", 91_000),
            (2026, 1, 3, 1.0, "a", "1:29.000", 89_000),
            (2026, 1, 3, 2.0, "b", "1:31.000", 91_000),
        ], columns=["year", "round", "lap", "position", "driverId", "time", "milliseconds"])
        pits = pd.DataFrame([
            (2026, 1, "a", 2, 1, "22.500"),
            (2026, 1, "a", 2, 2, "23.500"),
        ], columns=["year", "round", "driverId", "lap", "stop", "duration"])
        return laps, pits

    def test_driver_race_pace_mean_delta(self):
        laps, _ = self._fixtures()
        ev = ed.race_lap_evidence(laps)
        pace = ed.driver_race_pace(laps, ev, 2026, 1, "a")
        # field median per lap = 90_000; driver a = 89_000 -> -1.0s/lap
        assert pace["pace_delta_s"] == pytest.approx(-1.0)
        assert pace["pace_laps"] == 3

    def test_driver_race_pace_dnf_has_only_prior_laps(self):
        laps, _ = self._fixtures()
        ev = ed.race_lap_evidence(laps)
        # a driver who retired simply has fewer lap rows — no special casing
        pace = ed.driver_race_pace(laps, ev, 2026, 1, "b")
        assert pace["pace_delta_s"] == pytest.approx(1.0)

    def test_running_position_gains(self):
        laps, _ = self._fixtures()
        g = ed.running_position_gains(laps, 2026, 1, "a", quali_pos=3)
        # ran P1 every lap from P3: gained 2 places
        assert g["lap1_gain"] == 2
        assert g["last_gain"] == 2
        assert g["laps_led"] == 3

    def test_running_position_gains_no_data(self):
        laps, _ = self._fixtures()
        g = ed.running_position_gains(laps, 2026, 1, "ghost", 5)
        assert np.isnan(g["lap1_gain"])

    def test_pit_evidence_sums_stops(self):
        _, pits = self._fixtures()
        p = ed.pit_evidence(pits, 2026, 1, "a")
        assert p["pit_stops"] == 2
        assert p["pit_total_s"] == pytest.approx(46.0)

    def test_pit_evidence_no_stops(self):
        _, pits = self._fixtures()
        p = ed.pit_evidence(pits, 2026, 1, "nobody")
        assert p["pit_stops"] == 0
        assert p["pit_total_s"] == 0.0


# ── attribution logic ────────────────────────────────────────────────────

class TestDecomposeOne:
    def _ev(self, pace=0.0, last_gain=0.0, sc_laps=0, sc_first=0):
        return (
            {"pace_delta_s": pace, "pace_laps": 50, "median_lap_s": 90.0},
            {"pit_total_s": 45.0, "pit_stops": 2},
            {"sc_laps": sc_laps, "sc_first_lap": sc_first, "sc_share": 0.1},
            {"lap1_gain": 0.0, "last_gain": last_gain, "laps_led": 0},
        )

    def test_correct_prediction(self):
        row = ed.decompose_one(2, 2, "Finished", *self._ev())
        assert row["cause"] == "correct"
        assert row["verdict"] == "Correct"

    def test_dnf_is_dominant_cause(self):
        row = ed.decompose_one(1, 3, "Engine", *self._ev())
        assert row["cause"] == "dnf_mech"
        assert "DNF" in row["verdict"]

    def test_dnf_that_delivered_the_prediction_is_correct(self):
        # predicted out-of-points (3), DNF'd (actual 3): a CORRECT prediction,
        # not a miss — the historic mislabeling bug
        row = ed.decompose_one(3, 3, "Engine", *self._ev())
        assert row["cause"] == "correct_dnf"
        assert "Correct" in row["verdict"]

    def test_dnf_driver_error(self):
        row = ed.decompose_one(2, 3, "Accident", *self._ev())
        assert row["cause"] == "dnf_driver"

    def test_over_predict_with_slow_pace_evidence(self):
        row = ed.decompose_one(1, 2, "Finished", *self._ev(pace=0.8, last_gain=-4))
        assert row["cause"] == "over_predict"
        assert "slow race pace" in row["verdict"]
        assert "lost 4 places" in row["verdict"]

    def test_over_predict_no_evidence_below_thresholds(self):
        row = ed.decompose_one(1, 2, "Finished", *self._ev(pace=0.1, last_gain=-1))
        assert row["cause"] == "over_predict"
        assert row["verdict"] == "Finished worse than predicted"  # no noise evidence

    def test_under_predict_with_fast_pace_evidence(self):
        row = ed.decompose_one(2, 1, "Finished", *self._ev(pace=-0.7, last_gain=5))
        assert row["cause"] == "under_predict"
        assert "fast race pace" in row["verdict"]
        assert "gained 5 places" in row["verdict"]

    def test_sc_evidence_only_on_late_shuffles(self):
        row = ed.decompose_one(1, 2, "Finished", *self._ev(sc_laps=4, sc_first=30))
        assert "SC/VSC at lap 30" in row["verdict"]
        early = ed.decompose_one(1, 2, "Finished", *self._ev(sc_laps=4, sc_first=1))
        assert "SC/VSC" not in early["verdict"]


# ── end-to-end on synthetic data ─────────────────────────────────────────

class TestBuildAndSummarize:
    def test_end_to_end_synthetic(self, tmp_path):
        results = pd.DataFrame([
            (2026, 1, "R1", "a", "Driver A", "t1", "Team 1", 1, 1, 1, 25, 50, "Finished"),
            (2026, 1, "R1", "b", "Driver B", "t2", "Team 2", 2, 3, 3, 15, 50, "Engine"),
            (2026, 1, "R1", "c", "Driver C", "t3", "Team 3", 3, 12, 12, 0, 48, "Finished"),
        ], columns=["year", "round", "raceName", "driverId", "driverName",
                    "constructorId", "constructorName", "grid", "position",
                    "positionOrder", "points", "laps", "status"])
        laps = pd.DataFrame([
            (2026, 1, 1, 1.0, "a", "1:30.000", 90_000),
            (2026, 1, 1, 2.0, "b", "1:30.500", 90_500),
            (2026, 1, 1, 3.0, "c", "1:31.000", 91_000),
            (2026, 1, 2, 1.0, "a", "1:30.000", 90_000),
            (2026, 1, 2, 2.0, "b", "1:30.500", 90_500),
            (2026, 1, 2, 3.0, "c", "1:31.000", 91_000),
        ], columns=["year", "round", "lap", "position", "driverId", "time", "milliseconds"])
        pits = pd.DataFrame(columns=["year", "round", "driverId", "lap", "stop", "duration"])
        for name, df in (("results.csv", results), ("lap_times_jolpica.csv", laps),
                         ("pit_stops_jolpica.csv", pits)):
            df.to_csv(tmp_path / name, index=False)

        preds = pd.DataFrame([
            {"year": 2026, "round": 1, "race": "R1", "driver": "Driver A",
             "driverId": "a", "qpos": 1, "pred": 1, "actual": 1},
            {"year": 2026, "round": 1, "race": "R1", "driver": "Driver B",
             "driverId": "b", "qpos": 2, "pred": 1, "actual": 3},
            {"year": 2026, "round": 1, "race": "R1", "driver": "Driver C",
             "driverId": "c", "qpos": 3, "pred": 1, "actual": 3},
            {"year": 2026, "round": 1, "race": "R1", "driver": "Driver D",
             "driverId": "d", "qpos": 15, "pred": 3, "actual": 3},
        ])
        # Driver D needs a results row: predicted out-of-points, retired —
        # the DNF delivered the prediction (correct_dnf, not a miss).
        import pandas as _pd
        extra = _pd.DataFrame([
            (2026, 1, "R1", "d", "Driver D", "t4", "Team 4", 15, 18, 18, 0, 12, "Retired"),
        ], columns=["year", "round", "raceName", "driverId", "driverName",
                    "constructorId", "constructorName", "grid", "position",
                    "positionOrder", "points", "laps", "status"])
        results = _pd.concat([
            _pd.read_csv(tmp_path / "results.csv"), extra
        ], ignore_index=True)
        results.to_csv(tmp_path / "results.csv", index=False)

        dec = ed.build_decompositions(str(tmp_path), preds)
        assert len(dec) == 4
        by_driver = dec.set_index("driver")
        assert by_driver.loc["Driver A", "cause"] == "correct"
        assert by_driver.loc["Driver B", "cause"] == "dnf_mech"
        assert by_driver.loc["Driver C", "cause"] == "over_predict"
        assert by_driver.loc["Driver D", "cause"] == "correct_dnf"

        s = ed.summarize(dec)
        assert s["n_predictions"] == 4
        assert s["n_misses"] == 2
        assert s["accuracy"] == pytest.approx(0.5)
        assert s["cause_share"]["dnf_mechanical"] == pytest.approx(0.5)
        assert s["cause_share"]["over_predict"] == pytest.approx(0.5)

    def test_baseline_predictions_cover_full_field(self, tmp_path):
        results = pd.DataFrame([
            (2026, 1, "R1", "a", "Driver A", 1, 1),
            (2026, 1, "R1", "b", "Driver B", 2, 12),
        ], columns=["year", "round", "raceName", "driverId", "driverName",
                    "position", "grid"])
        quali = pd.DataFrame([
            (2026, 1, "a", 1, "1:30.0", None, None),
            (2026, 1, "b", 5, "1:30.5", None, None),
        ], columns=["year", "round", "driverId", "position", "Q1", "Q2", "Q3"])
        results.to_csv(tmp_path / "results.csv", index=False)
        quali.to_csv(tmp_path / "qualifying.csv", index=False)

        preds = ed._baseline_predictions(str(tmp_path), 2026)
        assert len(preds) == 2
        assert preds.iloc[0]["pred"] == 1   # quali P1 -> podium bucket
        assert preds.iloc[1]["pred"] == 2   # quali P5 -> points bucket

    def test_active_universe_matches_training_harness(self):
        """The active-grid filter must reproduce train_model's universe:
        whoever raced the single most recent round in results.csv."""
        results = pd.DataFrame([
            (2025, 5, "old", "Retired Driver", "ret", "Old Team"),
            (2026, 3, "cur", "Active Driver", "act", "Current Team"),
            (2026, 2, "old", "Retired Driver", "ret", "Old Team"),
        ], columns=["year", "round", "driverId", "driverName",
                    "constructorId", "constructorName"])
        active_d, active_c = ed.active_universe(results)
        assert active_d == {"cur"}
        assert active_c == {"act"}
