import { createSelector } from '@reduxjs/toolkit';
import type { RootState } from '../index';
import type { DriverStanding, TeamStanding, PointsHistory, TeamPointsHistory } from '../../types';
import { getActiveSeason } from '../../utils/constants';
import { computeRawPoints } from './computeStandings';
import type { CalculatedResults } from './computeStandings';

const selectGridPositions = (state: RootState) => state.grid.positions;
const selectRaces = (state: RootState) => state.seasonData.races;
const selectDrivers = (state: RootState) => state.seasonData.drivers;
const selectPastResults = (state: RootState) => state.seasonData.pastResults;
const selectPointsSystem = (state: RootState) => state.ui.selectedPointsSystem;
const selectOfficialDriverStandings = (state: RootState) => state.seasonData.officialDriverStandings;
const selectOfficialConstructorStandings = (state: RootState) => state.seasonData.officialConstructorStandings;

const compareByCountback = (finishesA: number[], finishesB: number[]): number => {
  const maxLength = Math.max(finishesA.length, finishesB.length);
  for (let i = 0; i < maxLength; i++) {
    const countA = finishesA[i] || 0;
    const countB = finishesB[i] || 0;
    if (countA !== countB) {
      return countB - countA;
    }
  }
  return 0;
};

const selectCalculatedPoints = createSelector(
  [selectGridPositions, selectRaces, selectDrivers, selectPastResults, selectPointsSystem],
  (positions, races, drivers, pastResults, pointsSystem): { official: CalculatedResults; total: CalculatedResults } => {
    const season = getActiveSeason();
    const base = { positions, races, drivers, pastResults, pointsSystem, season };
    return {
      official: computeRawPoints({ ...base, filterOfficialOnly: true }),
      total: computeRawPoints({ ...base, filterOfficialOnly: false }),
    };
  }
);

export const selectDriverStandings = createSelector(
  [selectCalculatedPoints, selectOfficialDriverStandings],
  ({ official, total }, officialStandings): DriverStanding[] => {
    const useOfficial = officialStandings && officialStandings.length > 0;
    
    if (useOfficial) {
      // Build official points map from API standings
      const officialPointsMap: Record<string, number> = {};
      officialStandings.forEach(s => {
        officialPointsMap[s.driverId] = s.points;
      });
      
      // Use official standings as the primary driver list (they always have all drivers)
      return officialStandings
        .map(s => ({
          driverId: s.driverId,
          points: s.points,
          position: s.position,
          predictionPointsGained: 0,
          positionChange: 0,
          finishCounts: total.driverFinishes[s.driverId] || []
        }));
    }
    
    // Fallback to calculated standings
    const officialRankingsCalc = Object.entries(official.driverPoints)
      .map(([driverId, points]) => ({
        driverId,
        points,
        finishCounts: official.driverFinishes[driverId] || []
      }))
      .sort((a, b) => {
        if (b.points !== a.points) return b.points - a.points;
        return compareByCountback(a.finishCounts, b.finishCounts);
      })
      .reduce((acc, { driverId }, index) => {
        acc[driverId] = index + 1;
        return acc;
      }, {} as Record<string, number>);

    return Object.entries(total.driverPoints)
      .map(([driverId, points]) => ({
        driverId,
        points,
        position: 0,
        predictionPointsGained: points - (official.driverPoints[driverId] || 0),
        positionChange: 0,
        finishCounts: total.driverFinishes[driverId] || []
      }))
      .sort((a, b) => {
        if (b.points !== a.points) return b.points - a.points;
        return compareByCountback(a.finishCounts, b.finishCounts);
      })
      .map((standing, index) => {
        const newPosition = index + 1;
        const oldPosition = officialRankingsCalc[standing.driverId] || newPosition;
        return {
          ...standing,
          position: newPosition,
          positionChange: oldPosition - newPosition
        };
      });
  }
);

export const selectTeamStandings = createSelector(
  [selectCalculatedPoints, selectOfficialConstructorStandings],
  ({ official, total }, officialStandings): TeamStanding[] => {
    const useOfficial = officialStandings && officialStandings.length > 0;
    
    if (useOfficial) {
      // Use official standings as the primary team list
      return officialStandings
        .map(s => ({
          teamId: s.teamId,
          points: s.points,
          position: s.position,
          predictionPointsGained: 0,
          positionChange: 0,
          finishCounts: total.teamFinishes[s.teamId] || []
        }));
    }
    
    // Fallback to calculated standings
    const officialRankingsCalc = Object.entries(official.teamPoints)
      .map(([teamId, points]) => ({
        teamId,
        points,
        finishCounts: official.teamFinishes[teamId] || []
      }))
      .sort((a, b) => {
        if (b.points !== a.points) return b.points - a.points;
        return compareByCountback(a.finishCounts, b.finishCounts);
      })
      .reduce((acc, { teamId }, index) => {
        acc[teamId] = index + 1;
        return acc;
      }, {} as Record<string, number>);

    return Object.entries(total.teamPoints)
      .map(([teamId, points]) => ({
        teamId,
        points,
        position: 0,
        predictionPointsGained: points - (official.teamPoints[teamId] || 0),
        positionChange: 0,
        finishCounts: total.teamFinishes[teamId] || []
      }))
      .sort((a, b) => {
        if (b.points !== a.points) return b.points - a.points;
        return compareByCountback(a.finishCounts, b.finishCounts);
      })
      .map((standing, index) => {
        const newPosition = index + 1;
        const oldPosition = officialRankingsCalc[standing.teamId] || newPosition;
        return {
          ...standing,
          position: newPosition,
          positionChange: oldPosition - newPosition
        };
      });
  }
);

export const selectPointsHistory = createSelector(
  [selectCalculatedPoints],
  ({ total }): PointsHistory[] => total.driverHistories
);

export const selectTeamPointsHistory = createSelector(
  [selectCalculatedPoints],
  ({ total }): TeamPointsHistory[] => total.teamHistories
);
