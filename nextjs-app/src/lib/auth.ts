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

async function authFetch(
  path: string,
  options: RequestInit = {}
): Promise<AuthResponse> {
  const res = await fetch(path, {
    credentials: "include", // send + receive cookies
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  const data = await res.json();
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
