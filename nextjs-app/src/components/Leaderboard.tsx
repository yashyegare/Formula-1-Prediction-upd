import { useEffect, useState } from "react";
import { getLeaderboard, AuthUser } from "../lib/auth";

interface LeaderboardEntry {
  rank: number;
  name: string;
  accuracy: number;
  racesScored: number;
  exactMatches: number;
}

interface LeaderboardProps {
  currentUser?: AuthUser | null;
}

export default function Leaderboard({ currentUser }: LeaderboardProps) {
  const [entries, setEntries] = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [season] = useState(2026);

  useEffect(() => {
    setLoading(true);
    getLeaderboard(season)
      .then((data) => {
        if (data?.entries) setEntries(data.entries);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [season]);

  return (
    <div className="w-full max-w-md rounded-xl border border-stone-800 bg-[#111] p-6 mt-8">
      <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
        <span>🏆</span> Leaderboard
        <span className="ml-auto text-xs font-normal text-zinc-500">2026 Season</span>
      </h3>

      {loading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-10 animate-pulse rounded-lg bg-stone-800/50" />
          ))}
        </div>
      ) : entries.length === 0 ? (
        <p className="text-sm text-zinc-500 text-center py-6">
          No predictions yet. Be the first to submit!
        </p>
      ) : (
        <div className="space-y-1.5">
          {/* Header row */}
          <div className="grid grid-cols-[2rem_1fr_3.5rem_3rem] gap-2 px-2 text-[10px] font-medium uppercase tracking-wider text-zinc-600">
            <span>#</span>
            <span>Player</span>
            <span className="text-right">Accuracy</span>
            <span className="text-right">Exact</span>
          </div>

          {entries.map((entry) => {
            const isMe = currentUser && entry.name === (currentUser.displayName || currentUser.username);
            return (
              <div
                key={entry.rank}
                className={`grid grid-cols-[2rem_1fr_3.5rem_3rem] gap-2 items-center rounded-lg px-2 py-2 text-sm transition-colors ${
                  isMe
                    ? "bg-red-500/10 border border-red-500/20"
                    : entry.rank <= 3
                    ? "bg-stone-800/30"
                    : ""
                }`}
              >
                <span className={`font-bold ${entry.rank === 1 ? "text-yellow-400" : entry.rank === 2 ? "text-zinc-300" : entry.rank === 3 ? "text-amber-600" : "text-zinc-500"}`}>
                  {entry.rank === 1 ? "🥇" : entry.rank === 2 ? "🥈" : entry.rank === 3 ? "🥉" : entry.rank}
                </span>
                <span className={`truncate font-medium ${isMe ? "text-red-400" : "text-zinc-300"}`}>
                  {entry.name} {isMe && <span className="text-[10px] text-red-400/60">(you)</span>}
                </span>
                <span className="text-right font-mono text-xs text-zinc-400">
                  {entry.accuracy.toFixed(1)}%
                </span>
                <span className="text-right font-mono text-xs text-zinc-600">
                  {entry.exactMatches}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
