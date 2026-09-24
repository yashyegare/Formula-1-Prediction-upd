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

/* ── lap-curve replay doc — mirror flask-app/lap_curves.json schema v1 ── */

type CurvePoint = [lap: number, pPodium: number, pPoints: number, pOut: number, expectedPos: number];

interface LapCurveDriver {
  driverId: string;
  driverCode?: string;
  surname?: string;
  final_position: number | null;
  curve: CurvePoint[];
}

interface LapCurvesDoc {
  season: number;
  n_sims: number;
  races: Array<{
    year: number;
    round: number;
    n_laps: number;
    sample_laps: number[];
    drivers: LapCurveDriver[];
  }>;
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

type CurveMetric = "podium" | "points" | "out";

interface DriverCurvesDoc {
  season: number;
  driverId: string;
  driverCode: string;
  surname: string;
  races: Array<{
    round: number;
    n_laps: number;
    sample_laps: number[];
    final_position: number | null;
    curve: CurvePoint[];
  }>;
}

const CURVE_METRIC: Record<
  CurveMetric,
  { idx: 1 | 2 | 3; label: string }
> = {
  podium: { idx: 1, label: "P(podium)" },
  points: { idx: 2, label: "P(points)" },
  out: { idx: 3, label: "P(out)" },
};

const CURVE_COLORS = [
  "#f59e0b", "#34d399", "#60a5fa", "#f472b6", "#a78bfa",
  "#f87171", "#22d3ee", "#facc15",
];

const W = 600;
const H = 220;
const PAD = 10;

function ReplayChart({
  doc,
  metric,
  highlight,
}: {
  doc: NonNullable<LapCurvesDoc["races"][number]>;
  metric: CurveMetric;
  highlight: string | null;
}) {
  const mi = CURVE_METRIC[metric].idx;
  const shown = doc.drivers.slice(0, 8);
  const x = (lap: number) => PAD + (lap / doc.n_laps) * (W - 2 * PAD);
  const y = (p: number) => PAD + (1 - p) * (H - 2 * PAD);
  return (
    <svg
      viewBox={`0 0 ${W} ${H + 22}`}
      className="w-full"
      role="img"
      aria-label={`${CURVE_METRIC[metric].label} by lap`}
    >
      {/* horizontal gridlines: 0, 25, 50, 75, 100% */}
      {[0, 0.25, 0.5, 0.75, 1].map((p) => (
        <g key={p}>
          <line
            x1={PAD}
            x2={W - PAD}
            y1={y(p)}
            y2={y(p)}
            stroke="#27272a"
            strokeWidth={p === 0 || p === 1 ? 1 : 0.5}
          />
          <text x={2} y={y(p) + 3} fill="#71717a" fontSize={9}>
            {p * 100}%
          </text>
        </g>
      ))}
      {/* lap ticks */}
      {doc.sample_laps.map((lap) => (
        <text
          key={lap}
          x={x(lap)}
          y={H + 14}
          fill="#71717a"
          fontSize={9}
          textAnchor="middle"
        >
          L{lap}
        </text>
      ))}
      {/* one polyline per driver; the highlighted driver renders last
          (on top) and thicker */}
      {shown
        .slice()
        .sort((a) => (a.driverId === highlight ? 1 : -1))
        .map((d, i) => {
          const pts = d.curve
            .map((pt) => `${x(pt[0])},${y(pt[mi])}`)
            .join(" ");
          const isHi = d.driverId === highlight;
          return (
            <polyline
              key={d.driverId}
              points={pts}
              fill="none"
              stroke={CURVE_COLORS[i % CURVE_COLORS.length]}
              strokeWidth={isHi ? 3 : 1.5}
              opacity={highlight && !isHi ? 0.35 : 1}
            />
          );
        })}
    </svg>
  );
}

/* ═══════════════════════════════════════════════
   PAGE
   ═══════════════════════════════════════════════ */

const RaceIntelPage: NextPage = () => {
  const [season, setSeason] = useState<RaceIntelSeason | null>(null);
  const [selectedRound, setSelectedRound] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [curves, setCurves] = useState<LapCurvesDoc["races"][number] | null>(null);
  const [curvesMetric, setCurvesMetric] = useState<CurveMetric>("podium");
  const [highlight, setHighlight] = useState<string | null>(null);
  const [profile, setProfile] = useState<string | null>(null);
  const [profileCurves, setProfileCurves] = useState<DriverCurvesDoc | null>(null);

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

  // raced rounds get their replay curves (the /curves artifact)
  useEffect(() => {
    if (!race || race.status !== "raced") {
      setCurves(null);
      return;
    }
    let cancelled = false;
    setCurves(null);
    setHighlight(null);
    fetch(`${NEXT_PUBLIC_API_URL}/api/race-intel/curves/${race.year}/${race.round}`)
      .then(async (res) => {
        if (!res.ok) return null; // future round or artifact absent: no chart
        return (await res.json()) as LapCurvesDoc["races"][number];
      })
      .then((doc) => {
        if (!cancelled) setCurves(doc);
      })
      .catch(() => {
        if (!cancelled) setCurves(null);
      });
    return () => {
      cancelled = true;
    };
  }, [race]);

  // driver deep-dive: season-wide curve traces for the selected profile
  useEffect(() => {
    if (!profile || !season) {
      setProfileCurves(null);
      return;
    }
    let cancelled = false;
    setProfileCurves(null);
    fetch(
      `${NEXT_PUBLIC_API_URL}/api/race-intel/curves/${season.season}/driver/${profile}`,
    )
      .then(async (res) => {
        if (!res.ok) return null;
        return (await res.json()) as DriverCurvesDoc;
      })
      .then((doc) => {
        if (!cancelled) setProfileCurves(doc);
      })
      .catch(() => {
        if (!cancelled) setProfileCurves(null);
      });
    return () => {
      cancelled = true;
    };
  }, [profile, season]);

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
                          onMouseEnter={() => setHighlight(d.driverId)}
                          onMouseLeave={() => setHighlight(null)}
                          onClick={() =>
                            setProfile(profile === d.driverId ? null : d.driverId)
                          }
                          className={[
                            "border-b border-zinc-900 last:border-0 hover:bg-zinc-900/40 cursor-pointer",
                            profile === d.driverId ? "bg-red-950/20" : "",
                          ].join(" ")}
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

              {/* lap-by-lap replay (raced rounds only) */}
              {race?.status === "raced" && (
                <section className="mt-8 rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-semibold text-zinc-200">
                        Race replay — how the probabilities moved
                      </h3>
                      <p className="mt-0.5 text-xs text-zinc-500 max-w-xl">
                        The scenario simulator rerun at every sampled lap of the
                        actual race, conditioned on the running order as it
                        stood. Hover a driver row to trace their line.
                      </p>
                    </div>
                    <div className="flex gap-1">
                      {(Object.keys(CURVE_METRIC) as CurveMetric[]).map((m) => (
                        <button
                          key={m}
                          onClick={() => setCurvesMetric(m)}
                          className={[
                            "rounded-md px-2.5 py-1 text-xs font-medium border transition-colors",
                            curvesMetric === m
                              ? "border-red-500 bg-red-600/20 text-red-300"
                              : "border-zinc-800 bg-zinc-900 text-zinc-400 hover:border-zinc-600",
                          ].join(" ")}
                        >
                          {CURVE_METRIC[m].label}
                        </button>
                      ))}
                    </div>
                  </div>
                  {curves ? (
                    <ReplayChart
                      doc={curves}
                      metric={curvesMetric}
                      highlight={highlight}
                    />
                  ) : (
                    <p className="py-6 text-center text-xs text-zinc-500">
                      Lap curves unavailable for this round.
                    </p>
                  )}
                </section>
              )}

              {/* driver deep-dive panel */}
              {profile && (
                <section className="mt-4 rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
                  <div className="mb-3 flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-zinc-200">
                      {profileCurves?.driverCode ?? ""} {profileCurves?.surname ?? profile}
                      {" "}
                      — season replay
                    </h3>
                    <button
                      onClick={() => setProfile(null)}
                      className="text-xs text-zinc-500 hover:text-zinc-300"
                    >
                      close
                    </button>
                  </div>
                  {profileCurves ? (
                    <div className="flex flex-wrap gap-3">
                      {profileCurves.races.map((r) => {
                        const pts = r.curve
                          .map((pt) => `${(pt[0] / r.n_laps) * 100},${(1 - pt[1]) * 100}`)
                          .join(" ");
                        return (
                          <div key={r.round} className="w-28">
                            <svg viewBox="0 0 100 100" className="w-full" role="img"
                              aria-label={`Round ${r.round} P(podium) trace`}>
                              <line x1="0" y1="100" x2="100" y2="100" stroke="#27272a" strokeWidth="1" />
                              <polyline points={pts} fill="none" stroke="#f59e0b" strokeWidth="3" />
                            </svg>
                            <p className="mt-1 text-center text-[10px] text-zinc-500">
                              R{r.round}
                              {r.final_position ? (
                                <span className={
                                  r.final_position <= 3
                                    ? " text-emerald-400"
                                    : r.final_position <= 10
                                      ? " text-zinc-300"
                                      : " text-rose-400"
                                }>
                                  {" "}P{r.final_position}
                                </span>
                              ) : (
                                <span className="text-rose-400"> DNF</span>
                              )}
                            </p>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="py-6 text-center text-xs text-zinc-500">
                      Loading season traces…
                    </p>
                    )}
                </section>
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
