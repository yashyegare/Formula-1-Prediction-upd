// Auth client that talks to our Flask backend's /api/auth/* endpoints.
// Replaces the better-auth client that expected a separate auth server.

const API_BASE = import.meta.env.PUBLIC_API_BASE_URL || 'http://localhost:8000';

async function apiFetch(path: string, options: RequestInit = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 429) {
      throw new Error(data.error || 'Too many attempts. Please wait a few minutes and try again.');
    }
    throw new Error(data.error || `Request failed (${res.status})`);
  }
  return data;
}

export const signIn = {
  email: async ({ email, password }: { email: string; password: string }) => {
    try {
      // Send email/username as-is — backend tries username then email lookup
      const data = await apiFetch('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username: email, password }),
      });
      return { data, error: null };
    } catch (err) {
      return { data: null, error: { message: err instanceof Error ? err.message : 'Invalid username or password' } };
    }
  },
  social: async ({ provider, callbackURL, errorCallbackURL }: any) => {
    // Google sign-in not supported with Flask backend
    throw new Error('Google sign-in is not available. Please use email/password.');
  },
};

export const signUp = {
  email: async ({ email, password, name, callbackURL }: any) => {
    try {
      // Generate a unique username from the email prefix + random suffix
      // to avoid collisions when multiple users share similar display names
      const emailPrefix = email.split('@')[0].toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 12);
      const suffix = Math.random().toString(36).slice(2, 6);
      const username = `${emailPrefix}_${suffix}`;
      const data = await apiFetch('/api/auth/signup', {
        method: 'POST',
        body: JSON.stringify({ username, email, password, displayName: name || emailPrefix }),
      });
      return { data, error: null, needsVerification: false };
    } catch (err) {
      return { data: null, error: { message: err instanceof Error ? err.message : 'Signup failed' } };
    }
  },
};

export const signOut = async () => {
  try {
    await apiFetch('/api/auth/logout', { method: 'POST' });
  } catch {
    // Ignore errors on logout
  }
};

export const useSession = () => {
  // This is called at import time, so we can't use hooks here.
  // Instead, the useAuth hook will handle session checking.
  return { data: null, isPending: false };
};

export const sendVerificationEmail = async ({ email }: { email: string }) => {
  // No email verification in our Flask backend
  return { data: null, error: null };
};
