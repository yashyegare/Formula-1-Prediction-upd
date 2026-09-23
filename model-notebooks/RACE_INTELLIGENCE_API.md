# Race intelligence serving layer (Phase 4)

The consumption layer for everything Phases 1–3 built: a **pre-computed
race-intel artifact** plus a small **Flask read API** that serves it.

```
f1_canonical.db ──▶ race_intelligence.py ──▶ datasets/race_intel.json
(Phase 2)           (Phase 3 simulator +           │
                     Phase 1 attribution)          ▼
                                        flask-app/race_intelligence_api.py
                                        GET /api/race-intel/...
```

The intelligence is generated **offline and deterministically**; the API
only reads the file. No numpy/sklearn in the serving path, and the JSON
itself is reviewable in a diff before it ships.

## The artifact (`datasets/race_intel.json`)

One document per season, rebuilt by:

```bash
python race_intelligence.py --season 2026 --sims 2000
```

Contents:

- **`mechanism`** — the fitted swing/dnf parameters (≤ previous season,
  the walk-forward discipline).
- **`races[]`** — per race, per driver: the simulated outcome
  distribution (`p_podium` / `p_points` / `p_out`), `expected_position`,
  simulated DNF rate, and the derived grid-swing insight —
  `observed_swing` (real grid→finish shift) against `sim_swing_mean`
  (what the mechanism expected). The "why it landed there" number a
  dashboard can render directly.
- **`season_attribution`** — the Phase-1 miss taxonomy for the season's
  baseline record (accuracy 68.6%, under-predict 53.3%, dnf_other 25.3%).

Two builds with the same seed are **byte-identical** (verified by test);
seed = `42 + year*100 + round` per race, so adding a round never
reshuffles existing rounds.

## The API (`flask-app/race_intelligence_api.py`)

| Endpoint | Returns |
|---|---|
| `GET /api/race-intel/season/<year>` | full season document |
| `GET /api/race-intel/race/<year>/<round>` | one race's driver array |
| `GET /api/race-intel/drivers/<year>/<round>` | `driverId` + 3 probabilities only |

Failure semantics are explicit, never silently empty: unknown
season/round → 404 with a JSON error; missing/unreadable artifact →
503 telling you to run the generator. The file is cached by mtime, so a
rebuilt artifact is served without a process restart (pinned by test).

## Test coverage (10 tests)

Artifact schema and round ordering, probability sums ≈ 1 and bounds,
byte-level determinism, attribution numbers equal `summarize()` on the
same record, mechanism equals a direct `fit_swing_params` call, and the
per-driver probabilities equal a direct `simulate_race` call at the same
seed (the artifact is a faithful materialization of the simulator, not a
re-implementation). API: response shapes, the drivers projection, 404s,
503-without-artifact, and hot-reload on rebuild.

## Design notes

- **Pre-compute, don't infer at request time** — mirrors how
  `predictions_api.py` works in this repo and keeps the serving layer
  boring on purpose. Re-generation is one deterministic command.
- **The insight numbers are derived, not stored twice** — `sim_swing_mean`
  is computed from the same fit the simulator used, so artifact and
  simulator cannot drift apart (pinned by the reproduce test).
- Not wired into `flask-app/app.py` yet: this is a standalone blueprint
  module so the existing prediction API stays untouched until the
  frontend needs it.
