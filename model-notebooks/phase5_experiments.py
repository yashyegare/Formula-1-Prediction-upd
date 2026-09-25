"""
phase5_experiments.py

Phase-5 accuracy experiments, run on the identical walk-forward splits the
production model reports on (train <= Y, test Y+1; RF_PARAMS; active grid).

Part 1 — feature ablation. The 13-feature production contract vs:
    + driver_form_momentum       (slope of the grid->finish delta series)
    + driver_track_form_delta    (circuit-specific finish residual)
    + both
Swept over seeds, mean±std reported, so a verdict cannot be one lucky
seed. Same protocol as measure_pace_pit.py (MODEL_NOTES #9 discipline).

Part 2 — probability calibration. The platform consumes hard buckets, but
Phase 1's evidence and the simulator both live in probabilities, so the
question is whether a calibration layer on top of the SAME RF improves
log loss / Brier score (it cannot change accuracy materially — it
monotonically reorders almost nothing — and it must not, or the layer is
overfit). Calibrators are fit ONLY on training-fold data via 5-fold
cross-validated probabilities (Platt = multinomial logistic on the prob
vector; isotonic = per-class OvR, renormalized) — never on the test year.

Usage:
    python phase5_experiments.py --data ./datasets/cleaned_data.csv
"""
import argparse

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_predict, KFold
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, log_loss
from sklearn.preprocessing import LabelEncoder

import train_model

SEEDS = [42, 7, 123, 2026]
EPS = 1e-9  # log-loss floor


def _walkforward_probs(df: pd.DataFrame, features: list[str],
                       rf_params: dict):
    """Per fold: fit on seasons <= Y, return test-year (y_true, probs).
    Also returns per-fold cross-validated training probabilities so a
    calibrator can be fit without ever touching the test year."""
    X = df[features].copy()
    y = df["position"].apply(train_model.position_index).to_numpy()
    years = df["year"].to_numpy()

    for col in ("GP_name", "constructor", "driver"):
        if col in X.columns:
            X[col] = LabelEncoder().fit_transform(X[col])

    all_years = sorted(df["year"].unique())
    folds = []
    for train_end, test_year in zip(all_years[:-1], all_years[1:]):
        tr, te = years <= train_end, years == test_year
        if tr.sum() == 0 or te.sum() == 0:
            continue
        rf = RandomForestClassifier(**dict(rf_params, n_jobs=-1))
        rf.fit(X[tr], y[tr])
        probs = rf.predict_proba(X[te])
        # align prob columns to class ids even if a fold's train set
        # somehow lacks a class (never true here, but cheap to be safe)
        classes = rf.classes_
        full = np.zeros((probs.shape[0], 3))
        for i, c in enumerate(classes):
            full[:, int(c) - 1] = probs[:, i]
        folds.append({"y": y[te], "p": full, "years": years[te]})
    return folds


def _agg_metrics(folds):
    y = np.concatenate([f["y"] for f in folds])
    p = np.vstack([f["p"] for f in folds])
    pred = p.argmax(axis=1) + 1
    return {
        "acc": accuracy_score(y, pred),
        "logloss": log_loss(y, np.clip(p, EPS, 1 - EPS), labels=[1, 2, 3]),
        "brier": float(np.mean(np.sum((p - _onehot(y)) ** 2, axis=1))),
        "points_recall": (pred[y == 2] == 2).mean(),
        "podium_recall": (pred[y == 1] == 1).mean(),
    }


def _onehot(y):
    out = np.zeros((len(y), 3))
    out[np.arange(len(y)), np.asarray(y) - 1] = 1.0
    return out


# ── calibration ──────────────────────────────────────────────────────────

def _fit_platt(p_train, y_train):
    lr = LogisticRegression(max_iter=1000, C=1.0)
    lr.fit(p_train, y_train)
    return lambda p: lr.predict_proba(p)


def _fit_isotonic(p_train, y_train):
    regs = []
    for c in (1, 2, 3):
        ir = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        ir.fit(p_train[:, c - 1], (y_train == c).astype(float))
        regs.append(ir)

    def apply(p):
        out = np.column_stack([regs[c - 1].predict(p[:, c - 1])
                               for c in (1, 2, 3)])
        out = np.clip(out, EPS, None)
        s = out.sum(axis=1, keepdims=True)
        # isotonic can produce all-zero rows; fall back to the RF probs
        empty = (s.ravel() <= 0)
        out[empty] = p[empty]
        s = out.sum(axis=1, keepdims=True)
        return out / s

    return apply


def _calibrated_eval(df, features, rf_params, calibrator):
    """Walk-forward with calibration: per fold, the calibrator is fit on
    5-fold cross-validated probabilities WITHIN the training seasons
    (time leakage inside the training set is impossible for a prob-level
    recalibration of the same rows; the test year is never seen)."""
    X = df[features].copy()
    y = df["position"].apply(train_model.position_index).to_numpy()
    years = df["year"].to_numpy()
    for col in ("GP_name", "constructor", "driver"):
        if col in X.columns:
            X[col] = LabelEncoder().fit_transform(X[col])

    all_years = sorted(df["year"].unique())
    y_parts, p_parts = [], []
    for train_end, test_year in zip(all_years[:-1], all_years[1:]):
        tr, te = years <= train_end, years == test_year
        if tr.sum() == 0 or te.sum() == 0:
            continue
        rf = RandomForestClassifier(**dict(rf_params, n_jobs=-1))
        rf.fit(X[tr], y[tr])
        p_test = rf.predict_proba(X[te])
        # out-of-fold training probs for the calibrator
        if calibrator == "none":
            apply = None
        else:
            kf = KFold(n_splits=5, shuffle=True, random_state=rf_params["random_state"])
            p_oof = cross_val_predict(
                RandomForestClassifier(**rf_params), X[tr], y[tr],
                cv=kf, method="predict_proba", n_jobs=-1)[:, :3]
            fit = _fit_platt if calibrator == "platt" else _fit_isotonic
            apply = fit(p_oof, y[tr])
            p_test = p_test[:, :3]
        if apply is not None:
            p_test = apply(p_test)
        y_parts.append(y[te])
        p_parts.append(p_test)
    return _agg_metrics([{"y": a, "p": b} for a, b in zip(y_parts, p_parts)])


# ── main ─────────────────────────────────────────────────────────────────

CONTRACTS = {
    "prod13": [],
    "+momentum": ["driver_form_momentum"],
    "+trackdelta": ["driver_track_form_delta"],
    "+both": ["driver_form_momentum", "driver_track_form_delta"],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="./datasets/cleaned_data.csv")
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    df = df[(df["active_driver"] == 1) & (df["active_constructor"] == 1)].copy()
    for col in ("driver_form_momentum", "driver_track_form_delta"):
        if col not in df.columns:
            raise SystemExit(f"[ABORT] '{col}' missing — rebuild cleaned_data.csv first")
        if df[col].nunique() <= 1 and col == "driver_track_form_delta":
            raise SystemExit(f"[ABORT] '{col}' is constant — refusing a fake null result")

    # ── Part 1: feature ablation across seeds ──
    print("=== Part 1: feature ablation (walk-forward, seeds {}) ===".format(SEEDS))
    results = {name: [] for name in CONTRACTS}
    for seed in SEEDS:
        params = dict(train_model.RF_PARAMS, random_state=seed)
        for name, extra in CONTRACTS.items():
            feats = train_model.FEATURES + extra
            folds = _walkforward_probs(df, feats, params)
            m = _agg_metrics(folds)
            results[name].append(m)
    print(f"\n{'contract':<14} {'accuracy':>16} {'log loss':>16} {'brier':>16} {'pts recall':>16}")
    summary = {}
    for name, reps in results.items():
        row = {}
        for k in ("acc", "logloss", "brier", "points_recall"):
            row[k] = (float(np.mean([r[k] for r in reps])),
                      float(np.std([r[k] for r in reps])))
        summary[name] = row
        print(f"{name:<14} {row['acc'][0]:>10.1%}±{row['acc'][1]:.1%} "
              f"{row['logloss'][0]:>8.3f}±{row['logloss'][1]:.3f} "
              f"{row['brier'][0]:>8.3f}±{row['brier'][1]:.3f} "
              f"{row['points_recall'][0]:>10.1%}±{row['points_recall'][1]:.1%}")

    best = max(summary, key=lambda n: summary[n]["acc"][0])
    print(f"\nBest accuracy contract: {best}")

    # ── Part 2: calibration on the best contract ──
    print(f"\n=== Part 2: calibration layer on '{best}' ===")
    for cal in ("none", "platt", "isotonic"):
        reps = []
        for seed in SEEDS:
            params = dict(train_model.RF_PARAMS, random_state=seed)
            m = _calibrated_eval(df, train_model.FEATURES + CONTRACTS[best],
                                 params, cal)
            reps.append(m)
        acc = np.mean([r["acc"] for r in reps])
        ll = np.mean([r["logloss"] for r in reps])
        br = np.mean([r["brier"] for r in reps])
        print(f"{cal:<10} acc {acc:.1%} | log loss {ll:.3f} | brier {br:.3f}")


if __name__ == "__main__":
    main()
