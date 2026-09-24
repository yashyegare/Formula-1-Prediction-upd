"""Shared synthetic-artifact helper for the race-intelligence API tests."""

import json


def _install_stub_artifact(path) -> None:
    doc = {
        "schema_version": 2,
        "season": 2026,
        "n_sims": 500,
        "next_round": 2,
        "mechanism": {"swing_mean": 1.0, "swing_sd": 4.0, "dnf_rate": 0.15},
        "races": [
            {"year": 2026, "round": 1, "name": "Stub GP", "date": "2026-03-01",
             "status": "raced", "n_drivers": 2,
             "params": {"swing_mean": 1.0, "swing_sd": 4.0,
                        "dnf_rate": 0.15},
             "drivers": [
                 {"driverId": "hamilton", "driverCode": "HAM",
                  "surname": "Hamilton", "constructorId": "ferrari",
                  "grid": 1,
                  "p_podium": 0.60, "p_points": 0.30, "p_out": 0.10,
                  "expected_position": 2.1, "sim_dnf_rate": 0.15,
                  "observed_swing": -2, "sim_swing_mean": 0.9},
                 {"driverId": "tsunoda", "driverCode": "TSU",
                  "surname": "Tsunoda", "constructorId": "rb",
                  "grid": 10,
                  "p_podium": 0.02, "p_points": 0.18, "p_out": 0.80,
                  "expected_position": 8.4, "sim_dnf_rate": 0.15,
                  "observed_swing": 4, "sim_swing_mean": -1.5},
             ]},
            {"year": 2026, "round": 2, "name": "Future GP",
             "date": "2026-03-08", "status": "scheduled", "n_drivers": 2,
             "params": {"swing_mean": 1.0, "swing_sd": 4.0,
                        "dnf_rate": 0.15},
             "drivers": [
                 {"driverId": "verstappen", "driverCode": "VER",
                  "surname": "Verstappen", "constructorId": "redbull",
                  "grid": 1,
                  "p_podium": 0.55, "p_points": 0.35, "p_out": 0.10,
                  "expected_position": 2.3, "sim_dnf_rate": 0.15},
                 {"driverId": "norris", "driverCode": "NOR",
                  "surname": "Norris", "constructorId": "mclaren",
                  "grid": 3,
                  "p_podium": 0.28, "p_points": 0.52, "p_out": 0.20,
                  "expected_position": 4.0, "sim_dnf_rate": 0.15},
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


def _install_stub_curves(path) -> None:
    """A minimal lap_curves.json sibling: one raced round with two
    drivers whose curves end concentrated (the replay's contract)."""
    doc = {
        "schema_version": 1,
        "season": 2026,
        "n_sims": 500,
        "buckets": 10,
        "mechanism": {
            "rem_swing_by_bucket": {"9": {"mean": 0.0, "sd": 4.5},
                                    "0": {"mean": 0.0, "sd": 1.3}},
            "fail_rate_by_bucket": {"9": 0.12, "0": 0.007},
        },
        "races": [
            {"year": 2026, "round": 1, "n_laps": 10,
             "sample_laps": [1, 5, 10],
             "drivers": [
                 {"driverId": "hamilton", "final_position": 1,
                  "curve": [
                      [1, 0.54, 0.36, 0.10, 4.8],
                      [5, 0.71, 0.22, 0.07, 3.1],
                      [10, 1.0, 0.0, 0.0, 1.0]]},
                 {"driverId": "tsunoda", "final_position": 9,
                  "curve": [
                      [1, 0.02, 0.18, 0.80, 8.4],
                      [5, 0.03, 0.24, 0.73, 8.1],
                      [10, 0.0, 1.0, 0.0, 9.0]]},
             ]},
        ],
    }
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
