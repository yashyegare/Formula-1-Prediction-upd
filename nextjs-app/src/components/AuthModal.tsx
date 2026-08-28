import React, { useState, useEffect } from "react";
import { useAuth } from "../contexts/AuthContext";

interface AuthModalProps {
  open: boolean;
  onClose: () => void;
  defaultMode?: "signin" | "signup";
}

export default function AuthModal({ open, onClose, defaultMode = "signin" }: AuthModalProps) {
  const { signIn, signUp } = useAuth();
  const [mode, setMode] = useState<"signin" | "signup">(defaultMode);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setMode(defaultMode);
      setError("");
      setUsername("");
      setEmail("");
      setPassword("");
      setDisplayName("");
    }
  }, [open, defaultMode]);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);

    let err: string | null = null;
    if (mode === "signup") {
      err = await signUp(username, email, password, displayName || username);
    } else {
      err = await signIn(username, password);
    }

    setSubmitting(false);
    if (err) {
      setError(err);
    } else {
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl border border-stone-700 bg-[#1a1a1a] p-8 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <h2 className="text-xl font-bold text-white">
            {mode === "signin" ? "Welcome Back" : "Create Account"}
          </h2>
          <button
            onClick={onClose}
            className="text-zinc-500 hover:text-white transition-colors text-xl leading-none"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {/* Username */}
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="text-zinc-400">Username</span>
            <input
              className="rounded-lg border border-stone-700 bg-stone-900 px-3 py-2.5 text-white text-sm outline-none focus:border-red-500 transition-colors"
              type="text"
              placeholder="e.g. yashf1"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
            />
          </label>

          {/* Email (signup only) */}
          {mode === "signup" && (
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="text-zinc-400">Email</span>
              <input
                className="rounded-lg border border-stone-700 bg-stone-900 px-3 py-2.5 text-white text-sm outline-none focus:border-red-500 transition-colors"
                type="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </label>
          )}

          {/* Display Name (signup only) */}
          {mode === "signup" && (
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="text-zinc-400">Display Name</span>
              <input
                className="rounded-lg border border-stone-700 bg-stone-900 px-3 py-2.5 text-white text-sm outline-none focus:border-red-500 transition-colors"
                type="text"
                placeholder="Yash"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
              />
            </label>
          )}

          {/* Password */}
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="text-zinc-400">Password</span>
            <input
              className="rounded-lg border border-stone-700 bg-stone-900 px-3 py-2.5 text-white text-sm outline-none focus:border-red-500 transition-colors"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
            />
          </label>

          {/* Error */}
          {error && (
            <p className="text-sm text-red-400 bg-red-400/10 rounded-lg px-3 py-2">{error}</p>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={submitting}
            className="mt-2 rounded-lg bg-red-600 px-4 py-2.5 text-sm font-semibold text-white transition-all hover:bg-red-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting
              ? "Loading..."
              : mode === "signin"
              ? "Sign In"
              : "Create Account"}
          </button>
        </form>

        {/* Toggle mode */}
        <p className="mt-5 text-center text-sm text-zinc-500">
          {mode === "signin" ? (
            <>
              Don&apos;t have an account?{" "}
              <button
                onClick={() => { setMode("signup"); setError(""); }}
                className="text-red-400 hover:text-red-300 font-medium transition-colors"
              >
                Sign Up
              </button>
            </>
          ) : (
            <>
              Already have an account?{" "}
              <button
                onClick={() => { setMode("signin"); setError(""); }}
                className="text-red-400 hover:text-red-300 font-medium transition-colors"
              >
                Sign In
              </button>
            </>
          )}
        </p>
      </div>
    </div>
  );
}
