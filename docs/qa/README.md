# ProSporter acceptance evidence pack (CLNT-179, Workstream 7)

Draft evidence for the acceptance criteria in
[`docs/prosporter-project-schedule.md`](../prosporter-project-schedule.md)
section 1 and the performance and quality standard in section 3.

| Field | Value |
|---|---|
| Target | `https://prosporter.vercel.app` (Vercel production deployment) |
| Commit under test | `70dc500` — *seo: keep the storefront out of the index until NEXT_PUBLIC_SITE_URL is set* |
| Measured | 6 September 2026, from Sydney (the deployment serves from `syd1`) |
| Scope | Read-only. Nothing under `src/` was changed to produce this pack. |

> **This deployment is deliberately `noindex, nofollow`.** `NEXT_PUBLIC_SITE_URL`
> is unset, so `isIndexableDeployment()` in `src/lib/site.ts` is false and
> `robots.txt`, `sitemap.xml` and the `X-Robots-Tag` header all take their
> pre-cutover shape. Treat that as expected, not as a defect. It does mean two
> SEO checks cannot be completed until cutover — they are marked below.

> **No personal data and no secrets are recorded here.** Cart cookie values,
> Shopify cart GIDs, checkout URLs and any matched credential shapes are
> reported by attribute or by shape only, never by value.

## Files

| File | What it holds | Produced by |
|---|---|---|
| [`crawl-report.md`](crawl-report.md) | Link and status crawl, image checks, legacy 308/410 replay | `scripts/qa/crawl.mjs` |
| [`crawl-results.csv`](crawl-results.csv) | Every URL checked, one row each | `scripts/qa/crawl.mjs` |
| [`performance.md`](performance.md) | Lighthouse mobile medians and LCP diagnostics | `scripts/qa/lighthouse.mjs` |
| [`lighthouse/`](lighthouse/) | The raw Lighthouse HTML reports (9 runs) | `scripts/qa/lighthouse.mjs` |
| [`responsive-and-console.md`](responsive-and-console.md) | Console errors, horizontal overflow, headings | `scripts/qa/console-and-responsive.mjs` |
| [`screenshots/`](screenshots/) | 27 PNGs: 9 pages x 375 / 768 / 1280 px | `scripts/qa/console-and-responsive.mjs` |
| [`security-and-seo.md`](security-and-seo.md) | Transport headers, per-page metadata, JSON-LD, bundle secret scan, cart cookie, webhook rejection | `scripts/qa/security-and-seo.mjs` |
| `*.json` | Machine-readable companions to the reports above | all scripts |

Every script is re-runnable against any deployment with `--base <url>`, uses
Node 22 stdlib only (plus `npx lighthouse@12`), and installs nothing.
`scripts/qa/cdp.mjs` is the shared Chrome DevTools Protocol client — this repo
has neither Playwright nor Puppeteer and a read-only QA pass is not the place to
add one, so the scripts drive the Chrome already on the machine directly.

## Section 1 — acceptance criteria

| # | Criterion | Verdict | Evidence | Notes |
|---:|---|---|---|---|
| 1 | Responsive layout at 375 / 768 / 1280 | **FAIL** | [`responsive-and-console.md`](responsive-and-console.md), [`screenshots/`](screenshots/) | Clean at 768 and 1280 on all nine key pages, and clean at 375 px on home, shop, collection, search, blog, article, contact and 404. **8 of 30 sampled product detail pages scroll horizontally at 375 px** — defect D1. |
| 2 | Chrome, Safari, Firefox, Edge | **Not yet testable** | — | Only Chrome (152) is installed on the measurement machine, and Safari, Firefox and Edge cannot be driven headlessly from here. Needs a real browser matrix (manual devices or a cross-browser service); Safari on iOS in particular has to be checked by hand. |
| 3 | Forms submit and deliver | **Not yet testable** | [`security-and-seo.md`](security-and-seo.md), `docs/forms.md` | `/contact` currently renders the documented fallback ("Our contact form is being set up") because `CONTACT_TO_EMAIL` has not been nominated — a client input under schedule section 9. There is no form to submit yet, so neither delivery nor validation states can be exercised on this deployment. |
| 4 | Lighthouse Performance >= 85 mobile, home + one interior page | **PASS** | [`performance.md`](performance.md) | Median mobile Performance 96 (home), 97 (collection), 94 (product) over three runs each. |
| 5 | HTTPS enforced, no secrets client-side | **PASS** (with hardening gaps) | [`security-and-seo.md`](security-and-seo.md) | `http://` 308s to `https://`; HSTS `max-age=63072000; includeSubDomains; preload`. 16 served JS chunks (685 KB) carry no `shpat_`/`shpss_`/`shpca_`, no Storefront or webhook secret name or value, no `RESEND_*`, no bare 32-hex literal. Standard hardening headers are absent — defects D5 and D6. |
| 6 | Unique title and description, semantic headings, sitemap, robots, Open Graph | **PARTIAL** | [`security-and-seo.md`](security-and-seo.md) | Unique `<title>` on all nine pages, a meta description on all nine, exactly one `<h1>` on every page that should have one, canonical on seven of nine, `og:title`/`og:description`/`og:type`/`twitter:card` everywhere, valid JSON-LD on home, collection, product, blog and article. Two gaps: `og:image` only on product pages (D8), and the sitemap/robots half is **not yet testable** — both files serve their pre-cutover shape until `NEXT_PUBLIC_SITE_URL` is set. |
| 7 | GA4 (or nominated equivalent) recording on a client-owned property | **Not yet testable** | `src/components/analytics/Analytics.tsx`, `docs/deployment.md` | The integration is built (page views, `view_item`, `add_to_cart`, `begin_checkout`, a checkout-domain linker, Consent Mode v2 defaults) but renders nothing while `NEXT_PUBLIC_GA_MEASUREMENT_ID` is unset. Verified: zero `googletagmanager.com` requests on this deployment. The client's GA4 property is still wired to the live WooCommerce store, so it must not receive traffic before cutover. Testable only once the client supplies the measurement ID. |
| 8 | All internal links resolve, no broken links | **PASS** (with an SEO caveat) | [`crawl-report.md`](crawl-report.md) | 182 pages and 386 images crawled: every internal link resolved 200, no broken image. Six legacy product URLs the redirect map promises as 200 return 404, but nothing on the site links to them — defect D4. Separately, eight live pages have no inbound link at all — defect D2. |
| 9 | No JavaScript console errors on any key page | **PASS** | [`responsive-and-console.md`](responsive-and-console.md) | 27 measurements (9 pages x 3 widths): zero uncaught exceptions and zero `console.error` on every page at every width. The only error-level browser log anywhere is Chrome noting the intended 404 status on the 404 route, which is a network fact rather than a JavaScript error and is counted in its own column. |
| 10 | Functional test pass completed, results shared | **PARTIAL** | this folder | This pack is that record. It is not complete until criteria 2, 3 and 7 and section 3 criterion 3 can be exercised. |

## Section 3 — performance and quality standard

| # | Criterion | Verdict | Evidence | Notes |
|---:|---|---|---|---|
| 1 | Performance >= 85 **and LCP < 2.5 s** on home, a collection and a product page | **FAIL** on LCP | [`performance.md`](performance.md) | Performance passes comfortably (96 / 97 / 94). Median LCP is 2.75 s (home), 2.57 s (collection) and 3.12 s (product) — all three over the 2.5 s bar. Defect D3. |
| 2 | CLS < 0.1 and INP < 200 ms | **PASS on CLS; INP not yet testable** | [`performance.md`](performance.md) | CLS 0.000 on all three pages in all nine runs. INP is not a Lighthouse lab metric; it needs real interactions or field data. The lab proxy is healthy (TBT 7-39 ms, Max Potential FID 63-89 ms), but a defensible INP number needs CrUX or GA4 Web Vitals after launch. |
| 3 | Cart and checkout complete reliably; verified by a live test order | **PARTIAL** | [`security-and-seo.md`](security-and-seo.md) | Add to cart verified live in a real browser: variant selected, item added, bag reads 1 item / $40.00, the Shopify cart persists across a reload, and `prosporter_cart` comes back `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`. Cart update, discount codes, shipping calculation, payment and order confirmation are **not yet testable** — they need a real test order through Shopify checkout with payments configured, which is a cutover activity. |
| 4 | No unresolved Critical Defect at go-live | **PASS as measured** | below | Nothing found in this pass meets the schedule's Critical definition. Criterion 3's untested half could still surface one, so this is provisional. |

## Defects

Severity uses the schedule's own definition. A **Critical Defect** prevents
browsing products, prevents adding to cart, prevents checkout or order
confirmation, causes incorrect pricing or stock, or loses order data. Everything
else is graded by impact on acceptance.

**No Critical Defect was found in this pass.**

| ID | Severity | Defect | Where | Criterion |
|---|---|---|---|---|
| D1 | High (not Critical) | Product detail pages scroll horizontally at 375 px: **8 of 30 sampled products (27%)**. The gallery thumbnail strip (`ul.mt-3.flex.gap-3.overflow-x-auto.pb-1`) carries `overflow-x-auto` but nothing constrains its width, so its 80 px `img.object-cover` thumbnails widen the whole document instead of scrolling inside the strip. The document width scales with the image count: 465, 556, 648, 740, 833 and 1200 px observed against a 375 px viewport. Products with two or fewer images are unaffected, which is why a single-page check misses it. | `/product/knee-pads-sleek` (1200 px), `/product/provolley-mens-volleyball-jersey-sydney` (833 px), `/product/ace-unisex` (648 px) and five more listed in `responsive-and-console.md` | 1.1 |
| D2 | High (not Critical) | Eight live pages have no inbound link anywhere on the site. The primary nav and the footer carry only shop and collection links, so `/blog`, `/contact`, `/about`, `/faq`, `/size-guide`, `/terms-of-service`, `/refund-policy` and `/privacy-policy` are reachable only by typing the URL. Refund and privacy policies being unreachable is a commercial and consumer-law exposure as well as an SEO one. A link crawl from `/` never finds them, which is why the crawler seeds them explicitly. | `https://prosporter.vercel.app/` (header and footer) | 1.6, 1.8 |
| D3 | Medium | Largest Contentful Paint exceeds the 2.5 s standard on all three measured page types (2.75 / 2.57 / 3.12 s median). Home is image-bound: the hero `img.object-cover` spends 1.71 s (62% of LCP) in Load Time. Product is render-bound: 2.48 s (79%) in Render Delay on a text element. | `/`, `/shop/jerseys`, `/product/ace-unisex` | 3.1 |
| D4 | Medium | Six legacy product permalinks are recorded in `docs/redirects/redirect-map.csv` as `outcome=same_url, status_code=200` ("must return 200") but return 404: `/product/inner-west-jersey`, `/product/modena-jersey`, `/product/modena-volley-shorts`, `/product/modena-volley-jersey`, `/product/provolley-jersey`, `/product/provolley-womens-jersey`. The cause is upstream and known — all six are held in `docs/migration/exception-register.csv` under `attribute_needs_decision` pending a client answer on whether `Condition`/`Number` are variant-defining — but the redirect map has not been reconciled with that hold, so six indexed legacy URLs will 404 rather than redirect or answer 410 at cutover. | `https://prosporter.vercel.app/product/modena-jersey` and five siblings | 1.8 |
| D5 | Medium | `X-Content-Type-Options`, `Referrer-Policy` and `X-Frame-Options` (or a CSP `frame-ancestors`) are absent from HTML responses. | all pages | 1.5 |
| D6 | Low | No `Content-Security-Policy` and no `Permissions-Policy`. | all pages | 1.5 |
| D7 | Low | `og:image` is present only on product pages. Home, shop, collection, blog, article and content pages share without a card image. | all non-product pages | 1.6 |
| D8 | Low | No canonical link on `/search` or on the 404 route, and the 404 route reuses the home page's meta description verbatim. `/search` is already `noindex, follow`, so its missing canonical is defensible; the duplicated 404 description is not. | `/search?q=…`, any 404 URL | 1.6 |
| D9 | Low (UX) | "Add to bag" is enabled before a variant is chosen. Clicking it does nothing except surface "Please choose size and colour before adding to bag" in the live region. The message is correct and accessible, but a disabled button (or auto-selecting the only in-stock variant) would be clearer. | `https://prosporter.vercel.app/product/ace-unisex` | 3.3 |

## What still has to happen before sign-off

1. **Client inputs.** `CONTACT_TO_EMAIL` and a Resend sending domain (criterion 3), and the GA4 measurement ID for a client-owned property (criterion 7). Both are schedule section 9 dependencies.
2. **Cutover configuration.** `NEXT_PUBLIC_SITE_URL` — it flips indexability, the real `robots.txt` and the ~200-URL sitemap, and completes criterion 6.
3. **A cross-browser pass** on current Chrome, Safari, Firefox and Edge, including Safari on iOS (criterion 2).
4. **One live test order** through Shopify checkout covering cart update, a discount code, shipping calculation, payment and order confirmation (section 3 criterion 3).
5. **Field Web Vitals** once traffic exists, to close the INP half of section 3 criterion 2.
6. **Fix D1 and D3**, both of which are outright failures against sections 1.1 and 3.1 rather than pending evidence.

## Defect status after the 6 Sep 2026 fix pass

| ID | Status | Commit | Note |
|---|---|---|---|
| D1 | Fixed | `07baeb2` | Gallery grid item gets `min-w-0`; all 8 overflowing products verified at 375 px |
| D2 | Fixed | `e4e908a` | Help and Company/Legal footer columns link every content page and the blog |
| D3 | Fixed | `3127c43` | Home 2.25 s, collection 2.36 s, product 2.43 s on Vercel; see `performance.md` history |
| D4 | Fixed | `b47903c` | Six held products 308 to their primary collection until loaded |
| D5 | Fixed | `e4e908a` | nosniff, referrer-policy, X-Frame-Options, Permissions-Policy |
| D6 | Fixed | `e4e908a` | Static CSP; WordPress origins stay in `img-src` until CLNT-323's live run |
| D7 | Fixed | `07baeb2` | Default 1200x630 OG image on every non-product page |
| D8 | Fixed | `07baeb2` | 404 route has its own description and noindex; `/search` self-canonical |
| D9 | Fixed | `07baeb2` | Add to bag disabled with a hint until a purchasable variant is chosen |

New since the pass: CLNT-323, migrated page bodies hotlink images from the WordPress
domain (breaks at cutover). Pipeline fix committed in `e253b17`; live run pending.
Crawl, console/responsive and header checks have not been re-run after these commits;
re-run `scripts/qa/*.mjs` before the pack goes to the client.
