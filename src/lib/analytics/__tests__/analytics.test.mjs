/**
 * Unit tests for the pure halves of the GA4 slice (CLNT-179): the ecommerce
 * item builders and the `page_view` de-duplication rule.
 *
 * Plain Node, zero dependencies: `npm test` (or `node --test
 * src/lib/analytics/__tests__/*.test.mjs`). Requires Node >= 22.18, which
 * strips the TypeScript types from the imported modules without a build step —
 * which is also why neither module under test may import React or Next.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  addToCartParams,
  beginCheckoutParams,
  cartLineItem,
  findLineByVariant,
  itemsValue,
  productItem,
  round2,
  shortVariantId,
  viewItemParams,
} from "../items.ts";
import { nextPageView, pageViewPath } from "../page-view.ts";

// ------------------------------------------------------------------ fixtures

const product = {
  handle: "attack-jersey",
  title: "Attack Jersey",
  vendor: "ProSporter",
  price: 79.95,
  currency: "AUD",
  categoryLabel: "Jerseys",
};

const variant = {
  id: "gid://shopify/ProductVariant/4711",
  title: "Green / M",
  sku: "PS-AJ-GRN-M",
  available: true,
  price: 84.5,
  compareAtPrice: null,
  currency: "AUD",
  selectedOptions: [
    { name: "Colour", value: "Green" },
    { name: "Size", value: "M" },
  ],
  image: null,
};

function line({
  id = "gid://shopify/CartLine/1",
  variantId = "gid://shopify/ProductVariant/4711",
  sku = "PS-AJ-GRN-M",
  quantity = 2,
  price = "84.50",
  options = [
    { name: "Colour", value: "Green" },
    { name: "Size", value: "M" },
  ],
  title = "Attack Jersey",
  handle = "attack-jersey",
} = {}) {
  return {
    id,
    quantity,
    attributes: [],
    cost: {
      totalAmount: { amount: (Number(price) * quantity).toFixed(2), currencyCode: "AUD" },
      amountPerQuantity: { amount: price, currencyCode: "AUD" },
      compareAtAmountPerQuantity: null,
    },
    merchandise: {
      id: variantId,
      title: options.map((o) => o.value).join(" / "),
      sku,
      availableForSale: true,
      quantityAvailable: 9,
      selectedOptions: options,
      image: null,
      price: { amount: price, currencyCode: "AUD" },
      compareAtPrice: null,
      product: { id: "gid://shopify/Product/1", handle, title, featuredImage: null },
    },
  };
}

// --------------------------------------------------------------- small tools

test("round2 keeps money at two decimals and survives junk", () => {
  assert.equal(round2(84.499999), 84.5);
  assert.equal(round2(0.1 + 0.2), 0.3);
  assert.equal(round2(Number.NaN), 0);
});

test("shortVariantId reduces a Shopify gid to its numeric id", () => {
  assert.equal(shortVariantId("gid://shopify/ProductVariant/4711"), "4711");
  assert.equal(shortVariantId("4711"), "4711");
  assert.equal(shortVariantId(null), "");
});

// ------------------------------------------------------------- product items

test("productItem prefers the variant SKU as item_id", () => {
  const item = productItem(product, variant);
  assert.equal(item.item_id, "PS-AJ-GRN-M");
  assert.equal(item.item_name, "Attack Jersey");
  assert.equal(item.item_variant, "Green / M");
  assert.equal(item.item_brand, "ProSporter");
  assert.equal(item.item_category, "Jerseys");
  assert.equal(item.price, 84.5);
  assert.equal(item.quantity, 1);
  assert.equal(item.currency, "AUD");
});

test("productItem falls back to the numeric variant id, then to the handle", () => {
  assert.equal(productItem(product, { ...variant, sku: null }).item_id, "4711");
  assert.equal(productItem(product, { ...variant, sku: "  " }).item_id, "4711");
  assert.equal(productItem(product, null).item_id, "attack-jersey");
});

test("productItem uses product-level price when no variant is chosen", () => {
  const item = productItem(product, null);
  assert.equal(item.price, 79.95);
  assert.equal(item.item_variant, undefined);
});

test("productItem drops Shopify's Default Title placeholder", () => {
  const item = productItem(product, { ...variant, title: "Default Title" });
  assert.equal(item.item_variant, undefined);
});

test("productItem never emits a quantity below 1", () => {
  assert.equal(productItem(product, variant, 0).quantity, 1);
  assert.equal(productItem(product, variant, 3).quantity, 3);
});

test("viewItemParams is a one-item ecommerce payload with a matching value", () => {
  const params = viewItemParams(product, variant);
  assert.equal(params.currency, "AUD");
  assert.equal(params.value, 84.5);
  assert.equal(params.items.length, 1);
  assert.equal(params.coupon, undefined);
});

test("no builder leaks a personal-data field", () => {
  const payloads = [
    viewItemParams(product, variant),
    addToCartParams(line(), 1),
    beginCheckoutParams([line()], { coupon: "WINTER10" }),
  ];
  const forbidden = ["user_id", "email", "name", "phone", "address"];
  for (const payload of payloads) {
    for (const key of Object.keys(payload)) assert.ok(!forbidden.includes(key), key);
    for (const item of payload.items) {
      for (const key of Object.keys(item)) assert.ok(!forbidden.includes(key), key);
    }
  }
});

// ---------------------------------------------------------------- cart items

test("cartLineItem reads identity, variant label and unit price off the line", () => {
  const item = cartLineItem(line());
  assert.equal(item.item_id, "PS-AJ-GRN-M");
  assert.equal(item.item_name, "Attack Jersey");
  assert.equal(item.item_variant, "Green / M");
  assert.equal(item.price, 84.5);
  assert.equal(item.quantity, 2);
});

test("cartLineItem omits item_variant for a single-variant product", () => {
  const item = cartLineItem(
    line({ options: [{ name: "Title", value: "Default Title" }], sku: null }),
  );
  assert.equal(item.item_variant, undefined);
  assert.equal(item.item_id, "4711");
});

test("addToCartParams reports the quantity added, not the line total", () => {
  // The shopper adds one more of a line that already holds two.
  const params = addToCartParams(line({ quantity: 3 }), 1);
  assert.equal(params.items[0].quantity, 1);
  assert.equal(params.value, 84.5);
});

test("findLineByVariant matches on the merchandise id", () => {
  const lines = [line({ variantId: "gid://shopify/ProductVariant/1", sku: "A" }), line()];
  assert.equal(findLineByVariant(lines, "gid://shopify/ProductVariant/4711")?.merchandise.sku, "PS-AJ-GRN-M");
  assert.equal(findLineByVariant(lines, "gid://shopify/ProductVariant/999"), null);
});

test("itemsValue sums price x quantity", () => {
  assert.equal(itemsValue([cartLineItem(line()), cartLineItem(line({ price: "10.00", quantity: 3 }))]), 199);
  assert.equal(itemsValue([]), 0);
});

test("beginCheckoutParams carries every line, the coupon and the costed total", () => {
  const lines = [line(), line({ variantId: "gid://shopify/ProductVariant/2", sku: "B", quantity: 1, price: "10.00" })];
  const params = beginCheckoutParams(lines, { coupon: "WINTER10", value: 169, currency: "AUD" });
  assert.equal(params.items.length, 2);
  assert.equal(params.coupon, "WINTER10");
  // Overridden with Shopify's total, not the 179.00 the lines add up to.
  assert.equal(params.value, 169);
});

test("beginCheckoutParams omits coupon when none is applied and falls back to the line sum", () => {
  const params = beginCheckoutParams([line()]);
  assert.equal(params.coupon, undefined);
  assert.equal(params.value, 169);
  assert.equal(params.currency, "AUD");
});

test("beginCheckoutParams on an empty bag is still a valid payload", () => {
  const params = beginCheckoutParams([]);
  assert.deepEqual(params, { currency: "AUD", value: 0, items: [] });
});

// ------------------------------------------------------------ page_view rule

test("pageViewPath joins pathname and a non-empty query", () => {
  assert.equal(pageViewPath("/shop", ""), "/shop");
  assert.equal(pageViewPath("/shop", null), "/shop");
  assert.equal(pageViewPath("/shop", "colour=green"), "/shop?colour=green");
  assert.equal(pageViewPath("/shop", "?colour=green"), "/shop?colour=green");
  assert.equal(pageViewPath("shop"), "/shop");
});

test("the first page_view is sent even though config sends none", () => {
  assert.deepEqual(nextPageView(null, "/"), { url: "/", send: true });
});

test("a repeated location is not sent twice (re-render, Strict Mode, same-URL back)", () => {
  assert.deepEqual(nextPageView("/shop", "/shop"), { url: "/shop", send: false });
});

test("an SPA navigation is sent exactly once per distinct location", () => {
  const visits = ["/", "/", "/shop", "/shop?colour=green", "/shop?colour=green", "/shop", "/"];
  let previous = null;
  const sent = [];
  for (const url of visits) {
    const decision = nextPageView(previous, url);
    previous = decision.url;
    if (decision.send) sent.push(url);
  }
  assert.deepEqual(sent, ["/", "/shop", "/shop?colour=green", "/shop", "/"]);
});
