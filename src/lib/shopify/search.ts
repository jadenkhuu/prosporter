import "server-only";

/**
 * Storefront product search.
 *
 * Uses the Storefront `search` query rather than `products(query:)`. Verified
 * against the live 2026-07 schema: `search` takes `types: [PRODUCT]`,
 * `productFilters`, `unavailableProducts` and `prefix`, returns `totalCount`
 * (which `products` does not) and ranks by Shopify's own relevance engine —
 * synonyms, typo tolerance and prefix matching on the last term. `products`
 * only exposes a raw index query string with no relevance ranking and no
 * result count, so it would mean re-implementing ranking on the storefront.
 *
 * `SearchSortKeys` on 2026-07 is `RELEVANCE | PRICE` only, so "newest" is not
 * a server-side option here; price sorts use `sortKey: PRICE` + `reverse`.
 *
 * Caching: `force-cache` with `CACHE_TAGS.products` and a 300s revalidate,
 * not `no-store`. Search results are public, non-personalised catalog data —
 * the same query string yields the same page for every shopper — so the head
 * of the query distribution ("jersey", "shorts", a club name) is served from
 * the Next data cache instead of hitting the Storefront API on every
 * keystroke-driven navigation. The window is short (vs. the one hour used for
 * collection reads) because relevance and availability shift faster than a
 * collection does, and the products cache tag means a product webhook still
 * invalidates search results immediately.
 */
import { shopifyFetch } from "./client";
import { PRODUCT_CARD_FRAGMENTS } from "./fragments";
import { CACHE_TAGS } from "./tags";
import type { PageInfo, ProductCard } from "./types";

/** Seconds before a cached search response is revalidated in the background. */
export const SEARCH_REVALIDATE_SECONDS = 300;

/** Storefront cap on `first`; searches page well below it. */
const MAX_FIRST = 250;
const DEFAULT_FIRST = 48;

export type SearchSortKey = "RELEVANCE" | "PRICE";

export type SearchProductsOptions = {
  first?: number;
  after?: string | null;
  sort?: SearchSortKey;
  /** Price sorts only: true is high-to-low. Ignored for RELEVANCE. */
  reverse?: boolean;
};

export type ProductSearchResults = {
  products: ProductCard[];
  pageInfo: PageInfo;
  /** Total matches across all pages, from the Storefront `totalCount` field. */
  totalCount: number;
};

const SEARCH_PRODUCTS = /* GraphQL */ `
  ${PRODUCT_CARD_FRAGMENTS}
  query SearchProducts(
    $query: String!
    $first: Int!
    $after: String
    $sortKey: SearchSortKeys
    $reverse: Boolean
  ) {
    search(
      query: $query
      first: $first
      after: $after
      sortKey: $sortKey
      reverse: $reverse
      types: [PRODUCT]
      prefix: LAST
      unavailableProducts: LAST
    ) {
      totalCount
      edges {
        cursor
        node {
          ... on Product {
            ...ProductCard
          }
        }
      }
      pageInfo {
        hasNextPage
        hasPreviousPage
        startCursor
        endCursor
      }
    }
  }
`;

const EMPTY: ProductSearchResults = {
  products: [],
  pageInfo: { hasNextPage: false, hasPreviousPage: false, startCursor: null, endCursor: null },
  totalCount: 0,
};

/**
 * Search published products. A blank query returns no results without calling
 * Shopify (`query` is non-null on the schema and an empty string is a waste of
 * a request).
 *
 * `unavailableProducts: LAST` keeps sold-out gear discoverable but ranked
 * below what a shopper can actually buy; `prefix: LAST` matches partial final
 * words so "jers" finds jerseys.
 */
export async function searchProducts(
  query: string,
  opts: SearchProductsOptions = {},
): Promise<ProductSearchResults> {
  const q = query.trim();
  if (!q) return EMPTY;

  type Resp = {
    search: {
      totalCount: number;
      edges: { cursor: string; node: ProductCard }[];
      pageInfo: PageInfo;
    };
  };

  const data = await shopifyFetch<Resp>({
    query: SEARCH_PRODUCTS,
    variables: {
      query: q,
      first: Math.min(opts.first ?? DEFAULT_FIRST, MAX_FIRST),
      after: opts.after ?? null,
      sortKey: opts.sort ?? "RELEVANCE",
      reverse: opts.sort === "PRICE" ? (opts.reverse ?? false) : null,
    },
    tags: [CACHE_TAGS.products],
    revalidate: SEARCH_REVALIDATE_SECONDS,
  });

  return {
    // The union can only yield Products because `types: [PRODUCT]` is fixed,
    // but guard anyway so a schema change degrades instead of throwing.
    products: data.search.edges.map((e) => e.node).filter((n) => Boolean(n?.handle)),
    pageInfo: data.search.pageInfo,
    totalCount: data.search.totalCount,
  };
}
