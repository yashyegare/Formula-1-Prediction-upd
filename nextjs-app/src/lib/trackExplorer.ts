import { NEXT_PUBLIC_API_URL } from "src/lib/constants";

export const TRACK_EXPLORER_BASE = "https://f1-track-metrics-lab.vercel.app";

export interface ExplorerCircuitRef {
  explorerSlug?: string | null;
}

/** Deep link into Track Explorer's 3D compare view. The explorer selects
 *  tracks by its own "<cc>-<year>" ids, which only exist on the v4
 *  circuit registry — without a slug there is no safe link, so we omit
 *  it rather than let the explorer silently open a different track. */
export const explorerTrackUrl = (circuit?: ExplorerCircuitRef | null) =>
  circuit?.explorerSlug
    ? `${TRACK_EXPLORER_BASE}/?circuit=${circuit.explorerSlug}&mode=compare3d`
    : null;

export interface CircuitRegistryEntry extends ExplorerCircuitRef {
  circuitId: string;
  name: string;
  location: string;
  country: string;
  rounds: { round: number; name: string }[];
}

let registryPromise: Promise<CircuitRegistryEntry[]> | null = null;

/** Cached season circuit registry, keyed in the caller by whatever label
 *  that surface already has (Grand Prix name). Resolves empty when the
 *  API is cold so callers fall back rather than hang. */
export const loadCircuitRegistry = (): Promise<CircuitRegistryEntry[]> => {
  if (!registryPromise) {
    registryPromise = fetch(`${NEXT_PUBLIC_API_URL}/api/race-intel/circuits`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`API ${res.status}`))))
      .then((body: { circuits: CircuitRegistryEntry[] }) => body.circuits ?? [])
      .catch(() => {
        registryPromise = null;
        return [];
      });
  }
  return registryPromise;
};
