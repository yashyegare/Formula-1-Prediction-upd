"""
Contract tests for GET /api/race-intel/next-round — the year-free
current-round anchor every front-end points at.

The endpoint reads whatever season race_intel.json currently holds, so
these tests repoint ARTIFACT_PATH at a throwaway fixture and pin the
three states of the loop:

  - unraced round pending  → season_complete false, that round's summary
  - season complete        → season_complete true, the LAST raced round
  - artifact missing       → explicit JSON 503 (never an empty 200)

The driver arrays are stripped from the summary by contract; the detail
lives behind /race/<year>/<round>.
"""

import json

import pytest

import race_intelligence_api as ria


def _race(rnd: int, status: str) -> dict:
    return {
        "year": 2027,
        "round": rnd,
        "name": f"Round {rnd} Grand Prix",
        "date": f"2027-0{rnd}-15",
        "status": status,
        "n_drivers": 2,
        "params": {"swing_mean": 1.0, "swing_sd": 3.0, "dnf_rate": 0.1},
        "drivers": [
            {"driverId": "verstappen", "p_podium": 0.5,
             "p_points": 0.9, "p_out": 0.1},
            {"driverId": "hamilton", "p_podium": 0.3,
             "p_points": 0.7, "p_out": 0.3},
        ],
    }


def _doc(next_round) -> dict:
    return {
        "schema_version": 2,
        "season": 2027,
        "n_sims": 100,
        "mechanism": {},
        "season_attribution": {},
        "next_round": next_round,
        "races": [_race(1, "raced"), _race(2, "upcoming_post_quali")],
    }


@pytest.fixture()
def artifact(tmp_path, monkeypatch):
    """Repoint the blueprint's artifact path at a fixture doc and reset
    the mtime cache so each test loads its own document. Passing None
    points at a file that is never written (the missing-artifact state)."""
    def write(doc):
        path = tmp_path / "race_intel.json"
        if doc is not None:
            path.write_text(json.dumps(doc), encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
        monkeypatch.setattr(ria, "ARTIFACT_PATH", path)
        ria._CACHE["mtime"] = ria._CACHE["doc"] = None
        return path
    return write


def test_next_round_pending(client, artifact):
    artifact(_doc(next_round=2))
    resp = client.get("/api/race-intel/next-round")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["season"] == 2027
    assert body["season_complete"] is False
    assert body["race"]["round"] == 2
    assert body["race"]["status"] == "upcoming_post_quali"


def test_next_round_strips_drivers(client, artifact):
    artifact(_doc(next_round=2))
    body = client.get("/api/race-intel/next-round").get_json()
    assert "drivers" not in body["race"]
    # metadata the landing card renders stays in the summary
    assert {"name", "date", "n_drivers", "params"} <= body["race"].keys()


def test_season_complete_anchors_last_raced_round(client, artifact):
    artifact(_doc(next_round=None))
    resp = client.get("/api/race-intel/next-round")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["season_complete"] is True
    assert body["race"]["round"] == 2
    assert body["race"]["status"] == "upcoming_post_quali"


def test_missing_artifact_is_json_503(client, artifact):
    artifact(None)
    resp = client.get("/api/race-intel/next-round")
    assert resp.status_code == 503
    assert resp.is_json
    assert "error" in resp.get_json()
