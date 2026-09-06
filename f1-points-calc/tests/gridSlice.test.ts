import { describe, it, expect, beforeEach } from 'vitest';
import reducer, {
  moveDriver,
  placeDriver,
  resetGrid,
  toggleOfficialResults,
  clearPosition,
  fillRestOfSeason,
  clearEverything,
  setFastestLap,
} from '../src/store/slices/gridSlice';
import type { GridState, GridPosition, PastRaceResult } from '../src/types';

// ── Fixture helpers ──────────────────────────────────────────────────────────

const RACES = ['r1', 'r2'];
const POSITIONS_PER_RACE = 4;

function emptyGrid(): GridState {
  const positions: GridPosition[] = [];
  RACES.forEach(raceId => {
    for (let position = 1; position <= POSITIONS_PER_RACE; position++) {
      positions.push({ raceId, position, driverId: null, isOfficialResult: false });
    }
  });
  return { positions };
}

const slot = (state: GridState, raceId: string, position: number): GridPosition =>
  state.positions.find(p => p.raceId === raceId && p.position === position)!;

const driverAt = (state: GridState, raceId: string, position: number): string | null =>
  slot(state, raceId, position).driverId;

beforeEach(() => {
  // Guard against accidental fixture drift (state must start fully empty).
});

// ── placeDriver ──────────────────────────────────────────────────────────────

describe('gridSlice: placeDriver', () => {
  it('places a driver into an empty slot', () => {
    const state = reducer(emptyGrid(), placeDriver({ raceId: 'r1', position: 1, driverId: 'A' }));
    expect(driverAt(state, 'r1', 1)).toBe('A');
    expect(slot(state, 'r1', 1).isOfficialResult).toBe(false);
  });

  it('clears the same driver from other slots in the same race (no duplicates)', () => {
    let state = reducer(emptyGrid(), placeDriver({ raceId: 'r1', position: 1, driverId: 'A' }));
    state = reducer(state, placeDriver({ raceId: 'r1', position: 3, driverId: 'A' }));
    expect(driverAt(state, 'r1', 1)).toBeNull();
    expect(driverAt(state, 'r1', 3)).toBe('A');
  });

  it('does not touch the same driver in other races', () => {
    let state = reducer(emptyGrid(), placeDriver({ raceId: 'r1', position: 1, driverId: 'A' }));
    state = reducer(state, placeDriver({ raceId: 'r2', position: 2, driverId: 'A' }));
    expect(driverAt(state, 'r1', 1)).toBe('A');
    expect(driverAt(state, 'r2', 2)).toBe('A');
  });

  it('is a no-op for a nonexistent slot', () => {
    const state = reducer(emptyGrid(), placeDriver({ raceId: 'rX', position: 9, driverId: 'A' }));
    expect(state.positions.every(p => p.driverId === null)).toBe(true);
  });
});

// ── moveDriver ───────────────────────────────────────────────────────────────

describe('gridSlice: moveDriver', () => {
  it('moves a driver across races, clearing the source slot', () => {
    let state = reducer(emptyGrid(), placeDriver({ raceId: 'r1', position: 1, driverId: 'A' }));
    state = reducer(state, moveDriver({ driverId: 'A', toRaceId: 'r2', toPosition: 2, fromRaceId: 'r1', fromPosition: 1 }));
    expect(driverAt(state, 'r1', 1)).toBeNull();
    expect(driverAt(state, 'r2', 2)).toBe('A');
  });

  it('same-race move swaps the two drivers', () => {
    let state = reducer(emptyGrid(), placeDriver({ raceId: 'r1', position: 1, driverId: 'A' }));
    state = reducer(state, placeDriver({ raceId: 'r1', position: 3, driverId: 'C' }));
    state = reducer(state, moveDriver({ driverId: 'A', toRaceId: 'r1', toPosition: 3, fromRaceId: 'r1', fromPosition: 1 }));
    expect(driverAt(state, 'r1', 3)).toBe('A');
    expect(driverAt(state, 'r1', 1)).toBe('C'); // displaced driver lands in the source slot
  });

  it('moving into an empty slot leaves the source empty (no phantom swap)', () => {
    let state = reducer(emptyGrid(), placeDriver({ raceId: 'r1', position: 1, driverId: 'A' }));
    state = reducer(state, moveDriver({ driverId: 'A', toRaceId: 'r1', toPosition: 4, fromRaceId: 'r1', fromPosition: 1 }));
    expect(driverAt(state, 'r1', 4)).toBe('A');
    expect(driverAt(state, 'r1', 1)).toBeNull();
  });

  it('a move without a source (drop mode) clears the driver duplicates in the race', () => {
    let state = reducer(emptyGrid(), placeDriver({ raceId: 'r1', position: 1, driverId: 'A' }));
    state = reducer(state, moveDriver({ driverId: 'A', toRaceId: 'r1', toPosition: 2 }));
    expect(driverAt(state, 'r1', 1)).toBeNull();
    expect(driverAt(state, 'r1', 2)).toBe('A');
  });

  it('moving a driver marks the slot as a user prediction (official flag cleared)', () => {
    const pastResults: PastRaceResult = {
      r1: [{ driverId: 'A', teamId: 'ferrari', position: 1, fastestLap: false }],
    };
    let state = reducer(emptyGrid(), toggleOfficialResults({ show: true, pastResults }));
    expect(slot(state, 'r1', 1).isOfficialResult).toBe(true);
    state = reducer(state, moveDriver({ driverId: 'B', toRaceId: 'r1', toPosition: 1 }));
    expect(slot(state, 'r1', 1).isOfficialResult).toBe(false);
    expect(slot(state, 'r1', 1).driverId).toBe('B');
  });

  it('is a no-op when the target slot does not exist', () => {
    const state = reducer(emptyGrid(), moveDriver({ driverId: 'A', toRaceId: 'rX', toPosition: 1, fromRaceId: 'r1', fromPosition: 1 }));
    expect(state.positions.every(p => p.driverId === null)).toBe(true);
  });

  it('is a no-op when the source slot does not hold the moving driver', () => {
    let state = reducer(emptyGrid(), placeDriver({ raceId: 'r1', position: 1, driverId: 'A' }));
    state = reducer(state, moveDriver({ driverId: 'C', toRaceId: 'r1', toPosition: 2, fromRaceId: 'r1', fromPosition: 1 }));
    // Source held A, not C — the swap guard must refuse and C must not appear.
    expect(driverAt(state, 'r1', 2)).toBeNull();
    expect(driverAt(state, 'r1', 1)).toBe('A');
  });
});

// ── Official results ─────────────────────────────────────────────────────────

describe('gridSlice: toggleOfficialResults', () => {
  const pastResults: PastRaceResult = {
    r1: [
      { driverId: 'A', teamId: 'ferrari', position: 1, fastestLap: true },
      { driverId: 'B', teamId: 'ferrari', position: 2, fastestLap: false },
    ],
  };

  it('fills official results by matching position', () => {
    const state = reducer(emptyGrid(), toggleOfficialResults({ show: true, pastResults }));
    expect(driverAt(state, 'r1', 1)).toBe('A');
    expect(driverAt(state, 'r1', 2)).toBe('B');
    expect(slot(state, 'r1', 1).teamId).toBe('ferrari');
    expect(slot(state, 'r1', 1).hasFastestLap).toBe(true);
    expect(slot(state, 'r1', 1).isOfficialResult).toBe(true);
    // Slots without a past result stay untouched.
    expect(driverAt(state, 'r1', 3)).toBeNull();
    expect(driverAt(state, 'r2', 1)).toBeNull();
  });

  it('hiding clears only official-result slots', () => {
    let state = reducer(emptyGrid(), toggleOfficialResults({ show: true, pastResults }));
    state = reducer(state, placeDriver({ raceId: 'r1', position: 4, driverId: 'H' }));
    state = reducer(state, toggleOfficialResults({ show: false }));
    expect(driverAt(state, 'r1', 1)).toBeNull();
    expect(driverAt(state, 'r1', 2)).toBeNull();
    expect(driverAt(state, 'r1', 4)).toBe('H'); // user prediction survives
  });
});

// ── Clearing ─────────────────────────────────────────────────────────────────

describe('gridSlice: resetGrid / clearPosition / clearEverything', () => {
  it('resetGrid clears user predictions but keeps official results', () => {
    const pastResults: PastRaceResult = {
      r1: [{ driverId: 'A', teamId: 'ferrari', position: 1, fastestLap: false }],
    };
    let state = reducer(emptyGrid(), toggleOfficialResults({ show: true, pastResults }));
    state = reducer(state, placeDriver({ raceId: 'r2', position: 1, driverId: 'H' }));
    state = reducer(state, resetGrid());
    expect(driverAt(state, 'r1', 1)).toBe('A'); // official preserved
    expect(driverAt(state, 'r2', 1)).toBeNull(); // user prediction cleared
  });

  it('clearPosition refuses to clear an official result', () => {
    const pastResults: PastRaceResult = {
      r1: [{ driverId: 'A', teamId: 'ferrari', position: 1, fastestLap: false }],
    };
    let state = reducer(emptyGrid(), toggleOfficialResults({ show: true, pastResults }));
    state = reducer(state, clearPosition({ raceId: 'r1', position: 1 }));
    expect(driverAt(state, 'r1', 1)).toBe('A');
  });

  it('clearPosition clears a user prediction', () => {
    let state = reducer(emptyGrid(), placeDriver({ raceId: 'r1', position: 2, driverId: 'B' }));
    state = reducer(state, clearPosition({ raceId: 'r1', position: 2 }));
    expect(driverAt(state, 'r1', 2)).toBeNull();
  });

  it('clearEverything wipes official results too (full reset)', () => {
    const pastResults: PastRaceResult = {
      r1: [{ driverId: 'A', teamId: 'ferrari', position: 1, fastestLap: false }],
    };
    let state = reducer(emptyGrid(), toggleOfficialResults({ show: true, pastResults }));
    state = reducer(state, clearEverything());
    const occupied = state.positions.filter(p => p.driverId !== null || p.isOfficialResult || p.hasFastestLap);
    expect(occupied).toHaveLength(0);
  });
});

// ── fillRestOfSeason ─────────────────────────────────────────────────────────

describe('gridSlice: fillRestOfSeason', () => {
  it('fills the same driver+position from the start race to season end', () => {
    let state = reducer(emptyGrid(), fillRestOfSeason({ driverId: 'A', position: 2, startRaceId: 'r1', raceIds: RACES }));
    expect(driverAt(state, 'r1', 2)).toBe('A');
    expect(driverAt(state, 'r2', 2)).toBe('A');
  });

  it('starts filling at the given race (earlier races untouched)', () => {
    let state = reducer(emptyGrid(), fillRestOfSeason({ driverId: 'A', position: 2, startRaceId: 'r2', raceIds: RACES }));
    expect(driverAt(state, 'r1', 2)).toBeNull();
    expect(driverAt(state, 'r2', 2)).toBe('A');
  });

  it('skips official-result slots', () => {
    const pastResults: PastRaceResult = {
      r2: [{ driverId: 'B', teamId: 'ferrari', position: 2, fastestLap: false }],
    };
    let state = reducer(emptyGrid(), toggleOfficialResults({ show: true, pastResults }));
    state = reducer(state, fillRestOfSeason({ driverId: 'A', position: 2, startRaceId: 'r1', raceIds: RACES }));
    expect(driverAt(state, 'r1', 2)).toBe('A');
    expect(driverAt(state, 'r2', 2)).toBe('B'); // official result not overridden
  });

  it('is a no-op when the start race is not in the race list', () => {
    const state = reducer(emptyGrid(), fillRestOfSeason({ driverId: 'A', position: 1, startRaceId: 'rX', raceIds: RACES }));
    expect(state.positions.every(p => p.driverId === null)).toBe(true);
  });
});

// ── Fastest lap ──────────────────────────────────────────────────────────────

describe('gridSlice: setFastestLap', () => {
  it('is exclusive per race: assigning a new driver clears the previous holder', () => {
    let state = reducer(emptyGrid(), placeDriver({ raceId: 'r1', position: 1, driverId: 'A' }));
    state = reducer(state, placeDriver({ raceId: 'r1', position: 2, driverId: 'B' }));
    state = reducer(state, setFastestLap({ raceId: 'r1', driverId: 'A' }));
    expect(slot(state, 'r1', 1).hasFastestLap).toBe(true);
    state = reducer(state, setFastestLap({ raceId: 'r1', driverId: 'B' }));
    expect(slot(state, 'r1', 1).hasFastestLap).toBe(false);
    expect(slot(state, 'r1', 2).hasFastestLap).toBe(true);
  });

  it('null clears the flag from every slot in the race', () => {
    let state = reducer(emptyGrid(), placeDriver({ raceId: 'r1', position: 1, driverId: 'A' }));
    state = reducer(state, setFastestLap({ raceId: 'r1', driverId: 'A' }));
    state = reducer(state, setFastestLap({ raceId: 'r1', driverId: null }));
    expect(state.positions.filter(p => p.raceId === 'r1').every(p => !p.hasFastestLap)).toBe(true);
  });

  it('does not leak the flag to other races', () => {
    let state = reducer(emptyGrid(), placeDriver({ raceId: 'r1', position: 1, driverId: 'A' }));
    state = reducer(state, placeDriver({ raceId: 'r2', position: 1, driverId: 'A' }));
    state = reducer(state, setFastestLap({ raceId: 'r1', driverId: 'A' }));
    expect(slot(state, 'r2', 1).hasFastestLap).toBe(false);
  });
});
