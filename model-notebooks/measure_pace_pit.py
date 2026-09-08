"""
measure_pace_pit.py

One-command ablation for the pace/pit features once the lap-pace fetch
completes. Runs the identical walk-forward harness twice on identical
splits and seeds - the current 16-feature production contract vs the
18-feature contract with lap_pace_delta_s + constructor_pit_time_s - and
prints the comparison, so the keep-or-drop verdict is one command:

    python fetch_lap_pace.py --finalize
    python build_training_data.py --datasets ./datasets --out ./datasets
    python measure_pace_pit.py --data ./datasets/cleaned_data.csv

The guard against a silent noop: if the pace/pit columns carry no
information (all zero / constant), the ablation refuses to run - that is
exactly the failure mode a stale or absent fetch would produce, and it
must not masquerade as a "null result".
"""

import argparse

import numpy as np
import pandas as pd

import train_model

PACE_PIT_FEATURES = ["lap_pace_delta_s", "constructor_pit_time_s"]
SEEDS = [42, 7, 123, 2026]


def main():
    ap = argparse.ArgumentParser(description="Seed-swept pace/pit feature ablation")
    ap.add_argument("--data", default="./datasets/cleaned_data.csv")
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    df = df[(df["active_driver"] == 1) & (df["active_constructor"] == 1)].copy()

    for col in PACE_PIT_FEATURES:
        if col not in df.columns:
            raise SystemExit(f"[ABORT] '{col}' missing - rebuild cleaned_data.csv first")
        if df[col].nunique() <= 1:
            raise SystemExit(
                f"[ABORT] '{col}' is constant ({df[col].unique().tolist()}) - the "
                "lap/pit data did not make it into the build. Run fetch_lap_pace.py "
                "--finalize and build_training_data.py first; refusing to report a "
                "fake null result."
            )

    base_features = [f for f in train_model.FEATURES if f not in PACE_PIT_FEATURES]
    print(f"baseline contract: {len(base_features)} features | "
          f"pace/pit contract: {len(train_model.FEATURES)} features | "
          f"seeds {SEEDS}")

    results = {"base": [], "full": []}
    for seed in SEEDS:
        params = dict(train_model.RF_PARAMS, random_state=seed)
        original = train_model.FEATURES
        train_model.FEATURES = base_features
        try:
            rep = train_model.evaluate_walk_forward(df, params)
        finally:
            train_model.FEATURES = original
        results["base"].append(rep)
        rep2 = train_model.evaluate_walk_forward(df, params)
        results["full"].append(rep2)

    def agg(reps, key):
        vals = [r[key] for r in reps]
        return float(np.mean(vals)), float(np.std(vals))

    print(f"\n{'metric':24s} {'16-feature (prod)':>22s} {'18-feature (+pace/pit)':>24s}")
    for key, label in (
        ("overall_model_acc", "accuracy"),
        ("overall_points_recall", "points recall"),
        ("overall_podium_recall", "podium recall"),
    ):
        bm, bs = agg(results["base"], key)
        fm, fs = agg(results["full"], key)
        print(f"{label:24s} {bm:>10.1%} ±{bs:.1%} {fm:>12.1%} ±{fs:.1%}")

    acc_gap = np.mean([f["overall_model_acc"] - b["overall_model_acc"]
                       for b, f in zip(results["base"], results["full"])])
    pts_gap = np.mean([f["overall_points_recall"] - b["overall_points_recall"]
                       for b, f in zip(results["base"], results["full"])])
    per_seed_acc = [f["overall_model_acc"] >= b["overall_model_acc"]
                    for b, f in zip(results["base"], results["full"])]
    print(f"\nmean accuracy delta (18f - 16f): {acc_gap:+.1%} | "
          f"mean points-recall delta: {pts_gap:+.1%}")
    print(f"18f accuracy >= 16f on {sum(per_seed_acc)}/{len(SEEDS)} seeds")
    print("\nPer-seed accuracy (16f -> 18f):")
    for seed, b, f in zip(SEEDS, results["base"], results["full"]):
        print(f"  seed {seed}: {b['overall_model_acc']:.1%} -> {f['overall_model_acc']:.1%}"
              f" | points recall {b['overall_points_recall']:.0%} -> {f['overall_points_recall']:.0%}")

    print("\nFeature importances (mean across folds, 18-feature contract):")
    for name, imp in results["full"][0]["feature_importances"]:
        marker = "  <-- NEW" if name in PACE_PIT_FEATURES else ""
        print(f"  {name:32s} {imp:.2f}{marker}")


if __name__ == "__main__":
    main()
