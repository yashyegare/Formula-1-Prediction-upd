"""Shared synthetic-artifact helper for the race-intelligence API tests."""

import json


def _install_stub_artifact(path) -> None:
    doc = {
        "schema_version": 1,
        "season": 2026,
        "n_sims": 500,
        "mechanism": {"swing_mean": 1.0, "swing_sd": 4.0, "dnf_rate": 0.15},
        "races": [
            {"year": 2026, "round": 1, "n_drivers": 2,
             "params": {"swing_mean": 1.0, "swing_sd": 4.0,
                        "dnf_rate": 0.15},
             "drivers": [
                 {"driverId": "hamilton", "grid": 1,
                  "p_podium": 0.60, "p_points": 0.30, "p_out": 0.10,
                  "expected_position": 2.1, "sim_dnf_rate": 0.15,
                  "observed_swing": -2, "sim_swing_mean": 0.9},
                 {"driverId": "tsunoda", "grid": 10,
                  "p_podium": 0.02, "p_points": 0.18, "p_out": 0.80,
                  "expected_position": 8.4, "sim_dnf_rate": 0.15,
                  "observed_swing": 4, "sim_swing_mean": -1.5},
             ]},
            {"year": 2026, "round": 2, "n_drivers": 2,
             "params": {"swing_mean": 1.0, "swing_sd": 4.0,
                        "dnf_rate": 0.15},
             "drivers": [
                 {"driverId": "verstappen", "grid": 1,
                  "p_podium": 0.55, "p_points": 0.35, "p_out": 0.10,
                  "expected_position": 2.3, "sim_dnf_rate": 0.15,
                  "observed_swing": None, "sim_swing_mean": 0.8},
                 {"driverId": "norris", "grid": 3,
                  "p_podium": 0.28, "p_points": 0.52, "p_out": 0.20,
                  "expected_position": 4.0, "sim_dnf_rate": 0.15,
                  "observed_swing": None, "sim_swing_mean": -0.4},
             ]},
        ],
        "season_attribution": {
            "n_predictions": 220,
            "accuracy": 0.6862,
            "n_misses": 75,
            "cause_share": {"dnf_mechanical": 0.0, "dnf_driver_error": 0.0,
                            "dnf_other": 0.2533, "over_predict": 0.2133,
                            "under_predict": 0.5333},
            "evidence": {"over_pace_slow_share": 0.06,
                         "under_pace_fast_share": 0.09,
                         "sc_involved_share": 0.65,
                         "big_grid_swing_share": 0.31},
        },
    }
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
