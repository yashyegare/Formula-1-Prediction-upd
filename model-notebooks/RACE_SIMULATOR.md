# Race scenario simulator (Phase 3)

The plan's Layer 2: instead of a classifier's point prediction, a Monte
Carlo engine that produces a **probability distribution over outcomes per
driver** from pre-race information only. Built on the canonical DB
(Phase 2); informed by the error decomposition (Phase 1).

```
grid (pre-race) ──┐
                  ├─▶ Monte Carlo (swing + attrition) ──▶ P(podium/points/out)
swing/DNF fits ───┘         per driver, per race            + E[position]
```

## Design rationale

- **Two mechanisms, both fitted point-in-time** (seasons ≤ Y-1) from the
  canonical DB: the race-day swing (grid→finish delta of FINISHED entries,
  ~Normal(+1.0, 4.1) pooled over 2018–2026, stable across seasons) and
  attrition (per-entry DNF, 15.3% pooled, 11–21% by year).
- **The unconditional swing already embeds SC/strategy effects** — they
  happened inside those deltas. This is deliberate, per
  ERROR_DECOMPOSITION.md: SC exposure does not concentrate prediction
  error (1.08x lift), ordinary swing variance does. No scenario exotica.
- **This is where the rejected lap-pace feature lives on.** MODEL_NOTES #9
  rejected `lap_pace_delta_s` as a PRE-race classifier feature (regressive,
  4/4 seeds) — but lap data as post-race/PROBABILISTIC fuel is exactly
  what a simulator consumes. The swing distribution is the honest v1;
  per-driver pace-noise sd (from `fact_lap`) is the natural v2 knob.
- **Classification follows the real contract** (verified in the canonical
  DB: every classified entry has position ≥ 1): finishers take P1..n in
  key order, classified DNFs fill the remaining slots in random order.
  Under heavy attrition classified DNFs land in points, as in reality.
- **Determinism**: explicit seed everywhere; same seed → identical
  distributions byte-for-byte (pinned by test).

## Calibration results (the claim this module makes)

Walk-forward, fit ≤ Y-1, simulate Y, 2019–2026, 3,280 driver-races,
2,000 sims/race:

| method | log loss | Brier |
|---|---:|---:|
| **simulated distributions** | **0.746** | **0.436** |
| global-rates baseline | 0.997 | 0.604 |
| grid-onehot baseline | 4.221 | 0.611 |

The simulation decisively beats the no-skill floor and the deterministic
baseline-as-probability (a one-hot prediction is catastrophic under log
loss — the quantified argument for distributions over point predictions).

Reliability of P(podium): tracks the diagonal where predictions are
confident (predicted 50.8% → realized 60.4%; 19.5% → 9.5%), conservative
at the low end (predicted ~0 → realized ~1.3%) — the swing model can't see
a backmarker's podium, which is honest. The mid-bin under-realization
(19.5% → 9.5%) is the known gap: grid slot alone overrates mid-grid cars
whose race pace differs; the v2 pace feature targets exactly this bin.

MAP accuracy (not the headline): 2026 sim 68.2% vs quali-bucket 67.8% —
the point-prediction value is marginal BY DESIGN; the distribution is the
product.

## Usage

```bash
python race_simulator.py --db datasets/f1_canonical.db --race 2026 9 --sims 3000
python race_simulator.py --db datasets/f1_canonical.db --year 2026
python race_simulator.py --db datasets/f1_canonical.db --backtest 2019 2026
```

`--race` prints the full per-driver distribution table; `--backtest`
writes `sim_probs_backtest.csv` (per driver-race probabilities + actuals)
for further analysis.

## What was fixed while building it

The pit-lane clamp test caught a real bug: `np.clip(grid, 1, n)` sent
grid-0 (pit-lane) starters to the FRONT row instead of the back — the
naive lower-clip inverts F1 semantics. Fixed with an explicit `where`
(≤0 → back of grid); the same clamping was corrected in the grid-onehot
baseline and the MAP baseline. 45 real backtest rows had grid=0.

## Test coverage (20 tests)

Determinism, per-sim permutation validity, DNF slotting, degenerate-order
reproduction of grid order, pit-lane clamping, heavy-attrition points for
classified DNFs, distribution shape (front-runner dominance, probability
sums, position bounds), fitting (zero-swing exactness, pit-lane exclusion,
<30-sample fallback constants), scoring math (uniform LL = ln 3, uniform
Brier = 2/3, confident-correct vs confident-wrong, suffix selection), and
reliability tracking a perfectly calibrated synthetic set.
