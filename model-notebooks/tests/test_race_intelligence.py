"""
Tests for the race-intelligence layer (artifact builder + serving API).

Pins the contracts:
  - artifact schema v6 (statuses raced/scheduled/next_round, driver
    field completeness, round ordering, per-race circuit registry entry,
    expected_points as the simulated positions valued on the points scale,
    circuit.traits + the track_error correlation block)
  - lap-curves artifact (schema v1: per-driver evolution vectors that
    end concentrated, sample laps bracketing lap 1 and the final lap)
  - determinism: two builds with the same seed are byte-identical
  - distribution sums ≈ 1 per driver; all probabilities in [0, 1]
  - future rounds: no swing insight fields, deterministic championship
    order grid, expected position respects pit-lane clamping
  - attribution numbers agree with error_decomposition.summarize()
  - blueprint serving: 200 shapes for season/races/race/drivers/next,
    explicit 404s for unknown season/round, 503 when the artifact is
    absent, hot reload when the artifact is rebuilt — same contracts
    for the lap-curves artifact (404 for future rounds, 503 when the
    curves file is missing while the main artifact still serves)
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
def test_artifact_schema_v6():
    doc = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    assert set(doc) >= {"schema_version", "season", "n_sims", "next_round",
                        "mechanism", "races", "season_attribution",
                        "track_error"}
    assert doc["schema_version"] == 6
    rounds = [r["round"] for r in doc["races"]]
    assert rounds == sorted(rounds) and len(rounds) == len(set(rounds))
    statuses = {r["status"] for r in doc["races"]}
    assert statuses <= {"raced", "upcoming_post_quali", "scheduled"}
    # next_round = the first non-raced round
    future = [r["round"] for r in doc["races"] if r["status"] != "raced"]
    assert doc["next_round"] == (min(future) if future else None)
    for r in doc["races"]:
        assert set(r) >= {"year", "round", "name", "date", "status",
                          "n_drivers", "params", "drivers", "circuit"}
        # v4: shared circuit registry entry on every race (raced AND
        # future — the Track Explorer join key must exist pre-race too)
        assert set(r["circuit"]) >= {"circuitId", "name", "location",
                                     "country", "lat", "lng",
                                     "explorerSlug"}
        assert r["circuit"]["circuitId"]
        # v6: shape facts ride along where the explorer covers the venue
        traits = r["circuit"].get("traits")
        if traits is not None:
            assert set(traits) == {"cornerCount", "direction",
                                   "longestStraightMeters", "lengthMeters",
                                   "altitudeMeters", "drsZones", "continent",
                                   "firstGp"}
            assert traits["cornerCount"] > 0
            assert traits["direction"] in ("Clockwise", "Counter-clockwise")
        for d in r["drivers"]:
            assert set(d) >= {"driverId", "driverCode", "surname",
                              "constructorId", "grid", "p_podium",
                              "p_points", "p_out", "expected_position",
                              "expected_points", "sim_dnf_rate"}
            for k in ("p_podium", "p_points", "p_out", "sim_dnf_rate"):
                assert 0.0 <= d[k] <= 1.0
            # v5: expected points is a mean over sims of the current-era
            # scale, so it is bounded by a race win and never negative
            assert 0.0 <= d["expected_points"] <= 25.0
            assert d["p_podium"] + d["p_points"] + d["p_out"] \
                == pytest.approx(1.0, abs=1e-6)
            # pit-lane starts are clamped to the back, never the front
            assert d["expected_position"] >= 1.0
        if r["status"] == "raced":
            assert all("observed_swing" in d and "sim_swing_mean" in d
                       for d in r["drivers"])
            # v3: the actual outcome, needed by the postmortem join
            assert all({"actual_position", "status", "is_dnf",
                        "dnf_cause"} <= set(d) for d in r["drivers"])
        else:
            assert all("observed_swing" not in d and "sim_swing_mean" not in d
                       for d in r["drivers"])
            assert all("actual_position" not in d for d in r["drivers"])


@REAL
def test_race_meta_is_year_scoped():
    """The fact_race name/circuit lookup must filter on year as well as
    round — matching on round alone shipped the oldest season's names
    (the v3 artifact labelled 2026 round 5 "Spanish GP"; it is Canada)."""
    import sqlite3
    con = sqlite3.connect(str(DB))
    try:
        expect = {row[0]: (row[1], row[2]) for row in con.execute(
            "SELECT round, name, circuitId FROM fact_race WHERE year = 2026")}
    finally:
        con.close()
    doc = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    for r in doc["races"]:
        if r["round"] in expect:
            name, cid = expect[r["round"]]
            assert r["name"] == name
            assert r["circuit"]["circuitId"] == cid


@REAL
def test_season_circuits_all_resolve_explorer_slugs():
    """Every 2026 venue must carry the Track Explorer id its deep-link
    needs. A blank slug means dim_circuit gained a venue the slug map
    never heard of — the link would silently disappear from the UI."""
    doc = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    missing = [r["circuit"]["circuitId"] for r in doc["races"]
               if not r["circuit"]["explorerSlug"]]
    assert not missing, f"no explorer slug for {missing}"


def test_explorer_slug_map_shape():
    """The map is hand-curated from a coordinate match against the
    explorer's circuit dataset, so pin its shape: ids are the explorer's
    own "<cc>-<year opened>" form, keys are Jolpica circuitIds, and an
    unmapped circuit must degrade to no link rather than a wrong one."""
    import re
    assert ri.EXPLORER_SLUGS, "slug map must not be empty"
    for cid, slug in ri.EXPLORER_SLUGS.items():
        assert cid and cid == cid.strip()
        assert re.fullmatch(r"[a-z]{2}-\d{4}", slug), (cid, slug)
    assert len(set(ri.EXPLORER_SLUGS.values())) == len(ri.EXPLORER_SLUGS), \
        "two Jolpica circuits sharing one explorer id would mis-link"


@REAL
def test_track_traits_snapshot_covers_season_venues():
    """v6's correlation is only as wide as the explorer snapshot. A venue the
    snapshot misses silently drops out of the sample, so pin coverage of the
    season's own slugs and of the fields the correlation reads."""
    traits = json.loads((DATASETS / "track_traits.json").read_text(encoding="utf-8"))
    doc = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    for slug in {r["circuit"]["explorerSlug"] for r in doc["races"]}:
        entry = traits["traits"].get(slug)
        assert entry, f"track_traits.json has no {slug} — that venue is " \
                     "invisible to the error correlation"
        for key in ("cornerCount", "longestStraightMeters", "lengthMeters",
                    "altitudeMeters", "drsZones"):
            assert isinstance(entry[key], (int, float)), (slug, key)
        assert entry["cornerCount"] > 0


@REAL
def test_track_error_rows_replay_from_published_drivers():
    """The per-round error must be recomputable from the artifact's own
    driver rows — otherwise the page is showing a number nobody can audit."""
    doc = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    by_round = {r["round"]: r for r in doc["races"]}
    rows = doc["track_error"]["rounds"]
    assert rows, "no raced round carried traits — the join is broken"
    assert [r["round"] for r in rows] == sorted(r["round"] for r in rows)
    for row in rows:
        race = by_round[row["round"]]
        errors = [abs(d["actual_position"] - d["expected_position"])
                  for d in race["drivers"]
                  if d.get("actual_position") is not None]
        assert row["n_scored"] == len(errors)
        assert row["mean_abs_position_error"] == pytest.approx(
            sum(errors) / len(errors), abs=0.011)
        assert 0.0 <= row["dnf_rate"] <= 1.0


@REAL
def test_track_error_correlation_is_bounded_and_caveated():
    doc = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    block = doc["track_error"]
    assert set(block) == {"n_rounds", "rounds", "correlation", "caveat"}
    assert block["n_rounds"] == len(block["rounds"])
    assert block["caveat"], "shape facts must never ship without their caveat"
    assert set(block["correlation"]) <= set(ri.TRACK_TRAIT_METRICS)
    for metric, entry in block["correlation"].items():
        assert entry["n"] <= block["n_rounds"]
        for key in ("pearson", "spearman"):
            value = entry[key]
            assert value is None or -1.0 <= value <= 1.0, (metric, key, value)
    # a constant trait has no correlation to report: None, never a NaN
    # reaching the JSON the frontend parses
    for entry in block["correlation"].values():
        for key in ("pearson", "spearman"):
            value = entry[key]
            assert not (isinstance(value, float) and value != value)


@REAL
def test_expected_points_is_bounded_by_its_own_distribution():
    """v5 must be the points scale applied to the same simulation the
    published buckets come from, so it has to sit inside the range that
    distribution allows: every podium chance worth at most a win, every
    points chance at most P4, and at minimum the back of each band.
    (A replay from the artifact's own fields is not possible — the RNG
    assigns draws per grid column, and the column order is not
    published — which is exactly why the value ships precomputed.)"""
    doc = ri.build_race_intel(str(DB), str(DATASETS), 2026, 200, 42)
    # 0.011 slack: expected_points is published rounded to 2dp, so a bound
    # that holds exactly before rounding can miss by up to half a cent
    for r in doc["races"]:
        for d in r["drivers"]:
            hi = 25 * d["p_podium"] + 18 * d["p_points"]
            lo = 15 * d["p_podium"] + 1 * d["p_points"]
            assert lo - 0.011 <= d["expected_points"] <= hi + 0.011, \
                (r["round"], d["driverId"], d["expected_points"], lo, hi)


def test_points_scale_is_current_era():
    assert ri.RACE_POINTS == (25, 18, 15, 12, 10, 8, 6, 4, 2, 1)
    assert ri._points_for_position(1) == 25
    assert ri._points_for_position(10) == 1
    for pos in (11, 22, 0, -1):
        assert ri._points_for_position(pos) == 0


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
    """The blueprint module with stub artifacts wired in, plus a Flask
    app that registers the blueprint exactly like flask-app/app.py does."""
    from flask import Flask
    from flask_app_stub import _install_stub_artifact, _install_stub_curves
    art = tmp_path / "race_intel.json"
    _install_stub_artifact(art)
    curves = tmp_path / "lap_curves.json"
    _install_stub_curves(curves)
    import race_intelligence_api as api_mod
    monkeypatch.setattr(api_mod, "ARTIFACT_PATH", art)
    monkeypatch.setattr(api_mod, "CURVES_PATH", curves)
    monkeypatch.setattr(api_mod, "_CACHE", {"mtime": None, "doc": None})
    monkeypatch.setattr(api_mod, "_CURVES_CACHE", {"mtime": None, "doc": None})
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


# ── lap-curves endpoint ──────────────────────────────────────────────────

def test_api_curves_shape(api):
    client = api._test_client()
    r = client.get("/api/race-intel/curves/2026/1")
    assert r.status_code == 200
    doc = r.get_json()
    assert doc["round"] == 1 and doc["n_laps"] == 10
    assert doc["sample_laps"] == [1, 5, 10]
    ham = next(d for d in doc["drivers"] if d["driverId"] == "hamilton")
    # curve rows are [lap, p_podium, p_points, p_out, expected_position]
    assert ham["curve"][0] == [1, 0.54, 0.36, 0.10, 4.8]
    # the curve ends concentrated (the replay converges by the flag)
    assert ham["curve"][-1][1:4] == [1.0, 0.0, 0.0]


def test_api_curves_404s(api):
    client = api._test_client()
    # season mismatch
    assert client.get("/api/race-intel/curves/2019/1").status_code == 404
    # raced season, unknown round
    assert client.get("/api/race-intel/curves/2026/2").status_code == 404


def test_api_curves_503_without_curves_artifact(tmp_path, monkeypatch):
    """race_intel present but lap_curves missing: the curves route is a
    503 with an error body (never a silently empty 200), while the main
    routes keep working."""
    from flask import Flask
    from flask_app_stub import _install_stub_artifact
    import race_intelligence_api as api_mod
    art = tmp_path / "race_intel.json"
    _install_stub_artifact(art)
    monkeypatch.setattr(api_mod, "ARTIFACT_PATH", art)
    monkeypatch.setattr(api_mod, "CURVES_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(api_mod, "_CACHE", {"mtime": None, "doc": None})
    monkeypatch.setattr(api_mod, "_CURVES_CACHE", {"mtime": None, "doc": None})
    app = Flask(__name__)
    app.register_blueprint(api_mod.race_intel_bp)
    client = app.test_client()
    r = client.get("/api/race-intel/curves/2026/1")
    assert r.status_code == 503
    assert "lap_curves.json not found" in r.get_json()["error"]
    assert client.get("/api/race-intel/season/2026").status_code == 200


def test_api_curves_hot_reload(api, tmp_path):
    """A rebuilt curves artifact (new mtime) is served without restart."""
    from flask_app_stub import _install_stub_curves
    curves = tmp_path / "lap_curves.json"
    _install_stub_curves(curves)
    api._CURVES_CACHE["mtime"] = None
    client = api._test_client()
    assert client.get("/api/race-intel/curves/2026/1").status_code == 200

    doc = json.loads(curves.read_text(encoding="utf-8"))
    doc["races"][0]["drivers"][0]["curve"][0][1] = 0.99
    curves.write_text(json.dumps(doc), encoding="utf-8")
    r = client.get("/api/race-intel/curves/2026/1")
    ham = next(d for d in r.get_json()["drivers"]
               if d["driverId"] == "hamilton")
    assert ham["curve"][0][1] == 0.99


def test_api_driver_curves(api):
    """Per-driver deep-dive: every raced round's curve for one driver,
    with display metadata resolved from the race-intel artifact."""
    client = api._test_client()
    r = client.get("/api/race-intel/curves/2026/driver/hamilton")
    assert r.status_code == 200
    doc = r.get_json()
    assert doc["season"] == 2026 and doc["driverId"] == "hamilton"
    assert doc["driverCode"] == "HAM" and doc["surname"] == "Hamilton"
    assert len(doc["races"]) == 1  # the stub has one raced round
    race = doc["races"][0]
    assert race["round"] == 1 and race["n_laps"] == 10
    assert race["final_position"] == 1
    assert race["curve"][-1][1:4] == [1.0, 0.0, 0.0]


def test_api_driver_curves_404s(api):
    client = api._test_client()
    # driver exists in race-intel but never raced (scheduled round only)
    assert client.get(
        "/api/race-intel/curves/2026/driver/verstappen").status_code == 404
    # unknown driver
    assert client.get(
        "/api/race-intel/curves/2026/driver/nobody").status_code == 404
    # unknown season
    assert client.get(
        "/api/race-intel/curves/2019/driver/hamilton").status_code == 404
