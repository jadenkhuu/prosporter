/**
 * Pure cart maths for the drawer (CLNT-171).
 *
 * Deliberately free of runtime imports (only `import type`), so `node --test`
 * can load this module directly and so it is safe on both sides of the
 * server/client boundary.
 *
 * Shopify's cost model, for the record:
 *  - `cost.subtotalAmount` is the sum of the lines *before* cart-level
 *    discounts and taxes;
 *  - `discountAllocations` on the cart holds the cart-level (code and
 *    automatic) discounts;
 *  - `cost.totalAmount` is what the shopper actually pays, discounts applied.
 * So the drawer shows subtotal → discount → total, and never subtracts the
 * discount itself.
 */
import type { Cart } from "@/lib/shopify/types";

export type CartTotals = {
  currencyCode: string;
  /** Sum of the lines, before cart-level discounts. */
  subtotal: number;
  /** Cart-level discount, as a positive number. 0 when nothing is applied. */
  discount: number;
  /** What Shopify says the shopper pays. */
  total: number;
  hasDiscount: boolean;
};

/** Storefront money amounts are decimal strings; treat junk as 0. */
export function moneyAmount(money: { amount: string } | null | undefined): number {
  if (!money) return 0;
  const value = Number(money.amount);
  return Number.isFinite(value) ? value : 0;
}

/** Cart-level discount total, as a positive number. */
export function cartDiscountAmount(cart: Cart | null | undefined): number {
  if (!cart?.discountAllocations?.length) return 0;
  const total = cart.discountAllocations.reduce(
    (sum, allocation) => sum + moneyAmount(allocation?.discountedAmount),
    0,
  );
  return total > 0 ? total : 0;
}

/** Codes Shopify accepted for this cart. Rejected ones are dropped. */
export function appliedDiscountCodes(cart: Cart | null | undefined): string[] {
  return (cart?.discountCodes ?? []).filter((d) => d.applicable).map((d) => d.code);
}

export function cartTotals(cart: Cart | null | undefined, fallbackCurrency = "AUD"): CartTotals {
  const currencyCode = cart?.cost.subtotalAmount.currencyCode ?? fallbackCurrency;
  const subtotal = moneyAmount(cart?.cost.subtotalAmount);
  const discount = cartDiscountAmount(cart);
  // Fall back to subtotal − discount when Shopify has not costed the cart yet.
  const total = cart ? moneyAmount(cart.cost.totalAmount) : 0;
  return {
    currencyCode,
    subtotal,
    discount,
    total: total || Math.max(0, subtotal - discount),
    hasDiscount: discount > 0,
  };
}

/**
 * What the discount input actually submits: trimmed, inner whitespace removed
 * (shoppers paste "SUMMER 20"), and capped at the same 64 characters the server
 * action allows. Returns "" for anything that is not worth a round trip — the
 * caller uses that both to skip empty submits and, deliberately, to clear the
 * applied code.
 */
export function normalizeDiscountCode(input: string | null | undefined): string {
  if (typeof input !== "string") return "";
  return input.replace(/\s+/g, "").slice(0, 64);
}
