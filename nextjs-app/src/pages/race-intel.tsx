import type { NextPage } from "next";
import Head from "next/head";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useRouter } from "next/router";
import { useEffect, useMemo, useRef, useState } from "react";
import SiteNav, { SIMULATOR_URL } from "src/components/SiteNav";
import OutcomesPanel from "src/components/race-intel/OutcomesPanel";
import StateMessage from "src/components/race-intel/IntelStateMessage";
import { useIntelResource } from "src/lib/useIntelResource";
import {
  chooseRound,
  coverageRound,
  intelCalendarSchema,
  intelSeasonSchema,
  percent,
  raceLabel,
  type IntelDriver,
} from "src/lib/raceIntel";
import { explorerTrackUrl } from "src/lib/trackExplorer";

const loadingPanel = () => (
  <p className="ri-caption" role="status">
    Preparing this view…
  </p>
);
const PostmortemPanel = dynamic(
  () => import("src/components/PostmortemPanel"),
  { loading: loadingPanel }
);
const ReconcilePanel = dynamic(() => import("src/components/ReconcilePanel"), {
  loading: loadingPanel,
});
const TrackErrorSection = dynamic(
  () => import("src/components/TrackErrorSection"),
  { loading: loadingPanel }
);
const ReplayPanel = dynamic(
  () => import("src/components/race-intel/ReplayPanel"),
  { loading: loadingPanel }
);
const DriverProfilePanel = dynamic(
  () => import("src/components/race-intel/DriverProfilePanel"),
  { loading: loadingPanel }
);
const EvaluationPanel = dynamic(
  () => import("src/components/race-intel/EvaluationPanel"),
  { loading: loadingPanel }
);

const TABS = [
  { id: "outcomes", label: "Driver outcomes" },
  { id: "replay", label: "Race replay" },
  { id: "picks", label: "Your picks" },
  { id: "context", label: "Model context" },
] as const;
type Tab = (typeof TABS)[number]["id"];
const RaceIntelPage: NextPage = () => {
  const router = useRouter();
  const [attempt, setAttempt] = useState(0),
    [tab, setTab] = useState<Tab>("outcomes"),
    [selectedDriver, setSelectedDriver] = useState<string | null>(null),
    [profileDriver, setProfileDriver] = useState<string | null>(null),
    [copied, setCopied] = useState(false);
  const profileTrigger = useRef<HTMLButtonElement | null>(null);
  const calendar = useIntelResource(
    "/api/race-intel/next-round",
    intelCalendarSchema,
    attempt
  );
  const year = calendar.data?.season ?? new Date().getUTCFullYear();
  const resource = useIntelResource(
    `/api/race-intel/season/${year}`,
    intelSeasonSchema,
    attempt
  );
  const season = resource.data;
  const requested =
    typeof router.query.round === "string"
      ? Number(router.query.round)
      : undefined;
  const selectedRound = season
    ? chooseRound(season, calendar.data, requested)
    : null;
  const race = season?.races.find((r) => r.round === selectedRound) ?? null;
  const completed = season ? coverageRound(season) : 0;
  const officialRound =
    calendar.data?.season === season?.season
      ? calendar.data?.results_through_round ?? null
      : null;
  const stale = officialRound !== null && officialRound > completed;
  const drivers = useMemo(
    () =>
      [...(race?.drivers ?? [])].sort(
        (a, b) =>
          a.expected_position - b.expected_position ||
          a.driverId.localeCompare(b.driverId)
      ),
    [race]
  );
  const focused = drivers.find((d) => d.driverId === profileDriver) ?? null;
  const favorite = useMemo(
    () => [...drivers].sort((a, b) => b.p_podium - a.p_podium)[0],
    [drivers]
  );
  const winner = drivers.find((d) => d.actual_position === 1 && !d.is_dnf);
  const roundIndex =
    season?.races.findIndex((r) => r.round === selectedRound) ?? -1;
  const trackUrl = explorerTrackUrl(race?.circuit);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2500);
    return () => clearTimeout(timer);
  }, [copied]);
  const changeRound = (round: number) => {
    setSelectedDriver(null);
    setProfileDriver(null);
    void router.replace(
      { pathname: "/race-intel", query: { round: String(round) } },
      undefined,
      { shallow: true, scroll: false }
    );
  };
  const selectDriver = (driver: IntelDriver, trigger: HTMLButtonElement) => {
    profileTrigger.current = trigger;
    setSelectedDriver(driver.driverId);
    setProfileDriver(
      profileDriver === driver.driverId ? null : driver.driverId
    );
  };
  const closeProfile = () => {
    setProfileDriver(null);
    profileTrigger.current?.focus({ preventScroll: true });
  };
  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(
        `${window.location.origin}/race-intel?round=${selectedRound}`
      );
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <>
      <Head>
        <title>Race Intelligence — F1 Race Lab</title>
        <meta
          name="description"
          content="Explore model outcome probabilities, completed-race replays and your prediction results, with clear analysis coverage."
        />
      </Head>
      <div className="f1-site ri-site">
        <SiteNav />
        <main id="main-content" className="ri-page">
          <div className="ri-shell">
            <header className="ri-masthead">
              <div>
                <p className="ri-eyebrow">
                  <span aria-hidden="true">/</span> THE RACE, IN CONTEXT
                </p>
                <h1>
                  Race intelligence<span>.</span>
                </h1>
                <p>
                  Beyond the finishing order. Explore model scenarios, replay
                  the probabilities, and understand your picks.
                </p>
              </div>
              <div className="ri-edition">
                <span>ANALYSIS DESK</span>
                <strong>{season?.season ?? year}</strong>
                <small>Model snapshots · recorded outcomes</small>
              </div>
            </header>
            {resource.status === "loading" && (
              <section
                className="ri-loading"
                role="status"
                aria-label="Loading race intelligence"
              >
                <div />
                <div />
                <div />
                <p>Preparing the analysis desk…</p>
              </section>
            )}
            {(resource.status === "error" || resource.status === "empty") && (
              <StateMessage
                title="The analysis desk is unavailable"
                message={
                  resource.error ??
                  `There is no published analysis snapshot for ${year}. Current results are still available in the season simulator.`
                }
                retry={() => setAttempt((n) => n + 1)}
              />
            )}
            {season && (
              <>
                <aside
                  className={`ri-coverage${stale ? " ri-coverage--stale" : ""}`}
                  aria-label="Analysis coverage"
                >
                  <span className="ri-coverage-dot" aria-hidden="true" />
                  <div>
                    <strong>
                      {stale
                        ? "Analysis snapshot awaiting refresh"
                        : "Published analysis snapshot"}
                    </strong>
                    <p>
                      Completed-race analysis through <b>round {completed}</b>
                      {officialRound !== null ? (
                        <>
                          {" "}
                          · official results through{" "}
                          <b>round {officialRound}</b>.
                        </>
                      ) : (
                        ". Calendar freshness could not be verified."
                      )}{" "}
                      {stale
                        ? "Later scenario rows are archived estimates, not updated race analysis."
                        : "Simulation probabilities are estimates, not guarantees."}
                      {season.refresh && (
                        <span className="ri-snapshot-time">
                          {" "}
                          Snapshot built{" "}
                          {new Date(season.refresh.published_at).toLocaleString(
                            "en-GB",
                            {
                              dateStyle: "medium",
                              timeStyle: "short",
                              timeZone: "UTC",
                            }
                          )}{" "}
                          UTC.
                        </span>
                      )}
                    </p>
                  </div>
                  <a href={SIMULATOR_URL}>
                    Current results <span aria-hidden="true">↗</span>
                  </a>
                </aside>
                <div className="ri-race-picker">
                  <label htmlFor="intel-round">
                    Explore a weekend
                    <select
                      id="intel-round"
                      value={selectedRound ?? ""}
                      onChange={(event) =>
                        changeRound(Number(event.target.value))
                      }
                    >
                      {season.races.map((r) => (
                        <option key={r.round} value={r.round}>
                          R{String(r.round).padStart(2, "0")} · {r.name} ·{" "}
                          {raceLabel(r, officialRound)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="ri-round-stepper">
                    <button
                      className="ri-icon-button"
                      aria-label="Previous race"
                      disabled={roundIndex <= 0}
                      onClick={() => {
                        const previous = season.races[roundIndex - 1];
                        if (previous) changeRound(previous.round);
                      }}
                    >
                      ←
                    </button>
                    <button
                      className="ri-icon-button"
                      aria-label="Next race"
                      disabled={
                        roundIndex < 0 || roundIndex >= season.races.length - 1
                      }
                      onClick={() => {
                        const next = season.races[roundIndex + 1];
                        if (next) changeRound(next.round);
                      }}
                    >
                      →
                    </button>
                  </div>
                  <button
                    className="ri-button ri-copy"
                    onClick={() => void copyLink()}
                  >
                    {copied ? "Link copied ✓" : "Copy race link"}
                  </button>
                  <span className="ri-sr-only" role="status">
                    {copied ? "Race link copied to clipboard" : ""}
                  </span>
                </div>
                {!race ? (
                  <StateMessage
                    title="No rounds in this snapshot"
                    message="This analysis has no race records to display."
                  />
                ) : (
                  <>
                    <section
                      className="ri-weekend-card"
                      aria-labelledby="weekend-heading"
                    >
                      <div className="ri-round-stamp" aria-hidden="true">
                        <span>ROUND</span>
                        <strong>{String(race.round).padStart(2, "0")}</strong>
                      </div>
                      <div className="ri-weekend-copy">
                        <p
                          className={`ri-status ri-status--${
                            race.status === "raced" ? "completed" : "scenario"
                          }`}
                        >
                          {raceLabel(race, officialRound)}
                        </p>
                        <h2 id="weekend-heading">{race.name}</h2>
                        <p>
                          {new Intl.DateTimeFormat("en", {
                            day: "numeric",
                            month: "short",
                            year: "numeric",
                            timeZone: "UTC",
                          }).format(new Date(`${race.date}T12:00:00Z`))}
                          {race.circuit?.location
                            ? ` · ${race.circuit.location}, ${race.circuit.country}`
                            : ""}
                        </p>
                        <div className="ri-weekend-meta">
                          <span>
                            {season.n_sims.toLocaleString()} simulations / race
                          </span>
                          <span>{race.drivers.length} model entries</span>
                          <span>
                            Grid:{" "}
                            {race.status === "scheduled"
                              ? "latest field · championship snapshot"
                              : race.status === "upcoming_post_quali"
                              ? "qualifying result"
                              : "recorded race grid"}
                          </span>
                        </div>
                      </div>
                      {trackUrl && (
                        <a
                          className="ri-track-link"
                          href={trackUrl}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Explore circuit <span aria-hidden="true">↗</span>
                        </a>
                      )}
                      <svg
                        className="ri-weekend-art"
                        viewBox="0 0 320 160"
                        aria-hidden="true"
                      >
                        <path d="M10 150 100 60H210L260 10M45 160 127 80H230L290 20M80 160 150 100H250L320 30" />
                      </svg>
                    </section>
                    <div className="ri-stat-grid">
                      <section>
                        <span>BEST MODEL AVERAGE</span>
                        <strong>{drivers[0]?.surname ?? "—"}</strong>
                        <p>
                          {drivers[0]
                            ? `${drivers[0].expected_position.toFixed(
                                1
                              )} average simulated finish`
                            : "No model entries available"}
                        </p>
                      </section>
                      <section>
                        <span>PODIUM FAVORITE</span>
                        <strong>
                          {favorite ? percent(favorite.p_podium) : "—"}
                          <small>{favorite?.surname}</small>
                        </strong>
                        <p>Estimated chance of finishing P1–3</p>
                      </section>
                      <section>
                        <span>
                          {race.status === "raced"
                            ? "RECORDED WINNER"
                            : "SCENARIO BASIS"}
                        </span>
                        <strong>
                          {race.status === "raced"
                            ? winner?.surname ?? "Not recorded"
                            : race.status === "scheduled"
                            ? "Before qualifying"
                            : "After qualifying"}
                        </strong>
                        <p>
                          {race.status === "raced"
                            ? "Recorded result, separate from the model"
                            : "Based on inputs in the published snapshot"}
                        </p>
                      </section>
                    </div>
                    <nav
                      className="ri-section-tabs"
                      aria-label="Analysis sections"
                    >
                      {TABS.map((item) => (
                        <button
                          key={item.id}
                          aria-pressed={tab === item.id}
                          onClick={() => setTab(item.id)}
                        >
                          {item.label}
                          <span aria-hidden="true">↗</span>
                        </button>
                      ))}
                    </nav>
                    {tab === "outcomes" && (
                      <>
                        <OutcomesPanel
                          key={race.round}
                          race={race}
                          selectedDriver={profileDriver}
                          onSelect={selectDriver}
                        />
                        {focused && (
                          <DriverProfilePanel
                            key={focused.driverId}
                            driver={focused}
                            season={season.season}
                            onClose={closeProfile}
                          />
                        )}
                      </>
                    )}
                    {tab === "replay" && (
                      <ReplayPanel
                        key={`${race.year}-${race.round}`}
                        race={race}
                        selected={selectedDriver}
                        onSelect={setSelectedDriver}
                      />
                    )}
                    {tab === "picks" && (
                      <section
                        className="ri-personal"
                        aria-label="Personal prediction review"
                      >
                        <div className="ri-section-heading">
                          <div>
                            <p className="ri-eyebrow">YOUR VIEW OF THE GRID</p>
                            <h2>How did your picks compare?</h2>
                            <p>
                              Your saved predictions, the model, and recorded
                              results. Sign in through the predictor to review
                              your own picks.
                            </p>
                          </div>
                          <Link href="/#predict" className="ri-button">
                            Open predictor ↗
                          </Link>
                        </div>
                        <PostmortemPanel season={season.season} />
                        <ReconcilePanel season={season.season} />
                      </section>
                    )}
                    {tab === "context" && (
                      <section className="ri-context">
                        {season.evaluation && (
                          <EvaluationPanel evaluation={season.evaluation} />
                        )}
                        <div className="ri-panel">
                          <div className="ri-section-heading">
                            <div>
                              <p className="ri-eyebrow">UNDER THE BODYWORK</p>
                              <h2>What this model can tell you</h2>
                              <p>
                                Scenario estimates help describe uncertainty.
                                They do not establish why a particular incident
                                happened.
                              </p>
                            </div>
                          </div>
                          <div className="ri-method-grid">
                            <article>
                              <span>01 / SIMULATION</span>
                              <h3>
                                {season.n_sims.toLocaleString()} scenarios per
                                race
                              </h3>
                              <p>
                                Finishing-position changes and retirement risk
                                are simulated from parameters fitted on strictly
                                prior seasons. Scheduled rounds use a latest
                                completed field, ordered by constructor
                                standings and then driver standings. This is a
                                scenario grid, not a confirmed future entry
                                list.
                              </p>
                            </article>
                            <article>
                              <span>02 / REPLAY</span>
                              <h3>Conditioned on recorded order</h3>
                              <p>
                                Completed-round replays rerun the scenario model
                                at sampled laps. They are historical
                                reconstructions, not live predictions or actual
                                telemetry.
                              </p>
                            </article>
                            <article>
                              <span>03 / EVALUATION</span>
                              <h3>Keep the evaluation in context</h3>
                              <p>
                                The artifact reports{" "}
                                {percent(season.season_attribution.accuracy)}{" "}
                                baseline accuracy and{" "}
                                {season.season_attribution.n_misses} misses.
                                This is the artifact’s evaluation metric, not a
                                probability calibration guarantee.
                              </p>
                            </article>
                          </div>
                          <details className="ri-method-details">
                            <summary>
                              Simulation assumptions and miss breakdown
                            </summary>
                            <p>
                              Position-change distribution: mean{" "}
                              {season.mechanism.swing_mean.toFixed(2)}, standard
                              deviation {season.mechanism.swing_sd.toFixed(2)}{" "}
                              places. Fitted DNF rate:{" "}
                              {percent(season.mechanism.dnf_rate)}.
                            </p>
                            <dl className="ri-attribution">
                              {Object.entries(
                                season.season_attribution.cause_share
                              )
                                .filter(([, value]) => value > 0)
                                .map(([cause, value]) => (
                                  <div key={cause}>
                                    <dt>{cause.replace(/_/g, " ")}</dt>
                                    <dd>{percent(value)}</dd>
                                  </div>
                                ))}
                            </dl>
                            <p>
                              Miss categories describe recorded outcomes; they
                              are not proof of a causal explanation. Replay and
                              personal-pick views may have different evaluation
                              denominators.
                            </p>
                          </details>
                        </div>
                        {season.track_error && (
                          <TrackErrorSection trackError={season.track_error} />
                        )}
                      </section>
                    )}
                    <footer className="ri-footer">
                      <p>
                        <span aria-hidden="true">/</span> F1 RACE LAB{" "}
                        <span>
                          Model scenarios. Recorded outcomes. Clear boundaries.
                        </span>
                      </p>
                      <Link href="/about">About the project ↗</Link>
                    </footer>
                  </>
                )}
              </>
            )}
          </div>
        </main>
      </div>
    </>
  );
};
export default RaceIntelPage;
