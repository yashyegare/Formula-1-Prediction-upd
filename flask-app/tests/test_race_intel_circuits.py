"""
Contract tests for GET /api/race-intel/circuits — the season's circuit
registry (schema v4), the stable join key Track Explorer deep links use.

States pinned here:
  - v4 artifact   → one entry per circuit, ids + coords + per-round list
  - v3 artifact   → explicit JSON 503 (the registry was not built)
  - no artifact   → JSON 503 (the shared ArtifactUnavailable contract)
"""

import json

import pytest

import race_intelligence_api as ria


def _race(rnd: int, cid: str, status: str) -> dict:
    return {
        "year": 2027, "round": rnd, "name": f"Round {rnd} GP",
        "date": f"2027-0{rnd}-15", "status": status, "n_drivers": 1,
        "circuit": {"circuitId": cid, "name": cid.replace("_", " ").title(),
                    "location": "Somewhere", "country": "Nowhere",
                    "lat": 1.5, "lng": -2.5},
        "drivers": [],
    }


def _doc(schema_version: int) -> dict:
    return {
        "schema_version": schema_version,
        "season": 2027, "n_sims": 10, "mechanism": {},
        "season_attribution": {}, "next_round": 2,
        "races": [_race(1, "albert_park", "raced"),
                  _race(2, "shanghai", "scheduled")],
    }


@pytest.fixture()
def artifact(tmp_path, monkeypatch):
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


def test_circuits_registry(client, artifact):
    artifact(_doc(4))
    resp = client.get("/api/race-intel/circuits")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["season"] == 2027
    assert [c["circuitId"] for c in body["circuits"]] == \
        ["albert_park", "shanghai"]
    first = body["circuits"][0]
    assert {"circuitId", "name", "location", "country", "lat", "lng",
            "season", "rounds"} <= set(first)
    assert first["rounds"] == [{"round": 1, "name": "Round 1 GP",
                                "date": "2027-01-15", "status": "raced"}]


def test_circuits_dedupes_repeated_circuit(client, artifact):
    doc = _doc(4)
    doc["races"].append(_race(3, "albert_park", "scheduled"))
    artifact(doc)
    body = client.get("/api/race-intel/circuits").get_json()
    albert = next(c for c in body["circuits"]
                  if c["circuitId"] == "albert_park")
    assert [r["round"] for r in albert["rounds"]] == [1, 3]


def test_circuits_503_on_pre_v4_artifact(client, artifact):
    artifact(_doc(3))
    resp = client.get("/api/race-intel/circuits")
    assert resp.status_code == 503
    assert "schema v4" in resp.get_json()["error"]


def test_circuits_503_without_artifact(client, artifact):
    artifact(None)
    resp = client.get("/api/race-intel/circuits")
    assert resp.status_code == 503
    assert resp.is_json
