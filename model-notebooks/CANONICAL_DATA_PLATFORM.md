# Canonical F1 data platform (Phase 2)

One typed, validated, reproducible database under `datasets/f1_canonical.db`,
built entirely from the committed CSVs by `build_canonical.py` against the
schema in `canonical_schema.sql`.

```
datasets/*.csv ──▶ build_canonical.py ──▶ f1_canonical.db (STRICT SQLite)
                        │                      10 tables + 5 views
                        └──▶ build_manifest.json (sha256 + row counts + deltas)
```

## Design contracts (each is a decision, not a preference)

1. **Natural keys over surrogates.** `(year, round)` identifies a race,
   `(year, round, driverId)` an entry — the exact keys every existing
   artifact (cleaned_data.csv, backtest_wf.py, error_decomposition.py)
   already joins on. The Phase-1 key-collision bug (a quali lookup keyed
   without year) is structurally impossible in this schema: every fact
   carries `year+round` and PRIMARY KEYs enforce it.
2. **STRICT SQLite + CHECK + FK.** Types are real, causes and buckets are
   constrained, every fact references `fact_race`. SQLite keeps it runnable
   everywhere; the types map 1:1 to PostgreSQL when the project outgrows it
   (window-function views rewrite to `PERCENTILE_CONT` there).
3. **Status as a first-class dimension.** `dim_status` derives from the
   vocabulary ACTUALLY present in results.csv (deterministic IDs by sorted
   text), with `is_dnf`/`dnf_cause` from the ONE shared taxonomy in
   `build_training_data`. The legacy Ergast-era `status.csv` is no longer
   consumed — its vocabulary diverged from Jolpica's ("Cooling system",
   "Debris", "Illness" have no row there). A new upstream status changes
   the dimension and the manifest — visible in CI, not silent.
4. **Views, not copies.** The Phase-1 evidence quantities exist once, in
   SQL: field-median laps, the >1.20x slow-lap flag, SC exposure, running
   position gains vs grid slot, point-in-time standings with
   share-of-leader ratios and prior-snapshot lookups (round 1 falls through
   to the previous season's final — same ordering contract as
   `_attach_prior_standings`). Tests cross-check these against the pandas
   implementations row-for-row.

## Real-data findings (upstream dirt the gates caught)

- **Penalty-tied qualifying classifications are real.** 6 races (2023–2025,
  e.g. Pérez/Bottas both P15 at 2023 Spa, Sainz/Albon both P10 at 2024
  Monza) carry duplicate quali positions. The uniqueness gate was relaxed
  for qualifying only — results keep the strict DNF-safe order contract
  the training target depends on.
- **`positionOrder` carries TEXT markers** (`"R"`, `"D"`) in Ergast-era
  rows; coerced to numeric with markers → NULL (the DNF-safe order lives
  in `position`).
- **2026 statuses are generic** ("Retired", "Did not start"), so
  `dnf_cause = 'other'` for the whole season — the Phase-1 blocker, now
  visible as a queryable data condition (`test_2026_statuses_are_generic`
  pins it) instead of folklore.

## What the build enforces (validation gates, pre-insert)

Duplicate natural keys, orphan race/driver/constructor references,
duplicate results positions within a race, and results statuses missing
from the derived dimension all ABORT the build before anything is written.
Post-insert: `PRAGMA foreign_key_check` + `integrity_check` must be clean.

## Reproduce

```bash
cd model-notebooks
python build_canonical.py          # → datasets/f1_canonical.db + build_manifest.json
python -m pytest tests/ -q        # 79 tests (24 decomposition, 16 canonical, 39 ML)
```

The manifest (sorted keys, fixed separators, no timestamps; source hashes
over repo-canonical bytes — CRLF normalized to LF, so the baseline is
identical regardless of the checkout's line endings) is byte-stable
across rebuilds and platforms — a CI job can byte-compare the committed
manifest against a fresh build and fail on any source drift, the same
contract the ML pipeline applies to `cleaned_data.csv` and
`current_roster.json`.

## Row counts (current build)

| table | rows | table | rows |
|---|---:|---|---:|
| fact_lap | 201,811 | fact_championship_snapshot | 5,687 |
| fact_race_entry | 3,700 | dim_status | 54 |
| fact_quali_entry | 3,694 | dim_driver | 44 |
| fact_race | 196 | dim_constructor | 19 |
| fact_pit_stop | 6,376 | dim_circuit | 34 |

Views: `v_race_lap_evidence`, `v_race_sc_exposure`,
`v_running_position_gains`, `v_driver_race_evidence`,
`v_standings_pit`, `v_race_entry_outcome`.

Verified against the pandas pipeline: **bucket agreement 1.0 row-for-row**
on the overlapping active-grid universe; 2026 baseline accuracy from the
DB = 0.686, matching the documented number exactly.

## Not done on purpose

- No dbt/warehouse: at ~222k rows, STRICT SQLite + gates + manifest gives
  the same guarantees without new infrastructure. The schema is
  PostgreSQL-ready when a second ingestion source (OpenF1, weather)
  actually arrives.
- No surrogate keys / SCD2 dimensions: the natural keys ARE the contract
  with the existing ML artifacts; adding surrogates now would break that
  for zero benefit at this scale.
- `status.csv` remains on disk as Ergast lineage but is intentionally
  unconsumed.
