import { useEffect, useRef, useState } from "react";
import {
  explorerTrackUrl,
  loadCircuitRegistry,
  type CircuitRegistryEntry,
} from "../lib/trackExplorer";
import { SIMULATOR_URL } from "./SiteNav";

interface Roster {
  drivers: string[];
  grandsPrix: string[];
  driverTeam: Record<string, string>;
  season: number;
}
interface Scenario {
  round: string;
  driver: string;
  quali: number;
  season: number;
}
interface Result extends Scenario {
  outcome: number;
}
const STORAGE_KEY = "f1-prediction-scenario-v1";
const OUTCOMES: Record<
  number,
  { label: string; detail: string; category: string }
> = {
  1: { label: "Podium finish", detail: "P1–P3", category: "podium" },
  2: { label: "Points finish", detail: "P4–P10", category: "points" },
  3: { label: "Outside the points", detail: "P11+", category: "outside" },
};

export default function Predictor({ defaultRace }: { defaultRace?: string }) {
  const [roster, setRoster] = useState<Roster | null>(null);
  const [rosterError, setRosterError] = useState(false);
  const [rosterAttempt, setRosterAttempt] = useState(0);
  const [round, setRound] = useState("");
  const [driver, setDriver] = useState("");
  const [quali, setQuali] = useState(1);
  const [circuits, setCircuits] = useState<CircuitRegistryEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [slow, setSlow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [restored, setRestored] = useState(false);
  const chosenRace = useRef(false);
  const request = useRef<AbortController | null>(null);
  const slowTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const qualifyingInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    setRosterError(false);
    fetch("/roster", {
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(20000)]),
    })
      .then((res) => {
        if (!res.ok) throw new Error("Roster unavailable");
        return res.json() as Promise<Roster>;
      })
      .then((data) => {
        if (controller.signal.aborted) return;
        if (
          !Array.isArray(data.drivers) ||
          !data.drivers.length ||
          !Array.isArray(data.grandsPrix) ||
          !data.grandsPrix.length
        )
          throw new Error("Empty roster");
        setRoster(data);
        let saved: Partial<Scenario> = {};
        try {
          saved = JSON.parse(
            sessionStorage.getItem(STORAGE_KEY) ?? "{}"
          ) as Partial<Scenario>;
        } catch {
          /* A fresh scenario is fine. */
        }
        const valid =
          saved &&
          saved.season === data.season &&
          data.grandsPrix.includes(saved.round ?? "") &&
          data.drivers.includes(saved.driver ?? "") &&
          Number.isInteger(saved.quali) &&
          (saved.quali ?? 0) >= 1 &&
          (saved.quali ?? 23) <= 22;
        chosenRace.current = Boolean(valid);
        setRound(valid ? saved.round! : data.grandsPrix[0]!);
        setDriver(valid ? saved.driver! : data.drivers[0]!);
        setQuali(valid ? saved.quali! : 1);
        setRestored(Boolean(valid));
      })
      .catch(() => {
        if (!controller.signal.aborted) setRosterError(true);
      });
    loadCircuitRegistry().then((data) => {
      if (!controller.signal.aborted) setCircuits(data);
    });
    return () => controller.abort();
  }, [rosterAttempt]);
  useEffect(() => {
    if (
      !chosenRace.current &&
      defaultRace &&
      roster?.grandsPrix.includes(defaultRace)
    )
      setRound(defaultRace);
  }, [defaultRace, roster]);
  useEffect(() => {
    if (!roster || !round || !driver) return;
    try {
      sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ round, driver, quali, season: roster.season })
      );
    } catch {
      /* Saving is optional. */
    }
  }, [round, driver, quali, roster]);
  useEffect(
    () => () => {
      request.current?.abort();
      if (slowTimer.current) clearTimeout(slowTimer.current);
    },
    []
  );
  const clearResult = () => {
    setResult(null);
    setError(null);
    setRestored(false);
  };
  const changeQualifying = (value: number) => {
    setQuali(value);
    clearResult();
  };
  const circuit = circuits.find((c) => c.rounds.some((r) => r.name === round));
  const trackHref = explorerTrackUrl(circuit);
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (
      !roster ||
      loading ||
      !Number.isInteger(quali) ||
      quali < 1 ||
      quali > 22
    )
      return;
    const scenario: Scenario = { round, driver, quali, season: roster.season };
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setSlow(false);
    setError(null);
    setResult(null);
    slowTimer.current = setTimeout(() => setSlow(true), 5000);
    try {
      const response = await fetch("/predictGrid", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: driver,
          round,
          qualifying_pos: String(quali),
        }),
        signal: AbortSignal.any([
          controller.signal,
          AbortSignal.timeout(45000),
        ]),
      });
      if (!response.ok) throw new Error("Prediction unavailable");
      const body: unknown = await response.json();
      if (!Array.isArray(body) || ![1, 2, 3].includes(body[0] as number))
        throw new Error("Invalid response");
      if (!controller.signal.aborted)
        setResult({ ...scenario, outcome: body[0] as number });
    } catch {
      if (!controller.signal.aborted)
        setError(
          "We could not get an estimate. Your inputs are saved; please try again."
        );
    } finally {
      if (slowTimer.current) clearTimeout(slowTimer.current);
      if (!controller.signal.aborted) {
        setLoading(false);
        setSlow(false);
      }
    }
  };
  const outcome = result ? OUTCOMES[result.outcome] : null;
  const simulatorHref = `${SIMULATOR_URL}/?race=${encodeURIComponent(round)}`;
  return (
    <div className="lab-driver-tool">
      <div className="lab-tool-header">
        <span className="lab-tool-mark" aria-hidden="true">
          /
        </span>
        <div>
          <h3>Driver outcome predictor</h3>
          <p>A race-day estimate. A scenario you control.</p>
        </div>
      </div>
      <form onSubmit={submit} aria-busy={loading}>
        <div className="lab-tool-season">
          <span>{roster?.season ?? "Season"}</span>
          <span>
            {roster
              ? "Current roster"
              : rosterError
              ? "Unavailable"
              : "Loading roster…"}
          </span>
        </div>
        {restored && (
          <p className="lab-saved-note" role="status">
            Your last scenario is restored for this tab.
          </p>
        )}
        <label htmlFor="prediction-race">Grand Prix</label>
        <select
          id="prediction-race"
          value={round}
          disabled={!roster || loading}
          onChange={(event) => {
            chosenRace.current = true;
            setRound(event.target.value);
            clearResult();
          }}
        >
          {roster?.grandsPrix.map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
        {trackHref && (
          <a className="lab-tool-track-link" href={trackHref}>
            Explore {circuit?.name} ↗
          </a>
        )}
        <label htmlFor="prediction-driver">Driver</label>
        <select
          id="prediction-driver"
          value={driver}
          disabled={!roster || loading}
          onChange={(event) => {
            setDriver(event.target.value);
            clearResult();
          }}
        >
          {roster?.drivers.map((name) => (
            <option key={name} value={name}>
              {name}
              {roster.driverTeam[name] ? ` · ${roster.driverTeam[name]}` : ""}
            </option>
          ))}
        </select>
        {roster && (
          <div className="lab-driver-identity">
            <span aria-hidden="true">
              {driver
                .split(" ")
                .filter(Boolean)
                .map((part) => part[0])
                .join("")
                .slice(0, 2)}
            </span>
            <div>
              <strong>{driver}</strong>
              <small>
                {roster.driverTeam[driver] ?? "Current-season driver"}
              </small>
            </div>
          </div>
        )}
        <label htmlFor="prediction-quali">
          Qualifying position <span>Your scenario</span>
        </label>
        <div className="lab-position-stepper">
          <button
            type="button"
            disabled={loading || quali <= 1}
            aria-label="Improve qualifying position"
            onClick={() => changeQualifying(Math.max(1, quali - 1))}
          >
            −
          </button>
          <input
            id="prediction-quali"
            ref={qualifyingInput}
            type="number"
            required
            min={1}
            max={22}
            step={1}
            value={Number.isNaN(quali) ? "" : quali}
            disabled={loading}
            aria-describedby="qualifying-help"
            onChange={(event) => changeQualifying(event.target.valueAsNumber)}
          />
          <button
            type="button"
            disabled={loading || quali >= 22}
            aria-label="Lower qualifying position"
            onClick={() => changeQualifying(Math.min(22, quali + 1))}
          >
            +
          </button>
        </div>
        <p id="qualifying-help" className="lab-input-help">
          1–22 · This is your input, not a live qualifying result.
        </p>
        {rosterError && (
          <p role="alert" className="lab-tool-error">
            The driver list is unavailable.{" "}
            <button
              type="button"
              onClick={() => setRosterAttempt((value) => value + 1)}
            >
              Retry loading
            </button>
          </p>
        )}
        <button
          className="lab-estimate-button"
          type="submit"
          disabled={!roster || loading}
        >
          {loading ? (
            <>
              <span className="lab-spinner" aria-hidden="true" /> Getting your
              estimate…
            </>
          ) : (
            <>
              Predict driver outcome <span aria-hidden="true">→</span>
            </>
          )}
        </button>
        <p className="lab-request-status" role="status">
          {loading
            ? slow
              ? "The model is taking a little longer. Your request is still running."
              : "Checking this driver, circuit, and qualifying scenario…"
            : "Estimates are not guarantees of a race result."}
        </p>
      </form>
      {error && (
        <p className="lab-tool-error" role="alert">
          {error}
        </p>
      )}
      {result && outcome && (
        <section
          className={`lab-outcome lab-outcome-${outcome.category}`}
          aria-label="Prediction result"
        >
          <p className="lab-outcome-eyebrow">
            Model estimate / {result.season}
          </p>
          <h4 role="status">
            {outcome.label} <span>{outcome.detail}</span>
          </h4>
          <p>
            <strong>{result.driver}</strong> · {result.round}
          </p>
          <p className="lab-input-help">
            From qualifying P{result.quali}. This is an outcome category, not an
            exact finishing position.
          </p>
          <div className="lab-outcome-actions">
            <button
              type="button"
              onClick={() => qualifyingInput.current?.focus()}
            >
              Try another position
            </button>
            <a href={simulatorHref}>Explore championship impact ↗</a>
          </div>
          <p className="lab-input-help">
            The simulator opens this race. You choose the finishing order; this
            estimate is not inserted as an official result.
          </p>
        </section>
      )}
    </div>
  );
}
