"""
race_intelligence_api.py — serve the race-intelligence artifacts.

A blueprint (registered by app.py alongside auth and predictions) that
serves two precomputed model-notebooks/datasets JSON documents:
race_intel.json — per-race driver outcome distributions from the
scenario simulator, the derived grid-swing insight, and the season
attribution summary — and lap_curves.json — the lap-by-lap probability
evolution for raced rounds (the replay's P(podium) per lap per driver):

  GET /api/race-intel/season/<year>          — the full season document
  GET /api/race-intel/race/<year>/<round>    — one race's driver array
  GET /api/race-intel/races/<year>           — light index (no drivers)
  GET /api/race-intel/drivers/<year>/<round> — (driverId, p_podium,
                                               p_points, p_out) tuples
  GET /api/race-intel/next/<year>            — the next_round race
                                               (pre-race view)
  GET /api/race-intel/curves/<year>/<round>  — lap-by-lap probability
                                               evolution (raced rounds)

Future rounds carry `status` "upcoming_post_quali" or "scheduled" and
serve simulated distributions from the best point-in-time grid (real
quali when the round has qualified, else current championship order) —
these are PREdictions. Raced rounds carry status "raced" plus the
per-driver `observed_swing` / `sim_swing_mean` insight — the POST-race
"why it landed there" view — and are the only rounds with lap curves
(a replay needs the actual chart). Each curves doc carries its own
per-race `seed` (artifact builder convention 42 + year*100 + round),
so a client can reproduce the distributions it renders.

Both artifacts are generated OFFLINE (race_intelligence.py /
lap_curves.py) and loaded read-only at request time (no numpy/sklearn
in the serving path), each cached by mtime so a rebuild is served
without restart. Failures are explicit: a missing artifact is a 503
with an error body, a season/round outside the artifact is a 404 —
never a silently empty 200.
"""

import json
from pathlib import Path

from flask import Blueprint, Response, abort, jsonify

ARTIFACT_PATH = Path(__file__).resolve().parents[1] \
    / "model-notebooks" / "datasets" / "race_intel.json"
CURVES_PATH = Path(__file__).resolve().parents[1] \
    / "model-notebooks" / "datasets" / "lap_curves.json"


class ArtifactUnavailable(Exception):
    """The race-intel artifact does not exist on disk (yet)."""


race_intel_bp = Blueprint("race_intel", __name__)
_CACHE: dict = {"mtime": None, "doc": None}
_CURVES_CACHE: dict = {"mtime": None, "doc": None}


def _load_artifact() -> dict:
    """Read race_intel.json from disk, caching by mtime so a rebuilt
    artifact is picked up without a process restart."""
    try:
        mtime = ARTIFACT_PATH.stat().st_mtime
    except OSError:
        _CACHE["mtime"] = _CACHE["doc"] = None
        raise ArtifactUnavailable(
            f"race_intel.json not found at {ARTIFACT_PATH}. Generate it "
            "with model-notebooks/race_intelligence.py") from None
    if _CACHE["mtime"] != mtime:
        with open(ARTIFACT_PATH, encoding="utf-8") as f:
            doc = json.load(f)
        _CACHE["mtime"] = mtime
        _CACHE["doc"] = doc
    return _CACHE["doc"]


def _race_doc(year: int, rnd: int) -> dict:
    doc = _load_artifact()
    if doc["season"] != year:
        abort(404, description="no race-intel artifact for this season")
    for race in doc["races"]:
        if race["round"] == rnd:
            return race
    abort(404, description="round not in the race-intel artifact")


def _load_curves() -> dict:
    """Read lap_curves.json, cached by mtime (same contract as the main
    artifact: a rebuild is picked up without a process restart)."""
    try:
        mtime = CURVES_PATH.stat().st_mtime
    except OSError:
        _CURVES_CACHE["mtime"] = _CURVES_CACHE["doc"] = None
        raise ArtifactUnavailable(
            f"lap_curves.json not found at {CURVES_PATH}. Generate it "
            "with model-notebooks/lap_curves.py") from None
    if _CURVES_CACHE["mtime"] != mtime:
        with open(CURVES_PATH, encoding="utf-8") as f:
            doc = json.load(f)
        _CURVES_CACHE["mtime"] = mtime
        _CURVES_CACHE["doc"] = doc
    return _CURVES_CACHE["doc"]


def _curves_doc(year: int, rnd: int) -> dict:
    doc = _load_curves()
    if doc["season"] != year:
        abort(404, description="no lap-curve artifact for this season")
    for race in doc["races"]:
        if race["round"] == rnd:
            return race
    abort(404, description="round not in the lap-curve artifact "
                           "(future rounds have no replay)")


@race_intel_bp.errorhandler(ArtifactUnavailable)
def _artifact_missing(e: ArtifactUnavailable) -> tuple[Response, int]:
    return jsonify({"error": str(e)}), 503


@race_intel_bp.errorhandler(404)
def _not_found(e) -> tuple[Response, int]:
    """JSON 404s from this blueprint's routes — the frontends read the
    error body; Flask's default HTML page would break that contract."""
    return jsonify({"error": e.description}), 404


@race_intel_bp.route("/api/race-intel/season/<int:year>")
def season(year: int):
    doc = _load_artifact()
    if doc["season"] != year:
        abort(404, description="no race-intel artifact for this season")
    return jsonify(doc)


@race_intel_bp.route("/api/race-intel/races/<int:year>")
def races_index(year: int):
    """Light race index: everything except the per-driver arrays."""
    doc = _load_artifact()
    if doc["season"] != year:
        abort(404, description="no race-intel artifact for this season")
    out = {k: v for k, v in doc.items() if k != "races"}
    out["races"] = [{k: v for k, v in r.items() if k != "drivers"}
                    for r in doc["races"]]
    return jsonify(out)


@race_intel_bp.route("/api/race-intel/race/<int:year>/<int:rnd>")
def race(year: int, rnd: int):
    return jsonify(_race_doc(year, rnd))


@race_intel_bp.route("/api/race-intel/drivers/<int:year>/<int:rnd>")
def drivers(year: int, rnd: int):
    race_doc = _race_doc(year, rnd)
    out = [{"driverId": d["driverId"],
            "p_podium": d["p_podium"],
            "p_points": d["p_points"],
            "p_out": d["p_out"]} for d in race_doc["drivers"]]
    return jsonify(out)


@race_intel_bp.route("/api/race-intel/next/<int:year>")
def next_race(year: int):
    """The next_round race doc — the pre-race view for the dashboard."""
    doc = _load_artifact()
    if doc["season"] != year:
        abort(404, description="no race-intel artifact for this season")
    nxt = doc.get("next_round")
    if nxt is None:
        abort(404, description="no future rounds remain in this season")
    return jsonify(_race_doc(year, nxt))


@race_intel_bp.route("/api/race-intel/curves/<int:year>/<int:rnd>")
def curves(year: int, rnd: int):
    """Lap-by-lap probability evolution for one raced round."""
    return jsonify(_curves_doc(year, rnd))
