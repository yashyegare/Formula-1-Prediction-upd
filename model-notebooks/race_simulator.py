"""
race_simulator.py — the race scenario model (Phase 3).

Monte Carlo simulation of race outcomes from pre-race information only.
This is the plan's Layer 2: instead of a classifier's point prediction,
it produces a PROBABILITY DISTRIBUTION over outcomes per driver, from two
empirically fitted mechanisms:

  1. Race-day swing   — each finisher's finishing position = grid slot +
     delta, delta ~ Normal(swing_mean, swing_sd). The swing distribution is
     the grid->finish delta of FINISHED entries; fitted point-in-time from
     seasons strictly before the target race. The UNCONDITIONAL swing
     already embeds historical SC/strategy/rhythm effects (they happened
     inside those deltas), so the base model is honest without explicit
     scenario machinery — deliberately, per ERROR_DECOMPOSITION.md (SC
     exposure does not concentrate error; ordinary swing variance does).

  2. Attrition        — each entry DNFs with rate p (fitted point-in-time).
     DNFs are mutually exclusive across drivers, so the number of
     finishers is Binomial(N, 1-p). Classification follows the real
     contract (verified in the canonical DB: every classified entry has
     position >= 1): finishers take P1..n_finishers ordered by their
     simulated key (grid + delta); classified DNFs take the remaining
     positions in random order. Under heavy attrition (n_finishers < 10)
     classified DNFs can land in points — as they do in real races.

The value over the deterministic quali-bucket baseline is the
DISTRIBUTION: P(podium), P(points), P(out), expected position per driver.
The claim this module makes is therefore CALIBRATION, not higher point
accuracy — `backtest` measures reliability of the predicted probabilities
against actual outcomes, walk-forward (fit on seasons <= Y-1, simulate Y).

Determinism: every entry point takes an explicit seed; same seed => same
output distributions, byte-for-byte.

Usage:
    python race_simulator.py --db datasets/f1_canonical.db --year 2026
    python race_simulator.py --db datasets/f1_canonical.db --race 2026 9
    python race_simulator.py --db datasets/f1_canonical.db --backtest 2019 2026
"""
import argparse
import sqlite3

import numpy as np
import pandas as pd

# Bucket boundaries (mirror of train_model.position_index)
PODIUM_MAX = 3
POINTS_MAX = 10

GLOBAL_RATE_FALLBACK = {"mean": 0.99, "sd": 4.11, "dnf_rate": 0.153}


def position_bucket(pos: float) -> int:
    if pos < PODIUM_MAX + 1:
        return 1
    if pos > POINTS_MAX:
        return 3
    return 2


# ── fitting ───────────────────────────────────────────────────────────────

def fit_swing_params(entries: pd.DataFrame) -> dict:
    """
    Point-in-time mechanism parameters from FINISHED entries:
    mean/sd of the grid->finish swing, and the per-entry DNF rate.

    `entries` needs columns: grid, position, is_dnf. Rows with position<1
    (unclassified) or grid<1 (pit-lane starts, clamped to field size
    per race before fitting) are excluded from the swing sample — the
    same treatment the simulator applies at run time.
    """
    d = entries.copy()
    field = d.groupby(["year", "round"])["driverId"].transform("count")
    d["grid_clamped"] = d["grid"].clip(lower=1).clip(upper=field)
    finished = d[(d["is_dnf"] == 0) & (d["position"] >= 1)
                 & (d["grid"] >= 1)]
    swing = finished["grid_clamped"] - finished["position"]
    if len(swing) < 30:
        return dict(GLOBAL_RATE_FALLBACK)
    return {
        "mean": float(swing.mean()),
        "sd": float(swing.std(ddof=1)),
        "dnf_rate": float(d["is_dnf"].mean()),
    }


def fit_driver_sd(entries: pd.DataFrame, window: int = 10,
                  min_races: int = 5, sd_floor: float = 2.0,
                  sd_cap: float = 8.0) -> dict[str, float]:
    """
    v2 pace-noise: per-driver swing VOLATILITY (sd of the grid->finish
    delta over the driver's last `window` finished races, strictly before
    the target race). A driver who finishes where they qualify every week
    gets a small sd (metronome); a streaky one gets a large sd. This is
    the pace-noise mechanism the reliability curve asked for: the sim v1
    overrated mid-grid cars because everyone shared one swing sd.

    Returns {driverId: sd} with values clamped to [sd_floor, sd_cap] —
    floors/caps keep a 3-race sample from producing a near-deterministic
    or wildly heavy-tailed swing. Drivers with fewer than `min_races`
    finished races are absent from the dict (they fall back to the pooled
    sd at simulation time).

    `entries` needs: year, round, driverId, grid, position, is_dnf, and
    must be pre-filtered to seasons <= Y-1 (the caller's point-in-time
    contract); the last `window` finished races per driver are used.
    """
    d = entries.copy()
    field = d.groupby(["year", "round"])["driverId"].transform("count")
    d["grid_clamped"] = d["grid"].clip(lower=1).clip(upper=field)
    finished = d[(d["is_dnf"] == 0) & (d["position"] >= 1)
                 & (d["grid"] >= 1)].copy()
    finished["swing"] = finished["grid_clamped"] - finished["position"]
    finished = finished.sort_values(["driverId", "year", "round"])
    last = (finished.groupby("driverId", sort=False)
            .tail(window)
            .groupby("driverId")["swing"])
    n = last.size()
    sd = last.std(ddof=1)
    return {drv: float(np.clip(s, sd_floor, sd_cap))
            for drv, s, k in zip(sd.index, sd.values, n.values)
            if k >= min_races and np.isfinite(s)}


# ── simulation ────────────────────────────────────────────────────────────

def simulate_race(grid: list[tuple[str, int]], n_sims: int,
                  swing_mean: float, swing_sd: float, dnf_rate: float,
                  rng: np.random.Generator,
                  driver_sd: dict[str, float] | None = None) -> pd.DataFrame:
    """
    Simulate one race `n_sims` times.

    `grid`: (driverId, grid_slot) pairs, grid_slot the pre-race slot
    (1-based; 0 = pit-lane start, clamped to the back).

    `driver_sd`: optional per-driver swing-sd overrides (v2 pace-noise).
    A driver with a volatile recent-race delta history (sd 6) swings more
    than a metronome (sd 2); drivers absent from the dict fall back to the
    fitted pooled swing_sd. The pool mean stays shared: this models HOW
    FAR each driver's race day departs from their grid slot, not where
    they end up on average — that is the grid's job.

    Returns a long frame: one row per (sim, driver) with the simulated
    classification `position` and `is_dnf`. Each sim is a valid
    classification: positions 1..N used exactly once.
    """
    n = len(grid)
    drivers = [d for d, _ in grid]
    slots = np.array([g for _, g in grid], dtype=float)
    # Pit-lane starts (grid 0 or negative) go to the BACK of the grid —
    # real F1 semantics. A naive lower-clip to 1 would put them on pole.
    slots = np.where(slots <= 0, float(n), np.clip(slots, 1.0, float(n)))

    # per-driver swing sd (v2): pooled sd as the fallback
    if driver_sd:
        sds = np.array([driver_sd.get(d, swing_sd) for d in drivers])
    else:
        sds = np.full(n, swing_sd)

    # how many retire per sim
    n_dnf = rng.binomial(n, dnf_rate, size=n_sims)
    # who retires: without replacement, per sim
    order = np.argsort(rng.random((n_sims, n)), axis=1)  # random permutations
    dnf_mask = np.zeros((n_sims, n), dtype=bool)
    for s in range(n_sims):
        dnf_mask[s, order[s, :n_dnf[s]]] = True

    # swing deltas for everyone (DNF rows' deltas are ignored below);
    # per-driver sd via the scale trick: z ~ N(0,1) scaled per column
    z = rng.normal(size=(n_sims, n))
    delta = swing_mean + z * sds[None, :]
    key = slots[None, :] + delta
    # tiny jitter so exact ties (identical slots + deltas) can't collide
    key += rng.random((n_sims, n)) * 1e-9

    positions = np.empty((n_sims, n), dtype=int)
    for s in range(n_sims):
        fin = np.where(~dnf_mask[s])[0]
        dnf = np.where(dnf_mask[s])[0]
        fin_sorted = fin[np.argsort(key[s, fin], kind="stable")]
        positions[s, fin_sorted] = np.arange(1, len(fin) + 1)
        dnf_slots = np.arange(len(fin) + 1, n + 1)
        positions[s, dnf] = dnf_slots[rng.permutation(len(dnf))] \
            if len(dnf) else np.empty(0, dtype=int)

    rows = []
    for j, drv in enumerate(drivers):
        rows.append(pd.DataFrame({
            "driverId": drv,
            "sim": np.arange(n_sims),
            "position": positions[:, j],
            "is_dnf": dnf_mask[:, j].astype(int),
        }))
    return pd.concat(rows, ignore_index=True)


def summarize_simulation(sim: pd.DataFrame) -> pd.DataFrame:
    """Per-driver distribution summary from simulate_race output."""
    out = (sim.assign(bucket=sim["position"].map(position_bucket))
           .groupby("driverId")
           .agg(p_podium=("bucket", lambda b: (b == 1).mean()),
                p_points=("bucket", lambda b: (b == 2).mean()),
                p_out=("bucket", lambda b: (b == 3).mean()),
                expected_position=("position", "mean"),
                dnf_rate_sim=("is_dnf", "mean"))
           .reset_index())
    return out


# ── probabilistic scoring ─────────────────────────────────────────────────

def bucket_log_loss(probs: pd.DataFrame, suffix: str = "") -> float:
    """
    Mean log loss over driver rows. `probs` carries p_podium/p_points/p_out
    (optionally suffixed, e.g. suffix='_gr' for the global-rates baseline)
    plus the actual bucket column. One unified smoothed floor avoids
    infinite loss on confident-wrong rows; the floor is applied
    identically to every method compared.
    """
    p = probs[[f"p_podium{suffix}", f"p_points{suffix}",
               f"p_out{suffix}"]].to_numpy()
    p = np.clip(p, 1e-6, 1.0)
    p = p / p.sum(axis=1, keepdims=True)
    actual = probs["actual"].to_numpy() - 1  # 0/1/2 index
    return float(-np.log(p[np.arange(len(p)), actual]).mean())


def bucket_brier(probs: pd.DataFrame, suffix: str = "") -> float:
    """Multi-class Brier score (mean squared error of the full vector)."""
    p = probs[[f"p_podium{suffix}", f"p_points{suffix}",
               f"p_out{suffix}"]].to_numpy()
    actual = probs["actual"].to_numpy() - 1
    onehot = np.eye(3)[actual]
    return float(((p - onehot) ** 2).sum(axis=1).mean())


def reliability_curve(probs: pd.DataFrame, prob_col: str,
                      n_bins: int = 5) -> pd.DataFrame:
    """
    Reliability (calibration) table for one predicted-probability column:
    predicted mean vs realized frequency per prediction-strength bin.
    A calibrated model tracks the diagonal.
    """
    event_col = {"p_podium": "actual_podium", "p_points": "actual_points",
                 "p_out": "actual_out"}[prob_col]
    q = pd.qcut(probs[prob_col], q=n_bins, duplicates="drop")
    g = pd.DataFrame({
        "predicted": probs.groupby(q, observed=True)[prob_col].mean(),
        "realized": probs.groupby(q, observed=True)[event_col].mean(),
        "n": probs.groupby(q, observed=True)[prob_col].size(),
    })
    return g.reset_index(drop=True)


# ── walk-forward backtest ─────────────────────────────────────────────────

def load_entries(db_path: str) -> pd.DataFrame:
    con = sqlite3.connect(db_path)
    try:
        return pd.read_sql("""
            SELECT year, round, driverId, constructorId, grid, position,
                   is_dnf
            FROM fact_race_entry ORDER BY year, round, grid, driverId
        """, con)
    finally:
        con.close()


def backtest(entries: pd.DataFrame, years: range, n_sims: int,
             seed: int, driver_sd: bool = False) -> tuple[pd.DataFrame, dict]:
    """
    Walk-forward probabilistic backtest: for each season Y, fit the
    mechanisms on seasons <= Y-1, simulate every race of Y, score the
    predicted distributions against actual buckets. Also scores two
    baselines on the same rows with the same smoothing:

      global-rates  — the training seasons' pooled bucket frequencies
                      (the no-skill probabilistic baseline)
      grid-onehot   — bucket(grid) with the same smoothing floor
                      (the deterministic baseline as a probability)

    driver_sd=True enables the v2 pace-noise mechanism: per-driver swing
    volatility fitted on the same strictly-prior seasons (identical seeds
    per race, so the v1/v2 comparison differs ONLY through the mechanism,
    not through sampling noise — the ablation is paired).
    """
    rows = []
    for y in years:
        train = entries[entries["year"] <= y - 1]
        test = entries[entries["year"] == y]
        if len(train) == 0 or len(test) == 0:
            continue
        params = fit_swing_params(train)
        dsd = fit_driver_sd(train) if driver_sd else None
        train_buckets = train["position"].map(position_bucket)
        global_rates = [float((train_buckets == 1).mean()),
                        float((train_buckets == 2).mean()),
                        float((train_buckets == 3).mean())]

        for (yr, rnd), race in test.groupby(["year", "round"]):
            rng = np.random.default_rng(seed + yr * 100 + rnd)
            grid = list(zip(race["driverId"],
                            race["grid"].fillna(0).astype(int)))
            sim = simulate_race(grid, n_sims, params["mean"], params["sd"],
                                params["dnf_rate"], rng, driver_sd=dsd)
            summ = summarize_simulation(sim)
            summ = summ.merge(
                race[["driverId", "position", "grid"]].assign(
                    actual=lambda d: d["position"].map(position_bucket)),
                on="driverId", how="left")
            summ["year"], summ["round"] = yr, rnd
            rows.append(summ)
    probs = pd.concat(rows, ignore_index=True)
    probs["actual_podium"] = (probs["actual"] == 1).astype(float)
    probs["actual_points"] = (probs["actual"] == 2).astype(float)
    probs["actual_out"] = (probs["actual"] == 3).astype(float)

    metrics = {
        "sim_log_loss": bucket_log_loss(probs),
        "sim_brier": bucket_brier(probs),
    }

    # Baseline 1, global-rates: the training seasons' pooled bucket
    # frequencies as a constant vector (the no-skill probabilistic floor
    # any per-driver distribution must beat).
    for col, rate in zip(("p_podium_gr", "p_points_gr", "p_out_gr"),
                         global_rates):
        probs[col] = rate
    metrics["global_rates_log_loss"] = bucket_log_loss(probs, suffix="_gr")
    metrics["global_rates_brier"] = bucket_brier(probs, suffix="_gr")

    # Baseline 2, grid-onehot: bucket(grid) as a smoothed one-hot vector —
    # the deterministic baseline expressed as probabilities. Smoothing
    # floor identical to the sim's so the comparison is apples-to-apples.
    eps = 1e-6
    grid_probs = np.zeros((len(probs), 3)) + eps
    # pit-lane / missing grid slots (<=0) are back-of-grid -> bucket 3
    g = probs["grid"].where(probs["grid"] >= 1, 99.0)
    gb = g.map(position_bucket).to_numpy() - 1
    grid_probs[np.arange(len(probs)), gb] = 1.0
    grid_probs /= grid_probs.sum(axis=1, keepdims=True)
    probs["p_podium_oh"], probs["p_points_oh"], probs["p_out_oh"] = grid_probs.T
    metrics["grid_onehot_log_loss"] = bucket_log_loss(probs, suffix="_oh")
    metrics["grid_onehot_brier"] = bucket_brier(probs, suffix="_oh")
    return probs, metrics


def main():
    ap = argparse.ArgumentParser(description="Race scenario simulator")
    ap.add_argument("--db", default="datasets/f1_canonical.db")
    ap.add_argument("--sims", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--year", type=int, default=None,
                    help="simulate every race of this season (fit <= Y-1)")
    ap.add_argument("--race", nargs=2, type=int, metavar=("YEAR", "ROUND"),
                    help="detailed distribution table for one race")
    ap.add_argument("--backtest", nargs=2, type=int, metavar=("FROM", "TO"),
                    help="walk-forward calibration backtest over seasons")
    ap.add_argument("--ablation", nargs=2, type=int, metavar=("FROM", "TO"),
                    help="paired v1 (pooled sd) vs v2 (per-driver sd) backtest")
    args = ap.parse_args()

    entries = load_entries(args.db)

    if args.race:
        yr, rnd = args.race
        train = entries[entries["year"] <= yr - 1]
        params = fit_swing_params(train)
        race = entries[(entries["year"] == yr) & (entries["round"] == rnd)]
        rng = np.random.default_rng(args.seed)
        sim = simulate_race(list(zip(race["driverId"],
                                     race["grid"].fillna(0).astype(int))),
                            args.sims, params["mean"], params["sd"],
                            params["dnf_rate"], rng)
        summ = summarize_simulation(sim).merge(
            race[["driverId", "position"]], on="driverId", how="left")
        summ = summ.sort_values(["p_podium", "expected_position"],
                                ascending=[False, True])
        print(f"\n{yr} round {rnd} — {args.sims} sims "
              f"(swing {params['mean']:+.2f}±{params['sd']:.2f}, "
              f"DNF {params['dnf_rate']:.1%}, fit <= {yr - 1})")
        print(f"{'driver':20s} {'P(pod)':>7s} {'P(pts)':>7s} {'P(out)':>7s} "
              f"{'E[pos]':>7s} {'actual':>6s}")
        for _, r in summ.iterrows():
            print(f"{r['driverId']:20s} {r['p_podium']:7.1%} {r['p_points']:7.1%} "
                  f"{r['p_out']:7.1%} {r['expected_position']:7.1f} "
                  f"{r['position']:6.0f}")
        return

    if args.year:
        train = entries[entries["year"] <= args.year - 1]
        test = entries[entries["year"] == args.year]
        params = fit_swing_params(train)
        rng = np.random.default_rng(args.seed)
        accs, base_accs = [], []
        for (yr, rnd), race in test.groupby(["year", "round"]):
            sim = simulate_race(list(zip(race["driverId"],
                                         race["grid"].fillna(0).astype(int))),
                                args.sims, params["mean"], params["sd"],
                                params["dnf_rate"], rng)
            summ = summarize_simulation(sim).merge(
                race[["driverId", "position", "grid"]], on="driverId")
            pred_bucket = summ[["p_podium", "p_points", "p_out"]].idxmax(axis=1).map(
                {"p_podium": 1, "p_points": 2, "p_out": 3})
            accs.append((pred_bucket == summ["position"].map(position_bucket)).mean())
            base_accs.append((race["grid"].where(race["grid"] >= 1, 99.0)
                              .map(position_bucket)
                              == race["position"].map(position_bucket)).mean())
        print(f"\n{args.year}: sim MAP accuracy {np.mean(accs):.1%} vs "
              f"quali-bucket baseline {np.mean(base_accs):.1%} "
              f"(swing {params['mean']:+.2f}±{params['sd']:.2f}, "
              f"DNF {params['dnf_rate']:.1%})")
        print("The sim's value is the distribution, not MAP accuracy — "
              "run --backtest for the calibration claim.")
        return

    if args.backtest:
        lo, hi = args.backtest
        probs, metrics = backtest(entries, range(lo, hi + 1), args.sims,
                                  args.seed)
        print(f"\n=== Walk-forward probabilistic backtest {lo}-{hi} "
              f"({len(probs)} driver-races, {args.sims} sims) ===")
        print(f"{'method':28s} {'log loss':>9s} {'Brier':>8s}")
        for label, ll_key, br_key in (
                ("simulated distributions", "sim_log_loss", "sim_brier"),
                ("global-rates baseline", "global_rates_log_loss",
                 "global_rates_brier"),
                ("grid-onehot baseline", "grid_onehot_log_loss",
                 "grid_onehot_brier")):
            print(f"{label:28s} {metrics[ll_key]:9.4f} {metrics[br_key]:8.4f}")
        print(f"\nReliability of P(podium) (predicted vs realized):")
        curve = reliability_curve(probs, "p_podium")
        for _, r in curve.iterrows():
            print(f"  n={int(r['n']):4d}  predicted {r['predicted']:6.1%}  "
                  f"realized {r['realized']:6.1%}")
        probs.to_csv("sim_probs_backtest.csv", index=False,
                     lineterminator="\n")
        print("\nPer-driver probabilities written to sim_probs_backtest.csv")
        return

    if args.ablation:
        lo, hi = args.ablation
        # PAIRED ablation: identical seeds per race, so any metric delta
        # comes from the driver-sd mechanism, not sampling noise.
        probs1, m1 = backtest(entries, range(lo, hi + 1), args.sims,
                              args.seed, driver_sd=False)
        probs2, m2 = backtest(entries, range(lo, hi + 1), args.sims,
                              args.seed, driver_sd=True)
        print(f"\n=== Paired ablation: swing-sd v1 vs per-driver pace-noise v2 "
              f"({lo}-{hi}, {len(probs1)} driver-races, {args.sims} sims) ===")
        print(f"{'method':34s} {'log loss':>9s} {'Brier':>8s}")
        print(f"{'v1 pooled swing sd':34s} {m1['sim_log_loss']:9.4f} "
              f"{m1['sim_brier']:8.4f}")
        print(f"{'v2 per-driver pace-noise sd':34s} {m2['sim_log_loss']:9.4f} "
              f"{m2['sim_brier']:8.4f}")
        dll = m2["sim_log_loss"] - m1["sim_log_loss"]
        dbr = m2["sim_brier"] - m1["sim_brier"]
        print(f"{'v2 - v1':34s} {dll:+9.4f} {dbr:+8.4f}")
        print("\nReliability of P(podium), v2:")
        for _, r in reliability_curve(probs2, "p_podium").iterrows():
            print(f"  n={int(r['n']):4d}  predicted {r['predicted']:6.1%}  "
                  f"realized {r['realized']:6.1%}")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
