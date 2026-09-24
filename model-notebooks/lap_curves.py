"""
lap_curves.py — lap-by-lap replay: the probability-evolution curves.

Reruns the Phase-3 scenario simulator lap by lap over a COMPLETED race,
updating the fitted mechanisms point-in-time as the race information
changes. The output per driver is a per-lap vector of P(podium) /
P(points) / P(out) — the curve a dashboard animates to show HOW the race
happened, and the calibration record for the claim those curves are
honest (the walk-forward replay backtest below).

The mechanism (identical machinery to race_simulator.simulate_race —
same classification contract, same keys, same jitter):

  At each lap t with n_t runners remaining, re-fit the swing parameters
  ON THE REMAINING RACE ONLY: the distribution of (position at t) −
  (final position) over FINISHED entries of point-in-time historical
  races, restricted to laps at the same remaining-fraction bucket.
  A simulation needs to move a driver ~0 places at lap 58 of 58 but
  several places at lap 5 of 58 — the same machinery with
  fraction-dependent parameters. SC periods (slow laps vs the field
  median, the Phase-1 detector) are excluded from the historical swing
  sample: under SC the whole field compresses toward the SC order, so
  positions move for reasons the swing distribution must not learn.

  1. Remaining-swing: final = pos_t + delta, delta ~ Normal(rem_mean(t),
     rem_sd(t)) where rem_mean/rem_sd are fitted per remaining-fraction
     bucket (0..1 → 10 buckets) from historical races: for each finished
     entry, swing_t = position at t − final position, measured at laps
     with the same remaining fraction. By lap t the future differs only
     by the remaining swing, so the parameters re-fit point-in-time.
  2. Attrition: the historical runner-fail rate in the same bucket —
     the fraction of runners AT a similar remaining fraction who failed
     to reach the chequered flag. A driver leading at lap 55 of 58 is
     still subject to a small real failure probability, taken from the
     runners around the same stage of historical races.

Truth contract (verified in the canonical DB): official classification
≠ terminal lap-chart position (~22% of entries differ — post-race
penalties, retirements on the final lap, lapped order). The replay's
"actual" is the OFFICIAL classification (fact_race_entry.position),
which is what every other layer scores against.

Determinism: every entry point takes an explicit seed; same seed ⇒
byte-identical output. The artifact builder assigns each race a
dedicated RNG (seed 42 + year*100 + round + 1_000_000 — offset from the
race-intel artifact's stream so the two artifacts never share entropy).

Usage:
    python lap_curves.py --db datasets/f1_canonical.db \
        --datasets ./datasets --out datasets/lap_curves.json \
        --season 2026 --sims 400
    python lap_curves.py --db datasets/f1_canonical.db --backtest 2019 2026
"""
import argparse
import json
import sqlite3

import numpy as np
import pandas as pd

import race_simulator as rs
from error_decomposition import race_lap_evidence

# Remaining-fraction buckets: fraction of the race left = (L - t) / L,
# mapped onto BUCKETS. The LAST bucket (index 0) is "no laps remain";
# bucket boundaries are spaced geometrically-ish toward zero so late-race
# laps (where position locks in) get finer resolution.
N_BUCKETS = 10
MIN_BUCKET_SAMPLES = 30
# A lap is EXCLUDED from the historical swing sample — and live attrition
# is suppressed while it runs — when its field-median lap time exceeds the
# race's green median by more than this factor (the Phase-1 SC detector's
# threshold, reused verbatim: one taxonomy everywhere).
SC_SLOW_FACTOR = 1.35

GLOBAL_FALLBACK_REMAINING = {"mean": 0.0, "sd": 4.11, "fail_rate": 0.15}

SEED_OFFSET = 1_000_000  # lap-curves RNG stream, disjoint from race-intel


def remaining_fraction(lap: int, n_laps: int) -> float:
    """Fraction of the race remaining after lap `lap` completes: 1 - t/L."""
    if n_laps <= 0:
        return 0.0
    return float(max(0, n_laps - lap)) / float(n_laps)


def remaining_bucket(frac: float) -> int:
    """Bucket index 0..N_BUCKETS-1; 0 = race over, N_BUCKETS-1 = just started."""
    if frac <= 0.0:
        return 0
    return int(np.ceil(frac * (N_BUCKETS - 1)))


# ── fitting ──────────────────────────────────────────────────────────────

def fit_remaining_swing(laps_hist: pd.DataFrame,
                        entries_hist: pd.DataFrame,
                        slow_laps: set | None = None,
                        buckets: np.ndarray | None = None
                        ) -> dict[int, dict]:
    """
    Per-bucket remaining-swing parameters from historical lap charts.

    `laps_hist` carries year, round, lap, driverId, position (the lap
    chart, one row per runner-lap); `entries_hist` the official
    classification (year, round, driverId, position, is_dnf) — both
    already filtered to seasons ≤ Y-1. The fit's target is the OFFICIAL
    classification, not the terminal lap-chart position: ~22% of entries
    differ (post-race penalties, classified retirements, lapped order)
    and the simulator's own output IS a classification. swing_t =
    position at lap t − official final position, pooled across races per
    remaining-fraction bucket.

    `slow_laps` (optional): {(year, round, lap)} sets of SC/VSC-slow laps
    (the Phase-1 field-median detector). Those laps are excluded from the
    sample: under SC the field compresses toward the SC order, and the
    swing distribution must not learn a compression it will not see on a
    green flag (the sim freezes attrition under SC instead).

    Returns {bucket: {mean, sd}}; buckets with < MIN_BUCKET_SAMPLES
    samples fall back to the nearest populated bucket below (later in
    the race = more constrained), else the global fallback.
    """
    d = laps_hist.copy()
    d["position"] = pd.to_numeric(d["position"], errors="coerce")
    d = d[d["position"].notna()]

    m = d.merge(entries_hist[["year", "round", "driverId", "position"]]
                .rename(columns={"position": "final_pos"}),
                on=["year", "round", "driverId"], how="inner")
    m["n_laps"] = m.groupby(["year", "round"])["lap"].transform("max")
    m["frac"] = m.apply(
        lambda r: remaining_fraction(r["lap"], r["n_laps"]), axis=1)
    m["bucket"] = m["frac"].map(remaining_bucket)
    if slow_laps:
        m = m[~pd.MultiIndex.from_frame(
            m[["year", "round", "lap"]]).isin(slow_laps)]
    m["swing"] = m["position"] - m["final_pos"]

    if buckets is None:
        buckets = np.arange(N_BUCKETS)
    fits: dict[int, dict] = {}
    for b in buckets:
        s = m.loc[m["bucket"] == b, "swing"]
        if len(s) >= MIN_BUCKET_SAMPLES:
            fits[int(b)] = {"mean": float(s.mean()),
                            "sd": float(s.std(ddof=1))}
    # backfill: empty buckets inherit the nearest populated HIGHER bucket
    # index (later in the race = tighter) else the tightest available
    filled: dict[int, dict] = {}
    last = None
    for b in range(N_BUCKETS):
        if b in fits:
            last = fits[b]
        filled[b] = last if last is not None else None
    # forward-fill from the front (early laps) for buckets before any fit
    first = next((b for b in range(N_BUCKETS) if filled.get(b)), None)
    if first is not None:
        for b in range(first):
            filled[b] = filled[first]
    out = {}
    for b in range(N_BUCKETS):
        if filled.get(b) is not None:
            out[b] = filled[b]
        else:
            out[b] = dict(GLOBAL_FALLBACK_REMAINING)
    return out


def fit_remaining_fail_rate(laps_hist: pd.DataFrame,
                            entries_hist: pd.DataFrame,
                            buckets: np.ndarray | None = None
                            ) -> dict[int, float]:
    """
    Per-bucket attrition: P(a runner still racing at the START of this
    stage ends the race UNCLASSIFIED), fitted on historical runner-laps
    in the same remaining-fraction bucket. Truth is the OFFICIAL
    classification (`entries_hist.is_dnf`), never chart presence — a
    driver who parks on lap 55 of 58 and is still classified (the 90%
    rule) is a finisher in the sim's contract too. Late-race laps get
    tiny rates; early laps carry most of the risk. Uses the same
    backfill rule as fit_remaining_swing.
    """
    d = laps_hist.copy()
    d["position"] = pd.to_numeric(d["position"], errors="coerce")
    d = d[d["position"].notna()]
    d = d.merge(entries_hist[["year", "round", "driverId", "is_dnf"]],
                on=["year", "round", "driverId"], how="inner")
    d["n_laps"] = d.groupby(["year", "round"])["lap"].transform("max")
    d["frac"] = d.apply(
        lambda r: remaining_fraction(r["lap"], r["n_laps"]), axis=1)
    d["bucket"] = d["frac"].map(remaining_bucket)
    reached = 1 - d["is_dnf"].astype(int)

    if buckets is None:
        buckets = np.arange(N_BUCKETS)
    rates: dict[int, float] = {}
    for b in buckets:
        mask = d["bucket"] == b
        if mask.sum() >= MIN_BUCKET_SAMPLES:
            # fail rate = 1 - share of runner-laps in this bucket whose
            # driver saw the chequered flag
            rates[int(b)] = float(1.0 - reached[mask].mean())
    filled = {}
    last = None
    for b in range(N_BUCKETS):
        if b in rates:
            last = rates[b]
        filled[b] = last
    first = next((b for b in range(N_BUCKETS) if filled.get(b) is not None),
                 None)
    out = {}
    for b in range(N_BUCKETS):
        if filled.get(b) is not None:
            out[b] = filled[b]
        elif first is not None:
            out[b] = rates[first]
        else:
            out[b] = GLOBAL_FALLBACK_REMAINING["fail_rate"]
    return out


def _runner_laps_at(laps_race: pd.DataFrame, lap: int) -> pd.DataFrame:
    """Rows of `laps_race` (one race) at exactly `lap` with positions."""
    return laps_race[(laps_race["lap"] == lap)
                     & laps_race["position"].notna()].copy()


def replay_race(laps_race: pd.DataFrame, actual: pd.DataFrame,
                rem_swing: dict[int, dict], fail: dict[int, float],
                n_sims: int, rng: np.random.Generator,
                sc_laps: set[int] | None = None) -> pd.DataFrame:
    """
    Replay one race lap by lap.

    `laps_race`: the race's lap chart (year, round, lap, driverId,
    position). `actual`: the official classification (driverId, position,
    is_dnf) — the truth the replay's curves are scored against.
    `rem_swing`/`fail`: per-bucket parameters fitted point-in-time.
    `sc_laps`: this race's SC/VSC-slow lap numbers (Phase-1 detector);
    live attrition is frozen on those laps — under SC, running cars are
    not retiring, and the sim must not spend that probability.

    Returns a long frame: one row per (lap, driver) with
    p_podium/p_points/p_out/expected_position for every driver present
    at that lap. Retired drivers simply stop appearing (the chart's
    own semantics).
    """
    race_L = int(laps_race["lap"].max())
    sc = sc_laps or set()
    out_rows = []
    for lap in range(1, race_L + 1):
        at = _runner_laps_at(laps_race, lap)
        if at.empty:
            continue
        runners = at["driverId"].tolist()
        b = remaining_bucket(remaining_fraction(lap, race_L))
        params = rem_swing.get(b, dict(GLOBAL_FALLBACK_REMAINING))
        p_fail = 0.0 if lap in sc else fail.get(
            b, GLOBAL_FALLBACK_REMAINING["fail_rate"])

        grid = [(d, int(p)) for d, p in zip(runners, at["position"])]
        sim = rs.simulate_race(grid, n_sims, params["mean"], params["sd"],
                               p_fail, rng)
        summ = rs.summarize_simulation(sim)
        summ["lap"] = lap
        out_rows.append(summ)

    if not out_rows:
        return pd.DataFrame(columns=["driverId", "lap", "p_podium",
                                     "p_points", "p_out",
                                     "expected_position", "sim_dnf_rate"])
    res = pd.concat(out_rows, ignore_index=True)
    # attach the official classification for scoring convenience
    res = res.merge(actual[["driverId", "position", "is_dnf"]],
                    on="driverId", how="left")
    return res


def actual_bucket(position: float) -> int:
    return rs.position_bucket(position)


# ── artifact builder ─────────────────────────────────────────────────────

def _load_laps(db_path: str) -> pd.DataFrame:
    con = sqlite3.connect(db_path)
    try:
        return pd.read_sql(
            "SELECT year, round, lap, driverId, position, milliseconds "
            "FROM fact_lap WHERE position IS NOT NULL", con)
    finally:
        con.close()


def _load_entries_full(db_path: str) -> pd.DataFrame:
    con = sqlite3.connect(db_path)
    try:
        return pd.read_sql(
            "SELECT year, round, driverId, position, is_dnf "
            "FROM fact_race_entry", con)
    finally:
        con.close()


def _curves_doc_for_race(replay: pd.DataFrame, actual: pd.DataFrame,
                         laps_race: pd.DataFrame, n_laps: int) -> dict:
    """Render one race's curves into compact artifact JSON.

    Every driver gets an array of [lap, p_podium, p_points, p_out,
    expected_position] tuples at the artifact's sample laps (uniformly
    spaced, always including lap 1 and the final lap — the endpoints
    carry the whole story).

    Drivers leave the lap chart when they stop (~32% of classified
    finishers park early under the 90% rule). Once off the chart a
    car's race is DETERMINED — runners cannot be passed by a parked
    car — so the curve is extended with the locked outcome instead of
    freezing: officially retired drivers go to P(out)=1; classified
    drivers lock at the bucket of their last charted position (the
    residue is post-race penalties, which no live model can see)."""
    sample_laps = sorted(set(
        np.unique(np.linspace(1, n_laps, min(n_laps, 12)).astype(int))
        .tolist()))
    act_idx = actual.set_index("driverId")
    drivers = []
    for drv, g in replay.groupby("driverId"):
        g = g.sort_values("lap").set_index("lap")
        last_charted = int(g.index.max())
        act = act_idx.loc[drv] if drv in act_idx.index else None
        curve = []
        for lap in sample_laps:
            if lap in g.index:
                r = g.loc[lap]
                curve.append([int(lap), round(float(r["p_podium"]), 4),
                              round(float(r["p_points"]), 4),
                              round(float(r["p_out"]), 4),
                              round(float(r["expected_position"]), 2)])
            elif lap > last_charted and act is not None:
                # off the chart: the outcome is locked — extend it
                if int(act["is_dnf"]) == 1:
                    curve.append([int(lap), 0.0, 0.0, 1.0,
                                  float(g["expected_position"].iloc[-1])])
                else:
                    pos = float(act["position"]) \
                        if pd.notna(act["position"]) else 99.0
                    b = rs.position_bucket(pos)
                    onehot = [1.0, 0.0, 0.0] if b == 1 else (
                        [0.0, 1.0, 0.0] if b == 2 else [0.0, 0.0, 1.0])
                    curve.append([int(lap), *onehot,
                                  float(g["expected_position"].iloc[-1])])
            # lap < first charted lap: absent (data hole) — skip
        drivers.append({
            "driverId": drv,
            "final_position": (None if act is None or pd.isna(
                act["position"]) else int(act["position"])),
            "curve": curve,
        })
    drivers.sort(key=lambda d: (d["final_position"] is None,
                                d["final_position"]
                                if d["final_position"] is not None else 0))
    return {
        "n_laps": n_laps,
        "sample_laps": [int(x) for x in sample_laps],
        "drivers": drivers,
    }


def _slow_lap_set(all_laps: pd.DataFrame) -> set:
    """{(year, round, lap)} flagged SC/VSC-slow by the Phase-1
    field-median detector — the single shared SC taxonomy."""
    le = race_lap_evidence(all_laps)
    slow = le[le["is_slow_lap"]]
    return set(zip(slow["year"], slow["round"], slow["lap"]))


def build_curves(db_path: str, season: int, n_sims: int, seed: int
                 ) -> dict:
    """
    Build the lap-curves artifact for `season`: every raced round, every
    driver, a per-lap probability-evolution vector. Fitted strictly on
    seasons < season (walk-forward); deterministic under seed.
    """
    laps = _load_laps(db_path)
    entries = _load_entries_full(db_path)
    season_laps = laps[laps["year"] == season]
    raced_rounds = sorted(season_laps["round"].unique().tolist())
    if not raced_rounds:
        raise SystemExit(f"no lap data for season {season}")

    hist = laps[laps["year"] < season]
    entries_hist = entries[entries["year"] < season]
    slow_all = _slow_lap_set(laps)
    hist_slow = {k for k in slow_all if k[0] < season}
    rem_swing = fit_remaining_swing(hist, entries_hist,
                                    slow_laps=hist_slow)
    fail = fit_remaining_fail_rate(hist, entries_hist)

    races = []
    for rnd in raced_rounds:
        lr = season_laps[season_laps["round"] == rnd]
        actual = entries[(entries["year"] == season)
                         & (entries["round"] == rnd)][
            ["driverId", "position", "is_dnf"]]
        sc_laps = {lap for (y, r, lap) in slow_all
                   if y == season and r == rnd}
        rng = np.random.default_rng(seed + season * 100 + rnd + SEED_OFFSET)
        replay = replay_race(lr, actual, rem_swing, fail, n_sims, rng,
                             sc_laps=sc_laps)
        races.append({
            "year": season, "round": int(rnd),
            **_curves_doc_for_race(replay, actual, lr,
                                   int(lr["lap"].max())),
        })

    return {
        "schema_version": 1,
        "season": season,
        "n_sims": n_sims,
        "buckets": N_BUCKETS,
        "mechanism": {
            "rem_swing_by_bucket": {str(b): {"mean": round(v["mean"], 3),
                                             "sd": round(v["sd"], 3)}
                                    for b, v in rem_swing.items()},
            "fail_rate_by_bucket": {str(b): round(v, 4)
                                    for b, v in fail.items()},
        },
        "races": races,
    }


# ── walk-forward replay backtest ─────────────────────────────────────────

def replay_backtest(db_path: str, years: range, n_sims: int, seed: int
                    ) -> tuple[pd.DataFrame, dict]:
    """
    Walk-forward calibration of the lap curves: for each season Y, fit
    on seasons ≤ Y-1, replay every race of Y, score the per-lap
    distributions against official classifications. Two views:

      lap-view   — every (lap, driver) prediction of a runner is scored
                   (the curve's own contract: at every lap, the
                   distribution is honest about what happens next)
      final-view — the lap-1 distribution (pre-race, from the grid)
                   scored once per driver-race, directly comparable to
                   the Phase-3 backtest's numbers.
    """
    laps = _load_laps(db_path)
    entries = _load_entries_full(db_path)
    rows_final = []
    rows_lap = []
    slow_all = _slow_lap_set(laps)
    for y in years:
        hist = laps[laps["year"] < y]
        if hist.empty:
            continue
        entries_hist = entries[entries["year"] < y]
        hist_slow = {k for k in slow_all if k[0] < y}
        rem_swing = fit_remaining_swing(hist, entries_hist,
                                        slow_laps=hist_slow)
        fail = fit_remaining_fail_rate(hist, entries_hist)
        season_laps = laps[laps["year"] == y]
        for rnd in sorted(season_laps["round"].unique().tolist()):
            lr = season_laps[season_laps["round"] == rnd]
            actual = entries[(entries["year"] == y)
                             & (entries["round"] == rnd)][
                ["driverId", "position", "is_dnf"]]
            sc_laps = {lap for (yy, rr, lap) in slow_all
                       if yy == y and rr == rnd}
            rng = np.random.default_rng(seed + y * 100 + rnd + SEED_OFFSET)
            replay = replay_race(lr, actual, rem_swing, fail, n_sims, rng,
                                 sc_laps=sc_laps)
            if replay.empty:
                continue
            replay = replay.merge(actual.rename(columns={
                "position": "actual_position", "is_dnf": "actual_dnf"}),
                on="driverId", how="left")
            replay["actual"] = replay["actual_position"].map(actual_bucket)
            replay["year"], replay["round"] = y, rnd
            rows_lap.append(replay)
            rows_final.append(replay[replay["lap"] == 1])

    lap_view = pd.concat(rows_lap, ignore_index=True) if rows_lap \
        else pd.DataFrame()
    final_view = pd.concat(rows_final, ignore_index=True) if rows_final \
        else pd.DataFrame()
    metrics = {}
    if not lap_view.empty:
        metrics["lap_log_loss"] = rs.bucket_log_loss(lap_view)
        metrics["lap_brier"] = rs.bucket_brier(lap_view)
    if not final_view.empty:
        metrics["final_log_loss"] = rs.bucket_log_loss(final_view)
        metrics["final_brier"] = rs.bucket_brier(final_view)
        metrics["final_n"] = int(len(final_view))
    return lap_view, metrics


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Lap-by-lap probability evolution curves")
    ap.add_argument("--db", default="datasets/f1_canonical.db")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--sims", type=int, default=400)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="datasets/lap_curves.json")
    ap.add_argument("--race", nargs=2, type=int, metavar=("YEAR", "ROUND"),
                    help="print one race's curves as a table")
    ap.add_argument("--backtest", nargs=2, type=int, metavar=("FROM", "TO"),
                    help="walk-forward replay calibration over seasons")
    args = ap.parse_args()

    if args.race:
        yr, rnd = args.race
        laps = _load_laps(args.db)
        entries = _load_entries_full(args.db)
        lr = laps[(laps["year"] == yr) & (laps["round"] == rnd)]
        if lr.empty:
            raise SystemExit(f"no lap data for {yr} r{rnd}")
        actual = entries[(entries["year"] == yr)
                         & (entries["round"] == rnd)][
            ["driverId", "position", "is_dnf"]]
        hist = laps[laps["year"] < yr]
        entries_hist = entries[entries["year"] < yr]
        rem_swing = fit_remaining_swing(hist, entries_hist,
                                        slow_laps=_slow_lap_set(laps))
        fail = fit_remaining_fail_rate(hist, entries_hist)
        rng = np.random.default_rng(args.seed + yr * 100 + rnd
                                    + SEED_OFFSET)
        replay = replay_race(lr, actual, rem_swing, fail, args.sims, rng)
        piv = replay.pivot_table(index="lap", columns="driverId",
                                 values="p_podium")
        show = [c for c in piv.columns][:8]
        print(f"\n{yr} round {rnd}: P(podium) evolution "
              f"(first 8 drivers alphabetically; {args.sims} sims)")
        head = f"{'lap':>4s} " + " ".join(f"{c[:9]:>9s}" for c in show)
        print(head)
        for lap in piv.index:
            print(f"{lap:4d} " + " ".join(
                f"{piv.loc[lap, c]:9.3f}" for c in show))
        return

    if args.backtest:
        lo, hi = args.backtest
        _, metrics = replay_backtest(args.db, range(lo, hi + 1),
                                     args.sims, args.seed)
        print(f"\n=== Lap-curve walk-forward backtest {lo}-{hi} "
              f"({args.sims} sims/race-lap) ===")
        print(f"  lap view   (every lap, every runner): "
              f"LL {metrics['lap_log_loss']:.4f}  "
              f"Brier {metrics['lap_brier']:.4f}")
        print(f"  final view (lap 1 = pre-race, n={metrics['final_n']}): "
              f"LL {metrics['final_log_loss']:.4f}  "
              f"Brier {metrics['final_brier']:.4f}")
        print("  (final view comparable to race_simulator's 0.746 LL at "
              "2000 sims; fewer sims here widens it slightly)")
        return

    doc = build_curves(args.db, args.season, args.sims, args.seed)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    n_dr = sum(len(r["drivers"]) for r in doc["races"])
    print(f"lap_curves.json: {len(doc['races'])} races, {n_dr} driver "
          f"curves, season {args.season} ({args.sims} sims/lap) "
          f"-> {args.out}")


if __name__ == "__main__":
    main()
