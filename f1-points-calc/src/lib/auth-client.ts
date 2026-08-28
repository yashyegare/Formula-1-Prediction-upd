// Auth client that talks to our Flask backend's /api/auth/* endpoints.
// Replaces the better-auth client that expected a separate auth server.

const API_BASE = import.meta.env.PUBLIC_API_BASE_URL || 'http://localhost:8000';

async function apiFetch(path: string, options: RequestInit = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || `Request failed (${res.status})`);
  }
  return data;
}

export const signIn = {
  email: async ({ email, password }: { email: string; password: string }) => {
    try {
      // Try as username first (e.g. "alice")
      const data = await apiFetch('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username: email, password }),
      });
      return { data, error: null };
    } catch (err) {
      // If that failed and it looks like an email, try the part before @
      if (email.includes('@')) {
        try {
          const usernameFromEmail = email.split('@')[0];
          const data = await apiFetch('/api/auth/login', {
            method: 'POST',
            body: JSON.stringify({ username: usernameFromEmail, password }),
          });
          return { data, error: null };
        } catch {
          // Fall through
        }
      }
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
      // Generate a username from the name or email
      const username = (name || email.split('@')[0]).toLowerCase().replace(/[^a-z0-9_]/g, '');
      const data = await apiFetch('/api/auth/signup', {
        method: 'POST',
        body: JSON.stringify({ username, email, password, displayName: name || username }),
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
