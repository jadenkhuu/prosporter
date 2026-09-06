# Forms (CLNT-171)

What happened to the WordPress forms, and how the storefront's replacement works.

Acceptance criterion 3 in `prosporter-project-schedule.md`: *"All forms submit
successfully and deliver to the client-nominated email address; validation and
error states work."*

## The three legacy Contact Form 7 forms

The WordPress source ran Contact Form 7 6.1.7 with three forms. The CF7 export
(`exports/cf7_forms.json`, git-ignored) carries only titles and ids, so the
field lists were recovered from the rendered form markup embedded in the page
content (`exports/pages.json`).

| # | CF7 id | Title | Where it was rendered | Disposition |
|---|---|---|---|---|
| 1 | 253 | Contact Form 2 | `/contact` (page 250), as `wpcf7-f253-o2` | **Rebuilt** as `src/components/content/ContactForm.tsx` |
| 2 | 97 | Newsletter | `/` (page 344, home), as `wpcf7-f97-o3` | **Retired.** Email marketing is out of scope |
| 3 | 96 | Contact form 1 | nowhere — no page or post references `wpcf7-f96` | **Retired.** Superseded by form 253 |

Only forms 253 and 97 appear in any exported page or post body; form 96 is an
orphan left over from the original theme install. The plugin register
(`docs/audit/plugin-and-integration-register.md`) records Contact Form 7 as
"rebuild in Next.js with server action / email provider" — this is that rebuild.

Akismet was the CF7 spam filter (the legacy markup carries the
`_wpcf7_ak_hp_textarea` honeypot and an `ak_js` timestamp). It is not migrated;
the replacement carries its own honeypot, timing token and rate limiter, so no
third-party anti-spam service or paid tier is required.

### Field mapping: form 253 to the rebuilt form

The legacy markup named all four of its text inputs `your-name` — a
misconfiguration that made CF7 deliver only the last value. The labels were
placeholder-only, which fails the semantic-structure requirement in acceptance
criterion 2. The rebuild keeps the visible field set and fixes both faults.

| Legacy control | Rebuilt field | Required | Limit |
|---|---|---|---|
| `your-name` (placeholder "First Name") | `firstName` | yes | 60 |
| `your-name` (placeholder "Last Name") | `lastName` | yes | 60 |
| `your-name` (placeholder "E-mail address") | `email` | yes | 160, format-checked |
| — (added) | `phone` | no | 32, digits and separators |
| `your-name` (placeholder "Subject") | `subject` | yes | 120 |
| `textarea-935` (maxlength 2000) | `message` | yes | 10–2000 |

`phone` is the one addition. The same Contact page advertises a phone line, and
a number supplied up front saves a round trip on order questions. It is
optional, so it cannot block a submission.

### Newsletter (form 97)

Not rebuilt, and nothing renders in its place. Schedule section 8 puts
"Email-marketing platform setup, template design, or list migration" out of
scope, and the source audit found **no marketing-consent field on any of the 178
customer records**, so there is no list to carry over and no consent basis for
one. Shopify already collects marketing opt-in at checkout and in customer
accounts, which covers the signup path without a new integration. If the client
wants a footer signup later, it is a variation: pick a provider, agree consent
copy, and wire it to that provider's list API.

## The rebuilt contact form

| File | Role |
|---|---|
| `src/lib/contact/validate.ts` | Field rules and the honeypot check. Pure; unit-tested |
| `src/lib/contact/token.ts` | HMAC-stamped render-time token (the timing check). Pure; unit-tested |
| `src/lib/contact/rate-limit.ts` | In-memory per-IP limiter. Pure; unit-tested |
| `src/lib/contact/state.ts` | `useActionState` shape, shared by both halves |
| `src/lib/contact/config.ts` | The only reader of the contact environment variables |
| `src/lib/contact/deliver.ts` | Provider abstraction: Resend over `fetch`, or a log-only adapter |
| `src/lib/contact/actions.ts` | `"use server"` action: spam checks, validation, delivery |
| `src/components/content/ContactSection.tsx` | Server component: form, or the phone/email fallback |
| `src/components/content/ContactForm.tsx` | Client component: fields, errors, pending and status |
| `src/lib/contact/__tests__/contact.test.mjs` | 28 Node tests over the three pure modules |

`src/app/(content)/[handle]/page.tsx` renders `ContactSection` under the
sanitised page copy when the handle is `contact`. The migrated copy still
carries the phone number, the email addresses and the opening hours; only the
dead CF7 markup is stripped, by `src/lib/content-html.ts`.

### Spam protection

Three layers, none of which needs a third-party service or a paid tier:

1. **Honeypot** — a `website` field, positioned off-screen, `tabIndex={-1}` and
   `aria-hidden`, so no person and no screen reader ever fills it in.
2. **Timing token** — the server stamps the render time into a hidden field and
   signs it with `CONTACT_FORM_SECRET`. A submission arriving under three
   seconds after render was not typed by a person; one over an hour old asks the
   visitor to reload. Because the token must be per request, `ContactSection`
   calls `connection()`, which takes `/contact` (and only `/contact`) out of
   prerendering.
3. **Rate limit** — five submissions per IP per ten minutes, in an in-memory
   Map. **Per instance and best effort**: on Vercel each serverless instance has
   its own Map, and counters are lost when an instance recycles, so a determined
   submitter spread across warm instances gets more than the nominal quota. This
   is the same trade the webhook route's duplicate-suppression LRU makes. It
   stops the case that matters — one client hammering the endpoint — and if real
   abuse ever appears, a shared store slots in behind the same `check()`
   signature.

A tripped honeypot or timing check gets the ordinary success message. Telling a
bot which check it failed is free tuning information. Only the rate limit, which
a person can legitimately hit, reports itself.

### Privacy in logs

Per `src/lib/log.ts`, no log line carries a name, email address, phone number or
message body. Submissions log a request id, the outcome, the adapter and counts
(`fieldErrors`, `messageLength`). Resend failures log the HTTP status only,
because the provider's error body can echo the address that was posted.

### Delivery and graceful degradation

`deliver.ts` picks an adapter from the environment:

| Environment | Config present | Adapter | Behaviour |
|---|---|---|---|
| any | yes | `resend` | `POST https://api.resend.com/emails`, `reply_to` set to the sender |
| development / preview | no | `log` | Accepted and dropped; one log line, no content |
| production | no | `none` | **No form is rendered.** The page shows a short note pointing at the phone number and email address in the copy above, and one `contact.delivery_unconfigured` warning is logged per instance |

The production-unconfigured case is the important one: a rendered form with no
delivery would take a message and lose it silently, which is worse for the
visitor than being asked to phone.

Resend is called with plain `fetch` — no npm dependency. Its SDK wraps a single
endpoint, and adding a package would need approval under the schedule's
variation process for no benefit. Resend's free tier is $0; **any paid tier
needs the client's written approval** (schedule section 8 / the variation
process). Swapping to SES, Postmark or anything else means one more adapter in
`deliver.ts`; `actions.ts` only sees `deliverContactMessage`.

## What the client still has to supply

1. **The nominated destination address** (`CONTACT_TO_EMAIL`). Until it exists,
   production renders the fallback rather than a dead form. This is a section 9
   client input and it blocks sign-off on acceptance criterion 3.
2. **A sending domain verified in Resend** (`CONTACT_FROM_EMAIL`). Resend
   requires SPF and DKIM records on the sending domain; publishing DNS records
   for `prosporter.com.au` is a client action. Until then, mail either does not
   send or lands in spam.
3. **A Resend account** on the free tier, owned by the client.

Environment variables and where to set them: `docs/deployment.md`.

## Accessibility

The form is covered by the storefront's accessibility notes (`docs/accessibility.md`):
real `<label for>` on every control (the legacy form had none), `aria-invalid`
plus `aria-describedby` on a rejected field, focus moved to the first invalid
field after a failed submit, one `role="status"` `aria-live="polite"` region for
the form-level outcome, a disabled submit button while pending, the global
`:focus-visible` ring, and a reserved line under every field so an error message
shifts nothing on the page.
