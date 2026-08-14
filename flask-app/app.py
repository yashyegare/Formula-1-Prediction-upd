import json

import joblib
import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS, cross_origin

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# 3-class output: 1 = podium (P1-3), 2 = points (P4-10), 3 = out of points (P11+)
# -- matches what the nextjs predictor.tsx UI renders.
model = joblib.load("rffinal.pkl")

with open("id_maps.json") as f:
    ID_MAPS = json.load(f)
with open("current_roster.json") as f:
    ROSTER = json.load(f)

GP_IDS = ID_MAPS["GP_name"]
CONSTRUCTOR_IDS = ID_MAPS["constructor"]
DRIVER_IDS = ID_MAPS["driver"]
DRIVER_TEAM = ROSTER["driver_team"]
DRIVER_CONFIDENCE = ROSTER["driver_confidence"]
CONSTRUCTOR_RELIABILITY = ROSTER["constructor_reliability"]

# case-insensitive lookup helpers, since the frontend sends free-text names
_GP_LOOKUP = {name.lower(): name for name in GP_IDS}
_DRIVER_LOOKUP = {name.lower(): name for name in DRIVER_IDS}


@app.route("/predictGrid", methods=["POST", "OPTIONS"])
@cross_origin()
def predict_driver_position():
    data = request.get_json(force=True)
    driver_name_in = data["name"]
    round_name_in = data["round"]
    qualifying_pos = data["qualifying_pos"]

    driver_name = _DRIVER_LOOKUP.get(driver_name_in.lower())
    gp_name = _GP_LOOKUP.get(round_name_in.lower())

    if driver_name is None:
        return jsonify({"error": f"Unknown or inactive driver: {driver_name_in}"}), 400
    if gp_name is None:
        return jsonify({"error": f"Unknown Grand Prix: {round_name_in}"}), 400

    constructor_name = DRIVER_TEAM[driver_name]

    row = {
        "GP_name": [GP_IDS[gp_name]],
        "quali_pos": [qualifying_pos],
        "constructor": [CONSTRUCTOR_IDS[constructor_name]],
        "driver": [DRIVER_IDS[driver_name]],
        "driver_confidence": [DRIVER_CONFIDENCE[driver_name]],
        "constructor_relaiblity": [CONSTRUCTOR_RELIABILITY[constructor_name]],
    }

    df = pd.DataFrame(row)
    prediction = model.predict(df)  # [1], [2], or [3]

    results = jsonify(prediction.tolist())
    results.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    results.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
    return results


@app.route("/roster", methods=["GET"])
@cross_origin()
def roster():
    """Lets the frontend fetch the current driver list, GP list, and
    driver->team pairings directly, instead of hardcoding them in the
    Next.js app too."""
    return jsonify({
        "drivers": sorted(DRIVER_IDS.keys()),
        "grandsPrix": sorted(GP_IDS.keys()),
        "driverTeam": DRIVER_TEAM,
        "season": ROSTER["latest_year"],
    })


if __name__ == "__main__":
    app.run(debug=True, port=8000)