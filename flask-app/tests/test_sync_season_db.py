"""
Tests for the post-race ingest (sync_season_db.sync_year) and the
token-gated POST /api/admin/sync-season that drives it on production.

Everything runs against an isolated fake season (year 2099) in the
throwaway SQLite DB from conftest, with api_get monkeypatched — no
network, and no collision with the real seeded seasons.
"""

import pytest

import sync_season_db
from database import _execute, _fetchall, get_connection, init_db

YEAR = 2099


# ── fixtures / helpers ───────────────────────────────────────────────────

def _wipe():
    init_db()
    with get_connection() as conn:
        for table in ("races", "drivers", "constructors", "results",
                      "standings", "seasons"):
            _execute(conn, f"DELETE FROM {table} WHERE year = ?", (YEAR,))
        _execute(conn, "DELETE FROM predictions WHERE season = ?", (YEAR,))
        _execute(conn, "DELETE FROM leaderboard WHERE season = ?", (YEAR,))
        _execute(conn, "DELETE FROM users WHERE username = 'syncuser'")


def _seed_season():
    """3-round season: round 1 raced, rounds 2-3 open, 2-driver roster,
    one pre-existing standings row to prove replace-vs-wipe semantics."""
    with get_connection() as conn:
        _execute(conn, "INSERT INTO seasons (year, race_count) VALUES (?, ?)",
                 (YEAR, 3))
        for rnd in (1, 2, 3):
            _execute(conn,
                     "INSERT INTO races (id, year, round_num, name, "
                     "circuit_id, country, completed) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (f"{YEAR}_r{rnd}", YEAR, rnd, f"Round {rnd} GP",
                      "fake_circuit", "Zedland", 1 if rnd == 1 else 0))
        for did, tid in (("alice", "redbull"), ("bob", "ferrari")):
            _execute(conn,
                     "INSERT INTO drivers (id, year, code, given_name, "
                     "family_name, nationality, team_id) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (did, YEAR, did[:3].upper(), "Given", did.title(),
                      "Zedish", tid))
        for tid in ("redbull", "ferrari"):
            _execute(conn,
                     "INSERT INTO constructors (id, year, name, nationality, "
                     "color) VALUES (?, ?, ?, ?, ?)",
                     (tid, YEAR, tid.title(), "Zedish", "#ffffff"))
        _execute(conn,
                 "INSERT INTO results (year, round_num, driver_id, team_id, "
                 "position, fastest_lap) VALUES (?, ?, ?, ?, ?, ?)",
                 (YEAR, 1, "alice", "redbull", 1, 0))
        _execute(conn,
                 "INSERT INTO standings (year, entity_id, entity_type, "
                 "position, points) VALUES (?, ?, ?, ?, ?)",
                 (YEAR, "alice", "driver", 1, 25.0))


def _res(did, cid, pos, fastest_lap=False):
    row = {
        "position": str(pos),
        "Driver": {"driverId": did, "code": did[:3].upper(),
                   "givenName": "Given", "familyName": did.title(),
                   "nationality": "Zedish"},
        "Constructor": {"constructorId": cid, "name": cid.title(),
                        "nationality": "Zedish"},
    }
    if fastest_lap:
        row["FastestLap"] = {"Rank": "1"}
    return row


def _patch_api(monkeypatch, results_by_round=None, driver_standings=None,
               constructor_standings=None):
    """Fake Jolpica: a round missing from results_by_round reads as
    not-yet-raced, exactly like an empty Races block upstream."""
    results_by_round = results_by_round or {}

    def fake_api_get(relative, retries=3):
        if relative.endswith("results.json"):
            rnd = int(relative.split("/")[1])
            rows = results_by_round.get(rnd)
            if rows is None:
                return {"MRData": {"RaceTable": {"Races": []}}}
            return {"MRData": {"RaceTable": {"Races": [{"Results": rows}]}}}
        if "driverStandings" in relative:
            return {"MRData": {"StandingsTable": {"StandingsLists": [
                {"DriverStandings": driver_standings or []}]}}}
        if "constructorStandings" in relative:
            return {"MRData": {"StandingsTable": {"StandingsLists": [
                {"ConstructorStandings": constructor_standings or []}]}}}
        raise AssertionError(f"unexpected api_get({relative!r})")

    monkeypatch.setattr(sync_season_db, "api_get", fake_api_get)


def _standings(entity_type):
    with get_connection() as conn:
        return {
            r["entity_id"]: (r["position"], float(r["points"]))
            for r in _fetchall(
                conn,
                "SELECT entity_id, position, points FROM standings "
                "WHERE year = ? AND entity_type = ?", (YEAR, entity_type))
        }


@pytest.fixture(autouse=True)
def _isolated_fake_season():
    """Leave no 2099 rows behind for the rest of the suite (the shared
    test DB keeps seasons/races/drivers across files)."""
    _wipe()
    yield
    _wipe()


# ── sync_year ────────────────────────────────────────────────────────────

def test_unseeded_season_raises():
    _wipe()
    with pytest.raises(ValueError, match="not seeded"):
        sync_season_db.sync_year(YEAR)


def test_ingests_raced_round_and_stops_at_first_unraced(monkeypatch):
    _wipe()
    _seed_season()
    # round 3 HAS results but must never be fetched: round 2 is the first
    # open round and is unraced → the loop stops there (never guess by date)
    _patch_api(monkeypatch, results_by_round={3: [_res("alice", "redbull", 1)]})
    summary = sync_season_db.sync_year(YEAR, rescore=False)

    assert summary["new_rounds"] == []
    with get_connection() as conn:
        completed = {
            r["round_num"]: r["completed"] for r in _fetchall(
                conn, "SELECT round_num, completed FROM races WHERE year = ?",
                (YEAR,))
        }
    assert completed == {1: 1, 2: 0, 3: 0}


def test_ingest_writes_results_and_upserts_new_roster(monkeypatch):
    _wipe()
    _seed_season()
    _patch_api(monkeypatch, results_by_round={
        2: [_res("alice", "redbull", 1, fastest_lap=True),
            _res("bob", "ferrari", 2),
            _res("dave", "mercedes", 3)],
    })
    summary = sync_season_db.sync_year(YEAR, rescore=False)

    assert summary["new_rounds"] == [2]
    with get_connection() as conn:
        rows = {
            r["driver_id"]: r["position"] for r in _fetchall(
                conn,
                "SELECT driver_id, position FROM results "
                "WHERE year = ? AND round_num = 2", (YEAR,))
        }
        assert rows == {"alice": 1, "bob": 2, "dave": 3}
        assert _fetchall(
            conn, "SELECT id FROM drivers WHERE year = ? AND id = 'dave'",
            (YEAR,))
        assert _fetchall(
            conn,
            "SELECT id FROM constructors WHERE year = ? AND id = 'mercedes'",
            (YEAR,))
        assert _fetchall(
            conn,
            "SELECT id FROM races WHERE year = ? AND round_num = 2 "
            "AND completed = 1", (YEAR,))


def test_standings_replaced_with_deterministic_zero_fill(monkeypatch):
    _wipe()
    _seed_season()
    _patch_api(
        monkeypatch,
        results_by_round={2: [_res("alice", "redbull", 1),
                              _res("dave", "mercedes", 2)]},
        driver_standings=[
            {"position": "1", "points": "40", "Driver": {"driverId": "alice"}},
            {"position": "2", "points": "20", "Driver": {"driverId": "dave"}},
        ],
        constructor_standings=[
            {"position": "1", "points": "60",
             "Constructor": {"constructorId": "redbull"}},
        ],
    )
    summary = sync_season_db.sync_year(YEAR, rescore=False)

    assert summary["standings_refreshed"] is True
    # bob is on the roster but unclassified: zero-filled after the last
    # classified position instead of vanishing from the table
    assert _standings("driver") == {
        "alice": (1, 40.0), "dave": (2, 20.0), "bob": (3, 0.0)}
    # same rule for constructors: mercedes only arrived with round 2's
    # ingest, ferrari is unclassified — both zero-fill behind redbull
    assert _standings("constructor") == {
        "redbull": (1, 60.0), "ferrari": (2, 0.0), "mercedes": (3, 0.0)}


def test_empty_standings_fetch_never_wipes_live_rows(monkeypatch):
    _wipe()
    _seed_season()
    _patch_api(monkeypatch,
               results_by_round={2: [_res("alice", "redbull", 1)]},
               driver_standings=[], constructor_standings=[])
    summary = sync_season_db.sync_year(YEAR, rescore=False)

    assert summary["standings_refreshed"] is False
    assert _standings("driver") == {"alice": (1, 25.0)}  # untouched


def test_second_run_is_a_noop(monkeypatch):
    _wipe()
    _seed_season()
    _patch_api(monkeypatch,
               results_by_round={2: [_res("alice", "redbull", 1)]})
    first = sync_season_db.sync_year(YEAR, rescore=False)
    second = sync_season_db.sync_year(YEAR, rescore=False)

    assert first["new_rounds"] == [2]
    assert second == {"year": YEAR, "new_rounds": [], "standings_refreshed":
                      False, "rescored_predictions": 0}


def test_rescore_writes_leaderboard_for_stored_predictions(monkeypatch):
    _wipe()
    _seed_season()
    with get_connection() as conn:
        _execute(conn,
                 "INSERT INTO users (username, email, password_hash) "
                 "VALUES ('syncuser', 'sync@example.test', 'hash')")
        uid = _fetchall(
            conn,
            "SELECT id FROM users WHERE username = 'syncuser'")[0]["id"]
        _execute(conn,
                 "INSERT INTO predictions (user_id, season, grids_json, "
                 "accuracy_score) VALUES (?, ?, ?, 0)",
                 (uid, YEAR, '{"2099_r1": ["alice", "bob"]}'))
    _patch_api(monkeypatch,
               results_by_round={2: [_res("alice", "redbull", 1)]})
    summary = sync_season_db.sync_year(YEAR, rescore=True)

    assert summary["rescored_predictions"] == 1
    with get_connection() as conn:
        lb = _fetchall(
            conn,
            "SELECT accuracy_score, races_scored FROM leaderboard "
            "WHERE user_id = ? AND season = ?", (uid, YEAR))
    assert len(lb) == 1
    assert lb[0]["races_scored"] >= 1


# ── POST /api/admin/sync-season ─────────────────────────────────────────

def test_endpoint_invisible_without_token(client, monkeypatch):
    monkeypatch.delenv("SYNC_ADMIN_TOKEN", raising=False)
    assert client.post("/api/admin/sync-season", json={}).status_code == 404


def test_endpoint_rejects_wrong_token(client, monkeypatch):
    monkeypatch.setenv("SYNC_ADMIN_TOKEN", "s3cret-token")
    res = client.post("/api/admin/sync-season", json={"year": YEAR},
                      headers={"X-Sync-Token": "wrong"})
    assert res.status_code == 403


def test_endpoint_runs_sync_with_good_token(client, monkeypatch):
    monkeypatch.setenv("SYNC_ADMIN_TOKEN", "s3cret-token")
    calls = {}

    def fake_sync_year(year, rescore=True):
        calls["year"] = year
        return {"year": year, "new_rounds": [13],
                "standings_refreshed": True, "rescored_predictions": 2}

    monkeypatch.setattr(sync_season_db, "sync_year", fake_sync_year)
    res = client.post("/api/admin/sync-season", json={"year": YEAR},
                      headers={"X-Sync-Token": "s3cret-token"})

    assert res.status_code == 200
    assert res.get_json()["new_rounds"] == [13]
    assert calls["year"] == YEAR


def test_endpoint_maps_unseeded_season_to_400(client, monkeypatch):
    monkeypatch.setenv("SYNC_ADMIN_TOKEN", "s3cret-token")

    def raise_value(year, rescore=True):
        raise ValueError(f"season {year} is not seeded")

    monkeypatch.setattr(sync_season_db, "sync_year", raise_value)
    res = client.post("/api/admin/sync-season", json={"year": YEAR},
                      headers={"X-Sync-Token": "s3cret-token"})

    assert res.status_code == 400
    assert "not seeded" in res.get_json()["error"]


def test_endpoint_rejects_non_integer_year(client, monkeypatch):
    monkeypatch.setenv("SYNC_ADMIN_TOKEN", "s3cret-token")
    res = client.post("/api/admin/sync-season", json={"year": "banana"},
                      headers={"X-Sync-Token": "s3cret-token"})
    assert res.status_code == 400
