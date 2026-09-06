# Deployment (Vercel)

The storefront is a Next.js 16 app deployed on Vercel. Shopify is the backend; the
app only ever holds the **public** Storefront token and the webhook signing secret.
No Admin API credential is ever configured on the host.

## One-time setup

1. Vercel dashboard → **Add New → Project → Import** `stealth-startup-2026/prosporter`.
   Framework preset: Next.js (auto-detected). Root directory: repository root.
   Build command, output and install command: defaults. Node.js: 22.x (pinned in
   `package.json` `engines`).
2. **Environment variables** (Settings → Environment Variables). Set for Production and
   Preview; values come from the local `.env.local`, never from git:

   | Name | Value | Notes |
   |---|---|---|
   | `SHOPIFY_STORE_DOMAIN` | `prosporter.myshopify.com` | `*.myshopify.com` only |
   | `SHOPIFY_STOREFRONT_TOKEN` | Headless channel public token | dev storefront token for now; swap for a production storefront token before go-live |
   | `SHOPIFY_WEBHOOK_SECRET` | ProSporter-migration app client secret | HMAC key for `/api/webhooks/shopify` (see `docs/webhooks.md`) |
   | `NEXT_PUBLIC_SITE_URL` | `https://prosporter.com.au` | **Production only, set on cutover day.** Canonical origin and the indexing switch; see "SEO routes" below |
   | `RESEND_API_KEY` | Resend API key | Production **and** Preview. Contact form; see "Contact form" below |
   | `CONTACT_TO_EMAIL` | client-nominated inbox | Production and Preview. **Not yet supplied** |
   | `CONTACT_FROM_EMAIL` | e.g. `website@prosporter.com.au` | Production and Preview. Domain must be verified in Resend |
   | `CONTACT_FORM_SECRET` | `openssl rand -hex 32` | Production and Preview; optional but recommended |
   | `LOG_LEVEL` | `info` | optional |

   Do **not** set `SHOPIFY_OPTIONAL` on Vercel. It exists only so CI can build without a
   store; on the host it would let a misconfigured deploy boot in mock mode.
3. Deploy. Production tracks `main`; every other branch and PR gets a preview URL.
4. Region is pinned to Sydney (`syd1`) in `vercel.json` so server rendering sits next to
   the Australian shoppers and Shopify's AU checkout.

## After the first deploy

- Register webhooks against the deployment URL (dry run first):

  ```bash
  python3 scripts/webhooks/register_webhooks.py ensure https://<deployment-host>
  python3 scripts/webhooks/register_webhooks.py ensure https://<deployment-host> --apply
  ```

  Use the stable production hostname (custom domain or the `*.vercel.app` production
  alias), not a per-commit preview URL.
- Verify: `curl -sI https://<host>/product/nago` → 200; `https://<host>/cart` → 410;
  `https://<host>/product/<any>/` → single 308. `python3 scripts/redirects/verify_redirects.py`
  can be pointed at the host.

## Contact form

`/contact` renders a real form (`docs/forms.md`) that emails each submission through
Resend. Four variables drive it, all read by `src/lib/contact/config.ts` and nothing else:

| Name | Required | Notes |
|---|---|---|
| `RESEND_API_KEY` | yes | Resend account API key. The **free tier is $0**; moving to any paid tier is a variation and needs the client's written approval (schedule section 8) |
| `CONTACT_TO_EMAIL` | yes | Where submissions land. **Client dependency — the client has not nominated the address yet** (schedule section 9). Acceptance criterion 3 cannot be signed off until it exists |
| `CONTACT_FROM_EMAIL` | yes | Envelope sender. Must sit on a domain **verified in Resend**, which needs SPF and DKIM records published on `prosporter.com.au`. Publishing DNS is a client action; until it is done, mail either fails to send or is filed as spam |
| `CONTACT_FORM_SECRET` | no | HMAC key for the anti-spam timing token. Unset means the token is unsigned and forgeable — set it |

Set all four on **Production and Preview**. Preview is where the form is exercised
before go-live, and a preview deployment with no configuration silently switches to the
log-only adapter.

Behaviour when the variables are missing is deliberate, not accidental:

- **development / preview, unconfigured** — the form renders and works, and each
  submission is logged (outcome and counts only, never its contents) instead of emailed.
- **production, unconfigured** — no form is rendered. `/contact` shows a short note
  pointing at the phone number and email address already in the page copy, and logs one
  `contact.delivery_unconfigured` warning per instance. A form that accepted a message
  and dropped it would be worse than none.

`/contact` is the one `(content)` page that renders on demand rather than being
prerendered: the form's timing token has to be stamped per request. Every other handle
still comes out of `generateStaticParams`.

Verify after a deploy:

```bash
# The form is present (not the fallback) once the variables are set
curl -s https://<host>/contact | grep -c 'name="firstName"'   # 1

# Submissions log an outcome with no personal data
vercel logs <deployment> | grep contact.
```

Then send one real message and confirm it arrives at `CONTACT_TO_EMAIL`, that the reply
address is the sender's, and that the client can reply to it. That check is the evidence
for acceptance criterion 3.

## Caching model on Vercel

Catalog, content and search reads use the Next data cache with tags (`src/lib/shopify/tags.ts`)
and time-based revalidation (1 h catalog, 5 min search). On Vercel that cache is shared
across regions and instances, so a webhook hitting one function invalidates for all.
The webhook route's duplicate-suppression LRU is per instance and best effort; Shopify
retries are idempotent anyway because revalidation is.

## Security headers (CLNT-179, defects D5 and D6)

`next.config.ts` returns one `headers()` rule matching `/:path*`, so every response —
HTML, RSC payload, `/_next/*` asset, API route — carries the same set. The values and
the reasoning behind each one live in `src/lib/security-headers.ts`, covered by
`src/lib/__tests__/security-headers.test.mjs` (`npm test`).

| Header | Value | Why |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | Stops MIME sniffing turning a user-supplied response into script. |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Full path to our own origin, origin only cross-site, nothing on an HTTPS→HTTP downgrade. |
| `X-Frame-Options` | `DENY` | Clickjacking. Kept next to CSP `frame-ancestors` for browsers that honour only one. |
| `Permissions-Policy` | `accelerometer=(), camera=(), geolocation=(), microphone=(), payment=(), usb=(), interest-cohort=(), browsing-topics=()` | Nothing here uses any of them. `payment=()` is safe because checkout runs on Shopify's origin, not this one. The last two are Chrome's ad-topics API under both names. |
| `Content-Security-Policy` | see below | XSS and injection. |

HSTS is **not** set here: Vercel already sends
`Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`. Setting it in
two places invites them to drift.

### The policy

```
default-src 'self';
script-src 'self' 'unsafe-inline' https://www.googletagmanager.com;
style-src 'self' 'unsafe-inline';
img-src 'self' data: blob: https://cdn.shopify.com https://www.googletagmanager.com https://*.google-analytics.com;
font-src 'self' data:;
connect-src 'self' https://www.googletagmanager.com https://*.google-analytics.com https://*.analytics.google.com;
frame-src 'none';
frame-ancestors 'none';
form-action 'self';
base-uri 'self';
object-src 'none';
manifest-src 'self';
upgrade-insecure-requests
```

Development adds `'unsafe-eval'` to `script-src` (React rebuilds server error stacks with
`eval` for the dev overlay) and `ws: wss:` to `connect-src` (the Turbopack HMR socket).
Neither is present in production. The switch is `NODE_ENV === "development"`, read in
`next.config.ts` and passed into `securityHeaders()`.

What each non-`'self'` source is for:

- **`script-src 'unsafe-inline'`** — `src/components/analytics/Analytics.tsx` renders an
  inline `id="ga4-init"` bootstrap (the gtag stub, Consent Mode v2 defaults and `config`,
  which must run during parse, before hydration), and Next.js inlines its own bootstrap
  and flight-data scripts. JSON-LD `<script type="application/ld+json">` blocks are *not*
  the reason — CSP never executes them, so they need no allowance.
- **`script-src https://www.googletagmanager.com`** — `gtag.js`, loaded `afterInteractive`.
  It requests nothing while `NEXT_PUBLIC_GA_MEASUREMENT_ID` is unset.
- **`style-src 'unsafe-inline'`** — Next.js and `next/image` emit inline `<style>` blocks
  and `style` attributes. Nothing loads a third-party stylesheet; `next/font/google`
  self-hosts its faces at build time, which is why `font-src` is `'self'` only.
- **`img-src https://cdn.shopify.com`** — every product image, matching the
  `remotePatterns` allow-list in `next.config.ts`. `data:`/`blob:` cover `next/image`
  placeholders; the two Google hosts cover GA's pixel fallback.
- **No legacy WordPress origin.** Migrated page bodies were re-pointed at
  `cdn.shopify.com` on 6 Sep 2026 (CLNT-323, `scripts/migration/body_media.py`), and the
  test suite asserts the origin stays out of `img-src`. If a content image goes blank, fix
  the body in Shopify (or re-run the content stage) rather than re-adding the origin.
- **`connect-src` Google hosts** — GA4 beacons. There is deliberately **no** Shopify
  origin here: cart reads and writes are server actions that POST to this origin, and no
  client component fetches the Storefront API.
- **`form-action 'self'`** — the contact form and the cart drawer are server actions, and
  both search forms target `/search`. The Shopify checkout is an `<a href>` navigation
  from `CartDrawer`, which `form-action` does not govern, so no Shopify origin is needed.

### Why no nonce

The Next.js guide's strict CSP mints a per-request nonce in `src/proxy.ts`, which forces
**dynamic rendering on every route**. This storefront is almost entirely prerendered and
its LCP is already over the 2.5 s standard (QA defect D3), so trading the prerender for a
nonce is the wrong trade today. Revisit if LCP is fixed and an inline-script XSS becomes
a real risk; the change is confined to `src/proxy.ts` plus the `script-src`/`style-src`
lines here.

### Extending it

1. Edit `src/lib/security-headers.ts` — add the origin to the narrowest directive that
   works, with a comment saying what needs it. Never widen `default-src`.
2. Update the test in `src/lib/__tests__/security-headers.test.mjs`.
3. Rebuild before checking: `next start` serves the config snapshot written into
   `.next/required-server-files.json` at build time, so an edited policy does **not**
   appear until `npm run build` runs again.
4. Verify with a real browser, not just `curl -I`:

```bash
npm run build && PORT=3177 npm run start
curl -s -D - -o /dev/null http://127.0.0.1:3177/ | grep -i 'content-security'
```

   Then load `/`, `/shop`, a product, `/search?q=…`, `/contact`, `/blog` and an article
   with DevTools open and confirm the console reports zero CSP violations. `scripts/qa/cdp.mjs`
   drives headless Chrome for this without installing anything. To exercise the GA4 half,
   build with `NEXT_PUBLIC_GA_MEASUREMENT_ID` set to a throwaway property — with it unset,
   the inline bootstrap and `gtag.js` never render and the policy is not fully tested.

## SEO routes: sitemap, robots and structured data

| Route | Source | Notes |
|---|---|---|
| `/sitemap.xml` | `src/app/sitemap.ts` | Home, `/shop` + every collection, every product, every `(content)` page, `/blog` + every article. `lastmod` is Shopify `updatedAt` / `publishedAt`. ~180 URLs, one file — no `generateSitemaps` needed until the catalog grows an order of magnitude. |
| `/robots.txt` | `src/app/robots.ts` | Production: allow all, disallow `/search`, `/api/`, `/cart`, `/checkout`, `/account` and the `?sort=` / `?filter` facet permutations, plus the `Sitemap:` line. Anything that is not production: **disallow-all**. |
| JSON-LD | `src/lib/seo/json-ld.ts` | Organization + WebSite (SearchAction → `/search?q=`) in the root layout; Product + BreadcrumbList on `/product/[slug]`; BreadcrumbList on `/shop/...` and content pages; Article + BreadcrumbList on `/blog/[slug]`. |

Both routes are prerendered at build time and revalidate hourly, matching the catalog
cache window in `src/lib/shopify/tags.ts`.

### The site URL is one value

`NEXT_PUBLIC_SITE_URL` (`src/lib/site.ts`) is the only origin the app knows. It feeds
`metadataBase` in the root layout, every `alternates.canonical`, every Open Graph URL,
the `Sitemap:` line in robots.txt and every `<loc>` in the sitemap. It is also the
**indexing switch**: while it is unset, the production deployment returns disallow-all
from robots.txt and `X-Robots-Tag: noindex, nofollow` on every page, because before
cutover the `*.vercel.app` alias is a duplicate of the live WooCommerce store on the real
domain. Set it **on Production only, on cutover day**, to `https://prosporter.com.au`.
Never set it to the `*.vercel.app` alias. Leave it unset on Preview so previews fall back
to `VERCEL_PROJECT_PRODUCTION_URL` / `VERCEL_URL`. `SITE_URL` is accepted as an alias.

Because both routes are prerendered, the variable must be present **at build time**, not
just at runtime. Changing it requires a redeploy, not just a redeploy of the env var.

### Nothing is indexed before cutover, and previews never are

`src/app/robots.ts` returns `User-Agent: * / Disallow: /` and `src/proxy.ts` adds
`X-Robots-Tag: noindex, nofollow` whenever `VERCEL_ENV` is not `production` **or**
`NEXT_PUBLIC_SITE_URL` is unset (`isIndexableDeployment()` in `src/lib/site.ts`). So every
per-commit preview URL and the pre-cutover production alias are both kept out of the index. This is separate from the
two places that carry a real `noindex`: `/search` (route metadata, `noindex, follow`) and
the 410 bodies in `src/proxy.ts` (`X-Robots-Tag: noindex`). robots.txt is a crawl
directive, not an index directive — do not replace either of those with it.

### Validating after a deploy

```bash
# Production: allow-list plus the sitemap line
curl -s https://<host>/robots.txt
# A preview URL must answer "User-Agent: *\nDisallow: /"
curl -s https://<preview-host>/robots.txt

# Sitemap: 200, application/xml, and a URL count that matches the catalog
curl -sI https://<host>/sitemap.xml
curl -s  https://<host>/sitemap.xml | grep -c "<loc>"
# Every <loc> must be on the canonical origin
curl -s  https://<host>/sitemap.xml | grep -o "<loc>[^<]*" | sed "s|<loc>||" | cut -d/ -f1-3 | sort -u
```

Structured data: paste a product, a collection and an article URL into Google's
[Rich Results Test](https://search.google.com/test/rich-results) and the
[Schema Markup Validator](https://validator.schema.org/). A product page must report
`Product` (with `offers`) and `Breadcrumb` with no errors. Locally,
`curl -s http://localhost:3000/product/<handle> | grep -o "application/ld+json"` confirms
the blocks are server-rendered rather than injected by client JavaScript.

Finally, submit `https://<host>/sitemap.xml` in Google Search Console once the custom
domain is live (CLNT-303).

## Analytics (GA4, CLNT-179)

One environment variable turns the whole thing on:

| Variable | Where | Value |
| --- | --- | --- |
| `NEXT_PUBLIC_GA_MEASUREMENT_ID` | Vercel → Production **only, at cutover** | `G-XXXXXXXXXX` |
| `NEXT_PUBLIC_GA_DEBUG` | Local `.env.local`, or a Preview deployment while validating | `1` |

### Why it is not set yet

The client's existing GA4 property is attached to the **live WooCommerce store**. Sending
this storefront's traffic to it before cutover would mix a staging site's sessions into the
numbers the business currently reports on. So the variable stays unset until the client
supplies the property (or a new one) and the DNS switch happens.

Unset is a hard off, not a soft one: `src/components/analytics/Analytics.tsx` returns `null`,
so there is no `<script>` tag, no request to `googletagmanager.com`, and `track()` in
`src/lib/analytics/track.ts` returns before it logs or pushes anything. Nothing to clean up
later — just add the variable and redeploy.

Do **not** set it on Preview deployments for day-to-day work. Preview traffic is agency
traffic; it would pollute the property with sessions nobody wants to report on.

### What is implemented

Loaded with `next/script` (`afterInteractive`), not `@next/third-parties/google` — that
package is not a dependency here and is not bundled with Next, and it was not worth adding
one for a 20-line snippet. Behaviour is the same.

- **Consent Mode v2 defaults**, set before `config`: `ad_storage`, `ad_user_data` and
  `ad_personalization` **denied**; `analytics_storage` **granted**. No consent banner is in
  scope for this build. When one is added it flips these at runtime with
  `gtag('consent', 'update', {...})` — no change to the tag itself is needed.
- **No advertising signals**: `allow_google_signals: false`,
  `allow_ad_personalization_signals: false`, `anonymize_ip: true`. This is an
  analytics-only tag.
- **No personal data.** No `user_id`, email, name, phone or address is ever passed. A unit
  test asserts the builders emit none of those keys.
- **`send_page_view: false`** plus a `page_view` we fire ourselves on every pathname+search
  change (`src/lib/analytics/page-view.ts`). Without this, a hard load would be counted by
  gtag and a client-side navigation not counted at all. With it: exactly one `page_view` per
  distinct URL, hard load and SPA navigation alike.

### Where each event fires

| Event | Fired from | Notes |
| --- | --- | --- |
| `page_view` | `src/components/analytics/Analytics.tsx` (`<PageViews />`) | Once per distinct pathname+search. |
| `view_item` | `src/components/product/ProductDetail.tsx` | Once per product, on mount. **Not** re-sent when the shopper changes size or colour. |
| `add_to_cart` | `src/components/cart/CartProvider.tsx` (`addVariant`) | Only after the `addToCart` server action returns without an error, and only for the line Shopify actually returned. Reports the quantity just added, not the line's new total. |
| `begin_checkout` | `src/components/cart/CartDrawer.tsx` (Checkout button) | All cart lines, Shopify's costed total as `value`, the applied discount code as `coupon`. |
| `purchase` | **Shopify, not this app** | See below. |

`item_id` is the merchant SKU when the variant has one, otherwise the numeric Shopify
variant id — the same identifier Shopify's own integration sends, so both halves of the
funnel land on the same product in GA4.

### `purchase` comes from Shopify

Checkout is hosted by Shopify on `prosporter.myshopify.com`. This app never sees the order,
so it cannot and must not fire `purchase`. Two steps, both on the Shopify side, at cutover:

1. Install/connect the **Google & YouTube** channel in the Shopify admin and connect it to
   **the same GA4 property** as `NEXT_PUBLIC_GA_MEASUREMENT_ID`. It emits `purchase` (and
   the checkout-funnel events) from Shopify's checkout.
2. In GA4: **Admin → Data streams → the web stream → Configure tag settings → Configure your
   domains**, and list both the storefront host and `prosporter.myshopify.com` (plus
   `shop.app` if Shop Pay is enabled).

### Cross-domain: how the session stitches

The storefront tag is configured with a gtag `linker` covering
`prosporter.myshopify.com` and `shop.app` (`CHECKOUT_LINKER_DOMAINS` in
`src/lib/analytics/config.ts`), `accept_incoming: true`. The drawer's Checkout control is a
real `<a href={checkoutUrl}>`, so gtag decorates the click with a **`_gl` linker parameter**
carrying the GA client id; Shopify's Google tag on the checkout page reads `_gl` and adopts
that client id, so `begin_checkout` here and `purchase` there sit in one session.

Confidence and caveats, to be verified during QA rather than assumed:

- `_gl` is the current GA4 mechanism. The `_ga` client-id query parameter is the
  **Universal Analytics-era** form; do not build on it.
- The GA4 admin "Configure your domains" list (step 2 above) and the `linker` config do the
  same job. Setting both is belt-and-braces and is the recommended path — the admin setting
  is what Google now documents, the in-code `linker` is what guarantees the decoration
  happens even before the admin list propagates.
- Not yet verified against the live store: whether Shopify's checkout tag honours `_gl` on
  every checkout-extensibility surface. Validate in DebugView at cutover (checklist below);
  if the session splits, the fix is on the Shopify/GA4 admin side, not in this repo.

### Validating with GA4 DebugView

```bash
# Local: point at a throwaway/dev GA4 property, never the client's live one.
echo 'NEXT_PUBLIC_GA_MEASUREMENT_ID=G-XXXXXXXXXX' >> .env.local
echo 'NEXT_PUBLIC_GA_DEBUG=1' >> .env.local
npm run dev
```

`NEXT_PUBLIC_GA_DEBUG=1` does two things: it adds `debug_mode: true` to the config, which
puts every hit in **GA4 → Admin → DebugView**, and it mirrors each event to the browser
console as `[ga4] <event> {…}` so you can see the payload without leaving the page. Both are
still gated on the measurement id — with no id there is no console output either.

### QA checklist (each event, once and only once)

- [ ] With `NEXT_PUBLIC_GA_MEASUREMENT_ID` unset: no `googletagmanager.com` request in the
      network panel, no `[ga4]` line in the console.
- [ ] `page_view` — load the home page: exactly one. Navigate to /shop and to a product:
      one each. Press Back: one. Re-render (change a filter that does not change the URL):
      none.
- [ ] `page_view` — a filter change that *does* change the query string: exactly one.
- [ ] `view_item` — open a product page: one. Change size and colour: still one.
- [ ] `add_to_cart` — add to bag: one, with `item_id`, `item_variant`, `price`, `quantity`
      and `currency` populated. Add the same variant again: one more, `quantity: 1`.
- [ ] `add_to_cart` — a failed add (sold-out variant): **none**.
- [ ] `begin_checkout` — click Checkout: one, `value` equal to the drawer's Total, `coupon`
      set when a discount code is applied.
- [ ] Cross-domain — the checkout URL that opens carries a `_gl=` parameter.
- [ ] `purchase` — complete a test order: one, from Shopify, in the **same session** as the
      `begin_checkout` above (check the user snapshot in DebugView).
- [ ] No event carries an email, name, phone, address or user id.

## Custom domain and go-live (later)

`prosporter.com.au` moves to Vercel at cutover (see `docs/migration/cutover-runbook.md`).
Checkout stays on Shopify's domain until a Shopify checkout domain is configured;
customer-account URLs likewise. Both are client decisions on CLNT-303.

## Rollback

Vercel → Deployments → Promote a previous production deployment. Shopify data is
unaffected by frontend rollbacks.
