import { type NextPage } from "next";
import Head from "next/head";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { NEXT_PUBLIC_API_URL } from "src/lib/constants";

/* ═══════════════════════════════════════════════
   TYPES — mirror flask-app/race_intelligence_api.py
   ═══════════════════════════════════════════════ */

interface RaceIntelDriver {
  driverId: string;
  driverCode: string;
  surname: string;
  constructorId: string;
  grid: number;
  p_podium: number;
  p_points: number;
  p_out: number;
  expected_position: number;
  sim_dnf_rate: number;
  /** present only on raced rounds */
  observed_swing?: number | null;
  sim_swing_mean?: number;
}

interface RaceIntelRace {
  year: number;
  round: number;
  name: string;
  date: string;
  status: "raced" | "upcoming_post_quali" | "scheduled";
  n_drivers: number;
  drivers: RaceIntelDriver[];
}

interface RaceIntelSeason {
  season: number;
  n_sims: number;
  next_round: number | null;
  mechanism: { swing_mean: number; swing_sd: number; dnf_rate: number };
  races: RaceIntelRace[];
  season_attribution: {
    accuracy: number;
    n_misses: number;
    cause_share: Record<string, number>;
    evidence: Record<string, number>;
  };
}

const STATUS_LABEL: Record<RaceIntelRace["status"], string> = {
  raced: "Raced",
  upcoming_post_quali: "Post-quali",
  scheduled: "Scheduled",
};

/* ═══════════════════════════════════════════════
   PRESENTATION HELPERS
   ═══════════════════════════════════════════════ */

function pct(p: number): string {
  return `${(p * 100).toFixed(1)}%`;
}

function swing(s: number): string {
  const v = s > 0 ? `+${s}` : `${s}`;
  return v;
}

function swingColor(s: number | null | undefined): string {
  if (s === null || s === undefined) return "text-zinc-500";
  // positive = gained places on race day (grid P10 -> flag P6)
  return s > 0 ? "text-emerald-400" : s < 0 ? "text-rose-400" : "text-zinc-400";
}

/* ═══════════════════════════════════════════════
   PAGE
   ═══════════════════════════════════════════════ */

const RaceIntelPage: NextPage = () => {
  const [season, setSeason] = useState<RaceIntelSeason | null>(null);
  const [selectedRound, setSelectedRound] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(`${NEXT_PUBLIC_API_URL}/api/race-intel/season/2026`)
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw new Error(body?.error ?? `API ${res.status}`);
        }
        return res.json();
      })
      .then((doc: RaceIntelSeason) => {
        if (cancelled) return;
        setSeason(doc);
        // land on the next race — the pre-race view
        const next = doc.races.find((r) => r.round === doc.next_round);
        setSelectedRound(next ? next.round : doc.races[doc.races.length - 1]?.round ?? null);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const race = useMemo(
    () => season?.races.find((r) => r.round === selectedRound) ?? null,
    [season, selectedRound],
  );

  const drivers = useMemo(() => {
    if (!race) return [];
    return [...race.drivers].sort(
      (a, b) => a.expected_position - b.expected_position,
    );
  }, [race]);

  return (
    <>
      <Head>
        <title>Race Intelligence — F1 Race Predictor</title>
        <meta
          name="description"
          content="Simulated outcome distributions and post-race swing insight per driver, per race"
        />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      <main className="min-h-screen bg-[#0e0e0e] text-zinc-100 font-inter">
        <div className="mx-auto max-w-5xl px-6 py-10">
          <header className="mb-8">
            <p className="text-xs uppercase tracking-[0.25em] text-red-500 mb-2">
              <Link href="/" className="hover:underline">
                ← F1 Race Predictor
              </Link>
            </p>
            <h1 className="text-3xl font-extrabold tracking-tight">
              Race Intelligence
            </h1>
            <p className="mt-2 text-sm text-zinc-400 max-w-2xl">
              Outcome distributions from {season?.n_sims ?? "—"} Monte Carlo
              simulations per race. Future rounds are{" "}
              <span className="text-zinc-300">pre-race predictions</span>; raced
              rounds show each driver&apos;s realized grid→finish swing against
              what the model expected — the{" "}
              <span className="text-zinc-300">why it happened</span> view.
            </p>
          </header>

          {loading && (
            <div className="py-24 text-center text-zinc-500">
              Loading race intelligence…
            </div>
          )}

          {error && (
            <div className="rounded-lg border border-red-900/60 bg-red-950/40 p-6 text-sm">
              <p className="font-semibold text-red-400 mb-1">
                Race intelligence is unavailable
              </p>
              <p className="text-zinc-400">{error}</p>
            </div>
          )}

          {season && (
            <>
              {/* race selector */}
              <div className="mb-6 flex flex-wrap gap-2">
                {season.races.map((r) => {
                  const active = r.round === selectedRound;
                  return (
                    <button
                      key={r.round}
                      onClick={() => setSelectedRound(r.round)}
                      className={[
                        "rounded-full px-3 py-1.5 text-xs font-medium border transition-colors",
                        active
                          ? "border-red-500 bg-red-600/20 text-red-300"
                          : "border-zinc-800 bg-zinc-900/60 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200",
                      ].join(" ")}
                      title={`${r.name} — ${STATUS_LABEL[r.status]}`}
                    >
                      R{r.round}
                      <span
                        className={[
                          "ml-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle",
                          r.status === "raced"
                            ? "bg-emerald-500"
                            : r.status === "upcoming_post_quali"
                              ? "bg-amber-400"
                              : "bg-zinc-600",
                        ].join(" ")}
                      />
                    </button>
                  );
                })}
              </div>

              {/* selected race header */}
              {race && (
                <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
                  <div>
                    <h2 className="text-xl font-bold">{race.name}</h2>
                    <p className="text-xs text-zinc-500">
                      Round {race.round} · {race.date} ·{" "}
                      <span
                        className={
                          race.status === "raced"
                            ? "text-emerald-400"
                            : "text-amber-400"
                        }
                      >
                        {STATUS_LABEL[race.status]}
                      </span>
                      {race.status !== "raced" && (
                        <span className="text-zinc-600">
                          {" "}
                          · grid ={" "}
                          {race.status === "upcoming_post_quali"
                            ? "qualifying result"
                            : "championship order"}
                        </span>
                      )}
                    </p>
                  </div>
                </div>
              )}

              {/* driver table */}
              {race && (
                <div className="overflow-x-auto rounded-xl border border-zinc-800">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-zinc-800 text-left text-[11px] uppercase tracking-wider text-zinc-500">
                        <th className="px-4 py-3 font-medium">Grid</th>
                        <th className="px-4 py-3 font-medium">Driver</th>
                        <th className="px-4 py-3 font-medium">Team</th>
                        <th className="px-4 py-3 font-medium text-right">
                          E[Pos]
                        </th>
                        <th className="px-4 py-3 font-medium">Podium</th>
                        <th className="px-4 py-3 font-medium">Points</th>
                        <th className="px-4 py-3 font-medium">Out</th>
                        {race.status === "raced" && (
                          <th className="px-4 py-3 font-medium text-right">
                            Swing
                          </th>
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {drivers.map((d) => (
                        <tr
                          key={d.driverId}
                          className="border-b border-zinc-900 last:border-0 hover:bg-zinc-900/40"
                        >
                          <td className="px-4 py-2.5 font-mono text-zinc-400">
                            P{d.grid}
                          </td>
                          <td className="px-4 py-2.5">
                            <span className="font-mono text-[11px] text-red-400 mr-2">
                              {d.driverCode}
                            </span>
                            <span className="font-semibold">{d.surname}</span>
                          </td>
                          <td className="px-4 py-2.5 text-zinc-400 capitalize">
                            {d.constructorId}
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono text-zinc-300">
                            {d.expected_position.toFixed(1)}
                          </td>
                          <td className="px-4 py-2.5">
                            <div className="flex items-center gap-2">
                              <div className="h-1.5 w-16 overflow-hidden rounded-full bg-zinc-800">
                                <div
                                  className="h-full rounded-full bg-amber-400"
                                  style={{
                                    width: `${Math.max(d.p_podium * 100, 1).toFixed(1)}%`,
                                  }}
                                />
                              </div>
                              <span className="font-mono text-xs text-zinc-300">
                                {pct(d.p_podium)}
                              </span>
                            </div>
                          </td>
                          <td className="px-4 py-2.5">
                            <div className="flex items-center gap-2">
                              <div className="h-1.5 w-16 overflow-hidden rounded-full bg-zinc-800">
                                <div
                                  className="h-full rounded-full bg-emerald-500"
                                  style={{
                                    width: `${Math.max(d.p_points * 100, 1).toFixed(1)}%`,
                                  }}
                                />
                              </div>
                              <span className="font-mono text-xs text-zinc-300">
                                {pct(d.p_points)}
                              </span>
                            </div>
                          </td>
                          <td className="px-4 py-2.5">
                            <div className="flex items-center gap-2">
                              <div className="h-1.5 w-16 overflow-hidden rounded-full bg-zinc-800">
                                <div
                                  className="h-full rounded-full bg-rose-500"
                                  style={{
                                    width: `${Math.max(d.p_out * 100, 1).toFixed(1)}%`,
                                  }}
                                />
                              </div>
                              <span className="font-mono text-xs text-zinc-300">
                                {pct(d.p_out)}
                              </span>
                            </div>
                          </td>
                          {race.status === "raced" && (
                            <td
                              className={`px-4 py-2.5 text-right font-mono text-xs ${swingColor(d.observed_swing)}`}
                              title={`model expected ${d.sim_swing_mean ?? "—"} places`}
                            >
                              {d.observed_swing === null ||
                              d.observed_swing === undefined
                                ? "—"
                                : `${swing(d.observed_swing)} (exp ${d.sim_swing_mean ?? "—"})`}
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* season attribution footer */}
              {season && (
                <footer className="mt-8 rounded-xl border border-zinc-800 bg-zinc-900/40 p-5 text-xs text-zinc-400">
                  <p className="mb-2 font-semibold text-zinc-300">
                    Why the model misses — {season.season} season attribution
                  </p>
                  <p>
                    Baseline accuracy{" "}
                    <span className="font-mono text-zinc-200">
                      {pct(season.season_attribution.accuracy)}
                    </span>{" "}
                    over {season.season_attribution.n_misses} misses:{" "}
                    {Object.entries(season.season_attribution.cause_share)
                      .filter(([, v]) => v > 0)
                      .map(([k, v]) => `${k.replace("dnf_", "DNF ")} ${pct(v)}`)
                      .join(" · ")}
                  </p>
                  <p className="mt-1.5 text-zinc-500">
                    Mechanism: swing ~ N({season.mechanism.swing_mean},{" "}
                    {season.mechanism.swing_sd}) places · DNF rate{" "}
                    {pct(season.mechanism.dnf_rate)} — fitted on{" "}
                    strictly-prior seasons only.
                  </p>
                </footer>
              )}
            </>
          )}
        </div>
      </main>
    </>
  );
};

export default RaceIntelPage;
