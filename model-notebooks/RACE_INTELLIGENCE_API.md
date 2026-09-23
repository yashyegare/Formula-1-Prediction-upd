# Race intelligence serving layer (Phase 4)

The consumption layer for everything Phases 1–3 built: a **pre-computed
race-intel artifact**, a **Flask blueprint** that serves it, and a
**Next.js dashboard** that renders it.

```
f1_canonical.db ──▶ race_intelligence.py ──▶ datasets/race_intel.json
(Phase 2)           (Phase 3 simulator +           │
                     Phase 1 attribution)          ▼
                                        flask-app/race_intelligence_api.py
                                        (blueprint, registered in app.py)
                                                   │
                                                   ▼
                                        nextjs-app/src/pages/race-intel.tsx
```

The intelligence is generated **offline and deterministically**; the API
only reads the file. No numpy/sklearn in the serving path, and the JSON
itself is reviewable in a diff before it ships.

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

Failure semantics are explicit, never silently empty: unknown
season/round → **JSON 404** with an error body; missing/unreadable
artifact → **503** telling you to run the generator. The file is cached
by mtime, so a rebuilt artifact is served without a process restart
(pinned by test).

## The dashboard (`nextjs-app/src/pages/race-intel.tsx`)

One page, three views driven by the same data:

- **Race selector** — a pill per round with a status dot (green = raced,
  amber = pre-race prediction), landing on `next_round` by default.
- **Driver table** — sorted by expected position: grid, E[Pos], and
  podium/points/out probability bars. On raced rounds an extra **Swing**
  column shows `observed_swing (exp sim_swing_mean)` — green for
  race-day gainers, red for losers — the Phase-1 insight rendered.
- **Attribution footer** — the season's miss taxonomy and mechanism
  parameters.

Errors surface the API's explicit bodies (the 503 "generate the
artifact" message) instead of blank tables.

## Test coverage

model-notebooks (15): artifact schema v2 and round ordering, probability
sums ≈ 1 and bounds, byte-level determinism, future-grid determinism
(championship leader holds slot 1), attribution equal to `summarize()`,
mechanism equal to a direct `fit_swing_params` call, raced AND future
rounds equal direct `simulate_race` calls at the same seed (the artifact
is a faithful materialization of the simulator, not a re-implementation),
and the API: response shapes, the drivers projection, the light index,
the next endpoint (including 404 when the season is complete), 404s,
503-without-artifact, and hot-reload on rebuild.

flask-app (3): `app.py` registers the blueprint, all five routes exist
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
