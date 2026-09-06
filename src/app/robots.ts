import type { MetadataRoute } from "next";

import { absoluteUrl, isIndexableDeployment } from "@/lib/site";

/**
 * `/robots.txt` (Next.js metadata route).
 *
 * Production allows everything except the paths that are worthless or harmful
 * to crawl, and points at the sitemap. Anything that is not the production
 * deployment — every Vercel preview URL, and `next dev` — returns disallow-all,
 * so a per-commit copy of the storefront never competes with production in the
 * index. The signal is `VERCEL_ENV`, read once in `src/lib/site.ts`.
 *
 * robots.txt is a crawl directive, not an index directive: a disallowed URL can
 * still be indexed if something links to it. The two places where that matters
 * already carry a real `noindex`: `/search` (route metadata) and the 410 bodies
 * in `src/proxy.ts` (`X-Robots-Tag: noindex`). Nothing here duplicates those.
 */

/** Matches the catalog cache window in `src/lib/shopify/tags.ts` (1 h). */
export const revalidate = 3600;

/**
 * Crawling these produces nothing indexable:
 * - `/search` — infinite query permutations, already `noindex, follow`.
 * - `/api/` — the Shopify webhook receiver and any future handler.
 * - `/cart`, `/checkout`, `/account` — buyer-specific or Shopify-hosted; `/cart`
 *   is one of the 410 paths in `docs/redirects/gone.json` today.
 * - `/*?*sort=` and `/*?*filter` — facet permutations of a canonical listing.
 */
const DISALLOWED = [
  "/search",
  "/api/",
  "/cart",
  "/checkout",
  "/account",
  "/*?*sort=",
  "/*?*filter",
];

export default function robots(): MetadataRoute.Robots {
  if (!isIndexableDeployment()) {
    return { rules: [{ userAgent: "*", disallow: "/" }] };
  }

  return {
    rules: [{ userAgent: "*", allow: "/", disallow: DISALLOWED }],
    sitemap: absoluteUrl("/sitemap.xml"),
    host: absoluteUrl("/"),
  };
}
