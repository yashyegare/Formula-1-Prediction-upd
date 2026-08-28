import React, { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import DragDropProvider from './components/common/DragDropProvider';
import { initializeUiState, setMobileView, syncPointsSystemForYear, toggleOfficialResults as toggleOfficialResultsUI } from './store/slices/uiSlice';
import type { RootState } from './store';
import { moveDriver, resetGrid, toggleOfficialResults } from './store/slices/gridSlice';
import { fetchLockedPredictions } from './store/slices/lockedPredictionsSlice';
import { loadPrediction, type UserIdentifier } from './api/predictions';
import useRaceResults from './hooks/useRaceResults';
import { useAutoSave } from './hooks/useAutoSave';
import Layout from './components/layout/Layout';
import StandingsSidebar from './components/standings/StandingsSidebar';
import RaceGrid from './components/grid/RaceGrid';
import MobileRaceCardView from './components/grid/MobileRaceCardView';
import ToastContainer from './components/common/ToastContainer';
import HorizontalScrollBar from './components/common/HorizontalScrollBar';
import VersionHistory from './components/common/VersionHistory';
import ExportModal from './components/common/ExportModal';
import SponsorBanner from './components/common/SponsorBanner';
import HeaderMenu from './components/common/HeaderMenu';
import CalculatorDropdown from './components/common/CalculatorDropdown';
import GridSkeleton from './components/common/GridSkeleton';
import DriverSelectionSkeleton from './components/common/DriverSelectionSkeleton';
import PaywallOverlay from './components/common/PaywallOverlay';
import DriverSelection from './components/drivers/DriverSelection';
import SeasonSelector from './components/common/SeasonSelector';
import UserMenu from './components/auth/UserMenu';
import { SandboxGridProvider } from './contexts/GridContext';
import { useAppDispatch } from './store';
import useWindowSize from './hooks/useWindowSize';
import { GA_EVENTS, trackEvent } from './utils/analytics';
import { CURRENT_SEASON } from './utils/constants';


const App: React.FC<{ year?: string }> = ({ year }) => {
  const dispatch = useAppDispatch();

  const activeSeason = year ? parseInt(year, 10) : CURRENT_SEASON;

  useEffect(() => {
    if (year) {
      (window as any).INITIAL_YEAR = parseInt(year, 10);
    } else {
      delete (window as any).INITIAL_YEAR;
    }
  }, [year]);
  useRaceResults(activeSeason);
  useAutoSave();
  const mobileView = useSelector((state: RootState) => state.ui.mobileView);
  const showOfficialResults = useSelector((state: RootState) => state.ui.showOfficialResults);
  const pastResults = useSelector((state: RootState) => state.seasonData.pastResults);
  const isLoading = useSelector((state: RootState) => state.seasonData.isLoading);
  const requiresSubscription = useSelector((state: RootState) => state.seasonData.requiresSubscription);
  const { fingerprint } = useSelector((state: RootState) => state.predictions);
  const { user } = useSelector((state: RootState) => state.auth);
  const { isMobile } = useWindowSize();

  // Get identifier - prefer userId if logged in, fallback to fingerprint
  const getIdentifier = (): UserIdentifier | null => {
    if (user?.id) return { userId: user.id };
    if (fingerprint) return { fingerprint };
    return null;
  };
  const raceGridScrollRef = React.useRef<HTMLDivElement>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [showExport, setShowExport] = useState(false);
  // Load saved predictions on mount / login
  useEffect(() => {
    const identifier = getIdentifier();
    if (!identifier) return;

    const loadSaved = async () => {
      try {
        const prediction = await loadPrediction(identifier, undefined, activeSeason);
        if (prediction && prediction.grid) {
          // prediction.grid is either an object {raceId: [driverId, ...]} or array
          const grid = prediction.grid;
          if (typeof grid === 'object' && !Array.isArray(grid)) {
            Object.entries(grid).forEach(([raceId, drivers]) => {
              if (Array.isArray(drivers)) {
                drivers.forEach((driverId: string, posIdx: number) => {
                  if (driverId) {
                    dispatch(moveDriver({
                      driverId,
                      toRaceId: raceId,
                      toPosition: posIdx + 1
                    }));
                  }
                });
              }
            });
          } else if (Array.isArray(grid)) {
            grid.forEach((pos: any) => {
              if (pos.driverId && pos.raceId) {
                dispatch(moveDriver({
                  driverId: pos.driverId,
                  toRaceId: pos.raceId,
                  toPosition: pos.position
                }));
              }
            });
          }
        }
      } catch (error) {
        // Silent fail - grid starts empty
      }
    };

    loadSaved();
  }, [fingerprint, user, activeSeason, dispatch]);

  // Fetch locked predictions when identifier is available
  useEffect(() => {
    const identifier = getIdentifier();
    if (identifier) {
      dispatch(fetchLockedPredictions({ identifier, season: activeSeason }));
    }
  }, [fingerprint, user, activeSeason, dispatch]);

  const handleReset = () => {
    if (window.confirm('Are you sure you want to reset your predictions?')) {
      dispatch(resetGrid());
      trackEvent(GA_EVENTS.GRID_ACTIONS.RESET_PREDICTIONS, 'Grid Actions');
    }
  };

  const handleToggleOfficialResults = () => {
    const newValue = !showOfficialResults;
    dispatch(toggleOfficialResultsUI(newValue));
    dispatch(toggleOfficialResults({ show: newValue, pastResults }));
  };

  const handleLoadVersion = async (version: string) => {
    const identifier = getIdentifier();
    if (!identifier) return;

    try {
      const prediction = await loadPrediction(identifier, version, activeSeason);
      if (prediction && prediction.grid) {
        dispatch(resetGrid());

        prediction.grid.forEach(pos => {
          if (pos.driverId && !pos.isOfficialResult) {
            dispatch(moveDriver({
              driverId: pos.driverId,
              toRaceId: pos.raceId,
              toPosition: pos.position
            }));
          }
        });

        setShowHistory(false);
      }
    } catch (error) {
    }
  };


  useEffect(() => {
    dispatch(initializeUiState());
  }, [dispatch]);

  // Year-aware default points system: applies the season's native system
  // (e.g. 2003-2009 for 2009) unless the user has explicitly chosen one.
  useEffect(() => {
    dispatch(syncPointsSystemForYear(activeSeason));
  }, [dispatch, activeSeason]);

  useEffect(() => {
    if (!isMobile) {
      if (mobileView !== 'grid') {
        dispatch(setMobileView('grid'));
      }
    }
  }, [isMobile, mobileView, dispatch]);

  return (
    <DragDropProvider>
      <div className="app">
        <ToastContainer />

        <Layout
          sidebar={<StandingsSidebar activeSeason={activeSeason} />}
          content={
            <div className="flex-1 min-h-0 flex flex-col px-2 sm:px-3 pt-2 pb-16 sm:pb-0 w-full">
              <div className="mb-1.5 shrink-0">
                {/* Single header row — unified sizing */}
                <div className="flex items-center gap-1.5 sm:gap-2 flex-nowrap">
                  <a
                    href="http://localhost:3000"
                    className="text-sm sm:text-base lg:text-lg font-display font-semibold flex items-center min-w-0 shrink text-gray-600 hover:text-red-600 transition-colors"
                  >
                    <svg className="w-5 h-5 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                    </svg>
                    <span className="truncate">Race Predictor</span>
                  </a>

                  {/* Right-side controls */}
                  <div className="flex items-center gap-1.5 sm:gap-2 ml-auto shrink-0">
                    <SeasonSelector activeSeason={activeSeason} />

                    {/* Promo only visible at lg+ where there's room */}
                    <div className="hidden lg:inline-flex">
                      <SponsorBanner />
                    </div>

                    <HeaderMenu />

                    <UserMenu />
                  </div>
                </div>
              </div>


              <div className={`flex-1 min-h-0 flex flex-col ${(mobileView === 'grid' || !isMobile) ? '' : 'hidden'}`}>
                {requiresSubscription ? (
                  <div className="flex-1 min-h-0 overflow-hidden">
                    <PaywallOverlay />
                  </div>
                ) : isLoading ? (
                  <>
                    <div className="shrink-0"><DriverSelectionSkeleton /></div>
                    <div className="shrink-0 w-full py-1 hidden sm:block">
                      <div className="relative w-full h-2 bg-carbon-200/70 rounded-full">
                        <div className="absolute top-0 h-full w-1/4 bg-carbon-300 rounded-full" style={{ left: '0%' }} />
                      </div>
                    </div>
                    <div className="flex-1 min-h-0 overflow-hidden"><GridSkeleton /></div>
                  </>
                ) : (
                  <>
                <SandboxGridProvider>
                {!isMobile && <div className="shrink min-h-0 overflow-hidden"><DriverSelection /></div>}

                  {isMobile ? (
                    <div className="flex-1 min-h-0 overflow-hidden">
                      <MobileRaceCardView
                        onReset={handleReset}
                        onToggleOfficialResults={handleToggleOfficialResults}
                        onOpenHistory={() => setShowHistory(true)}
                        onOpenExport={() => setShowExport(true)}
                        showOfficialResults={showOfficialResults}
                      />
                    </div>
                  ) : (
                    <>
                      <div className="shrink-0"><HorizontalScrollBar scrollContainerRef={raceGridScrollRef} /></div>
                      <div className="flex-1 min-h-0 overflow-hidden">
                        <RaceGrid
                          scrollRef={raceGridScrollRef}
                          onReset={handleReset}
                          onToggleOfficialResults={handleToggleOfficialResults}
                          onOpenHistory={() => setShowHistory(true)}
                          onOpenExport={() => setShowExport(true)}
                          showOfficialResults={showOfficialResults}
                        />
                      </div>
                    </>
                  )}
                </SandboxGridProvider>
                </>
              )}
              </div>
            </div>
          }
        />


        {showHistory && (
          <VersionHistory
            onClose={() => setShowHistory(false)}
            onLoadVersion={handleLoadVersion}
          />
        )}

        <ExportModal
          isOpen={showExport}
          onClose={() => setShowExport(false)}
        />



      </div>
    </DragDropProvider>
  );
};

export default App;