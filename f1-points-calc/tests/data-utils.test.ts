import { describe, it, expect } from 'vitest';
import { POINTS_SYSTEMS, getPointsForPositionWithSystem, DEFAULT_POINTS_SYSTEM } from '../src/data/pointsSystems';
import {
  SEASON_RULES,
  getSeasonRules,
  getSprintPoints,
  getFastestLapPoints,
  hasFastestLapPoint,
  getDefaultPointsSystem,
  getCanonicalTeamId,
} from '../src/data/seasonRules';
import { getContrastText, teamFillStyle } from '../src/utils/color';
import { getDriverLastName, getDriverDisplayName, selectDriversByIdMap, selectTeamsByIdMap } from '../src/store/selectors/dataSelectors';
import type { RootState } from '../src/store/index';
import type { Driver, Team } from '../src/types';

// ── Points systems ───────────────────────────────────────────────────────────

describe('pointsSystems', () => {
  it('exposes every documented system with a unique id', () => {
    const ids = Object.keys(POINTS_SYSTEMS);
    expect(new Set(ids).size).toBe(ids.length);
    ids.forEach(id => {
      expect(POINTS_SYSTEMS[id].id).toBe(id);
      expect(POINTS_SYSTEMS[id].name.length).toBeGreaterThan(0);
    });
  });

  it('covers all 20 positions in every system (no NaN lookups)', () => {
    for (const system of Object.values(POINTS_SYSTEMS)) {
      for (let pos = 1; pos <= 20; pos++) {
        const value = system.regular[pos];
        expect(typeof value, `${system.id} P${pos}`).toBe('number');
        expect(Number.isFinite(value), `${system.id} P${pos}`).toBe(true);
      }
    }
  });

  it('current system matches the real 25-18-15-…-1 table', () => {
    const table = POINTS_SYSTEMS['current'].regular;
    expect([table[1], table[2], table[3]]).toEqual([25, 18, 15]);
    expect(table[10]).toBe(1);
    expect(table[11]).toBe(0);
  });

  it('getPointsForPositionWithSystem falls back to the current system for unknown ids', () => {
    expect(getPointsForPositionWithSystem(1, 'does-not-exist')).toBe(25);
    expect(getPointsForPositionWithSystem(1, 'winner-takes-all')).toBe(100);
    // Non-integer / out-of-range positions score 0.
    expect(getPointsForPositionWithSystem(0, 'current')).toBe(0);
    expect(getPointsForPositionWithSystem(99, 'current')).toBe(0);
  });

  it('default system id points at a real system', () => {
    expect(POINTS_SYSTEMS[DEFAULT_POINTS_SYSTEM]).toBeDefined();
  });
});

// ── Season rules ─────────────────────────────────────────────────────────────

describe('seasonRules', () => {
  it('maps each era to its correct points system', () => {
    expect(getDefaultPointsSystem(1984)).toBe('1960s-1980s');
    expect(getDefaultPointsSystem(1997)).toBe('1991-2002');
    expect(getDefaultPointsSystem(2005)).toBe('2003-2009');
    expect(getDefaultPointsSystem(2010)).toBe('current'); // no override → current
    expect(getDefaultPointsSystem(2026)).toBe('current');
  });

  it('fastest lap exists only from 2019 onward (2025+ dropped it)', () => {
    expect(hasFastestLapPoint(2018)).toBe(false);
    expect(hasFastestLapPoint(2019)).toBe(true);
    expect(hasFastestLapPoint(2024)).toBe(true);
    expect(hasFastestLapPoint(2025)).toBe(false);
    expect(hasFastestLapPoint(2026)).toBe(false);
  });

  it('fastest lap eligibility is P1–P10', () => {
    expect(getFastestLapPoints(1, 2021)).toBe(1);
    expect(getFastestLapPoints(10, 2021)).toBe(1);
    expect(getFastestLapPoints(11, 2021)).toBe(0);
    expect(getFastestLapPoints(0, 2021)).toBe(0);
  });

  it('sprint tables follow the era format', () => {
    // Pre-2021: no sprints.
    expect(getSprintPoints(1, 2019)).toBe(0);
    // 2021: 3-2-1.
    expect([getSprintPoints(1, 2021), getSprintPoints(2, 2021), getSprintPoints(3, 2021)]).toEqual([3, 2, 1]);
    expect(getSprintPoints(4, 2021)).toBe(0);
    // 2022+: 8 down to 1 for P8.
    expect([getSprintPoints(1, 2023), getSprintPoints(8, 2023), getSprintPoints(9, 2023)]).toEqual([8, 1, 0]);
  });

  it('unknown seasons get modern defaults (2022+ sprints, no dropped scores)', () => {
    const rules = getSeasonRules(2030);
    expect(rules.sprintFormat).toBe('2022+');
    expect(rules.droppedScores).toBeUndefined();
    expect(rules.fastestLap).toBeUndefined();
  });

  it('dropped-scores era is exactly 1981–1990 with bestOf 11', () => {
    for (let year = 1981; year <= 1990; year++) {
      expect(SEASON_RULES[year]?.droppedScores, String(year)).toEqual({ bestOf: 11 });
    }
    expect(SEASON_RULES[1980]).toBeUndefined();
    expect(SEASON_RULES[1991]?.droppedScores).toBeUndefined();
  });

  it('1997 excludes Schumacher from driver standings only', () => {
    expect(SEASON_RULES[1997]?.excludedDrivers).toEqual(['michael_schumacher']);
  });

  it('2006 constructor alias folds mf1 into spyker_mf1', () => {
    expect(getCanonicalTeamId(2006, 'mf1')).toBe('spyker_mf1');
    expect(getCanonicalTeamId(2006, 'ferrari')).toBe('ferrari');
    expect(getCanonicalTeamId(2005, 'mf1')).toBe('mf1'); // alias only in 2006
  });
});

// ── Color helpers ────────────────────────────────────────────────────────────

describe('color utils', () => {
  it('picks black text on light backgrounds, white on dark', () => {
    expect(getContrastText('#ffffff')).toBe('#000000');
    expect(getContrastText('#000000')).toBe('#ffffff');
    expect(getContrastText('#e10600')).toBe('#ffffff'); // F1 red
  });

  it('expands 3-digit hex shorthand', () => {
    expect(getContrastText('#fff')).toBe('#000000');
    expect(getContrastText('#000')).toBe('#ffffff');
  });

  it('falls back to white for garbage/missing input', () => {
    expect(getContrastText(undefined)).toBe('#ffffff');
    expect(getContrastText(null)).toBe('#ffffff');
    expect(getContrastText('')).toBe('#ffffff');
    expect(getContrastText('red')).toBe('#ffffff');
    expect(getContrastText('#12345')).toBe('#ffffff'); // wrong length
  });

  it('teamFillStyle renders solid or two-tone split backgrounds', () => {
    expect(teamFillStyle({ color: '#dc0000' })).toEqual({ background: '#dc0000' });
    expect(teamFillStyle({ color: '#dc0000', secondaryColor: '#ffffff' })).toEqual({
      background: 'linear-gradient(to bottom, #dc0000 50%, #ffffff 50%)',
    });
    expect(teamFillStyle(undefined)).toEqual({ background: '#ccc' });
    expect(teamFillStyle(null)).toEqual({ background: '#ccc' });
    expect(teamFillStyle({})).toEqual({ background: '#ccc' });
  });
});

// ── Data selectors / name helpers ────────────────────────────────────────────

const rootWith = (drivers: Driver[], teams: Team[]) =>
  ({
    seasonData: { drivers, teams },
  }) as unknown as RootState;

describe('data selectors', () => {
  it('getDriverLastName capitalizes the last underscore segment', () => {
    expect(getDriverLastName('max_verstappen')).toBe('Verstappen');
    expect(getDriverLastName('michael_schumacher')).toBe('Schumacher');
    expect(getDriverLastName('alonso')).toBe('Alonso');
  });

  it('getDriverDisplayName uppercases the family name', () => {
    expect(getDriverDisplayName({ id: '', code: '', givenName: 'Max', familyName: 'Verstappen', nationality: '', team: '' })).toBe('VERSTAPPEN');
  });

  it('selectDriversByIdMap indexes drivers by id', () => {
    const drivers: Driver[] = [
      { id: 'norris', code: 'NOR', givenName: 'Lando', familyName: 'Norris', nationality: 'GBR', team: 'mclaren' },
      { id: 'piastri', code: 'PIA', givenName: 'Oscar', familyName: 'Piastri', nationality: 'AUS', team: 'mclaren' },
    ];
    const map = selectDriversByIdMap(rootWith(drivers, []));
    expect(map['norris']?.code).toBe('NOR');
    expect(Object.keys(map)).toHaveLength(2);
  });

  it('selectTeamsByIdMap strips the "F1 Team" suffix from names', () => {
    const teams: Team[] = [
      { id: 'mclaren', name: 'McLaren F1 Team', nationality: 'GBR', color: '#ff8000' },
      { id: 'racing', name: 'Racing Bullshawk', nationality: 'ITA', color: '#ff0000' },
    ];
    const map = selectTeamsByIdMap(rootWith([], teams));
    expect(map['mclaren']?.name).toBe('McLaren');
    expect(map['racing']?.name).toBe('Racing Bullshawk'); // only exact suffix stripped
  });
});
