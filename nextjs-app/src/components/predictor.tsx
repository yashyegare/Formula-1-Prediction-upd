import Image from "next/image";
import React, { useEffect, useState } from "react";
import { NEXT_PUBLIC_API_URL } from "../lib/constants";

type Roster = {
    drivers: string[];
    grandsPrix: string[];
    driverTeam: Record<string, string>;
    season: number;
};

const Predictor = () => {
    const [roster, setRoster] = useState<Roster | null>(null);
    const [rosterError, setRosterError] = useState(false);

    const [round, setRound] = useState("");
    const [driver, setDriver] = useState("");
    const [quali, setQuali] = useState(0);

    const [prediction, setPrediction] = useState(-1);
    const [loading, setLoading] = useState(false);

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
            .catch((error) => {
                console.log("error fetching roster", error);
                setRosterError(true);
            });
    }, []);

    const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault();

        setLoading(true);
        setPrediction(-2);

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
                setPrediction(result[0]);
                setLoading(false);
            })
            .catch((error) => {
                setPrediction(0);
                console.log("error", error);
                setLoading(false);
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
                    className="rounded-lg bg-white p-2 text-sm font-medium text-black transition-all ease-in-out hover:shadow-2xl disabled:bg-orange-900"
                    type="submit"
                    disabled={!roster}
                >
                    🪄 Predict
                </button>
            </form>
            {prediction != -1 && (
                <section className="my-10 flex w-full max-w-md flex-col gap-4 rounded-lg border-[1px] border-stone-800 bg-[#111111] p-8">
                    <h2 className="text-xl font-medium m-0">Prediction:</h2>
                    <section className="flex w-full max-w-md flex-col gap-4 rounded-lg border-[1px] border-stone-500 bg-[#161616] p-8">
                        <p className="text-center font-medium text-2xl">
                            {!loading
                                ? prediction == 1
                                    ? "🏅Podium Finish!"
                                    : prediction == 2
                                    ? "🔢 Points Finish!"
                                    : prediction == 3
                                    ? "🅾️ Out of Points!"
                                    : "🛑 Something went wrong!!"
                                : "Loading..."}
                        </p>
                    </section>
                </section>
            )}
        </>
    );
};

export default Predictor;
