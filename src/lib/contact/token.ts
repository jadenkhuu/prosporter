/**
 * Form timing token — the second half of the contact form's spam protection
 * (the first is the honeypot in `validate.ts`).
 *
 * The server stamps the render time into a hidden field. On submit it checks
 * how long the form was on screen: a bot that POSTs the moment it parses the
 * page is rejected, and so is a token old enough to have come from a scraped
 * copy of the page. A person filling in five fields takes far longer than the
 * floor, so no real submission is caught by it.
 *
 * Pure module: `node:crypto` only, no `process.env` and no Next.js import, so
 * `__tests__/token.test.mjs` can exercise it directly. The secret is passed in
 * — `deliver.ts` is the only module that reads the environment.
 *
 * Token format: `<issuedAtMs>.<base64url hmac-sha256>`, or bare `<issuedAtMs>`
 * when no secret is configured. Unsigned mode is honest about what it is: a bot
 * can forge the timestamp, so the honeypot and the rate limiter carry the load.
 * Set `CONTACT_FORM_SECRET` in production to close that gap.
 */
import { createHmac, timingSafeEqual } from "node:crypto";

/** A form submitted faster than this was not filled in by a person. */
export const MIN_FORM_AGE_MS = 3_000;

/** Tokens expire after an hour; a stale one asks the visitor to resubmit. */
export const MAX_FORM_AGE_MS = 60 * 60 * 1000;

/** Small tolerance for clock skew between the rendering and receiving instance. */
const FUTURE_SKEW_MS = 5_000;

function sign(issuedAt: number, secret: string): string {
  return createHmac("sha256", secret).update(String(issuedAt)).digest("base64url");
}

/** Stamp a token for a form being rendered now. `secret` may be null. */
export function createFormToken(issuedAt: number, secret: string | null): string {
  if (!secret) return String(issuedAt);
  return `${issuedAt}.${sign(issuedAt, secret)}`;
}

export type FormTokenResult =
  | { ok: true; ageMs: number }
  | { ok: false; reason: "missing" | "malformed" | "signature" | "too_fast" | "expired" };

function signatureMatches(expected: string, received: string): boolean {
  const a = Buffer.from(expected, "utf8");
  const b = Buffer.from(received, "utf8");
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

/**
 * Verify a token against the clock. `secret` null means unsigned mode: the
 * timestamp is still range-checked, the signature simply is not required.
 */
export function verifyFormToken(
  token: unknown,
  options: {
    secret: string | null;
    now: number;
    minAgeMs?: number;
    maxAgeMs?: number;
  },
): FormTokenResult {
  const minAgeMs = options.minAgeMs ?? MIN_FORM_AGE_MS;
  const maxAgeMs = options.maxAgeMs ?? MAX_FORM_AGE_MS;

  if (typeof token !== "string" || token.trim() === "") return { ok: false, reason: "missing" };

  const trimmed = token.trim();
  const dot = trimmed.indexOf(".");
  const stamp = dot === -1 ? trimmed : trimmed.slice(0, dot);
  const signature = dot === -1 ? "" : trimmed.slice(dot + 1);

  if (!/^\d{1,15}$/.test(stamp)) return { ok: false, reason: "malformed" };
  const issuedAt = Number(stamp);

  if (options.secret) {
    if (!signature) return { ok: false, reason: "malformed" };
    if (!signatureMatches(sign(issuedAt, options.secret), signature)) {
      return { ok: false, reason: "signature" };
    }
  }

  const ageMs = options.now - issuedAt;
  // A token stamped in the future is either skew (tolerated) or forged.
  if (ageMs < -FUTURE_SKEW_MS) return { ok: false, reason: "malformed" };
  if (ageMs < minAgeMs) return { ok: false, reason: "too_fast" };
  if (ageMs > maxAgeMs) return { ok: false, reason: "expired" };

  return { ok: true, ageMs };
}
