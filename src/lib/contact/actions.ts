"use server";

/**
 * Contact form server action (CLNT-171, schedule acceptance criterion 3:
 * "All forms submit successfully and deliver to the client-nominated email
 * address; validation and error states work").
 *
 * The order of the checks matters. Spam checks run first and, apart from the
 * rate limit, are answered with the same success message a real submission
 * gets: telling a bot which check it tripped is free tuning information.
 *
 *   1. honeypot filled                -> silent accept, nothing delivered
 *   2. timing token missing/too fast  -> silent accept (a stale token asks for a reload)
 *   3. rate limit for this IP         -> visible "too many messages" error
 *   4. field validation               -> typed per-field errors
 *   5. delivery                       -> success, or a "call us instead" error
 *
 * Nothing here logs a name, an email address, a phone number or the message.
 * Log lines carry a request id, the outcome and counts — see `src/lib/log.ts`.
 *
 * A `"use server"` module may only export async functions, so the state type,
 * the initial state, the field names and the validation rules live in
 * `state.ts` and `validate.ts`.
 */
import { randomUUID } from "node:crypto";
import { headers } from "next/headers";

import { contactFormSecret } from "./config";
import { deliverContactMessage } from "./deliver";
import { createRateLimiter, rateLimitKey } from "./rate-limit";
import type { ContactFormState } from "./state";
import { CONTACT_TOKEN_FIELD, EMPTY_CONTACT_VALUES } from "./state";
import { verifyFormToken } from "./token";
import { isHoneypotFilled, validateContactSubmission } from "./validate";
import { log } from "../log";

const SUCCESS_MESSAGE =
  "Thanks — your message is on its way. We usually reply within one business day.";
const RATE_LIMITED_MESSAGE =
  "You have sent several messages already. Please wait a few minutes before sending another, or call us instead.";
const STALE_MESSAGE =
  "This form was open for a while and the page needs refreshing. Please reload and send it again.";
const VALIDATION_MESSAGE = "Please check the highlighted fields and try again.";
const DELIVERY_MESSAGE =
  "We could not send your message just now. Please try again shortly, or reach us on the phone number or email address above.";

/**
 * Module scope, so it survives between requests handled by the same instance —
 * and only those. See the header of `rate-limit.ts` for why per-instance and
 * best-effort is the right trade here.
 */
const limiter = createRateLimiter();

export async function submitContactForm(
  previous: ContactFormState,
  formData: FormData,
): Promise<ContactFormState> {
  const requestId = randomUUID();
  const raw: Record<string, unknown> = Object.fromEntries(formData.entries());
  const attempt = previous.attempt + 1;

  const accepted: ContactFormState = {
    status: "success",
    message: SUCCESS_MESSAGE,
    errors: {},
    values: EMPTY_CONTACT_VALUES,
    attempt,
  };

  // 1. Honeypot. A person never sees that field, so any value is a bot.
  if (isHoneypotFilled(raw)) {
    log.info("contact.rejected", { requestId, reason: "honeypot" });
    return accepted;
  }

  // 2. Timing token: too fast to have been typed, or too old to trust.
  const token = verifyFormToken(raw[CONTACT_TOKEN_FIELD], {
    secret: contactFormSecret(),
    now: Date.now(),
  });
  if (!token.ok) {
    log.info("contact.rejected", { requestId, reason: `token_${token.reason}` });
    if (token.reason !== "expired") return accepted;
    return {
      status: "error",
      message: STALE_MESSAGE,
      errors: {},
      values: validateContactSubmission(raw).values,
      attempt,
    };
  }

  // 3. Rate limit. Visible, because a person can legitimately hit it.
  const requestHeaders = await headers();
  const rate = limiter.check(
    rateLimitKey({
      forwardedFor: requestHeaders.get("x-forwarded-for"),
      realIp: requestHeaders.get("x-real-ip"),
    }),
    Date.now(),
  );
  if (!rate.allowed) {
    log.warn("contact.rejected", {
      requestId,
      reason: "rate_limited",
      retryAfterMs: rate.retryAfterMs,
    });
    return {
      status: "error",
      message: RATE_LIMITED_MESSAGE,
      errors: {},
      values: validateContactSubmission(raw).values,
      attempt,
    };
  }

  // 4. Field validation.
  const validation = validateContactSubmission(raw);
  if (!validation.ok) {
    log.info("contact.rejected", {
      requestId,
      reason: "validation",
      fieldErrors: Object.keys(validation.errors).length,
    });
    return {
      status: "error",
      message: VALIDATION_MESSAGE,
      errors: validation.errors,
      values: validation.values,
      attempt,
    };
  }

  // 5. Delivery.
  const result = await deliverContactMessage(validation.values, requestId);
  if (!result.delivered) {
    log.error("contact.failed", { requestId, adapter: result.adapter });
    return {
      status: "error",
      message: DELIVERY_MESSAGE,
      errors: {},
      values: validation.values,
      attempt,
    };
  }

  log.info("contact.accepted", {
    requestId,
    adapter: result.adapter,
    messageLength: validation.values.message.length,
  });
  return accepted;
}
