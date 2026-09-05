"""
Tests for _score_prediction — the accuracy scoring engine behind the
leaderboard. A silent bug here corrupts every user's score, so these pin
the formula: score += max(0, 10 - |predicted_pos - actual_pos|) per driver,
accuracy = sum(scores) / sum(10 * scored_drivers) * 100.
"""

import pytest

from database import get_connection
from predictions_api import _score_prediction

SEASON = 2099  # far-future season so tests never collide with real data


def _seed_results(rows):
    """rows: list of (round_num, driver_id, position)."""
    with get_connection() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO results (year, round_num, driver_id, team_id, position, fastest_lap) "
            "VALUES (?, ?, ?, '', ?, 0)",
            [(SEASON, rnd, drv, pos) for (rnd, drv, pos) in rows],
        )
        conn.commit()


@pytest.fixture()
def seeded_results():
    """One completed race: drivers d1..d5 finish P1..P5 in round 1."""
    _seed_results([(1, "d1", 1), (1, "d2", 2), (1, "d3", 3), (1, "d4", 4), (1, "d5", 5)])
    return {f"{SEASON}_r1": ["d1", "d2", "d3", "d4", "d5"]}


def test_perfect_prediction_scores_100(seeded_results):
    s = _score_prediction(seeded_results, SEASON)
    assert s["accuracyScore"] == 100.0
    assert s["racesScored"] == 1
    assert s["exactMatches"] == 5
    assert s["totalPositions"] == 0
    assert s["raceBreakdown"] == [{"race": f"{SEASON}_r1", "score": 50, "max": 50}]


def test_partially_wrong_prediction(seeded_results):
    # d2 and d3 swapped: diffs 0,1,1,0,0 → 48/50 = 96.0, exact = d1,d4,d5 = 3
    grids = {f"{SEASON}_r1": ["d1", "d3", "d2", "d4", "d5"]}
    s = _score_prediction(grids, SEASON)
    assert s["accuracyScore"] == 96.0
    assert s["exactMatches"] == 3
    assert s["totalPositions"] == 2


def test_worst_reasonable_ordering(seeded_results):
    # Fully reversed: diffs 4,2,0,2,4 → points 6+8+10+8+6 = 38/50 = 76.0
    grids = {f"{SEASON}_r1": ["d5", "d4", "d3", "d2", "d1"]}
    s = _score_prediction(grids, SEASON)
    assert s["accuracyScore"] == 76.0
    assert s["exactMatches"] == 1


def test_off_by_one_position_scores_9(seeded_results):
    grids = {f"{SEASON}_r1": ["d2", "d1", "d3", "d4", "d5"]}  # top two swapped
    s = _score_prediction(grids, SEASON)
    # diffs 1,1,0,0,0 → 9+9+10+10+10 = 48
    assert s["raceBreakdown"][0]["score"] == 48


def test_driver_not_in_results_is_skipped(seeded_results):
    # "phantom" didn't race → excluded from both score and max
    grids = {f"{SEASON}_r1": ["d1", "d2", "d3", "d4", "phantom"]}
    s = _score_prediction(grids, SEASON)
    assert s["raceBreakdown"][0]["max"] == 40  # only 4 real drivers counted
    assert s["accuracyScore"] == 100.0


def test_race_without_results_is_not_scored(seeded_results):
    # Round 2 has no results yet → only round 1 counts
    grids = {
        f"{SEASON}_r1": ["d1", "d2", "d3", "d4", "d5"],
        f"{SEASON}_r2": ["d1", "d2", "d3", "d4", "d5"],
    }
    s = _score_prediction(grids, SEASON)
    assert s["racesScored"] == 1
    assert [b["race"] for b in s["raceBreakdown"]] == [f"{SEASON}_r1"]


def test_accuracy_averages_across_races():
    """Total accuracy is the weighted mean across all scored races, not a
    per-race average — 50/50 on one race and 25/50 on another → 75/100 = 75%."""
    _seed_results([(1, "a", 1), (1, "b", 2), (2, "a", 1), (2, "b", 2)])
    grids = {
        f"{SEASON}_r1": ["a", "b"],       # perfect: 20/20
        f"{SEASON}_r2": ["b", "a"],       # both wrong by 1: 18/20
    }
    s = _score_prediction(grids, SEASON)
    assert s["racesScored"] == 2
    assert s["accuracyScore"] == 95.0  # 38/40


def test_malformed_grid_is_ignored(seeded_results):
    grids = {f"{SEASON}_r1": "not-a-list"}
    s = _score_prediction(grids, SEASON)
    assert s["racesScored"] == 0
    assert s["accuracyScore"] == 0


def test_none_slots_in_grid_are_skipped(seeded_results):
    grids = {f"{SEASON}_r1": ["d1", None, "d3", None, "d5"]}
    s = _score_prediction(grids, SEASON)
    assert s["raceBreakdown"][0]["max"] == 30
    assert s["exactMatches"] == 3
    assert s["accuracyScore"] == 100.0


def test_no_results_at_all_gives_zero_without_crashing():
    s = _score_prediction({f"{SEASON}_r1": ["d1"]}, 2098)
    assert s["accuracyScore"] == 0
    assert s["racesScored"] == 0
    assert s["exactMatches"] == 0
