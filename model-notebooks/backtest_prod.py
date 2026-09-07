"""
backtest_prod.py — verify the DEPLOYED model against real results.

For every round with complete quali + results data in a given year, this
sends each driver's actual qualifying position to the live /predictGrid
endpoint and scores the returned bucket against the real finishing bucket.
The trivial quali-bucket baseline is scored on the same rounds for context.

IMPORTANT caveat (stated so the number isn't misread): the endpoint serves
the CURRENT roster — standings, form and reliability as of the latest data
round. Backtesting PAST rounds therefore uses features that include
information from after those rounds. This validates that the deployed
artifact is the new model and behaves sanely; it is NOT a prospective
accuracy estimate (that's what walk-forward in train_model.py measures).

Usage:
    python backtest_prod.py --year 2026 --url https://f1-predictor-api-nddf.onrender.com
"""
import argparse
import time

import pandas as pd
import requests


def position_index(pos: int) -> int:
    if pos < 4:
        return 1
    if pos > 10:
        return 3
    return 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--url", default="https://f1-predictor-api-nddf.onrender.com")
    ap.add_argument("--datasets", default="./datasets")
    ap.add_argument("--sleep", type=float, default=0.3, help="seconds between API calls")
    args = ap.parse_args()

    results = pd.read_csv(f"{args.datasets}/results.csv")
    quali = pd.read_csv(f"{args.datasets}/qualifying.csv")

    r_y = results[results["year"] == args.year]
    q_y = quali[quali["year"] == args.year]
    rounds = sorted(set(r_y["round"]) & set(q_y["round"]))

    # quali position per (round, driverId); fall back to grid slot when a
    # driver has no quali classification (e.g. no time set in Q1)
    q_lookup = {(int(rnd), d): int(p) for rnd, d, p in
                zip(q_y["round"], q_y["driverId"], q_y["position"])}
    grid_lookup = {(int(rnd), d): int(g) for rnd, d, g in
                   zip(r_y["round"], r_y["driverId"], r_y["grid"])}

    session = requests.Session()
    rows = []
    for rnd in rounds:
        race_rows = r_y[r_y["round"] == rnd]
        race_name = race_rows["raceName"].iloc[0]
        for _, rr in race_rows.iterrows():
            key = (rnd, rr["driverId"])
            if key in q_lookup:
                qpos = q_lookup[key]
                src = "quali"
            elif key in grid_lookup and grid_lookup[key] > 0:
                qpos = grid_lookup[key]
                src = "grid-fallback"
            else:
                continue  # no meaningful pre-race slot known
            actual = position_index(int(rr["position"]))
            try:
                resp = session.post(
                    f"{args.url}/predictGrid",
                    json={"name": rr["driverName"], "round": race_name,
                          "qualifying_pos": qpos},
                    timeout=30,
                )
                pred = resp.json()[0] if resp.status_code == 200 else None
            except (requests.RequestException, KeyError, IndexError):
                pred = None
            if pred is None:
                print(f"  [WARN] {race_name} {rr['driverName']}: API failed")
                continue
            base = position_index(qpos)
            rows.append({"round": rnd, "race": race_name, "driver": rr["driverName"],
                         "qpos": qpos, "qsrc": src, "pred": int(pred),
                         "actual": actual, "base": base})
            time.sleep(args.sleep)

    df = pd.DataFrame(rows)
    if df.empty:
        print("No predictions collected — check endpoint/driver names.")
        return

    print(f"\n=== Backtest of LIVE endpoint vs real {args.year} results ===")
    print(f"({len(df)} driver-race predictions; qsrc fallbacks: "
          f"{(df['qsrc'] == 'grid-fallback').sum()})\n")
    per_round = df.groupby(["round", "race"]).agg(
        n=("pred", "size"),
        model_ok=("pred", lambda p: (p == df.loc[p.index, "actual"]).mean()),
        base_ok=("base", lambda b: (b == df.loc[b.index, "actual"]).mean()),
    )
    for (rnd, race), r in per_round.iterrows():
        mark = "  model>base" if r["model_ok"] > r["base_ok"] else ("  model<base" if r["model_ok"] < r["base_ok"] else "  tie")
        print(f"  r{rnd:02d} {race:28s} n={int(r['n']):2d}  model {r['model_ok']:5.1%}  baseline {r['base_ok']:5.1%}{mark}")

    model_acc = (df["pred"] == df["actual"]).mean()
    base_acc = (df["base"] == df["actual"]).mean()
    pod = df[df["actual"] == 1]
    pod_recall = (pod["pred"] == 1).mean() if len(pod) else float("nan")
    print(f"\nOverall: model {model_acc:.1%}  |  quali-bucket baseline {base_acc:.1%}"
          f"  |  podium recall {pod_recall:.0%}")
    print("Caveat: endpoint serves the CURRENT roster (post-latest-round standings/form),")
    print("so past rounds see future features — sanity check, not a prospective estimate.")


if __name__ == "__main__":
    main()
