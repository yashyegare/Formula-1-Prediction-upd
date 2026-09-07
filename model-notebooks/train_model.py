"""
train_model.py

Trains on cleaned_data.csv (built by build_training_data.py) and exports:
  - rffinal.pkl              the trained model (drop-in replacement)
  - id_maps.json             the driver/constructor/GP_name -> integer
                             LabelEncoder maps, which app.py and the
                             nextjs frontend must use verbatim (the
                             model only understands these exact codes)

Target: a 3-class bucket, not a raw finishing position -- the frontend
literally renders "Podium Finish!" / "Points Finish!" / "Out of Points!"
from it.

Classes: 1 = podium (P1-3), 2 = points (P4-10), 3 = out of points (P11+)

Validation methodology (the honest one):
  The random train_test_split + shuffled CV this script used before let
  races from the SAME season sit on both sides of the split, so the
  offline number (94%) measured season-pattern memorization, not
  prediction. Prod served ~66% because reality doesn't leak the future.
  This script therefore validates WALK-FORWARD: train on seasons <= Y,
  test on Y+1, for every Y in the data. That number is the honest one
  and should land near (or below) what prod actually experiences.

  It also reports the trivial baseline (bucket straight from qualifying
  position) ON THE SAME SPLIT, so "does the model beat the if-statement?"
  is answered fairly, per year and overall.

Usage:
    python train_model.py --data ./datasets/cleaned_data.csv --out ./datasets
"""
import argparse
import json

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix
from sklearn.preprocessing import LabelEncoder

# Inference feature order — app.py /predictGrid builds exactly these named
# columns. Keep in lockstep with flask-app/app.py.
# driver/constructor champ POINTS are share-of-leader ratios (0..1 within
# the snapshot), not raw points — raw points aren't comparable across a
# season and the model can't tell round-4-dominance from round-20-midpack
# without that normalization. driver_recent_form is the mean GRID->FINISH
# DELTA over the driver's last <=5 races (positive = gains places on race
# day; redundant-free complement to quali_pos, whose raw mean-finish form
# variant only carried ~3% importance). constructor_recent_form is the
# team's mean race points over its last <=5 races — reacts to mid-season
# upgrades far faster than the season-cumulative championship ratio.
# gap_to_pole is the driver's best qualifying lap in seconds behind the
# session's fastest — point-in-time by construction (quali precedes the
# race) and the resolution upgrade quali_pos (still ~50% of importance)
# was missing: P3-by-0.05s and P3-by-1.4s are different situations.
FEATURES = [
    "GP_name", "quali_pos", "gap_to_pole", "constructor", "driver",
    "driver_confidence", "constructor_relaiblity",
    "driver_champ_pos", "driver_champ_points_ratio",
    "constructor_champ_pos", "constructor_champ_points_ratio",
    "driver_recent_form", "constructor_recent_form",
]


def position_index(pos: int) -> int:
    """1 = podium (P1-3), 2 = points (P4-10), 3 = out of points (P11+)."""
    if pos < 4:
        return 1
    if pos > 10:
        return 3
    return 2


def evaluate_walk_forward(df: pd.DataFrame, rf_params: dict) -> dict:
    """
    Walk-forward evaluation.    Returns per-year and overall accuracy for both the model and the
    qualifying-position baseline, plus podium recall (the class the UI
    highlights) and points recall (class 2). The points/out boundary
    (P10/P11) is where nearly all the confusion lives — overall accuracy
    can stay flat while masking a real win or loss right at that cutoff,
    so the boundary metric is tracked explicitly.
    """
    X = df[FEATURES].copy()
    y = df["position"].apply(position_index)
    years = df["year"].to_numpy()

    # Encode whichever categorical identity columns are present in FEATURES.
    for col, le in (("GP_name", LabelEncoder()), ("constructor", LabelEncoder()), ("driver", LabelEncoder())):
        if col in X.columns:
            X[col] = le.fit_transform(X[col])

    all_years = sorted(df["year"].unique())
    per_year = []
    all_true, all_pred, all_base = [], [], []
    fold_importances = []

    for train_end, test_year in zip(all_years[:-1], all_years[1:]):
        tr = years <= train_end
        te = years == test_year
        if tr.sum() == 0 or te.sum() == 0:
            continue

        rf = RandomForestClassifier(**rf_params)
        rf.fit(X[tr], y[tr])
        fold_importances.append(rf.feature_importances_)

        pred = rf.predict(X[te])
        base = X.loc[te, "quali_pos"].apply(position_index)

        acc = accuracy_score(y[te], pred)
        base_acc = accuracy_score(y[te], base)
        podium_recall = (pred[y[te] == 1] == 1).mean() if (y[te] == 1).any() else float("nan")
        points_recall = (pred[y[te] == 2] == 2).mean() if (y[te] == 2).any() else float("nan")
        per_year.append({
            "test_year": test_year,
            "train_rows": int(tr.sum()),
            "test_rows": int(te.sum()),
            "model_acc": acc,
            "baseline_acc": base_acc,
            "podium_recall": podium_recall,
            "points_recall": points_recall,
        })
        all_true.extend(y[te].tolist())
        all_pred.extend(pred.tolist())
        all_base.extend(base.tolist())

    all_true = np.array(all_true)
    all_pred = np.array(all_pred)
    all_base = np.array(all_base)

    return {
        "per_year": per_year,
        "overall_model_acc": accuracy_score(all_true, all_pred),
        "overall_baseline_acc": accuracy_score(all_true, all_base),
        "overall_podium_recall": (all_pred[all_true == 1] == 1).mean(),
        "overall_points_recall": (all_pred[all_true == 2] == 2).mean(),
        "baseline_points_recall": (all_base[all_true == 2] == 2).mean(),
        "confusion": confusion_matrix(all_true, all_pred, labels=[1, 2, 3]),
        # Mean importances across folds — importance on a single fit can
        # mislead when seasons differ in size, so average like the accuracy.
        "feature_importances": sorted(
            zip(X.columns, np.mean(fold_importances, axis=0)), key=lambda t: -t[1]
        ),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="./datasets/cleaned_data.csv")
    ap.add_argument("--out", default="./datasets")
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    # only train on rows where both the driver and constructor are still
    # on the current grid -- there's no point learning label-encodings
    # for teams/drivers that don't exist anymore
    df = df[(df["active_driver"] == 1) & (df["active_constructor"] == 1)].copy()

    # Walk-forward experiments (Sept 2026): the original n300/d10 over-fit
    # short seasons. A 5-config sweep picked this config (best mean gap vs
    # baseline and best podium recall). Redefining driver_recent_form as a
    # grid->finish delta and adding constructor_recent_form was then A/B
    # tested on identical splits across seeds 42/7/123/2026: the 12-feature
    # set was never worse on accuracy and consistently better on points
    # recall (+2-3pt, the P10/P11 boundary), at the cost of ~1pt podium
    # recall on seed 42 — adopted as the better boundary model.
    #
    # gap_to_pole (13 features, same seed sweep): importance 0.12 and
    # quali_pos relieved 0.49 -> 0.44 — the resolution mechanism worked —
    # but accuracy meaned -0.3pt while points recall meaned +0.5pt: a wash
    # within noise, kept for the boundary metric. Together with the
    # model-family swap (LightGBM/XGBoost, incl. native categoricals, all
    # 3-5pt BELOW the RF and the baseline) this is the evidence that the
    # ceiling is the feature set / data volume, not the model — see
    # model-notebooks/MODEL_NOTES.md.
    rf_params = dict(n_estimators=400, max_depth=12, min_samples_leaf=20,
                     max_features=0.8, random_state=42)

    # ── Honest walk-forward evaluation FIRST ──
    print("=== Walk-forward validation (train <= Y, test Y+1) ===")
    if df["year"].nunique() < 2:
        print("[SKIP] Data has fewer than two seasons - walk-forward evaluation"
              " needs at least a train season and a later test season.")
        report = None
    else:
        report = evaluate_walk_forward(df, rf_params)
    if report:
        for r in report["per_year"]:
            print(f"  test {r['test_year']}: model {r['model_acc']:.1%} vs baseline {r['baseline_acc']:.1%}"
                  f" | podium recall {r['podium_recall']:.0%} | points recall {r['points_recall']:.0%}"
                  f" | trained on {r['train_rows']} rows")
        print(f"\nOverall walk-forward accuracy: {report['overall_model_acc']:.1%}")
        print(f"Baseline (quali bucket) on same splits: {report['overall_baseline_acc']:.1%}")
        print(f"Overall podium recall: {report['overall_podium_recall']:.0%}")
        print(f"Overall points recall: {report['overall_points_recall']:.0%}"
              f" (baseline {report['baseline_points_recall']:.0%})"
              " <- the P10/P11 boundary where the confusion lives")
        print("Confusion matrix (rows=actual, cols=predicted; classes 1=podium 2=points 3=out):")
        print(report["confusion"])
        print("\nWalk-forward feature importances (importance can shift with")
        print("the feature set — read alongside the accuracy, not instead of it):")
        for name, imp in report["feature_importances"]:
            print(f"  {name:32s} {imp:.2f}")

        beats = report["overall_model_acc"] - report["overall_baseline_acc"]
        if beats <= 0:
            print("\n[WARN] The model does NOT beat the qualifying-position baseline on")
            print("walk-forward splits. Any feature/model tuning should be measured")
            print("against this report, not against random-split accuracy.")

    # ── Final model: fit on ALL data (serving uses it for the future) ──
    X = df[FEATURES].copy()
    y = df["position"].apply(position_index)

    le_gp = LabelEncoder()
    le_constructor = LabelEncoder()
    le_driver = LabelEncoder()

    X["GP_name"] = le_gp.fit_transform(X["GP_name"])
    X["constructor"] = le_constructor.fit_transform(X["constructor"])
    X["driver"] = le_driver.fit_transform(X["driver"])

    rf = RandomForestClassifier(**rf_params)
    rf.fit(X, y)

    joblib.dump(rf, f"{args.out}/rffinal.pkl")

    id_maps = {
        "GP_name": {cls: int(i) for i, cls in enumerate(le_gp.classes_)},
        "constructor": {cls: int(i) for i, cls in enumerate(le_constructor.classes_)},
        "driver": {cls: int(i) for i, cls in enumerate(le_driver.classes_)},
    }
    # encoding pinned: locale defaults differ (Windows cp1252 vs Linux
    # utf-8) and produced artifacts CI could not decode. Never rely on it.
    with open(f"{args.out}/id_maps.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(id_maps, f, indent=2, ensure_ascii=False)

    print(f"\nSaved model to {args.out}/rffinal.pkl")
    print(f"Saved ID maps to {args.out}/id_maps.json")
    print(f"\n{len(id_maps['driver'])} drivers, {len(id_maps['constructor'])} constructors, "
          f"{len(id_maps['GP_name'])} GPs encoded")


if __name__ == "__main__":
    main()
