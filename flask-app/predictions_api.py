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

Endpoint families — why there are two auth patterns
----------------------------------------------------
There are deliberately TWO route families serving prediction data:

  Family A — /api/predictions/*   ("compat shim", upstream + Season Simulator)
  Family B — /api/me/prediction*  ("first-party", @login_required)

WHY BOTH EXIST: Family A is a frozen compatibility layer for the two
production frontends — the Season Simulator (f1-points-calc) was built
against an upstream API whose routes had idempotent, anonymous-friendly
semantics (save returns 201 even when anonymous and nothing is stored;
load returns 404 instead of 401 for anonymous callers). Re-pointing those
frontends at /api/me/* would be a breaking change for deployed clients.
Family B is the first-party API for our own code: strict @login_required,
clean JSON 401s, server-side scoring and leaderboard writes.

DIFFERENCES THAT ARE LOAD-BEARING (pinned by tests/test_prediction_endpoints_auth.py):
  - Family A save: anonymous → 201 {success: true} with NOTHING persisted.
  - Family A load: anonymous → 404 (null body), never a 401 redirect.
  - Family A lock/unlock: 401 JSON when anonymous (state-changing).
  - Family B: @login_required everywhere → 401 JSON, and POST is the only
    path that scores + writes the leaderboard.

RULES FOR CHANGE: New clients must use Family B. Do not add new routes to
Family A; do not change Family A's status codes (they are a wire contract).
If both frontends ever migrate to /api/me/*, delete Family A wholesale.

One additive exception, for the season reconciliation: Family A's save takes
an optional `standings` map ({"driverId": points}) — the simulator's own
simulated championship points, which the server cannot recompute because the
scoring rules live in that app. It is stored on predictions.standings_json and
read back only by Family B's /api/me/prediction/reconcile. Requests without it
behave exactly as before.
"""

import json
from typing import Optional

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from database import _is_pg

from database import (
    save_prediction, get_user_prediction, get_prediction_by_id as get_prediction,
    lock_prediction_by_id as lock_prediction, get_all_predictions,
    update_leaderboard, get_leaderboard, get_leaderboard_stats,
    get_season_init_data, get_connection,
    _fetchall, _fetchone, _execute,
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
        result_rows = _fetchall(
            conn,
            "SELECT round_num, driver_id, position FROM results "
            "WHERE year = " + ("%s" if _is_pg() else "?")
            + " ORDER BY round_num, position",
            (season,),
        )

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


# ── Championship points ────────────────────────────────────────────────

# Same scale race_intelligence.py uses to publish expected_points; keeping the
# two in sync is what makes the reconcile endpoint's columns comparable.
_RACE_POINTS = (25, 18, 15, 12, 10, 8, 6, 4, 2, 1)


def _points_for_position(pos) -> int:
    if not isinstance(pos, int):
        return 0
    return _RACE_POINTS[pos - 1] if 1 <= pos <= len(_RACE_POINTS) else 0


def _clean_standings(raw) -> Optional[str]:
    """Serialise the simulator's standings payload ({"driverId": points}).
    Returns None when absent or unusable, so save_prediction keeps the last
    known totals instead of overwriting them with garbage."""
    if not isinstance(raw, dict) or not raw:
        return None
    cleaned = {}
    for driver_id, points in list(raw.items())[:100]:
        if not isinstance(driver_id, str) or not driver_id.strip():
            continue
        if isinstance(points, bool) or not isinstance(points, (int, float)):
            continue
        cleaned[driver_id] = round(float(points), 2)
    return json.dumps(cleaned) if cleaned else None


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

        save_prediction(current_user.id, season, json.dumps(grids),
                        standings_json=_clean_standings(data.get("standings")))

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
                    row = _fetchone(
                        conn,
                        "SELECT date FROM races WHERE year = "
                        + ("%s" if _is_pg() else "?")
                        + " AND round_num = " + ("%s" if _is_pg() else "?"),
                        (year, rnd),
                    )
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
            _execute(conn,
                "UPDATE predictions SET locked = 0, locked_at = NULL WHERE id = "
                + ("%s" if _is_pg() else "?"),
                (pred["id"],),
            )
    return jsonify({"success": True})


# ── Authenticated prediction routes ─────────────────────────────────────

# Verdict taxonomy for the postmortem, aligned with model-notebooks/
# error_decomposition.py row labels (dnf_mech / dnf_driver / dnf_other /
# over_predict / under_predict) so the user's misses and the model's
# misses speak one vocabulary. "near" = off by 1-2 places: the position
# analogue of the model's P10/P11 boundary lives.

def _verdict(pred_pos: int, actual: dict) -> str:
    a = actual.get("actual_position")
    # a DNF classified exactly where predicted IS a hit (the analogue of
    # error_decomposition's correct_dnf: the result delivered the pick)
    if a is not None and a == pred_pos:
        return "exact"
    if actual.get("is_dnf"):
        return "dnf_" + (actual.get("dnf_cause") or "other")
    if a is None:
        return "unknown"
    diff = a - pred_pos
    if diff == 0:
        return "exact"
    if abs(diff) <= 2:
        return "near"
    return "over_predict" if diff > 0 else "under_predict"


@predictions_bp.route("/api/me/prediction/postmortem", methods=["GET"])
@login_required
def my_prediction_postmortem():
    """Explain WHY the current user's locked predictions missed, per
    raced round — the personal counterpart of the season_attribution
    the race-intel page shows for the model. Reads the user's grids
    from the predictions DB and joins them against the race-intel
    artifact (schema v3 actual fields); no scoring math is recomputed
    here, this is evidence, not leaderboard score."""
    season = request.args.get("season", 2026, type=int)
    pred = get_user_prediction(current_user.id, season)
    if not pred:
        return jsonify({"error": "No prediction found for this season"}), 404

    try:
        from race_intelligence_api import _load_artifact, ArtifactUnavailable
        doc = _load_artifact()
    except ArtifactUnavailable as e:
        return jsonify({"error": str(e)}), 503
    if doc["season"] != season:
        return jsonify({"error": "no race-intel artifact for this season"}), 404
    if doc.get("schema_version", 0) < 3:
        return jsonify({
            "error": "race_intel.json predates schema v3 (no actual "
                     "results); rebuild it with race_intelligence.py"}), 503

    grids = json.loads(pred["grids_json"]) if pred.get("grids_json") else {}

    races_out = []
    totals: dict[str, int] = {}
    scored = 0
    for race in doc["races"]:
        if race["status"] != "raced":
            continue
        race_id = f"{season}_r{race['round']}"
        grid = grids.get(race_id)
        if not isinstance(grid, list):
            continue
        actual_by_driver = {d["driverId"]: d for d in race["drivers"]}
        counts: dict[str, int] = {}
        misses = []
        abs_errs = []
        for pos_idx, driver_id in enumerate(grid):
            if not driver_id:
                continue
            actual = actual_by_driver.get(driver_id)
            if actual is None:
                continue  # roster lookahead — driver not in this race
            pred_pos = pos_idx + 1
            verdict = _verdict(pred_pos, actual)
            counts[verdict] = counts.get(verdict, 0) + 1
            totals[verdict] = totals.get(verdict, 0) + 1
            scored += 1
            a = actual.get("actual_position")
            if verdict not in ("exact", "near"):
                if a is not None:
                    abs_errs.append(abs(a - pred_pos))
                misses.append({
                    "driverId": driver_id,
                    "surname": actual.get("surname", ""),
                    "predicted_position": pred_pos,
                    "actual_position": a,
                    "verdict": verdict,
                    "status": actual.get("status", ""),
                    "grid_start": actual.get("grid"),
                    "sim_expected_position": actual.get("expected_position"),
                })
        misses.sort(key=lambda m: abs((m["actual_position"] or 99)
                                      - m["predicted_position"]),
                    reverse=True)
        races_out.append({
            "round": race["round"],
            "name": race["name"],
            "date": race["date"],
            "predictions_scored": sum(counts.values()),
            "mean_abs_error": round(sum(abs_errs) / len(abs_errs), 2)
                             if abs_errs else None,
            "verdict_counts": counts,
            "misses": misses[:5],  # the race's biggest surprises
        })

    correct = totals.get("exact", 0) + totals.get("near", 0)
    return jsonify({
        "season": season,
        "races_scored": len(races_out),
        "predictions_scored": scored,
        "hit_rate": round(correct / scored, 4) if scored else None,
        "verdict_share": {k: round(v / scored, 4) for k, v in totals.items()}
                         if scored else {},
        "races": sorted(races_out, key=lambda r: r["round"]),
    })

@predictions_bp.route("/api/me/prediction/reconcile", methods=["GET"])
@login_required
def my_prediction_reconcile():
    """Put the three point totals for a season side by side, per driver:
      - simulated: the Season Simulator's own what-if standings, computed
        client-side from the user's grid and shipped on every autosave
        (predictions.standings_json). The server cannot recompute them —
        the 19 points systems and the sprint / fastest-lap / half / double /
        dropped-score exceptions only exist inside that app.
      - model: expected_points from the race-intel Monte-Carlo artifact.
      - actual: real feature-race results, points for P1-P10.
    They don't share a denominator (the user predicts the whole season, only
    part of it has been raced), so model is given twice: season-long, which is
    comparable to simulated, and raced-only, which is comparable to actual."""
    season = request.args.get("season", 2026, type=int)
    pred = get_user_prediction(current_user.id, season)
    if not pred:
        return jsonify({"error": "No prediction found for this season"}), 404
    simulated = json.loads(pred["standings_json"]) if pred.get("standings_json") else None

    try:
        from race_intelligence_api import _load_artifact, ArtifactUnavailable
        doc = _load_artifact()
    except ArtifactUnavailable as e:
        return jsonify({"error": str(e)}), 503
    if doc["season"] != season:
        return jsonify({"error": "no race-intel artifact for this season"}), 404
    if doc.get("schema_version", 0) < 5:
        return jsonify({
            "error": "race_intel.json predates schema v5 (no expected_points); "
                     "rebuild it with race_intelligence.py"}), 503

    model_season: dict[str, float] = {}
    model_raced: dict[str, float] = {}
    actual_raced: dict[str, int] = {}
    identity: dict[str, dict] = {}
    raced_rounds = 0

    for race in doc["races"]:
        is_raced = race.get("status") == "raced"
        if is_raced:
            raced_rounds += 1
        for d in race.get("drivers", []):
            driver_id = d.get("driverId")
            if not driver_id:
                continue
            expected = float(d.get("expected_points") or 0.0)
            model_season[driver_id] = model_season.get(driver_id, 0.0) + expected
            identity.setdefault(driver_id, {
                "surname": d.get("surname", ""),
                "driverCode": d.get("driverCode", ""),
                "constructorId": d.get("constructorId", ""),
            })
            if is_raced:
                model_raced[driver_id] = model_raced.get(driver_id, 0.0) + expected
                actual_raced[driver_id] = (actual_raced.get(driver_id, 0)
                                           + _points_for_position(d.get("actual_position")))

    rows = []
    for driver_id in set(model_season) | set(simulated or {}):
        sim = (simulated or {}).get(driver_id)
        rows.append({
            "driverId": driver_id,
            **identity.get(driver_id, {"surname": "", "driverCode": "", "constructorId": ""}),
            "simulated": sim,
            "model_season": round(model_season.get(driver_id, 0.0), 2),
            "model_raced": round(model_raced.get(driver_id, 0.0), 2),
            "actual_raced": actual_raced.get(driver_id, 0),
            # What the user's grid expects beyond/behind the model, season-long.
            "sim_minus_model": None if sim is None
                               else round(sim - model_season.get(driver_id, 0.0), 2),
            # Where the model was optimistic or pessimistic about reality.
            "model_minus_actual": round(model_raced.get(driver_id, 0.0)
                                        - actual_raced.get(driver_id, 0), 2),
        })
    rows.sort(key=lambda r: (-(r["simulated"] if r["simulated"] is not None
                               else r["model_season"]), r["driverId"]))

    return jsonify({
        "season": season,
        "has_simulated_standings": simulated is not None,
        "rounds_in_artifact": len(doc["races"]),
        "raced_rounds": raced_rounds,
        "drivers": rows,
        "totals": {
            "simulated": None if simulated is None else round(sum(simulated.values()), 2),
            "model_season": round(sum(model_season.values()), 2),
            "model_raced": round(sum(model_raced.values()), 2),
            "actual_raced": sum(actual_raced.values()),
        },
    })


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
        rows = _fetchall(
            conn,
            "SELECT grids_json FROM predictions WHERE season = "
            + ("%s" if _is_pg() else "?"),
            (season,),
        )

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
