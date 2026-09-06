/**
 * GA4 configuration (CLNT-179).
 *
 * One rule governs this whole slice: **nothing happens without
 * `NEXT_PUBLIC_GA_MEASUREMENT_ID`.** The client's existing GA4 property is
 * still attached to the live WooCommerce store, so until cutover the variable
 * stays unset and the storefront must load no script, make no network call and
 * write nothing to the console. Every entry point below returns a falsy value
 * in that state and `track()` becomes a no-op.
 *
 * The `process.env.NEXT_PUBLIC_*` reads are written as literal member
 * expressions on purpose: that is what Next inlines into the client bundle at
 * build time. Do not refactor them behind a variable index.
 */

/** `G-XXXXXXX`. Null until the client hands over their own property. */
export function measurementId(): string | null {
  const value = (process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID ?? "").trim();
  return value ? value : null;
}

/** True once a measurement id is configured. Gates the script and every event. */
export function isAnalyticsEnabled(): boolean {
  return measurementId() !== null;
}

/**
 * `NEXT_PUBLIC_GA_DEBUG=1` adds `debug_mode` to the config (so hits show up in
 * GA4 DebugView) and mirrors every event to `console.debug`. Still gated on the
 * measurement id, because requirement 1 is "no console noise" before cutover.
 */
export function isDebugEnabled(): boolean {
  return isAnalyticsEnabled() && (process.env.NEXT_PUBLIC_GA_DEBUG ?? "").trim() === "1";
}

/**
 * Domains the gtag linker decorates outbound links for. Shopify hosts checkout
 * on the store's own origin, so without this the `checkoutUrl` click starts a
 * brand-new GA4 session and the Shopify-side `purchase` never joins the visit
 * that produced it. See docs/deployment.md § Analytics.
 */
export const CHECKOUT_LINKER_DOMAINS = ["prosporter.myshopify.com", "shop.app"] as const;
