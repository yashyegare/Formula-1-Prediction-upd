# Error decomposition — why predictions miss

Phase 1 of the Race Intelligence plan (the "why did it happen" layer), built
from data already in the repo. Produced by `error_decomposition.py` +
`backtest_wf.py`; analyzed three prediction records:

| Record | Universe | n | Accuracy |
|---|---|---:|---:|
| Quali-bucket **baseline** | active grid, 2018–2026 | 2,193 | 66.4% |
| **Model** (walk-forward per-row, `backtest_wf.py`) | active grid, 2019–2026 folds | 2,088 | 66.6% |
| **Deployed API** (`backtest_prod.py --out`, roster lookahead caveat applies) | 2026 | 242 | 71.1% |

The aggregate accuracies reproduce the documented numbers exactly
(66.3–66.4% baseline, 66.6% walk-forward, 71.1% prod-2026) — the
decomposition is computed over a validated record, not a parallel one.

## What the module attributes

Every driver-race is labeled:

- `correct` / `correct_dnf` — bucket matched. A DNF that landed out of
  points as predicted is a **correct** prediction, not a miss (pinning this
  explicitly was forced by a first-pass bug that counted it as a miss).
- `dnf_mech` / `dnf_driver` / `dnf_other` — miss caused by not finishing;
  cause class from the same status taxonomy the training pipeline uses.
- `over_predict` / `under_predict` — finished on the wrong side of a bucket
  boundary. Each miss row also carries post-race evidence: race-pace delta
  vs the field median (`pace_delta_s`), grid→flag running-position change
  (`last_gain`), pit time/stops, and the race's slow-lap (SC/VSC) count and
  first slow lap. Evidence is appended to the verdict only beyond fixed
  thresholds, so a bare "Finished worse than predicted" means no signal
  crossed those thresholds.

Evidence construction: slow-lap detection compares each lap's FIELD-median
time to the race's median lap (>1.20x = slow), which cancels per-driver
pace and catches SC/VSC/red-flag laps without race-control data. 2026's
Jolpica statuses are generic ("Retired", "Did not start"), so all 2026 DNFs
land in `dnf_other` — cause sub-classification exists for 2018–2025 only.

## Findings

### 1. The model's edge is real but lives almost entirely at the boundary

Paired on all 2,088 walk-forward rows (same universe, same splits):

|  | model right | model miss |
|---|---:|---:|
| **baseline right** | 1,235 | 150 |
| **baseline miss** | 156 | 547 |

- Rescues 156, regresses 150 → net +6 rows ≈ the +0.2pt edge. The model is
  a boundary-refinement machine, not a different predictor: on 84.5% of
  rows it outputs the same bucket as the quali baseline.
- Rescues are 85% under-predict fixes (P10/P11-type rows the baseline
  buries in "out of points"); regressions are 57% over-predicts. Same
  mechanism, opposite directions.
- On 547 both-miss rows, 96.7% of the time both predictors output the
  SAME bucket — co-misses inherit the quali anchor. The residual is shared
  noise, not a modeling gap either tool can see.

### 2. Miss taxonomy (share of misses, active grid)

| Cause | baseline 2018–26 | model (WF) | prod 2026 |
|---|---:|---:|---:|
| DNF (all classes) | 20.4% | 24.3% | 28.6% |
| over_predict | 28.8% | 39.5% | 22.9% |
| under_predict | 50.8% | 36.3% | 48.6% |

- The baseline's miss mass is under-predict (50.8%): quali anchors cannot
  see race-day gainers. The model converts much of that segment into
  boundary rescues (under-predict share falls to 36.3%) and its own misses
  skew over-predict (39.5%) — the price of promoting drivers into points
  buckets that sometimes don't hold.
- In 2026 (both baseline and prod) under-predict dominates (48.6–53.3%) —
  the most volatile recent season in the record; consistent with the 21%
  DNF rate (highest in the dataset, 2018–25 range 11–20%).

### 3. SC exposure is a weak concentration signal — effectively a null

61% of ALL predictions occur in races with ≥3 detected slow laps (the
detector is liberal — it counts VSC/red-flag/format anomalies too). Misses
sit in those races only 66% of the time → **1.08x lift**. SC exposure does
NOT meaningfully concentrate prediction error. The Layer-2 scenario model
should not overweight SC scenarios relative to ordinary under-predict
variance.

### 4. Grid swings dominate finished-race misses

66% of all misses (baseline record) involve a ≥3-place grid→finish swing;
56% of over-predict misses carry slow race pace (>+0.3s/lap) vs 29% of
under-predicts carrying fast pace. Race-day position dynamics — not
strategy exoticness — are the main finished-race miss mechanism.

## Post-Phase-2 correction

The docstring/plan claim that the full results.csv universe "drags the
baseline ~20pt below the documented 66%" was wrong — that gap was the
(year, round, driver) quali-lookup key bug, not survivorship. Verified
against the canonical DB (Phase 2): the full universe (3,693 rows) pools at
**68.9%**, the active grid at **66.4%**, and the two agree row-for-row
where they overlap. Universe composition (active grid skews recent), not
retired-driver quality.

## Implications for the plan

1. **Error decomposition is cheap when data contracts already exist** —
   built entirely from committed CSVs + reused status taxonomy; zero new
   ingestion. The canonical data model (plan §2) should inherit these
   keys: (year, round, driverId) + the status taxonomy + the slow-lap
   detector's threshold contract.
2. **The under-predict segment is the model's only remaining upside.**
   It cannot be fixed pre-race (feature program closed, MODEL_NOTES #7–#9);
   the plan's scenario model (§3 Layer 2) should target the *distribution*
   of grid→finish swings rather than SC/weather exotica.
3. **Prod-2026's higher accuracy (71.1%) is roster-lookahead, not skill**
   — per MODEL_NOTES' standing caveat. Its miss structure nonetheless
   matches the honest records' shape (under-predict dominant), which is
   the actual sanity signal.
4. **Do not build live SC-prediction features** (plan §6) on the basis of
   error concentration — there is none. Build live grid-swing / pace-trend
   tracking instead.

## Files

- `model-notebooks/error_decomposition.py` — attribution module (24 tests)
- `model-notebooks/backtest_wf.py` — walk-forward per-row record builder
- `model-notebooks/backtest_prod.py` — now writes `--out` prediction records
- `model-notebooks/attribution_baseline_all.csv` — baseline record (2,193)
- `model-notebooks/wf_predictions.csv` — model record (2,088)
- `model-notebooks/backtest_2026.csv` + `attribution_prod_2026.csv` — deployed API
- `model-notebooks/attribution_baseline_2026.csv` — baseline 2026 slice

Reproduce:

```bash
python backtest_wf.py --data ./datasets/cleaned_data.csv --out wf_predictions.csv
python error_decomposition.py --pred-csv wf_predictions.csv --out attribution_model.csv
python error_decomposition.py --datasets ./datasets --out attribution_baseline_all.csv
python backtest_prod.py --year 2026 --out backtest_2026.csv   # needs API up
python error_decomposition.py --pred-csv backtest_2026.csv --year 2026 --out attribution_prod_2026.csv
```
