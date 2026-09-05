import "server-only";

/**
 * Catalog source selection.
 *
 * Pages import this module and nothing else for catalog data. When the Shopify
 * environment variables are present every read goes to the Storefront API
 * through `src/lib/shopify` (force-cache + cache tags). When they are not —
 * CI builds with `SHOPIFY_OPTIONAL=1`, or a fresh clone with no `.env.local` —
 * the same view model is produced from the mock catalog in `catalog.ts`, so
 * the site still builds and renders.
 *
 * Nothing here calls `shopifyFetch` directly; it goes through `shopify/index`.
 */
import {
  catalog as mockCatalog,
  taxonomy,
  getCategoryLabel,
  getPopularProducts,
  type Product as MockProduct,
} from "./catalog";
import { log, errorFields } from "./log";
import {
  buildFacets,
  isColourOption,
  isDefaultOption,
  isSizeOption,
  type CatalogImage,
  type CatalogOption,
  type CatalogProduct,
  type CatalogProductDetail,
  type CatalogVariant,
  type CategoryTile,
  type HomeCatalog,
  type ListingScope,
} from "./catalog-view";
import {
  getAllCollections,
  getAllProductHandles,
  getAllProducts as getAllShopifyProducts,
  getCollectionPage,
  getProduct,
  getProductsPage,
  isShopifyConfigured,
  nodes,
  type Image as ShopifyImage,
  type Metafield,
  type Product as ShopifyProduct,
  type ProductCard as ShopifyProductCard,
} from "./shopify";
import { searchProducts } from "./shopify/search";

export type CatalogSource = "shopify" | "mock";

export function catalogSource(): CatalogSource {
  return isShopifyConfigured() ? "shopify" : "mock";
}

const FALLBACK_IMAGE: CatalogImage = {
  url: "/products/ace-unisex.png",
  alt: "ProSporter",
  width: null,
  height: null,
};

// ------------------------------------------------------------ shopify mapping

/**
 * Migration tags encode the facets the Storefront API cannot express as
 * structured fields: `gender:unisex`, `type:accessories`, `surface:beach`,
 * `club:<slug>`. Unprefixed tags are ignored.
 */
function tagValues(tags: string[], prefix: string): string[] {
  const p = `${prefix}:`;
  return tags.filter((t) => t.startsWith(p)).map((t) => t.slice(p.length)).filter(Boolean);
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/&/g, "and")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function toImage(image: ShopifyImage | null | undefined, alt: string): CatalogImage | null {
  if (!image?.url) return null;
  return { url: image.url, alt: image.altText ?? alt, width: image.width, height: image.height };
}

function money(value: string | null | undefined): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function optionValues(card: ShopifyProductCard, match: (name: string) => boolean): string[] {
  return card.options
    .filter((o) => match(o.name))
    .flatMap((o) => o.optionValues.map((v) => v.name));
}

function fromShopifyCard(card: ShopifyProductCard): CatalogProduct {
  const price = money(card.priceRange.minVariantPrice.amount);
  const maxPrice = money(card.priceRange.maxVariantPrice.amount);
  const compareAt = money(card.compareAtPriceRange.maxVariantPrice.amount);
  const categoryId = tagValues(card.tags, "type")[0] ?? (card.productType ? slugify(card.productType) : "shop");
  const taxonomyLabel = getCategoryLabel(categoryId);

  return {
    handle: card.handle,
    title: card.title,
    image: toImage(card.featuredImage, card.title),
    price,
    maxPrice,
    compareAtPrice: compareAt > price ? compareAt : null,
    currency: card.priceRange.minVariantPrice.currencyCode,
    onSale: compareAt > price,
    inStock: card.availableForSale,
    categoryId,
    categoryLabel: taxonomyLabel !== categoryId ? taxonomyLabel : card.productType || categoryId,
    surface: tagValues(card.tags, "surface")[0] ?? null,
    clubs: tagValues(card.tags, "club"),
    gender: tagValues(card.tags, "gender"),
    colours: optionValues(card, isColourOption),
    sizes: optionValues(card, isSizeOption),
    variantId: card.quickAddVariants.edges.length === 1 ? card.quickAddVariants.edges[0].node.id : null,
    createdAt: Date.parse(card.createdAt) || 0,
  };
}

/** `prosporter.*` metafields keyed by metafield key; list types are unpacked. */
function metafieldDetails(metafields: Metafield[]): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const field of metafields) {
    if (!field?.value) continue;
    if (field.type.startsWith("list.")) {
      try {
        const parsed: unknown = JSON.parse(field.value);
        if (Array.isArray(parsed)) {
          out[field.key] = parsed.map((v) => String(v));
          continue;
        }
      } catch {
        // Fall through to the raw value.
      }
    }
    out[field.key] = [field.value];
  }
  return out;
}

function toOptions(product: ShopifyProduct): CatalogOption[] {
  return product.options
    .map((o) => {
      const swatches: Record<string, string> = {};
      for (const v of o.optionValues) {
        if (v.swatch?.color) swatches[v.name] = v.swatch.color;
      }
      return {
        name: o.name,
        values: o.optionValues.map((v) => v.name),
        ...(Object.keys(swatches).length ? { swatches } : {}),
      };
    })
    .filter((o) => o.values.length > 0 && !isDefaultOption(o));
}

function toVariants(product: ShopifyProduct): CatalogVariant[] {
  return nodes(product.variants).map((v) => ({
    id: v.id,
    title: v.title,
    available: v.availableForSale,
    price: money(v.price.amount),
    compareAtPrice: v.compareAtPrice ? money(v.compareAtPrice.amount) : null,
    currency: v.price.currencyCode,
    selectedOptions: v.selectedOptions.map((o) => ({ name: o.name, value: o.value })),
    image: toImage(v.image, product.title),
  }));
}

function fromShopifyProduct(product: ShopifyProduct): CatalogProductDetail {
  const card = fromShopifyCard(product);
  const details = metafieldDetails(product.metafields);
  const images = nodes(product.images)
    .map((i) => toImage(i, product.title))
    .filter((i): i is CatalogImage => i !== null);
  const collection = nodes(product.collections)[0];

  return {
    ...card,
    // Metafields are authoritative when the migration set them; tags are the fallback.
    gender: details.gender ?? card.gender,
    surface: details.surface?.[0] ?? card.surface,
    clubs: details.club ?? card.clubs,
    images: images.length ? images : card.image ? [card.image] : [],
    descriptionHtml: product.descriptionHtml ?? "",
    description: product.description ?? "",
    seo: product.seo ?? { title: null, description: null },
    options: toOptions(product),
    variants: toVariants(product),
    variantId: card.variantId,
    details,
    breadcrumb: collection
      ? { href: `/shop/${collection.handle}`, label: collection.title }
      : { href: `/shop/${card.categoryId}`, label: card.categoryLabel },
  };
}

// --------------------------------------------------------------- mock mapping

function fromMockProduct(p: MockProduct): CatalogProduct {
  return {
    handle: p.slug,
    title: p.name,
    image: { url: p.image_local, alt: p.name, width: null, height: null },
    price: p.price,
    maxPrice: p.price,
    compareAtPrice: null,
    currency: p.currency,
    onSale: p.on_sale,
    inStock: p.in_stock,
    categoryId: p.primary_category,
    categoryLabel: getCategoryLabel(p.primary_category),
    surface: p.surface,
    clubs: p.clubs,
    gender: p.gender,
    colours: p.colours,
    sizes: p.sizes,
    // The mock catalog has no Shopify variants; the cart falls back to its shim.
    variantId: null,
    // Woo post ids climb over time, so they order the mock catalog newest-first.
    createdAt: p.id,
  };
}

function fromMockDetail(p: MockProduct): CatalogProductDetail {
  const card = fromMockProduct(p);
  const options: CatalogOption[] = [];
  if (p.colours.length) options.push({ name: "Colour", values: p.colours });
  if (p.sizes.length) options.push({ name: "Size", values: p.sizes });

  return {
    ...card,
    images: card.image ? [card.image] : [],
    descriptionHtml: "",
    description: `${p.name} from the ProSporter range. Performance volleyball apparel built to move with you and hold up season after season.`,
    seo: { title: null, description: null },
    options,
    variants: [],
    details: {},
    breadcrumb: { href: `/shop/${p.primary_category}`, label: card.categoryLabel },
  };
}

// -------------------------------------------------------------------- reads

function scope(
  title: string,
  kind: ListingScope["kind"],
  products: CatalogProduct[],
  description?: string,
): ListingScope {
  return { title, kind, description, products, facets: buildFacets(products) };
}

const SURFACE_COPY: Record<string, { title: string; description: string }> = {
  beach: { title: "Beach", description: "Built for sand, sun and the beach game." },
  indoor: { title: "Indoor", description: "Court-ready gear for the indoor season." },
};

/** Slugs the storefront IA knows about, used to show an empty state instead of a 404. */
function knownSlug(slug: string): string | null {
  const nav = taxonomy.primary_nav.find((c) => c.id === slug);
  if (nav) return nav.label;
  const collection = taxonomy.collections.find((c) => c.id === slug || c.slug === slug);
  if (collection) return collection.label;
  return SURFACE_COPY[slug]?.title ?? null;
}

/**
 * Resolve a catch-all `/shop/...` path into a scoped, faceted product set.
 * Handles `[]`, `[collection]`, `[sale|new-arrivals]` and `[clubs, slug]`.
 * Returns null when the path is not a catalog path so the route can 404.
 */
export async function getListing(segments: string[]): Promise<ListingScope | null> {
  const products = catalogSource() === "shopify" ? null : mockCatalog.map(fromMockProduct);

  if (segments.length === 0) {
    const all = products ?? (await getAllShopifyProducts()).map(fromShopifyCard);
    return scope("Shop All", "all", all);
  }

  const [first, second] = segments;
  if (segments.length > 2 || (segments.length === 2 && first !== "clubs")) return null;

  if (first === "new-arrivals") {
    const recent = products
      ? [...products].sort((a, b) => b.createdAt - a.createdAt).slice(0, 24)
      : (await getProductsPage({ first: 24, sortKey: "CREATED_AT", reverse: true })).products.map(
          fromShopifyCard,
        );
    return scope("New Arrivals", "new", recent, "The latest drops across the range.");
  }

  if (first === "sale") {
    const all = products ?? (await getAllShopifyProducts()).map(fromShopifyCard);
    return scope("Sale", "sale", all.filter((p) => p.onSale), "Marked-down gear while stock lasts.");
  }

  const handle = first === "clubs" ? second : first;
  if (!handle) return null;

  if (products) {
    // Mock: the taxonomy, not Shopify, decides what a segment means.
    if (first === "clubs") {
      const club = taxonomy.collections.find((c) => c.id === handle && c.type === "club");
      if (!club) return null;
      return scope(
        club.label,
        "club",
        products.filter((p) => p.clubs.includes(handle)),
        `Official ${club.label} teamwear.`,
      );
    }
    const nav = taxonomy.primary_nav.find((c) => c.id === handle);
    if (nav) return scope(nav.label, "category", products.filter((p) => p.categoryId === handle));
    const surface = SURFACE_COPY[handle];
    if (surface) {
      return scope(
        surface.title,
        "surface",
        products.filter((p) => p.surface === handle),
        surface.description,
      );
    }
    return null;
  }

  const page = await getCollectionPage(handle);
  if (!page) {
    // The collection may not be published yet (migration in progress). Known IA
    // slugs render the empty state in Listing.tsx; anything else is a 404.
    const label = knownSlug(handle);
    if (!label) return null;
    log.info("catalog.collection_missing", { handle });
    return scope(label, first === "clubs" ? "club" : "collection", []);
  }

  return scope(
    page.collection.title,
    first === "clubs" ? "club" : "collection",
    page.products.map(fromShopifyCard),
    page.collection.description || undefined,
  );
}

export type SearchSort = "relevance" | "price-asc" | "price-desc";

export type SearchResults = {
  query: string;
  sort: SearchSort;
  products: CatalogProduct[];
  /** Total matches on the store; may exceed `products.length` on page one. */
  total: number;
};

/** Fields the mock fallback matches on, lower-cased once per product. */
function mockHaystack(p: MockProduct): string {
  return [p.name, p.primary_category, p.surface ?? "", ...p.clubs, ...p.colours, ...p.gender]
    .join(" ")
    .toLowerCase();
}

/**
 * Product search. Shopify mode delegates to the Storefront `search` query
 * (relevance-ranked, cached — see `shopify/search.ts`); mock mode does a plain
 * substring match over the mock catalog so `SHOPIFY_OPTIONAL=1` builds work.
 *
 * `shopify/search.ts` is imported directly rather than through `shopify/index`
 * because index.ts is frozen for this slice; it is the same server-only layer.
 */
export async function searchCatalog(
  rawQuery: string,
  sort: SearchSort = "relevance",
): Promise<SearchResults> {
  const query = rawQuery.trim();
  if (!query) return { query, sort, products: [], total: 0 };

  if (catalogSource() === "mock") {
    const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
    const matches = mockCatalog
      .filter((p) => {
        const hay = mockHaystack(p);
        return terms.every((t) => hay.includes(t));
      })
      .map(fromMockProduct);
    const products =
      sort === "relevance" ? matches : [...matches].sort((a, b) => a.price - b.price);
    if (sort === "price-desc") products.reverse();
    return { query, sort, products, total: products.length };
  }

  const results = await searchProducts(query, {
    sort: sort === "relevance" ? "RELEVANCE" : "PRICE",
    reverse: sort === "price-desc",
  });
  log.info("catalog.search", { query, count: results.products.length, total: results.totalCount });
  return { query, sort, products: results.products.map(fromShopifyCard), total: results.totalCount };
}

export type ProductPage = { product: CatalogProductDetail; related: CatalogProduct[] };

export async function getProductPage(handle: string): Promise<ProductPage | null> {
  if (catalogSource() === "mock") {
    const found = mockCatalog.find((p) => p.slug === handle);
    if (!found) return null;
    const product = fromMockDetail(found);
    const related = mockCatalog
      .filter((p) => p.slug !== handle && p.primary_category === found.primary_category)
      .slice(0, 4)
      .map(fromMockProduct);
    return { product, related };
  }

  const found = await getProduct(handle);
  if (!found) return null;
  const product = fromShopifyProduct(found);

  // Related: same collection first, falling back to the same product type.
  const collection = nodes(found.collections)[0];
  const cards = collection
    ? ((await getCollectionPage(collection.handle, { first: 8 }))?.products ?? [])
    : (await getProductsPage({ first: 8, query: found.productType ? `product_type:'${found.productType}'` : undefined }))
        .products;
  const related = cards.filter((c) => c.handle !== handle).slice(0, 4).map(fromShopifyCard);
  return { product, related };
}

export async function getHomeCatalog(): Promise<HomeCatalog> {
  const products =
    catalogSource() === "shopify"
      ? (await getAllShopifyProducts()).map(fromShopifyCard)
      : mockCatalog.map(fromMockProduct);

  const imageFor = (match: (p: CatalogProduct) => boolean): CatalogImage | null => {
    const hit = products.find((p) => match(p) && p.inStock) ?? products.find(match);
    return hit?.image ?? null;
  };

  const categories: CategoryTile[] = taxonomy.primary_nav.map((cat) => {
    const count = products.filter((p) => p.categoryId === cat.id).length;
    return {
      id: cat.id,
      label: cat.label,
      href: `/shop/${cat.id}`,
      // Mock counts come from the taxonomy; Shopify counts only what is published.
      count: catalogSource() === "shopify" ? (count || null) : cat.count,
      image: imageFor((p) => p.categoryId === cat.id) ?? FALLBACK_IMAGE,
    };
  });

  const surfaces: CategoryTile[] = (["indoor", "beach"] as const).map((id) => ({
    id,
    label: SURFACE_COPY[id].title,
    href: `/shop/${id}`,
    count: null,
    image: imageFor((p) => p.surface === id) ?? FALLBACK_IMAGE,
  }));

  const clubs: CategoryTile[] =
    catalogSource() === "shopify"
      ? []
      : taxonomy.collections
          .filter((c) => c.type === "club")
          .map((club) => ({
            id: club.id,
            label: club.label,
            href: `/shop/clubs/${club.id}`,
            count: club.count,
            image: imageFor((p) => p.clubs.includes(club.id)) ?? FALLBACK_IMAGE,
          }));

  const popular =
    catalogSource() === "shopify"
      ? [...products].sort((a, b) => Number(b.inStock) - Number(a.inStock)).slice(0, 8)
      : getPopularProducts().map(fromMockProduct);

  return {
    newArrivals: [...products].sort((a, b) => b.createdAt - a.createdAt).slice(0, 8),
    popular,
    categories,
    surfaces,
    clubs,
  };
}

// ------------------------------------------------------------ static params

/**
 * Handles to prerender. Empty when Shopify is unconfigured, and empty (not a
 * thrown error) when the Storefront API is unreachable, so a build never fails
 * on catalog availability — those routes render on demand instead.
 */
export async function getProductHandles(): Promise<string[]> {
  if (catalogSource() === "mock") return [];
  try {
    return (await getAllProductHandles()).map((p) => p.handle);
  } catch (err) {
    log.warn("catalog.static_params_failed", { route: "product", ...errorFields(err) });
    return [];
  }
}

/** Listing paths to prerender: `/shop` plus every published collection. */
export async function getListingParams(): Promise<string[][]> {
  if (catalogSource() === "mock") return [];
  try {
    const collections = await getAllCollections();
    return [[], ...collections.filter((c) => c.handle !== "frontpage").map((c) => [c.handle])];
  } catch (err) {
    log.warn("catalog.static_params_failed", { route: "shop", ...errorFields(err) });
    return [];
  }
}
