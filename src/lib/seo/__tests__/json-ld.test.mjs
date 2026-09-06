/**
 * Unit tests for the pure SEO helpers: the JSON-LD builders and the site-URL /
 * deployment-environment config they (and `app/robots.ts`, `app/sitemap.ts`)
 * read.
 *
 * Plain Node, zero dependencies: `npm test` (or `node --test
 * src/lib/seo/__tests__/*.test.mjs`). Requires Node >= 22.18, which strips the
 * TypeScript types from the imported modules without a build step.
 *
 * The route files themselves (`src/app/robots.ts`, `src/app/sitemap.ts`) are not
 * imported here: they resolve the `@/` path alias and Next's `MetadataRoute`
 * types, neither of which plain Node resolves. Everything in them that is worth
 * testing without a network lives in the modules below.
 */
import assert from "node:assert/strict";
import { after, beforeEach, test } from "node:test";

import {
  buildArticleJsonLd,
  buildBreadcrumbJsonLd,
  buildOrganizationJsonLd,
  buildProductJsonLd,
  buildWebSiteJsonLd,
  serializeJsonLd,
} from "../json-ld.ts";
import {
  absoluteUrl,
  deploymentEnvironment,
  isIndexableDeployment,
  siteUrl,
} from "../../site.ts";

const ENV_KEYS = [
  "NEXT_PUBLIC_SITE_URL",
  "SITE_URL",
  "VERCEL_PROJECT_PRODUCTION_URL",
  "VERCEL_URL",
  "VERCEL_ENV",
];
const ORIGINAL = Object.fromEntries(ENV_KEYS.map((key) => [key, process.env[key]]));

function resetEnv() {
  for (const key of ENV_KEYS) delete process.env[key];
}

beforeEach(() => {
  resetEnv();
  process.env.NEXT_PUBLIC_SITE_URL = "https://prosporter.com.au";
});

after(() => {
  resetEnv();
  for (const [key, value] of Object.entries(ORIGINAL)) {
    if (value !== undefined) process.env[key] = value;
  }
});

// ------------------------------------------------------------------ site url

test("siteUrl prefers NEXT_PUBLIC_SITE_URL and normalises to an origin", () => {
  process.env.NEXT_PUBLIC_SITE_URL = "https://prosporter.com.au/";
  assert.equal(siteUrl(), "https://prosporter.com.au");
});

test("siteUrl accepts a bare hostname and assumes https", () => {
  process.env.NEXT_PUBLIC_SITE_URL = "prosporter.com.au";
  assert.equal(siteUrl(), "https://prosporter.com.au");
});

test("siteUrl falls back through SITE_URL and the Vercel hostnames", () => {
  resetEnv();
  process.env.SITE_URL = "https://from-site-url.example";
  assert.equal(siteUrl(), "https://from-site-url.example");

  resetEnv();
  process.env.VERCEL_PROJECT_PRODUCTION_URL = "prosporter.vercel.app";
  process.env.VERCEL_URL = "prosporter-abc123.vercel.app";
  assert.equal(siteUrl(), "https://prosporter.vercel.app");

  resetEnv();
  process.env.VERCEL_URL = "prosporter-abc123.vercel.app";
  assert.equal(siteUrl(), "https://prosporter-abc123.vercel.app");
});

test("siteUrl ignores blank and malformed values and ends at localhost", () => {
  resetEnv();
  process.env.NEXT_PUBLIC_SITE_URL = "   ";
  process.env.SITE_URL = "not a url";
  assert.equal(siteUrl(), "http://localhost:3000");
});

test("absoluteUrl produces slash-free paths and leaves the root bare", () => {
  assert.equal(absoluteUrl("/"), "https://prosporter.com.au");
  assert.equal(absoluteUrl(), "https://prosporter.com.au");
  assert.equal(absoluteUrl("/shop/beach"), "https://prosporter.com.au/shop/beach");
  assert.equal(absoluteUrl("/shop/beach/"), "https://prosporter.com.au/shop/beach");
  assert.equal(absoluteUrl("blog/kit"), "https://prosporter.com.au/blog/kit");
});

// -------------------------------------------------------------- environment

test("only VERCEL_ENV=production is indexable", () => {
  process.env.VERCEL_ENV = "production";
  assert.equal(deploymentEnvironment(), "production");
  assert.equal(isIndexableDeployment(), true);

  for (const env of ["preview", "development"]) {
    process.env.VERCEL_ENV = env;
    assert.equal(deploymentEnvironment(), env);
    assert.equal(isIndexableDeployment(), false, `VERCEL_ENV=${env} must not be indexable`);
  }
});

test("off Vercel the environment comes from NODE_ENV", () => {
  delete process.env.VERCEL_ENV;
  // NODE_ENV is "test" under `node --test`, so this is the development branch.
  assert.equal(deploymentEnvironment(), "development");
  assert.equal(isIndexableDeployment(), false);
});

// ------------------------------------------------------------- serialisation

test("serializeJsonLd escapes anything that could close the script tag", () => {
  const json = serializeJsonLd({ description: "</script><img src=x onerror=alert(1)>" });
  assert.ok(!json.includes("</script>"), "raw </script> must not survive");
  assert.ok(!json.includes("<"), "no raw < in the output");
  assert.ok(!json.includes(">"), "no raw > in the output");
  assert.equal(JSON.parse(json).description, "</script><img src=x onerror=alert(1)>");
});

test("serializeJsonLd escapes ampersands and the JS line separators", () => {
  const json = serializeJsonLd({ a: "Bats & Balls", b: "one\u2028two\u2029three" });
  assert.ok(!json.includes("&"));
  assert.ok(!json.includes("\u2028"));
  assert.ok(!json.includes("\u2029"));
  const parsed = JSON.parse(json);
  assert.equal(parsed.a, "Bats & Balls");
  assert.equal(parsed.b, "one\u2028two\u2029three");
});

// ------------------------------------------------------ organization/website

test("Organization and WebSite share the @id the other nodes reference", () => {
  const org = buildOrganizationJsonLd();
  const site = buildWebSiteJsonLd();
  assert.equal(org["@type"], "Organization");
  assert.equal(org["@id"], "https://prosporter.com.au#organization");
  assert.equal(org.logo, "https://prosporter.com.au/brand/prosporter-logo.png");
  assert.equal(site.publisher["@id"], org["@id"]);
});

test("WebSite SearchAction points at /search?q=", () => {
  const site = buildWebSiteJsonLd();
  assert.equal(site.potentialAction["@type"], "SearchAction");
  assert.equal(
    site.potentialAction.target.urlTemplate,
    "https://prosporter.com.au/search?q={search_term_string}",
  );
  assert.equal(site.potentialAction["query-input"], "required name=search_term_string");
});

// ------------------------------------------------------------- breadcrumbs

test("BreadcrumbList numbers positions from 1 and absolutises paths", () => {
  const crumbs = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "Shop", path: "/shop" },
    { name: "Nago Jersey", path: "/product/nago" },
  ]);
  assert.equal(crumbs["@type"], "BreadcrumbList");
  assert.deepEqual(
    crumbs.itemListElement.map((item) => [item.position, item.item]),
    [
      [1, "https://prosporter.com.au"],
      [2, "https://prosporter.com.au/shop"],
      [3, "https://prosporter.com.au/product/nago"],
    ],
  );
});

test("a breadcrumb without a path omits `item` rather than emitting a bad URL", () => {
  const crumbs = buildBreadcrumbJsonLd([{ name: "Home", path: "/" }, { name: "Current" }]);
  assert.equal("item" in crumbs.itemListElement[1], false);
  assert.equal(crumbs.itemListElement[1].name, "Current");
});

// ---------------------------------------------------------------- product

const singleVariant = {
  path: "/product/nago",
  name: "Nago Jersey",
  description: "Lightweight indoor jersey.",
  images: ["https://cdn.shopify.com/s/files/1/nago.jpg", "/products/placeholder.svg"],
  brand: "ProSporter",
  sku: "NAGO-001",
  currency: "AUD",
  offers: [{ sku: "NAGO-001", price: 79.95, currency: "AUD", available: true }],
};

test("a one-variant product emits a single Offer with price, currency and availability", () => {
  const node = buildProductJsonLd(singleVariant);
  assert.equal(node["@context"], "https://schema.org");
  assert.equal(node["@type"], "Product");
  assert.equal(node.url, "https://prosporter.com.au/product/nago");
  assert.deepEqual(node.brand, { "@type": "Brand", name: "ProSporter" });
  assert.equal(node.sku, "NAGO-001");
  assert.deepEqual(node.image, [
    "https://cdn.shopify.com/s/files/1/nago.jpg",
    "https://prosporter.com.au/products/placeholder.svg",
  ]);
  assert.equal(node.offers["@type"], "Offer");
  assert.equal(node.offers.price, "79.95");
  assert.equal(node.offers.priceCurrency, "AUD");
  assert.equal(node.offers.availability, "https://schema.org/InStock");
  assert.equal(node.offers.url, "https://prosporter.com.au/product/nago");
});

test("a multi-variant product emits an AggregateOffer over the rendered range", () => {
  const node = buildProductJsonLd({
    ...singleVariant,
    sku: null,
    offers: [
      { sku: "A", price: 49.5, currency: "AUD", available: false },
      { sku: "B", price: 79.95, currency: "AUD", available: true },
      { sku: "C", price: 64, currency: "AUD", available: false },
    ],
  });
  assert.equal(node.offers["@type"], "AggregateOffer");
  assert.equal(node.offers.lowPrice, "49.50");
  assert.equal(node.offers.highPrice, "79.95");
  assert.equal(node.offers.offerCount, 3);
  // In stock while any variant is buyable, which is what the page shows.
  assert.equal(node.offers.availability, "https://schema.org/InStock");
  assert.equal("sku" in node, false);
});

test("with no variants the price range fallback is used and out-of-stock is honest", () => {
  const node = buildProductJsonLd({
    ...singleVariant,
    sku: null,
    brand: null,
    offers: [],
    priceRange: { min: 30, max: 45, available: false },
  });
  assert.equal(node.offers["@type"], "AggregateOffer");
  assert.equal(node.offers.lowPrice, "30.00");
  assert.equal(node.offers.highPrice, "45.00");
  assert.equal(node.offers.availability, "https://schema.org/OutOfStock");
  assert.equal("offerCount" in node.offers, false);
  assert.equal("brand" in node, false);
});

test("empty and missing product fields are dropped, not emitted blank", () => {
  const node = buildProductJsonLd({
    path: "/product/bare",
    name: "Bare",
    description: "   ",
    images: [],
    currency: "AUD",
    offers: [{ price: 10, currency: "AUD", available: true }],
  });
  for (const key of ["description", "image", "sku", "brand"]) {
    assert.equal(key in node, false, `${key} must be omitted`);
  }
  assert.equal("sku" in node.offers, false);
});

// ---------------------------------------------------------------- article

test("Article carries the byline name only and defaults dateModified to publishedAt", () => {
  const node = buildArticleJsonLd({
    path: "/blog/beach-kit",
    headline: "Packing for the beach season",
    description: "What to take to a sand tournament.",
    image: "https://cdn.shopify.com/s/files/1/beach.jpg",
    datePublished: "2026-01-05T00:00:00Z",
    authorName: "Sam Rivers",
  });
  assert.equal(node["@type"], "Article");
  assert.equal(node.url, "https://prosporter.com.au/blog/beach-kit");
  assert.deepEqual(node.mainEntityOfPage, {
    "@type": "WebPage",
    "@id": "https://prosporter.com.au/blog/beach-kit",
  });
  assert.deepEqual(node.author, { "@type": "Person", name: "Sam Rivers" });
  assert.equal(node.dateModified, "2026-01-05T00:00:00Z");
  assert.deepEqual(node.publisher, { "@id": "https://prosporter.com.au#organization" });
  assert.equal(JSON.stringify(node).includes("@"), true); // sanity: the @id keys are there
  assert.equal(/mailto:|@[a-z0-9-]+\.[a-z]{2,}/i.test(JSON.stringify(node.author)), false);
});

test("an article without a byline is published by the Organization", () => {
  const node = buildArticleJsonLd({ path: "/blog/x", headline: "X" });
  assert.deepEqual(node.author, { "@id": "https://prosporter.com.au#organization" });
  assert.equal("datePublished" in node, false);
});
