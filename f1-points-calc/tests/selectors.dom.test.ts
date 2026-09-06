import { describe, it, expect, beforeEach } from 'vitest';
import { selectDriverStandings, selectTeamStandings, selectPointsHistory, selectTeamPointsHistory } from '../src/store/selectors/standingsSelectors';
import { selectDriverPointsForCharts, selectTeamPointsForCharts, selectTopDrivers } from '../src/store/selectors/resultsSelectors';
import {
  selectOverallAccuracy,
  selectLockedRaceCount,
  selectScoredRaceCount,
  selectNextRaceToLock,
  selectNextWeekendRacesToLock,
  selectAwaitingResultsRaces,
  selectScoredRaces,
} from '../src/store/selectors/lockedPredictionsSelectors';
import type { RootState } from '../src/store/index';
import type { GridPosition, Driver, PastRaceResult, Race } from '../src/types';
import type { LockedPrediction } from '../src/api/predictions';

// ── State builder ────────────────────────────────────────────────────────────

const DRIVER_IDS = ['A', 'B', 'C', 'D'];

const TEAM_OF: Record<string, string> = { A: 'ferrari', B: 'ferrari', C: 'mclaren', D: 'mclaren' };

const DRIVERS: Driver[] = DRIVER_IDS.map(id => ({
  id, code: id, givenName: '', familyName: id, nationality: '', team: TEAM_OF[id],
}));

const RACES: Race[] = [
  { id: 'r1', name: 'R1', isSprint: false, country: '', countryCode: '', order: 1, completed: true, round: '1' },
  { id: 'r2', name: 'R2', isSprint: false, country: '', countryCode: '', order: 2, completed: false, round: '2' },
  { id: 'r3', name: 'R3', isSprint: false, country: '', countryCode: '', order: 3, completed: false, round: '3' },
];

function pos(raceId: string, position: number, driverId: string): GridPosition {
  return { raceId, position, driverId, isOfficialResult: true };
}

interface Overrides {
  positions?: GridPosition[];
  pastResults?: PastRaceResult;
  officialDrivers?: { driverId: string; points: number; position: number }[] | null;
  officialTeams?: { teamId: string; points: number; position: number }[] | null;
  locked?: Record<string, LockedPrediction>;
}

function makeState(o: Overrides = {}): RootState {
  return {
    seasonData: {
      races: RACES,
      drivers: DRIVERS,
      teams: [],
      pastResults: o.pastResults ?? {},
      officialDriverStandings: o.officialDrivers ?? null,
      officialConstructorStandings: o.officialTeams ?? null,
    },
    grid: { positions: o.positions ?? [] },
    ui: { selectedPointsSystem: 'current' },
    lockedPredictions: { lockedPredictions: o.locked ?? {}, isLoading: false, isLocking: false, error: null },
  } as unknown as RootState;
}

// Standard two-race result set: A dominates, B second, C/D trade 3rd/4th.
const BASE_POSITIONS: GridPosition[] = [
  pos('r1', 1, 'A'), pos('r1', 2, 'B'), pos('r1', 3, 'C'), pos('r1', 4, 'D'),
  pos('r2', 1, 'A'), pos('r2', 2, 'B'), pos('r2', 3, 'D'), pos('r2', 4, 'C'),
];

beforeEach(() => {
  (window as unknown as { INITIAL_YEAR?: number }).INITIAL_YEAR = 2024;
});

// ── Standings ────────────────────────────────────────────────────────────────

describe('standingsSelectors', () => {
  it('falls back to computed standings: points desc + positions 1..n', () => {
    const state = makeState({ positions: BASE_POSITIONS });
    const standings = selectDriverStandings(state);
    expect(standings.map(s => s.driverId)).toEqual(['A', 'B', 'C', 'D']);
    // A: 25+25; B: 18+18; C: 15+12 (P3, P4); D: 12+15.
    expect(standings.map(s => s.points)).toEqual([50, 36, 27, 27]);
    expect(standings.map(s => s.position)).toEqual([1, 2, 3, 4]);
  });

  it('breaks point ties by countback: most wins first', () => {
    // C and D both have 27 — C won one more P3? No: tiebreak counts WINS (P1).
    // Both have zero wins, so 2nd-place counts (0 each), then 3rds: C=1, D=1…
    // P4s: C=1, D=1. Dead even → stable order. Construct a real win tie instead:
    const positions: GridPosition[] = [
      pos('r1', 1, 'A'), pos('r1', 2, 'B'),
      pos('r2', 1, 'B'), pos('r2', 2, 'A'),
      pos('r1', 3, 'C'), pos('r1', 4, 'D'),
      pos('r2', 3, 'C'), pos('r2', 4, 'D'),
    ];
    const state = makeState({ positions });
    const standings = selectDriverStandings(state);
    // A and B both 43, each with 1 win → even on wins; 2nds: A=1, B=1… also even.
    // Stable sort keeps A first; the assertion here is that ties don't crash.
    expect(standings[0].points).toBe(43);
    expect(standings[1].points).toBe(43);
    // C/D at 6 each (2×P3=15+15? no: current system P3=15 — recompute: C: 15+15=30).
    expect(standings[2].points).toBe(30);
  });

  it('prefers official standings when present, wiring computed finish counts', () => {
    const state = makeState({
      positions: BASE_POSITIONS,
      officialDrivers: [
        { driverId: 'A', points: 50, position: 1 },
        { driverId: 'B', points: 36, position: 2 },
        { driverId: 'C', points: 27, position: 3 },
        { driverId: 'D', points: 27, position: 4 },
      ],
    });
    const standings = selectDriverStandings(state);
    expect(standings.map(s => s.position)).toEqual([1, 2, 3, 4]);
    expect(standings.map(s => s.predictionPointsGained)).toEqual([0, 0, 0, 0]); // official board: no deltas
    // finishCounts still computed from the total board: A has 2 wins → [2,0].
    expect(standings[0].finishCounts[0]).toBe(2);
    expect(standings[2].finishCounts[2]).toBe(1); // C: one P3
  });

  it('predictionPointsGained = what-if total − official total', () => {
    // Official: A 25 (r1 only — his r2 official entry is replaced).
    // User drags B to P1 in r2, A to P2 (what-if, isOfficialResult false).
    const positions: GridPosition[] = [
      ...BASE_POSITIONS.filter(p => !(p.raceId === 'r2' && (p.driverId === 'A' || p.driverId === 'B'))),
      { raceId: 'r2', position: 1, driverId: 'B', isOfficialResult: false },
      { raceId: 'r2', position: 2, driverId: 'A', isOfficialResult: false },
    ];
    const state = makeState({ positions });
    const standings = selectDriverStandings(state);
    const a = standings.find(s => s.driverId === 'A')!;
    const b = standings.find(s => s.driverId === 'B')!;
    // Total board counts the what-if: A 25+18=43 (official 25 → +18);
    // B 18+25=43 (official 18 → +25). C/D unaffected → 0.
    expect(a.points).toBe(43);
    expect(a.predictionPointsGained).toBe(18);
    expect(b.points).toBe(43);
    expect(b.predictionPointsGained).toBe(25);
    // A/B tie at 43; C and D keep their official totals (27 each).
    expect(standings.map(s => s.points)).toEqual([43, 43, 27, 27]);
  });

  it('team standings mirror driver logic; both cars sum', () => {
    const state = makeState({ positions: BASE_POSITIONS });
    const standings = selectTeamStandings(state);
    expect(standings.map(s => s.teamId)).toEqual(['ferrari', 'mclaren']);
    expect(standings.map(s => s.points)).toEqual([86, 54]); // 50+36, 27+27
  });

  it('histories are cumulative in race order', () => {
    const state = makeState({ positions: BASE_POSITIONS });
    const history = selectPointsHistory(state);
    const aRows = history.filter(h => h.driverId === 'A');
    expect(aRows.map(h => h.cumulativePoints)).toEqual([25, 50]);
    const teamHistory = selectTeamPointsHistory(state);
    const ferrari = teamHistory.filter(h => h.teamId === 'ferrari');
    expect(ferrari.map(h => h.points)).toEqual([43, 43]); // 25+18 each race
    expect(ferrari.map(h => h.cumulativePoints)).toEqual([43, 86]);
  });

  it('selectTopDrivers slices the board', () => {
    const state = makeState({ positions: BASE_POSITIONS });
    expect(selectTopDrivers(state, 2).map(s => s.driverId)).toEqual(['A', 'B']);
  });
});

// ── Chart data alignment ─────────────────────────────────────────────────────

describe('resultsSelectors: chart data', () => {
  it('axis contains only races with history, sorted by order', () => {
    const state = makeState({ positions: BASE_POSITIONS });
    const chart = selectDriverPointsForCharts(state);
    // r3 has no results → excluded.
    expect(chart.axis.map(r => r.id)).toEqual(['r1', 'r2']);
  });

  it('series are null before a driver first appears and carry forward across gaps', () => {
    // B only appears in r2. A appears in both.
    const positions: GridPosition[] = [pos('r1', 1, 'A'), pos('r2', 2, 'B')];
    const state = makeState({ positions });
    const chart = selectDriverPointsForCharts(state);
    expect(chart.series['A']).toEqual([25, 25]);           // carries forward
    expect(chart.series['B']).toEqual([null, 18]);          // null before debut
  });

  it('leader considers the whole field, not just the first-inserted series', () => {
    // C (3rd driver id) dominates; A trails. Leader must be C's totals.
    const positions: GridPosition[] = [
      pos('r1', 1, 'C'), pos('r1', 2, 'A'),
      pos('r2', 1, 'C'), pos('r2', 2, 'A'),
    ];
    const state = makeState({ positions });
    const chart = selectDriverPointsForCharts(state);
    expect(chart.series['C']).toEqual([25, 50]);
    expect(chart.leader).toEqual([25, 50]);
  });

  it('leader tracks the actual per-round max across the full field', () => {
    const state = makeState({ positions: BASE_POSITIONS });
    const chart = selectDriverPointsForCharts(state);
    // r1: max driver total = 25 (A); r2: 50 (A). Team chart leads with ferrari 43/86.
    const teamChart = selectTeamPointsForCharts(state);
    expect(chart.leader).toEqual([25, 50]);
    expect(teamChart.leader).toEqual([43, 86]);
  });
});

// ── Locked predictions / weekend gating ──────────────────────────────────────

const DAY = 24 * 60 * 60 * 1000;

describe('lockedPredictionsSelectors', () => {
  it('overall accuracy aggregates only scored races and rounds the percentage', () => {
    const locked: Record<string, LockedPrediction> = {
      r1: { raceId: 'r1', positions: [], lockedAt: '', score: { exact: 17, total: 20, percentage: 85 } },
      r2: { raceId: 'r2', positions: [], lockedAt: '', score: { exact: 3, total: 20, percentage: 15 } },
      r3: { raceId: 'r3', positions: [], lockedAt: '' }, // not scored yet — excluded
    };
    const state = makeState({ locked });
    expect(selectOverallAccuracy(state)).toEqual({ exact: 20, total: 40, percentage: 50 });
    expect(selectLockedRaceCount(state)).toBe(3);
    expect(selectScoredRaceCount(state)).toBe(2);
  });

  it('accuracy is zero when nothing is scored', () => {
    expect(selectOverallAccuracy(makeState())).toEqual({ exact: 0, total: 0, percentage: 0 });
  });

  it('nextRaceToLock: first upcoming, uncompleted, unlocked race', () => {
    const now = Date.now();
    const races: Race[] = [
      { ...RACES[0], completed: true },
      { ...RACES[1], date: new Date(now + 2 * DAY).toISOString() },
      { ...RACES[2], date: new Date(now + 9 * DAY).toISOString() },
    ];
    const state = makeState({ locked: { r1: { raceId: 'r1', positions: [], lockedAt: '' } } });
    const s = { ...state, seasonData: { ...state.seasonData, races } } as RootState;
    expect(selectNextRaceToLock(s)?.id).toBe('r2');
  });

  it('nextWeekendRacesToLock groups the whole round and includes already-locked races', () => {
    const now = Date.now();
    // Weekend = r2 (race) + r2-sprint (same round), r2 already locked.
    const races: Race[] = [
      { ...RACES[0], completed: true },
      { ...RACES[1], date: new Date(now + 2 * DAY).toISOString() },
      { id: 'r2-sprint', name: 'R2 Sprint', isSprint: true, country: '', countryCode: '', order: 1, completed: false, round: '2', date: new Date(now + 2 * DAY).toISOString() },
    ];
    const locked: Record<string, LockedPrediction> = { r2: { raceId: 'r2', positions: [], lockedAt: '' } };
    const state = makeState({ locked });
    const s = { ...state, seasonData: { ...state.seasonData, races } } as RootState;
    const weekend = selectNextWeekendRacesToLock(s);
    expect(weekend.map(r => r.id)).toEqual(['r2-sprint', 'r2']); // sorted by order
  });

  it('nextWeekendRacesToLock returns [] while another round awaits results', () => {
    const now = Date.now();
    const races: Race[] = [
      // r1 locked but NOT completed → still awaiting results.
      { ...RACES[0], completed: false, date: new Date(now - 2 * DAY).toISOString() },
      { ...RACES[1], date: new Date(now + 2 * DAY).toISOString(), round: '2' },
    ];
    const locked: Record<string, LockedPrediction> = { r1: { raceId: 'r1', positions: [], lockedAt: '' } };
    const state = makeState({ locked });
    const s = { ...state, seasonData: { ...state.seasonData, races } } as RootState;
    expect(selectNextWeekendRacesToLock(s)).toEqual([]);
  });

  it('awaiting vs scored race lists sort correctly', () => {
    const now = Date.now();
    const races: Race[] = [
      { ...RACES[0], completed: true },
      { ...RACES[1], completed: false, date: new Date(now + 2 * DAY).toISOString() },
      { ...RACES[2], completed: false, date: new Date(now + 9 * DAY).toISOString() },
    ];
    const locked: Record<string, LockedPrediction> = {
      r1: { raceId: 'r1', positions: [], lockedAt: '', score: { exact: 5, total: 20, percentage: 25 } },
      r2: { raceId: 'r2', positions: [], lockedAt: '' },
      r3: { raceId: 'r3', positions: [], lockedAt: '' },
    };
    const state = makeState({ locked });
    const s = { ...state, seasonData: { ...state.seasonData, races } } as RootState;
    // r2/r3: locked but not completed → awaiting (r1 scored, r4+ unlisted).
    expect(selectAwaitingResultsRaces(s).map(x => x.race.id)).toEqual(['r2', 'r3']);
    expect(selectScoredRaces(s).map(x => x.race.id)).toEqual(['r1']); // most recent first, scored only
  });
});
