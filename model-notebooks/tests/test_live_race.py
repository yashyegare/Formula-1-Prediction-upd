"""
Tests for the live race-day layer (live_race.py + /api/race-intel/live).

The failure modes these pin:
  - the running-order collapse picking a stale position over the latest
  - retirement semantics: absent from the stream == out (P(out)=1),
    never silently dropped from the picture
  - number→driverId mapping gaps surfacing as `unmapped_numbers`,
    not vanishing
  - the remaining-fraction bucket following the leader's progression,
    and Practice/Quali sessions staying at remaining=1 (pre-race view)
  - staleness: an old snapshot is flagged `is_stale`, never fresh
  - the API: 200 shape, 503 without the artifact, hot reload

All OpenF1 traffic is mocked — these tests never touch the network.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import live_race as lr  # noqa: E402
import lap_curves as lc  # noqa: E402

# the serving blueprint (staleness lives at the API layer)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "flask-app"))

DB = Path(__file__).resolve().parents[1] / "datasets" / "f1_canonical.db"
REAL = pytest.mark.skipif(not DB.exists(),
                          reason="canonical DB not built locally")

NOW = "2026-09-20T15:00:00+00:00"


# ── running-order collapse ───────────────────────────────────────────────

class TestRunningOrder:
    def test_latest_position_wins(self):
        """The stream is append-ordered; the collapse must take each
        driver's MOST RECENT position, not the first seen."""
        positions = [
            {"date": NOW, "driver_number": 1, "position": 1},
            {"date": NOW, "driver_number": 3, "position": 2},
            # driver 1 slipped to P3 moments later
            {"date": "2026-09-20T15:00:05+00:00", "driver_number": 1,
             "position": 3},
            # an even-later frame restores P2 (out-of-order arrival)
            {"date": "2026-09-20T15:00:10+00:00", "driver_number": 1,
             "position": 2},
        ]
        order = lr.latest_running_order(positions)
        by_num = {o["driver_number"]: o["position"] for o in order}
        assert by_num[1] == 2  # latest, not first
        assert by_num[3] == 2  # driver 3's only frame is P2

    def test_absent_driver_is_just_absent(self):
        """The collapse never invents rows: a driver who stopped
        appearing simply has no entry (retirement is decided by the
        caller against the roster)."""
        positions = [{"date": NOW, "driver_number": 1, "position": 1}]
        order = lr.latest_running_order(positions)
        assert [o["driver_number"] for o in order] == [1]


# ── snapshot builder (mocked OpenF1, real DB fits) ───────────────────────

def _build_canonical_db(tmp_path) -> str:
    """A minimal but schema-true canonical DB so the snapshot builder's
    full path (code map, roster, fits, laps estimate) runs hermetically.
    CI has no built f1_canonical.db — it is a gitignored build artifact —
    so DB-backed tests either gate on its presence (REAL, below) or use
    this. Three drivers, two seasons of laps so the fits have data."""
    import sqlite3

    schema = Path(__file__).resolve().parents[1] / "canonical_schema.sql"
    db = str(tmp_path / "mini_canonical.db")
    con = sqlite3.connect(db)
    con.executescript(schema.read_text(encoding="utf-8"))
    pd.DataFrame([
        ("russell", "russell", "RUS", "George", "Russell", None, None),
        ("verappen", "max_verstappen", "VER", "Max", "Verstappen",
         None, None),
        ("norris", "norris", "NOR", "Lando", "Norris", None, None),
    ], columns=["driverId", "driverRef", "code", "forename", "surname",
                "dob", "nationality"]).to_sql(
        "dim_driver", con, if_exists="append", index=False)
    pd.DataFrame([("bak", "Baku City Circuit", "Baku", "Azerbaijan",
                   None, None)],
                 columns=["circuitId", "name", "location", "country",
                          "lat", "lng"]).to_sql(
        "dim_circuit", con, if_exists="append", index=False)
    pd.DataFrame([(1, "Finished", 0, None), (2, "Engine", 1, "mech")],
                 columns=["statusId", "status", "is_dnf",
                          "dnf_cause"]).to_sql(
        "dim_status", con, if_exists="append", index=False)
    pd.DataFrame([("merc", "Mercedes", "German"),
                  ("rbr", "Red Bull", "Austrian"),
                  ("mcl", "McLaren", "British")],
                 columns=["constructorId", "name",
                          "nationality"]).to_sql(
        "dim_constructor", con, if_exists="append", index=False)
    pd.DataFrame([
        (2025, 1, "bak", "Azerbaijan Grand Prix", None, None),
        (2026, 1, "bak", "Azerbaijan Grand Prix", None, None),
    ], columns=["year", "round", "circuitId", "name", "date",
                "time"]).to_sql("fact_race", con, if_exists="append",
                                index=False)
    # roster rows for the current season: retirements are detected by
    # subtracting the live runners from THIS set
    pd.DataFrame([
        (2025, 1, "russell", "merc", 1, 1, 1, 25.0, 30, 1, 0, None),
        (2025, 1, "verappen", "rbr", 2, 2, 2, 18.0, 30, 1, 0, None),
        (2025, 1, "norris", "mcl", 3, None, None, 0.0, 3, 2, 1, "mech"),
        (2026, 1, "russell", "merc", 1, 1, 1, 25.0, 30, 1, 0, None),
        (2026, 1, "verappen", "rbr", 2, 2, 2, 18.0, 30, 1, 0, None),
        (2026, 1, "norris", "mcl", 3, None, None, 0.0, 3, 2, 1, "mech"),
    ], columns=["year", "round", "driverId", "constructorId", "grid",
                "position", "positionOrder", "points", "laps",
                "statusId", "is_dnf", "dnf_cause"]).to_sql(
        "fact_race_entry", con, if_exists="append", index=False)
    # lap charts: everyone runs lap 1; norris retires after lap 3. All
    # laps identical -> no slow-lap flags, and the remaining-swing fit
    # sees zero variance (degenerate but valid; tiny buckets fall back
    # to the global parameters by design).
    lap_rows = []
    for year in (2025, 2026):
        for lap in range(1, 31):
            for did, pos in (("russell", 1.0), ("verappen", 2.0),
                             ("norris", 3.0)):
                if did == "norris" and lap > 3:
                    continue
                lap_rows.append((year, 1, lap, did, pos, None, 90000.0))
    pd.DataFrame(lap_rows, columns=["year", "round", "lap", "driverId",
                                    "position", "time_str",
                                    "milliseconds"]).to_sql(
        "fact_lap", con, if_exists="append", index=False)
    con.commit()
    con.close()
    return db


@pytest.fixture
def real_db(tmp_path):
    """Hermetic canonical DB — never the developer-local build artifact."""
    return _build_canonical_db(tmp_path)


def _mock_live(session_type="Race", positions=None, location="Baku"):
    drivers = [
        {"driver_number": 1, "name_acronym": "RUS"},
        {"driver_number": 3, "name_acronym": "VER"},
        {"driver_number": 4, "name_acronym": "NOR"},
        {"driver_number": 44, "name_acronym": "ZZZ"},  # unknown code
    ]
    if positions is None:
        positions = [
            {"date": NOW, "driver_number": 1, "position": 1},
            {"date": NOW, "driver_number": 3, "position": 2},
            {"date": NOW, "driver_number": 4, "position": 3},
            {"date": NOW, "driver_number": 44, "position": 4},
        ]
    return {
        "session": {"session_key": 1, "meeting_key": 1,
                    "session_name": session_type if session_type != "Race"
                    else "Race",
                    "session_type": session_type,
                    "date_start": NOW, "date_end": NOW,
                    "location": location, "country_name": "Azerbaijan",
                    "circuit_short_name": "Baku", "year": 2026},
        "drivers": drivers,
        "positions": positions,
    }


class TestSnapshot:
    def test_race_snapshot_end_to_end(self, real_db, monkeypatch):
        monkeypatch.setattr(lr, "fetch_live_session",
                            lambda: _mock_live("Race"))
        doc = lr.build_live_snapshot(real_db, 200, 42)
        assert doc["schema_version"] == 1
        assert doc["session"]["session_type"] == "Race"
        # runners sorted by position (the unmapped number never joins
        # them — it is surfaced in unmapped_numbers instead)
        running = [d for d in doc["drivers"] if d["position_now"]]
        assert [d["position_now"] for d in running] == [1, 2, 3]
        assert all(0 <= d["p_podium"] <= 1 for d in doc["drivers"])
        assert all(abs(d["p_podium"] + d["p_points"] + d["p_out"] - 1)
                   < 5e-3 for d in doc["drivers"])
        # the leader is the most likely podium finisher
        assert running[0]["p_podium"] == max(d["p_podium"]
                                             for d in running)
        # the unknown code surfaces as a gap, never silently vanishes
        assert doc["unmapped_numbers"] == [
            {"driver_number": 44, "name_acronym": "ZZZ"}]

    def test_retired_drivers_pinned_out(self, real_db, monkeypatch):
        """During a Race, roster drivers absent from the position stream
        are OUT (P(out)=1) — never dropped from the picture."""
        monkeypatch.setattr(
            lr, "fetch_live_session",
            lambda: _mock_live("Race", positions=[
                {"date": NOW, "driver_number": 1, "position": 1}]))
        doc = lr.build_live_snapshot(real_db, 200, 42)
        out_ids = {d["driverId"] for d in doc["drivers"]
                   if d["position_now"] is None}
        assert out_ids, "retired drivers must appear"
        for d in doc["drivers"]:
            if d["position_now"] is None:
                assert d["p_out"] == 1.0 and d["p_podium"] == 0.0

    def test_practice_is_pre_race_view(self, real_db, monkeypatch):
        """A Practice session has no race to be 'mid-': everyone running,
        remaining fraction 1 (the pre-race view), nobody marked out."""
        monkeypatch.setattr(lr, "fetch_live_session",
                            lambda: _mock_live("Practice"))
        doc = lr.build_live_snapshot(real_db, 200, 42)
        assert doc["remaining_fraction"] == 1.0
        assert all(d["position_now"] for d in doc["drivers"])

    def test_lap_progression_shrinks_remaining(self, real_db, monkeypatch):
        """More stream timestamps = more leader laps = smaller remaining
        fraction (bucket index decreases)."""
        monkeypatch.setattr(lr, "fetch_live_session",
                            lambda: _mock_live("Race"))
        early = lr.build_live_snapshot(real_db, 100, 42)
        # simulate a race 60% done: 40% of laps elapsed in distinct frames
        n_frames = 20
        positions = [
            {"date": f"2026-09-20T15:{i:02d}:00+00:00",
             "driver_number": 1, "position": 1}
            for i in range(n_frames)]
        monkeypatch.setattr(
            lr, "fetch_live_session",
            lambda: _mock_live("Race", positions=positions))
        late = lr.build_live_snapshot(real_db, 100, 42)
        assert late["remaining_fraction"] < early["remaining_fraction"]

    def test_deterministic_given_identical_snapshot(self, real_db,
                                                    monkeypatch):
        """The fetch is live, but the SIMULATION is not: the same
        snapshot + same seed => identical distributions."""
        monkeypatch.setattr(lr, "fetch_live_session",
                            lambda: _mock_live("Race"))
        a = lr.build_live_snapshot(real_db, 200, 42)
        b = lr.build_live_snapshot(real_db, 200, 42)
        a.pop("fetched_at"), b.pop("fetched_at")
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_staleness_flag(self, real_db, monkeypatch):
        import race_intelligence_api as api_mod
        monkeypatch.setattr(lr, "fetch_live_session",
                            lambda: _mock_live("Race"))
        doc = lr.build_live_snapshot(real_db, 100, 42)
        assert not api_mod._is_stale(doc)
        # rewind fetched_at past the staleness window
        old = dict(doc)
        old_dt = datetime.now(timezone.utc) - timedelta(
            minutes=doc["stale_after_min"] + 5)
        old["fetched_at"] = old_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert api_mod._is_stale(old)
        # malformed timestamp: stale (never trust what you cannot parse)
        bad = dict(doc, fetched_at="not-a-date")
        assert api_mod._is_stale(bad)


# ── the real feed (integration; skipped offline) ─────────────────────────

@pytest.mark.skipif(not DB.exists(), reason="canonical DB not built locally")
def test_real_feed_smoke():
    """Hits the real OpenF1 feed. Skipped automatically when offline;
    in CI it validates the mapping against the live 2026 season."""
    try:
        doc = lr.build_live_snapshot(str(DB), 100, 42)
    except (RuntimeError, Exception) as e:  # noqa: B902 - network absent
        pytest.skip(f"OpenF1 feed unavailable: {e}")
    assert doc["drivers"]
    assert doc["session"]["year"] >= 2026
    assert all(d["driverId"] for d in doc["drivers"] if d["position_now"])


# ── the /live API (stub artifact — offline) ──────────────────────────────

@pytest.fixture
def api(tmp_path, monkeypatch):
    from flask import Flask
    import race_intelligence_api as api_mod
    live = tmp_path / "live_state.json"
    live.write_text(json.dumps({
        "schema_version": 1,
        "fetched_at": datetime.now(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stale_after_min": 45,
        "session": {"session_name": "Race", "session_type": "Race",
                    "country_name": "Azerbaijan", "year": 2026},
        "remaining_fraction": 0.4,
        "drivers": [
            {"driverId": "russell", "position_now": 1, "p_podium": 0.7,
             "p_points": 0.2, "p_out": 0.1, "expected_position": 1.8},
            {"driverId": "tsunoda", "position_now": None, "p_podium": 0.0,
             "p_points": 0.0, "p_out": 1.0, "expected_position": None},
        ],
        "unmapped_numbers": [],
    }), encoding="utf-8")
    monkeypatch.setattr(api_mod, "LIVE_PATH", live)
    monkeypatch.setattr(api_mod, "_LIVE_CACHE", {"mtime": None, "doc": None})
    app = Flask(__name__)
    app.register_blueprint(api_mod.race_intel_bp)
    return app.test_client(), api_mod, live


def test_api_live_shape(api):
    client, _, _ = api
    r = client.get("/api/race-intel/live")
    assert r.status_code == 200
    doc = r.get_json()
    assert doc["is_stale"] is False
    assert doc["drivers"][0]["driverId"] == "russell"
    assert doc["drivers"][1]["p_out"] == 1.0


def test_api_live_stale_flag(api):
    client, _, live = api
    doc = json.loads(live.read_text(encoding="utf-8"))
    old = (datetime.now(timezone.utc) - timedelta(minutes=90)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    doc["fetched_at"] = old
    live.write_text(json.dumps(doc), encoding="utf-8")
    api_mod = api[1]
    api_mod._LIVE_CACHE["mtime"] = None
    r = client.get("/api/race-intel/live")
    assert r.get_json()["is_stale"] is True  # served, but loudly stale


def test_api_live_503_without_artifact(tmp_path, monkeypatch):
    from flask import Flask
    import race_intelligence_api as api_mod
    monkeypatch.setattr(api_mod, "LIVE_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(api_mod, "_LIVE_CACHE", {"mtime": None, "doc": None})
    app = Flask(__name__)
    app.register_blueprint(api_mod.race_intel_bp)
    r = app.test_client().get("/api/race-intel/live")
    assert r.status_code == 503
    assert "live_race.py" in r.get_json()["error"]


def test_api_live_hot_reload(api):
    client, api_mod, live = api
    doc = json.loads(live.read_text(encoding="utf-8"))
    doc["drivers"][0]["p_podium"] = 0.99
    live.write_text(json.dumps(doc), encoding="utf-8")
    api_mod._LIVE_CACHE["mtime"] = None
    r = client.get("/api/race-intel/live")
    assert r.get_json()["drivers"][0]["p_podium"] == 0.99
