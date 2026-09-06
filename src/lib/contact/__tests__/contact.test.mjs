/**
 * Unit tests for the contact form's pure helpers: field validation, the
 * honeypot, the anti-spam timing token and the rate limiter.
 *
 * Plain Node, zero dependencies: `npm test` (or `node --test
 * src/lib/contact/__tests__/*.test.mjs`). Requires Node >= 22.18, which strips
 * the TypeScript types from the imported modules without a build step.
 *
 * `actions.ts`, `config.ts` and `deliver.ts` are deliberately not imported:
 * they pull in `next/headers`, `server-only` and the environment. Everything
 * worth asserting without a running server lives in the three modules below.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  createRateLimiter,
  DEFAULT_LIMIT,
  DEFAULT_WINDOW_MS,
  rateLimitKey,
} from "../rate-limit.ts";
import {
  createFormToken,
  MAX_FORM_AGE_MS,
  MIN_FORM_AGE_MS,
  verifyFormToken,
} from "../token.ts";
import {
  HONEYPOT_FIELD,
  LIMITS,
  MESSAGE_MIN_LENGTH,
  isHoneypotFilled,
  normalizeField,
  validateContactSubmission,
} from "../validate.ts";

const valid = () => ({
  firstName: "Alex",
  lastName: "Nguyen",
  email: "alex@example.com",
  phone: "+61 2 8313 3805",
  subject: "Order 1234 sizing",
  message: "Could you confirm the sizing on the club jersey before I reorder?",
});

// ------------------------------------------------------------- validation

test("a complete submission passes and comes back normalised", () => {
  const result = validateContactSubmission({ ...valid(), firstName: "  Alex  " });
  assert.equal(result.ok, true);
  assert.deepEqual(result.errors, {});
  assert.equal(result.values.firstName, "Alex");
  assert.equal(result.values.email, "alex@example.com");
});

test("phone is optional and absent fields normalise to empty strings", () => {
  const result = validateContactSubmission({ ...valid(), phone: undefined });
  assert.equal(result.ok, true);
  assert.equal(result.values.phone, "");
});

test("every required field reports its own error", () => {
  const result = validateContactSubmission({});
  assert.equal(result.ok, false);
  assert.deepEqual(Object.keys(result.errors).sort(), [
    "email",
    "firstName",
    "lastName",
    "message",
    "subject",
  ]);
  assert.equal(result.errors.phone, undefined);
});

test("malformed email addresses are rejected", () => {
  for (const email of ["alex", "alex@", "@example.com", "alex@example", "a b@example.com", "a@b@c.com"]) {
    const result = validateContactSubmission({ ...valid(), email });
    assert.equal(result.ok, false, `expected ${email} to be rejected`);
    assert.match(result.errors.email ?? "", /valid email/);
  }
});

test("plausible email addresses are accepted", () => {
  for (const email of ["a@b.co", "alex.nguyen+club@sub.example.com.au", "ALEX@EXAMPLE.COM"]) {
    assert.equal(validateContactSubmission({ ...valid(), email }).ok, true, email);
  }
});

test("a phone number is only checked when one is supplied", () => {
  assert.equal(validateContactSubmission({ ...valid(), phone: "" }).ok, true);
  assert.equal(validateContactSubmission({ ...valid(), phone: "0283133805" }).ok, true);
  assert.equal(validateContactSubmission({ ...valid(), phone: "(02) 8313-3805" }).ok, true);

  const tooShort = validateContactSubmission({ ...valid(), phone: "12345" });
  assert.equal(tooShort.ok, false);
  assert.match(tooShort.errors.phone ?? "", /valid phone/);

  const letters = validateContactSubmission({ ...valid(), phone: "call me maybe" });
  assert.equal(letters.ok, false);
});

test("length limits are enforced on every field", () => {
  const long = validateContactSubmission({
    ...valid(),
    firstName: "a".repeat(LIMITS.firstName + 1),
    subject: "s".repeat(LIMITS.subject + 1),
    message: "m".repeat(LIMITS.message + 1),
  });
  assert.equal(long.ok, false);
  assert.match(long.errors.firstName ?? "", /60 characters or fewer/);
  assert.match(long.errors.subject ?? "", /120 characters or fewer/);
  assert.match(long.errors.message ?? "", /2000 characters or fewer/);

  const atLimit = validateContactSubmission({
    ...valid(),
    firstName: "a".repeat(LIMITS.firstName),
    message: "m".repeat(LIMITS.message),
  });
  assert.equal(atLimit.ok, true);
});

test("a message shorter than the floor is rejected", () => {
  const result = validateContactSubmission({ ...valid(), message: "hi" });
  assert.equal(result.ok, false);
  assert.match(result.errors.message ?? "", new RegExp(`${MESSAGE_MIN_LENGTH} characters`));
});

test("newlines survive in the message but are collapsed in single-line fields", () => {
  const result = validateContactSubmission({
    ...valid(),
    subject: "Order\n1234",
    message: "line one\nline two\nline three",
  });
  assert.equal(result.ok, true);
  assert.equal(result.values.subject, "Order 1234");
  assert.equal(result.values.message, "line one\nline two\nline three");
});

test("control characters and CRLF are stripped before the length check", () => {
  assert.equal(normalizeField("a\u0000b\u001fc"), "abc");
  assert.equal(normalizeField("one\r\ntwo"), "one\ntwo");
  assert.equal(normalizeField(42), "");
  assert.equal(normalizeField(null), "");
  const padded = "x".repeat(LIMITS.subject) + "\u0000".repeat(50);
  assert.equal(validateContactSubmission({ ...valid(), subject: padded }).ok, true);
});

test("a header-injection attempt cannot survive in the subject", () => {
  const result = validateContactSubmission({
    ...valid(),
    subject: "Hi\r\nBcc: someone@example.com",
  });
  assert.equal(result.values.subject.includes("\n"), false);
  assert.equal(result.values.subject.includes("\r"), false);
});

test("values are returned even when validation fails, so the form can repopulate", () => {
  const result = validateContactSubmission({ ...valid(), email: "nope" });
  assert.equal(result.ok, false);
  assert.equal(result.values.firstName, "Alex");
  assert.equal(result.values.message, valid().message);
});

// --------------------------------------------------------------- honeypot

test("an untouched honeypot passes and any value in it fails", () => {
  assert.equal(isHoneypotFilled({}), false);
  assert.equal(isHoneypotFilled({ [HONEYPOT_FIELD]: "" }), false);
  assert.equal(isHoneypotFilled({ [HONEYPOT_FIELD]: "   " }), false);
  assert.equal(isHoneypotFilled({ [HONEYPOT_FIELD]: "http://spam.example" }), true);
});

// ------------------------------------------------------------ timing token

const SECRET = "contact-form-test-secret";
const NOW = 1_700_000_000_000;

test("a signed token verifies once the form has been on screen long enough", () => {
  const token = createFormToken(NOW, SECRET);
  const result = verifyFormToken(token, { secret: SECRET, now: NOW + MIN_FORM_AGE_MS + 1 });
  assert.equal(result.ok, true);
  assert.equal(result.ageMs, MIN_FORM_AGE_MS + 1);
});

test("a submission faster than the floor is rejected as too_fast", () => {
  const token = createFormToken(NOW, SECRET);
  for (const elapsed of [0, 100, MIN_FORM_AGE_MS - 1]) {
    const result = verifyFormToken(token, { secret: SECRET, now: NOW + elapsed });
    assert.equal(result.ok, false, `elapsed ${elapsed}`);
    assert.equal(result.reason, "too_fast");
  }
});

test("a token older than the maximum is rejected as expired", () => {
  const token = createFormToken(NOW, SECRET);
  const result = verifyFormToken(token, { secret: SECRET, now: NOW + MAX_FORM_AGE_MS + 1 });
  assert.equal(result.ok, false);
  assert.equal(result.reason, "expired");
});

test("a token signed with another secret, or tampered with, is rejected", () => {
  const token = createFormToken(NOW, "other-secret");
  const now = NOW + MIN_FORM_AGE_MS + 1;
  assert.equal(verifyFormToken(token, { secret: SECRET, now }).reason, "signature");

  const good = createFormToken(NOW, SECRET);
  const [stamp, signature] = good.split(".");
  // Same signature, an older stamp: the attacker wants the age check to pass.
  const forged = `${Number(stamp) - MIN_FORM_AGE_MS}.${signature}`;
  assert.equal(verifyFormToken(forged, { secret: SECRET, now }).reason, "signature");
});

test("missing, empty and malformed tokens are rejected", () => {
  const now = NOW + MIN_FORM_AGE_MS + 1;
  assert.equal(verifyFormToken(undefined, { secret: SECRET, now }).reason, "missing");
  assert.equal(verifyFormToken("", { secret: SECRET, now }).reason, "missing");
  assert.equal(verifyFormToken("   ", { secret: SECRET, now }).reason, "missing");
  assert.equal(verifyFormToken(12345, { secret: SECRET, now }).reason, "missing");
  assert.equal(verifyFormToken("not-a-number.sig", { secret: SECRET, now }).reason, "malformed");
  assert.equal(verifyFormToken(String(NOW), { secret: SECRET, now }).reason, "malformed");
});

test("a token stamped well in the future is malformed, small skew is tolerated", () => {
  const future = createFormToken(NOW + 60_000, SECRET);
  assert.equal(verifyFormToken(future, { secret: SECRET, now: NOW }).reason, "malformed");

  // 1s of skew, then a normal fill time: still fine.
  const skewed = createFormToken(NOW + 1_000, SECRET);
  const result = verifyFormToken(skewed, { secret: SECRET, now: NOW + 30_000 });
  assert.equal(result.ok, true);
});

test("unsigned mode still range-checks the timestamp", () => {
  const token = createFormToken(NOW, null);
  assert.equal(token, String(NOW));
  assert.equal(verifyFormToken(token, { secret: null, now: NOW + 10_000 }).ok, true);
  assert.equal(verifyFormToken(token, { secret: null, now: NOW + 500 }).reason, "too_fast");
  assert.equal(
    verifyFormToken(token, { secret: null, now: NOW + MAX_FORM_AGE_MS + 1 }).reason,
    "expired",
  );
});

test("the age window is configurable", () => {
  const token = createFormToken(NOW, SECRET);
  const result = verifyFormToken(token, {
    secret: SECRET,
    now: NOW + 100,
    minAgeMs: 50,
    maxAgeMs: 200,
  });
  assert.equal(result.ok, true);
});

// ------------------------------------------------------------- rate limiter

test("the limiter allows up to the limit and then blocks", () => {
  const limiter = createRateLimiter({ limit: 3, windowMs: 1_000 });
  assert.equal(limiter.check("1.2.3.4", 0).allowed, true);
  assert.equal(limiter.check("1.2.3.4", 1).allowed, true);
  const third = limiter.check("1.2.3.4", 2);
  assert.equal(third.allowed, true);
  assert.equal(third.remaining, 0);

  const blocked = limiter.check("1.2.3.4", 3);
  assert.equal(blocked.allowed, false);
  assert.equal(blocked.remaining, 0);
  assert.equal(blocked.retryAfterMs, 1_000 - 3);
});

test("keys are limited independently", () => {
  const limiter = createRateLimiter({ limit: 1, windowMs: 1_000 });
  assert.equal(limiter.check("a", 0).allowed, true);
  assert.equal(limiter.check("b", 0).allowed, true);
  assert.equal(limiter.check("a", 0).allowed, false);
});

test("hits fall out of the window as it slides", () => {
  const limiter = createRateLimiter({ limit: 2, windowMs: 1_000 });
  limiter.check("a", 0);
  limiter.check("a", 500);
  assert.equal(limiter.check("a", 900).allowed, false);
  // The hit at t=0 has aged out by t=1001, freeing one slot.
  assert.equal(limiter.check("a", 1_001).allowed, true);
  assert.equal(limiter.check("a", 1_002).allowed, false);
  // Both have aged out.
  assert.equal(limiter.check("a", 2_000).allowed, true);
});

test("the key map is bounded, so unique keys cannot grow it without limit", () => {
  const limiter = createRateLimiter({ limit: 1, windowMs: 1_000, maxKeys: 10 });
  for (let i = 0; i < 500; i += 1) limiter.check(`ip-${i}`, i * 10);
  assert.ok(limiter.size() <= 10, `size was ${limiter.size()}`);
});

test("reset clears every counter", () => {
  const limiter = createRateLimiter({ limit: 1, windowMs: 1_000 });
  limiter.check("a", 0);
  limiter.reset();
  assert.equal(limiter.size(), 0);
  assert.equal(limiter.check("a", 0).allowed, true);
});

test("the defaults are the documented ones", () => {
  assert.equal(DEFAULT_LIMIT, 5);
  assert.equal(DEFAULT_WINDOW_MS, 10 * 60 * 1000);
  const limiter = createRateLimiter();
  for (let i = 0; i < DEFAULT_LIMIT; i += 1) {
    assert.equal(limiter.check("a", i).allowed, true);
  }
  assert.equal(limiter.check("a", DEFAULT_LIMIT).allowed, false);
});

test("the rate-limit key takes the left-most forwarded address", () => {
  assert.equal(rateLimitKey({ forwardedFor: "1.2.3.4, 5.6.7.8" }), "1.2.3.4");
  assert.equal(rateLimitKey({ forwardedFor: "  1.2.3.4  " }), "1.2.3.4");
  assert.equal(rateLimitKey({ forwardedFor: "", realIp: "9.9.9.9" }), "9.9.9.9");
  assert.equal(rateLimitKey({ forwardedFor: null, realIp: null }), "unknown");
  assert.equal(rateLimitKey({}), "unknown");
  assert.equal(rateLimitKey({ forwardedFor: "x".repeat(200) }).length, 64);
});
