"""
Auth-contract tests for the two prediction endpoint families.

predictions_api.py serves TWO route families with deliberately different
auth semantics (see its module docstring). These tests make the documented
differences load-bearing — changing a status code here is a wire-contract
break for deployed frontends and must fail CI:

  Family A — /api/predictions/*   compat shim (upstream + Season Simulator)
     save:    anonymous → 201, NOTHING persisted; logged-in → persisted
     load:    anonymous → 404 (never a 401)
     locked:  anonymous → 200 {locked: false}
     lock:    anonymous → 401 JSON (state-changing)

  Family B — /api/me/prediction*  first-party, strict @login_required
     GET/POST/lock: anonymous → 401 JSON
"""

import json

from database import (
    get_connection,
    get_user_prediction,
    _fetchone,
    _is_pg,
)

SEASON = 2098  # far-future season so tests never collide with real data


def _signup_and_login(client, username):
    res = client.post("/api/auth/signup", json={
        "username": username,
        "email": f"{username}@example.com",
        "password": "supersecret123",
    })
    assert res.status_code == 201


def _prediction_row_count() -> int:
    ph = "%s" if _is_pg() else "?"
    with get_connection() as conn:
        row = _fetchone(
            conn,
            f"SELECT COUNT(*) AS n FROM predictions WHERE season = {ph}",
            (SEASON,),
        )
    return row["n"]


# ── Family A: /api/predictions/* ─────────────────────────────────────────────

class TestFamilyACompatRoutes:
    def test_save_anonymous_returns_201_and_persists_nothing(self, client):
        res = client.post("/api/predictions/save", json={
            "name": "Anonymous", "season": SEASON,
            "grid": [{"raceId": f"{SEASON}_r1", "driverId": "d1", "position": 1}],
        })
        assert res.status_code == 201
        assert res.get_json()["success"] is True
        # The load-bearing bit: anonymous saves are accepted but NOT stored.
        assert _prediction_row_count() == 0

    def test_save_logged_in_persists(self, client):
        _signup_and_login(client, "fama_save")
        res = client.post("/api/predictions/save", json={
            "name": "FamA", "season": SEASON,
            "grid": [{"raceId": f"{SEASON}_r1", "driverId": "d1", "position": 1}],
        })
        assert res.status_code == 201
        assert _prediction_row_count() == 1

    def test_load_anonymous_is_404_not_401(self, client):
        res = client.post("/api/predictions/load", json={"season": SEASON})
        assert res.status_code == 404  # upstream contract: 404, never 401

    def test_load_logged_in_without_prediction_is_404(self, client):
        _signup_and_login(client, "fama_load")
        res = client.post("/api/predictions/load", json={"season": SEASON})
        assert res.status_code == 404

    def test_load_logged_in_with_prediction_returns_grid(self, client):
        _signup_and_login(client, "fama_load2")
        client.post("/api/predictions/save", json={
            "name": "FamA", "season": SEASON,
            "grid": [{"raceId": f"{SEASON}_r1", "driverId": "d1", "position": 1}],
        })
        res = client.post("/api/predictions/load", json={"season": SEASON})
        assert res.status_code == 200
        body = res.get_json()
        assert body["season"] == SEASON
        assert body["grid"][f"{SEASON}_r1"][0] == "d1"

    def test_locked_check_anonymous_is_200_false(self, client):
        res = client.post("/api/predictions/locked", json={"season": SEASON})
        assert res.status_code == 200
        assert res.get_json() == {"locked": False}

    def test_lock_anonymous_is_401_json(self, client):
        res = client.post("/api/predictions/lock", json={
            "season": SEASON, "raceId": f"{SEASON}_r1", "positions": [],
        })
        assert res.status_code == 401
        assert res.is_json

    def test_unlock_anonymous_is_401_json(self, client):
        res = client.post("/api/predictions/unlock", json={"season": SEASON})
        assert res.status_code == 401
        assert res.is_json

    def test_lock_logged_in_creates_locked_prediction(self, client):
        _signup_and_login(client, "fama_lock")
        res = client.post("/api/predictions/lock", json={
            "season": SEASON,
            "raceId": f"{SEASON}_r1",
            "positions": [{"driverId": "d1", "position": 1}],
        })
        # 200 (locked) or 400 (window/business rejection) — never 401/500.
        assert res.status_code in (200, 400), res.get_data(as_text=True)
        if res.status_code == 200:
            pred = get_user_prediction(
                _current_user_id(client, "fama_lock"), SEASON)
            assert pred is not None and pred["locked"]


def _current_user_id(client, username) -> int:
    """Look up the user id created by _signup_and_login (same username/email)."""
    from database import get_user_by_username
    return get_user_by_username(username)["id"]


# ── Family B: /api/me/prediction* ────────────────────────────────────────────

class TestFamilyBFirstPartyRoutes:
    def test_get_prediction_anonymous_is_401_json(self, client):
        res = client.get("/api/me/prediction")
        assert res.status_code == 401
        assert res.is_json  # JSON 401, not an HTML redirect

    def test_save_prediction_anonymous_is_401_json(self, client):
        res = client.post("/api/me/prediction", json={"season": SEASON, "grids": {}})
        assert res.status_code == 401
        assert res.is_json

    def test_lock_prediction_anonymous_is_401_json(self, client):
        res = client.post("/api/me/prediction/lock", json={"season": SEASON})
        assert res.status_code == 401
        assert res.is_json

    def test_get_prediction_logged_in_empty_state(self, client):
        _signup_and_login(client, "famb_get")
        res = client.get("/api/me/prediction")
        assert res.status_code == 200
        assert res.get_json()["prediction"] is None

    def test_save_prediction_logged_in_scores_and_persists(self, client):
        _signup_and_login(client, "famb_save")
        res = client.post("/api/me/prediction", json={
            "season": SEASON,
            "grids": {f"{SEASON}_r1": ["d1", "d2"]},
            "pointsSystem": "current",
        })
        assert res.status_code == 200
        body = res.get_json()["prediction"]
        assert "scoring" in body
        assert body["scoring"]["accuracyScore"] == 0  # no results seeded → 0, no crash

    def test_save_to_locked_prediction_is_403(self, client):
        _signup_and_login(client, "famb_lock2")
        client.post("/api/me/prediction", json={"season": SEASON, "grids": {}})
        assert client.post("/api/me/prediction/lock", json={"season": SEASON}).status_code == 200
        res = client.post("/api/me/prediction", json={"season": SEASON, "grids": {}})
        assert res.status_code == 403
        assert "locked" in res.get_json()["error"].lower()
