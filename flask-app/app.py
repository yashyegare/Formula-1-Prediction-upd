import json
import os
import secrets
import time
import urllib.request

import joblib
import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS, cross_origin
from database import init_db, is_seeded, get_season_init_data, get_circuits as db_get_circuits
from auth import auth_bp, login_manager
from predictions_api import predictions_bp

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

# Cross-origin session cookies (Vercel frontend → Render backend)
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"] = True
app.config["REMEMBER_COOKIE_SAMESITE"] = "None"
app.config["REMEMBER_COOKIE_SECURE"] = True

# Initialize Flask-Login
login_manager.init_app(app)

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(predictions_bp)

# Initialize SQLite database on startup
init_db()
if not is_seeded():
    print("[WARN] Database is empty. Run 'python seed_data.py' to populate F1 season data.")

# In-memory cache for /api/init to avoid re-fetching from Jolpica on every request
_INIT_CACHE = {}
# CORS origins — allow localhost in dev, plus production Vercel domains from env
CORS_ORIGINS = [
    "http://localhost:3000",   # Next.js dev
    "http://localhost:5173",   # Astro dev
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]
# Production frontends (set via env comma-separated)
# e.g. CORS_ORIGINS=https://your-app.vercel.app,https://simulator.vercel.app
_extra = os.environ.get("CORS_ORIGINS", "")
if _extra:
    CORS_ORIGINS.extend(o.strip() for o in _extra.split(",") if o.strip())

CORS(app, resources={r"/*": {
    "origins": CORS_ORIGINS,
    "supports_credentials": True,
    "allow_headers": ["Content-Type", "Authorization"],
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
}})

# Team colors for the 2026 grid (used by /api/init fallback)
TEAM_COLORS_2026 = {
    "mclaren": {"id": "mclaren", "name": "McLaren", "nationality": "British", "color": "#FF8000"},
    "ferrari": {"id": "ferrari", "name": "Ferrari", "nationality": "Italian", "color": "#D52E37"},
    "red_bull": {"id": "red_bull", "name": "Red Bull", "nationality": "Austrian", "color": "#4570C0"},
    "mercedes": {"id": "mercedes", "name": "Mercedes", "nationality": "German", "color": "#75F1D3"},
    "aston_martin": {"id": "aston_martin", "name": "Aston Martin", "nationality": "British", "color": "#229971"},
    "alpine": {"id": "alpine", "name": "Alpine F1 Team", "nationality": "French", "color": "#0093CC", "secondaryColor": "#FF87BC"},
    "audi": {"id": "audi", "name": "Audi", "nationality": "German", "color": "#BB0A30"},
    "rb": {"id": "rb", "name": "RB F1 Team", "nationality": "Italian", "color": "#6692FF"},
    "haas": {"id": "haas", "name": "Haas F1 Team", "nationality": "American", "color": "#B6BABD"},
    "williams": {"id": "williams", "name": "Williams", "nationality": "British", "color": "#64C4FF"},
    "cadillac": {"id": "cadillac", "name": "Cadillac F1 Team", "nationality": "American", "color": "#1E1E1E", "secondaryColor": "#E0E0E0"},
}

# Normalize Jolpica driver IDs to match the upstream frontend's expectations
DRIVER_ID_MAP = {
    "max_verstappen": "verstappen",
    "arvid_lindblad": "lindblad",
}

# Official 2026 standings (includes sprint + fastest lap points)
# Source: formula1.com after Dutch GP (R12)
OFFICIAL_DRIVER_STANDINGS = [
    {"position": 1, "driverId": "antonelli", "points": 242},
    {"position": 2, "driverId": "russell", "points": 183},
    {"position": 3, "driverId": "hamilton", "points": 183},
    {"position": 4, "driverId": "norris", "points": 159},
    {"position": 5, "driverId": "leclerc", "points": 155},
    {"position": 6, "driverId": "verstappen", "points": 112},
    {"position": 7, "driverId": "piastri", "points": 104},
    {"position": 8, "driverId": "hadjar", "points": 68},
    {"position": 9, "driverId": "lawson", "points": 49},
    {"position": 10, "driverId": "gasly", "points": 44},
    {"position": 11, "driverId": "lindblad", "points": 23},
    {"position": 12, "driverId": "colapinto", "points": 19},
    {"position": 13, "driverId": "bearman", "points": 18},
    {"position": 14, "driverId": "bortoleto", "points": 10},
    {"position": 15, "driverId": "hulkenberg", "points": 6},
    {"position": 16, "driverId": "sainz", "points": 6},
    {"position": 17, "driverId": "albon", "points": 5},
    {"position": 18, "driverId": "ocon", "points": 3},
    {"position": 19, "driverId": "alonso", "points": 3},
    {"position": 20, "driverId": "tsunoda", "points": 0},
    {"position": 21, "driverId": "stroll", "points": 0},
    {"position": 22, "driverId": "bottas", "points": 0},
    {"position": 23, "driverId": "perez", "points": 0},
]

OFFICIAL_CONSTRUCTOR_STANDINGS = [
    {"position": 1, "teamId": "mercedes", "points": 425},
    {"position": 2, "teamId": "ferrari", "points": 338},
    {"position": 3, "teamId": "mclaren", "points": 263},
    {"position": 4, "teamId": "red_bull", "points": 186},
    {"position": 5, "teamId": "rb", "points": 66},
    {"position": 6, "teamId": "alpine", "points": 63},
    {"position": 7, "teamId": "haas", "points": 21},
    {"position": 8, "teamId": "audi", "points": 16},
    {"position": 9, "teamId": "williams", "points": 11},
    {"position": 10, "teamId": "aston_martin", "points": 3},
    {"position": 11, "teamId": "cadillac", "points": 0},
]

# Country code map for circuits
COUNTRY_CODES = {
    "australia": "au", "china": "cn", "japan": "jp", "bahrain": "bh",
    "saudi arabia": "sa", "usa": "us", "italy": "it", "monaco": "mc",
    "canada": "ca", "spain": "es", "austria": "at", "uk": "uk",
    "great britain": "uk", "hungary": "hu", "belgium": "be",
    "netherlands": "nl", "azerbaijan": "az", "singapore": "sg",
    "mexico": "mx", "brazil": "br", "qatar": "qa", "uae": "ae",
    "france": "fr", "portugal": "pt", "turkey": "tr", "malaysia": "my",
}


def _fetch_jolpica(url):
    """Fetch from Jolpica API with error handling."""
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


@app.route("/api/init", methods=["GET"])
def api_init():
    """Return season data in the format the upstream frontend expects:
    { schedule, teams, drivers, raceResults, driverStandings, constructorStandings }
    Served from SQLite — instant response, no external API calls.
    """
    year = request.args.get("year", 2026, type=int)

    # Try SQLite first (instant)
    data = get_season_init_data(year)
    if data is not None:
        return jsonify(data)

    # Fall back to live Jolpica fetch for un-seeded years (slow)
    cache_key = f"init_{year}"
    if cache_key in _INIT_CACHE:
        return jsonify(_INIT_CACHE[cache_key])

    base = f"https://api.jolpi.ca/ergast/f1/{year}"
    races_data = _fetch_jolpica(f"{base}.json?limit=100")
    drivers_data = _fetch_jolpica(f"{base}/drivers.json?limit=100")
    constructors_data = _fetch_jolpica(f"{base}/constructors.json?limit=100")
    results_data = {"MRData": {"RaceTable": {"Races": []}}}
    all_races = []
    races = races_data.get("MRData", {}).get("RaceTable", {}).get("Races", []) if races_data else []
    max_rounds = len(races) if races else 24
    for rnd in range(1, max_rounds + 1):
        try:
            rnd_data = _fetch_jolpica(f"{base}/{rnd}/results.json")
            if rnd_data:
                rnd_races = rnd_data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
                if rnd_races and rnd_races[0].get("Results"):
                    all_races.append(rnd_races[0])
            time.sleep(0.3)
        except Exception:
            continue
    results_data["MRData"]["RaceTable"]["Races"] = all_races

    schedule = []
    for race in races:
        circ = race.get("Circuit", {})
        loc = circ.get("Location", {})
        country = loc.get("country", "")
        country_lower = country.lower()
        cc = COUNTRY_CODES.get(country_lower, country_lower[:2])
        rnd = int(race.get("round", 0))
        is_sprint = year >= 2022 and rnd in [3, 10, 17, 20]
        completed = bool(results_data and any(
            r.get("round") == str(rnd)
            for r in results_data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
        ))
        schedule.append({
            "id": f"{year}_r{rnd}", "name": race.get("raceName", ""),
            "isSprint": is_sprint, "country": country, "countryCode": cc,
            "order": rnd, "completed": completed, "date": race.get("date", ""),
            "round": str(rnd), "circuitId": circ.get("circuitId", ""),
            "trackSlug": circ.get("circuitId", ""),
        })

    teams = []
    constructors = constructors_data.get("MRData", {}).get("ConstructorTable", {}).get("Constructors", []) if constructors_data else []
    for con in constructors:
        cid = con.get("constructorId", "")
        color_data = TEAM_COLORS_2026.get(cid, {"color": "#888888"})
        teams.append({
            "id": cid, "name": con.get("name", cid),
            "nationality": con.get("nationality", ""),
            "color": color_data.get("color", "#888888"),
            "secondaryColor": color_data.get("secondaryColor"),
        })

    drivers_list = []
    drivers_raw = drivers_data.get("MRData", {}).get("DriverTable", {}).get("Drivers", []) if drivers_data else []
    driver_constructor = {}
    results_races = results_data.get("MRData", {}).get("RaceTable", {}).get("Races", []) if results_data else []
    for race in results_races:
        for res in race.get("Results", []):
            drv = res.get("Driver", {})
            con = res.get("Constructor", {})
            did = drv.get("driverId", "")
            cid = con.get("constructorId", "")
            if did and cid:
                normalized = DRIVER_ID_MAP.get(did, did)
                driver_constructor[normalized] = cid
                driver_constructor[did] = cid

    for drv in drivers_raw:
        did = drv.get("driverId", "")
        if did not in driver_constructor:
            continue
        normalized_id = DRIVER_ID_MAP.get(did, did)
        drivers_list.append({
            "id": normalized_id,
            "code": drv.get("code", did[:3].upper()),
            "givenName": drv.get("givenName", ""),
            "familyName": drv.get("familyName", ""),
            "nationality": drv.get("nationality", ""),
            "team": driver_constructor.get(did, ""),
        })

    race_results = {}
    for race in results_races:
        rnd = int(race.get("round", 0))
        race_id = f"{year}_r{rnd}"
        results_list = []
        for res in race.get("Results", []):
            drv = res.get("Driver", {})
            con = res.get("Constructor", "")
            con_id = con.get("constructorId", "") if isinstance(con, dict) else str(con)
            pos = res.get("position")
            if pos is None:
                continue
            raw_did = drv.get("driverId", "")
            results_list.append({
                "driverId": DRIVER_ID_MAP.get(raw_did, raw_did),
                "teamId": con_id, "position": int(pos),
                "fastestLap": res.get("FastestLap") is not None,
            })
        if results_list:
            race_results[race_id] = results_list

    result = {
        "schedule": schedule, "teams": teams, "drivers": drivers_list,
        "raceResults": race_results, "driverStandings": OFFICIAL_DRIVER_STANDINGS,
        "constructorStandings": OFFICIAL_CONSTRUCTOR_STANDINGS,
    }
    _INIT_CACHE[cache_key] = result
    return jsonify(result)


@app.route("/api/circuits", methods=["GET"])
def api_circuits():
    """Return circuit slugs for the upstream frontend."""
    year = request.args.get("year", 2026, type=int)
    # Try SQLite first
    data = db_get_circuits(year)
    if data:
        return jsonify(data)
    # Fallback to live Jolpica
    base = f"https://api.jolpi.ca/ergast/f1/{year}"
    raw = _fetch_jolpica(f"{base}.json?limit=100")
    races = raw.get("MRData", {}).get("RaceTable", {}).get("Races", []) if raw else []
    slugs = {}
    for race in races:
        rnd = int(race.get("round", 0))
        circ = race.get("Circuit", {})
        slugs[f"{year}_r{rnd}"] = circ.get("circuitId", f"r{rnd}")
    return jsonify(slugs)


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


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint for Railway."""
    return jsonify({"status": "ok", "seeded": is_seeded()})


if __name__ == "__main__":
    app.run(debug=True, port=8000)