"""
Regression tests for the /api/init un-seeded-year standings fallback.

Before this fix, api_init returned a hardcoded 2026-R12 snapshot for
EVERY un-seeded year — asking for 2027 would hand back 2026 drivers and
points. The constants are gone; _live_standings now reads the requested
season from Jolpica. These tests pin that behaviour with a monkeypatched
fetch (no network).
"""

import app as app_module


def _standings_payload(entries, list_key, sub_key, id_key):
    return {"MRData": {"StandingsTable": {"StandingsLists": [
        {list_key: [
            {"position": str(pos), "points": pts,
             sub_key: {id_key: eid}}
            for pos, eid, pts in entries
        ]}
    ]}}}


def test_live_standings_reads_the_requested_year_and_maps_ids(monkeypatch):
    seen_urls = []

    def fake_fetch(url):
        seen_urls.append(url)
        if "driverStandings" in url:
            return _standings_payload(
                [(1, "max_verstappen", 431.0), (2, "leclerc", 398)],
                "DriverStandings", "Driver", "driverId")
        if "constructorStandings" in url:
            return _standings_payload(
                [(1, "mclaren", 849)],
                "ConstructorStandings", "Constructor", "constructorId")
        return None

    monkeypatch.setattr(app_module, "_fetch_jolpica", fake_fetch)
    drivers, constructors = app_module._live_standings(2027)

    assert any("2027/driverStandings" in u for u in seen_urls)
    assert any("2027/constructorStandings" in u for u in seen_urls)
    # driverId normalized through DRIVER_ID_MAP, whole floats collapse to int
    assert drivers == [
        {"position": 1, "driverId": "verstappen", "points": 431},
        {"position": 2, "driverId": "leclerc", "points": 398},
    ]
    assert constructors == [
        {"position": 1, "teamId": "mclaren", "points": 849},
    ]


def test_live_standings_half_points_stay_fractional(monkeypatch):
    def fake_fetch(url):
        return _standings_payload(
            [(1, "prost", 71.5)], "DriverStandings", "Driver", "driverId")

    monkeypatch.setattr(app_module, "_fetch_jolpica", fake_fetch)
    drivers, _ = app_module._live_standings(1984)
    assert drivers == [{"position": 1, "driverId": "prost", "points": 71.5}]


def test_live_standings_empty_when_jolpica_has_none(monkeypatch):
    monkeypatch.setattr(app_module, "_fetch_jolpica", lambda url: None)
    assert app_module._live_standings(2030) == ([], [])
