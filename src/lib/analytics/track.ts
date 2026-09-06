/**
 * The one place that touches `gtag` (CLNT-179).
 *
 * Components never reach for `window.gtag`; they call `track(event, params)`.
 * That keeps the "is analytics on?" question in a single branch and makes the
 * pre-cutover default — `NEXT_PUBLIC_GA_MEASUREMENT_ID` unset — a genuine
 * no-op rather than a guard scattered across the UI.
 *
 * Never pass personal data (user_id, email, name, phone, address) in `params`.
 */
import { isAnalyticsEnabled, isDebugEnabled } from "./config";
import type { EcommerceParams } from "./items";

/** The four events the storefront owns; `purchase` comes from Shopify checkout. */
export type AnalyticsEvent = "page_view" | "view_item" | "add_to_cart" | "begin_checkout";

type GtagParams = Record<string, unknown>;

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

/**
 * Push through `window.gtag` when the inline snippet has defined it, and
 * straight onto `dataLayer` otherwise. The fallback pushes a real `arguments`
 * object, byte-for-byte what Google's own stub queues, so gtag.js drains it
 * identically whenever it arrives. It should never be needed — the snippet is a
 * parse-time inline script — but a queued event is cheaper than a lost one.
 */
function gtagPush(...args: unknown[]): void {
  if (typeof window === "undefined") return;
  if (window.gtag) {
    window.gtag(...args);
    return;
  }
  const dataLayer = (window.dataLayer = window.dataLayer ?? []);
  const queue = function () {
    // eslint-disable-next-line prefer-rest-params
    dataLayer.push(arguments);
  } as (...gtagArgs: unknown[]) => void;
  queue(...args);
}

export function track(event: AnalyticsEvent, params: EcommerceParams | GtagParams = {}): void {
  if (!isAnalyticsEnabled()) return;
  if (isDebugEnabled()) console.debug("[ga4]", event, params);
  gtagPush("event", event, params);
}

/**
 * `page_view` with an explicit location, because with `send_page_view: false`
 * gtag no longer derives one for us on SPA navigations.
 */
export function trackPageView(path: string): void {
  if (typeof window === "undefined") return;
  track("page_view", {
    page_path: path,
    page_location: `${window.location.origin}${path}`,
    page_title: document.title,
  });
}
