/**
 * schema.org JSON-LD builders (CLNT-176, workstream 4).
 *
 * Pure functions: they take plain inputs, return plain objects and read nothing
 * but `src/lib/site.ts`. That keeps them unit-testable with `node --test` (see
 * `src/lib/seo/__tests__/json-ld.test.mjs`) and keeps the route files thin —
 * a page builds an object and renders it through `<JsonLd>`
 * (`src/components/seo/JsonLd.tsx`).
 *
 * Rules that apply to everything here:
 *
 * - **Never emit personal data.** Article bylines carry the author's display
 *   name only, exactly as the page already renders it; `authorV2.email` is not
 *   fetched by the data layer and must never be added.
 * - **Only describe what the page shows.** Structured data that contradicts the
 *   rendered page is a manual-action risk, so prices, availability and
 *   breadcrumbs come from the same view model the component tree renders.
 * - **Serialise with `serializeJsonLd`**, never bare `JSON.stringify`: the
 *   escaping below is what stops a `</script>` inside a product description
 *   from closing the tag early.
 */
import { SITE_LOGO_PATH, SITE_NAME, absoluteUrl } from "../site.ts";

// ------------------------------------------------------------------- types

export type JsonLdPrimitive = string | number | boolean | null;
export type JsonLdValue = JsonLdPrimitive | JsonLdObject | JsonLdValue[];
export interface JsonLdObject {
  [key: string]: JsonLdValue | undefined;
}
/** A top-level node, ready to be rendered in its own `<script>` tag. */
export type JsonLdNode = JsonLdObject & { "@context": "https://schema.org"; "@type": string };

const CONTEXT = "https://schema.org" as const;

// ------------------------------------------------------------- serialisation

/**
 * JSON for a `<script type="application/ld+json">` body.
 *
 * `<` and `>` are escaped so a literal `</script>` in any string cannot close
 * the block (the XSS classic); `&` is escaped for HTML-entity safety inside the
 * element; U+2028/U+2029 are escaped because they are valid JSON but illegal in
 * a JavaScript string literal. All four are `\uXXXX` escapes, so the parsed
 * value is byte-for-byte the input.
 */
export function serializeJsonLd(data: JsonLdObject | JsonLdObject[]): string {
  return JSON.stringify(data)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

/** Drop empty/undefined members so no key is emitted with a meaningless value. */
function compact(object: JsonLdObject): JsonLdObject {
  const out: JsonLdObject = {};
  for (const [key, value] of Object.entries(object)) {
    if (value === undefined || value === null) continue;
    if (typeof value === "string" && value.trim() === "") continue;
    if (Array.isArray(value) && value.length === 0) continue;
    out[key] = value;
  }
  return out;
}

/** Collapse markup-free text to a single line and cap it, as Google does anyway. */
function text(value: string | null | undefined, max = 5000): string | undefined {
  const trimmed = (value ?? "").replace(/\s+/g, " ").trim();
  if (!trimmed) return undefined;
  return trimmed.length > max ? `${trimmed.slice(0, max - 1).trimEnd()}…` : trimmed;
}

/** schema.org wants prices as plain decimal strings, no currency symbol. */
function price(amount: number): string {
  return Number.isFinite(amount) ? amount.toFixed(2) : "0.00";
}

function availability(inStock: boolean): string {
  return inStock ? "https://schema.org/InStock" : "https://schema.org/OutOfStock";
}

// ------------------------------------------------------ organization / site

export function buildOrganizationJsonLd(): JsonLdNode {
  return {
    "@context": CONTEXT,
    "@type": "Organization",
    "@id": `${absoluteUrl("/")}#organization`,
    name: SITE_NAME,
    url: absoluteUrl("/"),
    logo: absoluteUrl(SITE_LOGO_PATH),
  };
}

/**
 * WebSite with the sitelinks SearchAction pointing at the storefront's own
 * search route. `/search` itself is `noindex, follow` (see the route), which is
 * the documented combination: the target of a SearchAction does not need to be
 * indexable, only reachable.
 */
export function buildWebSiteJsonLd(): JsonLdNode {
  return {
    "@context": CONTEXT,
    "@type": "WebSite",
    "@id": `${absoluteUrl("/")}#website`,
    name: SITE_NAME,
    url: absoluteUrl("/"),
    publisher: { "@id": `${absoluteUrl("/")}#organization` },
    potentialAction: {
      "@type": "SearchAction",
      target: {
        "@type": "EntryPoint",
        urlTemplate: `${absoluteUrl("/search")}?q={search_term_string}`,
      },
      "query-input": "required name=search_term_string",
    },
  };
}

// ------------------------------------------------------------- breadcrumbs

export type BreadcrumbItem = {
  name: string;
  /** App path (`/shop/beach`); absolutised here. Omit for the current page. */
  path?: string;
};

export function buildBreadcrumbJsonLd(items: BreadcrumbItem[]): JsonLdNode {
  return {
    "@context": CONTEXT,
    "@type": "BreadcrumbList",
    itemListElement: items.map((item, index) =>
      compact({
        "@type": "ListItem",
        position: index + 1,
        name: text(item.name, 200),
        item: item.path ? absoluteUrl(item.path) : undefined,
      }),
    ),
  };
}

// ----------------------------------------------------------------- product

export type ProductOfferInput = {
  sku?: string | null;
  price: number;
  currency: string;
  available: boolean;
};

export type ProductJsonLdInput = {
  /** App path of the product page, e.g. `/product/nago`. */
  path: string;
  name: string;
  description?: string | null;
  /** Absolute image URLs (Shopify CDN) or app paths. */
  images?: string[];
  /** `Product.vendor`, or a `prosporter.brand`-style metafield when one exists. */
  brand?: string | null;
  /** Product-level SKU; only meaningful for a single-variant product. */
  sku?: string | null;
  currency: string;
  /** One entry per buyable variant. A single entry emits a plain `Offer`. */
  offers: ProductOfferInput[];
  /** Fallback range when the source has no per-variant data (mock catalogue). */
  priceRange?: { min: number; max: number; available: boolean };
};

/**
 * `Product` with either a single `Offer` (one variant) or an `AggregateOffer`
 * (several). AggregateOffer is the honest shape for a size/colour matrix: the
 * page shows a price range, and claiming one exact price for the product would
 * disagree with the rendered page.
 */
export function buildProductJsonLd(input: ProductJsonLdInput): JsonLdNode {
  const url = absoluteUrl(input.path);
  const images = (input.images ?? [])
    .filter((src) => typeof src === "string" && src.trim() !== "")
    .map((src) => (/^https?:\/\//i.test(src) ? src : absoluteUrl(src)));

  return compact({
    "@context": CONTEXT,
    "@type": "Product",
    name: text(input.name, 200),
    url,
    description: text(input.description, 1000),
    image: images,
    sku: text(input.sku, 100),
    brand: input.brand ? { "@type": "Brand", name: text(input.brand, 100) ?? "" } : undefined,
    offers: buildOffers(input, url),
  }) as JsonLdNode;
}

function buildOffers(input: ProductJsonLdInput, url: string): JsonLdObject {
  const offers = input.offers.filter((offer) => Number.isFinite(offer.price));

  if (offers.length === 1) {
    const only = offers[0];
    return compact({
      "@type": "Offer",
      url,
      price: price(only.price),
      priceCurrency: only.currency || input.currency,
      availability: availability(only.available),
      itemCondition: "https://schema.org/NewCondition",
      sku: text(only.sku, 100),
    });
  }

  const prices = offers.map((offer) => offer.price);
  const min = prices.length ? Math.min(...prices) : (input.priceRange?.min ?? 0);
  const max = prices.length ? Math.max(...prices) : (input.priceRange?.max ?? min);
  const available = offers.length
    ? offers.some((offer) => offer.available)
    : (input.priceRange?.available ?? false);

  return compact({
    "@type": "AggregateOffer",
    url,
    lowPrice: price(min),
    highPrice: price(max),
    priceCurrency: input.currency,
    offerCount: offers.length || undefined,
    availability: availability(available),
  });
}

// ----------------------------------------------------------------- article

export type ArticleJsonLdInput = {
  /** App path, e.g. `/blog/beach-season-kit`. */
  path: string;
  headline: string;
  description?: string | null;
  /** Absolute image URL, when the article has one. */
  image?: string | null;
  datePublished?: string | null;
  dateModified?: string | null;
  /** Display name only. Never an email address. */
  authorName?: string | null;
};

export function buildArticleJsonLd(input: ArticleJsonLdInput): JsonLdNode {
  const url = absoluteUrl(input.path);
  return compact({
    "@context": CONTEXT,
    "@type": "Article",
    mainEntityOfPage: { "@type": "WebPage", "@id": url },
    url,
    headline: text(input.headline, 110),
    description: text(input.description, 1000),
    image: input.image ? [input.image] : undefined,
    datePublished: text(input.datePublished, 40),
    dateModified: text(input.dateModified ?? input.datePublished, 40),
    author: input.authorName
      ? { "@type": "Person", name: text(input.authorName, 100) ?? "" }
      : { "@id": `${absoluteUrl("/")}#organization` },
    publisher: { "@id": `${absoluteUrl("/")}#organization` },
  }) as JsonLdNode;
}
