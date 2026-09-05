import Image from "next/image";
import React, { useEffect, useState } from "react";
import { NEXT_PUBLIC_API_URL } from "../lib/constants";

type Roster = {
    drivers: string[];
    grandsPrix: string[];
    driverTeam: Record<string, string>;
    season: number;
};

/* Map Grand Prix names → Track Metrics Lab circuit slugs */
const GP_TO_CIRCUIT: Record<string, string> = {
    "Monaco Grand Prix": "monaco",
    "British Grand Prix": "silverstone",
    "Japanese Grand Prix": "suzuka",
    "Belgian Grand Prix": "spa",
    "Brazilian Grand Prix": "interlagos",
    "São Paulo Grand Prix": "interlagos",
    "Australian Grand Prix": "albert_park",
    "Bahrain Grand Prix": "bahrain",
    "Saudi Arabian Grand Prix": "jeddah",
    "Miami Grand Prix": "miami",
    "Emilia Romagna Grand Prix": "imola",
    "Spanish Grand Prix": "catalunya",
    "Canadian Grand Prix": "villeneuve",
    "Austrian Grand Prix": "spielberg",
    "French Grand Prix": "paul_ricard",
    "Hungarian Grand Prix": "hungaroring",
    "Dutch Grand Prix": "zandvoort",
    "Italian Grand Prix": "monza",
    "Singapore Grand Prix": "marina_bay",
    "Azerbaijan Grand Prix": "baku",
    "United States Grand Prix": "americas",
    "Mexico City Grand Prix": "rodriguez",
    "Mexican Grand Prix": "rodriguez",
    "Las Vegas Grand Prix": "las_vegas",
    "Qatar Grand Prix": "losail",
    "Abu Dhabi Grand Prix": "yas_marina",
    "Chinese Grand Prix": "shanghai",
    "70th Anniversary Grand Prix": "silverstone",
    "Styrian Grand Prix": "spielberg",
    "Eifel Grand Prix": "nurburgring",
    "Portuguese Grand Prix": "portimao",
    "Turkish Grand Prix": "istanbul",
    "Russian Grand Prix": "sochi",
    "Tuscan Grand Prix": "mugello",
    "Sakhir Grand Prix": "bahrain",
    "Barcelona Grand Prix": "catalunya",
};

const TRACK_METRICS_URL = "https://f1-track-metrics-lab.vercel.app";

/* ── Racing Loader Animation ── */
const RacingLoader = () => (
    <div className="relative w-full py-6 overflow-hidden">
        {/* Speed lines */}
        <div className="absolute inset-0 overflow-hidden">
            {[...Array(8)].map((_, i) => (
                <div
                    key={i}
                    className="absolute h-[1px] bg-gradient-to-r from-transparent via-red-500/40 to-transparent"
                    style={{
                        top: `${10 + i * 10}%`,
                        left: '-100%',
                        width: '60%',
                        animation: `speedLine ${0.8 + i * 0.15}s linear infinite`,
                        animationDelay: `${i * 0.1}s`,
                    }}
                />
            ))}
        </div>

        {/* Racing car */}
        <div className="relative flex items-center justify-center">
            <div className="flex items-center gap-3">
                <div
                    className="text-3xl"
                    style={{ animation: 'carBounce 0.6s ease-in-out infinite' }}
                >
                    🏎️
                </div>
                <div className="flex gap-1.5">
                    {[0, 1, 2].map((i) => (
                        <div
                            key={i}
                            className="w-2 h-2 rounded-full bg-red-500"
                            style={{
                                animation: 'pulse 1.2s ease-in-out infinite',
                                animationDelay: `${i * 0.3}s`,
                            }}
                        />
                    ))}
                </div>
            </div>
        </div>

        {/* Tachometer bar */}
        <div className="mt-4 w-full h-1.5 bg-stone-800 rounded-full overflow-hidden">
            <div
                className="h-full rounded-full bg-gradient-to-r from-red-600 via-red-500 to-orange-400"
                style={{ animation: 'tachometer 2s ease-in-out infinite' }}
            />
        </div>

        <style jsx>{`
            @keyframes speedLine {
                0% { transform: translateX(0); opacity: 0; }
                10% { opacity: 1; }
                90% { opacity: 1; }
                100% { transform: translateX(500%); opacity: 0; }
            }
            @keyframes carBounce {
                0%, 100% { transform: translateY(0) translateX(0); }
                25% { transform: translateY(-2px) translateX(2px); }
                75% { transform: translateY(1px) translateX(-1px); }
            }
            @keyframes pulse {
                0%, 100% { opacity: 0.3; transform: scale(0.8); }
                50% { opacity: 1; transform: scale(1.2); }
            }
            @keyframes tachometer {
                0% { width: 10%; }
                50% { width: 85%; }
                100% { width: 10%; }
            }
        `}</style>
    </div>
);

/* ── Result Reveal Animation ── */
const ResultReveal = ({ prediction, loading, coldStart }: {
    prediction: number;
    loading: boolean;
    coldStart: boolean;
}) => {
    const [visible, setVisible] = useState(false);

    useEffect(() => {
        if (!loading && prediction >= 0) {
            setVisible(true);
        }
    }, [loading, prediction]);

    if (loading) return null;

    const resultText = prediction === 1
        ? "🏅 Podium Finish!"
        : prediction === 2
        ? "🔢 Points Finish!"
        : prediction === 3
        ? "🅾️ Out of Points!"
        : "🛑 Something went wrong!!";

    const resultColor = prediction === 1
        ? "from-yellow-500/20 to-amber-500/10 border-yellow-500/30"
        : prediction === 2
        ? "from-green-500/20 to-emerald-500/10 border-green-500/30"
        : prediction === 3
        ? "from-stone-500/20 to-stone-600/10 border-stone-500/30"
        : "from-red-500/20 to-red-600/10 border-red-500/30";

    return (
        <section
            className={`my-6 flex w-full max-w-md flex-col gap-4 rounded-xl border bg-gradient-to-br p-8 transition-all duration-700 ${
                visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'
            } ${resultColor}`}
        >
            <h2 className="text-xl font-medium m-0 text-white">Prediction:</h2>
            <section className="flex w-full flex-col items-center gap-3 rounded-lg bg-[#161616] p-8 border border-stone-800">
                <p className="text-center font-bold text-2xl text-white">
                    {resultText}
                </p>
            </section>
        </section>
    );
};

const Predictor = () => {
    const [roster, setRoster] = useState<Roster | null>(null);
    const [rosterError, setRosterError] = useState(false);

    const [round, setRound] = useState("");
    const [driver, setDriver] = useState("");
    const [quali, setQuali] = useState(0);

    const [prediction, setPrediction] = useState(-1);
    const [loading, setLoading] = useState(false);
    const [coldStart, setColdStart] = useState(false);

    // fetch the live driver/GP list once on mount, instead of hardcoding
    // a season's roster that goes stale every year
    useEffect(() => {
        fetch(`${NEXT_PUBLIC_API_URL}/roster`)
            .then((res) => res.json())
            .then((data: Roster) => {
                setRoster(data);
                setRound(data.grandsPrix[0] ?? "");
                setDriver(data.drivers[0] ?? "");
            })
            .catch(() => {
                setRosterError(true);
            });
    }, []);

    const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault();

        setLoading(true);
        setColdStart(false);
        setPrediction(-2);

        // Show cold-start warning after 5 seconds
        const coldStartTimer = setTimeout(() => setColdStart(true), 5000);

        let myHeaders = new Headers();
        myHeaders.append("Content-Type", "application/json");

        let raw = JSON.stringify({
            name: driver,
            round: round,
            qualifying_pos: quali.toString(),
        });

        await fetch(`${NEXT_PUBLIC_API_URL}/predictGrid`, {
            method: "POST",
            headers: myHeaders,
            body: raw,
        })
            .then((response) => response.json())
            .then((result) => {
                clearTimeout(coldStartTimer);
                setPrediction(result[0]);
                setLoading(false);
                setColdStart(false);
            })
            .catch(() => {
                clearTimeout(coldStartTimer);
                setPrediction(0);
                setLoading(false);
                setColdStart(false);
            });
    };

    return (
        <>
            <div className="flex flex-col justify-center gap-4">
                <Image
                    src={"/f1-dark.png"}
                    width={100}
                    height={100}
                    alt={"Formula One Logo"}
                />
                <h1 className="text-4xl font-semibold m-0">Result Predictor</h1>
                <h2 className="text-xl opacity-60 m-0">Based on the Qualifying Position</h2>
            </div>
            <form
                className="my-10 flex w-full max-w-md flex-col gap-4 rounded-lg border-[1px] border-stone-800 bg-[#E6002B]/30 backdrop-blur-2xl p-8"
                onSubmit={handleSubmit}
            >
                <label className="flex flex-col gap-2 text-sm">
                    Season:
                    <input
                        className="rounded-lg border-[1px] border-stone-700 bg-stone-900 px-2 py-2 text-white outline-white"
                        type="number"
                        disabled
                        value={roster?.season ?? ""}
                    />
                </label>
                <label className="flex flex-col gap-2 text-sm">
                    Grand Prix:
                    <select
                        className="rounded-lg border-[1px] border-stone-700 bg-stone-900 px-2 py-2 text-white outline-white"
                        value={round}
                        onChange={(e) => setRound(e.target.value)}
                        disabled={!roster}
                    >
                        {roster?.grandsPrix.map((name) => (
                            <option key={name} value={name}>
                                {name}
                            </option>
                        ))}
                    </select>
                    {round && GP_TO_CIRCUIT[round] && (
                        <a
                            href={`${TRACK_METRICS_URL}?circuit=${GP_TO_CIRCUIT[round]}&mode=compare3d`}
                            target="_blank"
                            rel="noreferrer"
                            className="group mt-1 inline-flex items-center gap-2 rounded-md border border-blue-500/20 bg-blue-500/5 px-3 py-1.5 text-xs font-medium text-blue-400 transition-all hover:border-blue-400/40 hover:bg-blue-500/10 hover:text-blue-300"
                        >
                            🗺️ Explore this track in 3D
                            <svg className="h-3 w-3 opacity-60 transition-all group-hover:translate-x-0.5 group-hover:opacity-100" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                            </svg>
                        </a>
                    )}
                </label>
                <label className="flex flex-col gap-2 text-sm">
                    Driver:
                    <select
                        className="rounded-lg border-[1px] border-stone-700 bg-stone-900 px-2 py-2 text-white outline-white"
                        value={driver}
                        onChange={(e) => setDriver(e.target.value)}
                        disabled={!roster}
                    >
                        {roster?.drivers.map((name) => (
                            <option key={name} value={name}>
                                {name} {roster.driverTeam[name] ? `(${roster.driverTeam[name]})` : ""}
                            </option>
                        ))}
                    </select>
                </label>
                <label className="flex flex-col gap-2 text-sm">
                    Qualifying Position:
                    <input
                        className="rounded-lg border-[1px] border-stone-700 bg-stone-900 px-2 py-2 text-white outline-white"
                        type="number"
                        min={1}
                        max={22}
                        onChange={(e) => setQuali(Number(e.target.value))}
                    />
                </label>
                {rosterError && (
                    <p className="text-sm text-red-400">
                        Couldn&apos;t load the current driver/race list from the API. Is flask-app running?
                    </p>
                )}
                <button
                    className={`rounded-lg p-3 text-sm font-bold text-white transition-all duration-300 ease-in-out ${
                        loading
                            ? 'bg-red-900 cursor-wait animate-pulse'
                            : 'bg-gradient-to-r from-red-600 to-red-500 hover:from-red-500 hover:to-red-400 hover:shadow-lg hover:shadow-red-500/25 active:scale-95'
                    }`}
                    type="submit"
                    disabled={!roster || loading}
                >
                    {loading ? '⏳ Predicting...' : '🪄 Predict'}
                </button>
            </form>
            {loading && (
                <section className="my-6 flex w-full max-w-md flex-col gap-4 rounded-xl border border-stone-800 bg-[#111111] p-6">
                    <RacingLoader />
                    {coldStart && (
                        <p className="text-sm text-amber-400 text-center animate-pulse">
                            ⏳ Waking up the model server...
                        </p>
                    )}
                </section>
            )}
            {!loading && prediction >= 0 && (
                <ResultReveal
                    prediction={prediction}
                    loading={loading}
                    coldStart={coldStart}
                />
            )}

        </>
    );
};

export default Predictor;
