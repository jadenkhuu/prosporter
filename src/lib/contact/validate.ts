/**
 * Contact form validation (CLNT-171, schedule acceptance criterion 3).
 *
 * Pure and dependency-free on purpose: no Next.js import, no `process.env`, no
 * I/O. That is what lets `src/lib/contact/__tests__/*.test.mjs` import it with
 * plain `node --test` (Node >= 22.18 strips the types), and it keeps the rules
 * identical wherever they run.
 *
 * The field set mirrors the WordPress source form. The migrated Contact page
 * carried Contact Form 7 form 253 ("Contact Form 2"): First Name, Last Name,
 * E-mail address, Subject and a comment textarea (maxlength 2000). Phone is the
 * one addition — the same page advertises a phone line, and a caller-supplied
 * number saves a round trip on order questions. It is optional.
 *
 * See `docs/forms.md` for the disposition of all three legacy forms.
 */

/** Every field the form posts, in render order. */
export const CONTACT_FIELDS = [
  "firstName",
  "lastName",
  "email",
  "phone",
  "subject",
  "message",
] as const;

export type ContactField = (typeof CONTACT_FIELDS)[number];

/** One message per field; an absent key means the field is fine. */
export type ContactFieldErrors = Partial<Record<ContactField, string>>;

/** Cleaned values, ready for delivery. */
export type ContactValues = {
  firstName: string;
  lastName: string;
  email: string;
  /** Empty string when not supplied. */
  phone: string;
  subject: string;
  message: string;
};

/**
 * Length caps. `message` matches the 2000-character `maxlength` the legacy
 * textarea enforced; the rest are generous enough for real names and short
 * enough that the form cannot be used as a payload channel.
 */
export const LIMITS = {
  firstName: 60,
  lastName: 60,
  email: 160,
  phone: 32,
  subject: 120,
  message: 2000,
} as const;

/** Shortest useful message. Anything below this is almost always spam. */
export const MESSAGE_MIN_LENGTH = 10;

/**
 * Deliberately permissive: one `@`, no whitespace, a dot-bearing domain. The
 * server only needs to reject obvious nonsense — an address is proved by the
 * reply, not by a regex, and a stricter pattern rejects valid addresses.
 */
const EMAIL_RE = /^[^\s@,;:<>()[\]\\]+@[^\s@.,;:<>()[\]\\]+(?:\.[^\s@.,;:<>()[\]\\]+)+$/;

/** Digits plus the usual separators. Australian numbers may start `+61`. */
const PHONE_RE = /^[0-9+()\-. ]{6,}$/;

/**
 * C0 and C1 control characters, minus tab and newline. Nothing a visitor
 * legitimately types contains the rest, and stripping them stops a null byte or
 * an escape sequence reaching the mail body or a log line.
 */
const CONTROL_RE = /[\u0000-\u0008\u000b-\u001f\u007f-\u009f]/g;

/**
 * Normalise one raw form value: non-strings become "", CR/LF collapses to LF,
 * control characters are dropped and the ends are trimmed. This runs before the
 * length checks, so a field padded with control characters cannot slip past.
 */
export function normalizeField(value: unknown): string {
  if (typeof value !== "string") return "";
  return value.replace(/\r\n?/g, "\n").replace(CONTROL_RE, "").trim();
}

/** Collapse a single-line field so a pasted newline cannot forge a mail header. */
function singleLine(value: string): string {
  return value.replace(/\n+/g, " ").replace(/\s{2,}/g, " ").trim();
}

function requireText(
  errors: ContactFieldErrors,
  field: ContactField,
  value: string,
  label: string,
  max: number,
): void {
  if (!value) {
    errors[field] = `${label} is required.`;
    return;
  }
  if (value.length > max) {
    errors[field] = `${label} must be ${max} characters or fewer.`;
  }
}

export type ContactValidationResult = {
  ok: boolean;
  values: ContactValues;
  errors: ContactFieldErrors;
};

/**
 * Validate a raw submission. Always returns the normalised values as well as
 * the errors, so the client component can re-render what the visitor typed
 * instead of emptying the form on a failed submit.
 */
export function validateContactSubmission(raw: Record<string, unknown>): ContactValidationResult {
  const values: ContactValues = {
    firstName: singleLine(normalizeField(raw.firstName)),
    lastName: singleLine(normalizeField(raw.lastName)),
    email: singleLine(normalizeField(raw.email)),
    phone: singleLine(normalizeField(raw.phone)),
    subject: singleLine(normalizeField(raw.subject)),
    message: normalizeField(raw.message),
  };

  const errors: ContactFieldErrors = {};

  requireText(errors, "firstName", values.firstName, "First name", LIMITS.firstName);
  requireText(errors, "lastName", values.lastName, "Last name", LIMITS.lastName);

  if (!values.email) {
    errors.email = "Email address is required.";
  } else if (values.email.length > LIMITS.email) {
    errors.email = `Email address must be ${LIMITS.email} characters or fewer.`;
  } else if (!EMAIL_RE.test(values.email)) {
    errors.email = "Enter a valid email address.";
  }

  if (values.phone) {
    const digits = (values.phone.match(/\d/g) ?? []).length;
    if (values.phone.length > LIMITS.phone) {
      errors.phone = `Phone number must be ${LIMITS.phone} characters or fewer.`;
    } else if (!PHONE_RE.test(values.phone) || digits < 6) {
      errors.phone = "Enter a valid phone number, or leave it blank.";
    }
  }

  requireText(errors, "subject", values.subject, "Subject", LIMITS.subject);

  if (!values.message) {
    errors.message = "Message is required.";
  } else if (values.message.length < MESSAGE_MIN_LENGTH) {
    errors.message = `Message must be at least ${MESSAGE_MIN_LENGTH} characters.`;
  } else if (values.message.length > LIMITS.message) {
    errors.message = `Message must be ${LIMITS.message} characters or fewer.`;
  }

  return { ok: Object.keys(errors).length === 0, values, errors };
}

/**
 * Honeypot: a field hidden from sighted users and removed from the
 * accessibility tree, which a person therefore never fills in. Any value at all
 * means a bot filled the form in wholesale.
 */
export const HONEYPOT_FIELD = "website";

export function isHoneypotFilled(raw: Record<string, unknown>): boolean {
  return normalizeField(raw[HONEYPOT_FIELD]).length > 0;
}
