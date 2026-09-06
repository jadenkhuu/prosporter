/**
 * The `useActionState` contract for the contact form.
 *
 * Separate from `actions.ts` because a `"use server"` module may only export
 * async functions — the initial state and the shared types have to live
 * somewhere else. Separate from `validate.ts` because that module is imported
 * by plain-Node tests and should stay free of anything UI-shaped.
 *
 * No `server-only` here: both halves import it.
 */
import type { ContactFieldErrors, ContactValues } from "./validate";

/**
 * Hidden field carrying the render timestamp that `token.ts` checks. Named here
 * rather than in `actions.ts` because both the form and the action need it and
 * a `"use server"` module cannot export a constant.
 */
export const CONTACT_TOKEN_FIELD = "formToken";

export type ContactFormStatus = "idle" | "success" | "error";

export type ContactFormState = {
  status: ContactFormStatus;
  /** Status-region text. Empty while idle. */
  message: string;
  /** Field-level messages, keyed by field name. */
  errors: ContactFieldErrors;
  /** What the visitor typed, so a failed submit does not empty the form. */
  values: ContactValues;
  /**
   * Bumped on every server response. The client uses it as a React `key` on the
   * status region so a second identical failure is still announced.
   */
  attempt: number;
};

export const EMPTY_CONTACT_VALUES: ContactValues = {
  firstName: "",
  lastName: "",
  email: "",
  phone: "",
  subject: "",
  message: "",
};

export const INITIAL_CONTACT_FORM_STATE: ContactFormState = {
  status: "idle",
  message: "",
  errors: {},
  values: EMPTY_CONTACT_VALUES,
  attempt: 0,
};
