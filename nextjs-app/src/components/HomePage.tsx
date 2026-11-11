import Head from "next/head";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import Predictor from "./predictor";
import CircuitPreview from "./CircuitPreview";
import SiteNav, { SIMULATOR_URL } from "./SiteNav";

interface Race {
  id: string;
  name: string;
  date: string;
  round: string;
  completed: boolean;
  circuitId?: string;
}
interface Season {
  sync?: { lastSuccessfulSync: string | null };
  schedule: Race[];
  drivers: Array<{ id: string; givenName: string; familyName: string }>;
  raceResults: Record<string, Array<{ driverId: string; position: number }>>;
}
const formatDate = (date: string) =>
  new Date(`${date}T12:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });

export default function HomePage() {
  const [season, setSeason] = useState<Season | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [motionPaused, setMotionPaused] = useState(false);
  const year = new Date().getUTCFullYear();
  useEffect(() => {
    try {
      setMotionPaused(localStorage.getItem("f1-motion-paused") === "true");
    } catch {
      /* Storage is optional. */
    }
  }, []);
  const toggleMotion = () => {
    const nextValue = !motionPaused;
    setMotionPaused(nextValue);
    try {
      localStorage.setItem("f1-motion-paused", String(nextValue));
    } catch {
      /* Storage is optional. */
    }
  };
  useEffect(() => {
    if (
      !("IntersectionObserver" in window) ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    )
      return;
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            (entry.target as HTMLElement).dataset.reveal = "visible";
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.08 }
    );
    const sections = document.querySelectorAll<HTMLElement>("[data-reveal]");
    sections.forEach((section) => {
      section.dataset.reveal = "pending";
      observer.observe(section);
    });
    return () => {
      observer.disconnect();
      sections.forEach((section) => {
        section.dataset.reveal = "visible";
      });
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setFailed(false);
    const timeout = setTimeout(() => {
      setFailed(true);
      controller.abort();
    }, 20000);
    fetch(`/api/init?year=${year}`, {
      signal: controller.signal,
      cache: "no-store",
    })
      .then((res) => {
        if (!res.ok) throw new Error("Season unavailable");
        return res.json() as Promise<Season>;
      })
      .then(setSeason)
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      })
      .finally(() => clearTimeout(timeout));
    return () => {
      clearTimeout(timeout);
      controller.abort();
    };
  }, [year, attempt]);
  const races = [...(season?.schedule ?? [])].sort(
    (a, b) => Number(a.round) - Number(b.round)
  );
  const completed = races.filter((r) => r.completed);
  const next = races.find((r) => !r.completed);
  const latest = completed[completed.length - 1];
  const seasonRaces = useMemo(
    () => season?.schedule.map((race) => race.name),
    [season]
  );
  const podium = latest
    ? [...(season?.raceResults[latest.id] ?? [])]
        .sort((a, b) => a.position - b.position)
        .slice(0, 3)
    : [];

  return (
    <div
      className={`f1-site lab-home ${motionPaused ? "lab-motion-paused" : ""}`}
    >
      <Head>
        <title>F1 Race Lab — Predict the race. Explore the championship.</title>
        <meta
          name="description"
          content="Explore the next Formula 1 race, predict driver outcomes, and simulate how your results change the championship."
        />
      </Head>
      <div className="lab-home-header">
        <SiteNav />
      </div>
      <main id="main-content" className="lab-main">
        <section className="lab-hero">
          <div className="lab-hero-copy">
            <p className="lab-eyebrow">
              <span className="lab-live-dot" aria-hidden="true" /> Formula 1 /
              Season {year}
            </p>
            <h1>
              Predict the race.
              <br />
              <em>Explore the title fight.</em>
            </h1>
            <p className="lab-intro">
              Test a driver outcome, then build your championship scenario.
            </p>
            <div className="lab-actions">
              <a className="lab-primary" href="#predict">
                Predict this race ↗
              </a>
              <a className="lab-secondary" href={SIMULATOR_URL}>
                Simulate the championship
              </a>
            </div>
            <p className="lab-caption">
              Explore without an account. Sign in to save your simulator
              predictions.
            </p>
            <div className="lab-hero-bottom">
              <a href="#results" className="lab-scroll-cue">
                <span aria-hidden="true">↓</span> Latest race results
              </a>
              <button
                type="button"
                className="lab-motion-toggle"
                aria-pressed={motionPaused}
                onClick={toggleMotion}
              >
                {motionPaused
                  ? "Resume visual effects"
                  : "Pause visual effects"}
              </button>
            </div>
          </div>
          <aside className="lab-weekend" aria-live="polite">
            <p className="lab-eyebrow">
              {next
                ? `Up next / Round ${next.round}`
                : season
                ? "Season review"
                : "Race calendar"}
            </p>
            <h2>
              {next?.name ??
                (season
                  ? `${year} season complete`
                  : failed
                  ? "Calendar unavailable"
                  : "Loading the next race…")}
            </h2>
            {next && <p className="lab-race-date">{formatDate(next.date)}</p>}
            {season && (
              <p className="lab-caption">
                {latest
                  ? `Results through round ${latest.round} · ${formatDate(
                      latest.date
                    )}`
                  : "No completed races yet."}
              </p>
            )}
            {failed && (
              <p>
                We couldn’t load the calendar.{" "}
                <button
                  className="lab-text-button"
                  onClick={() => setAttempt((n) => n + 1)}
                >
                  Try again
                </button>
              </p>
            )}
            {season && (
              <p className="lab-sync-time">
                {season.sync?.lastSuccessfulSync ? (
                  <>
                    Last successful sync:{" "}
                    <time dateTime={season.sync.lastSuccessfulSync}>
                      {new Date(season.sync.lastSuccessfulSync).toLocaleString(
                        "en-GB",
                        {
                          day: "numeric",
                          month: "short",
                          hour: "2-digit",
                          minute: "2-digit",
                          timeZone: "UTC",
                        }
                      )}{" "}
                      UTC
                    </time>
                  </>
                ) : (
                  "Sync time not yet recorded"
                )}
              </p>
            )}
            {next?.circuitId && <CircuitPreview circuitId={next.circuitId} />}
          </aside>
        </section>
        {season && races.length > 0 && (
          <section className="lab-season-pulse" aria-label="Season progress">
            <div>
              <span className="lab-eyebrow">The championship so far</span>
              <strong>
                {completed.length}
                <span> / {races.length} races complete</span>
              </strong>
            </div>
            <div
              className="lab-season-bar"
              role="progressbar"
              aria-label="Completed races"
              aria-valuenow={completed.length}
              aria-valuemin={0}
              aria-valuemax={races.length}
            >
              <span
                style={{ width: `${(completed.length / races.length) * 100}%` }}
              />
            </div>
            <a href={SIMULATOR_URL}>
              {races.length - completed.length} races to shape{" "}
              <span aria-hidden="true">↗</span>
            </a>
          </section>
        )}
        <section
          id="predict"
          className="lab-predict-section"
          data-reveal="visible"
        >
          <div className="lab-section-heading">
            <p className="lab-eyebrow">Make your call</p>
            <h2>Explore your driver’s race.</h2>
            <p>
              Choose a driver and qualifying position to estimate podium,
              points, or outside the points.
            </p>
          </div>
          <div className="lab-predict-layout">
            <div className="lab-predictor">
              <Predictor
                defaultRace={next?.name}
                seasonRaces={seasonRaces}
                seasonError={failed}
              />
            </div>
            <div className="lab-explainer">
              <h3>Make the estimate useful.</h3>
              <ol>
                <li>
                  <strong>Compare two scenarios</strong>
                  <p>
                    Change qualifying position and predict again to compare the
                    two outcome categories.
                  </p>
                </li>
                <li>
                  <strong>Build your scenario</strong>
                  <p>
                    Set the finishing order and see how the championship
                    changes.
                  </p>
                  <a href={SIMULATOR_URL} className="lab-text-link">
                    Try a championship scenario →
                  </a>
                </li>
                <li>
                  <strong>Compare after the flag</strong>
                  <p>Review race analysis against the official results.</p>
                  <Link href="/race-intel" className="lab-text-link">
                    Review race analysis →
                  </Link>
                </li>
              </ol>
              <p className="lab-method-note">
                An estimate, with uncertainty. Qualifying is a strong signal;
                incidents and reliability can change everything.{" "}
                <Link href="/about">Read the methodology</Link>.
              </p>
            </div>
          </div>
        </section>
        <section id="results" className="lab-results" data-reveal="visible">
          <div>
            <p className="lab-eyebrow">
              Latest completed{latest ? ` / Round ${latest.round}` : ""}
            </p>
            <h2>
              {latest?.name ?? (season ? "No results yet" : "Official results")}
            </h2>
            <p className="lab-caption">
              {latest
                ? `${formatDate(latest.date)} · Official race classification`
                : "Completed races will appear here as results are published."}
            </p>
          </div>
          <ol className="lab-podium">
            {podium.map((r) => {
              const d = season?.drivers.find((d) => d.id === r.driverId);
              return (
                <li key={r.driverId}>
                  <span>P{r.position}</span>
                  <strong>
                    {d
                      ? `${d.givenName} ${d.familyName}`
                      : r.driverId.replaceAll("_", " ")}
                  </strong>
                </li>
              );
            })}
          </ol>
          <a href={SIMULATOR_URL} className="lab-text-link">
            Results & standings →
          </a>
        </section>
      </main>
      <footer className="lab-footer">
        <span>F1 Race Lab · An independent fan project by Yash Yegare</span>
        <div className="lab-footer-links">
          <Link href="/about">About & methodology</Link>
          <a href="#main-content">Back to top ↑</a>
        </div>
      </footer>
    </div>
  );
}
