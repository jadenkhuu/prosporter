/**
 * Unit tests for the pure cart maths behind the drawer's discount row.
 *
 * Plain Node, zero dependencies: `npm test` (or `node --test
 * src/lib/__tests__/*.test.mjs`). Requires Node >= 22.18, which strips the
 * TypeScript types from the imported module without a build step.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  appliedDiscountCodes,
  cartDiscountAmount,
  cartTotals,
  moneyAmount,
  normalizeDiscountCode,
} from "../cart-totals.ts";

const money = (amount, currencyCode = "AUD") => ({ amount, currencyCode });

/** Only the fields the totals helpers read. */
const cart = ({ subtotal = "180.00", total = "180.00", allocations = [], codes = [] } = {}) => ({
  discountCodes: codes,
  discountAllocations: allocations.map((a) => ({ discountedAmount: money(a) })),
  cost: {
    subtotalAmount: money(subtotal),
    totalAmount: money(total),
    totalTaxAmount: null,
    totalDutyAmount: null,
  },
});

test("moneyAmount parses decimal strings and tolerates junk", () => {
  assert.equal(moneyAmount(money("12.50")), 12.5);
  assert.equal(moneyAmount(money("")), 0);
  assert.equal(moneyAmount(money("not-a-number")), 0);
  assert.equal(moneyAmount(null), 0);
  assert.equal(moneyAmount(undefined), 0);
});

test("cartDiscountAmount sums every cart-level allocation", () => {
  assert.equal(cartDiscountAmount(cart({ allocations: ["10.00", "5.50"] })), 15.5);
});

test("cartDiscountAmount is 0 with no allocations, and for a null cart", () => {
  assert.equal(cartDiscountAmount(cart()), 0);
  assert.equal(cartDiscountAmount(null), 0);
  assert.equal(cartDiscountAmount(undefined), 0);
});

test("cartTotals reports subtotal, discount and the discounted total", () => {
  const totals = cartTotals(cart({ subtotal: "180.00", total: "162.00", allocations: ["18.00"] }));
  assert.deepEqual(totals, {
    currencyCode: "AUD",
    subtotal: 180,
    discount: 18,
    total: 162,
    hasDiscount: true,
  });
});

test("cartTotals leaves the total alone when nothing is discounted", () => {
  const totals = cartTotals(cart({ subtotal: "180.00", total: "180.00" }));
  assert.equal(totals.discount, 0);
  assert.equal(totals.total, 180);
  assert.equal(totals.hasDiscount, false);
});

test("cartTotals falls back to subtotal − discount when Shopify has no total yet", () => {
  const totals = cartTotals(cart({ subtotal: "50.00", total: "0.00", allocations: ["5.00"] }));
  assert.equal(totals.total, 45);
});

test("cartTotals never returns a negative total", () => {
  const totals = cartTotals(cart({ subtotal: "10.00", total: "0", allocations: ["25.00"] }));
  assert.equal(totals.total, 0);
});

test("cartTotals on a null cart is zeroed and uses the fallback currency", () => {
  assert.deepEqual(cartTotals(null), {
    currencyCode: "AUD",
    subtotal: 0,
    discount: 0,
    total: 0,
    hasDiscount: false,
  });
  assert.equal(cartTotals(null, "NZD").currencyCode, "NZD");
});

test("appliedDiscountCodes drops the codes Shopify rejected", () => {
  const codes = [
    { code: "SUMMER20", applicable: true },
    { code: "NOPE", applicable: false },
  ];
  assert.deepEqual(appliedDiscountCodes(cart({ codes })), ["SUMMER20"]);
  assert.deepEqual(appliedDiscountCodes(null), []);
});

test("normalizeDiscountCode strips whitespace and caps the length", () => {
  assert.equal(normalizeDiscountCode("  SUMMER 20 "), "SUMMER20");
  assert.equal(normalizeDiscountCode("\tclub\ndeal"), "clubdeal");
  assert.equal(normalizeDiscountCode("   "), "");
  assert.equal(normalizeDiscountCode(""), "");
  assert.equal(normalizeDiscountCode(null), "");
  assert.equal(normalizeDiscountCode(undefined), "");
  assert.equal(normalizeDiscountCode("A".repeat(200)).length, 64);
});
