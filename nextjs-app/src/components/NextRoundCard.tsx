import { useEffect, useState } from "react";
import Link from "next/link";

import { NEXT_PUBLIC_API_URL } from "src/lib/constants";

interface CircuitInfo {
  circuitId: string;
  name: string;
  location: string;
  country: string;
  lat: number | null;
  lng: number | null;
}

interface RoundSummary {
  year: number;
  round: number;
  name: string;
  date: string;
  status: "raced" | "upcoming_post_quali" | "scheduled";
  n_drivers: number;
  circuit?: CircuitInfo;
}

interface NextRoundDoc {
  season: number;
  season_complete: boolean;
  race: RoundSummary;
}

const SUBTITLE: Record<RoundSummary["status"], string> = {
  scheduled: "Qualifying not yet done — probabilities use championship order as the grid.",
  upcoming_post_quali: "Qualifying complete — probabilities run on the real grid.",
  raced: "Season complete — review every round's prediction against reality.",
};

const STATUS_LABEL: Record<RoundSummary["status"], string> = {
  scheduled: "Scheduled",
  upcoming_post_quali: "Post-quali",
  raced: "Raced",
};

const NextRoundCard = () => {
  const [doc, setDoc] = useState<NextRoundDoc | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${NEXT_PUBLIC_API_URL}/api/race-intel/next-round`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`API ${res.status}`))))
      .then((body: NextRoundDoc) => {
        if (!cancelled) setDoc(body);
      })
      .catch(() => {
        // cold/failed API: the landing page must not show a broken shell
        if (!cancelled) setDoc(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!doc) return null;

  const raceDate = new Date(`${doc.race.date}T00:00:00`);
  const dateText = Number.isNaN(raceDate.getTime())
    ? doc.race.date
    : raceDate.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });

  return (
    <section className="mb-8 whitespace-normal rounded-lg border border-[rgba(55,53,47,0.14)] bg-[rgba(241,241,239,0.6)] p-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-sm font-semibold uppercase tracking-wide text-[rgba(212,76,71,1)]">
          {doc.season_complete ? "Season" : `Round ${doc.race.round}`} · {doc.season}
        </span>
        <span className="text-sm text-[rgba(120,119,116,1)]">{STATUS_LABEL[doc.race.status]}</span>
      </div>
      <h2 className="mt-1 text-xl font-bold">{doc.race.name}</h2>
      {doc.race.circuit?.location && (
        <p className="mt-0.5 text-sm text-[rgba(120,119,116,1)]">
          {doc.race.circuit.location}
          {doc.race.circuit.country ? `, ${doc.race.circuit.country}` : ""}
        </p>
      )}
      <p className="mt-0.5 text-sm text-[rgba(55,53,47,0.7)]">
        {dateText} · {doc.race.n_drivers} drivers · {SUBTITLE[doc.race.status]}
      </p>
      <Link
        href="/race-intel"
        className="mt-3 inline-block rounded-md border border-[rgba(212,76,71,0.4)] bg-[rgba(253,235,236,1)] px-4 py-1.5 text-sm font-medium text-[rgba(212,76,71,1)] no-underline hover:bg-[rgba(212,76,71,0.12)]"
      >
        Open Race Intelligence
      </Link>
    </section>
  );
};

export default NextRoundCard;
