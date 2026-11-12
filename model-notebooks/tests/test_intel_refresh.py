import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_jolpica_data as fetch
from fetch_lap_pace import finalize, LAPS_HEADER, PITSTOPS_HEADER
from intel_evaluation import evaluate
from verify_intel_refresh import verify
import race_simulator as rs


def test_empty_cached_results_are_refetched(tmp_path, monkeypatch):
    (tmp_path / '2026_21_results.json_limit100.json').write_text(json.dumps({'MRData': {'total': '0'}}))
    data = {'MRData': {'total': '22'}}
    response = SimpleNamespace(status_code=200, json=lambda: data, raise_for_status=lambda: None)
    calls = []
    session = SimpleNamespace(get=lambda *args, **kwargs: calls.append(args) or response)
    monkeypatch.setattr(fetch.time, 'sleep', lambda _: None)
    assert fetch.get(session, tmp_path, '2026/21/results.json', {'limit': 100}) == data
    assert len(calls) == 1


def test_finalize_preserves_history_and_deduplicates_new_fragments(tmp_path):
    for kind, filename, header in [('laps', 'lap_times_jolpica.csv', LAPS_HEADER),
                                   ('pitstops', 'pit_stops_jolpica.csv', PITSTOPS_HEADER)]:
        old = {k: 1 for k in header}
        old.update(year=2025, driverId='old')
        pd.DataFrame([old]).to_csv(tmp_path / filename, index=False)
        folder = tmp_path / f'{kind}_fragments'
        folder.mkdir()
        new = {**old, 'year': 2026, 'driverId': 'new'}
        pd.DataFrame([new]).to_csv(folder / '2026-01.csv', index=False)
    finalize(tmp_path)
    finalize(tmp_path)
    assert list(pd.read_csv(tmp_path / 'lap_times_jolpica.csv').year) == [2025, 2026]


def test_global_baseline_is_fit_separately_in_each_temporal_fold():
    rows = []
    for year, position in [(2024, 1), (2025, 11), (2026, 11)]:
        for rnd in range(1, 4):
            rows.append(dict(year=year, round=rnd, driverId='d', constructorId='t', grid=1, position=position, is_dnf=0))
    probs, _ = rs.backtest(pd.DataFrame(rows), range(2025, 2027), 20, 42)
    assert set(probs.loc[probs.year == 2025, 'p_podium_gr']) == {1.0}
    assert set(probs.loc[probs.year == 2026, 'p_podium_gr']) == {.5}


def test_evaluation_excludes_future_and_rejects_training_leakage():
    training = pd.DataFrame({'year': [2025] * 3, 'position': [1, 5, 15]})
    driver = dict(actual_position=1, grid=1, expected_position=1, p_podium=1, p_points=0, p_out=0)
    races = [dict(status='raced', round=1, drivers=[driver]), dict(status='scheduled', round=2, drivers=[driver])]
    report = evaluate(races, training, 2026)
    assert report['n_entries'] == 1 and report['model']['brier'] == 0
    assert sum(b['n'] for b in report['podium_calibration']) == 1
    assert report['brier_delta_vs_global_95ci'][1] < 0
    training['year'] = 2026
    with pytest.raises(ValueError):
        evaluate(races, training, 2026)


def test_publish_guard_rejects_missing_round(tmp_path):
    (tmp_path / 'results.csv').write_text('year,round,driverId\n2026,1,d\n2026,2,d\n')
    (tmp_path / 'race_intel.json').write_text(json.dumps({'season': 2026, 'races': [{'round': 1, 'status': 'raced'}]}))
    (tmp_path / 'lap_curves.json').write_text(json.dumps({'season': 2026, 'races': [{'round': 1}]}))
    with pytest.raises(ValueError, match='Incomplete refresh'):
        verify(tmp_path)
    assert not (tmp_path / 'refresh_status.json').exists()


def test_publish_guard_rejects_regression_even_when_artifacts_agree(tmp_path):
    (tmp_path / 'results.csv').write_text('year,round,driverId\n2026,1,d\n')
    (tmp_path / 'race_intel.json').write_text(json.dumps({'season': 2026, 'races': [{'round': 1, 'status': 'raced'}]}))
    (tmp_path / 'lap_curves.json').write_text(json.dumps({'season': 2026, 'races': [{'round': 1}]}))
    (tmp_path / 'refresh_status.json').write_text(json.dumps({'season': 2026, 'results_through_round': 2}))
    with pytest.raises(ValueError, match='regress'):
        verify(tmp_path)
