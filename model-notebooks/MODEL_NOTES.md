# Model notes — where the ceiling is, and the evidence for it

These are the recorded conclusions from the September 2026 modeling sessions.
Every number below comes from the walk-forward harness in `train_model.py`
(train on seasons ≤ Y, test on Y+1) — never random splits, which leaked
season patterns and inflated the old offline number to 94%.

## Headline numbers (current 13-feature model)

| Metric | Value | Baseline (quali bucket, same splits) |
|---|---|---|
| Overall walk-forward accuracy | 66.6% | 66.3% |
| Podium recall | 74% | — |
| **Points recall (P4-10)** | **69%** | **63%** |

The model's advantage lives almost entirely at the **P10/P11 boundary** —
the most competitive, highest-variance part of the grid, where the confusion
matrix concentrates (podium→out errors are nearly zero; points↔out is
essentially the whole error budget). Overall accuracy dilutes this because
podium and out-of-points were already easy; points recall is tracked
explicitly on every run for that reason.

## The experiments that produced the ceiling evidence

1. **Leakage fix + honest validation** (first rework): the original 94% was
   leakage — lifetime DNF stats stamped from the future, random season-split
   CV. Walk-forward confirmed prod's ~66% was always the real number.

2. **Point-in-time features** (adopted): expanding-window
   driver/constructor reliability; prior-round championship standings as
   share-of-leader ratios. Closed the deficit to the trivial baseline
   (−0.6pt → +0.4pt).

3. **Form features** (adopted): driver form redefined from raw mean finish
   (redundant with quali_pos, 3% importance) to the mean grid→finish delta
   (2%); constructor form added as rolling last-5 team points (9% — second
   most important feature). Points recall +2-3pt, stable across 4 seeds.

4. **Gap-to-pole** (kept, verdict: wash): the driver's best quali lap in
   seconds behind pole, from Q1/Q2/Q3 times already in the dataset. The
   mechanism worked exactly as predicted — importance 0.12, third overall,
   and quali_pos relieved from 0.49 to 0.44 — but meaned −0.3pt accuracy /
   +0.5pt points recall across seeds. A resolution upgrade to the dominant
   feature produced no step change.

5. **Model-family swap** (rejected): LightGBM and XGBoost on the identical
   12-feature set and harness — including LightGBM's native categorical
   handling and three regularization levels — scored **59.5–63.6%**, i.e.
   3–5pt *below* both the RF and the trivial baseline. Boosting's greedy
   split-search overfits the small, noisy panel (~2,000 rows, ~40 rows per
   fold-year) where bagging's averaging does not.

6. **Calibration** (checked, healthy): RF probabilities on walk-forward
   predictions are well calibrated out of the box — reliability bins track
   the diagonal (e.g. 0.55-predicted bins realize 0.56–0.60), podium Brier
   0.098, log loss 0.754. No `CalibratedClassifierCV` needed if
   `predict_proba` is ever exposed in the UI.

7. **DNF-cause split** (null result, ml-dev branch): statuses classified
   into mechanical (engine/gearbox-class → the car's rate,
   `constructor_mech_dnf_rate`) vs accident/collision (the driver's
   racecraft, `driver_acc_dnf_rate`), both expanding-window over prior
   entries. Measured identically to the 13-feature model — 66.6% / podium
   74% / points 68% — with ~3% combined importance. The cause-agnostic DNF
   signal already inside `driver_confidence`/`constructor_relaiblity`
   covers what the split adds at this data size. Machinery kept on the
   branch as the experiment record; the null strengthens the ceiling
   evidence: another reliability-derived feature produced nothing.

8. **Street-circuit flag** (null result, ml-dev branch): binary flag for
   Monaco/Baku/Singapore/Jeddah/Las Vegas keyed by circuitId — a coarse
   track-character signal the label-encoded GP_name fails to give the
   model. Measured identically (66.6% / 74% / 68%), importance 0.00: the
   RF already extracts track character through GP_name + gap_to_pole, so
   the coarse binary adds nothing. Kept on the branch as the experiment
   record.

9. **Lap-pace + pit stops** (IN PROGRESS, ml-dev branch — verdict pending):
   the remaining feature lever. The committed `lap_times.csv`/`pit_stops.csv`
   are Ergast-era leftovers keyed by `raceId` (1-1033, pre-2021 coverage)
   with no crosswalk to the pipeline's `year`/`round` keys (verified:
   `id_maps.json` holds only label-encoder maps), so a fresh Jolpica fetch
   was required. Status:

   - `fetch_lap_pace.py` — checkpointed per-race-fragment fetcher (atomic
     writes; a crash can neither duplicate nor lose a race), hardened with
     5xx retry + multi-pass after a Jolpica 520 killed the first run.
     Fetching all 184 completed 2018-2026 races (laps + pit stops), hours
     at the unauthenticated rate limit.
   - Features wired end to end and pinned by 39 tests: `lap_pace_delta_s`
     (driver's mean per-race MEDIAN lap delta to the field median over
     last ≤5 races, seconds, per-race DNF exclusion) and
     `constructor_pit_time_s` (team's mean median stop duration; stops
     mapped to constructors via results). Real-data schema smoke on the
     partial fetch: 100% driverId join rate; 2018/1 deltas came out
     Hamilton −1.87s / Räikkönen −1.57s / Vettel −1.44s fastest — sane.
   - Measurement staged: `measure_pace_pit.py` runs the seed-swept
     16-feature vs 18-feature ablation on identical splits and REFUSES to
     run if the pace/pit columns are constant (a stale build must not
     masquerade as a null result).
   - Decision rule (same discipline as prior adoptions): keep only if the
     18-feature contract wins the boundary metric (points recall) or
     accuracy consistently across seeds; otherwise record the null. Two
     nulls here would close the feature program: four independent
     pace/form framings + two model families all landing in the same
     place is the strongest ceiling proof this data supports.

## Why the ceiling sits where it sits

Three independent lines of evidence:

- **The dominant feature resists refinement.** quali_pos carries ~44-50% of
  importance. Giving the model a genuinely finer version of the same signal
  (gap-to-pole, 0.12 importance) moved the boundary metric by half a point,
  not several.
- **No model family beats the trivial baseline by much.** The RF's +0.3-0.5pt
  over "P1-3 → podium, P4-10 → points" is real but tiny; stronger learners
  do *worse*. There is little extractable structure left in these features.
- **The residual is dominated by race-day noise.** Mechanical failures,
  first-lap incidents, safety cars, and strategy variance are invisible to
  any pre-race feature set. That is a property of the sport, not a gap in
  the modeling.

## What this means going forward

- **Don't bolt on more standings-derived features.** The two cheapest
  experiments (driver delta, constructor form) and the resolution upgrade
  (gap-to-pole) have all been spent; returns are diminishing at the
  boundary of what pre-race data can say.
- **The remaining lever is data volume and granularity**, not architecture:
  more seasons (the 2018+ window is ~3,700 rows), and weather/track-state
  features if a source exists. Even then, expect increments, not steps.
- **The honest write-up is the artifact.** A model that beats the trivial
  baseline by ~0.5pt overall and ~5-6pt at the P10/P11 boundary — with the
  leakage bug found, fixed, and pinned by tests, the family swap tried and
  rejected on evidence, and the ceiling explained — is a stronger portfolio
  story than an unexplained bigger number. If gap-to-pole-style refinements
  keep landing at noise level, the next honest move is to present this
  analysis, not to keep tuning.

## Serving notes

For a *future* race, "all data to date" is the correct point-in-time value,
so `current_roster.json` keeps lifetime confidence/reliability, the latest
championship snapshot, rolling form, and gap-to-pole references (per-GP
median + each driver's last actual gap). `app.py /predictGrid` accepts an
optional `gap_to_pole` from the frontend and falls back driver-last-gap →
per-GP median → 0.0. Backtests of *past* rounds against the live endpoint
(`backtest_prod.py`) necessarily use post-round features and are sanity
checks, not prospective accuracy estimates.
