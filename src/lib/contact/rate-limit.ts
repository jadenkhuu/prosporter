/**
 * Best-effort in-memory rate limiter for the contact form.
 *
 * **Per instance, not per deployment.** On Vercel every serverless instance
 * holds its own Map, so a submitter spread across N warm instances gets up to N
 * times the quota, and every counter is lost when an instance is recycled. That
 * is accepted here for the same reason the webhook route's duplicate-suppression
 * LRU is (see `docs/deployment.md`): it costs nothing, needs no external store,
 * and it stops the case that actually matters — one client hammering one
 * endpoint. The honeypot and the timing token in `token.ts` do the rest. If the
 * form ever attracts real abuse, swap this for a shared store (Vercel KV,
 * Upstash) behind the same `check()` signature.
 *
 * Pure module: no clock of its own (the caller passes `now`), no environment,
 * no Next.js import, so `__tests__/rate-limit.test.mjs` runs it under plain
 * `node --test`.
 */

/** Sliding window: submissions per key, per window. */
export const DEFAULT_LIMIT = 5;
export const DEFAULT_WINDOW_MS = 10 * 60 * 1000;

/** Cap on tracked keys, so a flood of unique IPs cannot grow the Map forever. */
const DEFAULT_MAX_KEYS = 5_000;

export type RateLimitResult = {
  allowed: boolean;
  /** Submissions left in the current window after this call. */
  remaining: number;
  /** How long until the oldest hit falls out of the window. 0 when allowed. */
  retryAfterMs: number;
};

export type RateLimiter = {
  check(key: string, now: number): RateLimitResult;
  /** Tracked key count. Exposed for tests and for a future metrics hook. */
  size(): number;
  reset(): void;
};

export function createRateLimiter(options?: {
  limit?: number;
  windowMs?: number;
  maxKeys?: number;
}): RateLimiter {
  const limit = options?.limit ?? DEFAULT_LIMIT;
  const windowMs = options?.windowMs ?? DEFAULT_WINDOW_MS;
  const maxKeys = options?.maxKeys ?? DEFAULT_MAX_KEYS;

  /** key -> timestamps of the hits still inside the window, oldest first. */
  const hits = new Map<string, number[]>();

  /**
   * Drop every key whose newest hit has aged out. Runs when the Map hits its
   * cap; if that is not enough (every key still live) the oldest-touched keys
   * go, which is what a Map's insertion order gives us for free.
   */
  function evict(now: number): void {
    for (const [key, stamps] of hits) {
      if (stamps.length === 0 || now - stamps[stamps.length - 1] >= windowMs) hits.delete(key);
    }
    while (hits.size >= maxKeys) {
      const oldest = hits.keys().next();
      if (oldest.done) break;
      hits.delete(oldest.value);
    }
  }

  return {
    check(key: string, now: number): RateLimitResult {
      if (hits.size >= maxKeys && !hits.has(key)) evict(now);

      const cutoff = now - windowMs;
      const stamps = (hits.get(key) ?? []).filter((t) => t > cutoff);

      if (stamps.length >= limit) {
        hits.set(key, stamps);
        return { allowed: false, remaining: 0, retryAfterMs: stamps[0] + windowMs - now };
      }

      stamps.push(now);
      hits.set(key, stamps);
      return { allowed: true, remaining: limit - stamps.length, retryAfterMs: 0 };
    },
    size() {
      return hits.size;
    },
    reset() {
      hits.clear();
    },
  };
}

/**
 * The key a request is limited on. `x-forwarded-for` is a client-supplied
 * header everywhere except behind a proxy that rewrites it — Vercel does, and
 * its left-most entry is the real client. Off Vercel the header is spoofable,
 * which is one more reason this limiter is best-effort. Unknown clients share
 * the `"unknown"` bucket rather than escaping the limiter entirely.
 */
export function rateLimitKey(headers: {
  forwardedFor?: string | null;
  realIp?: string | null;
}): string {
  const forwarded = (headers.forwardedFor ?? "").split(",")[0]?.trim();
  if (forwarded) return forwarded.slice(0, 64);
  const real = (headers.realIp ?? "").trim();
  if (real) return real.slice(0, 64);
  return "unknown";
}
