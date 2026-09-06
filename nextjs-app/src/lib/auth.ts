// Uses Next.js rewrites (next.config.mjs) to proxy /api/* to Flask backend

export interface AuthUser {
  id: number;
  username: string;
  email: string;
  displayName: string;
  avatarUrl?: string;
}

interface AuthResponse {
  user?: AuthUser;
  error?: string;
}

// Timeout for auth requests. Render free tier can cold-start: the first
// request may hang for many seconds. Abort after 20s so users get feedback
// instead of an endless spinner — a retry a minute later usually hits an
// already-awake server.
const REQUEST_TIMEOUT_MS = 20000;

async function fetchWithTimeout(path: string, options: RequestInit = {}): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(path, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

export function friendlyAuthError(err: unknown): string {
  if (err instanceof DOMException && err.name === "AbortError") {
    return "The server is taking too long to respond — it may be waking up. Please try again in a minute.";
  }
  if (err instanceof TypeError) {
    return "Can't reach the server. Check your connection and try again.";
  }
  return err instanceof Error && err.message ? err.message : "Something went wrong";
}

async function authFetch(
  path: string,
  options: RequestInit = {}
): Promise<AuthResponse> {
  let res: Response;
  try {
    res = await fetchWithTimeout(path, {
      credentials: "include", // send + receive cookies
      headers: { "Content-Type": "application/json", ...options.headers },
      ...options,
    });
  } catch (err) {
    return { error: friendlyAuthError(err) };
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return { error: data.error || "Something went wrong" };
  }
  return { user: data.user };
}

export async function signUp(
  username: string,
  email: string,
  password: string,
  displayName?: string
) {
  return authFetch("/api/auth/signup", {
    method: "POST",
    body: JSON.stringify({ username, email, password, displayName }),
  });
}

export async function signIn(username: string, password: string) {
  return authFetch("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function signOut() {
  const res = await fetch(`/api/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
  return res.ok;
}

export async function getCurrentUser(): Promise<AuthUser | null> {
  try {
    const res = await fetch(`/api/auth/me`, {
      credentials: "include",
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.user ?? null;
  } catch {
    return null;
  }
}

export async function getLeaderboard(season: number = 2026, limit: number = 50) {
  const res = await fetch(
    `/api/leaderboard?season=${season}&limit=${limit}`,
    { credentials: "include" }
  );
  if (!res.ok) return null;
  return res.json();
}
