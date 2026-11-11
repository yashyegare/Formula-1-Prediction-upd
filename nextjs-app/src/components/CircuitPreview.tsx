import { useEffect, useState } from "react";
import { explorerTrackUrl, loadCircuitRegistry } from "../lib/trackExplorer";

interface Preview {
  name: string;
  location: string;
  length: number;
  points: string;
}
export default function CircuitPreview({ circuitId }: { circuitId: string }) {
  const [track, setTrack] = useState<{ preview: Preview; href: string } | null>(
    null
  );
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setTrack(null);
    setSettled(false);
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
        if (!controller.signal.aborted) setSettled(true);
      });
    return () => controller.abort();
  }, [circuitId]);
  if (!track)
    return (
      <div className="lab-circuit-placeholder" role="status">
        {settled ? (
          <>
            <span>Circuit profile unavailable.</span>
            <a href="https://f1-track-metrics-lab.vercel.app">
              Browse Track Metrics Lab ↗
            </a>
          </>
        ) : (
          <>
            <span className="lab-skeleton" aria-hidden="true" />
            <span>Loading circuit profile…</span>
          </>
        )}
      </div>
    );
  const circuitPath = `M${track.preview.points.trim().split(/\s+/).join(" L")}`;
  return (
    <div className="lab-circuit-preview">
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
        Track Metrics Lab · Layouts and historical qualifying telemetry
      </p>
    </div>
  );
}
