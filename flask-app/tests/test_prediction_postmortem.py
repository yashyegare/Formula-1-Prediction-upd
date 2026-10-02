"""
Contract tests for GET /api/me/prediction/postmortem — the personal
error-decomposition feed (item 4 of the loop plan).

The endpoint joins the user's stored grids against the race-intel
artifact's schema-v3 actual fields. Tests write a throwaway artifact
season 2026, save predictions for a fresh signup, and pin:

  - Family B auth: anonymous → 401 JSON (never the Family A 404/201 mix)
  - verdict taxonomy + hit_rate over exact/near misses
  - DNF rows carry the artifact's status/dnf_cause evidence
  - no prediction → 404, missing artifact → 503, pre-v3 artifact → 503
"""

import json

import pytest

import race_intelligence_api as ria

GRID_R1 = ["norris", "hamilton", "tsunoda", "alonso", None, None, None,
           None, None, None, None, None, None, None, None, None, None,
           None, None, None, None, None]


def _artifact_doc() -> dict:
    return {
        "schema_version": 3,
        "season": 2026,
        "n_sims": 100,
        "mechanism": {},
        "season_attribution": {},
        "next_round": 2,
        "races": [
            {"year": 2026, "round": 1, "name": "Opening GP",
             "date": "2026-03-01", "status": "raced", "n_drivers": 4,
             "params": {},
             "drivers": [
                 {"driverId": "norris", "surname": "Norris",
                  "grid": 2, "p_podium": 0.5, "p_points": 0.4, "p_out": 0.1,
                  "expected_position": 2.5, "sim_dnf_rate": 0.1,
                  "observed_swing": -6, "sim_swing_mean": 0.0,
                  "actual_position": 8, "status": "Finished",
                  "is_dnf": False, "dnf_cause": None},
                 {"driverId": "hamilton", "surname": "Hamilton",
                  "grid": 1, "p_podium": 1, "p_points": 0, "p_out": 0,
                  "expected_position": 2.0, "sim_dnf_rate": 0.1,
                  "observed_swing": -2, "sim_swing_mean": 0.0,
                  "actual_position": 3, "status": "Finished",
                  "is_dnf": False, "dnf_cause": None},
                 {"driverId": "tsunoda", "surname": "Tsunoda",
                  "grid": 10, "p_podium": 0, "p_points": 0, "p_out": 1,
                  "expected_position": 12.0, "sim_dnf_rate": 0.3,
                  "observed_swing": None, "sim_swing_mean": 0.0,
                  "actual_position": 14, "status": "Engine",
                  "is_dnf": True, "dnf_cause": "mech"},
                 {"driverId": "alonso", "surname": "Alonso",
                  "grid": 5, "p_podium": 0, "p_points": 1, "p_out": 0,
                  "expected_position": 5.0, "sim_dnf_rate": 0.0,
                  "observed_swing": 4, "sim_swing_mean": 0.0,
                  "actual_position": 1, "status": "Finished",
                  "is_dnf": False, "dnf_cause": None},
             ]},
            {"year": 2026, "round": 2, "name": "Future GP",
             "date": "2026-03-08", "status": "scheduled", "n_drivers": 3,
             "params": {}, "drivers": []},
        ],
    }


@pytest.fixture()
def intel_artifact(tmp_path, monkeypatch):
    def write(doc):
        path = tmp_path / "race_intel.json"
        if doc is not None:
            path.write_text(json.dumps(doc), encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
        monkeypatch.setattr(ria, "ARTIFACT_PATH", path)
        ria._CACHE["mtime"] = ria._CACHE["doc"] = None
    return write


def _signup(client, name):
    res = client.post("/api/auth/signup", json={
        "username": name, "email": f"{name}@example.com",
        "password": "supersecret123"})
    assert res.status_code == 201


def _save_grid(client, grids):
    res = client.post("/api/me/prediction", json={"season": 2026,
                                                  "grids": grids})
    assert res.status_code == 200


def test_anonymous_is_401(client, intel_artifact):
    intel_artifact(_artifact_doc())
    res = client.get("/api/me/prediction/postmortem?season=2026")
    assert res.status_code == 401
    assert res.is_json


def test_no_prediction_is_404(client, intel_artifact):
    intel_artifact(_artifact_doc())
    _signup(client, "pm_nopred")
    res = client.get("/api/me/prediction/postmortem?season=2026")
    assert res.status_code == 404


def test_missing_artifact_is_503(client, intel_artifact):
    intel_artifact(None)
    _signup(client, "pm_noart")
    _save_grid(client, {"2026_r1": GRID_R1})
    res = client.get("/api/me/prediction/postmortem?season=2026")
    assert res.status_code == 503


def test_pre_v3_artifact_is_503(client, intel_artifact):
    doc = _artifact_doc()
    doc["schema_version"] = 2
    intel_artifact(doc)
    _signup(client, "pm_old")
    _save_grid(client, {"2026_r1": GRID_R1})
    res = client.get("/api/me/prediction/postmortem?season=2026")
    assert res.status_code == 503
    assert "schema" in res.get_json()["error"]


def test_verdicts_and_evidence(client, intel_artifact):
    intel_artifact(_artifact_doc())
    _signup(client, "pm_full")
    # norris predicted P1 finished P8 -> over_predict; hamilton P2->P3 ->
    # near; tsunoda P3 -> DNF (Engine/mech); alonso P4 won -> under_predict
    _save_grid(client, {"2026_r1": GRID_R1, "2026_r2": GRID_R1})
    res = client.get("/api/me/prediction/postmortem?season=2026")
    assert res.status_code == 200
    body = res.get_json()
    assert body["races_scored"] == 1  # the scheduled round is not scored
    assert body["predictions_scored"] == 4
    race = body["races"][0]
    assert race["verdict_counts"] == {"over_predict": 1, "near": 1,
                                      "dnf_mech": 1, "under_predict": 1}
    miss_by_driver = {m["driverId"]: m for m in race["misses"]}
    assert miss_by_driver["tsunoda"]["status"] == "Engine"
    assert miss_by_driver["tsunoda"]["actual_position"] == 14
    assert miss_by_driver["alonso"]["verdict"] == "under_predict"
    assert set(miss_by_driver) == {"norris", "tsunoda", "alonso"}
    assert body["hit_rate"] == pytest.approx(0.25)


def test_unknown_driver_slots_are_skipped(client, intel_artifact):
    intel_artifact(_artifact_doc())
    _signup(client, "pm_skips")
    _save_grid(client, {"2026_r1": ["alonso", "unknownrookie"] + [None] * 20})
    body = client.get("/api/me/prediction/postmortem?season=2026").get_json()
    assert body["predictions_scored"] == 1
    assert body["races"][0]["verdict_counts"] == {"exact": 1}


def test_dnf_at_predicted_place_counts_exact(client, intel_artifact):
    """correct_dnf semantics: a retirement classified exactly where the
    user picked it is a hit, not a dnf miss."""
    intel_artifact(_artifact_doc())
    _signup(client, "pm_dnfexact")
    grid = [None] * 22
    grid[13] = "tsunoda"  # predicted P14, DNF'd classified P14
    _save_grid(client, {"2026_r1": grid})
    body = client.get("/api/me/prediction/postmortem?season=2026").get_json()
    assert body["races"][0]["verdict_counts"] == {"exact": 1}
    assert body["races"][0]["misses"] == []
