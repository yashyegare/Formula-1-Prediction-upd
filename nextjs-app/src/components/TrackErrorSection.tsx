import { explorerTrackUrl } from "src/lib/trackExplorer";

/* Mirrors the `track_error` block of race_intel.json schema v6
   (built by model-notebooks/race_intelligence.py). */

export interface TrackErrorRound {
  round: number;
  name: string;
  explorerSlug: string | null;
  mean_abs_position_error: number;
  dnf_rate: number;
  n_scored: number;
  cornerCount: number;
  longestStraightMeters: number;
  lengthMeters: number;
  altitudeMeters: number;
  drsZones: number;
  direction: string;
  continent: string;
  firstGp: number;
}

export interface TrackError {
  n_rounds: number;
  rounds: TrackErrorRound[];
  correlation: Record<
    string,
    { n: number; pearson: number | null; spearman: number | null }
  >;
  caveat: string;
}

const TRAIT_LABEL: Record<string, string> = {
  cornerCount: "Corner count",
  longestStraightMeters: "Longest straight",
  lengthMeters: "Lap length",
  altitudeMeters: "Altitude",
  drsZones: "DRS zones",
  firstGp: "First GP held",
  clockwise: "Clockwise layout",
};

// A correlation is only worth colouring once it is big enough to notice at
// all — at n≈11 anything under 0.3 is noise wearing a sign.
const strength = (r: number | null) =>
  r == null
    ? "text-zinc-600"
    : Math.abs(r) < 0.3
      ? "text-zinc-500"
      : Math.abs(r) < 0.6
        ? "text-amber-400"
        : "text-red-400";

const TrackErrorSection = ({ trackError }: { trackError: TrackError }) => {
  const ranked = Object.entries(trackError.correlation).sort(
    (a, b) =>
      Math.abs(b[1].pearson ?? 0) - Math.abs(a[1].pearson ?? 0) ||
      a[0].localeCompare(b[0])
  );
  const th = "px-2 py-1.5 text-right font-medium text-zinc-500 whitespace-nowrap";
  const td = "px-2 py-1 text-right font-mono whitespace-nowrap";

  return (
    <section className="mt-8 rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
      <h3 className="text-sm font-semibold text-zinc-200">
        Where the model misses, by track shape
      </h3>
      <p className="mt-0.5 text-xs text-zinc-500 max-w-xl">
        Each raced round gets one error number — the mean absolute gap between
        a driver&apos;s simulated expected finish and where they actually
        classified — and is correlated against the Track Explorer&apos;s
        circuit-shape facts for that venue.
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        {ranked.map(([trait, entry]) => (
          <span
            key={trait}
            className="rounded-full border border-zinc-800 bg-zinc-950/60 px-2.5 py-1 text-[11px]"
          >
            <span className="text-zinc-400">{TRAIT_LABEL[trait] ?? trait}</span>{" "}
            <span className={`font-mono ${strength(entry.pearson)}`}>
              r {entry.pearson == null ? "—" : entry.pearson.toFixed(2)}
            </span>{" "}
            <span className="font-mono text-zinc-600">
              ρ {entry.spearman == null ? "—" : entry.spearman.toFixed(2)}
            </span>
            <span className="text-zinc-600"> · n{entry.n}</span>
          </span>
        ))}
      </div>

      <div className="mt-4 max-h-80 overflow-auto rounded-lg border border-zinc-800 bg-zinc-950/40">
        <table className="w-full text-[11px]">
          <thead className="sticky top-0 bg-zinc-950/95 text-zinc-500">
            <tr>
              <th className="px-2 py-1.5 text-left font-medium">Round</th>
              <th className={th}>Mean position error</th>
              <th className={th}>DNF rate</th>
              <th className={th}>Corners</th>
              <th className={th}>Spin</th>
              <th className={th}>Longest straight</th>
              <th className={th}>Altitude</th>
              <th className={th}>DRS</th>
            </tr>
          </thead>
          <tbody className="text-zinc-300">
            {trackError.rounds.map((r) => {
              const href = explorerTrackUrl({ explorerSlug: r.explorerSlug });
              return (
                <tr key={r.round} className="border-t border-zinc-800/60">
                  <td className="px-2 py-1 text-left whitespace-nowrap">
                    <span className="font-mono text-zinc-500">R{r.round}</span>{" "}
                    {href ? (
                      <a href={href} className="text-zinc-200 hover:text-red-400">
                        {r.name}
                      </a>
                    ) : (
                      <span className="text-zinc-200">{r.name}</span>
                    )}
                  </td>
                  <td className={`${td} ${r.mean_abs_position_error >= 4.5 ? "text-red-400" : "text-zinc-200"}`}>
                    {r.mean_abs_position_error.toFixed(2)}
                  </td>
                  <td className={td}>{(r.dnf_rate * 100).toFixed(0)}%</td>
                  <td className={td}>{r.cornerCount}</td>
                  <td className={`${td} text-zinc-400`}>
                    {r.direction === "Clockwise" ? "CW" : "ACW"}
                  </td>
                  <td className={td}>{r.longestStraightMeters} m</td>
                  <td className={td}>{r.altitudeMeters} m</td>
                  <td className={td}>{r.drsZones}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-[11px] text-zinc-500 max-w-xl">{trackError.caveat}</p>
    </section>
  );
};

export default TrackErrorSection;
