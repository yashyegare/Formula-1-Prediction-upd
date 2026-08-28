"""
Predictions and Leaderboard API for F1 Race Predictor.

Users can:
  - Save their season predictions (which driver finishes where in each race)
  - Lock predictions before a race (no more edits)
  - Get scored server-side against real results
  - View a public leaderboard ranked by accuracy

Scoring formula:
  For each race with real results, for each driver in the prediction:
    score += max(0, 10 - abs(predicted_position - actual_position))
  Max possible score per race: 10 * number_of_drivers_matched
  Total accuracy = sum(scores) / sum(max_scores) * 100 (percentage)
"""

import json
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from database import (
    save_prediction, get_user_prediction, get_prediction,
    lock_prediction, get_all_predictions,
    update_leaderboard, get_leaderboard, get_leaderboard_stats,
    get_season_init_data, get_connection,
)

predictions_bp = Blueprint("predictions", __name__)


# ── Accuracy scoring ─────────────────────────────────────────────────────

def _score_prediction(grids: dict, season: int) -> dict:
    """
    Score a prediction against real race results.

    Args:
        grids: dict of {race_id: [driver_id_p1, driver_id_p2, ...]}
        season: the season year

    Returns:
        {
            "accuracyScore": float (0-100),
            "racesScored": int,
            "exactMatches": int,
            "totalPositions": int,
            "raceBreakdown": [{"race": str, "score": int, "max": int}, ...]
        }
    """
    with get_connection() as conn:
        result_rows = conn.execute(
            "SELECT round_num, driver_id, position FROM results "
            "WHERE year = ? ORDER BY round_num, position", (season,)
        ).fetchall()

    # Build real results: {race_id: {driver_id: position}}
    real_results: dict[str, dict[str, int]] = {}
    for r in result_rows:
        race_id = f"{season}_r{r['round_num']}"
        real_results.setdefault(race_id, {})[r["driver_id"]] = r["position"]

    total_score = 0
    total_max = 0
    exact_matches = 0
    total_positions = 0
    breakdown = []

    for race_id, predicted_grid in grids.items():
        if not isinstance(predicted_grid, list):
            continue

        real_grid = real_results.get(race_id)
        if not real_grid:
            continue  # No real results yet for this race

        race_score = 0
        race_max = 0

        for pos_idx, driver_id in enumerate(predicted_grid):
            if not driver_id:
                continue
            predicted_pos = pos_idx + 1
            actual_pos = real_grid.get(driver_id)
            if actual_pos is None:
                continue  # Driver didn't race this round

            race_max += 10
            position_diff = abs(predicted_pos - actual_pos)
            points = max(0, 10 - position_diff)
            race_score += points
            total_positions += position_diff

            if predicted_pos == actual_pos:
                exact_matches += 1

        total_score += race_score
        total_max += race_max

        breakdown.append({
            "race": race_id,
            "score": race_score,
            "max": race_max,
        })

    accuracy = (total_score / total_max * 100) if total_max > 0 else 0

    return {
        "accuracyScore": round(accuracy, 2),
        "racesScored": len(breakdown),
        "exactMatches": exact_matches,
        "totalPositions": total_positions,
        "raceBreakdown": breakdown,
    }


# ── Prediction routes ────────────────────────────────────────────────────

@predictions_bp.route("/api/predictions", methods=["GET"])
def list_predictions():
    """List predictions for a season (public, used by upstream frontend)."""
    season = request.args.get("season", 2026, type=int)
    preds = get_all_predictions(season)

    entries = []
    for i, p in enumerate(preds):
        entries.append({
            "rank": i + 1,
            "userId": p["user_id"],
            "name": p.get("display_name") or p.get("username", "Anonymous"),
            "image": None,
            "racesScored": p.get("races_scored", 0) if "races_scored" in p else 0,
            "accuracy": p.get("accuracy_score", 0) if "accuracy_score" in p else 0,
            "exactMatches": p.get("exact_matches", 0) if "exact_matches" in p else 0,
            "totalPositions": p.get("total_positions", 0) if "total_positions" in p else 0,
        })

    return jsonify({
        "entries": entries,
        "pendingEntries": [],
        "currentPage": 1,
        "totalPages": 1,
        "totalUsers": len(entries),
        "season": season,
    })


@predictions_bp.route("/api/predictions/save", methods=["POST", "OPTIONS"])
def api_predictions_save():
    """Save a prediction (proxy route for upstream frontend compatibility)."""
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "Anonymous").strip()
    grid = data.get("grid", [])
    season = data.get("season", 2026)

    # If user is logged in, save to their account
    if current_user.is_authenticated:
        grids = {}
        for i, pos in enumerate(grid):
            if isinstance(pos, dict):
                race_id = pos.get("raceId", str(i))
                driver_id = pos.get("driverId")
                position = pos.get("position", i + 1)
                if driver_id:
                    if race_id not in grids:
                        grids[race_id] = [None] * 22
                    idx = position - 1 if isinstance(position, int) and position > 0 else i
                    if 0 <= idx < 22:
                        grids[race_id][idx] = driver_id

        save_prediction(current_user.id, season, json.dumps(grids))

    return jsonify({"success": True, "version": 1}), 201


@predictions_bp.route("/api/predictions/load", methods=["POST", "OPTIONS"])
def api_predictions_load():
    """Load a prediction (proxy route for upstream frontend compatibility)."""
    data = request.get_json(force=True, silent=True) or {}

    if current_user.is_authenticated:
        season = data.get("season", 2026)
        pred = get_user_prediction(current_user.id, season)
        if pred:
            return jsonify({
                "version": "1",
                "timestamp": pred.get("created_at", ""),
                "grid": json.loads(pred["grids_json"]) if pred.get("grids_json") else {},
                "pointsSystem": pred.get("points_system", "current"),
                "season": season,
            })

    return jsonify(None), 404


@predictions_bp.route("/api/predictions/locked", methods=["POST", "OPTIONS"])
def api_predictions_locked():
    """Check if a prediction is locked (proxy route compatibility)."""
    data = request.get_json(force=True, silent=True) or {}
    if current_user.is_authenticated:
        season = data.get("season", 2026)
        pred = get_user_prediction(current_user.id, season)
        if pred:
            return jsonify({
                "locked": bool(pred.get("locked")),
                "lockedAt": pred.get("locked_at"),
            })
    return jsonify({"locked": False})


@predictions_bp.route("/api/predictions/lock", methods=["POST", "OPTIONS"])
def api_lock_prediction():
    """Lock a prediction for a race (Season Simulator compat).
    Only allowed within 1 hour before race start."""
    import datetime as _dt
    data = request.get_json(force=True, silent=True) or {}
    if not current_user.is_authenticated:
        return jsonify({"error": "Login required"}), 401
    season = data.get("season", 2026)
    race_id = data.get("raceId", "")
    positions = data.get("positions", [])

    # Check if race date allows locking (within 1 hour before start)
    if race_id:
        parts = race_id.split("_")  # e.g. "2026_r13"
        if len(parts) == 2:
            try:
                year = int(parts[0])
                rnd = int(parts[1].replace("r", ""))
                with get_connection() as conn:
                    row = conn.execute(
                        "SELECT date FROM races WHERE year = ? AND round_num = ?",
                        (year, rnd)
                    ).fetchone()
                if row and row["date"]:
                    race_date = _dt.datetime.strptime(row["date"], "%Y-%m-%d")
                    lock_window = race_date - _dt.timedelta(hours=1)
                    now = _dt.datetime.now()
                    if now < lock_window:
                        days_left = (lock_window - now).days
                        return jsonify({
                            "error": f"Cannot lock yet. Locking opens 1 hour before race start ({row['date']}). {days_left} days remaining."
                        }), 400
            except (ValueError, IndexError):
                pass  # Skip date check if parsing fails

    pred = get_user_prediction(current_user.id, season)
    if pred and pred.get("locked"):
        return jsonify({"error": "Already locked"}), 400

    # Store locked positions in grids_json under the race_id
    grids = json.loads(pred["grids_json"]) if pred and pred.get("grids_json") else {}
    locked_grid = [None] * 22
    for pos in positions:
        if isinstance(pos, dict):
            driver_id = pos.get("driverId")
            position = pos.get("position", 0) - 1
            if driver_id and 0 <= position < 22:
                locked_grid[position] = driver_id
    grids[race_id] = locked_grid

    save_prediction(current_user.id, season, json.dumps(grids))
    # Re-fetch to get the id
    pred2 = get_user_prediction(current_user.id, season)
    if pred2:
        lock_prediction(pred2["id"])

    return jsonify({"success": True, "raceId": race_id, "lockedAt": str(__import__('datetime').datetime.now())})


@predictions_bp.route("/api/predictions/unlock", methods=["POST", "OPTIONS"])
def api_unlock_prediction():
    """Unlock a prediction (Season Simulator compat)."""
    data = request.get_json(force=True, silent=True) or {}
    if not current_user.is_authenticated:
        return jsonify({"error": "Login required"}), 401
    # For simplicity, unlock sets the whole season prediction as unlocked
    pred = get_user_prediction(current_user.id, data.get("season", 2026))
    if pred:
        from database import get_connection
        with get_connection() as conn:
            conn.execute("UPDATE predictions SET locked = 0, locked_at = NULL WHERE id = ?", (pred["id"],))
    return jsonify({"success": True})


# ── Authenticated prediction routes ─────────────────────────────────────

@predictions_bp.route("/api/me/prediction", methods=["GET"])
@login_required
def get_my_prediction():
    """Get the current user's prediction for a season."""
    season = request.args.get("season", 2026, type=int)
    pred = get_user_prediction(current_user.id, season)
    if not pred:
        return jsonify({"prediction": None})

    grids = json.loads(pred["grids_json"]) if pred.get("grids_json") else {}

    # Score it
    scoring = _score_prediction(grids, season)

    return jsonify({
        "prediction": {
            "id": pred["id"],
            "season": pred["season"],
            "grids": grids,
            "pointsSystem": pred.get("points_system", "current"),
            "locked": bool(pred.get("locked")),
            "lockedAt": pred.get("locked_at"),
            "createdAt": pred["created_at"],
            "updatedAt": pred["updated_at"],
            "scoring": scoring,
        }
    })


@predictions_bp.route("/api/me/prediction", methods=["POST"])
@login_required
def save_my_prediction():
    """Save the current user's prediction for a season."""
    data = request.get_json(force=True, silent=True) or {}
    season = data.get("season", 2026)
    grids = data.get("grids", {})
    points_system = data.get("pointsSystem", "current")

    # Check if locked
    existing = get_user_prediction(current_user.id, season)
    if existing and existing.get("locked"):
        return jsonify({"error": "Prediction is locked and cannot be edited"}), 403

    pred = save_prediction(current_user.id, season, json.dumps(grids), points_system)

    # Update leaderboard score
    scoring = _score_prediction(grids, season)
    update_leaderboard(
        current_user.id, season,
        scoring["accuracyScore"], scoring["racesScored"],
        scoring["exactMatches"], scoring["totalPositions"],
    )

    return jsonify({
        "prediction": {
            "id": pred["id"],
            "scoring": scoring,
        }
    })


@predictions_bp.route("/api/me/prediction/lock", methods=["POST"])
@login_required
def lock_my_prediction():
    """Lock the current user's prediction for a season (no more edits)."""
    data = request.get_json(force=True, silent=True) or {}
    season = data.get("season", 2026)

    pred = get_user_prediction(current_user.id, season)
    if not pred:
        return jsonify({"error": "No prediction found for this season"}), 404
    if pred.get("locked"):
        return jsonify({"error": "Already locked"}), 400

    lock_prediction(pred["id"])

    # Score and update leaderboard
    grids = json.loads(pred["grids_json"]) if pred.get("grids_json") else {}
    scoring = _score_prediction(grids, season)
    update_leaderboard(
        current_user.id, season,
        scoring["accuracyScore"], scoring["racesScored"],
        scoring["exactMatches"], scoring["totalPositions"],
    )

    return jsonify({"ok": True, "lockedAt": pred.get("locked_at")})


# ── Leaderboard routes ───────────────────────────────────────────────────

@predictions_bp.route("/api/leaderboard", methods=["GET"])
def api_leaderboard():
    """Get the public leaderboard for a season."""
    season = request.args.get("season", 2026, type=int)
    limit = request.args.get("limit", 50, type=int)

    entries = get_leaderboard(season, limit)
    stats = get_leaderboard_stats(season)

    return jsonify({
        "entries": [
            {
                "rank": e.get("rank") or i + 1,
                "userId": e["user_id"],
                "name": e.get("display_name") or e.get("username", "Anonymous"),
                "image": None,
                "racesScored": e["races_scored"],
                "accuracy": e["accuracy_score"],
                "exactMatches": e["exact_matches"],
                "totalPositions": e["total_positions"],
            }
            for i, e in enumerate(entries)
        ],
        "pendingEntries": [],
        "currentPage": 1,
        "totalPages": 1,
        "totalUsers": stats["totalPredictors"],
        "season": season,
        "leader": stats.get("leader"),
    })


@predictions_bp.route("/api/leaderboard/stats", methods=["GET"])
def leaderboard_stats():
    """Get leaderboard summary stats."""
    season = request.args.get("season", 2026, type=int)
    return jsonify(get_leaderboard_stats(season))


@predictions_bp.route("/api/leaderboard/score", methods=["POST"])
@login_required
def score_my_prediction():
    """Manually trigger a re-score of the current user's prediction."""
    data = request.get_json(force=True, silent=True) or {}
    season = data.get("season", 2026)

    pred = get_user_prediction(current_user.id, season)
    if not pred:
        return jsonify({"error": "No prediction found"}), 404

    grids = json.loads(pred["grids_json"]) if pred.get("grids_json") else {}
    scoring = _score_prediction(grids, season)

    update_leaderboard(
        current_user.id, season,
        scoring["accuracyScore"], scoring["racesScored"],
        scoring["exactMatches"], scoring["totalPositions"],
    )

    return jsonify({"scoring": scoring})


# ── Consensus route (proxy compatibility) ────────────────────────────────

@predictions_bp.route("/api/consensus", methods=["GET"])
def api_consensus():
    """Aggregate user predictions for a race (proxy route compatibility)."""
    season = request.args.get("season", 2026, type=int)
    race_id = request.args.get("raceId", "")

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT grids_json FROM predictions WHERE season = ?",
            (season,)
        ).fetchall()

    positions: dict[int, dict[str, int]] = {}
    total_users = len(rows)

    for row in rows:
        grids = json.loads(row["grids_json"]) if row["grids_json"] else {}
        grid = grids.get(race_id)
        if not grid or not isinstance(grid, list):
            continue
        for pos_idx, driver_id in enumerate(grid):
            if driver_id:
                pos = pos_idx + 1
                positions.setdefault(pos, {})
                positions[pos][driver_id] = positions[pos].get(driver_id, 0) + 1

    result_positions = {}
    for pos, drivers in positions.items():
        result_positions[pos] = [
            {"driverId": d, "count": c,
             "percentage": round(c / total_users * 100, 1) if total_users > 0 else 0}
            for d, c in sorted(drivers.items(), key=lambda x: -x[1])
        ]

    return jsonify({
        "season": season, "raceId": race_id,
        "totalUsers": total_users, "positions": result_positions,
    })
