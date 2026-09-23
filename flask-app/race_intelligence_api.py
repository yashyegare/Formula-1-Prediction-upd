"""
race_intelligence_api.py — serve the race-intelligence artifact (Phase 4).

Extends the Flask serving layer with the Phase-4 read API: serves
model-notebooks/datasets/race_intel.json — per-race driver outcome
distributions from the scenario simulator, the derived grid-swing
insight, and the season attribution summary — as three endpoints:

  GET /api/race-intel/season/<year>        — the full season document
  GET /api/race-intel/race/<year>/<round>  — one race's driver array
  GET /api/race-intel/drivers/<year>/<round> — (driverId, p_podium,
                                             p_points, p_out) tuples

The artifact is generated OFFLINE by model-notebooks/race_intelligence.py
and loaded read-only at request time (no numpy/sklearn in the serving
path). Failures are explicit: a missing artifact is a 503 with an error
body, a season/round outside the artifact is a 404 — never a silently
empty 200.
"""

import json
from pathlib import Path

from flask import Flask, Response, abort, jsonify

ARTIFACT_PATH = Path(__file__).resolve().parents[1] \
    / "model-notebooks" / "datasets" / "race_intel.json"


class ArtifactUnavailable(Exception):
    """The race-intel artifact does not exist on disk (yet)."""


app = Flask(__name__)
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


def _race(year: int, rnd: int) -> dict:
    doc = _load_artifact()
    if doc["season"] != year:
        abort(404, description="no race-intel artifact for this season")
    for race in doc["races"]:
        if race["round"] == rnd:
            return race
    abort(404, description="round not in the race-intel artifact")


@app.errorhandler(ArtifactUnavailable)
def _artifact_missing(e: ArtifactUnavailable) -> tuple[Response, int]:
    return jsonify({"error": str(e)}), 503


@app.route("/api/race-intel/season/<int:year>")
def season(year: int):
    doc = _load_artifact()
    if doc["season"] != year:
        abort(404, description="no race-intel artifact for this season")
    return jsonify(doc)


@app.route("/api/race-intel/race/<int:year>/<int:rnd>")
def race(year: int, rnd: int):
    return jsonify(_race(year, rnd))


@app.route("/api/race-intel/drivers/<int:year>/<int:rnd>")
def drivers(year: int, rnd: int):
    race_doc = _race(year, rnd)
    out = [{"driverId": d["driverId"],
            "p_podium": d["p_podium"],
            "p_points": d["p_points"],
            "p_out": d["p_out"]} for d in race_doc["drivers"]]
    return jsonify(out)
