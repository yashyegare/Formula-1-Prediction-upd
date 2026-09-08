"""
fetch_lap_pace.py

Resumable fetch of per-lap timing and pit-stop data from Jolpica-F1 for the
2018-2026 window, written incrementally so the multi-hour run survives
crashes and rate-limit blocks.

Why a fresh fetch: the legacy datasets/lap_times.csv and pit_stops.csv are
Ergast-era files keyed by numeric raceId (max 1033, coverage ending ~2020)
with no crosswalk to the year/round-keyed Jolpica pipeline anywhere in the
repo (id_maps.json holds only label-encoder maps), so the old files are
unjoinable to results.csv. This fetcher rebuilds both tables keyed by
(year, round, driverId) - directly joinable to everything else.

Cost: ~12 requests/race for laps (Jolpica caps pages at 100 timings,
~1100 timings/race) + 1 for pit stops ~= 2,400 requests total, i.e. hours
at the unauthenticated rate limit. Run it and walk away:

    python fetch_lap_pace.py                       # fetch all completed races
    python fetch_lap_pace.py --max-races 1         # smoke test
    python fetch_lap_pace.py --finalize            # concat fragments -> CSVs

Checkpointing: each race is stored as its own fragment file under
out/laps_fragments/ and out/pitstops_fragments/ (written atomically via
tmp+replace). A race is "done" iff its fragment exists, so a crash - even
between the API call and the write - can never duplicate or lose a race;
a re-run simply skips finished races and redoes the in-flight one. Raw API
pages are also cached under .jolpica_cache, so the redo costs no quota.
Run --finalize once fetching completes to produce lap_times_jolpica.csv and
pit_stops_jolpica.csv.

Race list comes from results.csv (year, round) - only races that actually
happened, so future rounds are never fetched.
"""

import argparse
import csv
import time
from pathlib import Path

import pandas as pd
import requests

from fetch_jolpica_data import paginate

LAPS_HEADER = ["year", "round", "lap", "position", "driverId", "time", "milliseconds"]
PITSTOPS_HEADER = ["year", "round", "driverId", "lap", "stop", "duration"]


def _time_to_ms(t):
    """'1:34.233' | '2:04.321' | '34.5' -> int milliseconds, None if unparseable."""
    if not t:
        return None
    try:
        parts = t.split(":")
        secs = float(parts[-1])
        mins = int(parts[-2]) if len(parts) > 1 else 0
        return int(round((mins * 60 + secs) * 1000))
    except (ValueError, IndexError):
        return None


def _frag_dir(out_dir, kind):
    d = Path(out_dir) / f"{kind}_fragments"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _frag_path(out_dir, kind, year, rnd):
    return _frag_dir(out_dir, kind) / f"{year}-{rnd:02d}.csv"


def _write_atomic(path, header, rows):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    tmp.replace(path)


def fetch_race_laps(session, cache_dir, year, rnd):
    """All per-lap timings for one race, flattened. [] if the race has none."""
    race_objects = paginate(session, cache_dir, f"{year}/{rnd}/laps")
    rows = []
    for race_obj in race_objects:
        for lap_obj in race_obj.get("Laps", []):
            lap_no = int(lap_obj["number"])
            for timing in lap_obj["Timings"]:
                rows.append([
                    year, rnd, lap_no,
                    int(timing["position"]) if timing.get("position") else None,
                    timing["driverId"], timing.get("time", ""),
                    _time_to_ms(timing.get("time", "")),
                ])
    return rows


def fetch_race_pitstops(session, cache_dir, year, rnd):
    """All pit stops for one race, flattened. [] if none."""
    race_objects = paginate(session, cache_dir, f"{year}/{rnd}/pitstops")
    rows = []
    for race_obj in race_objects:
        for s in race_obj.get("PitStops", []):
            rows.append([year, rnd, s["driverId"], int(s["lap"]), int(s["stop"]),
                         s.get("duration", "")])
    return rows


def finalize(out_dir):
    """Concat all fragments into the final joinable CSVs."""
    for kind, header in (("laps", LAPS_HEADER), ("pitstops", PITSTOPS_HEADER)):
        frags = sorted(_frag_dir(out_dir, kind).glob("*.csv"))
        frames = [pd.read_csv(f) for f in frags if f.stat().st_size > 0]
        combined = (pd.concat(frames, ignore_index=True) if frames
                    else pd.DataFrame(columns=header))
        out_file = Path(out_dir) / ("lap_times_jolpica.csv" if kind == "laps"
                                    else "pit_stops_jolpica.csv")
        combined.to_csv(out_file, index=False, lineterminator="\n")
        print(f"{out_file.name}: {len(combined)} rows from {len(frags)} races")


def main():
    ap = argparse.ArgumentParser(description="Resumable Jolpica laps + pitstops fetcher")
    ap.add_argument("--start-year", type=int, default=2018)
    ap.add_argument("--end-year", type=int, default=2026)
    ap.add_argument("--out", default="./datasets")
    ap.add_argument("--cache-dir", default="./.jolpica_cache")
    ap.add_argument("--max-races", type=int, default=0,
                    help="stop after N races (0 = no limit; smoke tests)")
    ap.add_argument("--finalize", action="store_true",
                    help="concat fragments into lap_times_jolpica.csv / pit_stops_jolpica.csv")
    args = ap.parse_args()

    Path(args.out).mkdir(parents=True, exist_ok=True)
    if args.finalize:
        finalize(args.out)
        return

    races = (pd.read_csv(Path(args.out) / "results.csv", usecols=["year", "round"])
               .drop_duplicates()
               .query(f"year >= {args.start_year} and year <= {args.end_year}")
               .sort_values(["year", "round"])
               .to_dict("records"))
    if args.max_races:
        races = races[:args.max_races]

    session = requests.Session()
    session.headers.update({"User-Agent": "f1-predictor-lap-pace/1.0"})

    already = sum(1 for r in races if _frag_path(args.out, "laps", int(r["year"]), int(r["round"])).exists())
    print(f"{len(races)} races to consider; {already} already fetched")

    n_rows = 0
    started = time.time()
    remaining = list(enumerate(races))
    pass_no = 0
    while remaining and pass_no < 5:
        pass_no += 1
        skipped = []
        for i, race in remaining:
            year, rnd = int(race["year"]), int(race["round"])

            laps_path = _frag_path(args.out, "laps", year, rnd)
            if not laps_path.exists():
                try:
                    rows = fetch_race_laps(session, args.cache_dir, year, rnd)
                except Exception as exc:
                    # multi-pass: a race that keeps failing is skipped and
                    # retried on the next pass (raw pages are cached, so
                    # the retry resumes for free); it only escalates if
                    # every pass fails
                    skipped.append((i, race))
                    print(f"[{i+1}/{len(races)}] {year}/{rnd}: laps failed ({exc}); will retry next pass")
                    continue
                _write_atomic(laps_path, LAPS_HEADER, rows)
                n_rows += len(rows)
                print(f"[{i+1}/{len(races)}] {year}/{rnd}: {len(rows)} lap rows")

            pits_path = _frag_path(args.out, "pitstops", year, rnd)
            if not pits_path.exists():
                try:
                    rows = fetch_race_pitstops(session, args.cache_dir, year, rnd)
                except Exception as exc:
                    skipped.append((i, race))
                    print(f"[{i+1}/{len(races)}] {year}/{rnd}: pit stops failed ({exc}); will retry next pass")
                    continue
                _write_atomic(pits_path, PITSTOPS_HEADER, rows)
                print(f"[{i+1}/{len(races)}] {year}/{rnd}: {len(rows)} pit stops")

        remaining = skipped
        if remaining:
            print(f"pass {pass_no} done: {len(remaining)} race(s) still failing, pausing 60s before retry")
            time.sleep(60)

    elapsed = time.time() - started
    print(f"done in {elapsed/60:.1f} min - {n_rows} new lap rows - "
          f"{len(remaining)} race(s) permanently failed"
          if remaining else
          f"done in {elapsed/60:.1f} min - {n_rows} new lap rows "
          f"(run --finalize to build the CSVs)")


if __name__ == "__main__":
    main()
