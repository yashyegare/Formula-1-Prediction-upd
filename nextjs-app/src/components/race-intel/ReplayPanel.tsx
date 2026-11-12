import { useEffect, useMemo, useRef, useState } from "react";
import {
  curveColor,
  percent,
  pointAtLap,
  replaySchema,
  visibleReplayDrivers,
  type CurvePoint,
  type IntelRace,
  type Replay,
} from "src/lib/raceIntel";
import { useIntelResource } from "src/lib/useIntelResource";

export const REPLAY_METRICS = {
  podium: { index: 1, label: "Podium · P1–3" },
  points: { index: 2, label: "P4–10" },
  out: { index: 3, label: "Outside top 10" },
} as const;
export type ReplayMetric = keyof typeof REPLAY_METRICS;
export function ProbabilityChart({
  drivers,
  nLaps,
  metric,
  selected,
  lap,
}: {
  drivers: Replay["drivers"];
  nLaps: number;
  metric: ReplayMetric;
  selected: string | null;
  lap: number;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(880);
  useEffect(() => {
    const resize = () =>
      setWidth(
        Math.max(
          300,
          Math.min(1000, svg.current?.getBoundingClientRect().width || 880)
        )
      );
    resize();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", resize);
      return () => window.removeEventListener("resize", resize);
    }
    const observer = new ResizeObserver(resize);
    if (svg.current) observer.observe(svg.current);
    return () => observer.disconnect();
  }, []);
  const height = 280,
    left = 52,
    right = 24,
    top = 16,
    bottom = 38;
  const x = (value: number) => left + (value / nLaps) * (width - left - right);
  const y = (value: number) => top + (1 - value) * (height - top - bottom);
  const index = REPLAY_METRICS[metric].index;
  const ticks = Array.from({ length: 6 }, (_, i) =>
    Math.round((i / 5) * nLaps)
  );
  return (
    <svg
      ref={svg}
      className="ri-probability-chart"
      style={{ height: 280 }}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`${REPLAY_METRICS[metric].label} probability by lap. Current lap ${lap}. Values are listed below.`}
    >
      {[0, 0.25, 0.5, 0.75, 1].map((p) => (
        <g key={p}>
          <line
            x1={left}
            x2={width - right}
            y1={y(p)}
            y2={y(p)}
            stroke="#dadbd4"
            strokeDasharray={p > 0 && p < 1 ? "3 5" : undefined}
          />
          <text x={left - 12} y={y(p) + 4} textAnchor="end">
            {Math.round(p * 100)}%
          </text>
        </g>
      ))}
      {[...new Set(ticks)].map((tick) => (
        <text key={tick} x={x(tick)} y={height - 12} textAnchor="middle">
          L{tick}
        </text>
      ))}
      {[...drivers]
        .sort(
          (a, b) =>
            Number(a.driverId === selected) - Number(b.driverId === selected)
        )
        .map((driver) => (
          <polyline
            key={driver.driverId}
            data-driver={driver.driverId}
            points={driver.curve
              .map((point) => `${x(point[0])},${y(point[index])}`)
              .join(" ")}
            fill="none"
            stroke={curveColor(driver.driverId)}
            strokeWidth={driver.driverId === selected ? 3.5 : 2}
            opacity={selected && driver.driverId !== selected ? 0.35 : 1}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}
      <line
        x1={x(lap)}
        x2={x(lap)}
        y1={top}
        y2={height - bottom}
        stroke="#303632"
        strokeDasharray="4 4"
      />
    </svg>
  );
}
export default function ReplayPanel({
  race,
  selected,
  onSelect,
}: {
  race: IntelRace;
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
  const [attempt, setAttempt] = useState(0);
  const [metric, setMetric] = useState<ReplayMetric>("podium");
  const [lap, setLap] = useState<number | null>(null);
  const resource = useIntelResource(
    race.status === "raced"
      ? `/api/race-intel/curves/${race.year}/${race.round}`
      : null,
    replaySchema,
    attempt
  );
  const doc = resource.data;
  const driverLabel = (driver: Replay["drivers"][number]) =>
    race.drivers.find((entry) => entry.driverId === driver.driverId)?.surname ||
    driver.surname ||
    driver.driverCode ||
    driver.driverId.replace(/_/g, " ");
  const effectiveSelected = doc?.drivers.some(
    (driver) => driver.driverId === selected
  )
    ? selected
    : null;
  const shown = useMemo(
    () =>
      doc
        ? visibleReplayDrivers(
            doc,
            [...race.drivers]
              .sort((a, b) => a.expected_position - b.expected_position)
              .map((d) => d.driverId),
            effectiveSelected
          )
        : [],
    [doc, race.drivers, effectiveSelected]
  );
  const currentLap = doc ? Math.min(lap ?? doc.n_laps, doc.n_laps) : 0;
  const metricIndex = REPLAY_METRICS[metric].index;
  return (
    <section className="ri-panel" aria-labelledby="replay-heading">
      <div className="ri-section-heading">
        <div>
          <p className="ri-eyebrow">AFTER THE LIGHTS GO OUT</p>
          <h2 id="replay-heading">How the probabilities changed</h2>
          <p>
            Historical scenario replays, conditioned on the running order at
            sampled laps. These are model estimates, not live timing.
          </p>
        </div>
        <span className="ri-section-number" aria-hidden="true">
          02
        </span>
      </div>
      {race.status !== "raced" ? (
        <div className="ri-empty">
          <strong>No completed-race replay yet</strong>
          <p>
            {race.status === "scheduled"
              ? "This round only has a pre-qualifying scenario in the analysis snapshot."
              : "Replay becomes available when a completed-race artifact is published."}{" "}
            Choose a completed round to explore a replay.
          </p>
        </div>
      ) : (
        <>
          {resource.status === "loading" && (
            <div className="ri-chart-skeleton" role="status">
              Loading the race replay…
            </div>
          )}
          {(resource.status === "error" || resource.status === "empty") && (
            <div className="ri-empty" role="status">
              <strong>Replay unavailable for this round</strong>
              <p>
                {resource.error ??
                  "The analysis snapshot does not include lap curves for this race."}
              </p>
              <button
                className="ri-button"
                onClick={() => setAttempt((n) => n + 1)}
              >
                Retry replay
              </button>
            </div>
          )}
          {doc && (
            <>
              <div className="ri-chart-toolbar">
                <div className="ri-segmented" aria-label="Replay metric">
                  {(Object.keys(REPLAY_METRICS) as ReplayMetric[]).map(
                    (key) => (
                      <button
                        key={key}
                        aria-pressed={metric === key}
                        onClick={() => setMetric(key)}
                      >
                        {REPLAY_METRICS[key].label}
                      </button>
                    )
                  )}
                </div>
                <label>
                  Focus driver
                  <select
                    value={effectiveSelected ?? ""}
                    onChange={(event) => onSelect(event.target.value || null)}
                  >
                    <option value="">Model leaders</option>
                    {doc.drivers.map((driver) => (
                      <option value={driver.driverId} key={driver.driverId}>
                        {driverLabel(driver)}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <ProbabilityChart
                drivers={shown}
                nLaps={doc.n_laps}
                metric={metric}
                selected={effectiveSelected}
                lap={currentLap}
              />
              <div className="ri-lap-control">
                <label htmlFor="replay-lap">
                  Inspect lap <strong>{currentLap}</strong> / {doc.n_laps}
                </label>
                <input
                  id="replay-lap"
                  type="range"
                  min={0}
                  max={doc.n_laps}
                  value={currentLap}
                  onChange={(event) => setLap(Number(event.target.value))}
                />
              </div>
              <p className="ri-caption">
                Six model leaders are shown by default. Selecting any driver
                adds their trace. Values use the latest available sample at or
                before the inspected lap.
              </p>
              <dl className="ri-replay-values">
                {shown.map((driver) => {
                  const point: CurvePoint | null = pointAtLap(
                    driver.curve,
                    currentLap
                  );
                  return (
                    <div
                      key={driver.driverId}
                      style={{ borderLeftColor: curveColor(driver.driverId) }}
                    >
                      <dt>{driverLabel(driver)}</dt>
                      <dd>
                        {point ? percent(point[metricIndex]) : "No sample"}
                        <small>
                          {point ? `Sample L${point[0]}` : "Not yet sampled"}
                        </small>
                      </dd>
                    </div>
                  );
                })}
              </dl>
            </>
          )}
        </>
      )}
    </section>
  );
}
