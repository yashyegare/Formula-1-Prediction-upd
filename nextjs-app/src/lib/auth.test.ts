/**
 * Tests for the Next.js app's auth client (src/lib/auth.ts).
 *
 * Pins the cold-start UX contract (20s abort → friendly message), the
 * non-JSON response crash fix, and the request payload shapes the Flask
 * backend expects.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  friendlyAuthError,
  signUp,
  signIn,
  signOut,
  getCurrentUser,
  getLeaderboard,
} from './auth';

const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
  vi.restoreAllMocks();
});

// ── friendlyAuthError ────────────────────────────────────────────────────────

describe('friendlyAuthError', () => {
  it('maps AbortError to the waking-up message', () => {
    expect(friendlyAuthError(new DOMException('aborted', 'AbortError'))).toMatch(/waking up/i);
  });

  it('maps TypeError to the connection message', () => {
    expect(friendlyAuthError(new TypeError('Failed to fetch'))).toMatch(/can't reach the server/i);
  });

  it('passes through backend Error messages', () => {
    expect(friendlyAuthError(new Error('Email already registered'))).toBe('Email already registered');
  });

  it('wraps unknown throws', () => {
    expect(friendlyAuthError(42)).toBe('Something went wrong');
  });
});

// ── signUp / signIn ──────────────────────────────────────────────────────────

describe('signUp', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ user: { id: 1, username: 'u', email: 'e', displayName: 'n' } }), { status: 200 })
    );
  });

  it('posts the full payload with credentials to the signup proxy route', async () => {
    await signUp('yash_12', 'tbzyash1@gmail.com', 'secret', 'Yash');
    const [path, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(path).toBe('/api/auth/signup');
    expect(init.method).toBe('POST');
    expect(init.credentials).toBe('include');
    expect(JSON.parse(init.body)).toEqual({
      username: 'yash_12',
      email: 'tbzyash1@gmail.com',
      password: 'secret',
      displayName: 'Yash',
    });
  });

  it('surfaces backend errors (duplicate email) instead of throwing', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: 'Email already registered' }), { status: 409 })
    );
    const result = await signUp('u', 'taken@x.com', 'p', 'U');
    expect(result.user).toBeUndefined();
    expect(result.error).toBe('Email already registered');
  });

  it('returns a friendly error on network failure (no throw)', async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    const result = await signUp('u', 'a@b.c', 'p', 'U');
    expect(result.error).toMatch(/can't reach the server/i);
  });

  it('returns a friendly error on cold-start abort (no throw)', async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new DOMException('aborted', 'AbortError'));
    const result = await signIn('u', 'p');
    expect(result.error).toMatch(/waking up/i);
  });
});

describe('signIn', () => {
  it('posts username+password with credentials', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ user: { id: 1 } }), { status: 200 }));
    await signIn('tbzyash1@gmail.com', 'pw');
    const [path, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(path).toBe('/api/auth/login');
    expect(JSON.parse(init.body)).toEqual({ username: 'tbzyash1@gmail.com', password: 'pw' });
    expect(init.credentials).toBe('include');
  });
});

// ── Response-shape robustness ────────────────────────────────────────────────

describe('response robustness', () => {
  it('does not crash on a non-JSON error page (e.g. proxy 502 HTML)', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response('<html>Bad Gateway</html>', { status: 502 }));
    const result = await signIn('u', 'p');
    // data.error is unavailable → generic fallback, no exception.
    expect(result.error).toBe('Something went wrong');
    expect(result.user).toBeUndefined();
  });

  it('does not crash on a non-JSON success response', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response('OK', { status: 200 }));
    const result = await signIn('u', 'p');
    expect(result.error).toBeUndefined();
    expect(result.user).toBeUndefined();
  });
});

// ── signOut / getCurrentUser / getLeaderboard ────────────────────────────────

describe('signOut', () => {
  it('returns true on success and false on failure', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
    expect(await signOut()).toBe(true);

    globalThis.fetch = vi.fn().mockResolvedValue(new Response('{}', { status: 500 }));
    expect(await signOut()).toBe(false);
  });
});

describe('getCurrentUser', () => {
  it('returns the user object when authenticated', async () => {
    const user = { id: 7, username: 'e2epg1', email: 'x@y.z', displayName: 'E2E' };
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ user }), { status: 200 })
    );
    expect(await getCurrentUser()).toEqual(user);
  });

  it('returns null when logged out (401) and never throws on network errors', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response('{"user":null}', { status: 401 }));
    expect(await getCurrentUser()).toBeNull();

    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    expect(await getCurrentUser()).toBeNull();
  });
});

describe('getLeaderboard', () => {
  it('fetches with the season+limit query and credentials', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ entries: [] }), { status: 200 })
    );
    await getLeaderboard(2026, 25);
    const [path, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(path).toBe('/api/leaderboard?season=2026&limit=25');
    expect(init.credentials).toBe('include');
  });

  it('returns null on failure instead of throwing', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response('{}', { status: 500 }));
    expect(await getLeaderboard()).toBeNull();
  });
});
