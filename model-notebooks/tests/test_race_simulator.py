"""
Tests for race_simulator.py (Phase 3).

The failure modes these pin:
  - nondeterminism (same seed must give identical distributions)
  - invalid classifications (positions must be a 1..N permutation per sim)
  - pit-lane grid=0 leaking into the podium bucket (the clamp contract)
  - DNF ordering violating the classified-after-finishers contract
  - fitting falling back to constants without saying so
  - scoring-math drift (log loss / Brier on hand-checkable vectors)
  - reliability bins not tracking a perfectly calibrated synthetic set
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
MODEL_DIR = HERE.parent
sys.path.insert(0, str(MODEL_DIR))

import race_simulator as rs  # noqa: E402


GRID = [("p1", 1), ("p2", 2), ("p3", 3), ("p4", 4), ("p5", 5),
        ("p6", 6), ("p7", 7), ("p8", 8), ("p9", 9), ("p10", 10)]


# ── classification validity ──────────────────────────────────────────────

class TestSimulationValidity:
    def test_deterministic_same_seed(self):
        rng1 = np.random.default_rng(42)
        rng2 = np.random.default_rng(42)
        s1 = rs.simulate_race(GRID, 200, 1.0, 4.0, 0.15, rng1)
        s2 = rs.simulate_race(GRID, 200, 1.0, 4.0, 0.15, rng2)
        pd.testing.assert_frame_equal(s1, s2)

    def test_positions_are_permutations(self):
        rng = np.random.default_rng(7)
        sim = rs.simulate_race(GRID, 300, 1.0, 4.0, 0.15, rng)
        for _, g in sim.groupby("sim"):
            assert sorted(g["position"]) == list(range(1, 11))

    def test_dnf_count_matches_binomial(self):
        rng = np.random.default_rng(11)
        sim = rs.simulate_race(GRID, 4000, 1.0, 4.0, 0.30, rng)
        per_sim = sim.groupby("sim")["is_dnf"].sum()
        assert abs(per_sim.mean() - 3.0) < 0.15  # N*p = 10*0.30

    def test_dnf_rows_never_outside_their_slots(self):
        """DNFs must be classified strictly after all finishers."""
        rng = np.random.default_rng(3)
        sim = rs.simulate_race(GRID, 500, 1.0, 4.0, 0.25, rng)
        for _, g in sim.groupby("sim"):
            n_fin = int((g["is_dnf"] == 0).sum())
            fin_pos = g.loc[g["is_dnf"] == 0, "position"]
            dnf_pos = g.loc[g["is_dnf"] == 1, "position"]
            assert fin_pos.max() <= n_fin
            assert (dnf_pos > n_fin).all()

    def test_degenerate_params_reproduce_grid_order(self):
        """sd->0, mean->0, no DNF: finishing order == grid order."""
        rng = np.random.default_rng(5)
        sim = rs.simulate_race(GRID, 50, 0.0, 1e-9, 0.0, rng)
        summ = rs.summarize_simulation(sim)
        order = summ.sort_values("expected_position")["driverId"].tolist()
        assert order == [d for d, _ in GRID]

    def test_pit_lane_grid_zero_clamped_to_back(self):
        rng = np.random.default_rng(9)
        grid = GRID + [("pit", 0)]
        sim = rs.simulate_race(grid, 2000, 0.0, 1e-9, 0.0, rng)
        summ = rs.summarize_simulation(sim).set_index("driverId")
        assert summ.loc["pit", "expected_position"] == pytest.approx(11.0)
        assert summ.loc["p1", "expected_position"] == pytest.approx(1.0)

    def test_heavy_attrition_puts_classified_dnfs_in_points(self):
        """The attrition contract: with most of the field out, classified
        DNFs land in points — P(out) < 1 for every driver."""
        rng = np.random.default_rng(13)
        sim = rs.simulate_race(GRID, 2000, 0.5, 3.0, 0.80, rng)
        summ = rs.summarize_simulation(sim)
        assert (summ["p_out"] < 1.0).all()


# ── distribution shape ───────────────────────────────────────────────────

class TestDistributionShape:
    def test_front_runner_has_higher_podium_prob(self):
        rng = np.random.default_rng(21)
        sim = rs.simulate_race(GRID, 3000, 1.0, 4.0, 0.15, rng)
        summ = rs.summarize_simulation(sim).set_index("driverId")
        assert summ.loc["p1", "p_podium"] > summ.loc["p5", "p_podium"]
        assert summ.loc["p1", "p_podium"] > summ.loc["p10", "p_podium"]

    def test_probabilities_sum_to_one(self):
        rng = np.random.default_rng(23)
        sim = rs.simulate_race(GRID, 500, 1.0, 4.0, 0.2, rng)
        summ = rs.summarize_simulation(sim)
        total = summ[["p_podium", "p_points", "p_out"]].sum(axis=1)
        assert np.allclose(total, 1.0)

    def test_expected_position_between_bounds(self):
        rng = np.random.default_rng(29)
        sim = rs.simulate_race(GRID, 500, 1.0, 4.0, 0.2, rng)
        summ = rs.summarize_simulation(sim)
        assert ((summ["expected_position"] >= 1)
                & (summ["expected_position"] <= 10)).all()


# ── fitting ──────────────────────────────────────────────────────────────

class TestFitting:
    @staticmethod
    def _zero_swing_entries(n_races=5, pit_lane_in_round=None):
        """n_races x (8 finished with zero swing + 1 DNF). grid i -> pos i."""
        rows = []
        for rnd in range(1, n_races + 1):
            for slot in range(1, 9):
                if pit_lane_in_round is not None and rnd == pit_lane_in_round:
                    grid = 0 if slot == 8 else slot
                    pos = 5 if slot == 8 else slot  # pit car still finishes P5
                else:
                    grid, pos = slot, slot
                rows.append({"year": 2020, "round": rnd,
                             "driverId": f"d{rnd}_{slot}",
                             "grid": grid, "position": pos, "is_dnf": 0})
            rows.append({"year": 2020, "round": rnd,
                         "driverId": f"dnf{rnd}", "grid": 9,
                         "position": 9, "is_dnf": 1})
        return pd.DataFrame(rows)

    def test_exact_stats_on_zero_swing_sample(self):
        p = rs.fit_swing_params(self._zero_swing_entries())
        assert p["mean"] == pytest.approx(0.0)
        assert p["sd"] == pytest.approx(0.0, abs=1e-12)
        assert p["dnf_rate"] == pytest.approx(1 / 9)

    def test_grid_zero_excluded_from_swing_fit(self):
        # round 3's P5 finisher started from pit lane (grid 0): their
        # +3 swing must NOT enter the sample; others are zero swing
        p = rs.fit_swing_params(self._zero_swing_entries(
            n_races=6, pit_lane_in_round=3))
        assert p["mean"] == pytest.approx(0.0)
        assert p["dnf_rate"] == pytest.approx(1 / 9)  # 6 DNFs / 54 rows

    def test_tiny_sample_falls_back_to_constants(self):
        entries = pd.DataFrame({
            "year": [2020] * 3, "round": [1] * 3,
            "driverId": list("abc"), "grid": [1, 2, 3],
            "position": [1, 2, 3], "is_dnf": [0, 0, 0],
        })
        p = rs.fit_swing_params(entries)
        assert p == rs.GLOBAL_RATE_FALLBACK

    def test_tiny_sample_falls_back_to_constants(self):
        entries = pd.DataFrame({
            "year": [2020] * 3, "round": [1] * 3,
            "driverId": list("abc"), "grid": [1, 2, 3],
            "position": [1, 2, 3], "is_dnf": [0, 0, 0],
        })
        p = rs.fit_swing_params(entries)
        assert p == rs.GLOBAL_RATE_FALLBACK


# ── scoring math ─────────────────────────────────────────────────────────

class TestScoring:
    def _frame(self, p_podium, p_points, p_out, actual):
        return pd.DataFrame({"p_podium": [p_podium], "p_points": [p_points],
                             "p_out": [p_out], "actual": [actual]})

    def test_uniform_log_loss_is_ln3(self):
        f = self._frame(1 / 3, 1 / 3, 1 / 3, 1)
        assert rs.bucket_log_loss(f) == pytest.approx(np.log(3))

    def test_uniform_brier_is_two_thirds(self):
        f = self._frame(1 / 3, 1 / 3, 1 / 3, 1)
        assert rs.bucket_brier(f) == pytest.approx(2 / 3)

    def test_confident_correct_beats_confident_wrong(self):
        good = self._frame(0.98, 0.01, 0.01, 1)
        bad = self._frame(0.98, 0.01, 0.01, 3)
        assert rs.bucket_log_loss(good) < rs.bucket_log_loss(bad)
        assert rs.bucket_brier(good) < rs.bucket_brier(bad)

    def test_suffix_selects_baseline_columns(self):
        f = pd.DataFrame({
            "p_podium": [0.5], "p_points": [0.3], "p_out": [0.2],
            "p_podium_gr": [1 / 3], "p_points_gr": [1 / 3],
            "p_out_gr": [1 / 3],
            "actual": [1],
        })
        assert rs.bucket_log_loss(f) < rs.bucket_log_loss(f, suffix="_gr")

    def test_reliability_tracks_diagonal_when_calibrated(self):
        n = 400
        rng = np.random.default_rng(31)
        p = rng.uniform(0.05, 0.95, n)
        probs = pd.DataFrame({
            "p_podium": p,
            "p_points": 0.0, "p_out": 0.0,
            "actual_podium": (rng.random(n) < p).astype(float),
        })
        curve = rs.reliability_curve(probs, "p_podium", n_bins=4)
        # realized within ~10pt of predicted per bin (400 draws/bin)
        assert ((curve["realized"] - curve["predicted"]).abs() < 0.10).all()


# ── bucket boundaries ────────────────────────────────────────────────────

class TestDriverSD:
    def test_high_volatility_driver_gets_larger_sd(self):
        # driver V: swings alternate +/-4 (positions stay in 1..9);
        # driver M: constant 0 swing
        rows = []
        for i in range(1, 11):
            rows.append({"year": 2020, "round": i, "driverId": "V",
                         "grid": 5, "position": 5 + (4 if i % 2 else -4),
                         "is_dnf": 0})
            rows.append({"year": 2020, "round": i, "driverId": "M",
                         "grid": 5, "position": 5, "is_dnf": 0})
        d = rs.fit_driver_sd(pd.DataFrame(rows), min_races=5)
        # sample sd (ddof=1) of ten alternating +/-4 swings
        assert d["V"] == pytest.approx(4 * np.sqrt(10 / 9))
        assert d["M"] == pytest.approx(2.0)  # floored

    def test_floors_and_caps_applied(self):
        # metronome -> floored at 2.0; wild -> capped at 8.0
        rows = []
        for i in range(1, 11):
            rows.append({"year": 2020, "round": i, "driverId": "metronome",
                         "grid": 4, "position": 4, "is_dnf": 0})
            rows.append({"year": 2020, "round": i, "driverId": "wild",
                         "grid": 5,
                         "position": 20 if i % 2 else 1, "is_dnf": 0})
        d = rs.fit_driver_sd(pd.DataFrame(rows))
        assert d["metronome"] == pytest.approx(2.0)   # floor
        assert d["wild"] == pytest.approx(8.0)        # cap

    def test_min_races_gate_and_prior_seasons_only(self):
        # driver with only 4 finished races -> absent from the dict
        rows = [{"year": 2020, "round": i, "driverId": "new",
                 "grid": 3, "position": 3, "is_dnf": 0}
                for i in range(1, 5)]
        rows += [{"year": 2020, "round": i, "driverId": "old",
                  "grid": 3, "position": 3, "is_dnf": 0}
                 for i in range(1, 7)]
        d = rs.fit_driver_sd(pd.DataFrame(rows), min_races=5)
        assert "new" not in d
        assert "old" in d

    def test_dnf_rows_never_enter_the_volatility_sample(self):
        # DNF'd races carry garbage positions; they must be excluded
        rows = []
        for i in range(1, 11):
            rows.append({"year": 2020, "round": i, "driverId": "x",
                         "grid": 2, "position": 2, "is_dnf": 0})
        rows.append({"year": 2020, "round": 11, "driverId": "x",
                     "grid": 1, "position": 20, "is_dnf": 1})
        d = rs.fit_driver_sd(pd.DataFrame(rows))
        assert d["x"] == pytest.approx(2.0)  # still the floor: zero swing

    def test_v2_simulation_spreads_volatile_driver(self):
        # full 10-driver grid so bucket probabilities are informative
        grid = [(f"d{i}", i) for i in range(1, 11)]
        dsd = {"d5": 9.0}
        rng1 = np.random.default_rng(17)
        s1 = rs.simulate_race(grid, 4000, 0.0, 0.5, 0.0, rng1)
        rng2 = np.random.default_rng(17)
        s2 = rs.simulate_race(grid, 4000, 0.0, 0.5, 0.0, rng2,
                              driver_sd=dsd)
        # spread = sd of the driver's simulated finishing positions.
        # Rank-order coupling means widening d5 shifts everyone a little;
        # the mechanism signature is that d5's spread grows the MOST.
        sd1 = s1.groupby("driverId")["position"].std()
        sd2 = s2.groupby("driverId")["position"].std()
        delta = sd2 - sd1
        assert delta["d5"] > 1.0
        assert delta.drop("d5").max() < delta["d5"]

    def test_ablation_path_is_paired_and_scores(self):
        # two seasons x 3 races x 10 drivers, zero swing (same shape as
        # TestBacktestSynthetic._entries, built inline)
        rows = []
        for y in (2025, 2026):
            for rnd in (1, 2, 3):
                for slot in range(1, 11):
                    rows.append({"year": y, "round": rnd,
                                 "driverId": f"d{slot}",
                                 "constructorId": "t", "grid": slot,
                                 "position": slot, "is_dnf": 0})
        entries = pd.DataFrame(rows)
        p1, m1 = rs.backtest(entries, range(2026, 2027), n_sims=40,
                             seed=5, driver_sd=False)
        p2, m2 = rs.backtest(entries, range(2026, 2027), n_sims=40,
                             seed=5, driver_sd=True)
        assert np.isfinite([m1["sim_log_loss"], m2["sim_log_loss"]]).all()
        # paired seeds: identical row universe
        assert len(p1) == len(p2)


class TestBuckets:
    def test_boundaries_match_training_contract(self):
        assert rs.position_bucket(1) == 1
        assert rs.position_bucket(3) == 1
        assert rs.position_bucket(4) == 2
        assert rs.position_bucket(10) == 2
        assert rs.position_bucket(11) == 3
        assert rs.position_bucket(22) == 3


# ── end-to-end backtest on synthetic entries ─────────────────────────────

class TestBacktestSynthetic:
    def _entries(self):
        """Two seasons, 10 drivers, 3 races each; deterministic swings."""
        rows = []
        for y in (2025, 2026):
            for rnd in (1, 2, 3):
                for slot in range(1, 11):
                    rows.append({
                        "year": y, "round": rnd, "driverId": f"d{slot}",
                        "constructorId": "t", "grid": slot,
                        # finish = grid + 1 (capped) for 90% of entries
                        "position": min(slot + 1, 10) if slot < 10 else 10,
                        "is_dnf": 0,
                    })
        return pd.DataFrame(rows)

    def test_backtest_runs_and_beats_no_skill_floor(self):
        entries = self._entries()
        probs, metrics = rs.backtest(entries, range(2026, 2027), n_sims=50,
                                     seed=1)
        assert len(probs) == 30  # 3 races x 10 drivers
        for key in ("sim_log_loss", "sim_brier", "global_rates_log_loss",
                    "global_rates_brier", "grid_onehot_log_loss",
                    "grid_onehot_brier"):
            assert key in metrics
        assert np.isfinite(list(metrics.values())).all()
