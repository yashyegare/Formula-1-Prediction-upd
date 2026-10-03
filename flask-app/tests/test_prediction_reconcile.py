"""
Contract tests for GET /api/me/prediction/reconcile (item 6 of the loop plan)
and for the `standings` field the Season Simulator adds to its autosave.

The reconcile endpoint is the only place the three point currencies meet:
the user's simulated standings (which only the simulator can compute), the
model's expected_points (schema v5 artifact) and real race results. Tests
sign up, save through the simulator's own route (/api/predictions/save,
Family A), then read through Family B, so the whole handoff is covered.
"""

import json

import pytest

import race_intelligence_api as ria
from database import get_connection, _execute, _fetchall, init_db, _is_pg


def _driver(driver_id, surname, expected_points, actual_position=None):
    return {"driverId": driver_id, "surname": surname, "driverCode": surname[:3].upper(),
            "constructorId": "test-team", "grid": 1, "p_podium": 0.0, "p_points": 0.0,
            "p_out": 0.0, "expected_position": 10.0, "sim_dnf_rate": 0.0,
            "sim_swing_mean": 0.0, "observed_swing": None, "dnf_cause": None,
            "status": "Finished" if actual_position else None,
            "is_dnf": False, "actual_position": actual_position,
            "expected_points": expected_points}


def _artifact_doc() -> dict:
    return {
        "schema_version": 5,
        "season": 2026,
        "n_sims": 100,
        "mechanism": {},
        "season_attribution": {},
        "next_round": 2,
        "races": [
            {"year": 2026, "round": 1, "name": "Opening GP", "date": "2026-03-01",
             "status": "raced", "n_drivers": 3, "params": {}, "circuit": {},
             "drivers": [_driver("norris", "Norris", 10.5, 1),
                         _driver("hamilton", "Hamilton", 4.5, 4),
                         _driver("alonso", "Alonso", 1.0, 11)]},
            {"year": 2026, "round": 2, "name": "Future GP", "date": "2026-03-08",
             "status": "scheduled", "n_drivers": 2, "params": {}, "circuit": {},
             "drivers": [_driver("norris", "Norris", 12.0),
                         _driver("leclerc", "Leclerc", 2.0)]},
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


def _autosave(client, standings=None, season=2026):
    """POST exactly what useAutoSave sends: a flat GridPosition[] plus the
    optional standings map."""
    body = {"grid": [
        {"raceId": "2026_r1", "position": 1, "driverId": "norris",
         "isOfficialResult": True},
        {"raceId": "2026_r1", "position": 2, "driverId": "hamilton",
         "isOfficialResult": True},
    ], "pointsSystem": "current", "season": season}
    if standings is not None:
        body["standings"] = standings
    res = client.post("/api/predictions/save", json=body)
    assert res.status_code == 201
    return res


def _rows(body):
    return {d["driverId"]: d for d in body["drivers"]}


def test_anonymous_is_401(client, intel_artifact):
    intel_artifact(_artifact_doc())
    res = client.get("/api/me/prediction/reconcile?season=2026")
    assert res.status_code == 401


def test_no_prediction_is_404(client, intel_artifact):
    intel_artifact(_artifact_doc())
    _signup(client, "rc_nopred")
    assert client.get("/api/me/prediction/reconcile?season=2026").status_code == 404


def test_missing_artifact_is_503(client, intel_artifact):
    intel_artifact(None)
    _signup(client, "rc_noart")
    _autosave(client, {"norris": 30.0})
    assert client.get("/api/me/prediction/reconcile?season=2026").status_code == 503


def test_pre_v5_artifact_is_503(client, intel_artifact):
    doc = _artifact_doc()
    doc["schema_version"] = 4
    for race in doc["races"]:
        for d in race["drivers"]:
            d.pop("expected_points")
    intel_artifact(doc)
    _signup(client, "rc_old")
    _autosave(client, {"norris": 30.0})
    res = client.get("/api/me/prediction/reconcile?season=2026")
    assert res.status_code == 503
    assert "schema" in res.get_json()["error"]


def test_three_currencies_are_joined_per_driver(client, intel_artifact):
    intel_artifact(_artifact_doc())
    _signup(client, "rc_full")
    _autosave(client, {"norris": 30.0, "alonso": 5.0})
    body = client.get("/api/me/prediction/reconcile?season=2026").get_json()

    assert body["has_simulated_standings"] is True
    assert body["rounds_in_artifact"] == 2
    assert body["raced_rounds"] == 1

    rows = _rows(body)
    # expected_points summed over every round for model_season, raced only
    # for model_raced
    assert rows["norris"]["model_season"] == 22.5
    assert rows["norris"]["model_raced"] == 10.5
    assert rows["norris"]["actual_raced"] == 25       # P1
    assert rows["hamilton"]["actual_raced"] == 12     # P4
    assert rows["alonso"]["actual_raced"] == 0        # P11 scores nothing
    assert rows["norris"]["simulated"] == 30.0
    assert rows["norris"]["sim_minus_model"] == 7.5
    assert rows["norris"]["model_minus_actual"] == -14.5
    assert rows["alonso"]["sim_minus_model"] == 4.0

    # outside the user's standings the simulated columns are null, not 0 —
    # "not predicted" must not read as "predicted nil"
    assert rows["leclerc"]["simulated"] is None
    assert rows["leclerc"]["sim_minus_model"] is None
    assert rows["leclerc"]["model_raced"] == 0.0
    assert rows["hamilton"]["surname"] == "Hamilton"

    # ranked by simulated where it exists, else by the model's season total:
    # alonso (5.0 simulated) outranks hamilton (4.5 expected, not predicted)
    assert [d["driverId"] for d in body["drivers"]] == [
        "norris", "alonso", "hamilton", "leclerc"]
    assert body["totals"] == {"simulated": 35.0, "model_season": 30.0,
                              "model_raced": 16.0, "actual_raced": 37}


def test_simulated_only_driver_still_gets_a_row(client, intel_artifact):
    intel_artifact(_artifact_doc())
    _signup(client, "rc_extra")
    _autosave(client, {"norris": 10.0, "rookie": 8.0})
    rows = _rows(client.get("/api/me/prediction/reconcile?season=2026").get_json())
    assert rows["rookie"]["model_season"] == 0.0
    assert rows["rookie"]["sim_minus_model"] == 8.0


def test_endpoint_works_without_any_standings_shipped(client, intel_artifact):
    """Family A save predates the standings field; the model/actual columns
    must still reconcile."""
    intel_artifact(_artifact_doc())
    _signup(client, "rc_bare")
    _autosave(client, None)
    body = client.get("/api/me/prediction/reconcile?season=2026").get_json()
    assert body["has_simulated_standings"] is False
    assert body["totals"]["simulated"] is None
    assert _rows(body)["norris"]["model_season"] == 22.5


def test_garbage_standings_are_rejected(client, intel_artifact):
    intel_artifact(_artifact_doc())
    _signup(client, "rc_garbage")
    _autosave(client, {"norris": "30 points", "": 5, "bad": True, "alonso": 5.0})
    body = client.get("/api/me/prediction/reconcile?season=2026").get_json()
    rows = _rows(body)
    # only the well-formed entries survive; norris is dropped rather than
    # stored as a string, so its simulated column stays null
    assert rows["norris"]["simulated"] is None
    assert "bad" not in rows
    assert "" not in rows
    assert "alonso" in rows
    assert body["has_simulated_standings"] is True


def test_save_without_standings_keeps_the_last_known_ones(client, intel_artifact):
    intel_artifact(_artifact_doc())
    _signup(client, "rc_coalesce")
    _autosave(client, {"norris": 30.0})
    _autosave(client, None)
    rows = _rows(client.get("/api/me/prediction/reconcile?season=2026").get_json())
    assert rows["norris"]["simulated"] == 30.0


@pytest.mark.skipif(_is_pg(), reason="SQLite-specific column-drop rehearsal")
def test_init_db_adds_standings_column_to_pre_existing_table(client):
    """The production database already exists, so CREATE TABLE IF NOT EXISTS
    never runs there — the additive migration is what gives it the column."""
    with get_connection() as conn:
        _execute(conn, "ALTER TABLE predictions DROP COLUMN standings_json")
        assert "standings_json" not in {
            r["name"] for r in _fetchall(conn, "PRAGMA table_info(predictions)")}
    init_db()
    with get_connection() as conn:
        assert "standings_json" in {
            r["name"] for r in _fetchall(conn, "PRAGMA table_info(predictions)")}
