# Race Intel refresh and evaluation

The scheduled `refresh.yml` workflow runs every six hours. It fetches only the
current season, merges it with preserved historical CSVs, fetches missing lap
and pit-stop rounds, then rebuilds training data, the canonical database, race
intelligence and replays. Raw API pages are cached; empty responses are never
trusted as permanent data. Current calendars expire after an hour and completed
result/qualifying/standings responses are rechecked after seven days.

`verify_intel_refresh.py` refuses publication unless the source results,
completed analysis and replay rounds agree. It also checks complete driver
fields and valid distributions. Tests run before the workflow commits. Failed
fetches or tests leave production's previous committed snapshot in place.
The existing workflow dispatches CI after its automated commit so the new
artifacts reach the Cloud Run backend even though a GitHub-token push does not
automatically trigger another workflow.

`datasets/refresh_status.json` records when an artifact set was validated and
its content digest. Its timestamp changes only when the artifacts or source
manifest change. The season endpoint exposes this as `refresh`; the UI labels
it **Snapshot built**, rather than implying a live prediction or deployment
timestamp. The official-results coverage check remains independent.

## Reproduce locally

Use a Python 3.11 virtual environment with `requirements.txt` and pytest.
From `model-notebooks`, using that environment's Python:

```sh
python fetch_jolpica_data.py --start-year 2026 --end-year 2026 --merge-output
python fetch_lap_pace.py --start-year 2026 --end-year 2026
python fetch_lap_pace.py --finalize
python build_training_data.py
python build_canonical.py
python race_intelligence.py --season 2026 --sims 2000
python lap_curves.py --season 2026 --sims 400
python verify_intel_refresh.py
python -m pytest tests/ -q
```

Copy `datasets/current_roster.json` to `flask-app/current_roster.json` after a
successful training-data build. Do not replace a production user database to
publish analysis artifacts. Review new driver identities and portrait coverage
when the serving roster changes. Completed lap/pit CSV rows are preserved;
upstream timing corrections require explicitly replacing the affected round
before refetching, rather than a routine incremental refresh.

## What the evaluation means

The `evaluation` object scores the **published pre-race scenario distributions**
on completed target-season races; it excludes lap replays. Model parameters and
the global-frequency baseline use strictly prior seasons. The starting-grid
baseline receives the same recorded grid, including penalties, as the model.
These are reproducible retrospective estimates, not predictions archived before
the races. Do not market these metrics as verified live forecasting performance.

Three exclusive classes are scored: P1–3, P4–10 and outside the top ten. Brier
and log loss measure probability quality; position MAE measures finishing-order
error. The same log-loss floor applies to every method. Podium reliability is
shown in fixed probability bands with entry counts. The paired Brier difference
versus historical rates includes a 1,000-resample interval, sampling whole races
to preserve driver dependence. Twenty races remain a small sample, and rule,
driver and team changes can limit generalization. No thresholds or model
parameters are tuned using these target-season outcomes.

Frontend checks cover personal-panel anonymous/missing/error states, request
cancellation, keyboard dialog recovery and axe accessibility structure rules.
Real contrast, touch behavior and screen-reader usability still require a
rendered-browser review; jsdom's automated audit excludes color contrast.
