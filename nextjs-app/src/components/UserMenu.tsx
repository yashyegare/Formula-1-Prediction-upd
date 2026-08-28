import { useState, useRef, useEffect } from "react";
import { useAuth } from "../contexts/AuthContext";

interface UserMenuProps {
  onSignInClick: () => void;
}

export default function UserMenu({ onSignInClick }: UserMenuProps) {
  const { user, loading, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  if (loading) {
    return (
      <div className="h-8 w-8 animate-pulse rounded-full bg-stone-800" />
    );
  }

  if (!user) {
    return (
      <button
        onClick={onSignInClick}
        className="rounded-lg border border-stone-700 bg-stone-800/60 px-3.5 py-1.5 text-xs font-medium text-zinc-300 transition-all hover:border-red-500/50 hover:bg-red-500/10 hover:text-white"
      >
        Sign In
      </button>
    );
  }

  const initials = (user.displayName || user.username)
    .split(" ")
    .map((w) => w[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 rounded-lg border border-stone-700 bg-stone-800/60 px-3 py-1.5 text-sm font-medium text-white transition-all hover:border-stone-600 hover:bg-stone-700"
      >
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-red-600 text-[10px] font-bold text-white">
          {initials}
        </div>
        <span className="max-w-[100px] truncate">{user.displayName || user.username}</span>
        <svg
          className={`h-3 w-3 text-zinc-500 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-56 rounded-xl border border-stone-700 bg-[#1a1a1a] p-1.5 shadow-2xl z-50">
          <div className="border-b border-stone-800 px-3 py-2.5 mb-1">
            <p className="text-sm font-medium text-white truncate">{user.displayName || user.username}</p>
            <p className="text-xs text-zinc-500 truncate">{user.email}</p>
          </div>
          <button
            onClick={() => {
              signOut();
              setOpen(false);
            }}
            className="w-full rounded-lg px-3 py-2 text-left text-sm text-zinc-400 transition-colors hover:bg-stone-800 hover:text-white"
          >
            Sign Out
          </button>
        </div>
      )}
    </div>
  );
}
