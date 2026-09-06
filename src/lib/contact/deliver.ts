import "server-only";

/**
 * Contact-form delivery, behind a two-adapter abstraction.
 *
 *   resend  — HTTP POST to https://api.resend.com/emails with plain `fetch`.
 *             No npm dependency: the Resend SDK is a thin wrapper over one
 *             endpoint, and adding a package for it would need approval under
 *             the schedule's variation process. Resend's free tier is $0.
 *   log     — development fallback when nothing is configured. Records that a
 *             message was accepted and nothing about its contents.
 *
 * Swapping providers (SES, Postmark, a Shopify app) means adding one adapter
 * here; `actions.ts` only sees `deliverContactMessage`.
 *
 * Privacy: the submitter's name, email, phone and message never reach the log.
 * Every log line carries a request id, the adapter name, the outcome and
 * counts, per the rule in `src/lib/log.ts`.
 */
import { DELIVERY_TIMEOUT_MS, contactConfig } from "./config";
import type { ContactValues } from "./validate";
import { errorFields, log } from "../log";
import { deploymentEnvironment } from "../site";

export type DeliveryAdapter = "resend" | "log" | "none";

export type DeliveryResult = {
  delivered: boolean;
  adapter: DeliveryAdapter;
  /** Provider-side id when there is one; never contains personal data. */
  providerId: string | null;
};

/**
 * Which adapter a submission would use right now.
 *
 *   "resend" — configured; messages are emailed.
 *   "log"    — development only; messages are accepted and dropped.
 *   "none"   — production with no configuration; the form must not render.
 */
export function deliveryAdapter(): DeliveryAdapter {
  if (contactConfig()) return "resend";
  return deploymentEnvironment() === "production" ? "none" : "log";
}

/**
 * True when the contact form should be rendered at all. False only in the
 * production-with-no-config case, where a rendered form would take a message
 * and silently lose it — worse than pointing the visitor at the phone number.
 */
export function isContactFormEnabled(): boolean {
  return deliveryAdapter() !== "none";
}

let warnedUnconfigured = false;

/**
 * Emitted once per instance, not once per request: an unconfigured production
 * deployment would otherwise log a line for every render of `/contact`.
 */
export function warnIfUnconfigured(): void {
  if (warnedUnconfigured || deliveryAdapter() !== "none") return;
  warnedUnconfigured = true;
  log.warn("contact.delivery_unconfigured", {
    hint: "set RESEND_API_KEY, CONTACT_TO_EMAIL and CONTACT_FROM_EMAIL; the form renders a phone/email fallback until then",
  });
}

/** Plain-text mail body. Kept plain so no submitted value is ever interpreted as markup. */
function renderBody(values: ContactValues, requestId: string): string {
  return [
    `Name:    ${values.firstName} ${values.lastName}`,
    `Email:   ${values.email}`,
    `Phone:   ${values.phone || "(not supplied)"}`,
    `Subject: ${values.subject}`,
    "",
    values.message,
    "",
    "--",
    `Sent from the prosporter.com.au contact form (ref ${requestId}).`,
  ].join("\n");
}

/**
 * Mail headers are line-delimited, so a newline in a header value is an
 * injection. `validate.ts` already collapses newlines in every single-line
 * field; this is the belt to that pair of braces.
 */
function headerSafe(value: string): string {
  return value.replace(/[\r\n]+/g, " ").trim();
}

async function deliverViaResend(
  values: ContactValues,
  requestId: string,
): Promise<DeliveryResult> {
  const config = contactConfig();
  if (!config) return { delivered: false, adapter: "none", providerId: null };

  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      authorization: `Bearer ${config.apiKey}`,
      "content-type": "application/json",
    },
    cache: "no-store",
    signal: AbortSignal.timeout(DELIVERY_TIMEOUT_MS),
    body: JSON.stringify({
      from: config.from,
      to: [config.to],
      reply_to: values.email,
      subject: headerSafe(`ProSporter contact: ${values.subject}`),
      text: renderBody(values, requestId),
    }),
  });

  if (!response.ok) {
    // The body can echo the address we posted, so only the status is logged.
    log.error("contact.delivery_failed", {
      requestId,
      adapter: "resend",
      status: response.status,
    });
    return { delivered: false, adapter: "resend", providerId: null };
  }

  let providerId: string | null = null;
  try {
    const payload: unknown = await response.json();
    if (payload && typeof payload === "object" && "id" in payload) {
      const id = (payload as { id?: unknown }).id;
      if (typeof id === "string") providerId = id;
    }
  } catch {
    // A 200 with an unparseable body still means the message was accepted.
  }

  log.info("contact.delivered", { requestId, adapter: "resend", providerId });
  return { delivered: true, adapter: "resend", providerId };
}

/**
 * Deliver one validated submission. Never throws: a provider failure comes back
 * as `delivered: false` so the action can show a "try the phone number instead"
 * message rather than a stack trace.
 */
export async function deliverContactMessage(
  values: ContactValues,
  requestId: string,
): Promise<DeliveryResult> {
  const adapter = deliveryAdapter();

  if (adapter === "none") {
    warnIfUnconfigured();
    return { delivered: false, adapter: "none", providerId: null };
  }

  if (adapter === "log") {
    log.info("contact.delivered", {
      requestId,
      adapter: "log",
      messageLength: values.message.length,
      hasPhone: values.phone.length > 0,
    });
    return { delivered: true, adapter: "log", providerId: null };
  }

  try {
    return await deliverViaResend(values, requestId);
  } catch (err) {
    log.error("contact.delivery_failed", {
      requestId,
      adapter: "resend",
      ...errorFields(err),
    });
    return { delivered: false, adapter: "resend", providerId: null };
  }
}
