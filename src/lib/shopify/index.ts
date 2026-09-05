import "server-only";

/**
 * Typed Storefront operations. This is the only module pages and server
 * actions should import for Shopify data. It owns pagination, cache tags and
 * the metafield identifier list so callers stay one line each.
 */
import { shopifyFetch } from "./client";
import { PRODUCT_METAFIELD_IDENTIFIERS } from "./fragments";
import * as Q from "./queries";
import { CACHE_TAGS, CATALOG_REVALIDATE_SECONDS } from "./tags";
import type { Cart, Collection, Connection, PageInfo, Product, ProductCard, UserError } from "./types";

export { ShopifyError, isShopifyError } from "./client";
export { isShopifyConfigured } from "./config";
export { CACHE_TAGS } from "./tags";
export * from "./types";

/** Storefront API hard limit on `first`. */
const PAGE_SIZE = 250;

// ------------------------------------------------------------------ products

export async function getProduct(handle: string): Promise<Product | null> {
  const data = await shopifyFetch<{ product: Product | null }>({
    query: Q.GET_PRODUCT_BY_HANDLE,
    variables: { handle, metafieldIdentifiers: PRODUCT_METAFIELD_IDENTIFIERS },
    tags: [CACHE_TAGS.products, CACHE_TAGS.product(handle)],
    revalidate: CATALOG_REVALIDATE_SECONDS,
  });
  return data.product;
}

export type ProductSortKey = "TITLE" | "PRICE" | "BEST_SELLING" | "CREATED_AT" | "UPDATED_AT" | "RELEVANCE";
export type ProductsPage = { products: ProductCard[]; pageInfo: PageInfo };

export async function getProductsPage(
  opts: { first?: number; after?: string | null; query?: string; sortKey?: ProductSortKey; reverse?: boolean } = {},
): Promise<ProductsPage> {
  const data = await shopifyFetch<{ products: Connection<ProductCard> }>({
    query: Q.GET_PRODUCTS,
    variables: {
      first: Math.min(opts.first ?? PAGE_SIZE, PAGE_SIZE),
      after: opts.after ?? null,
      query: opts.query ?? null,
      sortKey: opts.sortKey ?? null,
      reverse: opts.reverse ?? null,
    },
    tags: [CACHE_TAGS.products],
    revalidate: CATALOG_REVALIDATE_SECONDS,
  });
  return { products: data.products.edges.map((e) => e.node), pageInfo: data.products.pageInfo };
}

/** Walk every page. Use for sitemaps, static params and storefront-side filtering. */
export async function getAllProducts(query?: string): Promise<ProductCard[]> {
  const all: ProductCard[] = [];
  let after: string | null = null;
  do {
    const page: ProductsPage = await getProductsPage({ first: PAGE_SIZE, after, query });
    all.push(...page.products);
    after = page.pageInfo.hasNextPage ? page.pageInfo.endCursor : null;
  } while (after);
  return all;
}

export async function getAllProductHandles(): Promise<{ handle: string; updatedAt: string }[]> {
  type Node = { handle: string; updatedAt: string };
  const all: Node[] = [];
  let after: string | null = null;
  do {
    const data: { products: Connection<Node> } = await shopifyFetch({
      query: Q.GET_PRODUCT_HANDLES,
      variables: { first: PAGE_SIZE, after },
      tags: [CACHE_TAGS.products],
      revalidate: CATALOG_REVALIDATE_SECONDS,
    });
    all.push(...data.products.edges.map((e) => e.node));
    after = data.products.pageInfo.hasNextPage ? data.products.pageInfo.endCursor : null;
  } while (after);
  return all;
}

// --------------------------------------------------------------- collections

export async function getAllCollections(): Promise<Collection[]> {
  const all: Collection[] = [];
  let after: string | null = null;
  do {
    const data: { collections: Connection<Collection> } = await shopifyFetch({
      query: Q.GET_COLLECTIONS,
      variables: { first: PAGE_SIZE, after },
      tags: [CACHE_TAGS.collections],
      revalidate: CATALOG_REVALIDATE_SECONDS,
    });
    all.push(...data.collections.edges.map((e) => e.node));
    after = data.collections.pageInfo.hasNextPage ? data.collections.pageInfo.endCursor : null;
  } while (after);
  return all;
}

export type CollectionSortKey = "TITLE" | "PRICE" | "BEST_SELLING" | "CREATED" | "MANUAL" | "COLLECTION_DEFAULT" | "RELEVANCE";
export type CollectionFilterValue = { id: string; label: string; count: number; input: string };
export type CollectionFilter = {
  id: string;
  label: string;
  type: "LIST" | "PRICE_RANGE" | "BOOLEAN";
  values: CollectionFilterValue[];
};
export type CollectionPage = {
  collection: Collection;
  products: ProductCard[];
  pageInfo: PageInfo;
  filters: CollectionFilter[];
};

export async function getCollectionPage(
  handle: string,
  opts: {
    first?: number;
    after?: string | null;
    sortKey?: CollectionSortKey;
    reverse?: boolean;
    filters?: Record<string, unknown>[];
  } = {},
): Promise<CollectionPage | null> {
  type Resp = {
    collection: (Collection & { products: Connection<ProductCard> & { filters: CollectionFilter[] } }) | null;
  };
  const data = await shopifyFetch<Resp>({
    query: Q.GET_COLLECTION_BY_HANDLE,
    variables: {
      handle,
      first: Math.min(opts.first ?? PAGE_SIZE, PAGE_SIZE),
      after: opts.after ?? null,
      sortKey: opts.sortKey ?? null,
      reverse: opts.reverse ?? null,
      filters: opts.filters ?? null,
    },
    tags: [CACHE_TAGS.collections, CACHE_TAGS.collection(handle), CACHE_TAGS.products],
    revalidate: CATALOG_REVALIDATE_SECONDS,
  });
  if (!data.collection) return null;
  const { products, ...collection } = data.collection;
  return {
    collection,
    products: products.edges.map((e) => e.node),
    pageInfo: products.pageInfo,
    filters: products.filters,
  };
}

// --------------------------------------------------------------------- cart

export class CartUserError extends Error {
  readonly name = "CartUserError";
  constructor(readonly errors: UserError[]) {
    super(errors.map((e) => e.message).join("; "));
  }
}

type CartPayload = { cart: Cart | null; userErrors: UserError[] };

function unwrapCart(payload: CartPayload | undefined, op: string): Cart {
  if (!payload) throw new Error(`Missing ${op} payload`);
  if (payload.userErrors?.length) throw new CartUserError(payload.userErrors);
  if (!payload.cart) throw new Error(`${op} returned no cart`);
  return payload.cart;
}

export type CartLineInput = {
  merchandiseId: string;
  quantity: number;
  attributes?: { key: string; value: string }[];
};
export type BuyerIdentityInput = { email?: string; countryCode?: string };

/** Carts are buyer-specific: never cached. */
export async function getCart(id: string): Promise<Cart | null> {
  const data = await shopifyFetch<{ cart: Cart | null }>({ query: Q.GET_CART, variables: { id }, cache: "no-store" });
  return data.cart;
}

export async function createCart(
  input: { lines?: CartLineInput[]; buyerIdentity?: BuyerIdentityInput; discountCodes?: string[] } = {},
): Promise<Cart> {
  const data = await shopifyFetch<{ cartCreate: CartPayload }>({
    query: Q.CART_CREATE,
    variables: { input: { ...input, buyerIdentity: { countryCode: "AU", ...input.buyerIdentity } } },
  });
  return unwrapCart(data.cartCreate, "cartCreate");
}

export async function addCartLines(cartId: string, lines: CartLineInput[]): Promise<Cart> {
  const data = await shopifyFetch<{ cartLinesAdd: CartPayload }>({
    query: Q.CART_LINES_ADD,
    variables: { cartId, lines },
  });
  return unwrapCart(data.cartLinesAdd, "cartLinesAdd");
}

export async function updateCartLines(cartId: string, lines: { id: string; quantity: number }[]): Promise<Cart> {
  const data = await shopifyFetch<{ cartLinesUpdate: CartPayload }>({
    query: Q.CART_LINES_UPDATE,
    variables: { cartId, lines },
  });
  return unwrapCart(data.cartLinesUpdate, "cartLinesUpdate");
}

export async function removeCartLines(cartId: string, lineIds: string[]): Promise<Cart> {
  const data = await shopifyFetch<{ cartLinesRemove: CartPayload }>({
    query: Q.CART_LINES_REMOVE,
    variables: { cartId, lineIds },
  });
  return unwrapCart(data.cartLinesRemove, "cartLinesRemove");
}

export async function updateCartBuyerIdentity(cartId: string, buyerIdentity: BuyerIdentityInput): Promise<Cart> {
  const data = await shopifyFetch<{ cartBuyerIdentityUpdate: CartPayload }>({
    query: Q.CART_BUYER_IDENTITY_UPDATE,
    variables: { cartId, buyerIdentity },
  });
  return unwrapCart(data.cartBuyerIdentityUpdate, "cartBuyerIdentityUpdate");
}

export async function updateCartDiscountCodes(cartId: string, discountCodes: string[]): Promise<Cart> {
  const data = await shopifyFetch<{ cartDiscountCodesUpdate: CartPayload }>({
    query: Q.CART_DISCOUNT_CODES_UPDATE,
    variables: { cartId, discountCodes },
  });
  return unwrapCart(data.cartDiscountCodesUpdate, "cartDiscountCodesUpdate");
}
