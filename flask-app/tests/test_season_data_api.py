"""
Contract tests for the season-data endpoints: /api/init, /api/circuits,
/api/circuit, and the seed parser's half-points handling.

These pin the payload SHAPE the Season Simulator frontend consumes
(f1-points-calc/src/types/index.ts and store/slices/seasonDataSlice.ts).
The production incident behind them: the SQLite payload shipped with
different keys (constructorId, entityId, bare-round raceResults keys)
than the Jolpica fallback the frontend had always consumed — masked
until the seeded database was committed, because the DB path had never
run in production. If any shape here drifts, the simulator breaks even
though the API still returns HTTP 200.

The fallback-path test mocks _fetch_jolpica entirely: no test in this
file touches the network.
"""

import pytest

from database import (
    insert_constructor,
    insert_driver,
    insert_race,
    insert_result,
    insert_season,
    insert_standing,
)

YEAR = 2099  # synthetic season, unique to this file (avoids test_scoring years)
FALLBACK_YEAR = 2098  # never seeded, so /api/init exercises the fallback


def _seed_season():
    insert_season(YEAR, 2)
    insert_race(f"{YEAR}_r1", YEAR, 1, "Test GP", "test_circ",
                "Testland", "ts", f"{YEAR}-03-01", False, True)
    insert_race(f"{YEAR}_r2", YEAR, 2, "Second GP", "test_circ",
                "Testland", "ts", f"{YEAR}-03-08", False, False)
    insert_constructor("alfa_test", YEAR, "Alfa Test", "Italian", "#FF0000")
    insert_constructor("beta_test", YEAR, "Beta Test", "British", "#00FF00")
    insert_driver("nino_test", YEAR, "NIN", "Nino", "Testelli", "Italian", "alfa_test")
    insert_driver("pippo_test", YEAR, "PIP", "Pippo", "Testoni", "Italian", "beta_test")
    insert_result(YEAR, 1, "nino_test", "alfa_test", 1, True)
    insert_result(YEAR, 1, "pippo_test", "beta_test", 2, False)
    insert_standing(YEAR, "nino_test", "driver", 1, 25)
    insert_standing(YEAR, "alfa_test", "constructor", 1, 43)


@pytest.fixture()
def season(client):
    """Client with a small synthetic season seeded through the DB layer."""
    _seed_season()
    return client


def test_init_db_path_matches_frontend_contract(season):
    """SQLite path payload must match the Jolpica fallback's shape exactly —
    the only shape the frontend has ever consumed."""
    resp = season.get(f"/api/init?year={YEAR}")
    assert resp.status_code == 200
    data = resp.get_json()

    # Drivers: frontend Driver = { id, code, givenName, familyName,
    # nationality, team } — NOT { driverId, ..., teamId }.
    (driver,) = [d for d in data["drivers"] if d["id"] == "nino_test"]
    assert set(driver) >= {"id", "code", "givenName", "familyName", "nationality", "team"}
    assert driver["team"] == "alfa_test"
    assert "driverId" not in driver and "teamId" not in driver

    # Teams: frontend Team = { id, ... } — NOT constructorId.
    (team,) = [t for t in data["teams"] if t["id"] == "alfa_test"]
    assert set(team) >= {"id", "name", "color", "nationality"}
    assert "constructorId" not in team

    # raceResults keyed by race id (the same key the schedule uses and
    # pastResults[<raceId>] lookups expect) — NOT the bare round number.
    assert f"{YEAR}_r1" in data["raceResults"]
    assert all(k.startswith(f"{YEAR}_r") for k in data["raceResults"])
    row = data["raceResults"][f"{YEAR}_r1"][0]
    assert set(row) >= {"driverId", "teamId", "position", "fastestLap"}

    # Standings: driverId / teamId — NOT entityId.
    assert data["driverStandings"][0]["driverId"] == "nino_test"
    assert data["constructorStandings"][0]["teamId"] == "alfa_test"
    assert all("entityId" not in s
               for s in data["driverStandings"] + data["constructorStandings"])

    # completed derives from results availability (r1 raced, r2 didn't).
    completed = {r["id"]: r["completed"] for r in data["schedule"]}
    assert completed[f"{YEAR}_r1"] is True
    assert completed[f"{YEAR}_r2"] is False


def test_init_half_points_survive(season):
    """Fractional championship points (1984 Prost 71.5, 1991, 2009 Webber
    69.5) must not be int()-truncated anywhere in seed or serve."""
    insert_standing(YEAR, "pippo_test", "driver", 2, 71.5)
    resp = season.get(f"/api/init?year={YEAR}")
    assert resp.status_code == 200
    data = resp.get_json()
    (row,) = [s for s in data["driverStandings"] if s["driverId"] == "pippo_test"]
    assert row["points"] == 71.5


def test_circuit_slugs_shape(season):
    """data.circuits[] is what the seasonDataSlice and tracks getStaticPaths
    read; the old raceId→slug map matched no consumer."""
    resp = season.get("/api/circuits")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data.get("circuits"), list) and data["circuits"]
    for item in data["circuits"]:
        assert set(item) >= {"circuitId", "slug", "fullName", "country"}
    assert "test_circ" in {c["slug"] for c in data["circuits"]}


def test_circuit_history(season):
    resp = season.get("/api/circuit?circuitId=test_circ")
    assert resp.status_code == 200
    h = resp.get_json()
    assert h["circuitId"] == "test_circ"
    seasons = [e["season"] for e in h["editions"]]
    assert seasons == sorted(seasons, reverse=True)  # newest first
    newest = h["editions"][0]
    assert newest["results"][0]["position"] == 1
    assert newest["results"][0]["driverId"] == "nino_test"
    assert newest["results"][0]["driverName"] == "Nino Testelli"
    assert newest["results"][0]["teamName"] == "Alfa Test"
    assert h["stats"]["totalEditions"] == 1
    # The unraced round (no results) must NOT appear as an empty edition —
    # only the raced round is listed.
    assert [e["raceId"] for e in h["editions"]] == [f"{YEAR}_r1"]
    assert h["stats"]["uniqueWinners"] == 1
    assert h["stats"]["mostWinsDriver"] == {"name": "Nino Testelli", "count": 1}


def test_circuit_history_error_paths(client):
    assert client.get("/api/circuit?circuitId=nope").status_code == 404
    assert client.get("/api/circuit").status_code == 400


def test_init_fallback_merges_paginated_pages(client, monkeypatch):
    """Jolpica pages are capped at 100 result ROWS, so one race's Results
    block can straddle a page boundary. The fallback must union rows by
    round across pages, not keep only the first page's slice."""
    import app as appmod

    base = {"driverId": "nino_test", "code": "NIN", "givenName": "Nino",
            "familyName": "Testelli", "nationality": "Italian"}
    circuit = {"circuitId": "test_circ", "Location": {"country": "Testland"}}
    # Distinct drivers per row (real grids): duplicate driverIds across pages
    # are legitimately deduped by the merge, so same-id rows would defeat
    # the very straddle case under test.
    results = []
    for i in range(1, 63):
        d = dict(base)
        d["driverId"] = f"driver_{i:02d}"
        d["givenName"] = f"D{i:02d}"
        results.append({"number": str(i), "position": str(i),
                        "Driver": d,
                        "Constructor": {"constructorId": "alfa_test"}})
    # 62 rows → page 1: 60, page 2: 2
    # Row 1 keeps the base identity so drivers.json ∩ results is non-empty
    # (real Jolpica: drivers.json and results agree on driverIds).
    results[0]["Driver"] = dict(base)

    def race_payload(rows):
        return {"season": "2098", "round": "1", "raceName": "Test GP",
                "Circuit": dict(circuit), "Results": rows}

    pages = {
        f"https://api.jolpi.ca/ergast/f1/{FALLBACK_YEAR}/results.json?limit=100&offset=0":
            {"MRData": {"total": "62", "RaceTable": {"Races": [race_payload(results[:60])]}}},
        f"https://api.jolpi.ca/ergast/f1/{FALLBACK_YEAR}/results.json?limit=100&offset=60":
            {"MRData": {"total": "62", "RaceTable": {"Races": [race_payload(results[60:])]},
                        }},
        f"https://api.jolpi.ca/ergast/f1/{FALLBACK_YEAR}/drivers.json?limit=100":
            {"MRData": {"DriverTable": {"Drivers": [dict(base)]}}},
        f"https://api.jolpi.ca/ergast/f1/{FALLBACK_YEAR}/constructors.json?limit=100":
            {"MRData": {"ConstructorTable": {"Constructors": [
                {"constructorId": "alfa_test", "name": "Alfa Test",
                 "nationality": "Italian"}]}}},
        f"https://api.jolpi.ca/ergast/f1/{FALLBACK_YEAR}.json?limit=100":
            {"MRData": {"RaceTable": {"Races": [{
                "season": "2098", "round": "1", "raceName": "Test Grand Prix",
                "date": "2098-03-01", "Circuit": dict(circuit)}]}}},
    }

    monkeypatch.setattr(appmod, "_fetch_jolpica", lambda url: pages.get(url))

    resp = client.get(f"/api/init?year={FALLBACK_YEAR}")
    assert resp.status_code == 200
    data = resp.get_json()
    rows = data["raceResults"].get(f"{FALLBACK_YEAR}_r1", [])
    assert [r["position"] for r in rows] == list(range(1, 63))  # merged, not 60
    assert data["schedule"][0]["completed"] is True
    # The fallback's drivers list = drivers.json ∩ result participants:
    # only the base driver appears (the synthetic driver_NN rows aren't in
    # the mocked drivers.json), resolved to its team via the results.
    (drv,) = [d for d in data["drivers"] if d["id"] == "nino_test"]
    assert drv["team"] == "alfa_test"
