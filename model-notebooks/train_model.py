"""
train_model.py

Trains on cleaned_data.csv (built by build_training_data.py) and exports:
  - rffinal.pkl              the trained model (drop-in replacement)
  - id_maps.json             the driver/constructor/GP_name -> integer
                              LabelEncoder maps, which app.py and the
                              nextjs frontend must use verbatim (the
                              model only understands these exact codes)

Target: the original project predicts a 3-class bucket, not a raw
finishing position -- the frontend literally renders "Podium Finish!" /
"Points Finish!" / "Out of Points!" based on it. We keep that shape
(RandomForestClassifier, 3 classes) but fix what feeds it: the bucket
is computed from the driver's ACTUAL race finishing position, not the
qualifying-session position the original notebook accidentally used
(see build_training_data.py's docstring for that bug).

Classes: 1 = podium (P1-3), 2 = points (P4-10), 3 = out of points (P11+)

Usage:
    python train_model.py --data ./datasets/cleaned_data.csv --out ./datasets
"""
import argparse
import json

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.metrics import accuracy_score, confusion_matrix
from sklearn.preprocessing import LabelEncoder


def position_index(pos: int) -> int:
    """1 = podium (P1-3), 2 = points (P4-10), 3 = out of points (P11+)."""
    if pos < 4:
        return 1
    if pos > 10:
        return 3
    return 2


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

    X = df[["GP_name", "quali_pos", "constructor", "driver",
            "driver_confidence", "constructor_relaiblity"]].copy()
    y = df["position"].apply(position_index)

    le_gp = LabelEncoder()
    le_constructor = LabelEncoder()
    le_driver = LabelEncoder()

    X["GP_name"] = le_gp.fit_transform(X["GP_name"])
    X["constructor"] = le_constructor.fit_transform(X["constructor"])
    X["driver"] = le_driver.fit_transform(X["driver"])

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    rf = RandomForestClassifier(n_estimators=300, max_depth=10, random_state=42)
    rf.fit(X_train, y_train)

    pred = rf.predict(X_test)
    acc = accuracy_score(y_test, pred)
    baseline_pred = X_test["quali_pos"].apply(position_index)
    baseline_acc = accuracy_score(y_test, baseline_pred)
    print(f"Model accuracy: {acc:.1%}")
    print(f"Naive baseline accuracy (bucket from quali pos directly): {baseline_acc:.1%}")
    print("Confusion matrix (rows=actual, cols=predicted; classes 1=podium 2=points 3=out):")
    print(confusion_matrix(y_test, pred, labels=[1, 2, 3]))

    cv_acc = cross_val_score(rf, X, y, cv=StratifiedKFold(5, shuffle=True, random_state=42))
    print(f"5-fold CV accuracy: {cv_acc.mean():.1%} (+/- {cv_acc.std():.1%})")

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