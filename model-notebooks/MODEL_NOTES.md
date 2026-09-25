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

9. **Lap-pace + pit stops** (regressive null, ml-dev branch):
   the last feature lever, and the one that closed the feature program. The
   committed `lap_times.csv`/`pit_stops.csv`
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
   - Known limitation (deliberate design, not an oversight): pit in/out
     laps and safety-car laps are NOT excluded via an explicit join to
     pit-stop lap numbers. Instead the signal stacks two medians: each
     driver's per-lap delta is measured against the race's field-MEDIAN
     lap time, and the driver's per-race value is the median across
     their own laps. A full-field safety-car slowdown shifts every lap
     uniformly and cancels in the delta; isolated pit laps sit in the
     tails the median discards. Not bulletproof — a race with many
     pit-affected laps for one driver could still leak a little noise
     through — but a defensible choice that avoids a fragile
     lap-number join. If the eventual verdict is surprising in either
     direction, check this first.
   - Measurement staged: `measure_pace_pit.py` runs the seed-swept
     16-feature vs 18-feature ablation on identical splits and REFUSES to
     run if the pace/pit columns are constant (a stale build must not
     masquerade as a null result).
   - **Verdict (recorded 2026-09-13, fetch complete at 184/184 races —
     201,811 laps, 6,376 pit stops; 2024-25 validation folds 99-100%
     covered, so this is not a coverage artifact):** seed-swept 16f vs
     18f on identical splits — accuracy 66.7% → 66.3% (−0.4pt), points
     recall 68.1% → 66.3% (**−1.7pt**), podium recall 74.1% → 74.0%
     (wash). The 18-feature contract was worse on **4/4 seeds including
     the boundary metric** — a regressive null under the pre-registered
     decision rule, not a wash to keep. Notable: `lap_pace_delta_s`
     carried 0.09 importance (third overall) yet *degraded* accuracy —
     the model uses the signal but generalizes worse, because recent
     pace is already encoded in `driver_recent_form` + the quali
     features, and the lap-time distribution shifts hardest across the
     2022 regulation change, exactly inside the validation folds.
   - **Post-verdict actions:** production `FEATURES` pruned 18 → 13
     (`train_model.py`, and `PREDICT_FEATURES` in `flask-app/app.py`);
     all five experiment features stay computed in
     `build_training_data.py` and pinned by the schema test, so every
     null stays reproducible; `measure_pace_pit.py` now pins its
     16-vs-18 contracts literally, keeping the recorded comparison
     reproducible regardless of what the production contract becomes
     (supersedes the “kept on the branch” notes in #7/#8). Finalized
     data committed: `lap_times_jolpica.csv` / `pit_stops_jolpica.csv`.
   - **Feature program closed.** Six independent angles, one ceiling:
     recent-form framings (#3), gap-to-pole (#4), model families (#5),
     DNF-cause split (#7), circuit type (#8), lap-pace + pit stops
     (#9). 13 features is the final contract.

### 10. Phase-5 accuracy program: momentum, per-circuit history, calibration, blend (2026-09-25)

Re-opened the feature program one more time for the four named levers of
the Phase-5 plan, with the same pre-registered discipline:

- **`driver_form_momentum`** — the slope (mean first-difference) of the
  driver's grid→finish delta over the strictly prior ≤5 races. The level
  feature says how well the driver is racing; the slope says which way
  the trend is moving (upgrade trajectories, confidence swings).
- **`driver_track_form_delta`** — the driver's mean CLASSIFIED finish at
  this GP over prior visits minus their mean classified finish overall:
  strictly the circuit-specific residual (Monaco-2026 evidence: quali
  P10 → won). DNFs skipped symmetrically in both means; neutral prior
  below `MIN_TRACK_VISITS=2` prior classified visits at the GP — the RF
  splits on the threshold, so a fabricated neutral for real visits would
  blur exactly the signal the feature exists to carry.
- **Tyre age / compound** — a recorded non-starter: the pit-stops feed
  carries no compound or stint data and Jolpica does not serve tyre
  fields, so the feature cannot be built from this data at any price.
- **Probability calibration** — Platt scaling and per-class isotonic on
  5-fold out-of-fold training probabilities, fit per walk-forward fold,
  test year never touched.

**Feature ablation (seed-swept walk-forward, identical splits, 4 seeds):**
prod13 66.3%±0.3 (LL 0.755) → +momentum 66.4%±0.1 (0.753) → +trackdelta
66.2%±0.2 (0.755) → +both 66.4%±0.2 (0.753). All within ±0.3pt noise: a
**null**, matching the pattern of #7-#9. Both features stay computed in
`build_training_data.py` and pinned by tests; the serving `FEATURES`
contract stays at 13. Not redundant — corr(momentum, form level) is only
0.25 — just no marginal signal beyond what `quali_pos` already encodes.
Mechanism re-confirmed: with the expanded set, `quali_pos` carries **0.53**
of total importance (it was 44-50% pre-#4); the model remains a
qualifying-position reader at heart.

**Calibration verdict: rejected, actively harmful.** Raw RF 0.753 LL →
Platt 0.766, isotonic 0.813 (Brier likewise worse). The RF's native
probabilities (400-tree vote averaging) are already better calibrated
than any calibrator this data volume can fit — the layer only added
estimation error.

**The one live lead — RF/simulator complementarity (unadopted).** On the
2026 raced rounds (n=217 joined to the race-intel artifact): RF LL
0.720, simulator 0.707, and the two models' argmax picks agree only
**90.3%** of the time — they are differently wrong, not differently
calibrated versions of the same opinion. A 0.3-weight simulator blend
measures LL 0.698. This is one season (217 rows), the blend weight is
unregularized, and the serving path (the API already ships the
simulator's distributions) would need designing — so it is recorded as
candidate experiment #11, NOT adopted. If pursued, the honest protocol
is the same: pre-registered weight grid, seed-swept walk-forward over
all seasons, decision on mean±std.

**Feature program closed, second and final time.** Eight independent
angles now measure the same ceiling (#3, #4, #5, #7, #8, #9, and #10's
two). The remaining upside in this platform is not another column in
cleaned_data.csv — it is the complementarity between the two models the
platform already serves.

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
- **Every remaining feature family measured null or regressive.** The
  DNF-cause split (#7), street-circuit flag (#8), and lap-pace + pit stops
  (#9) — the last on 201,811 real laps with 99-100% coverage in the
  validation folds — all landed at identical-or-worse. Above quali +
  standings + form, the feature space is exhausted at this data size.

## What this means going forward

- **Don't bolt on more standings-derived features.** The two cheapest
  experiments (driver delta, constructor form), the resolution upgrade
  (gap-to-pole), and the lap-pace program have all been spent; the feature
  program is closed outright (#7-#9). Returns are diminishing at the
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
