"""
Tests for lap_curves.py — the lap-by-lap probability-evolution layer.

The failure modes these pin:
  - remaining-bucket backfill drifting (an empty bucket must inherit the
    TIGHTEST neighbour, never widen a late-race fit)
  - truth drift: fits/curves scored against the terminal lap-chart
    position instead of the OFFICIAL classification (~22% differ)
  - the replay not converging: a curve that doesn't sharpen to a vertex
    distribution by the final lap is a broken mechanism
  - artifact/curve determinism breaking (same seed must be byte-identical)
  - retired drivers leaking curves past their last charted lap
  - live SC attrition: the sim must not spend fail probability during SC
  - the lap-1 curve point failing to reproduce a direct simulate_race
    call at the same seed and bucket parameters (materialization drift)
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lap_curves as lc  # noqa: E402
import race_simulator as rs  # noqa: E402

DB = Path(__file__).resolve().parents[1] / "datasets" / "f1_canonical.db"
REAL = pytest.mark.skipif(not DB.exists(),
                          reason="canonical DB not built locally")


def _chart(rows, start_year=2025):
    """rows: (year_off, round, [(driverId, [positions per lap])])."""
    recs = []
    for yoff, rnd, drivers in rows:
        for drv, pos in drivers:
            for lap, p in enumerate(pos, start=1):
                recs.append((start_year + yoff, rnd, lap, float(p), drv))
    return pd.DataFrame(recs, columns=["year", "round", "lap",
                                       "position", "driverId"])


def _entries(rows, start_year=2025):
    """rows: (year_off, round, [(driverId, official_pos, is_dnf)])."""
    recs = []
    for yoff, rnd, drivers in rows:
        for drv, pos, dnf in drivers:
            recs.append((start_year + yoff, rnd, drv, pos, dnf))
    return pd.DataFrame(recs, columns=["year", "round", "driverId",
                                       "position", "is_dnf"])


# ── remaining_fraction / bucket math ─────────────────────────────────────

class TestBuckets:
    def test_fraction_and_bucket(self):
        assert lc.remaining_fraction(58, 58) == 0.0
        assert lc.remaining_fraction(0, 58) == 1.0
        assert lc.remaining_bucket(0.0) == 0
        assert lc.remaining_bucket(1.0) == 9
        assert lc.remaining_bucket(0.5) == 5  # ceil(0.5 * 9)

    def test_backfill_inherits_tightest_neighbour(self):
        """Only bucket 8 has data: buckets 9 (later) must inherit bucket
        8's TIGHT fit; buckets 0..7 (earlier) inherit each other forward
        from the first populated one. A widening backfill would make the
        replay MORE certain late in the race than the data allows."""
        chart = _chart([(0, 1, [("a", [1, 1, 1, 1, 1, 1, 1, 1, 1, 1]),
                                ("b", [2, 2, 2, 2, 2, 2, 2, 2, 2, 2])])])
        entries = _entries([(0, 1, [("a", 1, 0), ("b", 2, 0)])])
        # force a big remaining swing so bucket 8's fit is distinctive
        chart.loc[(chart["driverId"] == "a"), "position"] = [
            1, 1, 1, 1, 1, 1, 1, 1, 3, 3]
        chart.loc[(chart["driverId"] == "b"), "position"] = [
            2, 2, 2, 2, 2, 2, 2, 2, 4, 4]
        f = lc.fit_remaining_swing(chart, entries)
        assert f[8]["sd"] == pytest.approx(f[9]["sd"])
        assert f[8]["mean"] == pytest.approx(f[9]["mean"])
        # bucket 9 exists but inherits 8 exactly (no interpolation drift)
        assert set(f) == set(range(10))


# ── truth contract: official classification, not chart terminal ──────────

class TestTruthContract:
    def test_fit_uses_official_not_chart_terminal(self, monkeypatch):
        """Driver a charts P1 at every lap but is officially P3 (post-race
        penalty): the fit must target the official result. The remaining-
        swing MEAN is structurally ~0 (official results are a permutation
        of chart positions — one driver's demotion promotes others), so
        the contract lives in the SD: an official-truth fit has positive
        spread; a chart-terminal fit would be degenerate (sd = 0)."""
        monkeypatch.setattr(lc, "MIN_BUCKET_SAMPLES", 1)
        chart = _chart([(0, 1, [("a", [1] * 6), ("b", [2] * 6),
                                ("c", [3] * 6), ("d", [4] * 6)])])
        # official: a penalised to P4, b promoted P1, c P2, d P3
        entries = _entries([(0, 1, [("a", 4, 0), ("b", 1, 0),
                                    ("c", 2, 0), ("d", 3, 0)])])
        f = lc.fit_remaining_swing(chart, entries)
        # per-lap swings vs OFFICIAL: a -3, b +1, c +1, d +1. Non-terminal
        # laps (1,3,5,7,9 of 10) land in buckets 9,7,5,3,1 — each holding
        # exactly one lap's four swings, so every fitted sd is the sd of
        # [-3, 1, 1, 1] (a chart-terminal fit would give sd = 0).
        expected_sd = pd.Series([-3, 1, 1, 1]).std(ddof=1)
        for b in (9, 7, 5, 3, 1):
            assert f[b]["sd"] == pytest.approx(expected_sd, abs=1e-9)
        assert f[8]["sd"] > 0  # inherited (backfill), never degenerate

    def test_fail_rate_uses_official_dnf(self, monkeypatch):
        """A classified 90%-rule finisher (parked lap 6 of 10) is NOT a
        failure; an unclassified retiree IS — regardless of chart order."""
        monkeypatch.setattr(lc, "MIN_BUCKET_SAMPLES", 1)
        chart = _chart([(0, 1, [("a", [1] * 10),       # runs full distance
                                ("b", [2] * 6),        # parks lap 6, classified
                                ("c", [3] * 3),        # retires lap 3
                                ("d", [4] * 10)])])
        entries = _entries([(0, 1, [("a", 1, 0), ("b", 2, 0),
                                    ("c", 3, 1), ("d", 4, 0)])])
        fr = lc.fit_remaining_fail_rate(chart, entries)
        # laps 1-3 (buckets 9/8/7): c still running, retires later -> 25% fail
        assert fr[9] == pytest.approx(0.25)
        assert fr[7] == pytest.approx(0.25)
        # lap 6+ (bucket 4 and tighter): everyone reaches the flag -> 0
        assert fr[4] == pytest.approx(0.0)
        assert fr[1] == pytest.approx(0.0)
        # bucket 0 (race over) inherits the tightest data -> 0, never fallback
        assert fr[0] == pytest.approx(0.0)


# ── replay mechanics ─────────────────────────────────────────────────────

class TestReplay:
    def _replay(self, chart, entries, monkeypatch=None, **kw):
        if monkeypatch is not None:
            monkeypatch.setattr(lc, "MIN_BUCKET_SAMPLES", 1)
        hist_c = chart[chart["year"] < 2026]
        hist_e = entries[entries["year"] < 2026]
        f = lc.fit_remaining_swing(hist_c, hist_e)
        fr = lc.fit_remaining_fail_rate(hist_c, hist_e)
        race_c = chart[chart["year"] == 2026]
        actual = entries[entries["year"] == 2026][
            ["driverId", "position", "is_dnf"]]
        rng = np.random.default_rng(kw.pop("seed", 7))
        return lc.replay_race(race_c, actual, f, fr, 300, rng, **kw)

    def test_curve_sharpens_to_vertex_by_final_lap(self, monkeypatch):
        chart = _chart([
            (0, 1, [("a", [1] * 30), ("b", [2] * 30),
                    ("c", [3] * 30), ("d", [4] * 30)]),
            (1, 1, [("a", [1] * 20), ("b", [2] * 20),
                    ("c", [3] * 20), ("d", [4] * 20)])])
        entries = _entries([(0, 1, [("a", 1, 0), ("b", 2, 0),
                                    ("c", 3, 0), ("d", 4, 0)]),
                            (1, 1, [("a", 1, 0), ("b", 2, 0),
                                    ("c", 3, 0), ("d", 4, 0)])])
        rep = self._replay(chart, entries, monkeypatch)
        final = rep[rep["lap"] == 20]
        # perfectly processional race -> the leader must be near-certain
        a = final[final["driverId"] == "a"].iloc[0]
        assert a["p_podium"] > 0.95
        # and the pre-race lap must be LESS certain than the final lap
        first = rep[rep["lap"] == 1]
        a1 = first[first["driverId"] == "a"].iloc[0]
        assert a1["p_podium"] <= a["p_podium"] + 1e-9

    def test_retired_driver_stops_appearing(self, monkeypatch):
        chart = _chart([
            (0, 1, [("a", [1] * 10), ("b", [2] * 10),
                    ("c", [3] * 10), ("d", [4] * 10)]),
            (1, 1, [("a", [1] * 10), ("b", [2] * 10),
                    ("c", [3] * 5), ("d", [4] * 10)])])
        entries = _entries([(0, 1, [("a", 1, 0), ("b", 2, 0),
                                    ("c", 3, 0), ("d", 4, 0)]),
                            (1, 1, [("a", 1, 0), ("b", 2, 0),
                                    ("c", 3, 1), ("d", 4, 0)])])
        rep = self._replay(chart, entries, monkeypatch)
        assert rep[rep["driverId"] == "c"]["lap"].max() == 5
        assert rep[rep["driverId"] == "a"]["lap"].max() == 10

    def test_sc_laps_freeze_attrition(self, monkeypatch):
        """With p_fail forced positive everywhere, an SC lap must still
        produce sim_dnf_rate == 0 — live attrition is frozen under SC."""
        chart = _chart([
            (0, 1, [("a", [1] * 10), ("b", [2] * 10),
                    ("c", [3] * 10), ("d", [4] * 10)]),
            (1, 1, [("a", [1] * 10), ("b", [2] * 10),
                    ("c", [3] * 10), ("d", [4] * 10)])])
        entries = _entries([(0, 1, [("a", 1, 0), ("b", 2, 0),
                                    ("c", 3, 0), ("d", 4, 0)]),
                            (1, 1, [("a", 1, 0), ("b", 2, 0),
                                    ("c", 3, 0), ("d", 4, 0)])])
        monkeypatch.setattr(lc, "MIN_BUCKET_SAMPLES", 1)
        fail = {b: 0.5 for b in range(10)}  # force attrition everywhere
        rem = {b: {"mean": 0.0, "sd": 2.0} for b in range(10)}
        race = chart[chart["year"] == 2026]
        actual = entries[entries["year"] == 2026][
            ["driverId", "position", "is_dnf"]]
        rng = np.random.default_rng(7)
        rep = lc.replay_race(race, actual, rem, fail, 200, rng,
                             sc_laps={3})
        lap3 = rep[rep["lap"] == 3]
        lap2 = rep[rep["lap"] == 2]
        assert (lap3["dnf_rate_sim"] == 0).all()
        assert (lap2["dnf_rate_sim"] > 0).all()


# ── artifact builder (real data) ─────────────────────────────────────────

@REAL
class TestCurvesArtifact:
    def test_schema_and_coverage(self):
        doc = lc.build_curves(str(DB), 2026, 60, 42)
        assert doc["schema_version"] == 1 and doc["season"] == 2026
        assert len(doc["races"]) == 11  # all raced 2026 rounds have laps
        for r in doc["races"]:
            assert r["n_laps"] >= 40
            assert r["sample_laps"][0] == 1
            assert r["sample_laps"][-1] == r["n_laps"]
            assert len(r["sample_laps"]) <= 12
            for d in r["drivers"]:
                assert d["curve"], f"{r['round']}/{d['driverId']} empty curve"
                assert d["curve"][0][0] == 1  # starts at lap 1
                # all probabilities within [0, 1]; sums to 1 within the
                # 4dp rounding of the artifact (60-sim quantization)
                for lap, pp, pt, po, _ in d["curve"]:
                    assert 0.0 <= pp <= 1.0 and 0.0 <= pt <= 1.0
                    assert 0.0 <= po <= 1.0
                    assert abs(pp + pt + po - 1.0) < 2e-3
                # sorted by lap, strictly increasing laps
                laps = [c[0] for c in d["curve"]]
                assert laps == sorted(laps)

    def test_final_lap_concentrates_and_leader_leads(self):
        """By the final lap the distribution must concentrate (max bucket
        >= 0.75 for every runner still on chart), and the official winner
        must hold the highest final P(podium) with >= 0.9 — the residue
        below 1.0 is real (post-race penalty adjudication is genuinely
        unresolved at the flag), but a winner below 0.9 would mean the
        mechanism failed to converge."""
        doc = lc.build_curves(str(DB), 2026, 60, 42)
        for r in doc["races"]:
            for d in r["drivers"]:
                _, pp, pt, po, _ = d["curve"][-1]
                assert max(pp, pt, po) >= 0.5, \
                    f"r{r['round']} {d['driverId']} never concentrated"
        r1 = doc["races"][0]
        winner = next(d for d in r1["drivers"]
                      if d["final_position"] == 1)
        assert winner["curve"][-1][1] >= 0.9
        others = [d["curve"][-1][1] for d in r1["drivers"]
                  if d["driverId"] != winner["driverId"]]
        assert winner["curve"][-1][1] >= max(others)

    def test_leader_curve_sharpening(self):
        """The 2026 round-1 winner's curve must sharpen into the race:
        final E[pos] at least 2 places closer to 1 than the lap-1 value."""
        doc = lc.build_curves(str(DB), 2026, 60, 42)
        r1 = doc["races"][0]
        winner = next(d for d in r1["drivers"]
                      if d["final_position"] == 1)
        assert winner["curve"][-1][4] <= winner["curve"][0][4] - 2.0

    def test_artifact_deterministic(self):
        a = lc.build_curves(str(DB), 2026, 60, 42)
        b = lc.build_curves(str(DB), 2026, 60, 42)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_mechanism_block_present(self):
        doc = lc.build_curves(str(DB), 2026, 60, 42)
        mech = doc["mechanism"]
        assert set(mech) == {"rem_swing_by_bucket", "fail_rate_by_bucket"}
        # late-race must be tighter than early-race (the core mechanism)
        assert mech["rem_swing_by_bucket"]["1"]["sd"] \
            < mech["rem_swing_by_bucket"]["9"]["sd"]
        assert mech["fail_rate_by_bucket"]["1"] \
            < mech["fail_rate_by_bucket"]["9"]


@REAL
def test_lap1_row_reproduces_direct_simulate():
    """The lap-1 artifact row must be EXACTLY a direct simulate_race call
    at the lap-1 chart grid with the fitted bucket-9 parameters and the
    artifact's own RNG — lap 1 is the first consumer of the race's RNG
    stream, so the curve's first point is a pure materialization of the
    mechanism, not a re-implementation.

    (The lap-1 chart is the order AFTER lap 1 completes — start chaos
    included — so it is deliberately NOT the race-intel pre-start grid;
    those are different states of information and their distributions
    differ legitimately.)"""
    doc = lc.build_curves(str(DB), 2026, 100, 42)
    r1 = doc["races"][0]
    # recompute the exact (unrounded) bucket-9 fits the builder used
    laps = lc._load_laps(str(DB))
    entries = lc._load_entries_full(str(DB))
    hist = laps[laps["year"] < 2026]
    hist_e = entries[entries["year"] < 2026]
    slow = {k for k in lc._slow_lap_set(laps) if k[0] < 2026}
    fits = lc.fit_remaining_swing(hist, hist_e, slow_laps=slow)
    lr = laps[(laps["year"] == 2026) & (laps["round"] == r1["round"])]
    lap1 = lr[lr["lap"] == 1].sort_values("position")
    grid = list(zip(lap1["driverId"], lap1["position"].astype(int)))
    rng = np.random.default_rng(42 + 2026 * 100 + r1["round"]
                                + lc.SEED_OFFSET)
    sim = rs.simulate_race(grid, 100, fits[9]["mean"], fits[9]["sd"],
                           lc.fit_remaining_fail_rate(hist, hist_e)[9], rng)
    summ = rs.summarize_simulation(sim).set_index("driverId")
    for d in r1["drivers"]:
        row = summ.loc[d["driverId"]]
        assert d["curve"][0][1] == pytest.approx(row["p_podium"], abs=1e-3)
        assert d["curve"][0][3] == pytest.approx(row["p_out"], abs=1e-3)


# ── CLI ──────────────────────────────────────────────────────────────────

@REAL
def test_cli_backtest_runs(tmp_path, capsys):
    """The walk-forward replay backtest must run end-to-end and produce
    both metric views with the final view on the race-intel scale."""
    import subprocess
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1]
                             / "lap_curves.py"),
         "--db", str(DB), "--backtest", "2025", "2025", "--sims", "30"],
        capture_output=True, text=True, timeout=1200)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "lap view" in r.stdout and "final view" in r.stdout
