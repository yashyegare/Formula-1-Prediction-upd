import { useCallback, useEffect, useState } from "react";
import Circuit3D from "./Circuit3D";
import { explorerTrackUrl, loadCircuitRegistry } from "../lib/trackExplorer";

interface Preview {
  name: string;
  location: string;
  length: number;
  points: string;
}
export default function CircuitPreview({
  circuitId,
  paused = false,
}: {
  circuitId: string;
  paused?: boolean;
}) {
  const [mode, setMode] = useState<"outline" | "3d">("outline");
  const [failed3D, setFailed3D] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const on3DError = useCallback(() => {
    setMode("outline");
    setFailed3D(true);
  }, []);
  const [track, setTrack] = useState<{ preview: Preview; href: string } | null>(
    null
  );
  useEffect(() => {
    const controller = new AbortController();
    setTrack(null);
    setLoaded(false);
    setMode("outline");
    setFailed3D(false);
    Promise.all([
      loadCircuitRegistry(),
      fetch("/track-previews.json", { signal: controller.signal }).then(
        (res) => {
          if (!res.ok) throw new Error("Preview unavailable");
          return res.json() as Promise<{ circuits: Record<string, Preview> }>;
        }
      ),
    ])
      .then(([registry, data]) => {
        const circuit = registry.find((c) => c.circuitId === circuitId);
        const href = explorerTrackUrl(circuit);
        const preview = circuit?.explorerSlug
          ? data.circuits[circuit.explorerSlug]
          : undefined;
        if (!controller.signal.aborted && preview && href)
          setTrack({ preview, href });
      })
      .catch(() => {
        /* Calendar and prediction stay usable without a preview. */
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoaded(true);
      });
    return () => controller.abort();
  }, [circuitId]);
  if (!track)
    return (
      <div
        className="lab-circuit-placeholder"
        aria-label={
          loaded ? "Circuit profile unavailable" : "Loading circuit profile"
        }
      >
        {!loaded && <span className="lab-skeleton" />}
        <span>
          {loaded
            ? "Circuit profile unavailable. Race predictions remain available below."
            : "Preparing circuit profile…"}
        </span>
      </div>
    );
  const circuitPath = `M${track.preview.points.trim().split(/\s+/).join(" L")}`;
  return (
    <div className="lab-circuit-preview">
      <div className="lab-view-toggle" aria-label="Circuit display">
        <span>Circuit preview</span>
        <div>
          <button
            type="button"
            aria-pressed={mode === "outline"}
            onClick={() => setMode("outline")}
          >
            2D
          </button>
          <button
            type="button"
            aria-pressed={mode === "3d"}
            onClick={() => {
              setFailed3D(false);
              setMode("3d");
            }}
          >
            3D
          </button>
        </div>
      </div>
      {failed3D && (
        <p className="lab-3d-caption" role="status">
          3D is unavailable on this device. The circuit outline is still
          available.
        </p>
      )}
      {mode === "3d" ? (
        <Circuit3D
          points={track.preview.points}
          name={track.preview.name}
          paused={paused}
          onError={on3DError}
        />
      ) : (
        <>
          <a
            href={track.href}
            className="lab-track-outline"
            aria-label={`Explore ${track.preview.name} in Track Metrics Lab`}
          >
            <svg
              viewBox="0 0 320 180"
              role="img"
              aria-label={`${track.preview.name} circuit outline`}
            >
              <polyline
                points={track.preview.points}
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              <path
                className="lab-track-tracer"
                d={circuitPath}
                pathLength="1"
                fill="none"
                stroke="currentColor"
                strokeWidth="4"
                strokeLinecap="round"
                aria-hidden="true"
              />
            </svg>
          </a>
          <p className="lab-3d-caption">Choose 3D to rotate the circuit</p>
        </>
      )}
      <div className="lab-track-meta">
        <div>
          <strong>{track.preview.name}</strong>
          <span>
            {track.preview.location} ·{" "}
            {(track.preview.length / 1000).toFixed(3)} km
          </span>
        </div>
        <a href={track.href} className="lab-text-link">
          Explore circuit ↗
        </a>
      </div>
      <p className="lab-track-source">
        Circuit profile from Track Metrics Lab · 3D layouts and historical
        qualifying telemetry
      </p>
    </div>
  );
}
