"use client";

import Script from "next/script";
import { Suspense, useEffect, useRef } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import {
  CHECKOUT_LINKER_DOMAINS,
  isDebugEnabled,
  measurementId,
  nextPageView,
  pageViewPath,
  trackPageView,
} from "@/lib/analytics";

/**
 * Google Analytics 4 (CLNT-179).
 *
 * Loaded with `next/script` rather than `@next/third-parties/google`: that
 * package is not a dependency of this repo and is not bundled with Next, and
 * adding an npm dependency for one 20-line snippet was not worth it. The
 * behaviour is the same — `afterInteractive`, so gtag.js never blocks
 * hydration.
 *
 * Nothing renders while `NEXT_PUBLIC_GA_MEASUREMENT_ID` is unset, which is the
 * default until cutover: the client's GA4 property is still wired to the live
 * WooCommerce store and must not receive traffic from this storefront before
 * then. No script tag, no request to googletagmanager.com, no console output.
 *
 * Two deliberate configuration choices:
 *
 *  - `send_page_view: false`. gtag would otherwise send a `page_view` on script
 *    load and nothing on an App Router client navigation, so SPA routes would
 *    be invisible. We send every `page_view` ourselves from <PageViews />,
 *    exactly once per pathname+search (see src/lib/analytics/page-view.ts).
 *  - a `linker` covering the Shopify checkout domains. Checkout is hosted on
 *    prosporter.myshopify.com, a different origin, so the GA client id has to
 *    ride across on the outbound link or the Shopify-side `purchase` lands in a
 *    brand-new session. See docs/deployment.md § Analytics.
 *
 * Consent Mode v2 defaults are set *before* `config`: advertising storage
 * denied, analytics storage granted. No consent banner is in scope; a banner
 * added later flips these with `gtag('consent', 'update', ...)`.
 */

/** Fires one `page_view` per distinct location, on hard loads and SPA navigations alike. */
function PageViews() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const search = searchParams.toString();
  // A ref, not state: this must not re-render anything, and
  // react-hooks/set-state-in-effect forbids the setState version anyway.
  const lastSent = useRef<string | null>(null);

  useEffect(() => {
    const decision = nextPageView(lastSent.current, pageViewPath(pathname, search));
    lastSent.current = decision.url;
    if (decision.send) trackPageView(decision.url);
  }, [pathname, search]);

  return null;
}

export function Analytics() {
  const id = measurementId();
  if (!id) return null;

  const config = {
    // We own page_view; see PageViews above.
    send_page_view: false,
    // GA4 always truncates the IP; these keep Google Signals and ads
    // personalisation off, which is the modern equivalent of anonymize_ip and
    // is what keeps this an analytics-only, non-advertising tag.
    anonymize_ip: true,
    allow_google_signals: false,
    allow_ad_personalization_signals: false,
    // Cross-domain measurement into Shopify-hosted checkout.
    linker: { domains: [...CHECKOUT_LINKER_DOMAINS], accept_incoming: true },
    ...(isDebugEnabled() ? { debug_mode: true } : {}),
  };

  return (
    <>
      {/* A plain inline script, not <Script>, and deliberately so: it must
          run while the HTML is parsed, before hydration and therefore before
          <PageViews />'s effect. next/script would inject it after hydration,
          which races the first page_view into dataLayer ahead of the consent
          defaults and the config that give it a destination. It costs no
          request and defines the standard gtag queue stub. */}
      <script
        id="ga4-init"
        dangerouslySetInnerHTML={{
          __html: `window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}
gtag('js',new Date());
gtag('consent','default',{ad_storage:'denied',ad_user_data:'denied',ad_personalization:'denied',analytics_storage:'granted'});
gtag('config',${JSON.stringify(id)},${JSON.stringify(config)});`,
        }}
      />
      {/* gtag.js itself is afterInteractive: it drains the queue above whenever
          it arrives, so it never blocks hydration. */}
      <Script
        id="ga4-gtag"
        strategy="afterInteractive"
        src={`https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(id)}`}
      />
      {/* useSearchParams() opts its subtree out of static rendering; the
          Suspense boundary keeps that contained to this null-rendering leaf so
          the rest of every page still prerenders. */}
      <Suspense fallback={null}>
        <PageViews />
      </Suspense>
    </>
  );
}
