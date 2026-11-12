"""Scores the published pre-race distributions; never scores replay curves.

All model parameters and global-rate baselines use seasons before the target
season. Grid baselines receive the same recorded starting grid as the model.
"""
import numpy as np


def evaluate(races, training_entries, season):
    if len(training_entries) and training_entries.year.max() >= season:
        raise ValueError('evaluation training data includes the target season')
    positions = training_entries.position.to_numpy()
    frequencies = np.array([(positions <= 3).mean(),
        ((positions >= 4) & (positions <= 10)).mean(), (positions > 10).mean()])
    rows, rounds = [], []
    for race in races:
        if race['status'] != 'raced':
            continue
        for driver in race['drivers']:
            actual = driver.get('actual_position')
            if actual is None or actual < 1:
                continue
            bucket = 0 if actual <= 3 else 1 if actual <= 10 else 2
            grid = driver['grid'] if driver['grid'] > 0 else len(race['drivers'])
            gb = 0 if grid <= 3 else 1 if grid <= 10 else 2
            rows.append((driver, bucket, grid, gb))
            rounds.append(race['round'])
    if not rows or not len(positions):
        return None
    actual = np.eye(3)[[row[1] for row in rows]]
    model = np.array([[r[0]['p_podium'], r[0]['p_points'], r[0]['p_out']] for r in rows])
    global_rates = np.tile(frequencies, (len(rows), 1))
    grid_probs = np.eye(3)[[r[3] for r in rows]]
    def score(p):
        clipped = np.clip(p, 1e-6, 1)
        clipped /= clipped.sum(axis=1, keepdims=True)
        return {'brier': round(float(((p - actual)**2).sum(axis=1).mean()), 4),
                'log_loss': round(float(-(actual * np.log(clipped)).sum(axis=1).mean()), 4)}
    model_error = np.abs([r[0]['expected_position'] - r[0]['actual_position'] for r in rows])
    grid_error = np.abs([r[2] - r[0]['actual_position'] for r in rows])
    delta = ((model - actual)**2).sum(axis=1) - ((global_rates - actual)**2).sum(axis=1)
    # Resample whole races, preserving the dependence between drivers.
    groups = [delta[np.array(rounds) == rnd] for rnd in sorted(set(rounds))]
    sums, sizes = np.array([g.sum() for g in groups]), np.array([len(g) for g in groups])
    indices = np.random.default_rng(42).integers(0, len(groups), (1000, len(groups)))
    differences = sums[indices].sum(axis=1) / sizes[indices].sum(axis=1)
    bins = []
    for i in range(5):
        mask = (model[:, 0] >= i / 5) & ((model[:, 0] < (i + 1) / 5) if i < 4 else (model[:, 0] <= 1))
        if mask.any():
            bins.append({'lower': i / 5, 'upper': (i + 1) / 5,
                'n': int(mask.sum()), 'predicted': round(float(model[mask, 0].mean()), 4),
                'observed': round(float(actual[mask, 0].mean()), 4)})
    return {'season': season, 'training_through_year': season - 1,
        'results_through_round': max(rounds), 'n_races': len(groups), 'n_entries': len(rows),
        'model': {**score(model), 'position_mae': round(float(model_error.mean()), 3)},
        'global_rates': score(global_rates),
        'starting_grid': {**score(grid_probs), 'position_mae': round(float(grid_error.mean()), 3)},
        'brier_delta_vs_global_95ci': [round(float(x), 4) for x in np.quantile(differences, [.025, .975])],
        'podium_calibration': bins,
        'limitations': 'Retrospective evaluation using recorded race grids, including penalties. Not an archived live forecast. Replay curves are excluded. Same-season outcomes are never used to fit the model or global-rate baseline. Small samples and regime changes limit generalization.'}
