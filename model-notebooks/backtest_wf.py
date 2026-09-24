"""
backtest_wf.py — build the walk-forward MODEL prediction record.

Companion to error_decomposition.py. backtest_prod.py records what the
DEPLOYED model said about 2026 (239 rows, with the roster-lookahead caveat
documented in MODEL_NOTES). This script records what the walk-forward
harness itself predicts: for every season Y, train on seasons < Y exactly
as evaluate_walk_forward does, but keep the PER-ROW predictions instead of
collapsing them into accuracy metrics.

The result is an honest, prospectively-clean model record (~2,200 rows,
2019-2026) on the same active-grid universe as the quali-bucket baseline,
so error_decomposition.py can answer the Phase-1 question directly:

    does the model miss the SAME races the baseline misses — and when it
    misses, is the miss structure different?

Usage:
    python backtest_wf.py --data ./datasets/cleaned_data.csv --out wf_predictions.csv
    python error_decomposition.py --pred-csv wf_predictions.csv --out attribution_model.csv
"""
import argparse

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder

import train_model


def build_record(df: pd.DataFrame) -> pd.DataFrame:
    """
    Mirror of train_model.evaluate_walk_forward's fold structure (encode
    once, fit per fold on years <= train_end, test on the next year) with
    per-row predictions retained.
    """
    X = df[train_model.FEATURES].copy()
    y = df["position"].apply(train_model.position_index)
    years = df["year"].to_numpy()

    # Same single-pass encoding as evaluate_walk_forward — kept identical so
    # this record's aggregate accuracy reproduces the published walk-forward
    # number exactly.
    for col in ("GP_name", "constructor", "driver"):
        if col in X.columns:
            X[col] = LabelEncoder().fit_transform(X[col])

    all_years = sorted(df["year"].unique())
    rows = []
    for train_end, test_year in zip(all_years[:-1], all_years[1:]):
        tr = years <= train_end
        te = years == test_year
        if tr.sum() == 0 or te.sum() == 0:
            continue
        rf = RandomForestClassifier(**train_model.RF_PARAMS)
        rf.fit(X[tr], y[tr])
        pred = rf.predict(X[te])
        sub = df[te]
        rows.append(pd.DataFrame({
            "year": sub["year"].to_numpy(),
            "round": sub["round"].to_numpy(),
            "race": sub["GP_name"].to_numpy(),
            "driver": sub["driver"].to_numpy(),
            "qpos": sub["quali_pos"].to_numpy(),
            "pred": pred.astype(int),
            "actual": y[te].to_numpy().astype(int),
        }))
        print(f"  fold {test_year}: {te.sum()} rows predicted")

    return pd.concat(rows, ignore_index=True)


def main():
    ap = argparse.ArgumentParser(description="Walk-forward per-row prediction record")
    ap.add_argument("--data", default="./datasets/cleaned_data.csv")
    ap.add_argument("--out", default="wf_predictions.csv")
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    df = df[(df["active_driver"] == 1) & (df["active_constructor"] == 1)].copy()

    print("Building walk-forward per-row record (train <= Y-1, test Y)...")
    rec = build_record(df)
    acc = (rec["pred"] == rec["actual"]).mean()
    print(f"\nRecord: {len(rec)} rows, accuracy {acc:.1%} "
          f"(must match train_model's published walk-forward number)")

    rec.to_csv(args.out, index=False, lineterminator="\n")
    print(f"Written to {args.out}")
    print(f"Next: python error_decomposition.py --pred-csv {args.out} --out attribution_model.csv")


if __name__ == "__main__":
    main()
