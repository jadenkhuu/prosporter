/**
 * Cache tags shared by the Storefront data layer and the (future) Shopify
 * webhook handlers. A webhook revalidates the coarse tag for its topic plus
 * the fine-grained tag for the affected handle.
 *
 * Safe to import from client code: contains no secrets.
 */
export const CACHE_TAGS = {
  products: "shopify:products",
  collections: "shopify:collections",
  inventory: "shopify:inventory",
  product: (handle: string) => `shopify:product:${handle}`,
  collection: (handle: string) => `shopify:collection:${handle}`,
  // Content (CLNT-171): Shopify pages and blog articles.
  pages: "shopify:pages",
  articles: "shopify:articles",
  page: (handle: string) => `shopify:page:${handle}`,
  article: (handle: string) => `shopify:article:${handle}`,
} as const;

/** Default revalidation window for catalog reads, in seconds. */
export const CATALOG_REVALIDATE_SECONDS = 60 * 60;
