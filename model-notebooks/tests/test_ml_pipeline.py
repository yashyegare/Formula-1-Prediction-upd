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
        # year, round, driverId, driverName, constructorId, constructorName, raceName, position (finish), status
        (2026, 1, "alice", "Alice", "teamx", "TeamX", "Test GP", 1, "Finished"),
        (2026, 1, "bob",   "Bob",   "teamx", "TeamX", "Test GP", 2, "Finished"),
        (2026, 1, "carol", "Carol", "teamy", "TeamY", "Test GP", 3, "Finished"),
        (2026, 1, "dave",  "Dave",  "teamy", "TeamY", "Test GP", 4, "Finished"),
        (2026, 2, "alice", "Alice", "teamx", "TeamX", "Test GP 2", 1, "Finished"),
        (2026, 2, "bob",   "Bob",   "teamx", "TeamX", "Test GP 2", 2, "Finished"),
        (2026, 2, "carol", "Carol", "teamy", "TeamY", "Test GP 2", 3, "Accident"),   # DNF, classified P3
        (2026, 2, "dave",  "Dave",  "teamy", "TeamY", "Test GP 2", 4, "Finished"),
    ], columns=["year", "round", "driverId", "driverName", "constructorId", "constructorName",
                "raceName", "position", "status"])

    qualifying = pd.DataFrame([
        # Same race/driver pairs, but quali position deliberately different
        # from finishing position (reversed within the team pairs).
        (2026, 1, "alice", 3),
        (2026, 1, "bob",   4),
        (2026, 1, "carol", 1),
        (2026, 1, "dave",  2),
        (2026, 2, "alice", 4),
        (2026, 2, "bob",   3),
        (2026, 2, "carol", 2),
        (2026, 2, "dave",  1),
    ], columns=["year", "round", "driverId", "position"])

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
            "year", "round", "GP_name", "quali_pos", "constructor", "driver", "position",
            "driver_confidence", "constructor_relaiblity",
            "driver_champ_pos", "driver_champ_points",
            "constructor_champ_pos", "constructor_champ_points",
            "active_driver", "active_constructor",
        ]


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
        prior season in this fixture -> sentinel 0.
        """
        cleaned = _run_build(tmp_path / "datasets", tmp_path / "out", monkeypatch)
        alice_r1 = cleaned[(cleaned["driver"] == "Alice") & (cleaned["round"] == 1)].iloc[0]
        alice_r2 = cleaned[(cleaned["driver"] == "Alice") & (cleaned["round"] == 2)].iloc[0]
        assert alice_r1["driver_champ_pos"] == 0 and alice_r1["driver_champ_points"] == 0
        assert alice_r2["driver_champ_pos"] == 1 and alice_r2["driver_champ_points"] == 25.0
        # Alice WON round 2 (50 pts after) — that value must NOT leak back.
        assert alice_r2["driver_champ_points"] != 50.0
        teamy_r2 = cleaned[(cleaned["constructor"] == "TeamY") & (cleaned["round"] == 2)].iloc[0]
        assert teamy_r2["constructor_champ_pos"] == 2 and teamy_r2["constructor_champ_points"] == 27.0

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
            "constructor": "TeamX" if i % 2 == 0 else "TeamY",
            "driver": "Alice" if i % 4 == 0 else "Bob",
            "position": pos,
            "driver_confidence": 0.9,
            "constructor_relaiblity": 0.8,
            "driver_champ_pos": 1.0,
            "driver_champ_points": 25.0,
            "constructor_champ_pos": 1.0,
            "constructor_champ_points": 43.0,
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
        # Production (flask-app/app.py /predictGrid) sends the exact feature
        # list train_model.FEATURES declares — 10 columns since the
        # point-in-time standings features were added.
        assert len(train_model.FEATURES) == 10
        row = pd.DataFrame([{
            "GP_name": id_maps["GP_name"]["GP0"],
            "quali_pos": 3,
            "constructor": id_maps["constructor"]["TeamX"],
            "driver": id_maps["driver"]["Alice"],
            "driver_confidence": 0.9,
            "constructor_relaiblity": 0.8,
            "driver_champ_pos": 1.0,
            "driver_champ_points": 25.0,
            "constructor_champ_pos": 1.0,
            "constructor_champ_points": 43.0,
        }])
        preds = model.predict(row)
        assert preds[0] in (1, 2, 3)  # the three buckets the frontend renders
