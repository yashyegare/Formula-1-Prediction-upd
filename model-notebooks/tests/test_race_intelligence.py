"""
Tests for the race-intelligence layer (artifact builder + serving API).

Pins the contracts:
  - artifact schema v2 (statuses raced/scheduled/next_round, driver
    field completeness, round ordering)
  - determinism: two builds with the same seed are byte-identical
  - distribution sums ≈ 1 per driver; all probabilities in [0, 1]
  - future rounds: no swing insight fields, deterministic championship
    order grid, expected position respects pit-lane clamping
  - attribution numbers agree with error_decomposition.summarize()
  - blueprint serving: 200 shapes for season/races/race/drivers/next,
    explicit 404s for unknown season/round, 503 when the artifact is
    absent, and hot reload when the artifact is rebuilt
"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# the serving blueprint lives in flask-app/
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "flask-app"))

import race_intelligence as ri  # noqa: E402
import race_simulator as rs  # noqa: E402

DB = Path(__file__).resolve().parents[1] / "datasets" / "f1_canonical.db"
DATASETS = Path(__file__).resolve().parents[1] / "datasets"

REAL = pytest.mark.skipif(
    not (DB.exists() and (DATASETS / "results.csv").exists()),
    reason="real canonical DB / datasets not present")


# ── artifact builder (real data — cheap: 23 races x 200 sims) ─────────────

@REAL
def test_artifact_schema_v2():
    doc = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    assert set(doc) >= {"schema_version", "season", "n_sims", "next_round",
                        "mechanism", "races", "season_attribution"}
    assert doc["schema_version"] == 2
    rounds = [r["round"] for r in doc["races"]]
    assert rounds == sorted(rounds) and len(rounds) == len(set(rounds))
    statuses = {r["status"] for r in doc["races"]}
    assert statuses <= {"raced", "upcoming_post_quali", "scheduled"}
    # next_round = the first non-raced round
    future = [r["round"] for r in doc["races"] if r["status"] != "raced"]
    assert doc["next_round"] == (min(future) if future else None)
    for r in doc["races"]:
        assert set(r) >= {"year", "round", "name", "date", "status",
                          "n_drivers", "params", "drivers"}
        for d in r["drivers"]:
            assert set(d) >= {"driverId", "driverCode", "surname",
                              "constructorId", "grid", "p_podium",
                              "p_points", "p_out", "expected_position",
                              "sim_dnf_rate"}
            for k in ("p_podium", "p_points", "p_out", "sim_dnf_rate"):
                assert 0.0 <= d[k] <= 1.0
            assert d["p_podium"] + d["p_points"] + d["p_out"] \
                == pytest.approx(1.0, abs=1e-6)
            # pit-lane starts are clamped to the back, never the front
            assert d["expected_position"] >= 1.0
        if r["status"] == "raced":
            assert all("observed_swing" in d and "sim_swing_mean" in d
                       for d in r["drivers"])
        else:
            assert all("observed_swing" not in d and "sim_swing_mean" not in d
                       for d in r["drivers"])


@REAL
def test_future_round_grid_is_championship_order():
    """Round 12 (no quali yet) must be ordered by current championship
    points — the standings leader starts 'P1' in the simulated grid.
    (The drivers array itself is sorted by expected position; check the
    grid values as a set/permutation of 1..n plus who holds slot 1.)"""
    doc = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    r12 = [r for r in doc["races"] if r["round"] == 12][0]
    grids = [d["grid"] for d in r12["drivers"]]
    assert sorted(grids) == list(range(1, len(grids) + 1))
    p1 = [d for d in r12["drivers"] if d["grid"] == 1]
    # Antonelli leads the 2026 championship through round 11
    assert p1[0]["driverId"] == "antonelli"


@REAL
def test_artifact_deterministic():
    a = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    b = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


@REAL
def test_attribution_matches_summarize():
    from error_decomposition import (_baseline_predictions,
                                     build_decompositions, summarize)
    doc = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    preds = _baseline_predictions(str(DATASETS), 2026)
    s = summarize(build_decompositions(str(DATASETS), preds))
    # artifact rounds to 4dp
    assert doc["season_attribution"]["accuracy"] == pytest.approx(
        s["accuracy"], abs=5e-4)
    assert doc["season_attribution"]["n_misses"] == s["n_misses"]


@REAL
def test_mechanism_matches_fit():
    entries = rs.load_entries(str(DB))
    params = rs.fit_swing_params(entries[entries["year"] <= 2025])
    con = None  # placeholder to keep flake quiet
    doc = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    mech = doc["mechanism"]
    assert mech["swing_mean"] == pytest.approx(params["mean"], abs=1e-3)
    assert mech["dnf_rate"] == pytest.approx(params["dnf_rate"], abs=1e-4)


@REAL
def test_raced_probs_reproduce_simulator():
    """The artifact's per-driver probabilities for one raced round must
    equal a direct simulate_race call with the same seed and params."""
    doc = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    entries = rs.load_entries(str(DB))
    season_entries = entries[entries["year"] == 2026]
    race = [r for r in doc["races"] if r["status"] == "raced"][0]
    r_entries = season_entries[season_entries["round"] == race["round"]]
    grid = list(zip(r_entries["driverId"],
                    r_entries["grid"].fillna(0).astype(int)))
    sim = rs.simulate_race(grid, 200, doc["mechanism"]["swing_mean"],
                           doc["mechanism"]["swing_sd"],
                           doc["mechanism"]["dnf_rate"],
                           np.random.default_rng(42 + 2026 * 100
                                                 + race["round"]))
    summ = rs.summarize_simulation(sim).set_index("driverId")
    for d in race["drivers"]:
        row = summ.loc[d["driverId"]]
        assert d["p_podium"] == pytest.approx(row["p_podium"])
        assert d["p_points"] == pytest.approx(row["p_points"])


@REAL
def test_future_probs_reproduce_simulator():
    """Future rounds: same contract, from the point-in-time grid. The
    grid must be reconstructed in slot order — simulate_race assigns
    per-driver RNG columns by list position, so a different order would
    silently change every driver's randomness."""
    doc = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    race = [r for r in doc["races"]
            if r["round"] == doc["next_round"]][0]
    grid = sorted(((d["driverId"], d["grid"]) for d in race["drivers"]),
                  key=lambda g: g[1])
    sim = rs.simulate_race(grid, 200, doc["mechanism"]["swing_mean"],
                           doc["mechanism"]["swing_sd"],
                           doc["mechanism"]["dnf_rate"],
                           np.random.default_rng(42 + 2026 * 100
                                                 + race["round"]))
    summ = rs.summarize_simulation(sim).set_index("driverId")
    for d in race["drivers"]:
        assert d["p_out"] == pytest.approx(summ.loc[d["driverId"], "p_out"])


# ── serving blueprint (synthetic artifact — no real data needed) ──────────

@pytest.fixture
def api(tmp_path, monkeypatch):
    """The blueprint module with a stub artifact wired in, plus a Flask
    app that registers the blueprint exactly like flask-app/app.py does."""
    from flask import Flask
    from flask_app_stub import _install_stub_artifact
    art = tmp_path / "race_intel.json"
    _install_stub_artifact(art)
    import race_intelligence_api as api_mod
    monkeypatch.setattr(api_mod, "ARTIFACT_PATH", art)
    monkeypatch.setattr(api_mod, "_CACHE", {"mtime": None, "doc": None})
    app = Flask(__name__)
    app.register_blueprint(api_mod.race_intel_bp)
    api_mod._test_client = app.test_client  # noqa: SLF001 - test hook
    return api_mod


def test_api_season_shape(api):
    client = api._test_client()
    r = client.get("/api/race-intel/season/2026")
    assert r.status_code == 200
    doc = r.get_json()
    assert doc["season"] == 2026 and len(doc["races"]) == 2
    assert doc["next_round"] == 2
    assert "season_attribution" in doc


def test_api_race_and_drivers(api):
    client = api._test_client()
    r = client.get("/api/race-intel/race/2026/1")
    assert r.status_code == 200
    race = r.get_json()
    assert race["status"] == "raced"
    assert {d["driverId"] for d in race["drivers"]} == {"hamilton", "tsunoda"}

    r = client.get("/api/race-intel/drivers/2026/2")
    assert r.status_code == 200
    rows = r.get_json()
    assert len(rows) == 2
    assert all(set(x) == {"driverId", "p_podium", "p_points", "p_out"}
               for x in rows)


def test_api_races_index_excludes_drivers(api):
    client = api._test_client()
    r = client.get("/api/race-intel/races/2026")
    assert r.status_code == 200
    doc = r.get_json()
    assert len(doc["races"]) == 2
    assert all("drivers" not in x and "status" in x and "name" in x
               for x in doc["races"])
    assert doc["next_round"] == 2


def test_api_next_race(api):
    client = api._test_client()
    r = client.get("/api/race-intel/next/2026")
    assert r.status_code == 200
    race = r.get_json()
    assert race["round"] == 2 and race["status"] == "scheduled"


def test_api_next_race_404_when_season_complete(api, tmp_path, monkeypatch):
    from flask_app_stub import _install_stub_artifact
    art = tmp_path / "race_intel.json"
    _install_stub_artifact(art)
    doc = json.loads(art.read_text(encoding="utf-8"))
    doc["next_round"] = None
    art.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(api, "_CACHE", {"mtime": None, "doc": None})
    client = api._test_client()
    assert client.get("/api/race-intel/next/2026").status_code == 404


def test_api_404s(api):
    client = api._test_client()
    assert client.get("/api/race-intel/season/2019").status_code == 404
    assert client.get("/api/race-intel/race/2026/99").status_code == 404
    assert client.get("/api/race-intel/race/2019/1").status_code == 404
    assert client.get("/api/race-intel/races/2019").status_code == 404
    assert client.get("/api/race-intel/next/2019").status_code == 404


def test_api_503_without_artifact(tmp_path, monkeypatch):
    import race_intelligence_api as api_mod
    monkeypatch.setattr(api_mod, "ARTIFACT_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(api_mod, "_CACHE", {"mtime": None, "doc": None})
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(api_mod.race_intel_bp)
    client = app.test_client()
    r = client.get("/api/race-intel/season/2026")
    assert r.status_code == 503
    assert "not found" in r.get_json()["error"]


def test_api_picks_up_rebuilt_artifact(api, tmp_path):
    """A rebuilt artifact (new mtime) must be served without restart."""
    from flask_app_stub import _install_stub_artifact
    art = tmp_path / "race_intel.json"
    _install_stub_artifact(art)
    api._CACHE["mtime"] = None
    client = api._test_client()
    assert client.get("/api/race-intel/season/2026").status_code == 200

    doc = json.loads(art.read_text(encoding="utf-8"))
    doc["season_attribution"]["accuracy"] = 0.99
    art.write_text(json.dumps(doc), encoding="utf-8")

    r = client.get("/api/race-intel/season/2026")
    assert r.get_json()["season_attribution"]["accuracy"] == 0.99
