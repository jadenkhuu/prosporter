/**
 * Response security headers (CLNT-179, defects D5 and D6).
 *
 * `next.config.ts` imports `securityHeaders()` and returns it from `headers()`
 * for every route, so every HTML, JSON and asset response carries the same set.
 * The list lives here rather than inline in the config for one reason: the
 * config also imports `docs/redirects/redirects.json`, which Node cannot load
 * without an import attribute, so a config-level export is not reachable from
 * `node --test`. This module has no imports at all and is covered by
 * `src/lib/__tests__/security-headers.test.mjs`.
 *
 * Nonces are deliberately not used. A per-request nonce has to be minted in
 * `src/proxy.ts` and forces dynamic rendering on every route (see
 * `node_modules/next/dist/docs/01-app/02-guides/content-security-policy.md`);
 * this storefront is almost entirely prerendered and its LCP is already over
 * budget (defect D3), so the policy is static and accepts `'unsafe-inline'`
 * for scripts. See `docs/deployment.md` § Security headers for the rationale
 * per directive and how to extend it.
 */

export type ResponseHeader = { key: string; value: string };

/**
 * Directive sources, one entry per directive. Keep the comments: they are the
 * record of *why* each origin is allowed, which is what makes it safe to
 * remove one later.
 */
function cspDirectives(isDev: boolean): string[] {
  return [
    // Everything not named below falls back to the storefront's own origin.
    "default-src 'self'",

    // 'unsafe-inline': src/components/analytics/Analytics.tsx renders an inline
    //   `id="ga4-init"` bootstrap (only when NEXT_PUBLIC_GA_MEASUREMENT_ID is
    //   set), and Next.js inlines its own flight/bootstrap scripts.
    // googletagmanager.com: gtag.js.
    // 'unsafe-eval' in development only — React uses eval to rebuild server
    //   stacks for the dev overlay. Production needs neither.
    `script-src 'self' 'unsafe-inline' https://www.googletagmanager.com${isDev ? " 'unsafe-eval'" : ""}`,

    // next/font self-hosts its faces, but Next and next/image both emit inline
    // style blocks and style attributes, which 'unsafe-inline' covers. Nothing
    // loads a third-party stylesheet.
    "style-src 'self' 'unsafe-inline'",

    // cdn.shopify.com is every product image (next.config.ts remotePatterns).
    // data:/blob: cover next/image placeholders. The Google hosts serve GA's
    // 1x1 collect pixel when a beacon falls back to an image request.
    //
    // The legacy WordPress origin is deliberately absent: migrated page bodies
    // were re-pointed at cdn.shopify.com on 6 Sep 2026 (CLNT-323), and after
    // cutover the storefront itself serves prosporter.com.au, so 'self' covers
    // it. If an image goes blank, fix the body in Shopify; do not re-add it.
    "img-src 'self' data: blob: https://cdn.shopify.com https://www.googletagmanager.com https://*.google-analytics.com",

    // next/font/google downloads at build time and serves from /_next; data:
    // is kept for inlined faces.
    "font-src 'self' data:",

    // Cart mutations are server actions (POSTs to this origin), so no
    // client-side call reaches Shopify. The Google hosts are GA4 beacons.
    // ws: in development is the dev server's HMR socket.
    `connect-src 'self' https://www.googletagmanager.com https://*.google-analytics.com https://*.analytics.google.com${isDev ? " ws: wss:" : ""}`,

    // Nothing on this storefront embeds or is embedded. frame-ancestors is the
    // modern half of the X-Frame-Options pair set below.
    "frame-src 'none'",
    "frame-ancestors 'none'",

    // Every <form> posts to this origin: the contact form and the cart drawer
    // are server actions, the search forms target /search. Shopify checkout is
    // reached by a link navigation from CartDrawer, which form-action does not
    // govern.
    "form-action 'self'",

    "base-uri 'self'",
    "object-src 'none'",
    "manifest-src 'self'",
    "upgrade-insecure-requests",
  ];
}

/** The `Content-Security-Policy` value, as one line. */
export function contentSecurityPolicy(isDev: boolean): string {
  return cspDirectives(isDev).join("; ");
}

/**
 * Browser features this storefront never uses. Payment is on Shopify's own
 * origin, not here, so the Payment Request API is denied too.
 */
const PERMISSIONS_POLICY = [
  "accelerometer=()",
  "camera=()",
  "geolocation=()",
  "microphone=()",
  "payment=()",
  "usb=()",
  // Chrome's ad-topics APIs, under both the old and current names.
  "interest-cohort=()",
  "browsing-topics=()",
].join(", ");

/** Applied to every route by `next.config.ts`. */
export function securityHeaders(isDev: boolean): ResponseHeader[] {
  return [
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    // Kept alongside CSP frame-ancestors for browsers that honour only one.
    { key: "X-Frame-Options", value: "DENY" },
    { key: "Permissions-Policy", value: PERMISSIONS_POLICY },
    { key: "Content-Security-Policy", value: contentSecurityPolicy(isDev) },
  ];
}
