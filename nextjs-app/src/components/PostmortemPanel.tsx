import { useEffect, useState } from "react";
import Link from "next/link";

/* Mirrors GET /api/me/prediction/postmortem (flask-app/predictions_api.py) */

interface PostmortemMiss {
  driverId: string;
  surname: string;
  predicted_position: number;
  actual_position: number | null;
  verdict: string;
  status: string;
  grid_start: number | null;
  sim_expected_position: number | null;
}

interface PostmortemRace {
  round: number;
  name: string;
  date: string;
  predictions_scored: number;
  mean_abs_error: number | null;
  verdict_counts: Record<string, number>;
  misses: PostmortemMiss[];
}

interface PostmortemDoc {
  season: number;
  races_scored: number;
  predictions_scored: number;
  hit_rate: number | null;
  verdict_share: Record<string, number>;
  races: PostmortemRace[];
}

const VERDICT_LABEL: Record<string, string> = {
  exact: "Nailed it",
  near: "Near miss",
  over_predict: "Finished worse",
  under_predict: "Finished better",
  dnf_mech: "DNF — mechanical",
  dnf_driver: "DNF — driver error",
  dnf_other: "DNF",
  unknown: "No result",
};

const VERDICT_COLOR: Record<string, string> = {
  exact: "text-emerald-400 border-emerald-800/60 bg-emerald-950/30",
  near: "text-zinc-300 border-zinc-700 bg-zinc-800/40",
  over_predict: "text-rose-400 border-rose-900/60 bg-rose-950/30",
  under_predict: "text-sky-400 border-sky-900/60 bg-sky-950/30",
  dnf_mech: "text-amber-400 border-amber-900/60 bg-amber-950/30",
  dnf_driver: "text-amber-400 border-amber-900/60 bg-amber-950/30",
  dnf_other: "text-amber-400 border-amber-900/60 bg-amber-950/30",
};

const chip = (verdict: string) =>
  `rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${
    VERDICT_COLOR[verdict] ?? "border-zinc-700 bg-zinc-800/40 text-zinc-400"
  }`;

type PanelState =
  | { kind: "loading" }
  | { kind: "anonymous" }
  | { kind: "no_prediction" }
  | { kind: "error"; message: string }
  | { kind: "ready"; doc: PostmortemDoc };

const PostmortemPanel = ({ season }: { season: number }) => {
  const [state, setState] = useState<PanelState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/me/prediction/postmortem?season=${season}`, {
      credentials: "include",
    })
      .then(async (res) => {
        if (res.status === 401) return setState({ kind: "anonymous" });
        if (res.status === 404) return setState({ kind: "no_prediction" });
        const body = await res.json().catch(() => null);
        if (!res.ok) {
          return setState({ kind: "error", message: body?.error ?? `API ${res.status}` });
        }
        if (!cancelled) setState({ kind: "ready", doc: body });
      })
      .catch(() => {
        if (!cancelled) setState({ kind: "error", message: "Postmortem unavailable" });
      });
    return () => {
      cancelled = true;
    };
  }, [season]);

  return (
    <section className="mt-8 rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
      <h3 className="text-sm font-semibold text-zinc-200">
        Why your picks missed — {season} season postmortem
      </h3>
      <p className="mt-0.5 text-xs text-zinc-500 max-w-xl">
        Your locked predictions joined against the same outcome evidence the
        model&apos;s attribution uses: every miss labelled Nailed it / Near
        miss / Finished worse / Finished better / DNF, with the race result as
        proof.
      </p>

      {state.kind === "loading" && (
        <p className="py-6 text-center text-xs text-zinc-500">Loading your postmortem…</p>
      )}

      {state.kind === "anonymous" && (
        <p className="mt-3 text-xs text-zinc-400">
          Sign in and save your season predictions to see this.{" "}
          <Link href="/" className="text-red-400 hover:underline">
            Go to the Predictor
          </Link>
        </p>
      )}

      {state.kind === "no_prediction" && (
        <p className="mt-3 text-xs text-zinc-400">
          No prediction saved for {season} yet.{" "}
          <Link href="/" className="text-red-400 hover:underline">
            Make one in the Predictor
          </Link>
        </p>
      )}

      {state.kind === "error" && (
        <p className="mt-3 text-xs text-zinc-400">{state.message}</p>
      )}

      {state.kind === "ready" && state.doc.predictions_scored > 0 && (
        <div className="mt-4">
          <div className="mb-4 flex flex-wrap items-center gap-2 text-xs">
            <span className="font-mono text-lg text-zinc-100">
              {(state.doc.hit_rate != null ? state.doc.hit_rate * 100 : 0).toFixed(1)}%
            </span>
            <span className="text-zinc-500">
              of {state.doc.predictions_scored} predicted placements landed within 2 places
              across {state.doc.races_scored} raced rounds
            </span>
            {Object.entries(state.doc.verdict_share)
              .filter(([k]) => k !== "exact" && k !== "near")
              .sort((a, b) => b[1] - a[1])
              .map(([k, v]) => (
                <span key={k} className={chip(k)}>
                  {VERDICT_LABEL[k] ?? k} {(v * 100).toFixed(0)}%
                </span>
              ))}
          </div>
          <div className="flex flex-col gap-4">
            {state.doc.races.map((race) => (
              <div key={race.round} className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-4">
                <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-xs font-semibold text-zinc-300">
                    R{race.round} · {race.name}
                  </p>
                  <p className="text-[11px] text-zinc-500">
                    {race.predictions_scored} picks scored
                    {race.mean_abs_error != null && (
                      <> · mean error {race.mean_abs_error} places</>
                    )}
                  </p>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(race.verdict_counts).map(([k, n]) => (
                    <span key={k} className={chip(k)}>
                      {VERDICT_LABEL[k] ?? k} ×{n}
                    </span>
                  ))}
                </div>
                {race.misses.length > 0 && (
                  <ul className="mt-3 flex flex-col gap-1">
                    {race.misses.map((m) => (
                      <li key={m.driverId} className="text-[11px] text-zinc-400">
                        <span className="text-zinc-200">{m.surname}</span>: picked P
                        {m.predicted_position} →{" "}
                        {m.actual_position != null ? `P${m.actual_position}` : "no classified finish"}
                        {" · "}
                        <span className={VERDICT_COLOR[m.verdict]?.split(" ")[0] ?? "text-zinc-400"}>
                          {VERDICT_LABEL[m.verdict] ?? m.verdict}
                        </span>
                        {m.status && m.status !== "Finished" && <> · {m.status}</>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {state.kind === "ready" && state.doc.predictions_scored === 0 && (
        <p className="mt-3 text-xs text-zinc-400">
          Your prediction doesn&apos;t overlap any raced rounds of {season} yet —
          lock picks before a GP and they show up here afterwards.
        </p>
      )}
    </section>
  );
};

export default PostmortemPanel;
