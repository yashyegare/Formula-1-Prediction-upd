"""
Regression tests for the ML training pipeline.

The historic bug these pin: the original notebook accidentally trained
quali-position -> quali-position because a pandas merge collided the
results 'position' column with the qualifying 'position' column
(position_x/position_y suffix mixup). build_training_data.py fixed it by
renaming the qualifying position to 'quali_pos' BEFORE the merge, so the
target 'position' is the actual race finishing position.

If either file is ever refactored, these tests fail loudly if:
  - position_index() bucket boundaries drift (P1-3 / P4-10 / P11+)
  - the target column leaks qualifying position back into 'position'
  - DNF detection or confidence formulas change
"""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

# Import the pipeline scripts directly from the parent directory.
HERE = Path(__file__).resolve().parent
MODEL_DIR = HERE.parent
sys.path.insert(0, str(MODEL_DIR))

import train_model  # noqa: E402
import build_training_data  # noqa: E402


# ── gap-to-pole: lap-time parsing and session math ────────────────────────

class TestGapToPole:
    def test_lap_time_parsing(self):
        assert build_training_data._lap_time_ms("1:38.109") == 98109
        assert build_training_data._lap_time_ms("98.109") == 98109
        assert build_training_data._lap_time_ms("1:30.01") == 90010  # 2-digit ms padded
        assert build_training_data._lap_time_ms("1:30.0") == 90000
        assert build_training_data._lap_time_ms(None) is None
        assert build_training_data._lap_time_ms("") is None
        assert build_training_data._lap_time_ms("garbage") is None

    def test_gap_to_pole_session_math(self):
        """
        One session, four drivers: pole 90.000s, others behind by 0.1/0.5/1.0s.
        A driver with NO time gets the session median gap (0.5s here), never
        their own future results. Pole sitter scores exactly 0.0.
        """
        q = pd.DataFrame([
            (2026, 1, "p1", 1, "1:30.000", None, None),
            (2026, 1, "p2", 2, "1:30.100", None, None),
            (2026, 1, "p3", 3, "1:30.500", None, None),
            (2026, 1, "p4", 4, "1:31.000", None, None),
            (2026, 1, "p5", 5, None, None, None),      # no time -> median 0.5
        ], columns=["year", "round", "driverId", "position", "Q1", "Q2", "Q3"])
        gaps = build_training_data._gap_to_pole(q)
        assert gaps.iloc[0] == pytest.approx(0.0)   # pole
        assert gaps.iloc[1] == pytest.approx(0.1)
        assert gaps.iloc[2] == pytest.approx(0.5)
        assert gaps.iloc[3] == pytest.approx(1.0)
        assert gaps.iloc[4] == pytest.approx(0.3)   # median of [0.0,0.1,0.5,1.0]

    def test_gap_uses_best_available_session(self):
        """A driver's best time is the fastest of their available sessions
        (a Q1-eliminated driver has only Q1); pole is the session's fastest
        best. A Q2/Q3 time beats the driver's own Q1 time."""
        q = pd.DataFrame([
            (2026, 1, "pole",  1, "1:30.000", "1:29.800", "1:29.500"),
            (2026, 1, "q2car", 2, "1:30.200", "1:29.900", None),      # best 1:29.900
            (2026, 1, "q1car", 3, "1:30.400", None, None),            # best 1:30.400
        ], columns=["year", "round", "driverId", "position", "Q1", "Q2", "Q3"])
        gaps = build_training_data._gap_to_pole(q)
        assert gaps.iloc[0] == pytest.approx(0.0)                       # 1:29.500
        assert gaps.iloc[1] == pytest.approx(0.4)                       # 1:29.900
        assert gaps.iloc[2] == pytest.approx(0.9)                       # 1:30.400

    def test_session_with_no_times_yields_zero(self):
        q = pd.DataFrame([
            (2026, 1, "a", 1, None, None, None),
            (2026, 1, "b", 2, None, None, None),
        ], columns=["year", "round", "driverId", "position", "Q1", "Q2", "Q3"])
        gaps = build_training_data._gap_to_pole(q)
        assert (gaps == 0.0).all()


# ── position_index: the 3-class bucketing ────────────────────────────────────

class TestPositionIndex:
    @pytest.mark.parametrize("pos,expected", [
        (1, 1), (2, 1), (3, 1),          # podium
        (4, 2), (5, 2), (10, 2),         # points
        (11, 3), (20, 3), (22, 3),       # out of points
    ])
    def test_bucket_boundaries(self, pos, expected):
        # P3/P4 and P10/P11 are the historic off-by-one traps — pinned exactly.
        assert train_model.position_index(pos) == expected

    @pytest.mark.parametrize("degenerate", [0, -1])
    def test_degenerate_inputs_still_bucket_deterministically(self, degenerate):
        # Real data (Jolpica's DNF-safe numeric order) is >= 1, but if a
        # refactor changes how degenerate inputs bucket, it must be deliberate.
        assert train_model.position_index(degenerate) == 1


# ── build_training_data: the leakage fix ─────────────────────────────────────

def _write_pipeline_inputs(datasets: Path):
    """
    Synthetic season crafted so qualifying position != finishing position
    for every driver. If the target ever leaks back to qualifying position
    (the original bug), these assertions fail with exact numbers.
    """
    results = pd.DataFrame([
        # year, round, driverId, driverName, constructorId, constructorName, raceName, position (finish), points, status
        (2026, 1, "alice", "Alice", "teamx", "TeamX", "Test GP", 1, 25, "Finished"),
        (2026, 1, "bob",   "Bob",   "teamx", "TeamX", "Test GP", 2, 18, "Finished"),
        (2026, 1, "carol", "Carol", "teamy", "TeamY", "Test GP", 3, 15, "Finished"),
        (2026, 1, "dave",  "Dave",  "teamy", "TeamY", "Test GP", 4, 12, "Finished"),
        (2026, 2, "alice", "Alice", "teamx", "TeamX", "Test GP 2", 1, 25, "Finished"),
        (2026, 2, "bob",   "Bob",   "teamx", "TeamX", "Test GP 2", 2, 18, "Finished"),
        (2026, 2, "carol", "Carol", "teamy", "TeamY", "Test GP 2", 3, 0, "Accident"),  # DNF, classified P3
        (2026, 2, "dave",  "Dave",  "teamy", "TeamY", "Test GP 2", 4, 12, "Finished"),
    ], columns=["year", "round", "driverId", "driverName", "constructorId", "constructorName",
                "raceName", "position", "points", "status"])

    qualifying = pd.DataFrame([
        # Same race/driver pairs, but quali position deliberately different
        # from finishing position (reversed within the team pairs). Q1 times
        # give gap-to-pole: Alice 0.1s off, Bob 0.2s, Carol pole (0.0), Dave
        # 0.3s; round 2 shifted by one slot. Carol (round 2, no time) tests
        # the median fill.
        (2026, 1, "alice", 3, "1:30.100"),
        (2026, 1, "bob",   4, "1:30.200"),
        (2026, 1, "carol", 1, "1:30.000"),
        (2026, 1, "dave",  2, "1:30.300"),
        (2026, 2, "alice", 4, "1:30.100"),
        (2026, 2, "bob",   3, "1:30.200"),
        (2026, 2, "carol", 2, None),
        (2026, 2, "dave",  1, "1:30.000"),
    ], columns=["year", "round", "driverId", "position", "Q1"])

    # Championship snapshots AFTER each round (post-race), exactly how the
    # real data ships. Round-2 rows must therefore see round-1 values.
    driver_standings = pd.DataFrame([
        # after round 1 (race points 25/18/15/12 in finish order)
        (2026, 1, "alice", 25.0, 1, 1),
        (2026, 1, "bob",   18.0, 0, 2),
        (2026, 1, "carol", 15.0, 0, 3),
        (2026, 1, "dave",  12.0, 0, 4),
        # after round 2
        (2026, 2, "alice", 50.0, 2, 1),
        (2026, 2, "bob",   36.0, 0, 2),
        (2026, 2, "carol", 15.0, 0, 3),   # DNF'd round 2, no new points
        (2026, 2, "dave",  24.0, 0, 4),
    ], columns=["year", "round", "driverId", "points", "wins", "position"])

    constructor_standings = pd.DataFrame([
        (2026, 1, "teamx", 43.0, 1, 1),
        (2026, 1, "teamy", 27.0, 0, 2),
        (2026, 2, "teamx", 86.0, 2, 1),
        (2026, 2, "teamy", 27.0, 0, 2),
    ], columns=["year", "round", "constructorId", "points", "wins", "position"])

    datasets.mkdir(parents=True, exist_ok=True)
    results.to_csv(datasets / "results.csv", index=False)
    qualifying.to_csv(datasets / "qualifying.csv", index=False)
    driver_standings.to_csv(datasets / "driver_standings.csv", index=False)
    constructor_standings.to_csv(datasets / "constructor_standings.csv", index=False)


def _run_build(datasets: Path, out: Path, monkeypatch):
    _write_pipeline_inputs(datasets)
    out.mkdir(parents=True, exist_ok=True)  # the scripts assume an existing output dir
    monkeypatch.setattr(
        sys, "argv",
        ["build_training_data.py", "--datasets", str(datasets), "--out", str(out)],
    )
    build_training_data.main()
    return pd.read_csv(out / "cleaned_data.csv")


class TestLeakageFix:
    def test_target_is_finish_position_not_qualifying(self, tmp_path, monkeypatch):
        cleaned = _run_build(tmp_path / "datasets", tmp_path / "out", monkeypatch)

        alice = cleaned[cleaned["driver"] == "Alice"]
        # Alice qualified P3/P4 but FINISHED P1 both races.
        # Old bug: target would read the quali values (3/4). Fix: 1/1.
        assert sorted(alice["position"].tolist()) == [1, 1]
        assert sorted(alice["quali_pos"].tolist()) == [3, 4]

    def test_quali_pos_is_the_qualifying_classification(self, tmp_path, monkeypatch):
        cleaned = _run_build(tmp_path / "datasets", tmp_path / "out", monkeypatch)
        carol = cleaned[cleaned["driver"] == "Carol"]
        # Carol qualified P1/P2 — the feature must carry quali, not finish.
        assert sorted(carol["quali_pos"].tolist()) == [1, 2]
        assert sorted(carol["position"].tolist()) == [3, 3]

    def test_position_and_quali_pos_columns_are_distinct(self, tmp_path, monkeypatch):
        # The structural pin on the merge: the pipeline must not leave a
        # position_x/position_y collision that gets silently resolved wrong.
        cleaned = _run_build(tmp_path / "datasets", tmp_path / "out", monkeypatch)
        assert not (cleaned["position"] == cleaned["quali_pos"]).all()
        assert list(cleaned.columns) == [
            "year", "round", "GP_name", "quali_pos", "gap_to_pole", "constructor", "driver", "position",
            "driver_confidence", "constructor_relaiblity",
            "driver_champ_pos", "driver_champ_points_ratio",
            "constructor_champ_pos", "constructor_champ_points_ratio",
            "driver_recent_form", "constructor_recent_form",
            "active_driver", "active_constructor",
        ]

    def test_champ_points_are_leader_share_ratios(self, tmp_path, monkeypatch):
        """
        Raw championship points aren't comparable across a season (40 pts at
        round 4 = dominating; 40 pts at round 20 = mid-pack). The feature is
        points / leader-points WITHIN the same snapshot, so it stays 0..1.
        Round 1 (no prior snapshot) -> sentinel 0.0; round 2 carries the
        ROUND-1 snapshot normalized: Alice 25/25 = 1.0, Dave 12/25 = 0.48.
        """
        cleaned = _run_build(tmp_path / "datasets", tmp_path / "out", monkeypatch)
        alice_r1 = cleaned[(cleaned["driver"] == "Alice") & (cleaned["round"] == 1)].iloc[0]
        alice_r2 = cleaned[(cleaned["driver"] == "Alice") & (cleaned["round"] == 2)].iloc[0]
        dave_r2 = cleaned[(cleaned["driver"] == "Dave") & (cleaned["round"] == 2)].iloc[0]
        assert alice_r1["driver_champ_points_ratio"] == pytest.approx(0.0)  # sentinel
        assert alice_r2["driver_champ_points_ratio"] == pytest.approx(1.0)  # leader
        assert dave_r2["driver_champ_points_ratio"] == pytest.approx(12.0 / 25.0)

    def test_recent_form_is_prior_window_average(self, tmp_path, monkeypatch):
        """
        Recent form = mean GRID->FINISH DELTA over the driver's strictly
        prior <=5 races (quali_pos - position; positive = gains places on
        race day). Alice: quali P3/finish P1 then quali P4/finish P1, so
        her deltas are +2 and +3 — round-1 form is the fixed neutral prior
        0.0 (no history), round-2 form is exactly +2.0 (the PRIOR delta;
        her own +3 must not appear). A race's own result never appears in
        its form value, and the value is a delta, not a raw mean finish.
        """
        cleaned = _run_build(tmp_path / "datasets", tmp_path / "out", monkeypatch)
        alice = cleaned[cleaned["driver"] == "Alice"].sort_values("round")
        assert alice["driver_recent_form"].iloc[0] == pytest.approx(
            build_training_data.RECENT_FORM_PRIOR
        )
        assert alice["driver_recent_form"].iloc[1] == pytest.approx(2.0)

    def test_constructor_form_is_prior_window_average(self, tmp_path, monkeypatch):
        """
        Constructor form = mean TEAM POINTS over strictly prior <=5 races.
        TeamY scored 15+12=27 in round 1 and 0+12=12 in round 2, so round-1
        form is the fixed prior 0.0 and round-2 form is exactly 27.0 (the
        prior race only — the team's own round-2 points must not appear).
        TeamX round-2 form = 25+18 = 43.0.
        """
        cleaned = _run_build(tmp_path / "datasets", tmp_path / "out", monkeypatch)
        # A constructor has TWO rows per round (one per driver) — filter by
        # round, don't index a sorted frame (iloc[1] would be round 1's
        # second driver).
        teamy_r1 = cleaned[(cleaned["constructor"] == "TeamY") & (cleaned["round"] == 1)]
        teamy_r2 = cleaned[(cleaned["constructor"] == "TeamY") & (cleaned["round"] == 2)]
        assert teamy_r1["constructor_recent_form"].iloc[0] == pytest.approx(
            build_training_data.CONSTRUCTOR_FORM_PRIOR
        )
        assert teamy_r2["constructor_recent_form"].iloc[0] == pytest.approx(27.0)
        teamx_r2 = cleaned[(cleaned["constructor"] == "TeamX") & (cleaned["round"] == 2)]
        assert teamx_r2["constructor_recent_form"].iloc[0] == pytest.approx(43.0)


class TestFeatureEngineering:
    def test_dnf_detection_from_text_status(self):
        assert build_training_data.is_dnf("Finished") == 0
        assert build_training_data.is_dnf("Lapped") == 0
        assert build_training_data.is_dnf("+1 Lap") == 0
        assert build_training_data.is_dnf("+52.316") == 0
        assert build_training_data.is_dnf("Accident") == 1
        assert build_training_data.is_dnf("Engine") == 1
        assert build_training_data.is_dnf("Disqualified") == 1

    def test_driver_confidence_is_point_in_time(self, tmp_path, monkeypatch):
        """
        THE leakage pin: each row's confidence must come from strictly
        PRIOR races only. Alice has zero DNFs, so the OLD global-lifetime
        code stamped 1.0 on every row (including her first race — which
        knew the future). The expanding window gives:
          race 1: no history -> FIRST_APPEARANCE_PRIOR (0.90)
          race 2: race-1 reliability (1.0) -> 1.0
        Carol DNF'd in race 2, so her race-2 value must still be based on
        race 1 only (1.0) — her own DNF must NOT appear in her features.
        """
        cleaned = _run_build(tmp_path / "datasets", tmp_path / "out", monkeypatch)
        alice = cleaned[cleaned["driver"] == "Alice"].sort_values("round")
        assert alice["driver_confidence"].iloc[0] == pytest.approx(0.90)
        assert alice["driver_confidence"].iloc[1] == pytest.approx(1.0)
        carol = cleaned[cleaned["driver"] == "Carol"].sort_values("round")
        assert carol["driver_confidence"].iloc[1] == pytest.approx(1.0)

    def test_roster_confidence_is_lifetime_for_serving(self, tmp_path, monkeypatch):
        """The roster serves FUTURE races, where lifetime-to-date is the
        correct point-in-time value: Carol 1 DNF / 2 entries -> 0.5."""
        _run_build(tmp_path / "datasets", tmp_path / "out", monkeypatch)
        roster = json.loads((tmp_path / "out" / "current_roster.json").read_text())
        assert roster["driver_confidence"]["Carol"] == pytest.approx(0.5)
        assert roster["driver_confidence"]["Alice"] == pytest.approx(1.0)

    def test_standings_join_is_prior_round(self, tmp_path, monkeypatch):
        """
        Round-2 rows must carry ROUND-1 championship values; a round's own
        results must never appear in its features. Round-1 rows have no
        prior season in this fixture -> sentinel 0. The sentinel IS the
        leak-guard: if the join ever used a race's own snapshot, round-1
        rows would show pos 1 / ratio 1.0 instead of 0 / 0.0.
        """
        cleaned = _run_build(tmp_path / "datasets", tmp_path / "out", monkeypatch)
        alice_r1 = cleaned[(cleaned["driver"] == "Alice") & (cleaned["round"] == 1)].iloc[0]
        alice_r2 = cleaned[(cleaned["driver"] == "Alice") & (cleaned["round"] == 2)].iloc[0]
        assert alice_r1["driver_champ_pos"] == 0 and alice_r1["driver_champ_points_ratio"] == 0
        assert alice_r2["driver_champ_pos"] == 1
        # Round-2 ratio is built from the ROUND-1 snapshot: Alice led with
        # 25/25 -> 1.0 (she also leads after round 2, so positions can't
        # distinguish; the ratio scale does the pinning here).
        assert alice_r2["driver_champ_points_ratio"] == pytest.approx(1.0)
        teamy_r2 = cleaned[(cleaned["constructor"] == "TeamY") & (cleaned["round"] == 2)].iloc[0]
        assert teamy_r2["constructor_champ_pos"] == 2

    def test_gap_to_pole_in_cleaned_and_roster(self, tmp_path, monkeypatch):
        """
        Round 1: Carol pole (0.0), Alice +0.1, Bob +0.2, Dave +0.3.
        Round 2: Dave pole (0.0), Alice +0.1, Bob +0.2, Carol no time ->
        session median of KNOWN gaps (0.1, 0.2, 0.0) = 0.1. The roster
        carries the per-GP median and each driver's last actual gap for
        serving.
        """
        cleaned = _run_build(tmp_path / "datasets", tmp_path / "out", monkeypatch)
        r1 = cleaned[cleaned["round"] == 1].set_index("driver")["gap_to_pole"]
        assert r1["Carol"] == pytest.approx(0.0)
        assert r1["Alice"] == pytest.approx(0.1)
        assert r1["Dave"] == pytest.approx(0.3)
        r2 = cleaned[cleaned["round"] == 2].set_index("driver")["gap_to_pole"]
        assert r2["Dave"] == pytest.approx(0.0)
        assert r2["Carol"] == pytest.approx(0.1)  # median fill, not leaked
        roster = json.loads((tmp_path / "out" / "current_roster.json").read_text())
        # per-GP medians keyed by race name: round 1 gaps 0.0/0.1/0.2/0.3 ->
        # median 0.15; round 2 (incl. Carol's 0.1 fill) -> median 0.1
        assert roster["gp_median_gap_to_pole"]["Test GP"] == pytest.approx(0.15)
        assert roster["gp_median_gap_to_pole"]["Test GP 2"] == pytest.approx(0.1)
        assert roster["driver_last_gap_to_pole"]["Dave"] == pytest.approx(0.0)

    def test_dnf_driver_still_active_and_keeps_finish_position(self, tmp_path, monkeypatch):
        cleaned = _run_build(tmp_path / "datasets", tmp_path / "out", monkeypatch)
        carol_last = cleaned[(cleaned["driver"] == "Carol") & (cleaned["GP_name"] == "Test GP 2")]
        # A DNF still has a classified finishing order and stays on the roster.
        assert carol_last["position"].iloc[0] == 3
        assert carol_last["active_driver"].iloc[0] == 1

    def test_roster_json_written(self, tmp_path, monkeypatch):
        _run_build(tmp_path / "datasets", tmp_path / "out", monkeypatch)
        roster = json.loads((tmp_path / "out" / "current_roster.json").read_text())
        assert sorted(roster["active_drivers"]) == ["Alice", "Bob", "Carol", "Dave"]
        assert roster["latest_year"] == 2026 and roster["latest_round"] == 2

    def test_roster_exports_ratio_and_form_for_serving(self, tmp_path, monkeypatch):
        """
        app.py /predictGrid reads exactly these roster keys — the serving
        side of the scale-invariant points + recent-form contract.
        Alice's serving form is the mean of her deltas (+2, +3) = 2.5;
        TeamX's is the mean of its team points (43, 43) = 43.0.
        """
        _run_build(tmp_path / "datasets", tmp_path / "out", monkeypatch)
        roster = json.loads((tmp_path / "out" / "current_roster.json").read_text())
        assert roster["driver_champ_points_ratio"]["Alice"] == pytest.approx(1.0)
        assert roster["driver_champ_points_ratio"]["Dave"] == pytest.approx(0.48)
        assert roster["driver_recent_form"]["Alice"] == pytest.approx(2.5)
        assert roster["constructor_recent_form"]["TeamX"] == pytest.approx(43.0)
        assert roster["constructor_recent_form"]["TeamY"] == pytest.approx(19.5)
        assert "driver_champ_points" not in roster  # raw-points key retired


# ── train_model end-to-end on synthetic data ─────────────────────────────────

def _write_training_csv(out: Path):
    """40 rows of perfectly bucket-separable data so the model trains fast."""
    rows = []
    for i in range(40):
        pos = (i % 20) + 1  # finishing positions 1..20 cycling
        rows.append({
            "year": 2024 + (i % 2),  # two seasons so walk-forward has a split
            "round": (i % 2) + 1,
            "GP_name": f"GP{i % 2}",
            "quali_pos": pos,                       # correlated but the point stands
            "gap_to_pole": pos * 0.1,
            "constructor": "TeamX" if i % 2 == 0 else "TeamY",
            "driver": "Alice" if i % 4 == 0 else "Bob",
            "position": pos,
            "driver_confidence": 0.9,
            "constructor_relaiblity": 0.8,
            "driver_champ_pos": 1.0,
            "driver_champ_points_ratio": 1.0,
            "constructor_champ_pos": 1.0,
            "constructor_champ_points_ratio": 1.0,
            "driver_recent_form": 1.0,
            "constructor_recent_form": 20.0,
            "active_driver": 1,
            "active_constructor": 1,
        })
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "cleaned_data.csv", index=False)


class TestTrainModelEndToEnd:
    def test_trains_and_exports_artifacts(self, tmp_path, monkeypatch):
        _write_training_csv(tmp_path / "datasets")
        (tmp_path / "out").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(
            sys, "argv",
            ["train_model.py", "--data", str(tmp_path / "datasets" / "cleaned_data.csv"),
             "--out", str(tmp_path / "out")],
        )
        train_model.main()  # must not raise

        assert (tmp_path / "out" / "rffinal.pkl").exists()
        id_maps = json.loads((tmp_path / "out" / "id_maps.json").read_text())
        # The app.py / nextjs frontend consume these maps verbatim.
        assert set(id_maps) == {"GP_name", "constructor", "driver"}
        assert "Alice" in id_maps["driver"] and "Bob" in id_maps["driver"]
        assert "TeamX" in id_maps["constructor"] and "TeamY" in id_maps["constructor"]
        assert "GP0" in id_maps["GP_name"] and "GP1" in id_maps["GP_name"]

    def test_model_reloads_and_predicts_valid_buckets(self, tmp_path, monkeypatch):
        import joblib
        import numpy as np

        _write_training_csv(tmp_path / "datasets")
        (tmp_path / "out").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(
            sys, "argv",
            ["train_model.py", "--data", str(tmp_path / "datasets" / "cleaned_data.csv"),
             "--out", str(tmp_path / "out")],
        )
        train_model.main()

        model = joblib.load(tmp_path / "out" / "rffinal.pkl")
        id_maps = json.loads((tmp_path / "out" / "id_maps.json").read_text())
        # Production (flask-app/app.py /predictGrid) predicts on a DataFrame
        # with exactly these named columns — pin the inference contract.
        # 13 columns since the gap-to-pole feature.
        assert len(train_model.FEATURES) == 13
        row = pd.DataFrame([{
            "GP_name": id_maps["GP_name"]["GP0"],
            "quali_pos": 3,
            "gap_to_pole": 0.15,
            "constructor": id_maps["constructor"]["TeamX"],
            "driver": id_maps["driver"]["Alice"],
            "driver_confidence": 0.9,
            "constructor_relaiblity": 0.8,
            "driver_champ_pos": 1.0,
            "driver_champ_points_ratio": 1.0,
            "constructor_champ_pos": 1.0,
            "constructor_champ_points_ratio": 1.0,
            "driver_recent_form": 1.0,
            "constructor_recent_form": 20.0,
        }])
        preds = model.predict(row)
        assert preds[0] in (1, 2, 3)  # the three buckets the frontend renders
