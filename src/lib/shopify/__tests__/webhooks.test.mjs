/**
 * Unit tests for the pure webhook helpers.
 *
 * Plain Node, zero dependencies: `npm test` (or `node --test
 * src/lib/shopify/__tests__/*.test.mjs`). Requires Node >= 22.18, which strips
 * the TypeScript types from the imported modules without a build step.
 */
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { test } from "node:test";

import { CACHE_TAGS } from "../tags.ts";
import { HANDLED_TOPICS, topicToTags, verifyShopifyHmac } from "../webhooks.ts";

const SECRET = "shpss_test_secret";
const sign = (body, secret = SECRET) =>
  createHmac("sha256", secret).update(Buffer.from(body, "utf8")).digest("base64");

test("verifyShopifyHmac accepts a correctly signed body", () => {
  const body = JSON.stringify({ id: 1, handle: "nago" });
  assert.equal(verifyShopifyHmac(body, sign(body), SECRET), true);
});

test("verifyShopifyHmac accepts raw bytes as well as a string", () => {
  const body = '{"handle":"ünïcødé"}';
  assert.equal(verifyShopifyHmac(Buffer.from(body, "utf8"), sign(body), SECRET), true);
});

test("verifyShopifyHmac rejects a body altered by a single byte", () => {
  const body = '{"handle":"nago"}';
  const signature = sign(body);
  assert.equal(verifyShopifyHmac('{"handle":"nagp"}', signature, SECRET), false);
});

test("verifyShopifyHmac rejects a signature made with a different secret", () => {
  const body = '{"handle":"nago"}';
  assert.equal(verifyShopifyHmac(body, sign(body, "other-secret"), SECRET), false);
});

test("verifyShopifyHmac rejects missing, empty and malformed headers", () => {
  const body = "{}";
  for (const header of [null, undefined, "", "   ", "not-base64!!", "c2hvcnQ="]) {
    assert.equal(verifyShopifyHmac(body, header, SECRET), false, `header ${String(header)}`);
  }
});

test("verifyShopifyHmac rejects when the secret is missing", () => {
  const body = "{}";
  assert.equal(verifyShopifyHmac(body, sign(body), ""), false);
});

test("verifyShopifyHmac tolerates surrounding whitespace in the header", () => {
  const body = '{"handle":"nago"}';
  assert.equal(verifyShopifyHmac(body, ` ${sign(body)} `, SECRET), true);
});

test("product topics map to the coarse tag plus the handle tag", () => {
  for (const topic of ["products/create", "products/update", "products/delete"]) {
    const plan = topicToTags(topic, { id: 7, handle: "nago" });
    assert.equal(plan.known, true);
    assert.equal(plan.handle, "nago");
    assert.deepEqual(plan.tags, [CACHE_TAGS.products, CACHE_TAGS.product("nago")]);
  }
});

test("a product delete without a handle still revalidates the coarse tag", () => {
  const plan = topicToTags("products/delete", { id: 7 });
  assert.equal(plan.known, true);
  assert.equal(plan.handle, null);
  assert.deepEqual(plan.tags, [CACHE_TAGS.products]);
});

test("collection topics map to the collection tags", () => {
  for (const topic of ["collections/create", "collections/update", "collections/delete"]) {
    const plan = topicToTags(topic, { handle: "accessories" });
    assert.deepEqual(plan.tags, [CACHE_TAGS.collections, CACHE_TAGS.collection("accessories")]);
  }
});

test("inventory topics drop the inventory and product caches", () => {
  for (const topic of ["inventory_levels/update", "inventory_items/update"]) {
    const plan = topicToTags(topic, { inventory_item_id: 12 });
    assert.equal(plan.known, true);
    assert.deepEqual(plan.tags, [CACHE_TAGS.inventory, CACHE_TAGS.products]);
  }
});

test("topics are normalised for case and whitespace", () => {
  const plan = topicToTags("  PRODUCTS/UPDATE ", { handle: "nago" });
  assert.equal(plan.topic, "products/update");
  assert.equal(plan.known, true);
});

test("unknown topics are a no-op", () => {
  for (const topic of ["orders/create", "", "app/uninstalled", "products"]) {
    const plan = topicToTags(topic, { handle: "nago" });
    assert.equal(plan.known, false, topic);
    assert.deepEqual(plan.tags, []);
  }
});

test("non-string and hostile handles are ignored", () => {
  for (const payload of [null, undefined, "a string", { handle: 42 }, { handle: "  " }, { handle: "x".repeat(300) }]) {
    const plan = topicToTags("products/update", payload);
    assert.equal(plan.handle, null);
    assert.deepEqual(plan.tags, [CACHE_TAGS.products]);
  }
});

test("HANDLED_TOPICS covers exactly the mapped topics", () => {
  assert.equal(HANDLED_TOPICS.length, 8);
  for (const topic of HANDLED_TOPICS) {
    assert.equal(topicToTags(topic, {}).known, true, topic);
  }
});
