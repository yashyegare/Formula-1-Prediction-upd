# Race intelligence serving layer (Phase 4)

The consumption layer for everything Phases 1–3 built: a **pre-computed
race-intel artifact**, the **lap-by-lap replay curves**, a **Flask
blueprint** that serves both, and a **Next.js dashboard** that renders
them.

```
f1_canonical.db ──▶ race_intelligence.py ──▶ datasets/race_intel.json
(Phase 2)           (Phase 3 simulator +           │
                     Phase 1 attribution)          ▼
        └──▶ lap_curves.py ──▶ datasets/lap_curves.json
             (lap-by-lap replay)               │
                                               ▼
                                flask-app/race_intelligence_api.py
                                (blueprint, registered in app.py)
                                           │
                                           ▼
                                nextjs-app/src/pages/race-intel.tsx
```

The intelligence is generated **offline and deterministically**; the API
only reads the files. No numpy/sklearn in the serving path, and the JSON
itself is reviewable in a diff before it ships.

A **scheduled refresh** (`.github/workflows/refresh.yml`) keeps the
whole chain current: fetch latest Jolpica data → rebuild the canonical
DB and both artifacts → commit the diff → push (which redeploys the
backend on main). Quiet nights commit nothing; every refresh is
verified against the artifact contracts and the full ML test suite
before it ships.

## The artifact (`datasets/race_intel.json`, schema v2)

One document per season, rebuilt by:

```bash
python race_intelligence.py --season 2026 --sims 2000
```

Contents:

- **`mechanism`** — the fitted swing/dnf parameters (≤ previous season,
  the walk-forward discipline).
- **`races[]`** — every round of the season, each with a `status`:
  - `"raced"` — per driver: the simulated outcome distribution
    (`p_podium` / `p_points` / `p_out`), `expected_position`, simulated
    DNF rate, and the derived grid-swing insight — `observed_swing`
    (real grid→finish shift) against `sim_swing_mean` (what the
    mechanism expected). The "why it landed there" view.
  - `"upcoming_post_quali"` — quali has run, the race hasn't: the same
    distributions simulated from the **real qualifying grid**. The
    pre-race prediction view; swing fields are omitted.
  - `"scheduled"` — no quali yet: distributions from a grid ordered by
    **current championship standing** (drivers ranked by points; ties
    deterministic). Still a genuine point-in-time prediction — the
    mechanism is fitted on strictly-prior seasons either way.
- **`next_round`** — the first non-raced round (`null` when the season
  is complete).
- **`season_attribution`** — the Phase-1 miss taxonomy for the season's
  baseline record (2026: accuracy 68.6%, under-predict 53.3%,
  dnf_other 25.3%).

Every race entry also carries `name`/`date` (from the canonical
`fact_race`) and per-driver display fields (`driverCode`, `surname`,
`constructorId`).

Two builds with the same seed are **byte-identical** (verified by test);
seed = `42 + year*100 + round` per race, so adding rounds never
reshuffles existing ones.

## The lap curves (`datasets/lap_curves.json`, schema v1)

The same simulator rerun at every sampled lap of each RACED race,
conditioned on the running order as it actually stood (from
`fact_lap`): the per-lap evolution of every driver's P(podium) /
P(points) / P(out) — how the race happened, per lap.

The mechanism is the Phase-3 machinery unchanged; only the parameters
re-fit **point-in-time**, per remaining-fraction bucket (10 buckets,
1 = race just started, 0 = chequered flag):

- **Remaining swing** — `position at lap t − official final position`
of finished entries from prior seasons in the same bucket. As the
fraction shrinks, the sd collapses (4.48 → 1.33 places fitted on
2018–2025) — positions lock in as laps run out.
- **Remaining attrition** — P(a runner at that stage ends unclassified),
from the official classification (NOT chart presence — a 90%-rule
finisher who parks early is not a failure). Falls 12% → 0.7% across
the buckets.
- **SC handling** — safety-car/VSC laps (the Phase-1 field-median
detector) are excluded from the historical swing sample, and live
attrition is frozen while an SC runs (cars are not retiring under SC).
- **Truth contract** — curves are scored against the OFFICIAL
classification, not the terminal lap-chart position (~22% differ:
penalties, classified retirements, lapped order).
- **Locked outcomes** — ~32% of classified finishers leave the lap
chart early (90% rule). Once off the chart a car's race is determined,
so the curve extends with the locked outcome (retired → P(out)=1;
classified → bucket of the last charted position) instead of freezing.

Calibration (walk-forward 2024–2026, 50 sims/lap): lap view log loss
**0.547** / Brier 0.309; final view (lap-1 distributions, n=1163)
**0.695** / 0.405 — better than the pre-race artifact's 0.746, i.e.
conditioning on the lap-1 running order (launch included) genuinely
sharpens the prediction. A final-lap point is not forced to a vertex:
post-race penalty adjudication is genuinely unresolved at the flag, so
the residual is honest.

Each race doc carries `n_laps`, `sample_laps` (≤ 12 uniformly spaced,
always bracketing lap 1 and the flag), per-driver `final_position` and
`curve` rows `[lap, p_podium, p_points, p_out, expected_position]`.
Seed = `42 + year*100 + round + 1_000_000` — a disjoint stream from
race-intel, and byte-deterministic (verified by test).

```bash
python lap_curves.py --season 2026 --sims 400
python lap_curves.py --race 2026 1     # per-lap P(podium) table
python lap_curves.py --backtest 2019 2026  # walk-forward calibration
```

## The API (`flask-app/race_intelligence_api.py`)

A blueprint (`race_intel_bp`) registered by `app.py` alongside auth and
predictions — one process serves everything:

| Endpoint | Returns |
|---|---|
| `GET /api/race-intel/season/<year>` | full season document |
| `GET /api/race-intel/races/<year>` | light index (no per-driver arrays) |
| `GET /api/race-intel/race/<year>/<round>` | one race's driver array |
| `GET /api/race-intel/drivers/<year>/<round>` | `driverId` + 3 probabilities only |
| `GET /api/race-intel/next/<year>` | the `next_round` race doc — the pre-race view |
| `GET /api/race-intel/curves/<year>/<round>` | lap-by-lap probability evolution (raced rounds) |

Failure semantics are explicit, never silently empty: unknown
season/round → **JSON 404** with an error body; missing/unreadable
artifact → **503** telling you to run the generator (each artifact —
race-intel and lap-curves — fails independently; a missing curves file
does not take the main routes down). Files are cached by mtime, so a
rebuilt artifact is served without a process restart (pinned by test).

## The dashboard (`nextjs-app/src/pages/race-intel.tsx`)

One page, three views driven by the same data:

- **Race selector** — a pill per round with a status dot (green = raced,
  amber = pre-race prediction), landing on `next_round` by default.
- **Driver table** — sorted by expected position: grid, E[Pos], and
  podium/points/out probability bars. On raced rounds an extra **Swing**
  column shows `observed_swing (exp sim_swing_mean)` — green for
  race-day gainers, red for losers — the Phase-1 insight rendered.
- **Race replay** (raced rounds) — the lap-by-lap probability-evolution
  chart from `/curves`, switchable between P(podium)/P(points)/P(out);
  hovering a driver row highlights their line. The visual answer to
  "how did the race happen".
- **Attribution footer** — the season's miss taxonomy and mechanism
  parameters.

Errors surface the API's explicit bodies (the 503 "generate the
artifact" message) instead of blank tables.

## Test coverage

model-notebooks (19): artifact schema v2 and round ordering, probability
sums ≈ 1 and bounds, byte-level determinism, future-grid determinism
(championship leader holds slot 1), attribution equal to `summarize()`,
mechanism equal to a direct `fit_swing_params` call, raced AND future
rounds equal direct `simulate_race` calls at the same seed (the artifact
is a faithful materialization of the simulator, not a re-implementation),
and the API: response shapes, the drivers projection, the light index,
the next endpoint (including 404 when the season is complete), 404s,
503-without-artifact, curves shapes/404s/503 independence and hot-reload
on rebuild.

lap curves (14): bucket backfill direction (an empty bucket inherits the
TIGHTest neighbour, never widens), the official-classification truth
contract for both fits (chart-terminal truth is degenerate), replay
convergence, retired drivers stop appearing, SC freezes live attrition,
artifact schema/coverage/determinism, final-lap concentration bounds,
leader-curve sharpening, the lap-1 row exactly reproducing a direct
`simulate_race` call at the same seed, and the CLI backtest end-to-end.

flask-app (3): `app.py` registers the blueprint, all six routes exist
with GET allowed, and unknown seasons return the JSON 404 contract.

## Design notes

- **Pre-compute, don't infer at request time** — mirrors how
  `predictions_api.py` works in this repo and keeps the serving layer
  boring on purpose. Re-generation is one deterministic command.
- **The insight numbers are derived, not stored twice** — `sim_swing_mean`
  is computed from the same fit the simulator used, so artifact and
  simulator cannot drift apart (pinned by the reproduce tests).
- **Future grids are honest by construction** — no quali → championship
  order, never random; ties break deterministically because the artifact
  must stay byte-identical across rebuilds.
