"""
Tests for the race-intelligence layer (artifact builder + serving API).

Pins the Phase-4 contracts:
  - artifact schema (season/mechanism/races/season_attribution keys,
    driver field completeness, round ordering)
  - determinism: two builds with the same seed are byte-identical
  - distribution sums ≈ 1 per driver; all probabilities in [0, 1]
  - attribution numbers agree with error_decomposition.summarize()
  - API: 200 shape for season/race/drivers, explicit 404s for unknown
    season/round, 503 when the artifact is absent
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# the serving layer lives in flask-app/
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "flask-app"))

import race_intelligence as ri  # noqa: E402
import race_simulator as rs  # noqa: E402

DB = Path(__file__).resolve().parents[1] / "datasets" / "f1_canonical.db"
DATASETS = Path(__file__).resolve().parents[1] / "datasets"

REAL = pytest.mark.skipif(
    not (DB.exists() and (DATASETS / "results.csv").exists()),
    reason="real canonical DB / datasets not present")


# ── artifact builder (real data — cheap: 11 races x 2000 sims) ────────────

@REAL
def test_artifact_schema():
    doc = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    assert set(doc) >= {"schema_version", "season", "n_sims", "mechanism",
                        "races", "season_attribution"}
    assert doc["season"] == 2026 and len(doc["races"]) > 0
    rounds = [r["round"] for r in doc["races"]]
    assert rounds == sorted(rounds) and len(rounds) == len(set(rounds))
    for r in doc["races"]:
        assert set(r) >= {"year", "round", "n_drivers", "params", "drivers"}
        for d in r["drivers"]:
            assert set(d) >= {"driverId", "grid", "p_podium", "p_points",
                              "p_out", "expected_position", "sim_dnf_rate",
                              "observed_swing", "sim_swing_mean"}
            for k in ("p_podium", "p_points", "p_out", "sim_dnf_rate"):
                assert 0.0 <= d[k] <= 1.0
            assert d["p_podium"] + d["p_points"] + d["p_out"] == pytest.approx(1.0, abs=1e-6)
            # pit-lane starts are clamped to the back, never the front
            assert d["expected_position"] >= 1.0


@REAL
def test_artifact_deterministic():
    a = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    b = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    import json
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


@REAL
def test_attribution_matches_summarize():
    from error_decomposition import _baseline_predictions, build_decompositions, summarize
    doc = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    preds = _baseline_predictions(str(DATASETS), 2026)
    s = summarize(build_decompositions(str(DATASETS), preds))
    # artifact rounds to 4dp
    assert doc["season_attribution"]["accuracy"] == pytest.approx(s["accuracy"], abs=5e-4)
    assert doc["season_attribution"]["n_misses"] == s["n_misses"]


@REAL
def test_mechanism_matches_fit():
    entries = rs.load_entries(str(DB))
    params = rs.fit_swing_params(entries[entries["year"] <= 2025])
    mech = _doc_mechanism()
    assert mech["swing_mean"] == pytest.approx(params["mean"], abs=1e-3)
    assert mech["dnf_rate"] == pytest.approx(params["dnf_rate"], abs=1e-4)


@REAL
def test_driver_probs_reproduce_simulator():
    """The artifact's per-driver probabilities for one race must equal a
    direct simulate_race call with the same seed and race params."""
    import numpy as np
    doc = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    entries = rs.load_entries(str(DB))
    season_entries = entries[entries["year"] == 2026]
    race = doc["races"][0]
    r_entries = season_entries[season_entries["round"] == race["round"]]
    grid = list(zip(r_entries["driverId"], r_entries["grid"].fillna(0).astype(int)))
    sim = rs.simulate_race(grid, 200, doc["mechanism"]["swing_mean"],
                           doc["mechanism"]["swing_sd"],
                           doc["mechanism"]["dnf_rate"],
                           np.random.default_rng(42 + 2026 * 100 + race["round"]))
    summ = rs.summarize_simulation(sim).set_index("driverId")
    for d in race["drivers"]:
        row = summ.loc[d["driverId"]]
        assert d["p_podium"] == pytest.approx(row["p_podium"])
        assert d["p_points"] == pytest.approx(row["p_points"])


# ── serving API (synthetic artifact — no real data needed) ────────────────

@pytest.fixture
def api(tmp_path, monkeypatch):
    from flask_app_stub import _install_stub_artifact  # helper below
    art = tmp_path / "race_intel.json"
    _install_stub_artifact(art)
    import race_intelligence_api as api_mod
    monkeypatch.setattr(api_mod, "ARTIFACT_PATH", art)
    monkeypatch.setattr(api_mod, "_CACHE", {"mtime": None, "doc": None})
    api_mod.app.config["TESTING"] = True
    return api_mod.app.test_client()


def test_api_season_shape(api):
    r = api.get("/api/race-intel/season/2026")
    assert r.status_code == 200
    doc = r.get_json()
    assert doc["season"] == 2026 and len(doc["races"]) == 2
    assert "season_attribution" in doc


def test_api_race_and_drivers(api):
    r = api.get("/api/race-intel/race/2026/2")
    assert r.status_code == 200
    race = r.get_json()
    assert {d["driverId"] for d in race["drivers"]} == {"verstappen", "norris"}

    r = api.get("/api/race-intel/drivers/2026/2")
    assert r.status_code == 200
    rows = r.get_json()
    assert len(rows) == 2
    assert all(set(x) == {"driverId", "p_podium", "p_points", "p_out"}
               for x in rows)


def test_api_404s(api):
    assert api.get("/api/race-intel/season/2019").status_code == 404
    assert api.get("/api/race-intel/race/2026/99").status_code == 404
    assert api.get("/api/race-intel/race/2019/1").status_code == 404


def test_api_503_without_artifact(tmp_path, monkeypatch):
    import race_intelligence_api as api_mod
    monkeypatch.setattr(api_mod, "ARTIFACT_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(api_mod, "_CACHE", {"mtime": None, "doc": None})
    api_mod.app.config["TESTING"] = True
    client = api_mod.app.test_client()
    r = client.get("/api/race-intel/season/2026")
    assert r.status_code == 503
    assert "not found" in r.get_json()["error"]


def test_api_picks_up_rebuilt_artifact(tmp_path, monkeypatch):
    """A rebuilt artifact (new mtime) must be served without restart."""
    import json as _json
    from flask_app_stub import _install_stub_artifact
    art = tmp_path / "race_intel.json"
    _install_stub_artifact(art)
    import race_intelligence_api as api_mod
    monkeypatch.setattr(api_mod, "ARTIFACT_PATH", art)
    monkeypatch.setattr(api_mod, "_CACHE", {"mtime": None, "doc": None})
    api_mod.app.config["TESTING"] = True
    client = api_mod.app.test_client()
    assert client.get("/api/race-intel/season/2026").status_code == 200

    doc = _json.loads(art.read_text(encoding="utf-8"))
    doc["season_attribution"]["accuracy"] = 0.99
    art.write_text(_json.dumps(doc), encoding="utf-8")

    r = client.get("/api/race-intel/season/2026")
    assert r.get_json()["season_attribution"]["accuracy"] == 0.99


def _doc_mechanism():
    return ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)["mechanism"]
