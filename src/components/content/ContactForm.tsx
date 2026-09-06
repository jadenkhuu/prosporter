"use client";

/**
 * Contact form (CLNT-171). Replaces the Contact Form 7 block that
 * `src/lib/content-html.ts` strips out of the migrated Contact page — see
 * `docs/forms.md`.
 *
 * State comes from `useActionState(submitContactForm, …)`: `pending` disables
 * the submit button, `state.errors` carries per-field messages and
 * `state.values` carries back what the visitor typed so a rejected submit does
 * not empty the form. React resets an uncontrolled form once its action
 * resolves, so the field block is remounted on `state.attempt` and each input
 * re-applies its `defaultValue` from the returned values.
 *
 * Accessibility:
 *  - every control has a real `<label htmlFor>`; nothing relies on a placeholder
 *    (the legacy CF7 form was placeholder-only, which the audit flagged);
 *  - an invalid field gets `aria-invalid` and `aria-describedby` pointing at its
 *    message, and the first invalid field takes focus after a failed submit;
 *  - the form-level outcome is announced through one `role="status"`
 *    `aria-live="polite"` region, keyed on the attempt so a repeated identical
 *    message is re-announced;
 *  - every message slot reserves its line height, so showing an error moves
 *    nothing on the page;
 *  - focus styling is the global `:focus-visible` ring from `globals.css`.
 *
 * Visual language follows `Filters.tsx` / `SearchDialog.tsx`: `border-line`
 * hairlines on `bg-paper`, `eyebrow` labels, an ink submit button. No new CSS.
 */
import { useActionState, useEffect, useId, useRef } from "react";

import { submitContactForm } from "@/lib/contact/actions";
import {
  CONTACT_TOKEN_FIELD,
  INITIAL_CONTACT_FORM_STATE,
  type ContactFormState,
} from "@/lib/contact/state";
import {
  CONTACT_FIELDS,
  HONEYPOT_FIELD,
  LIMITS,
  type ContactField,
} from "@/lib/contact/validate";

const FIELD_CLASS =
  "w-full rounded-card border border-line bg-paper px-3 py-2.5 text-sm text-ink outline-none transition-colors placeholder:text-subtle hover:border-muted focus:border-ink";
const INVALID_CLASS = "border-ink";

/** One labelled control plus its reserved message line. */
function Field({
  field,
  label,
  state,
  children,
  hint,
}: {
  field: ContactField;
  label: string;
  state: ContactFormState;
  hint?: string;
  children: (props: {
    id: string;
    name: string;
    className: string;
    "aria-invalid": boolean | undefined;
    "aria-describedby": string | undefined;
    defaultValue: string;
    maxLength: number;
  }) => React.ReactNode;
}) {
  const id = `contact-${field}`;
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;
  const error = state.errors[field];
  // One message slot, so it is either the error or the hint — never both, and
  // never an `aria-describedby` pointing at an id that is not in the document.
  const describedBy = error ? errorId : hint ? hintId : undefined;

  return (
    <div>
      <label htmlFor={id} className="eyebrow mb-1.5 block text-ink">
        {label}
      </label>
      {children({
        id,
        name: field,
        className: `${FIELD_CLASS} ${error ? INVALID_CLASS : ""}`,
        "aria-invalid": error ? true : undefined,
        "aria-describedby": describedBy,
        defaultValue: state.values[field],
        maxLength: LIMITS[field],
      })}
      {/* Reserved line: the slot exists whether or not there is a message, so
          an error never pushes the rest of the form down. */}
      <p
        id={error ? errorId : hintId}
        className={`mt-1 min-h-[1.125rem] text-xs ${error ? "text-ink" : "text-subtle"}`}
      >
        {error ?? hint ?? ""}
      </p>
    </div>
  );
}

export function ContactForm({ formToken }: { formToken: string }) {
  const [state, formAction, pending] = useActionState(
    submitContactForm,
    INITIAL_CONTACT_FORM_STATE,
  );
  const formRef = useRef<HTMLFormElement>(null);
  const handledAttempt = useRef(0);
  const headingId = useId();
  const honeypotId = useId();

  // Move focus to the first field the server rejected. Focus only — no state is
  // set here, which `react-hooks/set-state-in-effect` forbids.
  useEffect(() => {
    if (state.attempt === handledAttempt.current) return;
    handledAttempt.current = state.attempt;
    if (state.status !== "error") return;
    const first = CONTACT_FIELDS.find((field) => state.errors[field]);
    if (!first) return;
    const control = formRef.current?.querySelector<HTMLElement>(`#contact-${first}`);
    control?.focus();
  }, [state]);

  return (
    <section aria-labelledby={headingId} className="mt-12 border-t border-line pt-10">
      <h2 id={headingId} className="display text-2xl sm:text-3xl">
        Send us a message
      </h2>
      <p className="mt-2 text-sm leading-relaxed text-muted">
        We answer most enquiries within one business day. For anything about an
        existing order, add the order number to the subject line.
      </p>

      <form ref={formRef} action={formAction} noValidate className="mt-6">
        <input type="hidden" name={CONTACT_TOKEN_FIELD} value={formToken} />

        {/* Honeypot: off-screen, out of the tab order and out of the
            accessibility tree, so only an automated submitter fills it in. */}
        <div aria-hidden="true" className="absolute left-[-9999px] top-auto h-px w-px overflow-hidden">
          <label htmlFor={honeypotId}>Website</label>
          <input
            id={honeypotId}
            type="text"
            name={HONEYPOT_FIELD}
            tabIndex={-1}
            autoComplete="off"
            defaultValue=""
          />
        </div>

        {/* Remounted per attempt so each input re-applies the value the server
            echoed back; React resets an uncontrolled form after an action. */}
        <div key={state.attempt} className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
          <Field field="firstName" label="First name" state={state}>
            {(props) => <input {...props} type="text" autoComplete="given-name" required />}
          </Field>
          <Field field="lastName" label="Last name" state={state}>
            {(props) => <input {...props} type="text" autoComplete="family-name" required />}
          </Field>
          <Field field="email" label="Email address" state={state}>
            {(props) => <input {...props} type="email" autoComplete="email" required />}
          </Field>
          <Field field="phone" label="Phone" state={state} hint="Optional">
            {(props) => <input {...props} type="tel" autoComplete="tel" />}
          </Field>
          <div className="sm:col-span-2">
            <Field field="subject" label="Subject" state={state}>
              {(props) => <input {...props} type="text" required />}
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field
              field="message"
              label="Message"
              state={state}
              hint={`Up to ${LIMITS.message} characters`}
            >
              {(props) => <textarea {...props} rows={7} required className={`${props.className} resize-y`} />}
            </Field>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-4">
          <button
            type="submit"
            disabled={pending}
            className="rounded-full bg-ink px-6 py-2.5 text-sm font-semibold text-paper transition-colors hover:bg-ink-2 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {pending ? "Sending…" : "Send message"}
          </button>
          {/* One live region for the whole form. Keyed on the attempt so an
              identical repeated message is announced again. */}
          <p
            key={state.attempt}
            role="status"
            aria-live="polite"
            className={`min-h-[1.25rem] flex-1 text-sm ${
              state.status === "error" ? "text-ink" : "text-muted"
            }`}
          >
            {pending ? "Sending your message…" : state.message}
          </p>
        </div>
      </form>
    </section>
  );
}
