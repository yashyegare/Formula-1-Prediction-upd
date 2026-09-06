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
FEATURES = [
    "GP_name", "quali_pos", "constructor", "driver",
    "driver_confidence", "constructor_relaiblity",
    "driver_champ_pos", "driver_champ_points",
    "constructor_champ_pos", "constructor_champ_points",
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
    Walk-forward evaluation. Returns per-year and overall accuracy for
    both the model and the qualifying-position baseline, plus podium
    recall (the class the UI highlights).
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

    for train_end, test_year in zip(all_years[:-1], all_years[1:]):
        tr = years <= train_end
        te = years == test_year
        if tr.sum() == 0 or te.sum() == 0:
            continue

        rf = RandomForestClassifier(**rf_params)
        rf.fit(X[tr], y[tr])

        pred = rf.predict(X[te])
        base = X.loc[te, "quali_pos"].apply(position_index)

        acc = accuracy_score(y[te], pred)
        base_acc = accuracy_score(y[te], base)
        podium_recall = (pred[y[te] == 1] == 1).mean() if (y[te] == 1).any() else float("nan")
        per_year.append({
            "test_year": test_year,
            "train_rows": int(tr.sum()),
            "test_rows": int(te.sum()),
            "model_acc": acc,
            "baseline_acc": base_acc,
            "podium_recall": podium_recall,
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
        "confusion": confusion_matrix(all_true, all_pred, labels=[1, 2, 3]),
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

    # Walk-forward experiments (Sept 2026) showed the original n300/d10
    # over-fit short seasons: regularized configs beat it by ~2pts and
    # podium recall, without touching the baseline gap. Chosen config:
    rf_params = dict(n_estimators=300, max_depth=12, min_samples_leaf=20,
                     max_features=0.5, random_state=42)

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
                  f" | podium recall {r['podium_recall']:.0%} | trained on {r['train_rows']} rows")
        print(f"\nOverall walk-forward accuracy: {report['overall_model_acc']:.1%}")
        print(f"Baseline (quali bucket) on same splits: {report['overall_baseline_acc']:.1%}")
        print(f"Overall podium recall: {report['overall_podium_recall']:.0%}")
        print("Confusion matrix (rows=actual, cols=predicted; classes 1=podium 2=points 3=out):")
        print(report["confusion"])

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
    with open(f"{args.out}/id_maps.json", "w") as f:
        json.dump(id_maps, f, indent=2, ensure_ascii=False)

    print(f"\nSaved model to {args.out}/rffinal.pkl")
    print(f"Saved ID maps to {args.out}/id_maps.json")
    print(f"\n{len(id_maps['driver'])} drivers, {len(id_maps['constructor'])} constructors, "
          f"{len(id_maps['GP_name'])} GPs encoded")


if __name__ == "__main__":
    main()
