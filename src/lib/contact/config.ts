import "server-only";

/**
 * The only reader of the contact-form environment variables, mirroring the
 * `src/lib/shopify/config.ts` convention: one module holds the secret, nothing
 * else touches `process.env`.
 *
 *   RESEND_API_KEY      Resend API key. Absent => no email is sent.
 *   CONTACT_TO_EMAIL    Where submissions are delivered. **Client-nominated
 *                       address, not yet supplied** (schedule section 9).
 *   CONTACT_FROM_EMAIL  Envelope sender. Must be on a domain verified in
 *                       Resend, which is a client dependency (DNS records).
 *   CONTACT_FORM_SECRET Optional HMAC key for the anti-spam timing token. When
 *                       unset the token is unsigned; see `token.ts`.
 *
 * See `docs/deployment.md` for where these are set and `docs/forms.md` for what
 * the form replaces.
 */

import { createFormToken } from "./token";

export type ContactConfig = {
  apiKey: string;
  to: string;
  from: string;
};

function env(name: string): string {
  return (process.env[name] ?? "").trim();
}

/**
 * Fully configured delivery, or null. Null is not an error: in development it
 * selects the log-only adapter, and in production it makes the route render the
 * phone/email fallback instead of a form that would silently drop messages.
 */
export function contactConfig(): ContactConfig | null {
  const apiKey = env("RESEND_API_KEY");
  const to = env("CONTACT_TO_EMAIL");
  const from = env("CONTACT_FROM_EMAIL");
  if (!apiKey || !to || !from) return null;
  return { apiKey, to, from };
}

/** Optional signing key for the timing token. Null when unset. */
export function contactFormSecret(): string | null {
  return env("CONTACT_FORM_SECRET") || null;
}

/**
 * Stamp a timing token for a form being rendered now.
 *
 * Async, and therefore called with `await` from the server component rather
 * than inline in JSX: `Date.now()` during render is impure and
 * `react-hooks/purity` rejects it. Awaiting it makes the read an explicit part
 * of rendering the request instead of something a re-render could redo.
 */
export async function issueContactFormToken(): Promise<string> {
  return createFormToken(Date.now(), contactFormSecret());
}

/** Per-request timeout for the delivery provider call, in milliseconds. */
export const DELIVERY_TIMEOUT_MS = 10_000;
