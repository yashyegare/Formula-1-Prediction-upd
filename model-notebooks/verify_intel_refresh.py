"""Fail closed before publishing stale/incomplete serving artifacts."""
import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def verify(directory):
    directory = Path(directory)
    intel = json.loads((directory / 'race_intel.json').read_text(encoding='utf-8'))
    curves = json.loads((directory / 'lap_curves.json').read_text(encoding='utf-8'))
    year = intel['season']
    with (directory / 'results.csv').open(encoding='utf-8') as stream:
        rows = [r for r in csv.DictReader(stream) if int(r['year']) == year]
    expected = {int(r['round']) for r in rows}
    built = {r['round'] for r in intel['races'] if r['status'] == 'raced'}
    replay = {r['round'] for r in curves['races']}
    if not expected or built != expected or curves['season'] != year or replay != expected:
        raise ValueError(f'Incomplete refresh: results={sorted(expected)}, analysis={sorted(built)}, replay={sorted(replay)}')
    target = directory / 'refresh_status.json'
    old = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
    if old.get('season') == year and max(expected) < old.get('results_through_round', 0):
        raise ValueError('Refresh would regress previously published coverage')
    for race in intel['races']:
        ids = [d['driverId'] for d in race['drivers']]
        if len(ids) != len(set(ids)) or not ids:
            raise ValueError('Empty or duplicate race entries')
        if race['status'] == 'raced':
            source = {r['driverId'] for r in rows if int(r['round']) == race['round']}
            if set(ids) != source:
                raise ValueError(f'Incomplete field in round {race["round"]}')
        for d in race['drivers']:
            p = [d[k] for k in ('p_podium', 'p_points', 'p_out')]
            if not all(0 <= x <= 1 for x in p) or abs(sum(p) - 1) > .005:
                raise ValueError('Invalid probability distribution')
    digest = hashlib.sha256(b''.join((directory / name).read_bytes()
        for name in ('race_intel.json', 'lap_curves.json', 'build_manifest.json'))).hexdigest()
    if old.get('artifact_sha256') != digest:
        status = {'season': year, 'results_through_round': max(expected),
            'replay_through_round': max(replay), 'artifact_sha256': digest,
            'published_at': datetime.now(timezone.utc).isoformat()}
        target.write_text(json.dumps(status, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f'Validated {len(built)} complete races and replays, through R{max(expected)}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--datasets', default='datasets')
    verify(parser.parse_args().datasets)
