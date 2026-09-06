import type { MetadataRoute } from "next";

import { getCollectionSitemapEntries, getProductSitemapEntries } from "@/lib/catalog-source";
import { getArticleSitemapEntries, getContentPageSitemapEntries } from "@/lib/content-source";
import { absoluteUrl, isIndexableDeployment, type SitemapEntry } from "@/lib/site";

/**
 * `/sitemap.xml` (Next.js metadata route).
 *
 * Covers every indexable route: home, the shop listings (`/shop` plus each
 * published collection), every product, every Shopify page under the `(content)`
 * group, `/blog` and every article. `lastModified` is Shopify's `updatedAt`
 * (`publishedAt` for articles) when the source has one.
 *
 * Deliberately excluded:
 * - `/search` — `noindex, follow` in the route's own metadata; infinite query
 *   permutations are thin/duplicate content.
 * - the 48 retired paths in `docs/redirects/gone.json` and every legacy redirect
 *   source — `src/proxy.ts` answers those with 410/308, not 200.
 * - `-2` duplicate handles from the WooCommerce export, and the `frontpage`
 *   collection, which is the home rail rather than a page.
 * - API routes, which `robots.ts` also disallows.
 *
 * ~200 URLs today (154 products, 10 collections, ~22 pages, 15 articles), far
 * below the 50,000-URL / 50 MB limit, so this stays a single file and does not
 * need `generateSitemaps`. Revisit if the catalog grows an order of magnitude.
 *
 * A single Storefront failure degrades to the static routes rather than a 500:
 * every source helper logs and returns an empty list. In mock mode
 * (`SHOPIFY_OPTIONAL=1`, CI) only the static routes are emitted, because there
 * is no real catalog to advertise.
 */

/** Matches the catalog cache window in `src/lib/shopify/tags.ts` (1 h). */
export const revalidate = 3600;

type Change = NonNullable<MetadataRoute.Sitemap[number]["changeFrequency"]>;

/** Routes that exist regardless of the catalog. Paths only; absolutised below. */
const STATIC_PATHS: { path: string; changeFrequency: Change; priority: number }[] = [
  { path: "/", changeFrequency: "daily", priority: 1 },
  { path: "/shop", changeFrequency: "daily", priority: 0.9 },
  { path: "/shop/new-arrivals", changeFrequency: "daily", priority: 0.7 },
  { path: "/shop/sale", changeFrequency: "daily", priority: 0.7 },
  { path: "/blog", changeFrequency: "weekly", priority: 0.6 },
];

function toUrl(
  entry: SitemapEntry,
  changeFrequency: Change,
  priority: number,
): MetadataRoute.Sitemap[number] {
  const lastModified = entry.lastModified ? new Date(entry.lastModified) : null;
  return {
    url: absoluteUrl(entry.path),
    ...(lastModified && !Number.isNaN(lastModified.getTime()) ? { lastModified } : {}),
    changeFrequency,
    priority,
  };
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  // A preview deployment is disallow-all in robots.txt; emitting a sitemap of
  // duplicate URLs there would only invite them into the index anyway.
  if (!isIndexableDeployment()) {
    return [{ url: absoluteUrl("/"), changeFrequency: "daily", priority: 1 }];
  }

  const [products, collections, pages, articles] = await Promise.all([
    getProductSitemapEntries(),
    getCollectionSitemapEntries(),
    getContentPageSitemapEntries(),
    getArticleSitemapEntries(),
  ]);

  const urls: MetadataRoute.Sitemap = [
    ...STATIC_PATHS.map((s) =>
      toUrl({ path: s.path, lastModified: null }, s.changeFrequency, s.priority),
    ),
    ...collections.map((entry) => toUrl(entry, "daily", 0.8)),
    ...products.map((entry) => toUrl(entry, "weekly", 0.7)),
    ...articles.map((entry) => toUrl(entry, "monthly", 0.5)),
    ...pages.map((entry) => toUrl(entry, "monthly", 0.4)),
  ];

  // A collection whose handle collides with a static listing path (`sale`,
  // `new-arrivals`) would otherwise be listed twice; first entry wins.
  const seen = new Set<string>();
  return urls.filter((entry) => {
    if (seen.has(entry.url)) return false;
    seen.add(entry.url);
    return true;
  });
}
