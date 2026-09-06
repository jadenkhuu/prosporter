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
   | `NEXT_PUBLIC_SITE_URL` | `https://prosporter.com.au` | **Production only.** Canonical origin; see "SEO routes" below |
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
the `Sitemap:` line in robots.txt and every `<loc>` in the sitemap. Set it **on Production
only**, to the live origin (`https://prosporter.com.au` after cutover; the `*.vercel.app`
production alias before it). Leave it unset on Preview so previews fall back to
`VERCEL_PROJECT_PRODUCTION_URL` / `VERCEL_URL`. `SITE_URL` is accepted as an alias.

Because both routes are prerendered, the variable must be present **at build time**, not
just at runtime. Changing it requires a redeploy, not just a redeploy of the env var.

### Preview deployments are never indexed

`src/app/robots.ts` returns `User-Agent: * / Disallow: /` whenever `VERCEL_ENV` is not
`production`, so every per-commit preview URL is disallow-all. This is separate from the
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

## Custom domain and go-live (later)

`prosporter.com.au` moves to Vercel at cutover (see `docs/migration/cutover-runbook.md`).
Checkout stays on Shopify's domain until a Shopify checkout domain is configured;
customer-account URLs likewise. Both are client decisions on CLNT-303.

## Rollback

Vercel → Deployments → Promote a previous production deployment. Shopify data is
unaffected by frontend rollbacks.
