import { useEffect, useState } from "react";
import Link from "next/link";

/* Mirrors GET /api/me/prediction/reconcile (flask-app/predictions_api.py) */

interface ReconcileRow {
  driverId: string;
  surname: string;
  driverCode: string;
  constructorId: string;
  simulated: number | null;
  model_season: number;
  model_raced: number;
  actual_raced: number;
  sim_minus_model: number | null;
  model_minus_actual: number;
}

interface ReconcileDoc {
  season: number;
  has_simulated_standings: boolean;
  rounds_in_artifact: number;
  raced_rounds: number;
  drivers: ReconcileRow[];
  totals: {
    simulated: number | null;
    model_season: number;
    model_raced: number;
    actual_raced: number;
  };
}

const SIMULATOR_URL = "https://formula-1-prediction-upd-fxzg.vercel.app";

const num = (v: number | null) => (v == null ? "—" : v.toFixed(v % 1 ? 1 : 0));

// A delta of 0.0 is a tie, not a signal, so it stays neutral grey.
const delta = (v: number | null) =>
  v == null
    ? { text: "—", className: "text-zinc-600" }
    : {
        text: `${v > 0 ? "+" : ""}${v.toFixed(1)}`,
        className:
          Math.abs(v) < 0.05
            ? "text-zinc-500"
            : v > 0
              ? "text-emerald-400"
              : "text-rose-400",
      };

type PanelState =
  | { kind: "loading" }
  | { kind: "anonymous" }
  | { kind: "no_prediction" }
  | { kind: "error"; message: string }
  | { kind: "ready"; doc: ReconcileDoc };

const ReconcilePanel = ({ season }: { season: number }) => {
  const [state, setState] = useState<PanelState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/me/prediction/reconcile?season=${season}`, {
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
        if (!cancelled) setState({ kind: "error", message: "Reconciliation unavailable" });
      });
    return () => {
      cancelled = true;
    };
  }, [season]);

  const th = "px-2 py-1.5 text-right font-medium text-zinc-500 whitespace-nowrap";
  const td = "px-2 py-1 text-right font-mono whitespace-nowrap";

  return (
    <section className="mt-8 rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
      <h3 className="text-sm font-semibold text-zinc-200">
        Season reconciliation — your simulator, the model, and what happened
      </h3>
      <p className="mt-0.5 text-xs text-zinc-500 max-w-xl">
        Three point currencies per driver: the championship points your Season
        Simulator grid projects, the points the Monte-Carlo model expected, and
        the points actually scored. The model is shown twice because the three
        don&apos;t share a denominator — season-long against your grid, raced
        rounds only against reality.
      </p>

      {state.kind === "loading" && (
        <p className="py-6 text-center text-xs text-zinc-500">Loading your reconciliation…</p>
      )}

      {state.kind === "anonymous" && (
        <p className="mt-3 text-xs text-zinc-400">
          Sign in and save a prediction to see this.{" "}
          <Link href="/" className="text-red-400 hover:underline">
            Go to the Predictor
          </Link>
        </p>
      )}

      {state.kind === "no_prediction" && (
        <p className="mt-3 text-xs text-zinc-400">
          No prediction saved for {season} yet.{" "}
          <a href={SIMULATOR_URL} className="text-red-400 hover:underline">
            Build one in the Season Simulator
          </a>
        </p>
      )}

      {state.kind === "error" && (
        <p className="mt-3 text-xs text-zinc-400">{state.message}</p>
      )}

      {state.kind === "ready" && !state.doc.has_simulated_standings && (
        <p className="mt-3 text-xs text-zinc-400">
          Your saved prediction carries no simulated standings yet — the
          simulator ships them with its autosave.{" "}
          <a href={SIMULATOR_URL} className="text-red-400 hover:underline">
            Open the Season Simulator
          </a>{" "}
          and move any driver; the next autosave fills the left columns.
        </p>
      )}

      {state.kind === "ready" && (
        <div className="mt-4">
          <p className="mb-2 text-[11px] text-zinc-500">
            {state.doc.raced_rounds} of {state.doc.rounds_in_artifact} rounds
            raced · totals{" "}
            <span className="font-mono text-zinc-300">
              {num(state.doc.totals.simulated)} your grid /{" "}
              {num(state.doc.totals.model_season)} model /{" "}
              {num(state.doc.totals.actual_raced)} actual
            </span>
          </p>
          <div className="max-h-96 overflow-auto rounded-lg border border-zinc-800 bg-zinc-950/40">
            <table className="w-full text-[11px]">
              <thead className="sticky top-0 bg-zinc-950/95 text-zinc-500">
                <tr>
                  <th className="px-2 py-1.5 text-left font-medium">Driver</th>
                  <th className={th}>Your grid</th>
                  <th className={th}>Model</th>
                  <th className={th}>You − Model</th>
                  <th className={th}>Model (raced)</th>
                  <th className={th}>Actual (raced)</th>
                  <th className={th}>Model − Actual</th>
                </tr>
              </thead>
              <tbody className="text-zinc-300">
                {state.doc.drivers.map((d) => {
                  const youVsModel = delta(d.sim_minus_model);
                  const modelVsReal = delta(d.model_minus_actual);
                  return (
                    <tr key={d.driverId} className="border-t border-zinc-800/60">
                      <td className="px-2 py-1 text-left">
                        <span className="font-mono text-zinc-500">{d.driverCode}</span>{" "}
                        <span className="text-zinc-200">{d.surname}</span>
                        {d.simulated == null && (
                          <span className="ml-1 text-zinc-600">(not in your standings)</span>
                        )}
                      </td>
                      <td className={td}>{num(d.simulated)}</td>
                      <td className={td}>{num(d.model_season)}</td>
                      <td className={`${td} ${youVsModel.className}`}>{youVsModel.text}</td>
                      <td className={td}>{num(d.model_raced)}</td>
                      <td className={td}>{num(d.actual_raced)}</td>
                      <td className={`${td} ${modelVsReal.className}`}>{modelVsReal.text}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
};

export default ReconcilePanel;
