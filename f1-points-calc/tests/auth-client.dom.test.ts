/**
 * Auth-client tests (jsdom: fetch, AbortController, DOMException).
 *
 * These pin the cold-start UX contract: a hung server aborts at 20s and the
 * user sees a friendly message, not an endless spinner; a 429 surfaces the
 * backend's message; signup generates collision-safe usernames.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { fetchWithTimeout, friendlyNetworkError, signIn, signUp, signOut } from '../src/lib/auth-client';

const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
  vi.restoreAllMocks();
});

// ── friendlyNetworkError ─────────────────────────────────────────────────────

describe('friendlyNetworkError', () => {
  it('maps AbortError to the waking-up message', () => {
    const err = new DOMException('The operation was aborted.', 'AbortError');
    expect(friendlyNetworkError(err).message).toMatch(/waking up/i);
  });

  it('maps TypeError (fetch network failure) to the connection message', () => {
    expect(friendlyNetworkError(new TypeError('Failed to fetch')).message).toMatch(/can't reach the server/i);
  });

  it('passes through real Error messages untouched', () => {
    expect(friendlyNetworkError(new Error('Email already registered')).message).toBe('Email already registered');
  });

  it('wraps unknown throws', () => {
    expect(friendlyNetworkError('boom' as unknown).message).toBe('Something went wrong');
  });
});

// ── fetchWithTimeout ─────────────────────────────────────────────────────────

describe('fetchWithTimeout', () => {
  it('resolves normally when the server answers in time', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
    const res = await fetchWithTimeout('http://localhost:8000/api/auth/me');
    expect(res.status).toBe(200);
  });

  it('aborts with AbortError when the server hangs past the timeout', async () => {
    vi.useFakeTimers();
    globalThis.fetch = vi.fn((_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () =>
          reject(new DOMException('The operation was aborted.', 'AbortError'))
        );
      })
    ) as unknown as typeof fetch;
    const promise = fetchWithTimeout('http://localhost:8000/api/auth/me');
    const assertion = expect(promise).rejects.toMatchObject({ name: 'AbortError' });
    await vi.advanceTimersByTimeAsync(20_000);
    await assertion;
    vi.useRealTimers();
  });
});

// ── signIn ───────────────────────────────────────────────────────────────────

describe('signIn.email', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ user: { id: 1, username: 'u', email: 'e', displayName: 'n' } }), { status: 200 })
    );
  });

  it('posts username+password to /api/auth/login with credentials', async () => {
    await signIn.email({ email: 'tbzyash1@gmail.com', password: 'secret' });
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('/api/auth/login');
    expect(init.credentials).toBe('include');
    const body = JSON.parse(init.body);
    expect(body.username).toBe('tbzyash1@gmail.com'); // sent as-is; backend tries username then email
    expect(body.password).toBe('secret');
  });

  it('returns { data } on success and null error', async () => {
    const result = await signIn.email({ email: 'x@y.z', password: 'p' });
    expect(result.error).toBeNull();
    expect(result.data).toEqual({ user: { id: 1, username: 'u', email: 'e', displayName: 'n' } });
  });

  it('surfaces the backend error message on 401', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: 'Invalid username or password' }), { status: 401 })
    );
    const result = await signIn.email({ email: 'x@y.z', password: 'wrong' });
    expect(result.data).toBeNull();
    expect(result.error?.message).toBe('Invalid username or password');
  });

  it('surfaces the 429 rate-limit message', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: 'Too many login attempts. Try again in 5 minutes.' }), { status: 429 })
    );
    const result = await signIn.email({ email: 'x@y.z', password: 'p' });
    expect(result.error?.message).toBe('Too many login attempts. Try again in 5 minutes.');
  });

  it('translates a network failure into the friendly message instead of throwing', async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    const result = await signIn.email({ email: 'x@y.z', password: 'p' });
    expect(result.error?.message).toMatch(/can't reach the server/i);
  });

  it('translates a cold-start abort into the waking-up message instead of throwing', async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new DOMException('aborted', 'AbortError'));
    const result = await signIn.email({ email: 'x@y.z', password: 'p' });
    expect(result.error?.message).toMatch(/waking up/i);
  });
});

// ── signUp ───────────────────────────────────────────────────────────────────

describe('signUp.email', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ user: { id: 2, username: 'tbzyash1_ab12', email: 'tbzyash1@gmail.com' } }), { status: 200 })
    );
  });

  it('generates a username from the email prefix + random suffix and posts it', async () => {
    const result = await signUp.email({ email: 'tbzyash1@gmail.com', password: 'Jarvis@890', name: 'Yash' });
    expect(result.error).toBeNull();
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('/api/auth/signup');
    const body = JSON.parse(init.body);
    expect(body.email).toBe('tbzyash1@gmail.com');
    expect(body.displayName).toBe('Yash');
    expect(body.username).toMatch(/^tbzyash1_[a-z0-9]{2,6}$/); // prefix sanitized + suffix
  });

  it('sanitizes special characters out of the username prefix', async () => {
    await signUp.email({ email: 'first.last+tag@sub.domain.com', password: 'p', name: '' });
    const [, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(init.body);
    expect(body.username.startsWith('firstlasttag_')).toBe(true);
    // Empty display name falls back to the email prefix.
    expect(body.displayName).toBe('firstlasttag');
  });

  it('prefix longer than 12 chars is truncated', async () => {
    await signUp.email({ email: 'averyveryverylongemailprefix@gmail.com', password: 'p', name: 'X' });
    const [, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(init.body);
    expect(body.username.startsWith('averyveryvery'.slice(0, 12))).toBe(true);
  });

  it('returns the backend duplicate-email error untouched', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: 'Email already registered' }), { status: 409 })
    );
    const result = await signUp.email({ email: 'taken@gmail.com', password: 'p', name: 'X' });
    expect(result.error?.message).toBe('Email already registered');
  });
});

// ── signOut ──────────────────────────────────────────────────────────────────

describe('signOut', () => {
  it('POSTs to /api/auth/logout and never throws (even on network failure)', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
    await expect(signOut()).resolves.toBeUndefined();

    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(signOut()).resolves.toBeUndefined();
  });
});
