"""
race_intelligence_api.py — serve the race-intelligence artifact.

A blueprint (registered by app.py alongside auth and predictions) that
serves model-notebooks/datasets/race_intel.json — per-race driver
outcome distributions from the scenario simulator, the derived
grid-swing insight, and the season attribution summary:

  GET /api/race-intel/season/<year>          — the full season document
  GET /api/race-intel/race/<year>/<round>    — one race's driver array
  GET /api/race-intel/races/<year>           — light index (no drivers)
  GET /api/race-intel/drivers/<year>/<round> — (driverId, p_podium,
                                               p_points, p_out) tuples
  GET /api/race-intel/next/<year>            — the next_round race
                                               (pre-race view)

Future rounds carry `status` "upcoming_post_quali" or "scheduled" and
serve simulated distributions from the best point-in-time grid (real
quali when the round has qualified, else current championship order) —
these are PREdictions. Raced rounds carry status "raced" plus the
per-driver `observed_swing` / `sim_swing_mean` insight — the POST-race
"why it landed there" view.

The artifact is generated OFFLINE by model-notebooks/race_intelligence.py
and loaded read-only at request time (no numpy/sklearn in the serving
path). Failures are explicit: a missing artifact is a 503 with an error
body, a season/round outside the artifact is a 404 — never a silently
empty 200.
"""

import json
from pathlib import Path

from flask import Blueprint, Response, abort, jsonify

ARTIFACT_PATH = Path(__file__).resolve().parents[1] \
    / "model-notebooks" / "datasets" / "race_intel.json"


class ArtifactUnavailable(Exception):
    """The race-intel artifact does not exist on disk (yet)."""


race_intel_bp = Blueprint("race_intel", __name__)
_CACHE: dict = {"mtime": None, "doc": None}


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
