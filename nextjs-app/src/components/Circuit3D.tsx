import { useEffect, useRef, useState } from "react";
import type { CircuitScene } from "../lib/circuitScene";

export default function Circuit3D({
  points,
  name,
  paused,
  onError,
}: {
  points: string;
  name: string;
  paused: boolean;
  onError: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<CircuitScene | null>(null);
  const [ready, setReady] = useState(false);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  useEffect(() => {
    let cancelled = false;
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const updateMotion = () =>
      scene.current?.setPaused(pausedRef.current || preference.matches);
    import("../lib/circuitScene")
      .then(({ createCircuitScene }) => {
        if (cancelled || !host.current) return;
        scene.current = createCircuitScene(
          host.current,
          points,
          pausedRef.current || preference.matches,
          onError
        );
        setReady(true);
      })
      .catch(() => {
        if (!cancelled) onError();
      });
    preference.addEventListener("change", updateMotion);
    return () => {
      cancelled = true;
      preference.removeEventListener("change", updateMotion);
      scene.current?.dispose();
      scene.current = null;
    };
  }, [points, onError]);
  useEffect(() => {
    scene.current?.setPaused(
      paused || window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }, [paused]);
  return (
    <div className="lab-3d">
      <div
        className="lab-3d-stage"
        ref={host}
        role="img"
        aria-label={`Interactive schematic of ${name}. Drag horizontally to rotate, or use the rotation buttons below.`}
      />
      {!ready && (
        <div className="lab-3d-loading" role="status">
          Preparing circuit…
        </div>
      )}
      <div className="lab-3d-controls" aria-label="Circuit view controls">
        <button
          type="button"
          disabled={!ready}
          aria-label="Rotate circuit left"
          onClick={() => scene.current?.rotate(-1)}
        >
          ↶
        </button>
        <span>Drag to rotate</span>
        <button
          type="button"
          disabled={!ready}
          aria-label="Rotate circuit right"
          onClick={() => scene.current?.rotate(1)}
        >
          ↷
        </button>
        <button
          type="button"
          disabled={!ready}
          onClick={() => scene.current?.reset()}
        >
          Reset view
        </button>
      </div>
      <p className="lab-3d-caption">Schematic layout · flat elevation</p>
    </div>
  );
}
